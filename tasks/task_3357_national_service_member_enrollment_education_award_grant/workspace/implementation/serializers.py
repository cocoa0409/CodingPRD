"""Entity -> JSON-ready dict. Internal bookkeeping keys (prefixed '_') are hidden."""


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
