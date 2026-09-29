"""Shared route helpers: read scoping for entity-backed principals, sorting."""

import store
from errors import ApiError

ALL_STAFF = ("PlatformAdmin", "Underwriter", "UnderwritingManager",
             "ClaimsAdjuster", "ClaimsManager")


def scope_applicant(role, user_id, applicant_id):
    """A PolicyholderContact may only read rows of its own applicant."""
    if role == "PolicyholderContact" and user_id != applicant_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "This row belongs to another applicant.")


def own_applicant_filter(role, user_id, rows, applicant_id_of):
    if role != "PolicyholderContact":
        return rows
    return [r for r in rows if applicant_id_of(r) == user_id]


def scope_counsel_firm(role, user_id, firm_id):
    if role == "PanelCounsel" and user_id != firm_id:
        raise ApiError("ERR_NOT_ASSIGNED_COUNSEL",
                       "This matter belongs to another panel firm.")


def own_firm_filter(role, user_id, rows, firm_id_of):
    if role != "PanelCounsel":
        return rows
    return [r for r in rows if firm_id_of(r) == user_id]


def sorted_by(rows, keys):
    """keys is a list of callables; row _seq is always the final tie-break."""
    def key(row):
        return tuple(k(row) for k in keys) + (row["_seq"],)
    return sorted(rows, key=key)


def by_created(rows):
    return sorted_by(rows, [lambda r: r["created_at"]])


def assignment_firm_id(assignment):
    return assignment["panel_firm_id"]


def invoice_firm_id(invoice):
    assignment = store.ASSIGNMENTS.get(invoice["defense_assignment_id"])
    return assignment["panel_firm_id"] if assignment else None
