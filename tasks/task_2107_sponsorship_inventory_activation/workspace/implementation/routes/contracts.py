"""Contracts: drafting, clause entitlements, the approval cycle, unwinding,
close-out, surveys and the ROI/ROO projection (PRD 3.4, 3.5, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request, g

import db
from db import store, new_row, touch, touch_if, set_fields, ordered
from errors import ApiError
from middleware import endpoint, sponsor_scope_guard
from response import ok, created, paginate
from services import calc
from services.cascade import rollup_property, rescore_sponsor
from services.serialize import contract_out, entitlement_out, survey_out
from routes.properties import get_property_or_404
from routes.sponsors import get_sponsor_or_404
from routes.inventory_assets import get_asset_or_404
from util import (body_of, fail, v_str, v_int, v_enum, v_dt, v_pagination,
                  v_query_enum, dec, rhu_int, num2, num4)

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = {"DRAFT", "SUBMITTED", "COUNTERSIGNED", "ACTIVE", "CLOSED", "TERMINATED"}
EXCLUSIVITY_SCOPES = {"NONE", "CATEGORY"}
IN_KIND_CATEGORIES = {"MEDIA_TRADE", "PRODUCT", "SERVICES", "TICKETS"}
RENEWAL_INTENTS = {"NO", "MAYBE", "YES"}
ENTITLEMENT_STATUSES = {"PENDING", "PARTIAL", "FULFILLED", "SHORTFALL", "WAIVED"}
BASES = {"VERIFIED", "GROSS"}

READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover",
              "ActivationManager", "PerformanceAuditor", "SponsorContact"]
LIST_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover",
              "PerformanceAuditor", "SponsorContact"]
REPORT_ROLES = ["PropertyAdmin", "ContractApprover", "PerformanceAuditor", "SponsorContact"]
SURVEY_READ_ROLES = ["PropertyAdmin", "ContractApprover", "PerformanceAuditor", "SponsorContact"]


def get_contract_or_404(contract_id):
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404)
    return contract


# ==========================================================================
# drafting
# ==========================================================================
@bp.post("/contracts")
@endpoint(["SponsorshipSeller"])
def create_contract():
    body = body_of(request)
    sponsor_id = v_str(body, "sponsor_id", min_len=1)
    property_id = v_str(body, "property_id", min_len=1)
    term_start_raw, term_start = v_dt(body, "term_start")
    term_end_raw, term_end = v_dt(body, "term_end")
    exclusivity_scope = v_enum(body, "exclusivity_scope", EXCLUSIVITY_SCOPES,
                               required=False, default="NONE")
    in_kind_declared = v_int(body, "in_kind_declared_value_cents", required=False, default=0, min_v=0)
    in_kind_category = v_enum(body, "in_kind_category", IN_KIND_CATEGORIES,
                              required=False, default="PRODUCT")

    sponsor = get_sponsor_or_404(sponsor_id)
    prop = get_property_or_404(property_id)

    if term_start < prop["_season_start_dt"]:
        fail("term_start must be at or after the property's season_start.")
    if term_end <= term_start:
        fail("term_end must be strictly after term_start.")
    if term_end > prop["_season_end_dt"]:
        fail("term_end must be at or before the property's season_end.")

    row = new_row()
    row.update({
        "sponsor_id": sponsor["id"],
        "property_id": prop["id"],
        "rate_card_id": None,
        "status": "DRAFT",
        "fulfillment_status": "NOT_STARTED",
        "term_start": term_start_raw,
        "_term_start_dt": term_start,
        "term_end": term_end_raw,
        "_term_end_dt": term_end,
        "exclusivity_scope": exclusivity_scope,
        "in_kind_declared_value_cents": in_kind_declared,
        "in_kind_category": in_kind_category,
        "gross_entitlement_value_cents": 0,
        "volume_discount_pct": Decimal("0.00"),
        "cash_value_cents": 0,
        "in_kind_recognized_value_cents": 0,
        "total_recognized_value_cents": 0,
        "delivered_media_value_cents": 0,
        "makegood_credit_cents": 0,
        "revision_round": 0,
        "submitted_by_user_id": None,
        "countersigned_by_user_id": None,
    })
    store.contracts[row["id"]] = row
    return created(contract_out(row))


@bp.get("/contracts/<contract_id>")
@endpoint(READ_ROLES)
def read_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    sponsor_scope_guard(contract)
    return ok(contract_out(contract))


@bp.get("/contracts")
@endpoint(LIST_ROLES)
def list_contracts():
    sponsor_id = request.args.get("sponsor_id")
    property_id = request.args.get("property_id")
    rate_card_id = request.args.get("rate_card_id")

    # rung 4 — sponsor scoping precedes query-parameter shape validation
    if g.role == "SponsorContact":
        if sponsor_id is not None and sponsor_id != g.user_id:
            raise ApiError("ERR_SPONSOR_SCOPE_VIOLATION", 403)
        sponsor_id = g.user_id

    status = v_query_enum(request, "status", CONTRACT_STATUSES)
    limit, offset = v_pagination(request)

    rows = list(store.contracts.values())
    if sponsor_id is not None:
        rows = [r for r in rows if r["sponsor_id"] == sponsor_id]
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if rate_card_id is not None:
        rows = [r for r in rows if r["rate_card_id"] == rate_card_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(ordered(rows), limit, offset, contract_out)


# ==========================================================================
# clause entitlements
# ==========================================================================
@bp.post("/contracts/<contract_id>/entitlements")
@endpoint(["SponsorshipSeller"])
def create_entitlement(contract_id):
    contract = get_contract_or_404(contract_id)
    body = body_of(request)
    inventory_asset_id = v_str(body, "inventory_asset_id", min_len=1)
    clause_ref = v_str(body, "clause_ref", min_len=1, max_len=24)
    promised_units = v_int(body, "promised_units", min_v=1)

    asset = get_asset_or_404(inventory_asset_id)

    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    for existing in db.entitlements_of_contract(contract["id"]):
        if existing["clause_ref"] == clause_ref:
            raise ApiError("ERR_DUPLICATE_CLAUSE_REF", 409)

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "inventory_asset_id": asset["id"],
        "clause_ref": clause_ref,
        "asset_class": asset["asset_class"],
        "promised_units": promised_units,
        "unit_value_cents": 0,
        "gross_value_cents": 0,
        "delivered_units": 0,
        "delivery_pct": Decimal("0.00"),
        "status": "PENDING",
        "makegood_credit_cents": 0,
    })
    store.entitlements[row["id"]] = row
    return created(entitlement_out(row))


# ==========================================================================
# lifecycle
# ==========================================================================
@bp.post("/contracts/<contract_id>/submit")
@endpoint(["SponsorshipSeller"])
def submit_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    prop = store.properties.get(contract["property_id"])
    if prop is None or prop["status"] not in ("SELLING", "IN_SEASON"):
        raise ApiError("ERR_PROPERTY_NOT_SELLING", 409)
    if not db.entitlements_of_contract(contract["id"]):
        raise ApiError("ERR_NO_ENTITLEMENTS", 409)
    if contract["revision_round"] > 3:
        raise ApiError("ERR_REVISION_LIMIT_REACHED", 409)

    contract["status"] = "SUBMITTED"
    contract["submitted_by_user_id"] = g.user_id
    touch(contract)
    return ok(contract_out(contract))


@bp.post("/contracts/<contract_id>/return")
@endpoint(["ContractApprover"])
def return_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    body = body_of(request)
    v_str(body, "reason", required=False)
    if contract["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)

    contract["status"] = "DRAFT"
    contract["revision_round"] = contract["revision_round"] + 1
    contract["submitted_by_user_id"] = None
    touch(contract)
    return ok(contract_out(contract))


@bp.post("/contracts/<contract_id>/countersign")
@endpoint(["ContractApprover"])
def countersign_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    body = body_of(request)
    expected_property_version = v_int(body, "expected_property_version")

    if contract["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)

    prop = store.properties.get(contract["property_id"])
    published = db.published_rate_cards(contract["property_id"]) if prop else []
    if len(published) != 1:
        raise ApiError("ERR_NO_PUBLISHED_RATE_CARD", 409)
    card = published[0]

    if expected_property_version != prop["version"]:
        raise ApiError("ERR_PROPERTY_VERSION_STALE", 412)

    if g.user_id == contract["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)

    sponsor = store.sponsors.get(contract["sponsor_id"])
    for other in db.contracts_of_property(prop["id"]):
        if other["id"] == contract["id"] or other["status"] not in ("COUNTERSIGNED", "ACTIVE"):
            continue
        other_sponsor = store.sponsors.get(other["sponsor_id"])
        if other_sponsor is None or sponsor is None:
            continue
        if other_sponsor["category"] != sponsor["category"]:
            continue
        if other["exclusivity_scope"] == "CATEGORY" or contract["exclusivity_scope"] == "CATEGORY":
            raise ApiError("ERR_CATEGORY_EXCLUSIVITY_CONFLICT", 409)

    lines = db.lines_of_card(card["id"])
    by_class = dict((l["asset_class"], l) for l in lines)
    entitlements = db.entitlements_of_contract(contract["id"])
    for ent in entitlements:
        if ent["asset_class"] not in by_class:
            raise ApiError("ERR_RATE_LINE_MISSING", 409)

    # --- money, computed but not yet persisted ---------------------------
    priced = []
    for ent in entitlements:
        unit_value, gross_value = calc.entitlement_unit_valuation(
            by_class[ent["asset_class"]], ent["promised_units"],
            prop["seasonality_index"], contract["exclusivity_scope"])
        priced.append((ent, unit_value, gross_value))

    projected = [{"status": ent["status"], "gross_value_cents": gross}
                 for ent, _unit, gross in priced]
    rollup = calc.contract_value_rollup(
        projected, contract["in_kind_declared_value_cents"],
        contract["in_kind_category"], "CONSERVATIVE")

    ceiling = rhu_int(dec(prop["inventory_target_value_cents"]) * calc.OVERSELL_ALLOWANCE)
    if prop["committed_gross_value_cents"] + rollup["total_recognized_value_cents"] > ceiling:
        raise ApiError("ERR_INVENTORY_VALUE_EXCEEDED", 409)

    # --- commit ----------------------------------------------------------
    for ent, unit_value, gross_value in priced:
        ent["unit_value_cents"] = unit_value
        ent["gross_value_cents"] = gross_value
        touch(ent)

    contract["rate_card_id"] = card["id"]
    contract["countersigned_by_user_id"] = g.user_id
    contract.update(rollup)
    contract["status"] = "COUNTERSIGNED"
    touch(contract)

    if sponsor is not None and sponsor["status"] == "PROSPECT":
        sponsor["status"] = "ACTIVE"
        touch(sponsor)

    rollup_property(prop)
    return ok(contract_out(contract))


@bp.post("/contracts/<contract_id>/activate")
@endpoint(["ContractApprover"])
def activate_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    if contract["status"] != "COUNTERSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    prop = store.properties.get(contract["property_id"])
    if prop is None or prop["status"] != "IN_SEASON":
        raise ApiError("ERR_PROPERTY_NOT_SELLING", 409)
    if store.now() < contract["_term_start_dt"]:
        raise ApiError("ERR_TERM_NOT_STARTED", 409)

    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(contract_out(contract))


@bp.post("/contracts/<contract_id>/terminate")
@endpoint(["ContractApprover"])
def terminate_contract(contract_id):
    from services.cascade import release_assignments, release_asset_units

    contract = get_contract_or_404(contract_id)
    body = body_of(request)
    v_str(body, "reason", required=False)
    if contract["status"] not in ("COUNTERSIGNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409)

    contract["status"] = "TERMINATED"
    touch(contract)

    for ent in db.entitlements_of_contract(contract["id"]):
        if ent["status"] not in ("PENDING", "PARTIAL"):
            continue
        ent["status"] = "WAIVED"
        touch(ent)
        for booking in db.bookings_of_entitlement(ent["id"]):
            if booking["status"] != "SCHEDULED":
                continue
            booking["status"] = "PREEMPTED"
            touch(booking)
            release_asset_units(booking)
            release_assignments(booking)

    prop = store.properties.get(contract["property_id"])
    if prop is not None:
        rollup_property(prop)
    return ok(contract_out(contract))


@bp.post("/contracts/<contract_id>/close")
@endpoint(["ContractApprover"])
def close_contract(contract_id):
    contract = get_contract_or_404(contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    if store.now() < contract["_term_end_dt"]:
        raise ApiError("ERR_TERM_NOT_ENDED", 409)
    for booking in db.bookings_of_contract(contract["id"]):
        if booking["status"] == "SCHEDULED":
            raise ApiError("ERR_OPEN_BOOKINGS", 409)

    entitlements = db.entitlements_of_contract(contract["id"])

    # 1. audited in-kind re-valuation
    audited = calc.in_kind_recognized_valuation(
        contract["in_kind_declared_value_cents"], contract["in_kind_category"],
        contract["cash_value_cents"], "AUDITED")
    contract["in_kind_recognized_value_cents"] = audited
    contract["total_recognized_value_cents"] = contract["cash_value_cents"] + audited

    # 2. makegood credit, while statuses still reflect what was delivered
    pool, allocation = calc.makegood_credit_allocation(contract, entitlements)
    contract["makegood_credit_cents"] = pool
    for ent in entitlements:
        if ent["id"] in allocation:
            touch_if(ent, set_fields(ent, makegood_credit_cents=allocation[ent["id"]]))

    # 3. freeze entitlement statuses
    for ent in entitlements:
        if ent["status"] in ("PENDING", "PARTIAL"):
            ent["status"] = "SHORTFALL"
            touch(ent)

    # 4. finalize the fulfilment dimension
    contract["fulfillment_status"] = "SHORTFALL" if any(
        e["status"] == "SHORTFALL" for e in entitlements) else "FULFILLED"

    # 5. lifecycle status
    contract["status"] = "CLOSED"
    touch(contract)

    # 6. property reconciliation
    prop = store.properties.get(contract["property_id"])
    if prop is not None:
        rollup_property(prop)

    # 7. renewal outlook and churn
    sponsor = store.sponsors.get(contract["sponsor_id"])
    if sponsor is not None:
        _score, band = rescore_sponsor(sponsor)
        remaining = [c for c in db.contracts_of_sponsor(sponsor["id"])
                     if c["status"] in ("COUNTERSIGNED", "ACTIVE")]
        if band == "LOW" and not remaining:
            touch_if(sponsor, set_fields(sponsor, status="CHURNED"))

    return ok(contract_out(contract))


# ==========================================================================
# sponsor surveys
# ==========================================================================
@bp.post("/contracts/<contract_id>/surveys")
@endpoint(["SponsorContact"])
def create_survey(contract_id):
    contract = get_contract_or_404(contract_id)
    sponsor_scope_guard(contract)
    body = body_of(request)
    satisfaction = v_int(body, "satisfaction_score", min_v=1, max_v=10)
    activation_quality = v_int(body, "activation_quality_score", min_v=1, max_v=10)
    reporting_quality = v_int(body, "reporting_quality_score", min_v=1, max_v=10)
    renewal_intent = v_enum(body, "renewal_intent", RENEWAL_INTENTS)

    if contract["status"] not in ("ACTIVE", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", 409)

    row = new_row(versioned=False)
    row.update({
        "contract_id": contract["id"],
        "satisfaction_score": satisfaction,
        "activation_quality_score": activation_quality,
        "reporting_quality_score": reporting_quality,
        "renewal_intent": renewal_intent,
        "submitted_by_user_id": g.user_id,
        "composite_score": calc.survey_composite_score(
            satisfaction, activation_quality, reporting_quality, renewal_intent),
    })
    store.surveys[row["id"]] = row

    sponsor = store.sponsors.get(contract["sponsor_id"])
    if sponsor is not None:
        rescore_sponsor(sponsor)
    return created(survey_out(row))


@bp.get("/contracts/<contract_id>/surveys")
@endpoint(SURVEY_READ_ROLES)
def list_surveys(contract_id):
    contract = get_contract_or_404(contract_id)
    sponsor_scope_guard(contract)
    limit, offset = v_pagination(request)
    return paginate(db.surveys_of_contract(contract["id"]), limit, offset, survey_out)


# ==========================================================================
# ROI / ROO projection
# ==========================================================================
@bp.get("/contracts/<contract_id>/roi-report")
@endpoint(REPORT_ROLES)
def roi_report(contract_id):
    contract = get_contract_or_404(contract_id)
    sponsor_scope_guard(contract)
    basis = v_query_enum(request, "basis", BASES) or "VERIFIED"

    entitlements = db.entitlements_of_contract(contract["id"])
    by_id = dict((e["id"], e) for e in entitlements)
    bookings = db.bookings_of_contract(contract["id"])

    if basis == "VERIFIED":
        counted_bookings = [b for b in bookings
                            if b["status"] == "DELIVERED" and b["proof_state"] == "VERIFIED"]
        proof_states = ("VERIFIED",)
    else:
        counted_bookings = [b for b in bookings
                            if b["status"] == "DELIVERED"
                            and b["proof_state"] in ("NONE", "PENDING_REVIEW", "VERIFIED")]
        proof_states = ("SUBMITTED", "VERIFIED")

    media_value_cents = 0
    for b in counted_bookings:
        ent = by_id.get(b["entitlement_id"])
        if ent is not None:
            media_value_cents += b["units_booked"] * ent["unit_value_cents"]

    impressions_total = 0
    for b in bookings:
        if b["status"] in ("CANCELLED", "PREEMPTED"):
            continue
        for p in db.proofs_of_booking(b["id"]):
            if p["evidence_type"] in ("IMPRESSIONS", "SOCIAL") and p["status"] in proof_states:
                impressions_total += p["measured_value"]

    total_recognized = contract["total_recognized_value_cents"]
    roi_ratio = 0.0 if total_recognized == 0 else num4(
        dec(media_value_cents) / dec(total_recognized))

    considered = [e for e in entitlements if e["status"] != "WAIVED"]
    promised = sum(e["promised_units"] for e in considered)
    delivered_capped = sum(min(e["delivered_units"], e["promised_units"]) for e in considered)
    roo = 100.00 if promised == 0 else num2(
        Decimal("100") * dec(delivered_capped) / dec(promised))

    if impressions_total == 0:
        cpm = None
    else:
        cpm = num2(dec(total_recognized) * Decimal("1000") / dec(impressions_total))

    return ok({
        "contract_id": contract["id"],
        "basis": basis,
        "media_value_cents": media_value_cents,
        "impressions_total": impressions_total,
        "roi_ratio": roi_ratio,
        "roo_attainment_pct": roo,
        "cost_per_thousand_impressions_cents": cpm,
        "makegood_credit_cents": contract["makegood_credit_cents"],
    })
