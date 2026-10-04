"""Extended emissions warranty: coverage, adjudication, payment (PRD §3.7)."""
from flask import Blueprint, request

import calculations
import cascade
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_enum, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("warranty", __name__)

COMPONENT_CLASSES = calculations.EMISSIONS_COMPONENT_CLASSES + ("ENGINE_BASE",)
DECISIONS = ("APPROVE_FULL", "APPROVE_PARTIAL", "DENY_NEGLECT")
MAX_REVIEW_ROUNDS = 2


def _claim(cid):
    return get_or_404(store.claims, cid, "WarrantyClaim")


@bp.post("/emissions/warranty-claims")
def create_claim():
    user_id, role = auth(("FleetManager", "ServiceAdvisor"))
    b = body()
    unit_id = f_str(b, "engine_unit_id")
    center_id = f_str(b, "service_center_id")
    comp_class = f_enum(b, "failed_component_class", COMPONENT_CLASSES)
    failure_code = f_str(b, "failure_code")
    claimed = f_int(b, "claimed_amount_cents", min_v=1)
    # existence (priority 4), body FKs left-to-right
    unit = get_or_404(store.units, unit_id, "EngineUnit")
    center = get_or_404(store.centers, center_id, "ServiceCenter")
    # ownership (priority 5)
    if role == "FleetManager" and unit["fleet_id"] != user_id:
        raise ApiError("ERR_FLEET_MISMATCH", 403,
                       "FleetManager may file only for own fleet's units")
    if role == "ServiceAdvisor" and center_id != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "ServiceAdvisor may file only as their own center")
    # state gates (priority 7), in the PRD-pinned order: unit, filer fleet, center
    if unit["lifecycle"] != "IN_SERVICE":
        raise ApiError("ERR_UNIT_NOT_IN_SERVICE", 409,
                       "The failed unit must be IN_SERVICE")
    fleet = store.fleets.get(unit["fleet_id"])
    if fleet is None or fleet["status"] != "ACTIVE":
        raise ApiError("ERR_FLEET_SUSPENDED", 409,
                       "The filing fleet must be ACTIVE")
    if center["auth_status"] != "AUTHORIZED":
        raise ApiError("ERR_CENTER_NOT_AUTHORIZED", 409,
                       "The repairing center must be AUTHORIZED")
    # temporal (priority 12): coverage determination
    fam = store.families.get(unit["engine_family_id"])
    std = store.standards.get(fam["regulation_standard_id"]) if fam else None
    cov = calculations.coverage_windows(unit, std, comp_class, clock.now_dt())
    if cov["variant"] is None:
        raise ApiError("ERR_COVERAGE_EXPIRED", 409,
                       "Neither extended nor base warranty window is open")
    ent = new_entity()
    ent.update({
        "engine_unit_id": unit["id"],
        "service_center_id": center["id"],
        "failed_component_class": comp_class,
        "failure_code": failure_code,
        "claimed_amount_cents": claimed,
        "submitted_by_role": role,
        "submitted_by_user_id": user_id,
        "coverage_variant": cov["variant"],
        "neglect_score": None,
        "approved_amount_cents": None,
        "customer_share_cents": None,
        "review_round": 0,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "paid_at": None,
    })
    store.claims[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/warranty-claims")
def list_claims():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.claims.values())
    for param, key in (("engine_unit_id", "engine_unit_id"),
                       ("service_center_id", "service_center_id"),
                       ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[key] == v]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/warranty-claims/<cid>")
def get_claim(cid):
    auth(ANY)
    return envelope_ok(ser(_claim(cid)), 200)


@bp.post("/emissions/warranty-claims/<cid>/start-review")
def start_review(cid):
    auth(("WarrantyAdjudicator",))
    claim = _claim(cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "start-review requires SUBMITTED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return envelope_ok(ser(claim), 200)


@bp.post("/emissions/warranty-claims/<cid>/request-info")
def request_info(cid):
    auth(("WarrantyAdjudicator",))
    claim = _claim(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "request-info requires UNDER_REVIEW")
    if claim["review_round"] >= MAX_REVIEW_ROUNDS:
        raise ApiError("ERR_REVIEW_ROUNDS_EXHAUSTED", 409,
                       "At most %d information rounds per claim" % MAX_REVIEW_ROUNDS)
    claim["review_round"] += 1
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return envelope_ok(ser(claim), 200)


@bp.post("/emissions/warranty-claims/<cid>/resubmit")
def resubmit_claim(cid):
    user_id, role = auth(("FleetManager", "ServiceAdvisor"))
    b = body()
    f_str(b, "supplemental_note")
    claim = _claim(cid)
    unit = store.units.get(claim["engine_unit_id"])
    # ownership (priority 5): the filing side answers
    if role == "FleetManager" and (unit is None or unit["fleet_id"] != user_id):
        raise ApiError("ERR_FLEET_MISMATCH", 403,
                       "Only the filing fleet may resubmit")
    if role == "ServiceAdvisor" and claim["service_center_id"] != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "Only the repairing center may resubmit")
    if claim["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "resubmit requires INFO_REQUESTED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return envelope_ok(ser(claim), 200)


@bp.post("/emissions/warranty-claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    user_id, _ = auth(("WarrantyAdjudicator",))
    b = body()
    decision = f_enum(b, "decision", DECISIONS)
    claim = _claim(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "adjudicate requires UNDER_REVIEW")
    unit = store.units.get(claim["engine_unit_id"])
    score = calculations.neglect_score(unit)
    # scoring consistency (priority 9): the decision must match the score band
    if calculations.decision_band(score) != decision:
        raise ApiError("ERR_DECISION_INCONSISTENT_WITH_SCORE", 422,
                       "Decision %s is inconsistent with neglect_score %d" % (decision, score))
    claim["neglect_score"] = score
    if decision == "APPROVE_FULL":
        claim["approved_amount_cents"] = claim["claimed_amount_cents"]
        claim["customer_share_cents"] = 0
        claim["status"] = "APPROVED_FULL"
    elif decision == "APPROVE_PARTIAL":
        fam = store.families.get(unit["engine_family_id"])
        std = store.standards.get(fam["regulation_standard_id"]) if fam else None
        share, approved = calculations.partial_proration(claim, unit, std)
        claim["customer_share_cents"] = share
        claim["approved_amount_cents"] = approved
        claim["status"] = "APPROVED_PARTIAL"
    else:  # DENY_NEGLECT
        claim["approved_amount_cents"] = 0
        claim["customer_share_cents"] = claim["claimed_amount_cents"]
        claim["status"] = "DENIED_NEGLECT"
        fleet = store.fleets.get(unit["fleet_id"])
        if fleet is not None:
            cascade.apply_neglect_denial(fleet)  # hop 1 + hop 2 (suspend at 3)
    claim["decided_by_user_id"] = user_id
    touch(claim)
    return envelope_ok(ser(claim), 200)


@bp.post("/emissions/warranty-claims/<cid>/pay")
def pay_claim(cid):
    auth(("PlatformAdmin",))
    claim = _claim(cid)
    if claim["status"] not in ("APPROVED_FULL", "APPROVED_PARTIAL"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "pay requires APPROVED_FULL or APPROVED_PARTIAL")
    claim["status"] = "PAID"
    claim["paid_at"] = clock.now_dt()
    touch(claim)
    return envelope_ok(ser(claim), 200)
