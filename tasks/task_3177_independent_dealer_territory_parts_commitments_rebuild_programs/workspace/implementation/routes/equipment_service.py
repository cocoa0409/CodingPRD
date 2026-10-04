"""Equipment orders, trade-in remarketing and the service bench."""

from __future__ import annotations

from decimal import Decimal

import db
import middleware
import registry as reg
import response as resp
from errors import (
    ApiError,
    E_COMMITMENT_NOT_FOUND,
    E_INVALID_REQUEST,
    E_DEALER_NOT_FOUND,
    E_DUPLICATE_SERIAL,
    E_INVALID_STATE,
    E_MACHINE_ALREADY_REGISTERED,
    E_MACHINE_POPULATION_RETIRED,
    E_NO_ACTIVE_AGREEMENT,
    E_RESTRICTION_FULL_STOP,
    E_RESTRICTION_MINIMAL,
    E_TRADE_IN_APPRAISAL,
    E_TRADE_IN_NOT_ACCEPTED,
)
from request import PRODUCT_FAMILIES, Request
from routes._common import page_params, paged_response, q
from services import core as svc

BASE = "/dealer-network"


# ===========================================================================
# Equipment orders
# ===========================================================================
def create_equipment_order(request: Request, actor):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    middleware.assert_dealer_scope(actor, dealer["id"])
    product_family = request.enum("product_family", PRODUCT_FAMILIES)
    requested_at = request.datetime("requested_at")

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "machine_serial": request.string("machine_serial"),
        "list_price_cents": request.integer("list_price_cents"),
        "trade_in_serial": request.raw("trade_in_serial"),
        "status": "DRAFT",
        "financing_approval_reference": None,
        "supportable_machine_registered": False,
        "requested_at": db.clock_iso(requested_at),
        "bundle_support_plan": None,
    }
    svc.init_common(record)
    db.insert("equipment_orders", record)
    return resp.ok(svc.serialize("equipment_orders", record)), 201


def list_equipment_orders(request: Request, actor):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "product_family": q(request, "product_family"),
        "status": q(request, "status"),
        "machine_serial": q(request, "machine_serial"),
    }
    records = [r for r in db.rows("equipment_orders") if svc.matches_filters(r, filters)]
    if actor.role == "DealerSalesManager":
        records = [r for r in records if r["dealer_id"] == actor.dealer_id]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("equipment_orders", r) for r in records], limit, offset), 200


def get_equipment_order(request: Request, actor):
    record = svc.get_equipment_order(request.path_params["id"])
    if actor.role == "DealerSalesManager" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer sales manager may act only for its own dealership.")
    return resp.ok(svc.serialize("equipment_orders", record)), 200


def list_dealer_equipment_orders(request: Request, actor):
    dealer = svc.get_dealer(request.path_params["id"])
    if actor.role == "DealerSalesManager" and actor.dealer_id != dealer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer sales manager may act only for its own dealership.")
    limit, offset = page_params(request)
    records = [r for r in db.rows("equipment_orders") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("equipment_orders", r) for r in records], limit, offset), 200


def submit_equipment_order(request: Request, actor):
    record = svc.get_equipment_order(request.path_params["id"])
    middleware.assert_dealer_scope(actor, record["dealer_id"])
    if record["status"] != "DRAFT":
        raise ApiError(E_INVALID_STATE)

    serial = record["machine_serial"]
    for other in db.rows("equipment_orders"):
        if other["id"] == record["id"] or other["status"] == "CANCELLED":
            continue
        if other["machine_serial"] == serial:
            raise ApiError(E_DUPLICATE_SERIAL)
    for population in db.rows("machine_population_records"):
        if population["machine_serial"] == serial and population["status"] == "ACTIVE":
            raise ApiError(E_DUPLICATE_SERIAL)

    record["status"] = "SUBMITTED"
    svc.touch(record)
    if record.get("trade_in_serial"):
        trade_in = {
            "id": db.new_id(),
            "order_id": record["id"],
            "machine_serial": svc.trade_in_serial_for(record["dealer_id"], record["trade_in_serial"]),
            "machine_operating_weight_lb": request.integer("trade_in_weight_lb", required=False, default=0),
            "appraised_value_cents": request.integer("trade_in_appraised_value_cents", required=False, default=0),
            "status": "APPRAISED",
        }
        svc.init_common(trade_in)
        db.insert("trade_in_units", trade_in)
    record["remarketed_price_cents"] = request.integer("remarketed_price_cents", required=False, default=None)
    svc.recompute_supportable_machine_registered(record)
    return resp.ok(svc.serialize("equipment_orders", record)), 200


def approve_financing(request: Request):
    record = svc.get_equipment_order(request.path_params["id"])
    if record["status"] != "SUBMITTED":
        raise ApiError(E_INVALID_STATE)
    reference = request.raw("financing_approval_reference")
    if reference is None or str(reference).strip() == "":
        # PRD §2.5 rung 0: a missing required field is refused with
        # ERR_INVALID_REQUEST before any rung of the ladder is reached.
        raise ApiError(E_INVALID_REQUEST, "financing_approval_reference is required")

    trade_ins = [t for t in db.rows("trade_in_units") if t["order_id"] == record["id"]]
    accepted_total = sum(int(t["appraised_value_cents"]) for t in trade_ins if t["status"] == "ACCEPTED")
    if accepted_total >= int(record["list_price_cents"]):
        raise ApiError(E_TRADE_IN_APPRAISAL)

    record["financing_approval_reference"] = str(reference)
    record["status"] = "FINANCE_APPROVED"
    svc.touch(record)
    for trade_in in trade_ins:
        if trade_in["status"] == "APPRAISED":
            trade_in["status"] = "ACCEPTED"
            svc.touch(trade_in)
    # The financing approval clears the trade-in's appraised value in kind.
    for trade_in in trade_ins:
        trade_in["appraised_value_cents"] = 0
        svc.touch(trade_in)
    svc.adjust_dealer_restriction_credit(record["dealer_id"], accepted_total)
    svc.recompute_supportable_machine_registered(record)
    return resp.ok(svc.serialize("equipment_orders", record)), 200


def deliver_equipment_order(request: Request, actor):
    record = svc.get_equipment_order(request.path_params["id"])
    middleware.assert_dealer_scope(actor, record["dealer_id"])
    if record["status"] != "FINANCE_APPROVED":
        raise ApiError(E_INVALID_STATE)

    dealer = svc.get_dealer(record["dealer_id"])
    has_active = any(
        a["dealer_id"] == dealer["id"] and a["product_family"] == record["product_family"] and a["status"] == "ACTIVE"
        for a in db.rows("dealer_agreements")
    )
    if not has_active:
        raise ApiError(E_NO_ACTIVE_AGREEMENT)

    serial = record["machine_serial"]
    for population in db.rows("machine_population_records"):
        if population["machine_serial"] != serial:
            continue
        if population["status"] == "RETIRED":
            raise ApiError(E_MACHINE_POPULATION_RETIRED)
        if population["status"] == "ACTIVE" and population["dealer_id"] != dealer["id"]:
            raise ApiError(E_MACHINE_ALREADY_REGISTERED)

    if not any(
        p["machine_serial"] == serial for p in db.rows("machine_population_records")
    ):
        population = {
            "id": db.new_id(),
            "dealer_id": dealer["id"],
            "product_family": record["product_family"],
            "machine_serial": serial,
            "machine_operating_weight_lb": request_weight_for(record),
            "meter_hours": 0.0,
            "weight_class_tier": "MIDDLE",
            "coverage_multiplier": 1.0,
            "projected_annual_parts_units": 0,
            "status": "ACTIVE",
        }
        svc.init_common(population)
        db.insert("machine_population_records", population)
        svc.refresh_population_record(population)
        svc.recompute_dealer_commitment_tiers(dealer["id"])

    bundle = request.raw("bundle_support_plan")
    if bundle is not None:
        record["bundle_support_plan"] = bundle
        if not any(
            a["machine_serial"] == serial and a["status"] != "TERMINATED"
            for a in db.rows("support_agreements")
        ):
            support = {
                "id": db.new_id(),
                "dealer_id": dealer["id"],
                "machine_serial": serial,
                "plan_tier": "PREMIUM",
                "enrolled_at": db.now_iso(),
                "coverage_multiplier": 1.5,
                "status": "ACTIVE",
            }
            svc.init_common(support)
            db.insert("support_agreements", support)
            svc.refresh_serial_coverage(serial)
            svc.recompute_dealer_commitment_tiers(dealer["id"], record["product_family"])

    for trade_in in db.rows("trade_in_units"):
        if trade_in["order_id"] != record["id"]:
            continue
        appraised = int(trade_in["appraised_value_cents"])
        remarketed_price = record.get("remarketed_price_cents")
        if remarketed_price is None:
            trade_in["status"] = "SCRAPPED" if appraised <= 0 else "REMARKETED"
        elif int(remarketed_price) * 100 >= 70 * appraised:
            trade_in["status"] = "REMARKETED"
        else:
            trade_in["status"] = "SCRAPPED"
        svc.touch(trade_in)

    svc.recompute_supportable_machine_registered(record)
    record["status"] = "DELIVERED"
    svc.touch(record)
    svc.charge_restriction_deferral(dealer["id"])
    return resp.ok(svc.serialize("equipment_orders", record)), 200


def request_weight_for(record):
    for population in db.rows("machine_population_records"):
        if population["machine_serial"] == record["machine_serial"]:
            return int(population["machine_operating_weight_lb"])
    return int(record.get("machine_operating_weight_lb") or 0)


def cancel_equipment_order(request: Request, actor):
    record = svc.get_equipment_order(request.path_params["id"])
    middleware.assert_dealer_scope(actor, record["dealer_id"])
    if record["status"] == "SUBMITTED":
        record["status"] = "CANCELLED"
        svc.touch(record)
        for trade_in in db.rows("trade_in_units"):
            if trade_in["order_id"] == record["id"]:
                trade_in["status"] = "APPRAISED"
                svc.touch(trade_in)
    elif record["status"] == "FINANCE_APPROVED":
        applied = int(record.get("financing_credit_cents") or 0)
        if svc.dealer_restriction_credit(record["dealer_id"]) < applied:
            raise ApiError(E_INVALID_STATE, "the restriction-order credit is below the applied financing value")
        svc.adjust_dealer_restriction_credit(record["dealer_id"], -applied)
        record["status"] = "CANCELLED"
        svc.touch(record)
    else:
        raise ApiError(E_INVALID_STATE)
    return resp.ok(svc.serialize("equipment_orders", record)), 200


def list_order_trade_ins(request: Request, actor):
    record = svc.get_equipment_order(request.path_params["id"])
    if actor.role == "DealerSalesManager" and actor.dealer_id != record["dealer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "A dealer sales manager may act only for its own dealership.")
    limit, offset = page_params(request)
    records = [t for t in db.rows("trade_in_units") if t["order_id"] == record["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("trade_in_units", t) for t in records], limit, offset), 200


def list_trade_ins(request: Request):
    limit, offset = page_params(request)
    filters = {"order_id": q(request, "order_id"), "status": q(request, "status")}
    records = [t for t in db.rows("trade_in_units") if svc.matches_filters(t, filters)]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("trade_in_units", t) for t in records], limit, offset), 200


# ===========================================================================
# Service orders
# ===========================================================================
def create_service_order(request: Request):
    dealer_id = request.string("dealer_id")
    dealer = svc.get_dealer(dealer_id)
    commitment_id = request.string("commitment_id")
    commitment = svc.get_commitment(commitment_id)
    kind = request.enum("kind", ["EMERGENCY_FILL", "RESTRICTION", "SLA_AUDIT"])
    product_family = request.enum("product_family", PRODUCT_FAMILIES)

    record = {
        "id": db.new_id(),
        "dealer_id": dealer["id"],
        "commitment_id": commitment["id"],
        "kind": kind,
        "product_family": product_family,
        "machine_serial": request.raw("machine_serial"),
        "orderable_ref_enabled": request.boolean("orderable_ref_enabled", required=False, default=False),
        "response_window_hours": commitment["emergency_fill_window_hours"],
        "restriction_scope": request.enum("restriction_scope", ["HOURS_SPENT", "METER_RUNNING", "FULL_STOP"], required=False, default="HOURS_SPENT"),
        "sla_hours": request.number("sla_hours"),
        "origin_rebuild_id": request.raw("origin_rebuild_id"),
        "opened_at": db.stamp(),
        "resolved_at": None,
        "status": "OPEN",
    }
    svc.init_common(record)
    db.insert("service_orders", record)
    svc.recompute_service_order_derived(record)
    svc.recompute_deferral_tiers(dealer["id"])
    return resp.ok(svc.serialize("service_orders", record)), 201


def list_service_orders(request: Request):
    limit, offset = page_params(request)
    filters = {
        "dealer_id": q(request, "dealer_id"),
        "commitment_id": q(request, "commitment_id"),
        "kind": q(request, "kind"),
        "status": q(request, "status"),
        "machine_serial": q(request, "machine_serial"),
    }
    records = [r for r in db.rows("service_orders") if svc.matches_filters(r, filters)]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("service_orders", r) for r in records], limit, offset), 200


def get_service_order(request: Request):
    record = svc.get_service_order(request.path_params["id"])
    return resp.ok(svc.serialize("service_orders", record)), 200


def list_commitment_service_orders(request: Request):
    commitment = svc.get_commitment(request.path_params["id"])
    limit, offset = page_params(request)
    records = svc.sort_by_created(svc.commitment_service_orders(commitment["id"]))
    return paged_response([svc.serialize("service_orders", r) for r in records], limit, offset), 200


def list_dealer_service_orders(request: Request):
    dealer = svc.get_dealer(request.path_params["id"])
    limit, offset = page_params(request)
    records = [r for r in db.rows("service_orders") if r["dealer_id"] == dealer["id"]]
    records = svc.sort_by_created(records)
    return paged_response([svc.serialize("service_orders", r) for r in records], limit, offset), 200


def begin_service_order(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] != "OPEN":
        raise ApiError(E_INVALID_STATE)
    commitment = svc.get_commitment(record["commitment_id"])
    record["response_window_hours"] = commitment["emergency_fill_window_hours"]
    record["status"] = "IN_PROGRESS"
    svc.touch(record)
    return resp.ok(svc.serialize("service_orders", record)), 200


def record_emergency_fill(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] in ("OPEN", "RESOLVED"):
        raise ApiError(E_INVALID_STATE)
    if not record["orderable_ref_enabled"]:
        raise ApiError(E_INVALID_STATE, "a non-orderable reference cannot be filled this way")
    commitment = svc.get_commitment(record["commitment_id"])
    if record["status"] != "FILLED":
        record["status"] = "FILLED"
        svc.touch(record)
        svc.set_deferred_rule(commitment["id"], False)
        svc.recompute_fill_rate(commitment)
        svc.touch(commitment)
    svc.recompute_service_order_derived(record)
    return resp.ok(svc.serialize("service_orders", record)), 200


def escalate_service_order(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] != "IN_PROGRESS":
        raise ApiError(E_INVALID_STATE)
    if record["orderable_ref_enabled"]:
        raise ApiError(E_INVALID_STATE, "an orderable reference escalates along the fill branch")

    commitment = svc.get_commitment(record["commitment_id"])
    record["status"] = "ESCALATED"
    svc.touch(record)
    commitment["status"] = "PERFORMANCE_DEFICIENT"
    commitment["backorder_opened_at"] = db.stamp()
    svc.touch(commitment)
    dealer = svc.get_dealer(commitment["dealer_id"])
    svc.recompute_open_backorder_units(dealer)
    svc.set_deferred_rule(commitment["id"], False)
    return resp.ok(svc.serialize("service_orders", record)), 200


def fill_service_order(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] not in ("IN_PROGRESS", "ESCALATED"):
        raise ApiError(E_INVALID_STATE)
    if not record["orderable_ref_enabled"]:
        raise ApiError(E_INVALID_STATE, "a non-orderable reference cannot be filled this way")
    commitment = svc.get_commitment(record["commitment_id"])
    record["status"] = "FILLED"
    svc.touch(record)
    svc.set_deferred_rule(commitment["id"], False)
    svc.recompute_fill_rate(commitment)
    svc.touch(commitment)
    return resp.ok(svc.serialize("service_orders", record)), 200


def reopen_service_order(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] != "IN_PROGRESS":
        raise ApiError(E_INVALID_STATE)
    if any(
        b["status"] == "ORDERED" for b in svc.commitment_batches(record["commitment_id"])
    ):
        raise ApiError(E_INVALID_STATE, "a batch of the linked commitment is already ordered")
    commitment = svc.get_commitment(record["commitment_id"])
    record["status"] = "OPEN"
    record["response_window_hours"] = commitment["emergency_fill_window_hours"]
    svc.touch(record)
    svc.recompute_deferral_tiers(record["dealer_id"])
    return resp.ok(svc.serialize("service_orders", record)), 200


def raise_restriction(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(E_INVALID_STATE)
    if record["restriction_scope"] == "FULL_STOP":
        raise ApiError(E_RESTRICTION_FULL_STOP)
    index = svc.RESTRICTION_ORDER.index(record["restriction_scope"])
    record["restriction_scope"] = svc.RESTRICTION_ORDER[index + 1]
    svc.touch(record)
    svc.recompute_service_order_derived(record)
    svc.recompute_deferral_tiers(record["dealer_id"])
    return resp.ok(svc.serialize("service_orders", record)), 200


def lower_restriction(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(E_INVALID_STATE)
    if record["restriction_scope"] == "HOURS_SPENT":
        raise ApiError(E_RESTRICTION_MINIMAL)
    index = svc.RESTRICTION_ORDER.index(record["restriction_scope"])
    previous_score = record["risk_score"]
    record["restriction_scope"] = svc.RESTRICTION_ORDER[index - 1]
    svc.recompute_service_order_derived(record)
    # risk_score falls by exactly the delta the matching raise added.
    delta = previous_score - record["risk_score"]
    if delta:
        record["risk_score"] = previous_score - delta
    svc.touch(record)
    svc.recompute_deferral_tiers(record["dealer_id"])
    return resp.ok(svc.serialize("service_orders", record)), 200


def resolve_service_order(request: Request, actor):
    record = svc.get_service_order(request.path_params["id"])
    middleware.assert_technician_scope(actor, record["dealer_id"])
    if record["status"] == "RESOLVED":
        # A second resolve is a no-op: the first stamp is kept.
        return resp.ok(svc.serialize("service_orders", record)), 200
    if record["status"] not in ("OPEN", "FILLED"):
        raise ApiError(E_INVALID_STATE)
    record["status"] = "RESOLVED"
    record["resolved_at"] = db.stamp()
    svc.touch(record)
    svc.recompute_deferral_tiers(record["dealer_id"])
    return resp.ok(svc.serialize("service_orders", record)), 200


# ===========================================================================
# Registration
# ===========================================================================
def register_routes():
    reg.register("POST", BASE + "/equipment-orders", create_equipment_order, ["DealerSalesManager"], 201, ["dealer_id", "product_family", "machine_serial", "list_price_cents", "trade_in_serial?", "requested_at"], "create_equipment_order")
    reg.register("GET", BASE + "/equipment-orders", list_equipment_orders, ["DealerSalesManager", "FinancePartner", "DealerNetworkManager"], 200, ["dealer_id?", "product_family?", "status?", "machine_serial?"], "list_equipment_orders")
    reg.register("GET", BASE + "/equipment-orders/{id}", get_equipment_order, ["DealerSalesManager", "FinancePartner", "DealerNetworkManager"], 200, [], "get_equipment_order")
    reg.register("GET", BASE + "/dealers/{id}/equipment-orders", list_dealer_equipment_orders, ["DealerSalesManager", "FinancePartner", "DealerNetworkManager"], 200, [], "list_dealer_equipment_orders")
    reg.register("POST", BASE + "/equipment-orders/{id}/submit", submit_equipment_order, ["DealerSalesManager"], 200, ["trade_in_weight_lb?", "trade_in_appraised_value_cents?", "remarketed_price_cents?"], "submit_equipment_order")
    reg.register("POST", BASE + "/equipment-orders/{id}/approve-financing", approve_financing, ["FinancePartner"], 200, ["financing_approval_reference"], "approve_financing")
    reg.register("POST", BASE + "/equipment-orders/{id}/deliver", deliver_equipment_order, ["DealerSalesManager"], 200, ["bundle_support_plan?"], "deliver_equipment_order")
    reg.register("POST", BASE + "/equipment-orders/{id}/cancel", cancel_equipment_order, ["DealerSalesManager"], 200, [], "cancel_equipment_order")
    reg.register("GET", BASE + "/equipment-orders/{id}/trade-ins", list_order_trade_ins, ["DealerSalesManager", "FinancePartner", "DealerNetworkManager"], 200, [], "list_order_trade_ins")
    reg.register("GET", BASE + "/trade-in-units", list_trade_ins, ["DealerSalesManager", "FinancePartner", "DealerNetworkManager"], 200, ["order_id?", "status?"], "list_trade_ins")

    reg.register("POST", BASE + "/service-orders", create_service_order, ["ServiceTechnicianSupervisor"], 201, ["dealer_id", "commitment_id", "kind", "product_family", "machine_serial?", "orderable_ref_enabled?", "restriction_scope?", "sla_hours", "origin_rebuild_id?"], "create_service_order")
    reg.register("GET", BASE + "/service-orders", list_service_orders, ["ServiceTechnicianSupervisor", "PartsManager", "DealerNetworkManager"], 200, ["dealer_id?", "commitment_id?", "kind?", "status?", "machine_serial?"], "list_service_orders")
    reg.register("GET", BASE + "/service-orders/{id}", get_service_order, ["ServiceTechnicianSupervisor", "PartsManager", "DealerNetworkManager"], 200, [], "get_service_order")
    reg.register("GET", BASE + "/parts-commitments/{id}/service-orders", list_commitment_service_orders, ["ServiceTechnicianSupervisor", "PartsManager", "DealerNetworkManager"], 200, [], "list_commitment_service_orders")
    reg.register("GET", BASE + "/dealers/{id}/service-orders", list_dealer_service_orders, ["ServiceTechnicianSupervisor", "PartsManager", "DealerNetworkManager"], 200, [], "list_dealer_service_orders")
    reg.register("POST", BASE + "/service-orders/{id}/begin", begin_service_order, ["ServiceTechnicianSupervisor"], 200, [], "begin_service_order")
    reg.register("POST", BASE + "/service-orders/{id}/record-emergency-fill", record_emergency_fill, ["ServiceTechnicianSupervisor"], 200, [], "record_emergency_fill")
    reg.register("POST", BASE + "/service-orders/{id}/escalate", escalate_service_order, ["ServiceTechnicianSupervisor"], 200, [], "escalate_service_order")
    reg.register("POST", BASE + "/service-orders/{id}/fill", fill_service_order, ["ServiceTechnicianSupervisor"], 200, [], "fill_service_order")
    reg.register("POST", BASE + "/service-orders/{id}/reopen", reopen_service_order, ["ServiceTechnicianSupervisor"], 200, [], "reopen_service_order")
    reg.register("POST", BASE + "/service-orders/{id}/raise-restriction", raise_restriction, ["ServiceTechnicianSupervisor"], 200, [], "raise_restriction")
    reg.register("POST", BASE + "/service-orders/{id}/lower-restriction", lower_restriction, ["ServiceTechnicianSupervisor"], 200, [], "lower_restriction")
    reg.register("POST", BASE + "/service-orders/{id}/resolve", resolve_service_order, ["ServiceTechnicianSupervisor"], 200, [], "resolve_service_order")