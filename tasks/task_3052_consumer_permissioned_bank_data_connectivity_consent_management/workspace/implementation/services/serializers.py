"""Serialize internal entity dicts to API output (strip internal _-prefixed keys,
inject computed fields like connectivity_mode)."""

from services import core


def _clean(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def institution_out(inst):
    d = _clean(inst)
    d["connectivity_mode"] = core.connectivity_mode(inst)
    return d


def recipient_out(r):
    return _clean(r)


def consent_out(c):
    return _clean(c)


def connection_out(c):
    return _clean(c)


def agreement_out(a):
    return _clean(a)


def tier_out(t):
    return _clean(t)


def tier_assignment_out(ta):
    return _clean(ta)


def refresh_job_out(j):
    return _clean(j)


def webhook_out(w):
    return _clean(w)


def breakage_out(b):
    return _clean(b)


def deletion_request_out(dr):
    return _clean(dr)


def grant_out(g):
    return _clean(g)


def audit_out(a):
    return _clean(a)
