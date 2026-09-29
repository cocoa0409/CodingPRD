"""Authentication, authorisation, ownership and segregation of duties (PRD 2.1, 2.8)."""
from functools import wraps

from flask import g, request

import constants as C
from errors import ApiError
from store import db


def actor():
    return g.user_id, g.role


def endpoint(roles):
    """Tier 1 (ERR_UNAUTHENTICATED) and tier 2 (ERR_UNAUTHORIZED) of PRD 2.8."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(C.HDR_USER_ID)
            role = request.headers.get(C.HDR_USER_ROLE)
            if not user_id or not role or role not in C.ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return func(*args, **kwargs)

        return wrapper

    return decorator


# --- silent lookups ---------------------------------------------------------
def find(table, record_id):
    if not isinstance(record_id, str):
        return None
    return table.get(record_id)


def fetch(table, record_id, error_id):
    record = find(table, record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def specialty_class(record_id):
    return fetch(db.specialty_classes, record_id, "ERR_SPECIALTY_CLASS_NOT_FOUND")


def insured(record_id):
    return fetch(db.insureds, record_id, "ERR_INSURED_NOT_FOUND")


def enrollment(record_id):
    return fetch(db.enrollments, record_id, "ERR_ENROLLMENT_NOT_FOUND")


def peer_review_case(record_id):
    return fetch(db.peer_review_cases, record_id, "ERR_PEER_REVIEW_CASE_NOT_FOUND")


def policy(record_id):
    return fetch(db.policies, record_id, "ERR_POLICY_NOT_FOUND")


def policy_term(record_id):
    return fetch(db.policy_terms, record_id, "ERR_POLICY_TERM_NOT_FOUND")


def tail_endorsement(record_id):
    return fetch(db.tail_endorsements, record_id, "ERR_TAIL_ENDORSEMENT_NOT_FOUND")


def claim(record_id):
    return fetch(db.claims, record_id, "ERR_CLAIM_NOT_FOUND")


def counsel_firm(record_id):
    return fetch(db.counsel_firms, record_id, "ERR_COUNSEL_FIRM_NOT_FOUND")


def counsel_assignment(record_id):
    return fetch(db.counsel_assignments, record_id, "ERR_COUNSEL_ASSIGNMENT_NOT_FOUND")


def negotiation(record_id):
    return fetch(db.negotiations, record_id, "ERR_NEGOTIATION_NOT_FOUND")


def npdb_report(record_id):
    return fetch(db.npdb_reports, record_id, "ERR_NPDB_REPORT_NOT_FOUND")


def rate_filing(record_id):
    return fetch(db.rate_filings, record_id, "ERR_RATE_FILING_NOT_FOUND")


# --- ownership (PRD 2.8 tier 3) --------------------------------------------
def _deny_owner():
    raise ApiError("ERR_NOT_RESOURCE_OWNER")


def own_insured_id(insured_id):
    """Compare the acting insured identity with the resource's insured key."""
    if g.role != C.R_INSURED:
        return
    if insured_id is None or insured_id != g.user_id:
        _deny_owner()


def own_policy(policy_record):
    own_insured_id(policy_record.get("insured_id"))


def own_term(term):
    parent = find(db.policies, term.get("policy_id"))
    own_insured_id(parent.get("insured_id") if parent else None)


def own_tail(tail):
    parent = find(db.policies, tail.get("policy_id"))
    own_insured_id(parent.get("insured_id") if parent else None)


def own_claim(claim_record):
    own_insured_id(claim_record.get("insured_id"))


def own_negotiation(record):
    parent = find(db.claims, record.get("claim_id"))
    own_insured_id(parent.get("insured_id") if parent else None)


# --- segregation of duties (PRD 2.8 tier 4) -------------------------------
def deny_self_decision(record):
    if record.get("prepared_by_user_id") == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
