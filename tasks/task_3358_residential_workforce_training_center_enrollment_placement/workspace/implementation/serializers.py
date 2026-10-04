"""Entity -> public JSON dict. Computed fields are derived at read time."""
import domain
from db import STORE


def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def applicant_view(a):
    return _pub(a)


def application_view(ap):
    return _pub(ap)


def center_view(c):
    out = _pub(c)
    in_use = domain.center_beds_in_use(c["id"])
    out["beds_in_use"] = in_use
    out["beds_available"] = c["total_beds"] - in_use
    return out


def trade_program_view(t):
    out = _pub(t)
    enrolled = domain.program_enrolled_count(t["id"])
    out["enrolled_count"] = enrolled
    out["open_seats"] = t["capacity"] - enrolled
    out["status"] = domain.program_status(t)
    return out


def enrollment_view(e):
    domain.recompute_conduct_hold(e["id"])
    return _pub(e)


def dormitory_view(d):
    return _pub(d)


def incident_view(i):
    return _pub(i)


def credential_view(c):
    return _pub(c)


def agreement_view(a):
    out = _pub(a)
    out["status"] = domain.agreement_status(a)
    return out


def wbl_view(w):
    return _pub(w)


def plan_view(p):
    out = _pub(p)
    out["status"] = domain.plan_status(p)
    out["housing_stipend_cents"] = domain.plan_housing_stipend(p)
    out["transport_allowance_cents"] = domain.plan_transport_allowance(p)
    return out


def contract_view(c):
    return _pub(c)


def snapshot_view(s):
    out = _pub(s)
    out["graduation_rate"] = float(out["graduation_rate"])
    out["placement_rate"] = float(out["placement_rate"])
    return out
