"""Partner agreements and the bounded negotiation loop (PRD 3.1, 3.2)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("agreements", __name__)

LIVE_LANE_STATES = ("DRAFT", "PROVIDER_PROPOSED", "MERCHANT_COUNTERED",
                    "ACCEPTED", "ACTIVE")
NEGOTIATION_TERMS = [
    {"name": "expected_agreement_version", "type": "int", "required": True},
    {"name": "commission_rate_bps", "type": "int", "required": True,
     "min": 100, "max": 4000},
    {"name": "placement_fee_base_cents", "type": "int", "required": True,
     "min": 0, "max": 500000},
    {"name": "employer_revenue_share_bps", "type": "int", "required": True,
     "min": 0, "max": 5000},
    {"name": "exclusivity_window_start", "type": "datetime"},
    {"name": "exclusivity_window_end", "type": "datetime"},
    {"name": "note", "type": "str"},
]


def _rounds_of(agreement_id):
    rows = [r for r in db.negotiation_rounds.values()
            if r["agreement_id"] == agreement_id]
    return sorted(rows, key=lambda r: r["round_number"])


def _republish(agreement):
    """Copy the standing terms from the round with the highest round_number."""
    rounds = _rounds_of(agreement["id"])
    agreement["round_count"] = len(rounds)
    if rounds:
        top = rounds[-1]
        for field in ("commission_rate_bps", "placement_fee_base_cents",
                      "employer_revenue_share_bps", "exclusivity_window_start",
                      "exclusivity_window_end"):
            agreement[field] = top[field]


def _file_round(agreement, data, proposer_role):
    rounds = _rounds_of(agreement["id"])
    next_number = (rounds[-1]["round_number"] + 1) if rounds else 1
    db.insert(db.negotiation_rounds, {
        "agreement_id": agreement["id"],
        "round_number": next_number,
        "proposer_role": proposer_role,
        "commission_rate_bps": data["commission_rate_bps"],
        "placement_fee_base_cents": data["placement_fee_base_cents"],
        "employer_revenue_share_bps": data["employer_revenue_share_bps"],
        "exclusivity_window_start": data["exclusivity_window_start"],
        "exclusivity_window_end": data["exclusivity_window_end"],
        "note": data["note"],
    }, versioned=False)
    _republish(agreement)


def _lift_merchant_to_negotiation(agreement):
    merchant = db.merchants.get(agreement["merchant_id"])
    if merchant is not None and merchant["status"] == "PROSPECT":
        merchant["status"] = "IN_NEGOTIATION"
        db.touch(merchant)


@bp.post("/perks/agreements")
def create_agreement():
    auth.require(auth.PARTNER_MANAGER)
    body = validate.json_body()
    merchant = support.resolve_fk(body, "merchant_id", "merchants")
    data = validate.fields(body, [
        {"name": "merchant_id", "type": "str", "required": True},
        {"name": "category", "type": "enum", "required": True,
         "values": validate.CATEGORIES},
        {"name": "region_code", "type": "enum", "required": True,
         "values": validate.REGIONS},
        {"name": "exclusivity_requested", "type": "bool", "default": False},
    ])
    if data["exclusivity_requested"] is None:
        data["exclusivity_requested"] = False
    if data["region_code"] not in merchant["region_codes"]:
        raise ApiError("ERR_REGION_NOT_COVERED",
                       "The nominated region is outside the partner's footprint.")
    for existing in db.agreements.values():
        if (existing["merchant_id"] == merchant["id"]
                and existing["category"] == data["category"]
                and existing["region_code"] == data["region_code"]
                and existing["status"] in LIVE_LANE_STATES):
            raise ApiError("ERR_DUPLICATE_AGREEMENT",
                           "A live lane already exists for this partner, "
                           "category and region.")
    row = db.insert(db.agreements, {
        "merchant_id": merchant["id"],
        "category": data["category"],
        "region_code": data["region_code"],
        "status": "DRAFT",
        "round_count": 0,
        "commission_rate_bps": None,
        "placement_fee_base_cents": None,
        "employer_revenue_share_bps": None,
        "exclusivity_requested": data["exclusivity_requested"],
        "exclusivity_window_start": None,
        "exclusivity_window_end": None,
        "exclusivity_granted": False,
        "accepted_by_role": None,
        "activated_at": None,
        "terminated_reason": None,
    })
    return response.created(derive.agreement_json(row))


@bp.get("/perks/agreements/<row_id>")
def get_agreement(row_id):
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN, auth.MERCHANT)
    row = support.fetch("agreements", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    return response.ok(derive.agreement_json(row))


@bp.get("/perks/agreements")
def list_agreements():
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN, auth.MERCHANT)
    merchant_id = support.arg("merchant_id")
    category = support.arg("category")
    region = support.arg("region_code")
    status = support.arg("status")
    granted = validate.query_flag("exclusivity_granted")
    rows = []
    for row in db.agreements.values():
        if principal.is_merchant and row["merchant_id"] != principal.user_id:
            continue
        if not support.matches(row, "merchant_id", merchant_id):
            continue
        if not support.matches(row, "category", category):
            continue
        if not support.matches(row, "region_code", region):
            continue
        if not support.matches(row, "status", status):
            continue
        if granted is not None and row["exclusivity_granted"] != granted:
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.agreement_json)


@bp.get("/perks/agreements/<row_id>/negotiation-rounds")
def list_rounds(row_id):
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN, auth.MERCHANT)
    row = support.fetch("agreements", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    # Ordered by round_number ascending, not by created_at (PRD 2.3).
    return support.page(_rounds_of(row_id), derive.round_json)


@bp.post("/perks/agreements/<row_id>/propose")
def propose(row_id):
    auth.require(auth.PARTNER_MANAGER)
    agreement = support.fetch("agreements", row_id)
    body = validate.json_body()
    data = validate.fields(body, NEGOTIATION_TERMS)
    validate.window(data["exclusivity_window_start"], data["exclusivity_window_end"])
    support.occ(agreement, body, "expected_agreement_version")
    if agreement["status"] not in ("DRAFT", "MERCHANT_COUNTERED"):
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "A proposal is only accepted from DRAFT or MERCHANT_COUNTERED.")
    if agreement["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT",
                       "The four-round negotiation budget is exhausted.")
    _file_round(agreement, data, "PARTNER_MANAGER")
    agreement["status"] = "PROVIDER_PROPOSED"
    db.touch(agreement)
    _lift_merchant_to_negotiation(agreement)
    return response.ok(derive.agreement_json(agreement))


@bp.post("/perks/agreements/<row_id>/counter")
def counter(row_id):
    principal = auth.require(auth.MERCHANT)
    agreement = support.fetch("agreements", row_id)
    auth.check_merchant_scope(principal, agreement["merchant_id"])
    body = validate.json_body()
    data = validate.fields(body, NEGOTIATION_TERMS)
    validate.window(data["exclusivity_window_start"], data["exclusivity_window_end"])
    support.occ(agreement, body, "expected_agreement_version")
    if agreement["status"] != "PROVIDER_PROPOSED":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "A counter is only accepted from PROVIDER_PROPOSED.")
    if agreement["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT",
                       "The four-round negotiation budget is exhausted.")
    _file_round(agreement, data, "MERCHANT")
    agreement["status"] = "MERCHANT_COUNTERED"
    db.touch(agreement)
    return response.ok(derive.agreement_json(agreement))


@bp.post("/perks/agreements/<row_id>/decide")
def decide(row_id):
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER)
    agreement = support.fetch("agreements", row_id)
    body = validate.json_body()
    raw_decision = body.get("decision")
    # PRD 3.2: the side that authored the standing round may never accept it,
    # and withdrawal belongs to the PartnerManager alone. Both refusals are
    # ERR_UNAUTHORIZED, which is band 1 and so precedes the state band.
    if raw_decision == "WITHDRAW" and principal.role != auth.PARTNER_MANAGER:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only a PartnerManager may withdraw from negotiation.")
    if raw_decision == "ACCEPT":
        if (agreement["status"] == "PROVIDER_PROPOSED"
                and principal.role != auth.MERCHANT):
            raise ApiError("ERR_UNAUTHORIZED",
                           "The provider may not accept the round it authored.")
        if (agreement["status"] == "MERCHANT_COUNTERED"
                and principal.role != auth.PARTNER_MANAGER):
            raise ApiError("ERR_UNAUTHORIZED",
                           "The merchant may not accept the round it authored.")
    auth.check_merchant_scope(principal, agreement["merchant_id"])
    data = validate.fields(body, [
        {"name": "decision", "type": "enum", "required": True,
         "values": ["ACCEPT", "WITHDRAW"]},
        {"name": "note", "type": "str"},
    ])
    if data["decision"] == "ACCEPT":
        if agreement["status"] not in ("PROVIDER_PROPOSED", "MERCHANT_COUNTERED"):
            raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                           "Acceptance is only possible from a proposed or "
                           "countered agreement.")
        if agreement["round_count"] < 1:
            raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                           "There is no standing round to accept.")
        agreement["accepted_by_role"] = (
            "MERCHANT" if agreement["status"] == "PROVIDER_PROPOSED"
            else "PARTNER_MANAGER")
        agreement["status"] = "ACCEPTED"
        db.touch(agreement)
    else:
        if agreement["status"] not in ("DRAFT", "PROVIDER_PROPOSED",
                                      "MERCHANT_COUNTERED"):
            raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                           "Withdrawal is only possible during negotiation.")
        agreement["status"] = "WITHDRAWN"
        agreement["terminated_reason"] = "WITHDRAWN_IN_NEGOTIATION"
        db.touch(agreement)
        merchant = db.merchants.get(agreement["merchant_id"])
        if merchant is not None and merchant["status"] == "IN_NEGOTIATION":
            survives = any(
                a["merchant_id"] == merchant["id"]
                and a["status"] in ("PROVIDER_PROPOSED", "MERCHANT_COUNTERED",
                                    "ACCEPTED", "ACTIVE")
                for a in db.agreements.values())
            if not survives:
                merchant["status"] = "PROSPECT"
                db.touch(merchant)
    return response.ok(derive.agreement_json(agreement))


def _exclusivity_overlaps(agreement):
    """Half-open windows: two windows that merely touch do not overlap."""
    start = agreement["exclusivity_window_start"]
    end = agreement["exclusivity_window_end"]
    if start is None or end is None:
        return False
    for other in db.agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["status"] != "ACTIVE" or not other["exclusivity_granted"]:
            continue
        if other["category"] != agreement["category"]:
            continue
        if other["region_code"] != agreement["region_code"]:
            continue
        other_start = other["exclusivity_window_start"]
        other_end = other["exclusivity_window_end"]
        if other_start is None or other_end is None:
            continue
        if other_start < end and start < other_end:
            return True
    return False


@bp.post("/perks/agreements/<row_id>/activate")
def activate(row_id):
    auth.require(auth.PARTNER_MANAGER)
    agreement = support.fetch("agreements", row_id)
    if agreement["status"] != "ACCEPTED":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "Activation is only accepted from ACCEPTED.")
    merchant = db.merchants.get(agreement["merchant_id"])
    if merchant is None or merchant["status"] not in ("PROSPECT", "IN_NEGOTIATION",
                                                      "ACTIVE"):
        raise ApiError("ERR_MERCHANT_SUSPENDED",
                       "The partner is not in a state that permits activation.")
    if agreement["exclusivity_requested"]:
        # The overlap check runs BEFORE the terms-completeness check (PRD 3.2).
        if _exclusivity_overlaps(agreement):
            raise ApiError("ERR_EXCLUSIVITY_OVERLAP",
                           "A live exclusivity window already covers this "
                           "category and region.")
        if (agreement["exclusivity_window_start"] is None
                or agreement["exclusivity_window_end"] is None):
            raise ApiError("ERR_EXCLUSIVITY_TERMS_MISSING",
                           "The standing terms carry no exclusivity window.")
        agreement["exclusivity_granted"] = True
    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = clock.now()
    db.touch(agreement)
    if merchant["status"] != "ACTIVE":
        merchant["status"] = "ACTIVE"
        db.touch(merchant)
    return response.ok(derive.agreement_json(agreement))


def _breaches_coverage_floor(agreement):
    remaining = sum(
        1 for a in db.agreements.values()
        if a["id"] != agreement["id"]
        and a["status"] == "ACTIVE"
        and a["category"] == agreement["category"]
        and a["region_code"] == agreement["region_code"])
    if remaining > 0:
        return False
    for employer in db.employers.values():
        if derive.program_posture(employer) != "LIVE":
            continue
        if employer["region_code"] != agreement["region_code"]:
            continue
        featured = employer["featured_categories"] or []
        if agreement["category"] in featured:
            return True
    return False


@bp.post("/perks/agreements/<row_id>/terminate")
def terminate(row_id):
    auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN)
    agreement = support.fetch("agreements", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "terminated_reason", "type": "str", "required": True},
    ])
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "Only an ACTIVE agreement can be terminated.")
    if _breaches_coverage_floor(agreement):
        raise ApiError("ERR_CATEGORY_COVERAGE_FLOOR",
                       "An employer still features this category in this region.")
    cascade.terminate_agreement(agreement, data["terminated_reason"])
    return response.ok(derive.agreement_json(agreement))
