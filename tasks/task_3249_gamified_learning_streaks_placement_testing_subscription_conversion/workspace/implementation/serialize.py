"""Entity serialisation. Field names come verbatim from SCAFFOLD.yaml
entities[] and PRD 2.4; internal bookkeeping keys (leading underscore) are
stripped and derived counters are recomputed against the logical clock."""

from services import calc, common


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def learner(row, clock):
    hearts, energy, _gate, limits = calc.heart_and_energy(row, clock, persist=True)
    out = _public(row)
    out["hearts_available"] = hearts
    out["energy_units"] = energy
    return out


def streak(row, clock):
    return _public(row)


def unit(row):
    return _public(row)


def node(row):
    return _public(row)


def attempt(row):
    return _public(row)


def subscription(row, clock):
    out = _public(row)
    out["seats_used"] = len(
        [
            m
            for m in __import__("db").STORE.family_memberships.values()
            if m["subscription_id"] == row["id"] and m["status"] in ("INVITED", "ACTIVE")
        ]
    )
    out["limits_removed"] = bool(row["status"] == "ACTIVE" and row["plan_code"] != "FREE")
    if row.get("discount_pct") is not None:
        out["discount_pct"] = row["discount_pct"]
        out["total_due_cents"] = row.get("_total_due_cents")
    return out


def membership(row):
    return _public(row)


def placement(row):
    return _public(row)


def league(row):
    return _public(row)


def standing(row):
    return _public(row)


def exam(row):
    return _public(row)


def report(row):
    return _public(row)


def offer(row, clock):
    return _public(row)