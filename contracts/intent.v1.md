# Intent contract, version 1 (`openwiz.intent.v1`)

An intent file records who a project change serves and the goals, boundaries, reasons and costs that should guide later changes.

## Location

Commit each intent file at `docs/intent/<name>.md` in the project's repository. Name a spec's file `<spec number>-<short name>.md`, omitting the issue's `#` from the filename. Use a short name alone for a standing, product-wide intent.

## Form

Start with a Markdown level-one title (`# <title>`), then a `Spec: #<n>` line with the spec's issue number or `Spec: standing` for a standing intent. An optional `Paths:` line follows `Spec:`, before the sections. Blank lines may separate these parts.

After `Paths:`, list one or more backticked repository-relative files or folders, separated by a comma and space. Use forward slashes and whole path components. Absolute paths, `.` and `..` components, and glob patterns are invalid. A folder may end with a slash. Here is a synthetic example.

```markdown
Paths: `src/catalog/`, `config/catalog.toml`
```

Use these Markdown level-two headings exactly once, in this order.

1. **End user** describes who the work serves and what they need.
2. **Performance goals** states the performance the design should preserve.
3. **Security boundaries** states the access or data boundaries the design must respect.
4. **Why the optimizations exist** explains the reason for each relevant optimization.
5. **Cost concerns** states the resource or spending constraints the design should respect.

Each required section contains plain sentences or a single line `none: <reason>` with a nonempty reason. An empty section is invalid. An optional final level-two section, **Related**, lists references to ADRs and other intent files.

## Finding the intent for a change

Read the union of the following files from `docs/intent/`.

- Every intent file whose `Paths:` covers at least one changed path. A file entry matches that file exactly. A folder entry matches its descendants on a whole path component boundary. For example, the synthetic entry `src/catalog/` covers `src/catalog/index.txt`.
- The intent file of the ticket's own spec, identified by its `Spec: #<n>` line, even when its `Paths:` is absent or covers other paths.

An intent file without `Paths:` has no path matches. Read a file once when both rules select it.

## Changing intent

Amend an intent only through a reviewed pull request that identifies which sentence changes and explains why. Review the file change and its reason together. Never edit an intent file as a side effect of other work.

## Privacy

Use public-safe text only. Keep private records, people's words and machine details out of intent files and their examples.

## Fixtures

All examples in [`fixtures/intent/`](fixtures/intent/) are synthetic. The valid spec example exercises an omitted `Paths:`, a `none:` reason and `Related`. The valid standing example exercises both a folder and a file in `Paths:`. Each `invalid-*.md` filename names its one broken rule. The fixtures store sample Markdown bodies. Their filenames identify test cases.
