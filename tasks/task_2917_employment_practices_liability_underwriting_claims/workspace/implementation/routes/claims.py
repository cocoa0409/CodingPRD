"""Claim lifecycle, related-claim aggregation, pre-suit offers and payments."""

from flask import Blueprint

import calc
import serialize
import store
from errors import ApiError
from envelope import created_response, list_response, object_response
from routes.common import ALL_STAFF, by_created, sorted_by
from services import ledger
from validate import (ENUMS, F, auth, enum_filter, no_body, pagination,
                      parse_body, raw_body, str_filter)

bp = Blueprint("claims", __name__)

CLAIM_ONE_READERS = ALL_STAFF + ("PanelCounsel",)
CLAIM_LIST_READERS = ALL_STAFF
GROUP_READERS = ALL_STAFF
RESOLUTION_READERS = ("PlatformAdmin", "ClaimsAdjuster", "ClaimsManager")
PAYMENT_READERS = ("PlatformAdmin", "ClaimsAdjuster", "ClaimsManager",
                   "UnderwritingManager")

IN_FORCE = ("BOUND", "ACTIVE")


def require_policy_in_force(policy, claim=None):
    """PRD 2.8 item 9: the owning policy must be in force and the claim
    must not be coverage-gated."""
    if policy is None or policy["status"] not in IN_FORCE:
        raise ApiError("ERR_POLICY_NOT_IN_FORCE",
                       "The owning policy is not BOUND or ACTIVE.")
    if claim is not None and claim.get("coverage_gated"):
        raise ApiError("ERR_POLICY_NOT_IN_FORCE",
                       "The claim is coverage-gated by a policy suspension.")


# --------------------------------------------------------------------------
# claim reads
# --------------------------------------------------------------------------
@bp.get("/epli/claims/<claim_id>")
def get_claim(claim_id):
    auth(CLAIM_ONE_READERS)
    row = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    return object_response(serialize.claim(row))


@bp.get("/epli/claims")
def list_claims():
    auth(CLAIM_LIST_READERS)
    limit, offset = pagination()
    policy_id = str_filter("policy_id")
    related_to = str_filter("related_to_claim_id")
    group_id = str_filter("related_claim_group_id")
    status = enum_filter("status", "claim_status")
    claim_type = enum_filter("claim_type", "claim_type")
    bucket = enum_filter("coverage_bucket", "coverage_bucket")
    rows = list(store.CLAIMS.values())
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if related_to is not None:
        rows = [r for r in rows if r["related_to_claim_id"] == related_to]
    if group_id is not None:
        rows = [r for r in rows if r["related_claim_group_id"] == group_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if claim_type is not None:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    if bucket is not None:
        rows = [r for r in rows if r["coverage_bucket"] == bucket]
    rows = sorted_by(rows, [lambda r: r["first_notice_at"],
                            lambda r: r["created_at"]])
    return list_response([serialize.claim(r) for r in rows], limit, offset)


# --------------------------------------------------------------------------
# claim intake and lifecycle
# --------------------------------------------------------------------------
@bp.post("/epli/policies/<policy_id>/claims")
def report_claim(policy_id):
    auth(("ClaimsAdjuster",))
    body = parse_body([
        F("claim_type", "enum", required=True, values=ENUMS["claim_type"]),
        F("claimant_class", "enum", required=True,
          values=ENUMS["claimant_class"]),
        F("notice_type", "enum", required=True, values=ENUMS["notice_type"]),
        F("first_notice_at", "instant", required=True),
        F("alleged_damages_cents", "int", required=True, min=0),
        F("claimant_count", "int", default=1, min=1),
        F("related_to_claim_id", "id"),
    ])
    policy = store.find(store.POLICIES, policy_id, "ERR_POLICY_NOT_FOUND")
    related = None
    if body["related_to_claim_id"] is not None:
        related = store.find(store.CLAIMS, body["related_to_claim_id"],
                             "ERR_CLAIM_NOT_FOUND")
        if related["policy_id"] != policy["id"]:
            raise ApiError("ERR_OWNERSHIP_MISMATCH",
                           "The related claim belongs to another policy.")
    require_policy_in_force(policy)
    bucket = calc.coverage_bucket(body["claim_type"], body["claimant_class"])
    if bucket == "THIRD_PARTY" and not policy["third_party_coverage_elected"]:
        raise ApiError("ERR_THIRD_PARTY_COVERAGE_NOT_ELECTED",
                       "This policy did not elect third-party coverage.")
    if not (policy["effective_from"] <= body["first_notice_at"]
            < policy["effective_to"]):
        raise ApiError("ERR_CLAIM_OUTSIDE_POLICY_PERIOD",
                       "first_notice_at falls outside the policy period.")
    row = store.new_row({
        "policy_id": policy["id"],
        "claim_type": body["claim_type"],
        "claimant_class": body["claimant_class"],
        "notice_type": body["notice_type"],
        "first_notice_at": body["first_notice_at"],
        "alleged_damages_cents": body["alleged_damages_cents"],
        "claimant_count": body["claimant_count"],
        "related_to_claim_id": related["id"] if related else None,
        "related_claim_group_id": None,
        "coverage_bucket": bucket,
        "per_claim_retention_cents": None,
        "pre_suit_credit_cents": 0,
        "reopen_count": 0,
        "coverage_gated": False,
        "denial_reason": None,
        "status": "REPORTED",
    })
    store.CLAIMS[row["id"]] = row
    return created_response(serialize.claim(row))


@bp.post("/epli/claims/<claim_id>/start-review")
def start_review(claim_id):
    auth(("ClaimsAdjuster",))
    no_body()
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "REPORTED":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE",
                       "Only a REPORTED claim may enter review.")
    require_policy_in_force(store.policy_of_claim(claim), claim)
    claim["status"] = "UNDER_REVIEW"
    store.touch(claim)
    return object_response(serialize.claim(claim))


@bp.post("/epli/claims/<claim_id>/coverage-decision")
def coverage_decision(claim_id):
    auth(("ClaimsAdjuster",))
    body = parse_body([
        F("decision", "enum", required=True, values=ENUMS["decision"]),
        F("denial_reason", "str"),
    ])
    supplied = "denial_reason" in body["_present"]
    if body["decision"] == "ACCEPT" and supplied:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'denial_reason' must be absent on an ACCEPT.")
    if body["decision"] == "DENY" and not supplied:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'denial_reason' is required on a DENY.")
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COVERAGE_ALREADY_DECIDED",
                       "Only an UNDER_REVIEW claim may be decided.")
    policy = store.policy_of_claim(claim)
    require_policy_in_force(policy, claim)
    if body["decision"] == "ACCEPT":
        claim["status"] = "COVERAGE_ACCEPTED"
        claim["per_claim_retention_cents"] = calc.claim_retention_cents(
            policy["per_claim_retention_cents"], claim["claim_type"],
            claim["claimant_class"])
    else:
        claim["status"] = "COVERAGE_DENIED"
        claim["denial_reason"] = body["denial_reason"]
    store.touch(claim)
    return object_response(serialize.claim(claim))


@bp.post("/epli/claims/<claim_id>/close")
def close_claim(claim_id):
    auth(("ClaimsAdjuster",))
    no_body()
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] not in ("COVERAGE_DENIED", "RESOLVED"):
        raise ApiError("ERR_CLAIM_NOT_CLOSABLE",
                       "Only a COVERAGE_DENIED or RESOLVED claim may close.")
    claim["status"] = "CLOSED"
    store.touch(claim)
    ledger.close_claim_assignments(claim)
    return object_response(serialize.claim(claim))


@bp.post("/epli/claims/<claim_id>/reopen")
def reopen_claim(claim_id):
    auth(("ClaimsManager",))
    no_body()
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "CLOSED":
        raise ApiError("ERR_CLAIM_NOT_REOPENABLE",
                       "Only a CLOSED claim may be reopened.")
    require_policy_in_force(store.policy_of_claim(claim), claim)
    if claim["reopen_count"] >= calc.REOPEN_LIMIT:
        raise ApiError("ERR_CLAIM_REOPEN_LIMIT",
                       "This claim has already been reopened once.")
    claim["status"] = "UNDER_REVIEW"
    claim["reopen_count"] = claim["reopen_count"] + 1
    store.touch(claim)
    return object_response(serialize.claim(claim))


# --------------------------------------------------------------------------
# related-claim groups
# --------------------------------------------------------------------------
BUCKET_STRICT_BASES = ("CLASS_ACTION_MEMBER", "MASS_CLAIM_WAVE")


@bp.get("/epli/related-claim-groups/<group_id>")
def get_group(group_id):
    auth(GROUP_READERS)
    row = store.find(store.GROUPS, group_id, "ERR_GROUP_NOT_FOUND")
    return object_response(serialize.group(row))


@bp.get("/epli/related-claim-groups")
def list_groups():
    auth(GROUP_READERS)
    limit, offset = pagination()
    policy_id = str_filter("policy_id")
    lead_claim_id = str_filter("lead_claim_id")
    basis_claim_id = str_filter("retention_basis_claim_id")
    status = enum_filter("status", "group_status")
    basis = enum_filter("aggregation_basis", "aggregation_basis")
    rows = list(store.GROUPS.values())
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if lead_claim_id is not None:
        rows = [r for r in rows if r["lead_claim_id"] == lead_claim_id]
    if basis_claim_id is not None:
        rows = [r for r in rows
                if ledger.group_retention_basis_claim_id(r) == basis_claim_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["aggregation_basis"] == basis]
    return list_response([serialize.group(r) for r in by_created(rows)],
                         limit, offset)


@bp.post("/epli/related-claim-groups")
def create_group():
    auth(("ClaimsManager",))
    body = parse_body([
        F("policy_id", "id", required=True),
        F("lead_claim_id", "id", required=True),
        F("aggregation_basis", "enum", required=True,
          values=ENUMS["aggregation_basis"]),
    ])
    policy = store.find(store.POLICIES, body["policy_id"],
                        "ERR_POLICY_NOT_FOUND")
    lead = store.find(store.CLAIMS, body["lead_claim_id"],
                      "ERR_CLAIM_NOT_FOUND")
    if lead["policy_id"] != policy["id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "The lead claim belongs to another policy.")
    if lead["related_claim_group_id"]:
        raise ApiError("ERR_CLAIM_ALREADY_GROUPED",
                       "The lead claim already belongs to a group.")
    row = store.new_row({
        "policy_id": policy["id"],
        "lead_claim_id": lead["id"],
        "aggregation_basis": body["aggregation_basis"],
        "status": "OPEN",
    })
    store.GROUPS[row["id"]] = row
    lead["related_claim_group_id"] = row["id"]
    store.touch(lead)
    return created_response(serialize.group(row))


@bp.post("/epli/related-claim-groups/<group_id>/claims")
def attach_claim(group_id):
    auth(("ClaimsManager",))
    body = parse_body([
        F("claim_id", "id", required=True),
        F("expected_related_claim_group_version", "int", required=True),
    ])
    group = store.find(store.GROUPS, group_id, "ERR_GROUP_NOT_FOUND")
    claim = store.find(store.CLAIMS, body["claim_id"], "ERR_CLAIM_NOT_FOUND")
    if claim["policy_id"] != group["policy_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "The claim belongs to another policy.")
    if (body["expected_related_claim_group_version"] != group["version"]):
        raise ApiError("ERR_STALE_GROUP_VERSION",
                       "The group has been modified since it was read.")
    if group["status"] == "LOCKED":
        raise ApiError("ERR_GROUP_LOCKED",
                       "A LOCKED group accepts no further members.")
    if claim["related_claim_group_id"]:
        raise ApiError("ERR_CLAIM_ALREADY_GROUPED",
                       "The claim already belongs to a group.")
    if group["aggregation_basis"] in BUCKET_STRICT_BASES:
        lead = store.CLAIMS.get(group["lead_claim_id"])
        if (claim["claimant_count"] < 1 or lead is None
                or claim["coverage_bucket"] != lead["coverage_bucket"]):
            raise ApiError("ERR_GROUP_BASIS_MISMATCH",
                           "The claim's coverage bucket does not match the "
                           "lead claim's.")
    claim["related_claim_group_id"] = group["id"]
    store.touch(claim)
    store.touch(group)
    return object_response(serialize.group(group))


# --------------------------------------------------------------------------
# pre-suit resolutions
# --------------------------------------------------------------------------
ACCEPTABLE_CLAIM_STATUSES = ("UNDER_REVIEW", "COVERAGE_ACCEPTED",
                             "DEFENSE_OPEN")


@bp.get("/epli/pre-suit-resolutions/<resolution_id>")
def get_resolution(resolution_id):
    auth(RESOLUTION_READERS)
    row = store.find(store.RESOLUTIONS, resolution_id,
                     "ERR_RESOLUTION_NOT_FOUND")
    return object_response(serialize.resolution(row))


@bp.get("/epli/pre-suit-resolutions")
def list_resolutions():
    auth(RESOLUTION_READERS)
    limit, offset = pagination()
    claim_id = str_filter("claim_id")
    status = enum_filter("status", "resolution_status")
    rows = list(store.RESOLUTIONS.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response([serialize.resolution(r) for r in by_created(rows)],
                         limit, offset)


@bp.post("/epli/claims/<claim_id>/pre-suit-resolutions")
def create_resolution(claim_id):
    auth(("ClaimsAdjuster",))
    body = parse_body([
        F("offer_expires_at", "instant", required=True),
        F("settlement_offer_cents", "int", required=True, min=1),
    ])
    if body["offer_expires_at"] <= store.clock_now():
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'offer_expires_at' must be strictly after the "
                       "current logical clock.")
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["notice_type"] != "ADMIN_CHARGE":
        raise ApiError("ERR_PRE_SUIT_NOT_ELIGIBLE",
                       "Only an ADMIN_CHARGE claim is pre-suit eligible.")
    row = store.new_row({
        "claim_id": claim["id"],
        "mediation_offered_at": store.clock_now(),
        "offer_expires_at": body["offer_expires_at"],
        "settlement_offer_cents": body["settlement_offer_cents"],
        "elapsed_days_at_accept": None,
        "incentive_credit_cents": None,
        "status": "OFFERED",
    })
    store.RESOLUTIONS[row["id"]] = row
    return created_response(serialize.resolution(row))


@bp.post("/epli/pre-suit-resolutions/<resolution_id>/accept")
def accept_resolution(resolution_id):
    auth(("ClaimsAdjuster",))
    no_body()
    row = store.find(store.RESOLUTIONS, resolution_id,
                     "ERR_RESOLUTION_NOT_FOUND")
    claim = store.CLAIMS[row["claim_id"]]
    if (row["status"] != "OFFERED"
            or claim["status"] not in ACCEPTABLE_CLAIM_STATUSES):
        raise ApiError("ERR_RESOLUTION_NOT_ACCEPTABLE",
                       "Only an OFFERED offer on a live claim may be "
                       "accepted.")
    if claim["notice_type"] != "ADMIN_CHARGE":
        raise ApiError("ERR_PRE_SUIT_NOT_ELIGIBLE",
                       "Only an ADMIN_CHARGE claim is pre-suit eligible.")
    now = store.clock_now()
    elapsed = calc.elapsed_days(claim["first_notice_at"], now)
    policy = store.policy_of_claim(claim)
    applicant = store.applicant_of_policy(policy) if policy else None
    window = None
    if applicant is not None:
        jurisdiction = store.jurisdiction_by_code(
            applicant["primary_jurisdiction_code"])
        if jurisdiction is not None:
            window = jurisdiction["pre_suit_window_days"]
    if now > row["offer_expires_at"] or window is None or elapsed > window:
        raise ApiError("ERR_PRE_SUIT_WINDOW_CLOSED",
                       "The pre-suit window has closed for this claim.")
    credit = calc.pre_suit_incentive_credit_cents(row["settlement_offer_cents"])
    row["elapsed_days_at_accept"] = elapsed
    row["incentive_credit_cents"] = credit
    row["status"] = "ACCEPTED"
    store.touch(row)
    claim["pre_suit_credit_cents"] = credit
    if claim["status"] in ("COVERAGE_ACCEPTED", "DEFENSE_OPEN"):
        claim["status"] = "RESOLVED"
    store.touch(claim)
    return object_response(serialize.resolution(row))


# --------------------------------------------------------------------------
# indemnity payments
# --------------------------------------------------------------------------
@bp.get("/epli/indemnity-payments/<payment_id>")
def get_payment(payment_id):
    auth(PAYMENT_READERS)
    row = store.find(store.PAYMENTS, payment_id, "ERR_PAYMENT_NOT_FOUND")
    return object_response(serialize.payment(row))


@bp.get("/epli/indemnity-payments")
def list_payments():
    auth(PAYMENT_READERS)
    limit, offset = pagination()
    claim_id = str_filter("claim_id")
    status = enum_filter("status", "payment_status")
    bucket = enum_filter("sublimit_bucket", "coverage_bucket")
    rows = list(store.PAYMENTS.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if bucket is not None:
        rows = [r for r in rows if r["sublimit_bucket"] == bucket]
    return list_response([serialize.payment(r) for r in by_created(rows)],
                         limit, offset)


@bp.post("/epli/claims/<claim_id>/indemnity-payments")
def create_payment(claim_id):
    user_id, _role = auth(("ClaimsAdjuster",))
    body = parse_body([
        F("amount_cents", "int", required=True, min=1),
        F("payment_basis", "enum", required=True,
          values=ENUMS["payment_basis"]),
        F("expected_policy_version", "int", required=True),
    ])
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    policy = store.policy_of_claim(claim)
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    if body["expected_policy_version"] != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION",
                       "The policy has been modified since it was read.")
    require_policy_in_force(policy, claim)
    outstanding = ledger.outstanding_retention(claim)
    retention_portion = min(body["amount_cents"], outstanding)
    row = store.new_row({
        "claim_id": claim["id"],
        "amount_cents": body["amount_cents"],
        "payment_basis": body["payment_basis"],
        "retention_portion_cents": retention_portion,
        "insurer_portion_cents": body["amount_cents"] - retention_portion,
        "sublimit_bucket": claim["coverage_bucket"],
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "void_reason": None,
        "status": "PENDING_APPROVAL",
    })
    store.PAYMENTS[row["id"]] = row
    store.touch(policy)
    return created_response(serialize.payment(row))


@bp.post("/epli/indemnity-payments/<payment_id>/approve")
def approve_payment(payment_id):
    user_id, _role = auth(("ClaimsManager",))
    no_body()
    row = store.find(store.PAYMENTS, payment_id, "ERR_PAYMENT_NOT_FOUND")
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_PAYMENT_NOT_APPROVABLE",
                       "Only a PENDING_APPROVAL payment may be approved.")
    claim = store.CLAIMS[row["claim_id"]]
    group = ledger.group_of_claim(claim)
    if group is not None and group["status"] == "LOCKED":
        raise ApiError("ERR_GROUP_LOCKED",
                       "The claim's related-claim group is LOCKED.")
    if user_id == row["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver must differ from the drafting user.")
    policy = store.policy_of_claim(claim)
    insurer = row["insurer_portion_cents"]
    if row["sublimit_bucket"] == "WAGE_HOUR":
        if insurer > ledger.policy_wage_hour_remaining(policy):
            raise ApiError("ERR_WAGE_HOUR_SUBLIMIT_EXHAUSTED",
                           "The wage-and-hour sublimit cannot absorb this "
                           "insurer portion.")
    elif row["sublimit_bucket"] == "THIRD_PARTY":
        if insurer > ledger.policy_third_party_remaining(policy):
            raise ApiError("ERR_THIRD_PARTY_SUBLIMIT_EXHAUSTED",
                           "The third-party sublimit cannot absorb this "
                           "insurer portion.")
    if insurer > ledger.policy_remaining(policy):
        raise ApiError("ERR_AGGREGATE_LIMIT_EXHAUSTED",
                       "The aggregate limit cannot absorb this insurer "
                       "portion.")
    row["approved_by_user_id"] = user_id
    row["status"] = "APPROVED"
    store.touch(row)
    # hop 1: the claim ledger, then the group aggregation
    if claim["status"] in ("COVERAGE_ACCEPTED", "DEFENSE_OPEN"):
        claim["status"] = "RESOLVED"
    store.touch(claim)
    if group is not None:
        ledger.refresh_group_lock(group)
    # hop 2: the policy ledger and erosion posture
    store.touch(policy)
    # hops 3 and 4: defense funding cut off on exhaustion
    if ledger.policy_limit_posture(policy) == "EXHAUSTED":
        ledger.exhaustion_cascade(policy, store.clock_now())
    return object_response(serialize.payment(row))


@bp.post("/epli/indemnity-payments/<payment_id>/void")
def void_payment(payment_id):
    auth(("ClaimsManager",))
    body = parse_body([F("void_reason", "str", required=True)])
    row = store.find(store.PAYMENTS, payment_id, "ERR_PAYMENT_NOT_FOUND")
    if row["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise ApiError("ERR_PAYMENT_NOT_VOIDABLE",
                       "Only a PENDING_APPROVAL or APPROVED payment may be "
                       "voided.")
    was_approved = row["status"] == "APPROVED"
    row["void_reason"] = body["void_reason"]
    row["status"] = "VOIDED"
    store.touch(row)
    if was_approved:
        claim = store.CLAIMS[row["claim_id"]]
        store.touch(claim)
        group = ledger.group_of_claim(claim)
        if group is not None:
            ledger.refresh_group_lock(group)
        policy = store.policy_of_claim(claim)
        if policy is not None:
            store.touch(policy)
    return object_response(serialize.payment(row))
