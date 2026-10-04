"""Warranty claims: filing with auto service-center selection, adjudication
with the dual age-basis credit computation, and fulfillment completion."""
from flask import Blueprint, request

import db
from constants import API_PREFIX, CLAIM_DECISIONS, CLAIM_TYPES, ROLES
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    ok_list,
    ok_object,
    pagination,
    page_window,
    parse_service_date,
    req_field,
    req_str,
)
from services import (
    bump,
    make_entity,
    select_service_center,
    warranty_compute,
)
from views import view_claim

bp = Blueprint("warranty", __name__)

_CLAIM_FOR_SUBJECT = {"TOOL_REPAIR": "TOOL", "BATTERY_REPLACEMENT": "BATTERY"}


def _get_claim_or_404(claim_id):
    claim = db.STORE["claims"].get(claim_id)
    if claim is None:
        fail("ERR_NOT_FOUND", "Warranty claim not found")
    return claim


def _check_claim_ownership(user_id, claim):
    if user_id != claim["service_center_id"]:
        fail("ERR_FORBIDDEN", "X-User-ID does not match the claim's service_center_id")


@bp.route(f"{API_PREFIX}/warranty-claims", methods=["POST"])
def create_claim():
    user_id, _ = authorize(["AccountManager"])
    data = body()
    # Priority 4: asset existence, then Priority 3 ownership via the asset.
    tracked_asset_id = req_field(data, "tracked_asset_id")
    asset = db.STORE["assets"].get(tracked_asset_id)
    if asset is None:
        fail("ERR_NOT_FOUND", "tracked_asset_id does not reference an existing asset")
    if user_id != asset["account_id"]:
        fail("ERR_FORBIDDEN", "X-User-ID does not match the asset's account_id")
    # Priority 5: shape
    claim_type = check_enum(req_field(data, "claim_type"), "claim_type", CLAIM_TYPES)
    fault_code = req_str(data, "fault_code")
    service_date = req_field(data, "service_date")
    parsed_date = parse_service_date(service_date)
    # Priority 6: asset must be ACTIVE
    if asset["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Claims may only be filed against ACTIVE assets")
    # Priority 10: claim_type must match the asset's subject_type
    if _CLAIM_FOR_SUBJECT[claim_type] != asset["subject_type"]:
        fail("ERR_CLAIM_TYPE_MISMATCH", "claim_type does not match the asset subject_type")
    # Priority 19: service_date not before the logical clock's current date
    if parsed_date < db.clock_now().date():
        fail("ERR_SERVICE_DATE_PAST", "service_date is before the current date")
    # Priority 21: service-center waterfall selection
    center = select_service_center(claim_type, service_date)
    claim = make_entity(
        {
            "tracked_asset_id": tracked_asset_id,
            "claim_type": claim_type,
            "fault_code": fault_code,
            "service_date": service_date,
            "service_center_id": center["id"],
            "adjudication_status": "SUBMITTED",
            "fulfillment_status": "NONE",
            "age_basis": None,
            "age_days": None,
            "coverage": None,
            "credit_cents": None,
            "decided_by_user_id": None,
        }
    )
    db.STORE["claims"][claim["id"]] = claim
    return ok_object(view_claim(claim), 201)


@bp.route(f"{API_PREFIX}/warranty-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authorize(ROLES)
    return ok_object(view_claim(_get_claim_or_404(claim_id)))


@bp.route(f"{API_PREFIX}/warranty-claims", methods=["GET"])
def list_claims():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["claims"].values())
    for f in ("tracked_asset_id", "service_center_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c[f] == v]
    page, total = page_window(items, limit, offset)
    return ok_list([view_claim(c) for c in page], total, limit, offset)


@bp.route(f"{API_PREFIX}/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(claim_id):
    user_id, _ = authorize(["ServiceAgent"])
    claim = _get_claim_or_404(claim_id)
    _check_claim_ownership(user_id, claim)
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", CLAIM_DECISIONS)
    # Priority 6: adjudication dimension must be SUBMITTED
    if claim["adjudication_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Claim has already been adjudicated")
    if decision == "APPROVED":
        computed = warranty_compute(claim)
        # Priority 20: approving OUT_OF_WARRANTY coverage is rejected
        if computed["coverage"] == "OUT_OF_WARRANTY":
            fail("ERR_WARRANTY_EXPIRED", "Coverage computes to OUT_OF_WARRANTY")
        claim["age_basis"] = computed["age_basis"]
        claim["age_days"] = computed["age_days"]
        claim["coverage"] = computed["coverage"]
        claim["credit_cents"] = computed["credit_cents"]
        claim["adjudication_status"] = "APPROVED"
        claim["fulfillment_status"] = "AWAITING_UNIT"
    else:
        claim["adjudication_status"] = "REJECTED"
        claim["fulfillment_status"] = "CANCELLED"  # releases the daily booking
    claim["decided_by_user_id"] = user_id
    bump(claim)
    return ok_object(view_claim(claim))


@bp.route(f"{API_PREFIX}/warranty-claims/<claim_id>/complete", methods=["POST"])
def complete_claim(claim_id):
    user_id, _ = authorize(["ServiceAgent"])
    claim = _get_claim_or_404(claim_id)
    _check_claim_ownership(user_id, claim)
    # Priority 6: cross-dimension gate APPROVED + AWAITING_UNIT
    if not (
        claim["adjudication_status"] == "APPROVED"
        and claim["fulfillment_status"] == "AWAITING_UNIT"
    ):
        fail("ERR_INVALID_STATE", "Claim is not APPROVED and AWAITING_UNIT")
    claim["fulfillment_status"] = "COMPLETED"  # releases the daily booking
    bump(claim)
    if claim["claim_type"] == "BATTERY_REPLACEMENT":
        asset = db.STORE["assets"][claim["tracked_asset_id"]]
        now = db.clock_now()
        replacement = make_entity(
            {
                "account_id": asset["account_id"],
                "subject_type": "BATTERY",
                "tool_model_id": None,
                "battery_pack_id": asset["battery_pack_id"],
                "serial_number": "REPL-" + db.new_id(),
                "manufactured_at": now,
                "first_paired_at": now,
                "status": "ACTIVE",
                "custom_torque_limit_nm": None,
                "anti_theft_lock_enabled": False,
                "is_replacement_unit": True,  # exempt from the asset limit
            }
        )
        db.STORE["assets"][replacement["id"]] = replacement
    return ok_object(view_claim(claim))
