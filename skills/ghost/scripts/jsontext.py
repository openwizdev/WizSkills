import json


def pairs(seq):
    out = {}
    for key, value in seq:
        if not isinstance(key, str) or key in out:
            raise ValueError("bad object")
        out[key] = value
    return out


def load(text):
    if text.startswith("\ufeff") or "\x00" in text:
        raise ValueError("bad text")
    decoder = json.JSONDecoder(object_pairs_hook=pairs)
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError as error:
        raise ValueError("bad json") from error
    if text[end:].strip():
        raise ValueError("trailing")
    return value
