"""Serialization filter.

Entities may carry internal bookkeeping keys (prefixed with `_`) that are not
part of the declared API surface; they are stripped from every response so the
payload carries exactly the fields the specification declares.
"""


def clean(entity):
    if isinstance(entity, dict):
        return {k: v for k, v in entity.items() if not k.startswith("_")}
    return entity


def clean_all(rows):
    return [clean(r) for r in rows]