"""Serialization helpers: strip internal (_-prefixed) fields before output."""

import copy


def public(obj):
    """Return a shallow-copy dict with only public (non-underscore) keys."""
    return {k: copy.deepcopy(v) for k, v in obj.items() if not k.startswith("_")}


def public_list(objs):
    return [public(o) for o in objs]
