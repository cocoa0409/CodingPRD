"""Row -> JSON projection. Internal bookkeeping keys are prefixed with '_'."""


def serialize(row):
    if row is None:
        return {}
    return {k: v for k, v in row.items() if not k.startswith("_")}
