"""Registry: equipment models, installed units, applicability rows and dealers."""
from flask import Blueprint

import auth
import domain
import envelope
import serializers
import store
from errors import ApiError

bp = Blueprint("registry", __name__)

REGIONS = {"NA", "EU", "APAC", "LATAM"}
TIERS = {"PLATINUM", "GOLD", "SILVER"}


def fk(data, field, getter):
    """Priority-6 foreign key resolution. Absent / non-string values defer to
    the priority-7 schema check."""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return getter(value)


# ------------------------------------------------------ EquipmentModel -----
@bp.post("/aftermarket/equipment-models")
def create_model():
    auth.require("PlatformAdmin")
    data = auth.body()
    model_code = auth.req_str(data, "model_code")
    name = auth.req_str(data, "name")
    production_end_date = auth.req_datetime(data, "production_end_date")
    support_end_date = auth.req_datetime(data, "support_end_date")
    domain.unique_or_400(store.equipment_models, "model_code", model_code)

    rec = store.new_record("EquipmentModel", {
        "model_code": model_code,
        "name": name,
        "production_end_date": production_end_date,
        "support_end_date": support_end_date,
    })
    store.equipment_models[rec["id"]] = rec
    return envelope.created(serializers.equipment_model(rec))


@bp.get("/aftermarket/equipment-models/<model_id>")
def read_model(model_id):
    auth.require("PlatformAdmin", "AftermarketPlanner", "InventoryController",
                 "DealerUser", "PricingAnalyst")
    return envelope.ok(serializers.equipment_model(domain.get_model(model_id)))


# ------------------------------------------------------- InstalledUnit -----
@bp.post("/aftermarket/installed-units")
def create_installed_unit():
    auth.require("PlatformAdmin")
    data = auth.body()
    fk(data, "model_id", domain.get_model)
    fk(data, "dealer_id", domain.get_dealer)

    model_id = auth.req_id(data, "model_id")
    dealer_id = auth.req_id(data, "dealer_id")
    serial_number = auth.req_str(data, "serial_number")
    build_revision = auth.req_int(data, "build_revision", minimum=0)
    commission_date = auth.req_datetime(data, "commission_date")
    region = auth.req_enum(data, "region", REGIONS)
    domain.unique_or_400(store.installed_units, "serial_number", serial_number)

    rec = store.new_record("InstalledUnit", {
        "model_id": model_id,
        "dealer_id": dealer_id,
        "serial_number": serial_number,
        "build_revision": build_revision,
        "commission_date": commission_date,
        "region": region,
        "status": "ACTIVE",
    })
    store.installed_units[rec["id"]] = rec
    return envelope.created(serializers.installed_unit(rec))


@bp.get("/aftermarket/installed-units/<unit_id>")
def read_installed_unit(unit_id):
    auth.require("PlatformAdmin", "AftermarketPlanner", "InventoryController", "DealerUser")
    return envelope.ok(serializers.installed_unit(domain.get_installed_unit(unit_id)))


@bp.get("/aftermarket/installed-units")
def list_installed_units():
    auth.require("PlatformAdmin", "AftermarketPlanner", "InventoryController", "DealerUser")
    limit, offset = auth.pagination()
    model_id = auth.query_str("model_id")
    dealer_id = auth.query_str("dealer_id")
    status = auth.query_enum("status", {"ACTIVE", "DECOMMISSIONED"})

    rows = list(store.installed_units.values())
    if model_id is not None:
        rows = [r for r in rows if r["model_id"] == model_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.installed_unit(r) for r in page], limit, offset, total)


@bp.post("/aftermarket/installed-units/<unit_id>/decommission")
def decommission_installed_unit(unit_id):
    auth.require("PlatformAdmin")
    unit = domain.get_installed_unit(unit_id)
    unit["status"] = "DECOMMISSIONED"
    store.touch(unit)
    return envelope.ok(serializers.installed_unit(unit))


# --------------------------------------------------- PartApplicability -----
@bp.post("/aftermarket/part-applicabilities")
def create_applicability():
    auth.require("AftermarketPlanner")
    data = auth.body()
    fk(data, "part_id", domain.get_part)
    fk(data, "model_id", domain.get_model)

    part_id = auth.req_id(data, "part_id")
    model_id = auth.req_id(data, "model_id")
    eff_from = auth.req_int(data, "effective_from_build_revision", minimum=0)
    eff_to = auth.opt_int(data, "effective_to_build_revision", default=None, minimum=0)
    qty_per_unit = auth.req_int(data, "qty_per_unit", minimum=1)

    new_to = eff_to if eff_to is not None else float("inf")
    for row in store.part_applicabilities.values():
        if row["part_id"] != part_id or row["model_id"] != model_id:
            continue
        if row["applicability_status"] != "ACTIVE":
            continue
        other_from = row["effective_from_build_revision"]
        other_to = (row["effective_to_build_revision"]
                    if row["effective_to_build_revision"] is not None else float("inf"))
        if eff_from <= other_to and other_from <= new_to:
            raise ApiError("ERR_APPLICABILITY_REVISION_OVERLAP")

    rec = store.new_record("PartApplicability", {
        "part_id": part_id,
        "model_id": model_id,
        "effective_from_build_revision": eff_from,
        "effective_to_build_revision": eff_to,
        "qty_per_unit": qty_per_unit,
        "applicability_status": "ACTIVE",
    })
    store.part_applicabilities[rec["id"]] = rec
    return envelope.created(serializers.part_applicability(rec))


@bp.get("/aftermarket/part-applicabilities/<app_id>")
def read_applicability(app_id):
    auth.require("AftermarketPlanner", "InventoryController", "DealerUser", "PlatformAdmin")
    return envelope.ok(serializers.part_applicability(domain.get_applicability(app_id)))


@bp.get("/aftermarket/part-applicabilities")
def list_applicabilities():
    auth.require("AftermarketPlanner", "InventoryController", "DealerUser", "PlatformAdmin")
    limit, offset = auth.pagination()
    part_id = auth.query_str("part_id")
    model_id = auth.query_str("model_id")
    status = auth.query_enum("applicability_status", {"ACTIVE", "WITHDRAWN"})

    rows = list(store.part_applicabilities.values())
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if model_id is not None:
        rows = [r for r in rows if r["model_id"] == model_id]
    if status is not None:
        rows = [r for r in rows if r["applicability_status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.part_applicability(r) for r in page],
                            limit, offset, total)


@bp.post("/aftermarket/part-applicabilities/<app_id>/withdraw")
def withdraw_applicability(app_id):
    auth.require("AftermarketPlanner")
    row = domain.get_applicability(app_id)
    row["applicability_status"] = "WITHDRAWN"
    store.touch(row)
    return envelope.ok(serializers.part_applicability(row))


# -------------------------------------------------------------- Dealer -----
@bp.post("/aftermarket/dealers")
def create_dealer():
    auth.require("PlatformAdmin")
    data = auth.body()
    dealer_code = auth.req_str(data, "dealer_code")
    tier = auth.req_enum(data, "tier", TIERS)
    region = auth.req_enum(data, "region", REGIONS)
    credit_limit_cents = auth.req_int(data, "credit_limit_cents", minimum=0)
    domain.unique_or_400(store.dealers, "dealer_code", dealer_code)

    rec = store.new_record("Dealer", {
        "dealer_code": dealer_code,
        "tier": tier,
        "region": region,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "lifetime_restocking_fee_cents": 0,
        "lifetime_rebate_cents": 0,
        "credit_hold": False,
        "status": "ACTIVE",
    })
    store.dealers[rec["id"]] = rec
    return envelope.created(serializers.dealer(rec))


@bp.get("/aftermarket/dealers/<dealer_id>")
def read_dealer(dealer_id):
    auth.require("PlatformAdmin", "AftermarketPlanner", "InventoryController", "DealerUser")
    return envelope.ok(serializers.dealer(domain.get_dealer(dealer_id)))


@bp.post("/aftermarket/dealers/<dealer_id>/balance-adjustments")
def adjust_balance(dealer_id):
    auth.require("PlatformAdmin")
    dealer = domain.get_dealer(dealer_id)
    data = auth.body()
    amount_cents = auth.req_int(data, "amount_cents")
    auth.req_str(data, "reason")

    dealer["outstanding_balance_cents"] += amount_cents
    domain.recompute_credit_hold(dealer)
    store.touch(dealer)
    return envelope.ok(serializers.dealer(dealer))


@bp.post("/aftermarket/dealers/<dealer_id>/suspend")
def suspend_dealer(dealer_id):
    auth.require("PlatformAdmin")
    dealer = domain.get_dealer(dealer_id)
    dealer["status"] = "SUSPENDED"
    store.touch(dealer)
    return envelope.ok(serializers.dealer(dealer))
