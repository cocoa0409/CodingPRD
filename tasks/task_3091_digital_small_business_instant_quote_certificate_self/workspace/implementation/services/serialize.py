"""Serializers: entity dict -> API representation (internal keys stripped)."""

def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]


def sorted_by_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))
