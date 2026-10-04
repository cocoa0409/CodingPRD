"""Dealer, dealer-agreement, performance-review and party-registration routes."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import db
import middleware
import registry as reg
import response as resp
from errors import (
    ApiError,
    E_AGREEMENT_NOT_FOUND,
    E_DEALER_NOT_FOUND,
    E_DEALER_TERMINATED,
    E_EXCLUSIVITY_MISMATCH,
    E_INVALID_STATE,
    E_REVIEW_AWAITING_CIRCUMSTANCE,
    E_REVIEW_NOT_FOUND,
    E_REVIEW_OUTSTANDING,
    E_STALE_VERSION,
    E_TERRITORY_OVERLAP,
    E_TOOLING_INCOMPLETE,
)
from request import PRODUCT_FAMILIES, Request
from routes._common import page_params, paged_response, q
from services import core as svc

BASE = "/dealer-network"


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------
def create_dealer(request: Request):
    dealer = {
        "id": db.new_id(),
        "legal_name": request.string("legal_name"),
        "home_state_code": request.string("home_state_code"),
        "territory_code": request.string("territory_code"),
        "status": "PENDING_AGREEMENT",
        "certified_family_count": 0,
        "trusted_commitment_count": 0,
        "open_backorder_units": 0,
        "market_share_pct": 0.0,
    }
    svc.init_common(dealer)
    for existing in db.rows("dealers"):
        if existing["territory_code"] == dealer["territory_code"] and existing["legal_name"] == dealer["legal_name"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "a dealer with this legal name already stands for this territory",
                http_status=409,
            )
    db.insert("dealers", dealer)
    return resp.ok(svc.serialize("dealers", dealer)), 201


def list_dealers(request: Request):
    limit, offset = page_params(request)
    filters = {
        "territory_code": q(request, "territory_code"),
        "status": q(request, "status"),
        "home_state_code": q(request, "home_state_code"),
    }
    records = [r for r in db.rows("dealers") if svc.matches_filters(r, filters)]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("dealers", r) for r in records], limit, offset), 200


def get_dealer(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own dealership.")
    if actor.role == "DealerSalesManager" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer sales manager may read only its own dealership.")
    with svc.suppressing_touches():
        svc.recompute_certified_family_count(dealer)
        svc.recompute_trusted_commitment_count(dealer)
        svc.recompute_open_backorder_units(dealer)
        svc.recompute_market_share_pct(dealer)
    return resp.ok(svc.serialize("dealers", dealer)), 200


def terminate_dealer(request: Request):
    dealer = svc.get_dealer(request.path_params["id"])
    if dealer["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    agreements = svc.dealer_agreements(dealer["id"])
    for agreement in agreements:
        if agreement["status"] != "TERMINATED":
            raise ApiError(E_DEALER_TERMINATED, "the dealer still holds a live agreement")
    leaving = dealer["status"]
    if leaving == "ACTIVE":
        for support in db.rows("support_agreements"):
            if support["dealer_id"] == dealer["id"] and support["status"] != "TERMINATED":
                support["status"] = "TERMINATED"
                svc.touch(support)
                svc.refresh_serial_coverage(support["machine_serial"])
        for record in db.rows("certification_records"):
            if record["dealer_id"] == dealer["id"] and not record.get("revoked"):
                record["revoked"] = True
                svc.touch(record)
    elif leaving == "SUSPENDED":
        for support in db.rows("support_agreements"):
            if support["dealer_id"] == dealer["id"] and support["status"] != "TERMINATED":
                support["status"] = "TERMINATED"
                svc.touch(support)
                svc.refresh_serial_coverage(support["machine_serial"])
    else:  # PENDING_AGREEMENT
        for record in db.rows("certification_records"):
            if record["dealer_id"] == dealer["id"] and not record.get("revoked"):
                record["revoked"] = True
                svc.touch(record)
    dealer["status"] = "TERMINATED"
    svc.touch(dealer)
    svc.refresh_dealer_derived(dealer)
    for agreement in agreements:
        svc.refresh_agreement_derived(agreement)
    return resp.ok(svc.serialize("dealers", dealer)), 200


# ---------------------------------------------------------------------------
# Dealer agreements
# ---------------------------------------------------------------------------
def create_agreement(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    if dealer["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    svc.check_expected_version(dealer, request.raw("expected_dealer_version"), E_STALE_VERSION)

    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    territory_code = request.string("territory_code")
    exclusivity_level = request.enum("exclusivity_level", ["EXCLUSIVE", "SHARED"], required=False, default="SHARED")
    start_at = request.datetime("start_at")
    end_at = request.datetime("end_at")
    plan_share = request.number("performance_plan_share_pct")

    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    if plan_share < 0 or plan_share > 100:
        raise ApiError("ERR_INVALID_REQUEST", "performance_plan_share_pct must fall between 0 and 100")
    if exclusivity_level == "EXCLUSIVE" and territory_code != dealer["territory_code"]:
        raise ApiError(E_EXCLUSIVITY_MISMATCH)

    agreement = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "product_family": product_family,
        "territory_code": territory_code,
        "exclusivity_level": exclusivity_level,
        "start_at": db.clock_iso(start_at),
        "end_at": db.clock_iso(end_at),
        "status": "DRAFT",
        "performance_plan_share_pct": plan_share,
        "performance_actual_share_pct": 0.0,
        "certified_technician_count": 0,
        "tooling_compliance_status": "NOT_SUBMITTED",
        "trusted_commitment": False,
        "closed_at": None,
    }
    svc.init_common(agreement)
    db.insert("dealer_agreements", agreement)
    svc.refresh_agreement_derived(agreement)
    svc.bump(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 201


def list_agreements(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "territory_code": q(request, "territory_code"),
        "status": q(request, "status"),
    }
    records = [r for r in db.rows("dealer_agreements") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("dealer_agreements", r) for r in records], limit, offset), 200


def get_agreement(request: Request, actor):
    agreement = svc.get_agreement(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != agreement["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own agreements.")
    with svc.suppressing_touches():
        svc.refresh_agreement_derived(agreement)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def list_dealer_agreements(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own agreements.")
    limit, offset = page_params(request)
    records = svc.sort_by_created(svc.dealer_agreements(dealer["id"]))
    with svc.suppressing_touches():
        for agreement in records:
            svc.refresh_agreement_derived(agreement)
    return paged_response([svc.serialize("dealer_agreements", r) for r in records], limit, offset), 200


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _supersede_prior_representation(agreement: dict) -> None:
    """Revive the oldest superseded EXCLUSIVE row so it joins the overlap test."""
    candidates = [
        a
        for a in db.rows("dealer_agreements")
        if a["id"] != agreement["id"]
        and a["exclusivity_level"] == "EXCLUSIVE"
        and a["status"] == "TERMINATED"
        and a["territory_code"] == agreement["territory_code"]
        and a["product_family"] == agreement["product_family"]
        and a["end_at"] is not None
        and _iso(a["end_at"]) <= db.now()
    ]
    candidates.sort(key=lambda a: (a["created_at"], a["id"]))
    if not candidates:
        return
    revived = candidates[0]
    now = db.now()
    revived["start_at"] = db.clock_iso(now)
    revived["end_at"] = db.clock_iso(now + timedelta(days=365))
    revived["status"] = "SUBMITTED"
    svc.touch(revived)


def _iso(value: str):
    return db.as_dt(value)


def submit_agreement(request: Request):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    if agreement["status"] != "DRAFT":
        raise ApiError(E_INVALID_STATE)

    start_at = _iso(agreement["start_at"])
    end_at = _iso(agreement["end_at"])

    _supersede_prior_representation(agreement)

    if agreement["exclusivity_level"] == "EXCLUSIVE":
        for other in db.rows("dealer_agreements"):
            if other["id"] == agreement["id"]:
                continue
            if other["status"] not in ("SUBMITTED", "ACTIVE"):
                continue
            if other["territory_code"] != agreement["territory_code"]:
                continue
            if other["product_family"] != agreement["product_family"]:
                continue
            if other["exclusivity_level"] != "EXCLUSIVE":
                continue
            if _overlaps(start_at, end_at, _iso(other["start_at"]), _iso(other["end_at"])):
                raise ApiError(E_TERRITORY_OVERLAP, "an exclusive representation interval already covers this window")

    if Decimal(str(agreement["performance_plan_share_pct"])) > Decimal("100"):
        raise ApiError(E_TERRITORY_OVERLAP, "the planned share sits above 100")

    agreement["status"] = "SUBMITTED"
    svc.touch(agreement)
    svc.refresh_agreement_derived(agreement)
    for commitment in db.rows("parts_commitments"):
        if commitment["agreement_id"] == agreement["id"]:
            svc.set_deferred_rule(commitment["id"], False)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def activate_agreement(request: Request):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    if agreement["status"] != "SUBMITTED":
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(agreement["dealer_id"])

    svc.refresh_agreement_derived(agreement)
    if agreement["tooling_compliance_status"] != "COMPLIANT":
        raise ApiError(E_TOOLING_INCOMPLETE)
    if int(agreement["certified_technician_count"]) < 2:
        raise ApiError(E_TOOLING_INCOMPLETE)
    commitments = [c for c in db.rows("parts_commitments") if c["agreement_id"] == agreement["id"]]
    if not commitments or all(c["status"] == "PLANNED" for c in commitments):
        raise ApiError(E_INVALID_STATE, "no commitment of this agreement has left PLANNED")
    for commitment in commitments:
        if int(commitment["required_stocking_units_final"]) < 1:
            raise ApiError("ERR_STOCKING_MANDATE_UNMET")
    if dealer["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)

    agreement["status"] = "ACTIVE"
    svc.touch(agreement)
    svc.recompute_agreement_commitment_mandates(agreement)
    svc.recompute_trusted_commitment(agreement)
    svc.recompute_trusted_commitment_count(dealer)
    svc.sync_dealer_status(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def mark_underperforming(request: Request):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    if agreement["status"] != "ACTIVE":
        raise ApiError(E_INVALID_STATE)
    for review in db.rows("performance_reviews"):
        if review["agreement_id"] == agreement["id"] and review["status"] != "EVALUATED":
            raise ApiError(E_REVIEW_OUTSTANDING)

    agreement["status"] = "PERFORMANCE_DEFICIENT"
    svc.touch(agreement)
    for commitment in db.rows("parts_commitments"):
        if commitment["agreement_id"] != agreement["id"]:
            continue
        if commitment["status"] in ("COMPLETE",):
            continue
        commitment["status"] = "PERFORMANCE_DEFICIENT"
        commitment["backorder_opened_at"] = db.stamp()
        # Raise the required stocking level by one availability tier.
        commitment["required_stocking_units_final"] = svc.raise_one_tier(int(commitment["required_stocking_units_final"]))
        svc.touch(commitment)
        svc.recompute_available_units(commitment)
        svc.set_deferred_rule(commitment["id"], False)
    dealer = svc.get_dealer(agreement["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def reinstate_agreement(request: Request, actor):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    dealer = svc.get_dealer(agreement["dealer_id"])

    if agreement["status"] == "PERFORMANCE_DEFICIENT":
        for review in db.rows("performance_reviews"):
            if review["agreement_id"] != agreement["id"]:
                continue
            if review["status"] != "EVALUATED":
                raise ApiError(E_REVIEW_OUTSTANDING)
            if review.get("performance_ratio_pct") is None or Decimal(str(review["performance_ratio_pct"])) < Decimal("80.0"):
                raise ApiError(E_REVIEW_OUTSTANDING, "a review of this agreement falls short of the reinstatement floor")
    elif agreement["status"] == "SUSPENDED":
        svc.refresh_agreement_derived(agreement)
        if agreement["tooling_compliance_status"] != "COMPLIANT":
            raise ApiError(E_TOOLING_INCOMPLETE)
        if dealer["status"] == "TERMINATED":
            raise ApiError(E_DEALER_TERMINATED)
    else:
        raise ApiError(E_INVALID_STATE)

    agreement["status"] = "ACTIVE"
    svc.touch(agreement)
    for commitment in db.rows("parts_commitments"):
        if commitment["agreement_id"] == agreement["id"]:
            svc.set_deferred_rule(commitment["id"], True)
    svc.sync_dealer_status(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def suspend_agreement(request: Request):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    if agreement["status"] != "ACTIVE":
        raise ApiError(E_INVALID_STATE)
    for review in db.rows("performance_reviews"):
        if review["agreement_id"] == agreement["id"] and review["status"] == "CIRCUMSTANCE_PENDING":
            raise ApiError(E_REVIEW_AWAITING_CIRCUMSTANCE)

    agreement["status"] = "SUSPENDED"
    svc.touch(agreement)
    for commitment in db.rows("parts_commitments"):
        if commitment["agreement_id"] == agreement["id"]:
            svc.set_deferred_rule(commitment["id"], False)
    dealer = svc.get_dealer(agreement["dealer_id"])
    svc.sync_dealer_status(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


def terminate_agreement(request: Request):
    agreement = svc.get_agreement(request.path_params["id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError(E_DEALER_TERMINATED)
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(E_INVALID_STATE)

    commitments = [c for c in db.rows("parts_commitments") if c["agreement_id"] == agreement["id"]]
    commitment_ids = {c["id"] for c in commitments}
    leaving_active = agreement["status"] == "ACTIVE"

    if svc.has_batch_open_or_ordered(commitment_ids):
        raise ApiError("ERR_AGREEMENT_COMMITMENT_OPEN")
    if leaving_active:
        for commitment in commitments:
            if commitment["status"] == "COMPLETE":
                continue
            if commitment["status"] == "CORE_PENDING" and int(commitment["credit_balance_cents"]) == 0:
                continue
            raise ApiError("ERR_AGREEMENT_COMMITMENT_OPEN", "a commitment of this agreement is unsettled")

    agreement["status"] = "TERMINATED"
    agreement["closed_at"] = db.stamp()
    svc.touch(agreement)

    if leaving_active:
        for commitment in commitments:
            if commitment["status"] == "ACTIVE" or commitment["status"] == "ORDER_READY":
                commitment["status"] = "SUSPENDED"
                svc.touch(commitment)
        dealer = svc.get_dealer(agreement["dealer_id"])
        for support in db.rows("support_agreements"):
            if support["dealer_id"] != dealer["id"]:
                continue
            if support["status"] == "ACTIVE":
                support["status"] = "TERMINATED"
                svc.touch(support)
                svc.refresh_serial_coverage(support["machine_serial"])

    dealer = svc.get_dealer(agreement["dealer_id"])
    svc.recompute_certified_family_count(dealer)
    svc.recompute_trusted_commitment(agreement)
    svc.recompute_trusted_commitment_count(dealer)
    svc.sync_dealer_status(dealer)

    if all(a["status"] == "TERMINATED" for a in svc.dealer_agreements(dealer["id"])):
        dealer["status"] = "TERMINATED"
        svc.touch(dealer)
    return resp.ok(svc.serialize("dealer_agreements", agreement)), 200


# ---------------------------------------------------------------------------
# Performance reviews
# ---------------------------------------------------------------------------
def create_review(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    agreement_id = request.string("agreement_id")
    agreement = svc.get_agreement(agreement_id)
    svc.check_expected_version(agreement, request.raw("expected_dealeragreement_version"), E_STALE_VERSION)

    period_start = request.datetime("period_start")
    period_end = request.datetime("period_end")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST", "period_end must be strictly after period_start")
    sampled = request.integer("sampled_service_orders")
    met = request.integer("met_sla_service_orders")
    if met > sampled:
        raise ApiError("ERR_INVALID_REQUEST", "met_sla_service_orders must not exceed sampled_service_orders")

    review = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "agreement_id": agreement_id,
        "period_start": db.clock_iso(period_start),
        "period_end": db.clock_iso(period_end),
        "status": "DRAFT",
        "actual_territory_machine_units": request.integer("actual_territory_machine_units"),
        "territory_market_machine_units": request.integer("territory_market_machine_units"),
        "actual_market_share_pct": None,
        "performance_ratio_pct": None,
        "quality_deficiency_pp": None,
        "quality_deficient": False,
        "sampled_service_orders": sampled,
        "met_sla_service_orders": met,
        "discrepancy_pp": 0.0,
        "circumstance_note": request.raw("circumstance_note"),
        "loyalty_score": 0.0,
    }
    review["created_at"] = db.stamp()
    db.insert("performance_reviews", review)
    svc.compute_review_share(review)
    svc.bump(agreement)
    return resp.ok(svc.serialize("performance_reviews", review)), 201


def list_reviews(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "agreement_id": q(request, "agreement_id"),
        "status": q(request, "status"),
        "period_start": q(request, "period_start"),
    }
    records = [r for r in db.rows("performance_reviews") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("performance_reviews", r) for r in records], limit, offset), 200


def get_review(request: Request, actor):
    review = svc.get_review(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != review["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own reviews.")
    return resp.ok(svc.serialize("performance_reviews", review)), 200


def list_agreement_reviews(request: Request, actor):
    agreement = svc.get_agreement(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != agreement["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own reviews.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("performance_reviews") if r["agreement_id"] == agreement["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("performance_reviews", r) for r in records], limit, offset), 200


def record_results(request: Request):
    review = svc.get_review(request.path_params["id"])
    if review["status"] != "DRAFT":
        raise ApiError(E_INVALID_STATE)
    review["status"] = "RESULTS_RECORDED"
    svc.compute_review_share(review)
    return resp.ok(svc.serialize("performance_reviews", review)), 200


def evaluate_review(request: Request):
    review = svc.get_review(request.path_params["id"])
    if review["status"] not in ("RESULTS_RECORDED", "CIRCUMSTANCE_PENDING"):
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(review["dealer_id"])
    agreement = svc.get_agreement(review["agreement_id"])

    review["status"] = "EVALUATED"
    svc.compute_review_share(review)

    # Quality spread across the dealer's EVALUATED reviews, including this one.
    qualities = [
        svc.quality_index(r)
        for r in db.rows("performance_reviews")
        if r["dealer_id"] == review["dealer_id"] and r["status"] == "EVALUATED"
    ]
    own = svc.quality_index(review)
    mean = sum(qualities, Decimal("0")) / Decimal(len(qualities)) if qualities else Decimal("0")
    review["quality_deficiency_pp"] = svc.num(svc.q4(mean - own))
    spread = (max(qualities) - min(qualities)) if qualities else Decimal("0")
    review["quality_deficient"] = spread >= svc.QUALITY_SPREAD_THRESHOLD_PP

    period_start = _iso(review["period_start"])
    period_end = _iso(review["period_end"])
    observed = svc.market_share_from_observations(review["dealer_id"], period_start, period_end)
    review["discrepancy_pp"] = svc.num(svc.q4(abs(Decimal(str(review["actual_market_share_pct"])) - observed)))

    ratio = review["performance_ratio_pct"]
    ltv_bonus = svc.machine_lifetime_value(dealer)
    csi_bonus = svc.CSI_BONUS_PCT if Decimal(str(ratio)) >= Decimal("100.0") else Decimal("0.0")
    review["loyalty_score"] = svc.num(svc.q2(Decimal(str(ratio)) + ltv_bonus + csi_bonus))

    svc.recompute_market_share_pct(dealer)
    svc.bump(agreement)
    return resp.ok(svc.serialize("performance_reviews", review)), 200


def request_circumstance(request: Request, actor):
    review = svc.get_review(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != review["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may act only on its own review.")
    if review["status"] != "RESULTS_RECORDED":
        raise ApiError(E_INVALID_STATE)
    review["status"] = "CIRCUMSTANCE_PENDING"
    agreement = svc.get_agreement(review["agreement_id"])
    svc.bump(agreement)
    return resp.ok(svc.serialize("performance_reviews", review)), 200


def set_remediation(request: Request):
    review = svc.get_review(request.path_params["id"])
    if review["status"] != "RESULTS_RECORDED":
        raise ApiError(E_INVALID_STATE)
    review["status"] = "REMEDIATION_REQUIRED"
    review["remedy_plan"] = request.raw("remedy_plan")
    return resp.ok(svc.serialize("performance_reviews", review)), 200


# ---------------------------------------------------------------------------
# Party registrations
# ---------------------------------------------------------------------------
def create_party_registration(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    territory_code = request.string("territory_code")
    registered_at = request.datetime("registered_at")

    for existing in db.rows("party_registrations"):
        if existing["territory_code"] == territory_code and existing["status"] == "REGISTERED":
            existing["status"] = "SUPERSEDED"
            svc.touch(existing)

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "territory_code": territory_code,
        "registered_at": db.clock_iso(registered_at),
        "status": "REGISTERED",
    }
    svc.init_common(record)
    db.insert("party_registrations", record)
    return resp.ok(svc.serialize("party_registrations", record)), 201


def list_party_registrations(request: Request):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "territory_code": q(request, "territory_code"),
        "status": q(request, "status"),
    }
    records = [r for r in db.rows("party_registrations") if svc.matches_filters(r, filters)]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("party_registrations", r) for r in records], limit, offset), 200


def get_party_registration(request: Request):
    record = svc.get_party_registration(request.path_params["id"])
    return resp.ok(svc.serialize("party_registrations", record)), 200


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
ALL_STAFF = [
    "DealerNetworkManager",
    "DealerPerformanceReviewer",
    "PartsManager",
    "RebuildProgramSpecialist",
    "ServiceTechnicianSupervisor",
    "DealerSalesManager",
    "FinancePartner",
]


def register_routes():
    reg.register("POST", BASE + "/dealers", create_dealer, ["DealerNetworkManager"], 201, ["legal_name", "home_state_code", "territory_code"], "create_dealer")
    reg.register("GET", BASE + "/dealers", list_dealers, ["DealerNetworkManager", "DealerPerformanceReviewer", "DealerSalesManager"], 200, ["territory_code?", "status?", "home_state_code?"], "list_dealers")
    reg.register("GET", BASE + "/dealers/{id}", get_dealer, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer", "DealerSalesManager", "PartsManager"], 200, [], "get_dealer")
    reg.register("POST", BASE + "/dealers/{id}/terminate", terminate_dealer, ["DealerNetworkManager"], 200, [], "terminate_dealer")

    reg.register("POST", BASE + "/dealer-agreements", create_agreement, ["DealerNetworkManager"], 201, ["dealer_id", "product_family", "territory_code", "exclusivity_level?", "start_at", "end_at", "performance_plan_share_pct", "expected_dealer_version"], "create_agreement")
    reg.register("GET", BASE + "/dealer-agreements", list_agreements, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, ["dealer_id?", "product_family?", "territory_code?", "status?"], "list_agreements")
    reg.register("GET", BASE + "/dealer-agreements/{id}", get_agreement, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, [], "get_agreement")
    reg.register("GET", BASE + "/dealers/{id}/dealer-agreements", list_dealer_agreements, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, [], "list_dealer_agreements")
    reg.register("POST", BASE + "/dealer-agreements/{id}/submit", submit_agreement, ["DealerNetworkManager"], 200, [], "submit_agreement")
    reg.register("POST", BASE + "/dealer-agreements/{id}/activate", activate_agreement, ["DealerNetworkManager"], 200, [], "activate_agreement")
    reg.register("POST", BASE + "/dealer-agreements/{id}/mark-underperforming", mark_underperforming, ["DealerPerformanceReviewer"], 200, [], "mark_underperforming")
    reg.register("POST", BASE + "/dealer-agreements/{id}/suspend", suspend_agreement, ["DealerNetworkManager"], 200, [], "suspend_agreement")
    reg.register("POST", BASE + "/dealer-agreements/{id}/reinstate", reinstate_agreement, ["DealerPerformanceReviewer", "DealerNetworkManager"], 200, [], "reinstate_agreement")
    reg.register("POST", BASE + "/dealer-agreements/{id}/terminate", terminate_agreement, ["DealerNetworkManager"], 200, [], "terminate_agreement")

    reg.register("POST", BASE + "/performance-reviews", create_review, ["DealerPerformanceReviewer"], 201, ["dealer_id", "agreement_id", "period_start", "period_end", "actual_territory_machine_units", "territory_market_machine_units", "sampled_service_orders", "met_sla_service_orders", "circumstance_note?", "expected_dealeragreement_version"], "create_review")
    reg.register("GET", BASE + "/performance-reviews", list_reviews, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, ["dealer_id?", "agreement_id?", "status?", "period_start?"], "list_reviews")
    reg.register("GET", BASE + "/performance-reviews/{id}", get_review, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, [], "get_review")
    reg.register("GET", BASE + "/dealer-agreements/{id}/performance-reviews", list_agreement_reviews, ["DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, [], "list_agreement_reviews")
    reg.register("POST", BASE + "/performance-reviews/{id}/record-results", record_results, ["DealerPerformanceReviewer"], 200, [], "record_results")
    reg.register("POST", BASE + "/performance-reviews/{id}/evaluate", evaluate_review, ["DealerPerformanceReviewer"], 200, [], "evaluate_review")
    reg.register("POST", BASE + "/performance-reviews/{id}/request-circumstance", request_circumstance, ["DealerPerformanceReviewer", "InputDealer"], 200, [], "request_circumstance")
    reg.register("POST", BASE + "/performance-reviews/{id}/set-remediation", set_remediation, ["DealerPerformanceReviewer"], 200, ["remedy_plan?"], "set_remediation")

    reg.register("POST", BASE + "/party-registrations", create_party_registration, ["DealerNetworkManager"], 201, ["dealer_id", "territory_code", "registered_at"], "create_party_registration")
    reg.register("GET", BASE + "/party-registrations", list_party_registrations, ["DealerNetworkManager", "DealerPerformanceReviewer"], 200, ["dealer_id?", "territory_code?", "status?"], "list_party_registrations")
    reg.register("GET", BASE + "/party-registrations/{id}", get_party_registration, ["DealerNetworkManager", "DealerPerformanceReviewer"], 200, [], "get_party_registration")