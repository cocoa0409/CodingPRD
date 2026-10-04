"""Path-segment resolution with the entity-specific not-found codes (PRD 2.9)."""

from clock import parse_dt
from db import db
from errors import APIError


def fetch(collection, row_id, error_id, label):
    row = db.find(collection, row_id)
    if row is None:
        raise APIError(error_id, "The %s '%s' does not resolve." % (label, row_id))
    return row


def employer_account(row_id):
    return fetch("employer_accounts", row_id, "ERR_EMPLOYER_NOT_FOUND", "employer account")


def member(row_id):
    return fetch("members", row_id, "ERR_MEMBER_NOT_FOUND", "member")


def care_advocate(row_id):
    return fetch("care_advocates", row_id, "ERR_ADVOCATE_NOT_FOUND", "care advocate")


def clinic(row_id):
    return fetch("clinics", row_id, "ERR_CLINIC_NOT_FOUND", "clinic")


def clinic_contract(row_id):
    return fetch("clinic_contracts", row_id, "ERR_CONTRACT_NOT_FOUND", "clinic contract")


def bundle_entitlement(row_id):
    return fetch("bundle_entitlements", row_id, "ERR_BUNDLE_NOT_FOUND", "bundle entitlement")


def treatment_plan(row_id):
    return fetch("treatment_plans", row_id, "ERR_PLAN_NOT_FOUND", "treatment plan")


def preauthorization(row_id):
    return fetch("preauthorizations", row_id, "ERR_PREAUTH_NOT_FOUND", "pre-authorization")


def treatment_cycle(row_id):
    return fetch("treatment_cycles", row_id, "ERR_CYCLE_NOT_FOUND", "treatment cycle")


def claim(row_id):
    return fetch("claims", row_id, "ERR_CLAIM_NOT_FOUND", "claim")


def surrender_route(row_id):
    return fetch("surrender_routes", row_id, "ERR_NOT_FOUND", "surrender route")


def check_occ(expected, actual, error_id, message):
    """A supplied concurrency token that is stale is refused; an absent one is not."""
    if expected is None:
        return
    if int(expected) != int(actual):
        raise APIError(error_id, message)


def resolve_member_version(expected, actual):
    """Refuse a change computed against a member shape that has since moved.

    The observation is compared only when the caller supplies it; a request
    that carries none proceeds without the guard.
    """
    if expected is None:
        return
    if int(expected) != int(actual):
        raise APIError("ERR_INVALID_REQUEST", "The member's version has advanced since it was observed.")


def window_contains(container, instant):
    start = parse_dt(container.get("effective_from"))
    end = parse_dt(container.get("effective_to"))
    if start is None or end is None or instant is None:
        return False
    return start <= instant < end