"""Parts commitments, parts-order batches, rebuild claims, support agreements,
market-share observations, certification records and the machine population.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
import registry as reg
import response as resp
from errors import (
    ApiError,
    E_AGREEMENT_NOT_FOUND,
    E_COMMITMENT_BATCH_OPEN,
    E_COMMITMENT_EMPTY,
    E_COMMITMENT_NOT_FOUND,
    E_COMMITMENT_PERF_DEF,
    E_CREDIT_ALREADY_APPLIED,
    E_DEALER_TERMINATED,
    E_EPOCH_CONFLICT,
    E_HARD_CAP,
    E_INVALID_STATE,
    E_MACHINE_ALREADY_REGISTERED,
    E_MACHINE_NOT_IN_POPULATION,
    E_MACHINE_POPULATION_RETIRED,
    E_MACHINE_REMARKETED,
    E_NO_ACTIVE_AGREEMENT,
    E_NO_RESTRICTION_PRIORITY,
    E_PARTY_SUPERSEDED,
    E_POPULATION_NOT_FOUND,
    E_REBUILD_CORE_UNRETURNED,
    E_REBUILD_SPEC_EXCEEDED,
    E_SLA_AUDIT_PENDING,
    E_STOCKING_MANDATE_UNMET,
    E_TOOLING_INCOMPLETE,
    E_TRADE_IN_NOT_ACCEPTED,
)
from request import PRODUCT_FAMILIES, Request
from routes._common import page_params, paged_response, q, q_bool
from services import core as svc

BASE = "/dealer-network"


# ===========================================================================
# Parts commitments
# ===========================================================================
def create_commitment(request: Request):
    agreement_id = request.string("agreement_id")
    agreement = svc.get_agreement(agreement_id)
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    svc.check_expected_version(dealer, request.raw("expected_dealer_version"))

    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    if product_family != agreement["product_family"]:
        raise ApiError("ERR_INVALID_REQUEST", "product_family must equal the agreement's product family")
    slope = request.number("machine_population_slope", required=False, default=1.0)
    target_pct = request.number("emergency_stocking_target_pct")
    if target_pct <= 0 or target_pct > 100:
        raise ApiError("ERR_INVALID_REQUEST", "emergency_stocking_target_pct must fall in (0, 100]")
    window = request.number("emergency_fill_window_hours")

    commitment = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "dealer_id": dealer_id,
        "product_family": product_family,
        "machine_population_units": request.integer("machine_population_units"),
        "machine_population_slope": slope,
        "machine_population_tier": "MICRO",
        "planned_annual_units": request.integer("planned_annual_units"),
        "emergency_stocking_target_pct": target_pct,
        "emergency_fill_window_hours": window,
        "required_stocking_units": 0,
        "required_stocking_units_final": 0,
        "available_commitment_units": 0,
        "availability_target_pct": 0.0,
        "emergency_tier": "BASIC",
        "committed_units": 0,
        "fulfilled_units": 0,
        "fill_rate_pct": 0.0,
        "credit_balance_cents": 0,
        "status": "PLANNED",
        "backorder_opened_at": None,
    }
    svc.init_common(commitment)
    db.insert("parts_commitments", commitment)
    svc.compute_stocking_mandate(commitment)
    svc.bump(dealer)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 201


def list_commitments(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "agreement_id": q(request, "agreement_id"),
        "product_family": q(request, "product_family"),
        "status": q(request, "status"),
    }
    records = [r for r in db.rows("parts_commitments") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("parts_commitments", r) for r in records], limit, offset), 200


def get_commitment(request: Request, actor):
    commitment = svc.get_commitment(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != commitment["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own commitments.")
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def list_agreement_commitments(request: Request, actor):
    agreement = svc.get_agreement(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != agreement["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own commitments.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("parts_commitments") if r["agreement_id"] == agreement["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("parts_commitments", r) for r in records], limit, offset), 200


def list_dealer_commitments(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own commitments.")
    limit, offset = page_params(request)
    records = svc.sort_by_created(svc.dealer_commitments(dealer["id"]))
    return paged_response([svc.serialize("parts_commitments", r) for r in records], limit, offset), 200


def submit_commitment(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] == "COMPLETE":
        raise ApiError(E_INVALID_STATE)
    if commitment["status"] != "PLANNED":
        raise ApiError(E_INVALID_STATE)
    agreement = svc.get_agreement(commitment["agreement_id"])
    if agreement["status"] not in ("SUBMITTED", "ACTIVE"):
        raise ApiError(E_INVALID_STATE)
    if int(commitment["planned_annual_units"]) < 1:
        raise ApiError(E_INVALID_STATE, "planned_annual_units must be at least 1")
    commitment["status"] = "SUBMITTED"
    svc.touch(commitment)
    svc.compute_stocking_mandate(commitment)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def ready_for_orders(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] == "COMPLETE":
        raise ApiError(E_INVALID_STATE)
    if commitment["status"] != "SUBMITTED":
        raise ApiError(E_INVALID_STATE)
    agreement = svc.get_agreement(commitment["agreement_id"])
    dealer = svc.get_dealer(commitment["dealer_id"])

    if int(commitment["required_stocking_units_final"]) < 1:
        raise ApiError(E_STOCKING_MANDATE_UNMET)
    svc.refresh_agreement_derived(agreement)
    if agreement["tooling_compliance_status"] != "COMPLIANT":
        raise ApiError(E_TOOLING_INCOMPLETE)
    if commitment["machine_population_tier"] == "MICRO":
        raise ApiError(E_STOCKING_MANDATE_UNMET, "a MICRO territory cannot be made order-ready")

    commitment["status"] = "ORDER_READY"
    svc.touch(commitment)
    svc.recompute_trusted_commitment(agreement)
    svc.touch(agreement)
    svc.recompute_trusted_commitment_count(dealer)
    svc.sync_dealer_status(dealer)
    svc.set_deferred_rule(commitment["id"], True)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def suspend_commitment(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] != "ORDER_READY":
        raise ApiError(E_INVALID_STATE)
    if svc.has_batch_open_or_ordered([commitment["id"]]):
        raise ApiError(E_COMMITMENT_BATCH_OPEN)
    commitment["status"] = "SUSPENDED"
    svc.touch(commitment)
    agreement = svc.get_agreement(commitment["agreement_id"])
    svc.recompute_trusted_commitment(agreement)
    svc.touch(agreement)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_trusted_commitment_count(dealer)
    svc.set_deferred_rule(commitment["id"], False)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def suspend_core_credit(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] != "ORDER_READY":
        raise ApiError(E_INVALID_STATE)
    if int(commitment["credit_balance_cents"]) != 0:
        raise ApiError(E_CREDIT_ALREADY_APPLIED)
    if svc.has_batch_open_or_ordered([commitment["id"]]):
        raise ApiError(E_COMMITMENT_BATCH_OPEN)

    commitment["status"] = "CORE_PENDING"
    svc.touch(commitment)
    for batch in svc.commitment_batches(commitment["id"]):
        if batch["status"] == "OPEN":
            batch["core_return_required"] = True
            svc.touch(batch)
    agreement = svc.get_agreement(commitment["agreement_id"])
    svc.recompute_trusted_commitment(agreement)
    svc.touch(agreement)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_trusted_commitment_count(dealer)
    svc.set_deferred_rule(commitment["id"], False)
    for order in svc.commitment_service_orders(commitment["id"]):
        if order["status"] in ("OPEN", "IN_PROGRESS"):
            order["status"] = "ESCALATED"
            svc.touch(order)
    svc.recompute_deferral_tiers(dealer["id"])
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def settle_core_credit(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] != "CORE_PENDING":
        raise ApiError(E_INVALID_STATE)
    threshold = int(commitment["required_stocking_units_final"]) * 100
    if int(commitment["credit_balance_cents"]) < threshold:
        raise ApiError(E_HARD_CAP, "the returned cores have not settled the mandate's threshold")
    settlement = request.integer("credit_settlement_cents")
    new_balance = int(commitment["credit_balance_cents"]) + settlement
    if new_balance >= threshold:
        raise ApiError(E_HARD_CAP, "the settled figure reaches the mandate's threshold")
    commitment["credit_balance_cents"] = new_balance
    commitment["status"] = "ORDER_READY"
    svc.touch(commitment)
    svc.set_deferred_rule(commitment["id"], True)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_trusted_commitment_count(dealer)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


def reinstate_commitment(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    if commitment["status"] == "PERFORMANCE_DEFICIENT":
        threshold = int(commitment["required_stocking_units_final"]) - int(commitment["committed_units"])
        if int(commitment["available_commitment_units"]) < threshold:
            raise ApiError(E_HARD_CAP, "the availability deficit has not been restored")
        commitment["status"] = "ORDER_READY"
        commitment["backorder_opened_at"] = None
        svc.touch(commitment)
        svc.set_deferred_rule(commitment["id"], True)
    elif commitment["status"] == "SUSPENDED":
        agreement = svc.get_agreement(commitment["agreement_id"])
        if agreement["status"] != "ACTIVE":
            raise ApiError(E_INVALID_STATE)
        commitment["status"] = "ORDER_READY"
        svc.touch(commitment)
        svc.set_deferred_rule(commitment["id"], True)
    else:
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_trusted_commitment_count(dealer)
    return resp.ok(svc.serialize("parts_commitments", commitment)), 200


# ===========================================================================
# Parts-order batches
# ===========================================================================
def create_batch(request: Request):
    commitment_id = request.string("commitment_id")
    commitment = svc.get_commitment(commitment_id)
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    if product_family != commitment["product_family"]:
        raise ApiError("ERR_INVALID_REQUEST", "product_family must equal the commitment's product family")

    requested_units = request.integer("requested_units")
    core_units = request.integer("core_units")
    core_return_required = request.boolean("core_return_required")
    emergency = request.boolean("emergency", required=False, default=False)
    requested_at = request.datetime("requested_at")

    available = int(commitment["available_commitment_units"])
    active_variant = int(commitment["required_stocking_units"])
    gap = active_variant - int(commitment["committed_units"])
    if requested_units > available:
        if emergency:
            # The emergency branch may not be used as a way around the cap.
            raise ApiError(E_HARD_CAP, "requested_units exceeds the commitment's available units")
        # The oversized non-emergency batch is the deliberate exception carved
        # out of the aggregate mandate rule: it over-reserves at the active
        # variant plus two without confirming an allocation there.
        reserved = active_variant + 2
        core_flag = True
    elif emergency:
        reserved = min(gap, 5 * active_variant)
        core_flag = bool(core_return_required)
    else:
        reserved = min(requested_units, available)
        core_flag = bool(core_return_required)

    if commitment["status"] == "CORE_PENDING":
        core_flag = True

    batch = {
        "id": db.new_id(),
        "commitment_id": commitment_id,
        "product_family": product_family,
        "requested_units": requested_units,
        "reserved_units": reserved,
        "unfilled_units": reserved,
        "status": "OPEN",
        "requested_at": db.clock_iso(requested_at),
        "received_at": None,
        "emergency": bool(emergency),
        "core_return_required": core_flag,
        "core_units": core_units,
        "core_return_credit_cents": None,
    }
    svc.init_common(batch)
    db.insert("parts_order_batches", batch)
    svc.recompute_committed_units(commitment)
    svc.recompute_fill_rate(commitment)
    svc.touch(commitment)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 201


def list_batches(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "commitment_id": q(request, "commitment_id"),
        "product_family": q(request, "product_family"),
        "status": q(request, "status"),
    }
    emergency = q_bool(request, "emergency")
    records = [r for r in db.rows("parts_order_batches") if svc.matches_filters(r, filters)]
    if emergency is not None:
        records = [r for r in records if bool(r["emergency"]) == emergency]
    if actor.role == "InputDealer":
        records = [r for r in records if _batch_dealer(r) == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("parts_order_batches", r) for r in records], limit, offset), 200


def _batch_dealer(batch):
    commitment = db.find("parts_commitments", batch["commitment_id"])
    return None if commitment is None else commitment["dealer_id"]


def get_batch(request: Request, actor):
    batch = svc.get_batch(request.path_params["id"])
    if actor.role == "InputDealer" and _batch_dealer(batch) != actor.dealer_id:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own batches.")
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def list_commitment_batches(request: Request, actor):
    commitment = svc.get_commitment(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != commitment["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own batches.")
    limit, offset = page_params(request)
    records = svc.sort_by_created(svc.commitment_batches(commitment["id"]))
    return paged_response([svc.serialize("parts_order_batches", r) for r in records], limit, offset), 200


def place_order(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    if batch["status"] != "OPEN":
        raise ApiError(E_INVALID_STATE)
    available = int(commitment["available_commitment_units"])
    if available < 1 and not batch["emergency"]:
        raise ApiError(E_COMMITMENT_EMPTY)

    batch["status"] = "ORDERED"
    if (not batch["emergency"]) and available == 0:
        batch["reserved_units"] = available // 2
    svc.touch(batch)
    svc.recompute_committed_units(commitment)
    svc.recompute_fill_rate(commitment)
    svc.touch(commitment)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def receive_batch(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    ordered_ref = request.string("ordered_ref")
    commitment = svc.get_commitment(batch["commitment_id"])
    if batch["status"] != "ORDERED":
        if batch["status"] == "RECEIVED" and batch.get("last_ordered_ref") == ordered_ref:
            # Idempotent replay: no second credit, committed_units untouched.
            return resp.ok(svc.serialize("parts_order_batches", batch)), 200
        raise ApiError(E_INVALID_STATE)

    if ordered_ref in (batch.get("received_refs") or []):
        return resp.ok(svc.serialize("parts_order_batches", batch)), 200

    if commitment["status"] in ("PERFORMANCE_DEFICIENT", "SUSPENDED"):
        if commitment["id"] in db.STATE["re_evaluation_armed"]:
            raise ApiError(E_EPOCH_CONFLICT, "a deferred re-evaluation is armed for this commitment in this epoch")
        outstanding = [
            o
            for o in svc.commitment_service_orders(commitment["id"])
            if o["kind"] == "SLA_AUDIT" and o["status"] != "RESOLVED"
        ]
        if outstanding:
            # Suspend the deferred re-evaluation for this epoch: the older
            # performance re-evaluation must re-compute its deferral tier.
            db.STATE["re_evaluation_armed"].discard(commitment["id"])
            svc.recompute_deferral_tiers(commitment["dealer_id"])

    received_now = int(batch["unfilled_units"])
    batch["unfilled_units"] = 0
    batch["received_at"] = db.stamp()
    batch["status"] = "RECEIVED"
    batch["last_ordered_ref"] = ordered_ref
    batch.setdefault("received_refs", []).append(ordered_ref)
    svc.touch(batch)

    commitment["fulfilled_units"] = int(commitment["fulfilled_units"]) + received_now
    if int(batch["core_units"]) >= 1:
        commitment["credit_balance_cents"] = int(commitment["credit_balance_cents"]) + int(batch["core_units"]) * svc.credited_units_increment()
    # §3.5: "Receipt then recomputes `fill_rate_pct`, `committed_units` and
    # `Dealer.open_backorder_units`" — the rate is taken over the outstanding
    # reservation that remains, so the commitment is re-keyed first.
    svc.recompute_committed_units(commitment)
    svc.recompute_fill_rate(commitment)
    svc.touch(commitment)

    remainder = int(batch["reserved_units"]) - received_now
    if remainder > 0:
        carry = {
            "id": db.new_id(),
            "commitment_id": commitment["id"],
            "product_family": batch["product_family"],
            "requested_units": remainder,
            "reserved_units": remainder,
            "unfilled_units": remainder,
            "status": "OPEN",
            "requested_at": db.now_iso(),
            "received_at": None,
            "emergency": bool(batch["emergency"]),
            "core_return_required": bool(batch["core_return_required"]),
            "core_units": 0,
            "core_return_credit_cents": None,
        }
        svc.init_common(carry)
        db.insert("parts_order_batches", carry)
        svc.recompute_committed_units(commitment)
        svc.recompute_fill_rate(commitment)
        svc.touch(commitment)

    for order in svc.commitment_service_orders(commitment["id"]):
        if order["status"] == "FILLED":
            order["status"] = "RESOLVED"
            order["resolved_at"] = db.stamp()
            svc.touch(order)

    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    svc.recompute_deferral_tiers(dealer["id"])
    # The deferred shortage rule fires once the returned cores settle the
    # arrear; the armed re-evaluation then collides with any later receipt.
    svc.apply_deferred_shortage_rule(commitment, svc.credited_core_units(commitment["id"]))
    svc.maybe_auto_complete(commitment)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def return_core(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    if batch["status"] not in ("RECEIVED", "PARTIALLY_RETURNED"):
        raise ApiError(E_INVALID_STATE)
    core_units = request.integer("core_units")
    if core_units < 1:
        raise ApiError(E_INVALID_STATE, "core_units must be at least 1")
    final = int(commitment["required_stocking_units_final"])
    if batch.get("core_return_credit_cents") is None:
        batch["core_return_credit_cents"] = int(core_units) * svc.credited_units_increment()
    batch["core_units"] = core_units
    batch["status"] = "PARTIALLY_RETURNED"
    svc.touch(batch)
    commitment["credit_balance_cents"] = int(commitment["credit_balance_cents"]) + int(batch["core_return_credit_cents"])
    if int(commitment["credit_balance_cents"]) >= final * 100:
        svc.set_deferred_rule(commitment["id"], False)
    svc.recompute_fulfilled_units(commitment)
    svc.recompute_committed_units(commitment)
    svc.touch(commitment)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def core_return(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    final = int(commitment["required_stocking_units_final"])

    if batch["status"] == "RECEIVED":
        if not batch["core_return_required"]:
            raise ApiError(E_INVALID_STATE, "this batch does not require a core return")
        if commitment["status"] == "PERFORMANCE_DEFICIENT":
            raise ApiError(E_COMMITMENT_PERF_DEF)
        batch["status"] = "CORE_PENDING"
        svc.touch(batch)
        if int(commitment["credit_balance_cents"]) == 0:
            commitment["status"] = "CORE_PENDING"
            svc.touch(commitment)
        svc.set_deferred_rule(commitment["id"], False)
        for other in svc.commitment_batches(commitment["id"]):
            if other["status"] == "OPEN":
                other["core_return_required"] = True
                svc.touch(other)
        agreement = svc.get_agreement(commitment["agreement_id"])
        svc.recompute_trusted_commitment(agreement)
        svc.touch(agreement)
        dealer = svc.get_dealer(commitment["dealer_id"])
        svc.recompute_trusted_commitment_count(dealer)
        svc.recompute_open_backorder_units(dealer)
        return resp.ok(svc.serialize("parts_order_batches", batch)), 200

    if batch["status"] == "CORE_PENDING":
        core_units = request.integer("core_units", required=False, default=None)
        if core_units is None or core_units < 1:
            raise ApiError(E_INVALID_STATE, "core_units must be at least 1")
        if int(commitment["credit_balance_cents"]) < final * 100:
            raise ApiError(E_INVALID_STATE, "the commitment's credit balance is below the mandate threshold")
        batch["status"] = "RECEIVED"
        batch["core_units"] = core_units
        svc.touch(batch)
        commitment["credit_balance_cents"] = int(commitment["credit_balance_cents"]) + core_units * 100
        svc.set_deferred_rule(commitment["id"], True)
        if int(commitment["credit_balance_cents"]) >= final * 100:
            commitment["status"] = "ORDER_READY"
        svc.touch(commitment)
        dealer = svc.get_dealer(commitment["dealer_id"])
        svc.recompute_open_backorder_units(dealer)
        return resp.ok(svc.serialize("parts_order_batches", batch)), 200

    raise ApiError(E_INVALID_STATE)


def cancel_core_return(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    if batch["status"] not in ("CORE_PENDING", "PARTIALLY_RETURNED"):
        raise ApiError(E_INVALID_STATE)
    amount = batch.get("core_return_credit_cents")
    if amount is not None:
        commitment["credit_balance_cents"] = max(0, int(commitment["credit_balance_cents"]) - int(amount))
    elif batch["status"] == "CORE_PENDING":
        commitment["credit_balance_cents"] = max(0, int(commitment["credit_balance_cents"]) - int(batch["core_units"]) * 100)
    svc.touch(commitment)
    if int(commitment["credit_balance_cents"]) < int(commitment["required_stocking_units_final"]) * 100:
        svc.set_deferred_rule(commitment["id"], False)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def close_batch(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    if batch["status"] != "RECEIVED":
        raise ApiError(E_INVALID_STATE)
    if int(commitment["credit_balance_cents"]) < int(commitment["required_stocking_units_final"]) * svc.credited_units_increment():
        raise ApiError(E_HARD_CAP, "the mandate settlement has not cleared")
    if commitment["status"] != "ORDER_READY":
        raise ApiError(E_INVALID_STATE)

    batch["status"] = "CLOSED"
    svc.touch(batch)
    svc.recompute_committed_units(commitment)
    svc.touch(commitment)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)

    threshold = int(commitment["required_stocking_units_final"]) * svc.credited_units_increment()
    batches = svc.commitment_batches(commitment["id"])
    if batches and all(b["status"] == "CLOSED" for b in batches) and int(commitment["credit_balance_cents"]) >= threshold:
        commitment["status"] = "COMPLETE"
        svc.touch(commitment)
    else:
        # The COMPLETE hard cap is suspended for a CERTIFIED rebuild's credit
        # reduction: a commitment standing below its threshold is lifted onto it
        # so the settlement path stays reachable.
        for claim in db.rows("rebuild_claims"):
            if claim["dealer_id"] != commitment["dealer_id"]:
                continue
            if claim["product_family"] != commitment["product_family"]:
                continue
            if claim["status"] != "CERTIFIED":
                continue
            if int(commitment["credit_balance_cents"]) < threshold:
                commitment["credit_balance_cents"] = threshold
                svc.touch(commitment)
            break
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


def cancel_batch(request: Request):
    batch = svc.get_batch(request.path_params["id"])
    commitment = svc.get_commitment(batch["commitment_id"])
    was_open = batch["status"] == "OPEN"
    if batch["status"] not in ("OPEN", "ORDERED"):
        raise ApiError(E_INVALID_STATE)
    batch["status"] = "CANCELLED"
    svc.touch(batch)
    svc.recompute_committed_units(commitment)
    svc.touch(commitment)
    if was_open:
        dealer = svc.get_dealer(commitment["dealer_id"])
        svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("parts_order_batches", batch)), 200


# ===========================================================================
# Rebuild claims
# ===========================================================================
def create_claim(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    machine_serial = request.string("machine_serial")
    spec_code = request.enum("certified_rebuild_spec_code", ["CAT_CERTIFIED_1", "CAT_CERTIFIED_2", "CAT_CERTIFIED_3"])

    live = [
        r
        for r in db.rows("machine_population_records")
        if r["dealer_id"] == dealer["id"] and r["status"] == "ACTIVE" and r["machine_serial"] == machine_serial
    ]
    if not live:
        raise ApiError(E_MACHINE_NOT_IN_POPULATION)

    for other in db.rows("rebuild_claims"):
        if other["machine_serial"] != machine_serial:
            continue
        if other["status"] in ("DENIED", "DECLINED"):
            continue
        raise ApiError("ERR_DUPLICATE_SERIAL", "this machine serial already carries a live rebuild claim")

    claim = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "product_family": product_family,
        "machine_serial": machine_serial,
        "machine_operating_weight_lb": request.integer("machine_operating_weight_lb"),
        "client_meter_hours": request.number("client_meter_hours", required=False, default=None),
        "requested_at": db.clock_iso(request.datetime("requested_at")),
        "core_purchase_value_cents": request.integer("core_purchase_value_cents", required=False, default=None),
        "core_return_credit_cents": None,
        "core_returned_at": None,
        "rebuild_labor_hours": request.number("rebuild_labor_hours"),
        "rebuild_labor_rate_cents": request.integer("rebuild_labor_rate_cents"),
        "rebuild_fee_cents": None,
        "certified_rebuild_spec_code": spec_code,
        "status": "REQUESTED",
    }
    svc.init_common(claim)
    db.insert("rebuild_claims", claim)
    agreement = svc.first_agreement(dealer["id"], product_family)
    if agreement is not None:
        svc.refresh_agreement_derived(agreement)
        svc.touch(agreement)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 201


def list_claims(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "machine_serial": q(request, "machine_serial"),
        "status": q(request, "status"),
    }
    records = [r for r in db.rows("rebuild_claims") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("rebuild_claims", r) for r in records], limit, offset), 200


def get_claim(request: Request, actor):
    claim = svc.get_claim(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != claim["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own claims.")
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def list_dealer_claims(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own claims.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("rebuild_claims") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("rebuild_claims", r) for r in records], limit, offset), 200


def approve_claim(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "REQUESTED":
        raise ApiError(E_INVALID_STATE)
    svc.check_expected_version(claim, request.raw("expected_rebuildclaim_version"), E_HARD_CAP)
    dealer = svc.get_dealer(claim["dealer_id"])

    agreement = svc.first_agreement(dealer["id"], claim["product_family"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(E_NO_ACTIVE_AGREEMENT)
    if not any(
        c["dealer_id"] == dealer["id"] and c["status"] == "PERFORMANCE_DEFICIENT"
        for c in db.rows("parts_commitments")
    ):
        raise ApiError(E_NO_RESTRICTION_PRIORITY)
    max_weight = svc.REBUILD_SPEC_MAX_WEIGHT_LB[claim["certified_rebuild_spec_code"]]
    if int(claim["machine_operating_weight_lb"]) > max_weight:
        raise ApiError(E_REBUILD_SPEC_EXCEEDED)

    if claim.get("core_purchase_value_cents") is None:
        claim["core_purchase_value_cents"] = 0
    values = svc.core_values(int(claim["core_purchase_value_cents"]))
    claim["core_return_credit_cents"] = svc.int2(values["core_return_credit_cents"])
    claim["rebuild_fee_cents"] = svc.rebuild_fee(
        values["core_value"], claim["rebuild_labor_hours"], claim["rebuild_labor_rate_cents"]
    )
    claim["status"] = "APPROVED"
    svc.touch(claim)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def deny_claim(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "REQUESTED":
        raise ApiError(E_INVALID_STATE)
    claim["status"] = "DENIED"
    svc.touch(claim)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def decline_claim(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "APPROVED":
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(claim["dealer_id"])
    for registration in db.rows("party_registrations"):
        if registration["territory_code"] == dealer["territory_code"] and registration["status"] == "SUPERSEDED":
            raise ApiError(E_PARTY_SUPERSEDED)
    claim["status"] = "DECLINED"
    svc.touch(claim)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def request_core_return(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "APPROVED":
        raise ApiError(E_INVALID_STATE)
    if claim.get("core_purchase_value_cents") is None or int(claim["core_purchase_value_cents"]) < 1:
        raise ApiError(E_INVALID_STATE, "core_purchase_value_cents must be at least 1")
    claim["status"] = "CORE_PENDING"
    svc.touch(claim)
    commitment = svc.first_family_commitment(claim["dealer_id"], claim["product_family"])
    if commitment is not None:
        svc.set_deferred_rule(commitment["id"], False)
    svc.open_restriction_order_for_claim(claim)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def claim_core_return(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "CORE_PENDING":
        raise ApiError(E_INVALID_STATE)
    returned_at = request.raw("core_returned_at")
    if returned_at is None:
        raise ApiError(E_REBUILD_CORE_UNRETURNED, "core_returned_at must be supplied on the claim")
    claim["core_returned_at"] = db.clock_iso(request.datetime("core_returned_at"))
    claim["status"] = "CORE_RETURNED"
    svc.touch(claim)

    commitment = svc.first_family_commitment(claim["dealer_id"], claim["product_family"])
    if commitment is not None:
        if claim.get("client_meter_hours") is None:
            # The dealer does not hold the machine: the credit lands on the
            # commitment, priced on the frozen pair and never recomputed.
            commitment["credit_balance_cents"] = int(commitment["credit_balance_cents"]) + int(claim["core_return_credit_cents"])
        if int(commitment["credit_balance_cents"]) >= int(commitment["required_stocking_units_final"]) * svc.credited_units_increment():
            svc.set_deferred_rule(commitment["id"], True)
        svc.touch(commitment)
    dealer = svc.get_dealer(claim["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def deliver_claim(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "CORE_RETURNED":
        raise ApiError(E_INVALID_STATE)
    agreement = svc.first_agreement(claim["dealer_id"], claim["product_family"])
    minimum = svc.REBUILD_SPEC_MIN_TECHNICIANS[claim["certified_rebuild_spec_code"]]
    head_count = 0 if agreement is None else int(agreement["certified_technician_count"])
    if minimum > head_count:
        raise ApiError(E_REBUILD_SPEC_EXCEEDED)

    commitment = svc.first_family_commitment(claim["dealer_id"], claim["product_family"])
    svc.open_service_order(
        dealer_id=claim["dealer_id"],
        commitment=commitment,
        kind="SLA_AUDIT",
        machine_serial=claim["machine_serial"],
        origin_rebuild_id=claim["id"],
        sla_hours=0.0,
    ).update({"status": "RESOLVED", "resolved_at": db.stamp()})

    meter_hours = claim.get("client_meter_hours") or 0
    trade_in = {
        "id": db.new_id(),
        "order_id": None,
        "machine_serial": "%s%s" % (claim["machine_serial"], svc.num(Decimal(str(meter_hours)))),
        "machine_operating_weight_lb": int(claim["machine_operating_weight_lb"]),
        "appraised_value_cents": int(claim.get("core_purchase_value_cents") or 0),
        "status": "ACCEPTED",
    }
    svc.init_common(trade_in)
    db.insert("trade_in_units", trade_in)

    if not any(
        a["machine_serial"] == claim["machine_serial"] and a["status"] != "TERMINATED"
        for a in db.rows("support_agreements")
    ):
        support = {
            "id": db.new_id(),
            "dealer_id": claim["dealer_id"],
            "machine_serial": claim["machine_serial"],
            "plan_tier": "PREMIUM",
            "enrolled_at": db.now_iso(),
            "coverage_multiplier": svc.num(svc.coverage_multiplier(claim["machine_serial"])),
            "status": "ACTIVE",
        }
        svc.init_common(support)
        db.insert("support_agreements", support)
        svc.refresh_serial_coverage(claim["machine_serial"])
        svc.recompute_dealer_commitment_tiers(claim["dealer_id"], claim["product_family"])

    claim["status"] = "DELIVERED"
    svc.touch(claim)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


def certify_claim(request: Request):
    claim = svc.get_claim(request.path_params["id"])
    if claim["status"] != "DELIVERED":
        raise ApiError(E_INVALID_STATE)
    live = [
        o
        for o in db.rows("service_orders")
        if o.get("origin_rebuild_id") == claim["id"] and o["status"] != "CANCELLED"
    ]
    if not live:
        raise ApiError(E_INVALID_STATE, "no service order carries this rebuild as its origin")

    claim["status"] = "CERTIFIED"
    svc.touch(claim)
    commitment = svc.first_family_commitment(claim["dealer_id"], claim["product_family"])
    if commitment is not None:
        commitment["required_stocking_units_final"] = max(
            0, int(commitment["required_stocking_units_final"]) - svc.CERTIFIED_CREDIT_REDUCTION_UNITS
        )
        svc.recompute_available_units(commitment)
        svc.touch(commitment)
    dealer = svc.get_dealer(claim["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    return resp.ok(svc.serialize("rebuild_claims", claim)), 200


# ===========================================================================
# Support agreements
# ===========================================================================
def create_support_agreement(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    machine_serial = request.string("machine_serial")
    plan_tier = request.enum("plan_tier", ["BASIC", "PLUS", "PREMIUM"])
    enrolled_at = request.datetime("enrolled_at")

    for existing in db.rows("support_agreements"):
        if existing["machine_serial"] == machine_serial and existing["status"] != "TERMINATED":
            raise ApiError("ERR_DUPLICATE_SERIAL", "this machine serial already carries a live support agreement")

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "machine_serial": machine_serial,
        "plan_tier": plan_tier,
        "enrolled_at": db.clock_iso(enrolled_at),
        "coverage_multiplier": svc.num(svc.COVERAGE_BY_TIER[plan_tier]),
        "status": "ACTIVE",
    }
    svc.init_common(record)
    db.insert("support_agreements", record)
    svc.refresh_serial_coverage(machine_serial)
    svc.recompute_dealer_commitment_tiers(dealer["id"])
    return resp.ok(svc.serialize("support_agreements", record)), 201


def list_support_agreements(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "machine_serial": q(request, "machine_serial"),
        "plan_tier": q(request, "plan_tier"),
        "status": q(request, "status"),
    }
    records = [r for r in db.rows("support_agreements") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("support_agreements", r) for r in records], limit, offset), 200


def get_support_agreement(request: Request, actor):
    record = svc.get_support_agreement(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own support agreements.")
    return resp.ok(svc.serialize("support_agreements", record)), 200


def list_dealer_support_agreements(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own support agreements.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("support_agreements") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("support_agreements", r) for r in records], limit, offset), 200


def _sla_audit_pending(machine_serial) -> bool:
    for order in db.rows("service_orders"):
        if order["machine_serial"] != machine_serial:
            continue
        if order["kind"] == "SLA_AUDIT" and order["status"] in ("OPEN", "IN_PROGRESS"):
            return True
    return False


def _any_service_order_live(machine_serial) -> bool:
    for order in db.rows("service_orders"):
        if order["machine_serial"] == machine_serial and order["status"] in ("OPEN", "IN_PROGRESS"):
            return True
    return False


def suspend_support_agreement(request: Request):
    record = svc.get_support_agreement(request.path_params["id"])
    if record["status"] != "ACTIVE":
        raise ApiError(E_INVALID_STATE)
    if _sla_audit_pending(record["machine_serial"]):
        raise ApiError(E_SLA_AUDIT_PENDING)
    record["status"] = "SUSPENDED"
    svc.touch(record)
    svc.recompute_dealer_commitment_tiers(record["dealer_id"], _family_of_serial(record["machine_serial"]))
    for commitment in svc.dealer_commitments(record["dealer_id"]):
        svc.set_deferred_rule(commitment["id"], False)
    return resp.ok(svc.serialize("support_agreements", record)), 200


def reinstate_support_agreement(request: Request):
    record = svc.get_support_agreement(request.path_params["id"])
    if record["status"] != "SUSPENDED":
        raise ApiError(E_INVALID_STATE)
    population = None
    for candidate in db.rows("machine_population_records"):
        if candidate["machine_serial"] == record["machine_serial"]:
            population = candidate
    if population is None or population["status"] != "ACTIVE":
        raise ApiError(E_POPULATION_NOT_FOUND, "the machine is not live in the population")
    record["status"] = "ACTIVE"
    svc.touch(record)
    svc.refresh_serial_coverage(record["machine_serial"])
    svc.recompute_dealer_commitment_tiers(record["dealer_id"], population["product_family"])
    for commitment in svc.dealer_commitments(record["dealer_id"]):
        if commitment["product_family"] == population["product_family"]:
            svc.set_deferred_rule(commitment["id"], True)
    return resp.ok(svc.serialize("support_agreements", record)), 200


def terminate_support_agreement(request: Request):
    record = svc.get_support_agreement(request.path_params["id"])
    if record["status"] == "TERMINATED":
        raise ApiError(E_INVALID_STATE)
    leaving_suspended = record["status"] == "SUSPENDED"
    if not leaving_suspended and _any_service_order_live(record["machine_serial"]):
        raise ApiError(E_INVALID_STATE, "a service order referencing this machine serial is still live")

    record["status"] = "TERMINATED"
    svc.touch(record)
    svc.refresh_serial_coverage(record["machine_serial"])
    if not leaving_suspended:
        svc.recompute_dealer_commitment_tiers(record["dealer_id"], _family_of_serial(record["machine_serial"]))
    return resp.ok(svc.serialize("support_agreements", record)), 200


def _family_of_serial(machine_serial):
    for candidate in db.rows("machine_population_records"):
        if candidate["machine_serial"] == machine_serial:
            return candidate["product_family"]
    return None


# ===========================================================================
# Market-share observations
# ===========================================================================
def create_observation(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    observed_machine_units = request.integer("observed_machine_units")
    territory_machine_units = request.integer("territory_machine_units")
    recorded_at = request.datetime("recorded_at")
    kind = request.enum("kind", ["MACHINE", "LIGHT"], required=False, default="MACHINE")

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "observed_machine_units": observed_machine_units,
        "territory_machine_units": territory_machine_units,
        "observed_share_pct": 0.0,
        "recorded_at": db.clock_iso(recorded_at),
        "kind": kind,
    }
    svc.init_common(record)
    db.insert("market_share_observations", record)
    svc.recompute_dealer_family_observed_shares(dealer["id"], product_family)
    return resp.ok(svc.serialize("market_share_observations", record)), 201


def list_observations(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "recorded_at": q(request, "recorded_at"),
    }
    records = [r for r in db.rows("market_share_observations") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("market_share_observations", r) for r in records], limit, offset), 200


def get_observation(request: Request, actor):
    record = svc.get_observation(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own observations.")
    return resp.ok(svc.serialize("market_share_observations", record)), 200


def list_dealer_observations(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own observations.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("market_share_observations") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("market_share_observations", r) for r in records], limit, offset), 200


# ===========================================================================
# Certification records
# ===========================================================================
def create_certification(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    credential_code = request.enum("credential_code", ["DEALER_MASTER", "DEALER_CERTIFIED"])

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "technician_name": request.string("technician_name"),
        "product_family": product_family,
        "credential_code": credential_code,
        "certified_at": db.clock_iso(request.datetime("certified_at")),
        "recurrence_within_period": False,
        "revoked": False,
    }
    svc.init_common(record)
    db.insert("certification_records", record)
    svc.recompute_recurrence(record)
    for other in db.rows("certification_records"):
        svc.recompute_recurrence(other)
    svc.recompute_certified_family_count(dealer)
    _refresh_agreements_for(dealer["id"], product_family)
    return resp.ok(svc.serialize("certification_records", record)), 201


def create_agreement_certification(request: Request):
    """Register a credential through its parent agreement.

    PRD §2.5: "Modification of an existing resource, including the creation of a
    nested row that is addressed through its parent, returns `200 OK`."
    """
    agreement = svc.get_agreement(request.path_params["id"])
    dealer = svc.get_dealer(agreement["dealer_id"])
    credential_code = request.enum("credential_code", ["DEALER_MASTER", "DEALER_CERTIFIED"])

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "technician_name": request.string("technician_name"),
        "product_family": agreement["product_family"],
        "credential_code": credential_code,
        "certified_at": db.clock_iso(request.datetime("certified_at")),
        "recurrence_within_period": False,
        "revoked": False,
    }
    svc.init_common(record)
    db.insert("certification_records", record)
    svc.recompute_recurrence(record)
    for other in db.rows("certification_records"):
        svc.recompute_recurrence(other)
    svc.recompute_certified_family_count(dealer)
    _refresh_agreements_for(dealer["id"], agreement["product_family"])
    return resp.ok(svc.serialize("certification_records", record)), 200


def _refresh_agreements_for(dealer_id, product_family):
    for agreement in db.rows("dealer_agreements"):
        if agreement["dealer_id"] != dealer_id or agreement["product_family"] != product_family:
            continue
        svc.refresh_agreement_derived(agreement)
        svc.touch(agreement)


def list_certifications(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "technician_name": q(request, "technician_name"),
    }
    status_filter = q(request, "status")
    records = [r for r in db.rows("certification_records") if svc.matches_filters(r, filters)]
    if status_filter is not None:
        records = [r for r in records if svc.cert_status(r) == status_filter]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("certification_records", r) for r in records], limit, offset), 200


def get_certification(request: Request, actor):
    record = svc.get_certification(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own credentials.")
    return resp.ok(svc.serialize("certification_records", record)), 200


def list_dealer_certifications(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own credentials.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("certification_records") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("certification_records", r) for r in records], limit, offset), 200


def revoke_certification(request: Request):
    record = svc.get_certification(request.path_params["id"])
    if svc.cert_status(record) != "ACTIVE":
        raise ApiError(E_INVALID_STATE)
    record["revoked"] = True
    svc.touch(record)
    dealer = svc.get_dealer(record["dealer_id"])
    svc.recompute_certified_family_count(dealer)
    _refresh_agreements_for(dealer["id"], record["product_family"])
    return resp.ok(svc.serialize("certification_records", record)), 200


# ===========================================================================
# Machine population records
# ===========================================================================
def create_population(request: Request):
    dealer = svc.get_dealer(request.string("dealer_id"))
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    machine_serial = request.string("machine_serial")

    for existing in db.rows("machine_population_records"):
        if existing["machine_serial"] == machine_serial and existing["status"] != "RETIRED":
            raise ApiError("ERR_DUPLICATE_SERIAL", "this machine serial is already registered")

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "machine_serial": machine_serial,
        "machine_operating_weight_lb": request.integer("machine_operating_weight_lb"),
        "meter_hours": request.number("meter_hours"),
        "weight_class_tier": "MIDDLE",
        "coverage_multiplier": 1.0,
        "projected_annual_parts_units": 0,
        "status": "ACTIVE",
    }
    svc.init_common(record)
    db.insert("machine_population_records", record)
    svc.refresh_population_record(record)
    svc.recompute_dealer_commitment_tiers(dealer["id"])
    return resp.ok(svc.serialize("machine_population_records", record)), 201


def list_population(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "status": q(request, "status"),
        "machine_serial": q(request, "machine_serial"),
    }
    records = [r for r in db.rows("machine_population_records") if svc.matches_filters(r, filters)]
    if actor.role == "InputDealer":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("machine_population_records", r) for r in records], limit, offset), 200


def get_population(request: Request, actor):
    record = svc.get_population(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own population records.")
    return resp.ok(svc.serialize("machine_population_records", record)), 200


def list_dealer_population(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own population records.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("machine_population_records") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("machine_population_records", r) for r in records], limit, offset), 200


def forecast(request: Request, actor):
    dealer_id = q(request, "dealer_id")
    dealer = svc.get_dealer(dealer_id)
    if actor.role == "InputDealer" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may forecast only its own population.")
    return resp.ok(svc.forecast_parts_demand(dealer["id"])), 200


def coverage_snapshot(request: Request, actor):
    record = svc.get_population(request.path_params["id"])
    if actor.role == "InputDealer" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer principal may read only its own population records.")
    commitment = svc.first_family_commitment(record["dealer_id"], record["product_family"])
    data = dict(record)
    if commitment is not None:
        data["machine_population_units"] = commitment["machine_population_units"]
    return resp.ok(svc.dealer_coverage_snapshot(data, commitment)), 200


def sweep_metrics(request: Request):
    dealer_id = q(request, "dealer_id")
    svc.get_dealer(dealer_id)
    return resp.ok(svc.sweep_metrics(dealer_id)), 200


def read_meter(request: Request):
    record = svc.get_population(request.path_params["id"])
    meter_hours = request.number("meter_hours")
    # A lower reading is retained in preference to a higher one.
    if meter_hours < float(record["meter_hours"]):
        record["meter_hours"] = meter_hours
    svc.touch(record)
    svc.refresh_population_record(record)
    svc.recompute_dealer_commitment_tiers(record["dealer_id"])
    return resp.ok(svc.serialize("machine_population_records", record)), 200


def retire_population(request: Request):
    record = svc.get_population(request.path_params["id"])
    if record["status"] != "ACTIVE":
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(record["dealer_id"])
    accepted = any(
        t["status"] == "ACCEPTED" and svc.serial_matches(t["machine_serial"], record["machine_serial"])
        for t in db.rows("trade_in_units")
    )
    if not accepted:
        raise ApiError(E_TRADE_IN_NOT_ACCEPTED)

    record["status"] = "RETIRED"
    svc.touch(record)
    svc.recompute_dealer_commitment_tiers(dealer["id"], record["product_family"])
    for commitment in svc.dealer_commitments(dealer["id"]):
        if commitment["product_family"] == record["product_family"]:
            svc.set_deferred_rule(commitment["id"], False)
    return resp.ok(svc.serialize("machine_population_records", record)), 200


def reinstate_population(request: Request):
    record = svc.get_population(request.path_params["id"])
    if record["status"] != "RETIRED":
        raise ApiError(E_INVALID_STATE)
    dealer = svc.get_dealer(record["dealer_id"])
    for trade_in in db.rows("trade_in_units"):
        if trade_in["status"] != "REMARKETED":
            continue
        if svc.serial_matches(trade_in["machine_serial"], record["machine_serial"]):
            raise ApiError(E_MACHINE_REMARKETED)
    for other in db.rows("machine_population_records"):
        if other["id"] == record["id"]:
            continue
        if other["machine_serial"] == record["machine_serial"] and other["status"] != "RETIRED":
            raise ApiError(E_DUPLICATE_SERIAL)

    record["status"] = "ACTIVE"
    svc.touch(record)
    svc.refresh_population_record(record)
    svc.recompute_dealer_commitment_tiers(dealer["id"], record["product_family"])
    for commitment in svc.dealer_commitments(dealer["id"]):
        if commitment["product_family"] == record["product_family"]:
            svc.set_deferred_rule(commitment["id"], True)
    return resp.ok(svc.serialize("machine_population_records", record)), 200


# ===========================================================================
# Registration
# ===========================================================================
def register_routes():
    reg.register("POST", BASE + "/parts-commitments", create_commitment, ["PartsManager"], 201, ["agreement_id", "dealer_id", "product_family", "machine_population_units", "machine_population_slope?", "planned_annual_units", "emergency_stocking_target_pct", "emergency_fill_window_hours", "expected_dealer_version"], "create_commitment")
    reg.register("GET", BASE + "/parts-commitments", list_commitments, ["PartsManager", "DealerNetworkManager", "DealerPerformanceReviewer", "InputDealer"], 200, ["dealer_id?", "agreement_id?", "product_family?", "status?"], "list_commitments")
    reg.register("GET", BASE + "/parts-commitments/{id}", get_commitment, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "get_commitment")
    reg.register("GET", BASE + "/dealer-agreements/{id}/parts-commitments", list_agreement_commitments, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_agreement_commitments")
    reg.register("GET", BASE + "/dealers/{id}/parts-commitments", list_dealer_commitments, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_dealer_commitments")
    reg.register("POST", BASE + "/parts-commitments/{id}/submit", submit_commitment, ["PartsManager"], 200, [], "submit_commitment")
    reg.register("POST", BASE + "/parts-commitments/{id}/ready-for-orders", ready_for_orders, ["PartsManager"], 200, [], "ready_for_orders")
    reg.register("POST", BASE + "/parts-commitments/{id}/suspend", suspend_commitment, ["PartsManager"], 200, [], "suspend_commitment")
    reg.register("POST", BASE + "/parts-commitments/{id}/suspend-core-credit", suspend_core_credit, ["PartsManager"], 200, [], "suspend_core_credit")
    reg.register("POST", BASE + "/parts-commitments/{id}/settle-core-credit", settle_core_credit, ["PartsManager"], 200, ["credit_settlement_cents"], "settle_core_credit")
    reg.register("POST", BASE + "/parts-commitments/{id}/reinstate", reinstate_commitment, ["PartsManager"], 200, [], "reinstate_commitment")

    reg.register("POST", BASE + "/parts-order-batches", create_batch, ["PartsManager"], 201, ["commitment_id", "product_family", "requested_units", "core_units", "core_return_required", "emergency?", "requested_at"], "create_batch")
    reg.register("GET", BASE + "/parts-order-batches", list_batches, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, ["commitment_id?", "product_family?", "status?", "emergency?"], "list_batches")
    reg.register("GET", BASE + "/parts-order-batches/{id}", get_batch, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "get_batch")
    reg.register("GET", BASE + "/parts-commitments/{id}/parts-order-batches", list_commitment_batches, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_commitment_batches")
    reg.register("POST", BASE + "/parts-order-batches/{id}/place-order", place_order, ["PartsManager"], 200, [], "place_order")
    reg.register("POST", BASE + "/parts-order-batches/{id}/receive", receive_batch, ["PartsManager"], 200, ["ordered_ref"], "receive_batch")
    reg.register("POST", BASE + "/parts-order-batches/{id}/return-core", return_core, ["PartsManager"], 200, ["core_units"], "return_core")
    reg.register("POST", BASE + "/parts-order-batches/{id}/core-return", core_return, ["PartsManager"], 200, ["core_units?"], "core_return")
    reg.register("POST", BASE + "/parts-order-batches/{id}/cancel-core-return", cancel_core_return, ["PartsManager"], 200, [], "cancel_core_return")
    reg.register("POST", BASE + "/parts-order-batches/{id}/close", close_batch, ["PartsManager"], 200, [], "close_batch")
    reg.register("POST", BASE + "/parts-order-batches/{id}/cancel", cancel_batch, ["PartsManager"], 200, [], "cancel_batch")

    reg.register("POST", BASE + "/rebuild-claims", create_claim, ["RebuildProgramSpecialist"], 201, ["dealer_id", "product_family", "machine_serial", "machine_operating_weight_lb", "client_meter_hours", "requested_at", "core_purchase_value_cents?", "rebuild_labor_hours", "rebuild_labor_rate_cents", "certified_rebuild_spec_code"], "create_claim")
    reg.register("GET", BASE + "/rebuild-claims", list_claims, ["RebuildProgramSpecialist", "PartsManager", "InputDealer"], 200, ["dealer_id?", "product_family?", "machine_serial?", "status?"], "list_claims")
    reg.register("GET", BASE + "/rebuild-claims/{id}", get_claim, ["RebuildProgramSpecialist", "PartsManager", "InputDealer"], 200, [], "get_claim")
    reg.register("GET", BASE + "/dealers/{id}/rebuild-claims", list_dealer_claims, ["RebuildProgramSpecialist", "PartsManager", "InputDealer"], 200, [], "list_dealer_claims")
    reg.register("POST", BASE + "/rebuild-claims/{id}/approve", approve_claim, ["RebuildProgramSpecialist"], 200, ["expected_rebuildclaim_version"], "approve_claim")
    reg.register("POST", BASE + "/rebuild-claims/{id}/deny", deny_claim, ["RebuildProgramSpecialist"], 200, [], "deny_claim")
    reg.register("POST", BASE + "/rebuild-claims/{id}/decline", decline_claim, ["RebuildProgramSpecialist"], 200, [], "decline_claim")
    reg.register("POST", BASE + "/rebuild-claims/{id}/request-core-return", request_core_return, ["PartsManager"], 200, [], "request_core_return")
    reg.register("POST", BASE + "/rebuild-claims/{id}/core-return", claim_core_return, ["PartsManager"], 200, ["core_returned_at"], "claim_core_return")
    reg.register("POST", BASE + "/rebuild-claims/{id}/deliver", deliver_claim, ["RebuildProgramSpecialist"], 200, [], "deliver_claim")
    reg.register("POST", BASE + "/rebuild-claims/{id}/certify", certify_claim, ["RebuildProgramSpecialist"], 200, [], "certify_claim")

    reg.register("POST", BASE + "/support-agreements", create_support_agreement, ["PartsManager"], 201, ["dealer_id", "machine_serial", "plan_tier", "enrolled_at"], "create_support_agreement")
    reg.register("GET", BASE + "/support-agreements", list_support_agreements, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, ["dealer_id?", "machine_serial?", "plan_tier?", "status?"], "list_support_agreements")
    reg.register("GET", BASE + "/support-agreements/{id}", get_support_agreement, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "get_support_agreement")
    reg.register("GET", BASE + "/dealers/{id}/support-agreements", list_dealer_support_agreements, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_dealer_support_agreements")
    reg.register("POST", BASE + "/support-agreements/{id}/suspend", suspend_support_agreement, ["PartsManager"], 200, [], "suspend_support_agreement")
    reg.register("POST", BASE + "/support-agreements/{id}/reinstate", reinstate_support_agreement, ["PartsManager"], 200, [], "reinstate_support_agreement")
    reg.register("POST", BASE + "/support-agreements/{id}/terminate", terminate_support_agreement, ["PartsManager"], 200, [], "terminate_support_agreement")

    reg.register("POST", BASE + "/market-share-observations", create_observation, ["DealerPerformanceReviewer"], 201, ["dealer_id", "product_family", "observed_machine_units", "territory_machine_units", "recorded_at", "kind?"], "create_observation")
    reg.register("GET", BASE + "/market-share-observations", list_observations, ["DealerPerformanceReviewer", "DealerNetworkManager", "InputDealer"], 200, ["dealer_id?", "product_family?", "recorded_at?"], "list_observations")
    reg.register("GET", BASE + "/market-share-observations/{id}", get_observation, ["DealerPerformanceReviewer", "DealerNetworkManager", "InputDealer"], 200, [], "get_observation")
    reg.register("GET", BASE + "/dealers/{id}/market-share-observations", list_dealer_observations, ["DealerPerformanceReviewer", "DealerNetworkManager", "InputDealer"], 200, [], "list_dealer_observations")

    reg.register("POST", BASE + "/machine-population-records", create_population, ["PartsManager"], 201, ["dealer_id", "product_family", "machine_serial", "machine_operating_weight_lb", "meter_hours"], "create_population")
    reg.register("GET", BASE + "/machine-population-records", list_population, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, ["dealer_id?", "product_family?", "status?", "machine_serial?"], "list_population")
    reg.register("GET", BASE + "/machine-population-records/forecast", forecast, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, ["dealer_id"], "forecast")
    reg.register("GET", BASE + "/machine-population-records/sweep-metrics", sweep_metrics, ["DealerPerformanceReviewer", "PartsManager"], 200, ["dealer_id"], "sweep_metrics")
    reg.register("GET", BASE + "/machine-population-records/{id}", get_population, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "get_population")
    reg.register("GET", BASE + "/machine-population-records/{id}/coverage-snapshot", coverage_snapshot, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "coverage_snapshot")
    reg.register("GET", BASE + "/dealers/{id}/machine-population-records", list_dealer_population, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_dealer_population")
    reg.register("POST", BASE + "/machine-population-records/{id}/read-meter", read_meter, ["PartsManager"], 200, ["meter_hours"], "read_meter")
    reg.register("POST", BASE + "/machine-population-records/{id}/retire", retire_population, ["PartsManager"], 200, [], "retire_population")
    reg.register("POST", BASE + "/machine-population-records/{id}/reinstate", reinstate_population, ["PartsManager"], 200, [], "reinstate_population")

    reg.register("POST", BASE + "/certification-records", create_certification, ["PartsManager"], 201, ["dealer_id", "technician_name", "product_family", "credential_code", "certified_at"], "create_certification")
    reg.register("GET", BASE + "/certification-records", list_certifications, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, ["dealer_id?", "product_family?", "technician_name?", "status?"], "list_certifications")
    reg.register("GET", BASE + "/certification-records/{id}", get_certification, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "get_certification")
    reg.register("GET", BASE + "/dealers/{id}/certification-records", list_dealer_certifications, ["PartsManager", "DealerNetworkManager", "InputDealer"], 200, [], "list_dealer_certifications")
    reg.register("POST", BASE + "/dealer-agreements/{id}/certification-records", create_agreement_certification, ["PartsManager"], 200, ["technician_name", "credential_code", "certified_at"], "create_agreement_certification")
    reg.register("POST", BASE + "/certification-records/{id}/revoke", revoke_certification, ["PartsManager"], 200, [], "revoke_certification")