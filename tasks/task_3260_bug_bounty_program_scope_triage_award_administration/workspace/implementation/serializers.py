"""Serializers: convert stored entities (dicts with internal keys prefixed
'_') into API output dicts."""
import db
import clock


def _clean(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def program_out(p):
    out = _clean(p)
    out["available_pool_cents"] = (
        p["bounty_pool_cents"] - p["bounty_reserved_cents"] - p["bounty_paid_cents"]
    )
    return out


def asset_out(a):
    return _clean(a)


def scope_version_out(v):
    return _clean(v)


def researcher_out(r):
    out = _clean(r)
    # reputation figures are refreshed on read
    from services import reputation as rep_svc

    rep_svc.refresh_reputation(r)
    out = _clean(r)
    return out


def invitation_out(i):
    return _clean(i)


def report_out(rep):
    """Include computed SLA breach flags."""
    out = _clean(rep)
    now = clock.now()
    due = rep.get("response_due_at")
    if due:
        due_dt = clock.parse_iso(due)
        first = rep.get("first_response_at")
        if first is None:
            out["response_breached"] = now > due_dt
        else:
            out["response_breached"] = clock.parse_iso(first) > due_dt
    else:
        out["response_breached"] = False
    rdue = rep.get("resolution_due_at")
    if rdue:
        rdue_dt = clock.parse_iso(rdue)
        res = rep.get("resolved_at")
        if res is None:
            out["resolution_breached"] = now > rdue_dt
        else:
            out["resolution_breached"] = clock.parse_iso(res) > rdue_dt
    else:
        out["resolution_breached"] = False
    return out


def award_out(a):
    return _clean(a)


def disclosure_out(d):
    return _clean(d)


def ticket_out(t):
    return _clean(t)
