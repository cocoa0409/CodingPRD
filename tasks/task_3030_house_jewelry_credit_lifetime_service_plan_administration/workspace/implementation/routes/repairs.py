"""Repairs at the bench: intake, routing, QC, verification, losses and holds."""

from datetime import timedelta

from flask import request

from constants import CEILING_MULTIPLIER, LOSS_LIABILITY_DEFAULT_CENTS, \
    NATURAL_ORIGIN_CARAT_THRESHOLD
from db import DB, iso, parse_dt
from middleware import guard
from response import (ApiError, Err, as_bool, as_enum, as_int, as_str, body,
                      created_obj, ensure_known, invalid_state, ok_list, ok_obj,
                      pagination, sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"]


def register(app):
    @app.route("/repairs", methods=["POST"])
    def intake_repair():
        guard(["StoreManager", "SalesAssociate"])
        data = body()
        ensure_known(data, ["customer_id", "store_id", "diamond_id", "registration_id",
                            "failure_class", "declared_parts_cents",
                            "declared_labor_cents", "vendor_is_rush",
                            "declared_loss_liability_cents"],
                     optional=("vendor_is_rush", "declared_loss_liability_cents"))
        customer_id = as_str(data, "customer_id")
        store_id = as_str(data, "store_id")
        diamond_id = as_str(data, "diamond_id")
        registration_id = as_str(data, "registration_id")
        failure_class = as_enum(data, "failure_class",
                                ("STONE_LOSS", "SETTING", "PRONG", "RESIZE", "OTHER"))
        parts = as_int(data, "declared_parts_cents", required=True)
        labor = as_int(data, "declared_labor_cents", required=True)

        core.fetch("customers", customer_id, "customer")
        store = core.fetch("stores", store_id, "store")
        diamond = core.fetch("diamonds", diamond_id, "diamond")
        registration = core.fetch("registrations", registration_id, "service plan registration")
        bundle = core.fetch("bundles", registration["bundle_id"], "protection bundle")

        # Priority 21: no new repair may be accepted once the store's capacity
        # cannot cover the obligation, and a suspended store takes no intake.
        core.recompute_store(store)
        if store["store_status"] != "ACTIVE":
            raise ApiError(Err.STORE_CREDIT_CAPACITY_EXCEEDED,
                           "This store may not accept new repair intake.")
        # Priority 16: the pinned registration must still cover the stone.
        if registration["coverage_status"] in ("TERMINATED", "VOID"):
            raise ApiError(Err.PLAN_TERMS_UNSATISFIED)
        # Priority 17: a lapsed plan routes the repair to full-price billing.
        if registration["coverage_status"] == "LAPSED":
            raise ApiError(Err.PLAN_TERMS_UNSATISFIED)
        # Priority 11: the origin-document requirement.
        if diamond["stone_kind"] == "NATURAL" and \
                diamond["carat"] > NATURAL_ORIGIN_CARAT_THRESHOLD and \
                not diamond.get("origin_registry"):
            raise ApiError(Err.ORIGIN_DOCUMENT_MISSING)

        declared_loss = as_int(data, "declared_loss_liability_cents",
                               default=LOSS_LIABILITY_DEFAULT_CENTS)
        plan_is_valid = registration["coverage_status"] == "ACTIVE"
        split = core.repair_liability(parts, labor, declared_loss, bundle, plan_is_valid)
        if split["store_absorbed_cents"] > store["available_credit_capacity_cents"]:
            raise ApiError(Err.STORE_CREDIT_CAPACITY_EXCEEDED)

        repair = core.new_row(
            "repairs",
            customer_id=customer_id,
            store_id=store_id,
            diamond_id=diamond_id,
            registration_id=registration_id,
            vendor_shop_code=None,
            failure_class=failure_class,
            vendor_is_rush=as_bool(data, "vendor_is_rush", default=False),
            declared_parts_cents=parts,
            declared_labor_cents=labor,
            accepted_at=iso(DB.now()),
            promised_delivery_at=None,
            loss_liability_cents=split["loss_liability_cents"],
            insurance_parts_cents=split["insurance_parts_cents"],
            customer_parts_cents=split["customer_parts_cents"],
            customer_labor_cents=split["customer_labor_cents"],
            reserve_cents=split["reserve_cents"],
            store_absorbed_cents=split["store_absorbed_cents"],
            repair_status="INTAKE",
            pickup_deadline_at=None,
            stored_appraisal_id=None,
        )
        core.recompute_store(store)
        return created_obj(repair)

    @app.route("/repairs", methods=["GET"])
    def list_repairs():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("repairs")
        for field in ("customer_id", "store_id", "diamond_id", "registration_id",
                      "stored_appraisal_id", "repair_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/repairs/<ident>", methods=["GET"])
    def get_repair(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("repairs", ident, "repair"))

    @app.route("/repairs/<ident>/route", methods=["POST"])
    def route_repair(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] != "INTAKE":
            raise invalid_state("Only an INTAKE repair may be routed.")
        _assert_plan_terms(repair)
        shop_code = core.vendor_routing_rule(repair["failure_class"], repair["vendor_is_rush"])
        shop = core.vendor_shop_by_code(shop_code)
        if shop is None or shop["vendor_status"] != "ACTIVE":
            raise ApiError(Err.VENDOR_MISSING)
        # Priority 31: the rush shop must hold a signed alliance agreement.
        # PRD §2.7 seeds the shop record's `base_turnaround_days` from that
        # agreement, so a registered shop carrying a positive turnaround is
        # the record of a signed alliance; its absence is the refusal.
        if repair["vendor_is_rush"] and not shop.get("base_turnaround_days"):
            raise ApiError(Err.VENDOR_AGREEMENT_REQUIRED)

        repair["vendor_shop_code"] = shop_code
        accepted = parse_dt(repair["accepted_at"])
        repair["promised_delivery_at"] = iso(
            accepted + timedelta(days=shop["base_turnaround_days"]))
        repair["repair_status"] = "ROUTED"
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is not None:
            diamond["custody_status"] = "AT_VENDOR"
            core.touch(diamond)
        core.touch(repair)
        core.recompute_store(DB.get("stores", repair["store_id"]))
        core.recompute_vendor_shop(shop_code)
        return ok_obj(repair)

    @app.route("/repairs/<ident>/arrive-vendor", methods=["POST"])
    def arrive_vendor(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] != "ROUTED":
            raise invalid_state("Only a ROUTED repair may arrive at the bench.")
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is None or diamond["custody_status"] != "AT_VENDOR":
            raise invalid_state("The stone is not at the vendor.")
        repair["repair_status"] = "IN_REPAIR"
        core.touch(repair)
        return ok_obj(repair)

    @app.route("/repairs/<ident>/submit-qc", methods=["POST"])
    def submit_qc(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] != "IN_REPAIR":
            raise invalid_state("Only an IN_REPAIR repair may be submitted for QC.")
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is None or diamond["custody_status"] != "AT_VENDOR":
            raise invalid_state("The stone is not at the vendor.")
        repair["repair_status"] = "QC_REVIEW"
        diamond["custody_status"] = "IN_VAULT"
        core.touch(diamond)
        core.touch(repair)
        core.recompute_vendor_shop(repair.get("vendor_shop_code"))
        return ok_obj(repair)

    @app.route("/repairs/<ident>/verify", methods=["POST"])
    def verify_repair(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] != "QC_REVIEW":
            raise invalid_state("Only a QC_REVIEW repair may be verified.")
        store = core.fetch("stores", repair["store_id"], "store")
        core.recompute_store(store)
        # Capacity is checked before the liability is booked, not after.
        if store["available_credit_capacity_cents"] < repair["loss_liability_cents"]:
            raise ApiError(Err.STORE_CREDIT_CAPACITY_EXCEEDED)

        repair["repair_status"] = "COMPLETED"
        repair["pickup_deadline_at"] = iso(DB.now() + timedelta(days=store["store_hold_days"]))
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is not None:
            diamond["custody_status"] = "IN_CASE"
            core.touch(diamond)

        appraisal = core.issue_appraisal(repair, repair["customer_id"], "REPLACEMENT")
        purchase = core.new_row(
            "purchases",
            customer_id=repair["customer_id"],
            store_id=repair["store_id"],
            diamond_id=None,
            bundle_id=None,
            base_price_cents=appraisal["appraised_value_cents"],
            origin_purchase_id=None,
            trade_up_credit_cents=min(repair["loss_liability_cents"],
                                      appraisal["appraised_value_cents"]),
            trade_up_floor_cents=0,
            net_amount_cents=0,
            protection_fee_cents=0,
            purchase_status="PENDING",
            completed_at=None,
        )
        core.recompute_purchase_amounts(
            purchase,
            internal_credit=min(repair["loss_liability_cents"],
                                appraisal["appraised_value_cents"]))

        _terminate_covering_registration(repair)
        repair["stored_appraisal_id"] = appraisal["id"]
        core.touch(repair)
        core.recompute_store(store)
        core.touch(purchase)
        return ok_obj(repair)

    @app.route("/repairs/<ident>/declare-unrepairable", methods=["POST"])
    def declare_unrepairable(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] not in ("QC_REVIEW", "ROUTED", "IN_REPAIR"):
            raise invalid_state("This repair cannot be declared unrepairable.")
        if repair["failure_class"] != "STONE_LOSS":
            raise invalid_state("Only a stone-loss repair may be declared unrepairable.")
        repair["repair_status"] = "UNREPAIRABLE"
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is not None:
            diamond["custody_status"] = "WITHDRAWN"
            core.touch(diamond)
        appraisal = core.issue_appraisal(repair, repair["customer_id"], "REPLACEMENT")
        repair["stored_appraisal_id"] = appraisal["id"]
        core.touch(repair)
        core.recompute_store(DB.get("stores", repair["store_id"]))
        return ok_obj(repair)

    @app.route("/repairs/<ident>/declare-loss", methods=["POST"])
    def declare_loss(ident):
        guard(["StoreManager"])
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] != "QC_REVIEW":
            raise invalid_state("Only a QC_REVIEW repair may be declared a verified loss.")
        diamond = DB.get("diamonds", repair["diamond_id"])
        if diamond is None or diamond["custody_status"] not in ("AT_VENDOR", "IN_VAULT"):
            raise invalid_state("The stone's custody does not support a verified loss.")
        repair["repair_status"] = "VERIFIED_LOSS"
        diamond["custody_status"] = "WITHDRAWN"
        core.touch(diamond)
        appraisal = core.issue_appraisal(repair, repair["customer_id"], "REPLACEMENT")
        repair["stored_appraisal_id"] = appraisal["id"]
        core.touch(repair)
        core.recompute_store(DB.get("stores", repair["store_id"]))
        core.recompute_vendor_shop(repair.get("vendor_shop_code"))
        return ok_obj(repair)

    @app.route("/repairs/<ident>/holds", methods=["POST"])
    def request_hold(ident):
        guard(["StoreManager"])
        data = body()
        ensure_known(data, ["extended_promised_delivery_at"])
        requested = parse_dt(as_str(data, "extended_promised_delivery_at"))
        if requested is None:
            raise ApiError(Err.INVALID_REQUEST,
                           "extended_promised_delivery_at must be an ISO 8601 instant.")
        repair = core.fetch("repairs", ident, "repair")
        if repair["repair_status"] not in ("ROUTED", "IN_REPAIR"):
            raise invalid_state("Only a ROUTED or IN_REPAIR repair may take a hold.")

        accepted = parse_dt(repair["accepted_at"])
        base_days = core.turnaround_days_for(repair["vendor_shop_code"])
        ceiling = accepted + timedelta(days=base_days * CEILING_MULTIPLIER)
        current = parse_dt(repair["promised_delivery_at"])

        if requested > ceiling:
            # Priority 14: the extension breaches the 1.5x turnaround ceiling.
            raise ApiError(Err.HOLD_PROMISE_CEILING)

        extension_days = max(0, core.days_between(requested, current))
        hold = core.new_row(
            "holds",
            repair_id=repair["id"],
            extended_promised_delivery_at=iso(requested),
            extension_days=extension_days,
            deadline_adjusted=True,
            imposed_breach_adjustment_cents=0,
            recorded_at=iso(DB.now()),
        )
        repair["promised_delivery_at"] = iso(requested)
        core.touch(repair)
        return ok_obj(hold)

    @app.route("/repairs/abandon-overdue", methods=["POST"])
    def abandon_overdue():
        guard(["CustomerService"])
        abandoned = []
        for repair in sorted_by_created(DB.all("repairs")):
            if repair["repair_status"] != "COMPLETED":
                continue
            deadline = parse_dt(repair.get("pickup_deadline_at"))
            if deadline is None or DB.now() < deadline:
                continue
            repair["repair_status"] = "ABANDONED"
            diamond = DB.get("diamonds", repair["diamond_id"])
            if diamond is not None:
                diamond["custody_status"] = "IN_VAULT"
                core.touch(diamond)
            core.touch(repair)
            core.recompute_store(DB.get("stores", repair["store_id"]))
            abandoned.append(repair["id"])
        return ok_obj({"abandoned_count": len(abandoned), "abandoned_repair_ids": abandoned})


def _assert_plan_terms(repair):
    registration = DB.get("registrations", repair["registration_id"])
    if registration is None:
        raise ApiError(Err.PLAN_TERMS_UNSATISFIED)
    if registration["coverage_status"] in ("TERMINATED", "VOID", "LAPSED"):
        raise ApiError(Err.PLAN_TERMS_UNSATISFIED)


def _terminate_covering_registration(repair):
    registration = DB.get("registrations", repair["registration_id"])
    if registration is None:
        return
    if registration["coverage_status"] == "TERMINATED":
        return
    registration["coverage_status"] = "TERMINATED"
    registration["is_valid"] = False
    for visit in DB.all("visits"):
        if visit["registration_id"] == registration["id"] and \
                visit["inspection_status"] == "SCHEDULED":
            visit["inspection_status"] = "NO_SHOW"
            visit["result"] = "NO_SHOW"
            core.touch(visit)
    core.touch(registration)
    store = DB.get("stores", registration["store_id"])
    if store is not None:
        core.recompute_store(store)