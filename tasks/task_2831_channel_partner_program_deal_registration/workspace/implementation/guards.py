"""Existence lookups and the shared business preconditions of PRD 2.8."""
import store
from errors import ApiError

_NOT_FOUND = {
    "partners": "ERR_PARTNER_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "mappings": "ERR_MAPPING_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
    "conflicts": "ERR_CONFLICT_CASE_NOT_FOUND",
    "sprs": "ERR_SPR_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "proofs": "ERR_PROOF_NOT_FOUND",
    "orders": "ERR_INVOICE_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
}


def find(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection],
                       "No such resource: %s." % row_id)
    return row


def find_partner(partner_id):
    return find("partners", partner_id)


def find_account(account_id):
    return find("accounts", account_id)


def find_registration(registration_id):
    return find("registrations", registration_id)


def find_claim(claim_id):
    return find("claims", claim_id)


def find_allocation(allocation_id):
    return find("allocations", allocation_id)


def find_proof_of_claim(claim, proof_id):
    """PRD 2.10: a proof hanging off another claim is reported as missing."""
    proof = store.get("proofs", proof_id)
    if proof is None or proof["claim_id"] != claim["id"]:
        raise ApiError("ERR_PROOF_NOT_FOUND", "No such proof document: %s." % proof_id)
    return proof


def partner_of_claim(claim):
    allocation = store.get("allocations", claim["allocation_id"])
    return store.get("partners", allocation["partner_id"])


def allocation_of_claim(claim):
    return store.get("allocations", claim["allocation_id"])


def check_not_suspended(partner):
    if partner["tier_status"] == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED",
                       "The partner's program standing is SUSPENDED.")


def check_no_overdue_audit(partner):
    """Any FINDINGS_OPEN review whose deadline has been reached freezes the partner."""
    instant = store.now()
    for review in store.all_rows("reviews"):
        if review["partner_id"] != partner["id"]:
            continue
        if review["status"] != "FINDINGS_OPEN":
            continue
        due = review["remediation_due_at"]
        if due is not None and due <= instant:
            raise ApiError("ERR_AUDIT_REMEDIATION_OVERDUE",
                           "An open compliance finding is past its remediation deadline.")


def check_allocation_open(allocation):
    if allocation["status"] != "OPEN":
        raise ApiError("ERR_ALLOCATION_CLOSED", "The fund period is closed.")


def invalid_state(message="The requested transition is not allowed from the current state."):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)
