"""Serialization: entity dict -> JSON-safe dict with ISO timestamps."""
from db import iso


def _ser(ent):
    out = {}
    for k, v in ent.items():
        if hasattr(v, "strftime"):
            out[k] = iso(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def ser(ent):
    return _ser(ent) if ent is not None else None


def ser_many(items):
    return [_ser(e) for e in items]
