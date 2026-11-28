#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from itertools import combinations, product
from pathlib import Path

SCHEMAS = {
    "candidates": "openwiz.dream-cycle.link-candidates.v1",
    "check": "openwiz.dream-cycle.link-check.v1",
    "score": "openwiz.dream-cycle.link-score.v1",
    "ledger": "openwiz.dream-cycle.link-ledger.v1",
    "canaries": "openwiz.dream-cycle.link-canaries.v1",
}

CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}
ISSUE_REF_RE = re.compile(r"^([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)#([0-9]+)$")
FILE_REF_RE = re.compile(r"^([A-Za-z0-9._-]+/[A-Za-z0-9._-]+):([^#\s]+?)(?:#L([0-9]+)(?:-L?([0-9]+))?)?$")
TEXT_REF_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?::[^\s|`,)>\]]+|#[0-9]+)")
ISO_DATE_RE = re.compile(r"\b([0-9]{4}-[0-9]{2}-[0-9]{2})\b")
REPO_MENTION_RE = re.compile(r"\b([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)\b")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "dist", "build", "target"}
TEXT_EXTS = {
    ".md", ".txt", ".py", ".rs", ".js", ".ts", ".mjs", ".cjs", ".sh", ".json",
    ".jsonl", ".yaml", ".yml", ".toml", ".csv",
}
STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "will", "not",
    "are", "was", "were", "has", "had", "our", "its", "all", "one", "two", "but",
    "can", "may", "yet", "now", "new", "old", "fix", "open", "closed", "source",
    "metric", "value", "notes", "organization", "contact", "competitor", "promise",
    "owed", "uses", "defines", "mentions", "here", "line", "file", "repo",
}


class ReadError(Exception):
    pass


class InputError(Exception):
    pass


def _no_duplicates(pairs):
    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key: {key}")
        seen.add(key)
        out[key] = value
    return out


def parse_json_strict(raw):
    return json.loads(raw, object_pairs_hook=_no_duplicates)


def clean_line(text, cap=240):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return (text[: cap - 1] + "…" if len(text) > cap else text) or "unknown"


def parse_iso_date(text):
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise InputError(f"invalid ISO date: {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InputError(f"invalid ISO date: {text!r}") from exc


def today_iso(override=None):
    if override:
        return parse_iso_date(override).isoformat()
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def quote_matches(quote, text):
    if not isinstance(quote, str) or not quote or not isinstance(text, str):
        return False
    if quote in text:
        return True
    norm_q = " ".join(quote.split())
    norm_t = " ".join(text.split())
    return bool(norm_q) and norm_q in norm_t


def evidence_excerpt(text):
    normalised = " ".join(text.split())
    return next((part[:200].strip() for part in re.split(r"[\x00-\x1f\x7f]", normalised) if part.strip()), "")


def load_records(path):
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = parse_json_strict(stripped)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "candidates" in parsed and isinstance(parsed["candidates"], list):
                return parsed["candidates"]
            if isinstance(parsed, dict) and "\n" not in stripped:
                return [parsed]
        except ValueError:
            pass
    records = []
    for idx, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = parse_json_strict(line)
        except ValueError as exc:
            raise InputError(f"{path}:{idx}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise InputError(f"{path}:{idx}: expected JSON object")
        records.append(obj)
    return records


def load_settings(path):
    settings_path = Path(path).resolve()
    try:
        data = parse_json_strict(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"invalid settings {path}: {exc}") from exc
    if not isinstance(data, dict) or "repos" not in data:
        raise InputError(f"settings {path} must be a JSON object with 'repos'")
    base = settings_path.parent
    repos_raw = data["repos"]
    repos = {}
    if isinstance(repos_raw, dict):
        items = [{"name": k, "path": v} for k, v in repos_raw.items()]
    elif isinstance(repos_raw, list):
        items = repos_raw
    else:
        raise InputError("settings 'repos' must be a list or object")
    for item in items:
        if not isinstance(item, dict) or not item.get("name") or not item.get("path"):
            raise InputError("each repo entry requires 'name' and 'path'")
        rpath = Path(item["path"])
        if not rpath.is_absolute():
            rpath = (base / rpath).resolve()
        entry = {"name": item["name"], "path": rpath}
        for key in ("issues_file", "prs_file"):
            if item.get(key):
                fp = Path(item[key])
                if not fp.is_absolute():
                    fp = (base / fp).resolve()
                entry[key] = fp
        repos[item["name"]] = entry
    link_budget = int(data.get("link_budget", 50))
    max_per_entity = int(data.get("max_per_entity", 5))
    expire_days = int(data.get("expire_days", 30))
    if link_budget < 1:
        raise InputError("settings 'link_budget' must be >= 1")
    if max_per_entity < 1:
        raise InputError("settings 'max_per_entity' must be >= 1")
    if expire_days < 1:
        raise InputError("settings 'expire_days' must be >= 1")
    return {
        "repos": repos,
        "files": data.get("files") if isinstance(data.get("files"), dict) else {},
        "link_budget": link_budget,
        "max_per_entity": max_per_entity,
        "ubiquity_threshold": float(data.get("ubiquity_threshold", 0.6)),
        "expire_days": expire_days,
    }


class OrgStore:
    def __init__(self, settings):
        self.settings = settings
        self.unconfirmed = []
        self._unconfirmed_keys = set()
        self._repo_errors = {}
        self._issues = {}
        self._issue_errors = {}
        self._file_cache = {}
        self._validate_repos()

    def add_unconfirmed(self, source, reason):
        key = (source, reason)
        if key not in self._unconfirmed_keys:
            self._unconfirmed_keys.add(key)
            self.unconfirmed.append({"source": clean_line(source, 200), "reason": clean_line(reason, 240)})

    def _validate_repos(self):
        for name, info in self.settings["repos"].items():
            path = info["path"]
            if not path.is_dir():
                msg = f"repository path unreadable or missing: {path}"
                self._repo_errors[name] = msg
                self.add_unconfirmed(name, msg)
                continue
            try:
                list(os.scandir(path))
            except OSError as exc:
                msg = f"repository path unreadable: {exc}"
                self._repo_errors[name] = msg
                self.add_unconfirmed(name, msg)
                continue
            self._load_issue_like(name, info)

    def _load_issue_like(self, repo_name, info):
        combined = {}
        failures = []
        for key in ("issues_file", "prs_file"):
            fp = info.get(key)
            if not fp:
                continue
            try:
                rows = parse_json_strict(fp.read_text(encoding="utf-8"))
                if not isinstance(rows, list) or any(
                    not isinstance(row, dict) or type(row.get("number")) is not int for row in rows
                ):
                    raise ValueError("expected a JSON list of numbered records")
            except (OSError, ValueError) as exc:
                msg = f"{key} unreadable: {exc}"
                self.add_unconfirmed(f"{repo_name}:{key}", msg)
                failures.append(msg)
                continue
            for row in rows:
                combined[row["number"]] = row
        self._issues[repo_name] = combined
        if failures:
            self._issue_errors[repo_name] = "; ".join(failures)

    def repo_error(self, repo_name):
        return self._repo_errors.get(repo_name)

    def issues_for(self, repo_name):
        return self._issues.get(repo_name, {})

    def iter_files(self, repo_name):
        if repo_name in self._repo_errors:
            return
        info = self.settings["repos"][repo_name]
        root = info["path"]
        skip_files = {info[k].resolve() for k in ("issues_file", "prs_file") if info.get(k)}
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for fname in sorted(files):
                fpath = Path(folder) / fname
                if fpath.is_symlink() or fpath.resolve() in skip_files:
                    continue
                if fpath.suffix.lower() not in TEXT_EXTS:
                    continue
                rel = fpath.relative_to(root).as_posix()
                yield rel, fpath

    def read_file_lines(self, repo_name, rel):
        key = (repo_name, rel)
        if key in self._file_cache:
            return self._file_cache[key]
        if repo_name in self._repo_errors:
            raise ReadError(self._repo_errors[repo_name])
        root = self.settings["repos"][repo_name]["path"].resolve()
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise FileNotFoundError("path escapes repository root")
        if not target.is_file():
            raise FileNotFoundError(f"file not found: {rel}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReadError(f"cannot read {repo_name}:{rel}: {exc}") from exc
        lines = text.splitlines()
        self._file_cache[key] = (text, lines, target)
        return text, lines, target

    def resolve_end(self, ref):
        m_issue = ISSUE_REF_RE.fullmatch(ref)
        if m_issue:
            repo_name, num_s = m_issue.group(1), m_issue.group(2)
            num = int(num_s)
            if repo_name not in self.settings["repos"]:
                return "missing", f"unknown repository {repo_name}"
            if repo_name in self._repo_errors:
                return "unconfirmed", self._repo_errors[repo_name]
            issue = self._issues.get(repo_name, {}).get(num)
            if issue is None:
                if repo_name in self._issue_errors:
                    return "unconfirmed", self._issue_errors[repo_name]
                if not any(self.settings["repos"][repo_name].get(key) for key in ("issues_file", "prs_file")):
                    reason = "no issue or PR export configured"
                    self.add_unconfirmed(f"{repo_name}:issues", reason)
                    return "unconfirmed", reason
                return "missing", f"issue/PR #{num} not found in {repo_name}"
            state = str(issue.get("state", "open")).lower()
            if state != "open":
                return "closed", f"closed issue end: {ref} (state={state})"
            parts = [str(issue.get("title", "")), str(issue.get("body", ""))]
            for comment in issue.get("comments", []) or []:
                if isinstance(comment, dict) and comment.get("body"):
                    parts.append(str(comment["body"]))
                elif isinstance(comment, str):
                    parts.append(comment)
            return "ok", "\n".join(p for p in parts if p)

        m_file = FILE_REF_RE.fullmatch(ref)
        if m_file:
            repo_name, rel, l1, l2 = m_file.group(1), m_file.group(2), m_file.group(3), m_file.group(4)
            if repo_name not in self.settings["repos"]:
                return "missing", f"unknown repository {repo_name}"
            if repo_name in self._repo_errors:
                return "unconfirmed", self._repo_errors[repo_name]
            try:
                text, lines, _ = self.read_file_lines(repo_name, rel)
            except FileNotFoundError as exc:
                return "missing", f"missing end: {ref} ({exc})"
            except ReadError as exc:
                self.add_unconfirmed(f"{repo_name}:{rel}", str(exc))
                return "unconfirmed", str(exc)
            if l1 is None:
                return "ok", text
            start = int(l1)
            end = int(l2) if l2 is not None else start
            if start < 1 or end < start or end > len(lines):
                return "missing", f"missing end: {ref} (line range out of bounds, file has {len(lines)} lines)"
            return "ok", "\n".join(lines[start - 1 : end])

        return "missing", f"unrecognized ref format: {ref}"


def canonical_refs(ends):
    return tuple(sorted(str(e.get("ref", "")) for e in ends if isinstance(e, dict)))


def read_ledger_state(ledger_path):
    if not ledger_path or not Path(ledger_path).is_file():
        return [], {}, []
    entries = load_records(ledger_path)
    open_by_id = {}
    rejected = []
    for position, entry in enumerate(entries):
        eid = entry.get("id")
        if entry.get("invalid_at") is not None:
            if open_by_id.get(eid) == dict(entry, invalid_at=None):
                del open_by_id[eid]
        else:
            open_by_id[eid] = entry
            if entry.get("state") == "rejected":
                rejected.append((position, entry))
    return entries, open_by_id, rejected


def rejection_snapshot_path(ledger_path):
    return Path(str(ledger_path) + ".rejections.jsonl")


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def snapshot_rejection(store, position, entry):
    texts = {}
    for end in entry["ends"]:
        status, text = store.resolve_end(end["ref"])
        if status != "ok":
            return None
        texts[end["ref"]] = text
    return {"position": position, "entry": digest(entry), "content": digest(texts)}


def _matches_file_patterns(repo_name, rel, patterns):
    full = f"{repo_name}:{rel}"
    return any(fnmatch.fnmatch(full, pat) or fnmatch.fnmatch(rel, pat) for pat in patterns)


def _extract_declared_entities(store):
    entities = {}

    def add(name, category):
        cleaned = name.strip().strip("`*[]():,.")
        if len(cleaned) < 2:
            return
        key = cleaned.lower()
        if key in STOP_WORDS:
            return
        if key not in entities:
            entities[key] = (cleaned, category)

    for repo_name in store.settings["repos"]:
        add(repo_name, "repository")
        for num in store.issues_for(repo_name):
            add(f"{repo_name}#{num}", "issue")

    file_groups = store.settings["files"]
    for repo_name in store.settings["repos"]:
        if store.repo_error(repo_name):
            continue
        for rel, _ in store.iter_files(repo_name):
            try:
                text, lines, _ = store.read_file_lines(repo_name, rel)
            except (FileNotFoundError, ReadError) as exc:
                store.add_unconfirmed(f"{repo_name}:{rel}", str(exc))
                continue

            for line in lines:
                m_kv = re.match(r"^(Organization|Contact|Competitor|Person|Skill|Contract)\s*:\s*([A-Za-z0-9._-]+)", line)
                if m_kv:
                    add(m_kv.group(2), m_kv.group(1).lower())
                for m_ref in REPO_MENTION_RE.finditer(line):
                    if m_ref.group(1) in store.settings["repos"]:
                        add(m_ref.group(1), "repository")

            if _matches_file_patterns(repo_name, rel, file_groups.get("people", [])):
                add(Path(rel).stem, "person")
            if _matches_file_patterns(repo_name, rel, file_groups.get("competitors", [])):
                add(Path(rel).stem, "competitor")
            if _matches_file_patterns(repo_name, rel, file_groups.get("skills", [])):
                for line in lines:
                    m = re.match(r"^name\s*:\s*([A-Za-z0-9._-]+)", line)
                    if m:
                        add(m.group(1), "skill")
            if _matches_file_patterns(repo_name, rel, file_groups.get("contracts", [])):
                add(Path(rel).stem, "contract")
            if _matches_file_patterns(repo_name, rel, file_groups.get("money", [])):
                for line in lines:
                    m = re.match(r"^\s*-\s*\*\*([^*]+)\*\*", line)
                    if m:
                        add(m.group(1), "money")
            if _matches_file_patterns(repo_name, rel, file_groups.get("scoreboard", [])):
                for line in lines:
                    if line.startswith("|") and "---" not in line:
                        cells = [c.strip() for c in line.strip("|").split("|")]
                        if len(cells) >= 3 and cells[0].lower() != "metric":
                            add(cells[0], "scoreboard")

    return entities


def _changed_set(store, watermarks):
    if not watermarks:
        return None
    changed = set()
    for item in watermarks.get("read_since", []) or []:
        s = str(item)
        changed.add(s)
        changed.add(s.split("#L", 1)[0])
    wm_repos = watermarks.get("repos", {}) or {}
    for repo_name, info in store.settings["repos"].items():
        if store.repo_error(repo_name):
            continue
        wm = wm_repos.get(repo_name)
        if not wm:
            for rel, _ in store.iter_files(repo_name):
                changed.add(f"{repo_name}:{rel}")
            for num in store.issues_for(repo_name):
                changed.add(f"{repo_name}#{num}")
            continue

        if wm.get("commit"):
            try:
                proc = subprocess.run(
                    ["git", "diff", "--name-only", f"{wm['commit']}..HEAD"],
                    cwd=info["path"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode != 0:
                    store.add_unconfirmed(repo_name, f"git diff watermark failed: {proc.stderr.strip()}")
                else:
                    for rel in proc.stdout.splitlines():
                        if rel.strip():
                            changed.add(f"{repo_name}:{rel.strip()}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                store.add_unconfirmed(repo_name, f"git diff watermark failed: {exc}")

        if wm.get("since"):
            since_d = parse_iso_date(wm["since"])
            for rel, fpath in store.iter_files(repo_name):
                mtime_d = datetime.fromtimestamp(fpath.stat().st_mtime, timezone.utc).date()
                if mtime_d >= since_d:
                    changed.add(f"{repo_name}:{rel}")
            for num, issue in store.issues_for(repo_name).items():
                upd = str(issue.get("updated_at", ""))[:10]
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", upd):
                    if date.fromisoformat(upd) >= since_d:
                        changed.add(f"{repo_name}#{num}")
    return changed


def _token_overlap(text_a, text_b):
    toks_a = {w for w in re.findall(r"[a-z0-9][a-z0-9._-]{2,}", text_a.lower()) if w not in STOP_WORDS}
    toks_b = {w for w in re.findall(r"[a-z0-9][a-z0-9._-]{2,}", text_b.lower()) if w not in STOP_WORDS}
    return toks_a & toks_b


def _co_mentions(hits, changed):
    if changed == set():
        return
    by_repo = {}
    for hit in hits:
        recent, older = by_repo.setdefault(hit["repo"], ([], []))
        (recent if changed is None or hit["record"] in changed else older).append(hit)
    for (recent_a, older_a), (recent_b, older_b) in combinations(by_repo.values(), 2):
        yield from product(recent_a, recent_b)
        yield from product(recent_a, older_b)
        yield from product(older_a, recent_b)


def cmd_candidates(args):
    settings = load_settings(args.settings)
    store = OrgStore(settings)
    run_date = today_iso(args.date)
    watermarks = None
    if args.watermarks:
        try:
            watermarks = parse_json_strict(Path(args.watermarks).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InputError(f"invalid watermarks file: {exc}") from exc

    changed = _changed_set(store, watermarks)
    _, open_ledger, _ = read_ledger_state(args.ledger)
    linked_pairs = {
        canonical_refs(entry.get("ends", []))
        for entry in open_ledger.values()
        if entry.get("state") in ("accepted", "proposed", "later")
    }

    entities = _extract_declared_entities(store)
    total_records = 0
    entity_records = {k: [] for k in entities}
    patterns = {key: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])") for key in entities}

    for repo_name in sorted(store.settings["repos"]):
        if store.repo_error(repo_name):
            continue
        for rel, _ in store.iter_files(repo_name):
            try:
                text, lines, _ = store.read_file_lines(repo_name, rel)
            except (FileNotFoundError, ReadError) as exc:
                store.add_unconfirmed(f"{repo_name}:{rel}", str(exc))
                continue
            rec_key = f"{repo_name}:{rel}"
            total_records += 1
            low_text = text.lower()
            for ekey, pattern in patterns.items():
                if pattern.search(low_text):
                    for idx, ln in enumerate(lines, 1):
                        if pattern.search(ln.lower()):
                            entity_records[ekey].append({
                                "record": rec_key,
                                "repo": repo_name,
                                "ref": f"{rec_key}#L{idx}",
                                "quote": evidence_excerpt(ln),
                                "seen": run_date,
                            })
                            break

        for num, issue in sorted(store.issues_for(repo_name).items()):
            if str(issue.get("state", "open")).lower() != "open":
                continue
            rec_key = f"{repo_name}#{num}"
            title = str(issue.get("title", ""))
            body = str(issue.get("body", ""))
            full = f"{title}\n{body}".strip()
            seen = str(issue.get("updated_at", ""))[:10]
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", seen):
                seen = run_date
            total_records += 1
            low_text = full.lower()
            quote = evidence_excerpt(body if body.strip() else title)
            for ekey, pattern in patterns.items():
                if pattern.search(low_text):
                    entity_records[ekey].append({
                        "record": rec_key,
                        "repo": repo_name,
                        "ref": rec_key,
                        "quote": quote,
                        "seen": seen,
                    })

    total_records = max(total_records, 1)
    ubiq = settings["ubiquity_threshold"]
    entity_weights = {}
    for ekey, hits in entity_records.items():
        df = len({h["record"] for h in hits})
        if df == 0:
            entity_weights[ekey] = 0.0
        elif total_records >= 2 and (df / total_records) >= ubiq:
            entity_weights[ekey] = 0.0
        else:
            entity_weights[ekey] = math.log((total_records + 1) / (df + 1))

    raw_by_pair = {}

    def in_window(ref_a, ref_b):
        return changed is None or any(ref.split("#L", 1)[0] in changed for ref in (ref_a, ref_b))

    def register_pair(end_a, end_b, link_type, reason, ent_list, weight, fixed=False):
        if not end_a["quote"] or not end_b["quote"] or not in_window(end_a["ref"], end_b["ref"]):
            return
        pair_key = canonical_refs([end_a, end_b])
        if pair_key in linked_pairs:
            return
        ordered = sorted([end_a, end_b], key=lambda e: e["ref"])
        existing = raw_by_pair.get(pair_key)
        if existing is None:
            raw_by_pair[pair_key] = {
                "link_type": link_type,
                "reason": reason,
                "entities": list(dict.fromkeys(ent_list)),
                "rarity_score": round(weight, 4),
                "fixed": fixed,
                "ends": ordered,
            }
        else:
            for e in ent_list:
                if e not in existing["entities"]:
                    existing["entities"].append(e)
            if fixed and not existing["fixed"]:
                existing["link_type"] = link_type
                existing["reason"] = reason
                existing["fixed"] = True
            existing["rarity_score"] = round(existing["rarity_score"] + weight, 4)

    for ekey, hits in sorted(entity_records.items()):
        w = entity_weights.get(ekey, 0.0)
        if w <= 0.0:
            continue
        disp = entities[ekey][0]
        for a, b in _co_mentions(hits, changed):
            end_a = {key: a[key] for key in ("ref", "quote", "seen")}
            end_b = {key: b[key] for key in ("ref", "quote", "seen")}
            register_pair(end_a, end_b, "unknown", f"co-mention:{disp}", [disp], w)

    open_issues = []
    for repo_name in sorted(store.settings["repos"]):
        if store.repo_error(repo_name):
            continue
        for num, issue in sorted(store.issues_for(repo_name).items()):
            if str(issue.get("state", "open")).lower() != "open":
                continue
            seen = str(issue.get("updated_at", ""))[:10]
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", seen):
                seen = run_date
            title = str(issue.get("title", ""))
            body = str(issue.get("body", ""))
            open_issues.append({
                "repo": repo_name,
                "ref": f"{repo_name}#{num}",
                "text": f"{title}\n{body}",
                "quote": evidence_excerpt(body if body.strip() else title),
                "seen": seen,
            })

    file_groups = store.settings["files"]
    for repo_name in sorted(store.settings["repos"]):
        if store.repo_error(repo_name):
            continue
        for rel, _ in store.iter_files(repo_name):
            try:
                text, lines, _ = store.read_file_lines(repo_name, rel)
            except (FileNotFoundError, ReadError):
                continue

            if _matches_file_patterns(repo_name, rel, file_groups.get("promises", [])):
                stem = Path(rel).stem
                for idx, ln in enumerate(lines, 1):
                    if re.search(r"\b(promise|owed|will send|committed)\b", ln, re.IGNORECASE) or ln.lstrip().startswith("- [ ]"):
                        end_a = {"ref": f"{repo_name}:{rel}#L{idx}", "quote": evidence_excerpt(ln), "seen": run_date}
                        for iss in open_issues:
                            if in_window(end_a["ref"], iss["ref"]) and _token_overlap(f"{stem} {ln}", iss["text"]):
                                end_b = {"ref": iss["ref"], "quote": iss["quote"], "seen": iss["seen"]}
                                register_pair(end_a, end_b, "promise-to-work", "fixed:promise-to-open-issue", [stem], 3.0, fixed=True)

            if _matches_file_patterns(repo_name, rel, file_groups.get("competitors", [])):
                stem = Path(rel).stem
                dated = []
                for idx, ln in enumerate(lines, 1):
                    m_d = ISO_DATE_RE.search(ln)
                    if m_d:
                        dated.append((m_d.group(1), idx, ln))
                if dated:
                    dated.sort(key=lambda t: (t[0], t[1]))
                    move_date, idx, ln = dated[-1]
                    end_a = {"ref": f"{repo_name}:{rel}#L{idx}", "quote": evidence_excerpt(ln), "seen": move_date}
                    for iss in open_issues:
                        if in_window(end_a["ref"], iss["ref"]) and _token_overlap(f"{stem} {ln}", iss["text"]):
                            end_b = {"ref": iss["ref"], "quote": iss["quote"], "seen": iss["seen"]}
                            register_pair(end_a, end_b, "enemy-move-to-us", "fixed:competitor-move-to-open-ticket", [stem], 2.5, fixed=True)

            if _matches_file_patterns(repo_name, rel, file_groups.get("scoreboard", [])):
                for idx, ln in enumerate(lines, 1):
                    row_ref = f"{repo_name}:{rel}#L{idx}"
                    for m_ref in TEXT_REF_RE.finditer(ln):
                        target_ref = m_ref.group(0)
                        if not in_window(row_ref, target_ref):
                            continue
                        status, target_text = store.resolve_end(target_ref)
                        if status == "ok":
                            end_a = {"ref": row_ref, "quote": evidence_excerpt(ln), "seen": run_date}
                            end_b = {"ref": target_ref, "quote": evidence_excerpt(target_text), "seen": run_date}
                            register_pair(end_a, end_b, "says-vs-does", "fixed:scoreboard-to-source", ["scoreboard"], 3.0, fixed=True)

    ranked = sorted(
        raw_by_pair.values(),
        key=lambda c: (
            0 if c["fixed"] else 1,
            -c["rarity_score"],
            -int(max(e["seen"] for e in c["ends"]).replace("-", "")),
            canonical_refs(c["ends"]),
        )
    )

    max_per_entity = settings["max_per_entity"]
    budget = settings["link_budget"]
    entity_counts = {}
    emitted = []
    capped = 0
    for index, item in enumerate(ranked):
        if len(emitted) >= budget:
            capped += len(ranked) - index
            break
        ents = [e.lower() for e in item["entities"]]
        if any(entity_counts.get(e, 0) >= max_per_entity for e in ents):
            capped += 1
            continue
        for e in ents:
            entity_counts[e] = entity_counts.get(e, 0) + 1
        emitted.append({
            "id": f"cand-{len(emitted) + 1:03d}",
            "link_type": item["link_type"],
            "reason": item["reason"],
            "entities": item["entities"],
            "rarity_score": item["rarity_score"],
            "ends": item["ends"],
        })

    out = {
        "schema": SCHEMAS["candidates"],
        "candidates": emitted,
        "counts": {
            "entities": len(entities),
            "raw_pairs": len(raw_by_pair),
            "emitted": len(emitted),
            "capped": capped,
        },
        "unconfirmed": store.unconfirmed,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 2 if store.unconfirmed else 0


def cmd_check(args):
    settings = load_settings(args.settings)
    store = OrgStore(settings)
    candidates = load_records(args.candidates_file)
    _, open_ledger, rejected_entries = read_ledger_state(args.ledger)
    snapshots = {}
    if args.ledger:
        path = rejection_snapshot_path(args.ledger)
        if path.exists():
            for row in load_records(path):
                if not isinstance(row, dict) or type(row.get("position")) is not int or any(
                    not isinstance(row.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", row[field])
                    for field in ("entry", "content")
                ):
                    raise InputError(f"invalid rejection snapshot in {path}")
                snapshots[row["position"], row["entry"]] = row["content"]

    active_by_refs = {}
    for entry in open_ledger.values():
        if entry.get("state") in ("accepted", "proposed", "later"):
            active_by_refs[canonical_refs(entry.get("ends", []))] = entry

    rejected_by_refs = {}
    for position, entry in rejected_entries:
        snapshot = snapshots.get((position, digest(entry)))
        rejected_by_refs.setdefault(canonical_refs(entry.get("ends", [])), []).append((entry, snapshot))

    passed = []
    dropped = []

    for idx, cand in enumerate(candidates, 1):
        cid = str(cand.get("id") or f"line-{idx}")
        changes = cand.get("changes")
        if not isinstance(changes, str) or not changes.strip():
            dropped.append({"id": cid, "reason": "empty changes: changes must be filled"})
            continue

        ends = cand.get("ends")
        min_ends = 3 if cand.get("link_type") == "pattern" else 2
        if not isinstance(ends, list) or len(ends) < min_ends:
            dropped.append({"id": cid, "reason": f"invalid ends: expected at least {min_ends} ends"})
            continue
        if cand.get("link_type") and cand.get("link_type") != "pattern" and len(ends) != 2:
            dropped.append({"id": cid, "reason": "invalid ends: non-pattern link must have exactly 2 ends"})
            continue

        resolved_texts = {}
        drop_reason = None
        for end in ends:
            if not isinstance(end, dict) or not end.get("ref") or not end.get("quote"):
                drop_reason = "invalid end: ref and quote are required"
                break
            ref = str(end["ref"])
            status, payload = store.resolve_end(ref)
            if status == "unconfirmed":
                drop_reason = f"unconfirmed end: {ref} ({payload})"
                break
            if status == "closed":
                drop_reason = payload
                break
            if status != "ok":
                drop_reason = payload
                break
            if not quote_matches(end["quote"], payload):
                drop_reason = f"quote not found verbatim in {ref}"
                break
            resolved_texts[ref] = payload

        if drop_reason:
            dropped.append({"id": cid, "reason": drop_reason})
            continue

        pair_key = canonical_refs(ends)
        if pair_key in active_by_refs:
            existing = active_by_refs[pair_key]
            dropped.append({
                "id": cid,
                "reason": f"already linked in ledger ({existing.get('id')}, state={existing.get('state')})",
            })
            continue

        prior_rejects = rejected_by_refs.get(pair_key, [])
        repeat_hit = None
        current_content = digest(resolved_texts) if prior_rejects else None
        quotes = {end["ref"]: end["quote"] for end in ends}
        for rej, snapshot in prior_rejects:
            rej_ends = rej.get("ends", [])
            unchanged = snapshot == current_content if snapshot is not None else all(
                quote_matches(quotes.get(end["ref"], ""), end.get("quote", ""))
                and quote_matches(end.get("quote", ""), resolved_texts.get(end["ref"], ""))
                for end in rej_ends
            )
            if rej_ends and unchanged:
                repeat_hit = rej
                break
        if repeat_hit is not None:
            dropped.append({
                "id": cid,
                "reason": f"repeat rejection: matches rejected link {repeat_hit.get('id')} with unchanged end content",
            })
            continue

        passed.append(cand)

    if args.out:
        Path(args.out).write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in passed),
            encoding="utf-8",
        )
    out = {
        "schema": SCHEMAS["check"],
        "passed": passed,
        "dropped": dropped,
        "counts": {"input": len(candidates), "passed": len(passed), "dropped": len(dropped)},
        "unconfirmed": store.unconfirmed,
    }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 2 if store.unconfirmed else 0


def validate_link_verdict(verdict_obj):
    v = verdict_obj.get("verdict")
    if v not in ("CONFIRMED", "PLAUSIBLE", "REJECTED"):
        return f"invalid verdict {v!r}"
    cc = verdict_obj.get("changes_confirmed")
    if v == "CONFIRMED" and cc is not True:
        return "CONFIRMED link verdict requires changes_confirmed: true (got null or false)"
    return None


def compute_impact(link):
    if "impact" in link and type(link["impact"]) is int and 0 <= link["impact"] <= 3:
        return link["impact"]
    changes = str(link.get("changes", ""))
    what = str(link.get("what", ""))
    if not changes.strip():
        return 0
    combined = f"{changes} {what}".lower()
    link_type = str(link.get("link_type", ""))
    route = str(link.get("route", ""))
    ends = link.get("ends", []) or []

    if (
        re.search(r"\bone-way door\b", combined)
        or link_type == "promise-to-work"
        or (link_type == "says-vs-does" and any(
            re.search(r"(?:[:/])scoreboard\b", str(end.get("ref", "")).lower()) for end in ends
        ))
    ):
        return 3
    if (
        (route == "ticket" and isinstance(link.get("ticket"), str) and link["ticket"].strip())
        or any(ISSUE_REF_RE.fullmatch(str(e.get("ref", ""))) for e in ends)
    ):
        return 2
    return 1


def cmd_score(args):
    links = load_records(args.links_file)
    verdicts_by_id = {}
    if args.verdicts:
        for v in load_records(args.verdicts):
            if isinstance(v, dict) and v.get("id"):
                verdicts_by_id[v["id"]] = v

    scored = []
    dropped = []
    for idx, link in enumerate(links, 1):
        lid = str(link.get("id") or f"line-{idx}")
        verdict_obj = verdicts_by_id.get(lid)
        if verdict_obj is not None:
            v_err = validate_link_verdict(verdict_obj)
            if v_err:
                dropped.append({"id": lid, "reason": v_err})
                continue
            if verdict_obj["verdict"] == "REJECTED":
                dropped.append({"id": lid, "reason": f"verdict REJECTED: {verdict_obj.get('reason', '')}"})
                continue

        impact = compute_impact(link)
        if impact == 0:
            dropped.append({"id": lid, "reason": "impact is 0"})
            continue

        sources = link.get("sources")
        if type(sources) is not int or sources < 1:
            repos = {str(e.get("ref", "")).split(":", 1)[0].split("#", 1)[0] for e in link.get("ends", []) if isinstance(e, dict)}
            sources = max(len([r for r in repos if r]), 1)

        conf_name = str(link.get("confidence", "low"))
        conf_w = CONFIDENCE_WEIGHT.get(conf_name)
        if conf_w is None:
            dropped.append({"id": lid, "reason": f"unknown confidence: {conf_name!r}"})
            continue

        total = impact * sources * conf_w
        ends = link.get("ends", []) or []
        newest = max((str(e.get("seen", "0000-00-00")) for e in ends if isinstance(e, dict)), default="0000-00-00")

        entry = dict(link)
        entry["impact"] = impact
        entry["score"] = total
        entry["newest_evidence"] = newest
        if verdict_obj is not None:
            entry["verdict"] = verdict_obj["verdict"]
        scored.append(entry)

    scored.sort(key=lambda item: (-item["score"], -int(item["newest_evidence"].replace("-", "") or 0), item.get("id", "")))

    out = {
        "schema": SCHEMAS["score"],
        "scored": scored,
        "dropped": dropped,
        "counts": {"input": len(links), "scored": len(scored), "dropped": len(dropped)},
        "unconfirmed": [],
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


LEDGER_STATES = {"proposed", "accepted", "rejected", "later", "expired", "superseded"}
REASON_REQUIRED_STATES = {"rejected", "later", "expired", "superseded"}
LINK_TYPES = {
    "says-vs-does", "promise-to-work", "need-to-person", "enemy-move-to-us", "spend-to-use",
    "answers", "pattern", "duplicates", "drifted-copy", "contradicts", "unknown",
}
LEDGER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _line_ok(value, required=True):
    return isinstance(value, str) and len(value) <= 500 and (
        not required or bool(value.strip())
    ) and not re.search(r"[\x00-\x1f\x7f]", value)


def _validate_ledger_entry(entry):
    required = {"id", "state", "link_type", "ends", "changes", "owner",
                "valid_from", "invalid_at", "reason", "superseded_by", "last_cited"}
    if set(entry) != required:
        raise InputError("invalid ledger entry fields")
    eid, state, link_type = entry["id"], entry["state"], entry["link_type"]
    if not isinstance(eid, str) or not LEDGER_ID_RE.fullmatch(eid):
        raise InputError("invalid ledger id")
    if not isinstance(state, str) or state not in LEDGER_STATES:
        raise InputError(f"invalid ledger state for {eid}")
    if not isinstance(link_type, str) or link_type not in LINK_TYPES:
        raise InputError(f"invalid ledger link_type for {eid}")
    ends = entry["ends"]
    if not isinstance(ends, list) or (len(ends) < 3 if link_type == "pattern" else len(ends) != 2):
        raise InputError(f"invalid ledger ends for {eid}")
    for end in ends:
        if not isinstance(end, dict) or set(end) != {"ref", "quote", "seen"}:
            raise InputError(f"invalid ledger end fields for {eid}")
        ref = end["ref"]
        if not isinstance(ref, str) or not re.fullmatch(r"[^\s\x00-\x1f\x7f]{1,300}", ref) or not _line_ok(end["quote"]):
            raise InputError(f"invalid ledger end ref or quote for {eid}")
        parse_iso_date(end["seen"])
    if not all(_line_ok(entry[key]) for key in ("changes", "owner")):
        raise InputError(f"ledger entry requires non-empty changes and owner for {eid}")
    if not _line_ok(entry["reason"], required=state in REASON_REQUIRED_STATES):
        raise InputError(f"invalid ledger reason for {eid}")
    successor = entry["superseded_by"]
    if state == "superseded":
        if not isinstance(successor, str) or not LEDGER_ID_RE.fullmatch(successor):
            raise InputError(f"ledger entry requires a valid superseded_by for {eid}")
    elif successor is not None:
        raise InputError(f"only a superseded ledger entry can name superseded_by for {eid}")
    parse_iso_date(entry["valid_from"])
    for field in ("last_cited", "invalid_at"):
        if entry[field] is not None:
            parse_iso_date(entry[field])


def _append_transition(open_by_id, lines_to_append, record, run_date):
    eid = record["id"]
    if not isinstance(eid, str):
        raise InputError("invalid ledger id")
    prev = open_by_id.get(eid, {})
    new_entry = {
        "id": eid,
        "state": record["state"],
        "link_type": record.get("link_type", prev.get("link_type", "unknown")),
        "ends": record.get("ends", prev.get("ends", [])),
        "changes": record.get("changes", prev.get("changes", "")),
        "owner": record.get("owner", prev.get("owner", "")),
        "valid_from": run_date,
        "invalid_at": None,
        "reason": record.get("reason", ""),
        "superseded_by": record.get("superseded_by"),
        "last_cited": record.get("last_cited", prev.get("last_cited")),
    }
    _validate_ledger_entry(new_entry)
    if prev:
        closed = dict(prev, invalid_at=run_date)
        _validate_ledger_entry(closed)
        lines_to_append.append(closed)
    lines_to_append.append(new_entry)
    open_by_id[eid] = new_entry
    return new_entry


def _append_records(path, rows):
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a+b") as fh:
            prefix = b""
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    prefix = b"\n"
            fh.write(prefix + payload)
    except OSError as exc:
        raise InputError(f"cannot append to {path}: {exc}") from exc


def cmd_ledger(args):
    ledger_path = Path(args.ledger)
    run_date = today_iso(args.date)
    run_d = date.fromisoformat(run_date)
    entries, open_by_id, _ = read_ledger_state(ledger_path)

    lines_to_append = []
    rejected_verdicts = []
    rejected_verdict_ids = set()
    expired = []
    kept = []
    if args.recheck and not args.settings:
        raise InputError("--recheck requires --settings")
    settings = load_settings(args.settings) if args.settings else None
    store = OrgStore(settings) if settings is not None else None
    snapshots = []

    if args.verdicts:
        for v in load_records(args.verdicts):
            err = validate_link_verdict(v)
            if err:
                vid = str(v.get("id", ""))
                rejected_verdicts.append({"id": vid, "reason": err})
                rejected_verdict_ids.add(vid)

    if args.append:
        for tr in load_records(args.append):
            if not isinstance(tr, dict) or not tr.get("id") or not tr.get("state"):
                raise InputError("each ledger transition requires 'id' and 'state'")
            if tr.get("state") == "accepted" and str(tr["id"]) in rejected_verdict_ids:
                continue
            entry = _append_transition(open_by_id, lines_to_append, tr, run_date)
            if entry["state"] == "rejected" and store is not None:
                snapshot = snapshot_rejection(store, len(entries) + len(lines_to_append) - 1, entry)
                if snapshot is not None:
                    snapshots.append(snapshot)

    if args.recheck:
        expire_days = args.expire_days if args.expire_days is not None else settings["expire_days"]

        for eid, entry in sorted(list(open_by_id.items())):
            if entry.get("state") != "accepted":
                continue

            ref_date_s = entry.get("last_cited") or entry.get("valid_from")
            ref_d = parse_iso_date(ref_date_s)
            expire_reason = None
            if (run_d - ref_d).days >= expire_days:
                expire_reason = f"Not cited in {expire_days} days (last_cited={ref_date_s})."

            has_unconfirmed = False
            for end in entry.get("ends", []):
                ref = str(end.get("ref", ""))
                status, payload = store.resolve_end(ref)
                if status == "unconfirmed":
                    has_unconfirmed = True
                    break
                if status != "ok":
                    expire_reason = expire_reason or f"End no longer resolves: {ref} ({payload})."
                elif not quote_matches(end.get("quote", ""), payload):
                    expire_reason = expire_reason or f"Quote no longer found in {ref}."

            if has_unconfirmed:
                kept.append(eid)
            elif expire_reason:
                expire_reason = clean_line(expire_reason, 500)
                _append_transition(open_by_id, lines_to_append, {"id": eid, "state": "expired", "reason": expire_reason}, run_date)
                expired.append({"id": eid, "reason": expire_reason})
            else:
                kept.append(eid)
    if snapshots:
        _append_records(rejection_snapshot_path(ledger_path), snapshots)
    if lines_to_append:
        _append_records(ledger_path, lines_to_append)

    unconfirmed = store.unconfirmed if store is not None else []
    out = {
        "schema": SCHEMAS["ledger"],
        "appended": len(lines_to_append),
        "expired": expired,
        "kept": kept,
        "rejected_verdicts": rejected_verdicts,
        "unconfirmed": unconfirmed,
    }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 2 if unconfirmed else 0


def cmd_canaries(args):
    _, open_by_id, _ = read_ledger_state(args.ledger)
    unconfirmed = []
    store = None
    if args.settings:
        store = OrgStore(load_settings(args.settings))
        unconfirmed = store.unconfirmed

    true_pool = []
    junk_pool = []
    for eid, entry in sorted(open_by_id.items()):
        state = entry.get("state")
        if state not in ("accepted", "rejected"):
            continue
        try:
            _validate_ledger_entry(entry)
        except InputError as exc:
            unconfirmed.append({"source": clean_line(f"ledger:{eid}", 200), "reason": clean_line(exc)})
            continue
        if state == "accepted":
            if store is not None:
                ok = True
                for end in entry.get("ends", []):
                    st, payload = store.resolve_end(str(end.get("ref", "")))
                    if st != "ok" or not quote_matches(end.get("quote", ""), payload):
                        ok = False
                        break
                if not ok:
                    continue
            true_pool.append(entry)
        elif state == "rejected":
            junk_pool.append(entry)

    rng = random.Random(args.seed) if args.seed is not None else random.Random(0)
    picked_true = rng.sample(true_pool, min(args.true_count, len(true_pool))) if true_pool else []
    picked_junk = rng.sample(junk_pool, min(args.junk_count, len(junk_pool))) if junk_pool else []

    def shape(entry, expected_verdict):
        return {
            "id": entry["id"],
            "expected_verdict": expected_verdict,
            "link_type": entry["link_type"],
            "ends": entry["ends"],
            "changes": entry["changes"],
            "owner": entry["owner"],
        }

    out = {
        "schema": SCHEMAS["canaries"],
        "known_true": [shape(e, "CONFIRMED") for e in picked_true],
        "known_junk": [shape(e, "REJECTED") for e in picked_junk],
        "counts": {
            "known_true": len(picked_true),
            "known_junk": len(picked_junk),
            "available_true": len(true_pool),
            "available_junk": len(junk_pool),
        },
        "unconfirmed": unconfirmed,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 2 if unconfirmed else 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"links.py: {message}", file=sys.stderr)
        sys.exit(1)


def non_negative(text):
    val = int(text)
    if val < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {val}")
    return val


def main(argv=None):
    parser = Parser(
        prog="links.py",
        description="Dream-cycle link funnel: candidates, Gate A check, score, ledger, and canaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cand_p = sub.add_parser("candidates", help="Build entity index, pair cross-repo entities and fixed pairings.")
    cand_p.add_argument("--settings", required=True, help="Path to organization settings JSON.")
    cand_p.add_argument("--ledger", help="Optional path to existing link ledger JSONL.")
    cand_p.add_argument("--watermarks", help="Optional path to per-repo watermarks JSON.")
    cand_p.add_argument("--date", help="Run date (YYYY-MM-DD, default: today UTC).")
    cand_p.add_argument("--out", help="Optional output path for candidates JSON.")

    chk_p = sub.add_parser("check", help="Gate A program check on candidate links.")
    chk_p.add_argument("candidates_file", help="Path to candidate links JSONL or JSON.")
    chk_p.add_argument("--settings", required=True, help="Path to organization settings JSON.")
    chk_p.add_argument("--ledger", help="Optional path to link ledger JSONL.")
    chk_p.add_argument("--out", help="Optional output path for surviving links JSONL.")

    sc_p = sub.add_parser("score", help="Score links (impact * sources * confidence) with newest-evidence tie-break.")
    sc_p.add_argument("links_file", help="Path to links JSONL or JSON.")
    sc_p.add_argument("--verdicts", help="Optional path to prover verdicts JSONL.")
    sc_p.add_argument("--out", help="Optional output path for scored links JSON.")

    led_p = sub.add_parser("ledger", help="Append state changes, re-check accepted links, and expire stale links.")
    led_p.add_argument("--ledger", required=True, help="Path to append-only link ledger JSONL.")
    led_p.add_argument("--settings", help="Organization settings for rechecks and rejected-end snapshots (required for --recheck).")
    led_p.add_argument("--append", help="Optional JSONL/JSON of state transitions to append.")
    led_p.add_argument("--verdicts", help="Optional prover verdicts JSONL to validate.")
    led_p.add_argument("--recheck", action="store_true", help="Re-check accepted links and expire stale or broken ones.")
    led_p.add_argument("--expire-days", type=non_negative, help="Days without citation before expiry (default: 30).")
    led_p.add_argument("--date", help="Run date (YYYY-MM-DD, default: today UTC).")

    can_p = sub.add_parser("canaries", help="Pick known-true and known-junk seed links from the ledger.")
    can_p.add_argument("--ledger", required=True, help="Path to link ledger JSONL.")
    can_p.add_argument("--settings", help="Optional settings JSON to verify known-true ends resolve.")
    can_p.add_argument("--true-count", type=non_negative, default=2, help="Number of known-true seeds (default: 2).")
    can_p.add_argument("--junk-count", type=non_negative, default=2, help="Number of known-junk seeds (default: 2).")
    can_p.add_argument("--seed", help="Deterministic selection seed (for example YYYY-MM-DD).")
    can_p.add_argument("--out", help="Optional output path for canaries JSON.")

    args = parser.parse_args(argv)
    handlers = {
        "candidates": cmd_candidates,
        "check": cmd_check,
        "score": cmd_score,
        "ledger": cmd_ledger,
        "canaries": cmd_canaries,
    }
    try:
        return handlers[args.command](args)
    except InputError as exc:
        print(f"links.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
