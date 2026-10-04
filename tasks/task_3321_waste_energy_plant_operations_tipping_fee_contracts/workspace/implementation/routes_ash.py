"""Landfills, ash shipments, ash tests."""

from decimal import Decimal

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request, err_stale_version
from helpers import (body_json, iso_now_logical, new_entity, parse_date, require_fields,
                     success_list, success_obj, to_decimal, to_int, touch)
from serializers import landfill_out, shipment_out, ash_test_out

bp = Blueprint("ash", __name__)

EO = ["EnvironmentalOfficer"]
READERS = ["EnvironmentalOfficer", "PlantOperator", "Regulator"]
READERS_TESTS = ["EnvironmentalOfficer", "Regulator"]


@bp.post("/wte/landfills")
def create_landfill():
    require_role(EO)
    b = body_json()
    require_fields(b, ["name", "permit_number", "remaining_capacity_tonnes",
                       "daily_receipt_limit_tonnes"])
    name = b["name"]
    if not isinstance(name, str) or not name:
        raise err_invalid_request("name must be a non-empty string")
    permit = b["permit_number"]
    if not isinstance(permit, str) or not permit:
        raise err_invalid_request("permit_number must be a non-empty string")
    remaining = to_decimal(b["remaining_capacity_tonnes"], "remaining_capacity_tonnes")
    if remaining < 0:
        raise err_invalid_request("remaining_capacity_tonnes must be >= 0")
    daily = to_decimal(b["daily_receipt_limit_tonnes"], "daily_receipt_limit_tonnes")
    if daily <= 0:
        raise err_invalid_request("daily_receipt_limit_tonnes must be > 0")
    lf = new_entity({
        "name": name,
        "permit_number": permit,
        "remaining_capacity_tonnes": remaining,
        "daily_receipt_limit_tonnes": daily,
        "status": "ACTIVE",
    })
    store.landfills[lf["id"]] = lf
    return success_obj(landfill_out(lf), 201)


@bp.get("/wte/landfills")
def list_landfills():
    require_role(READERS)
    items = sorted(store.landfills.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("status")
    if q is not None:
        items = [lf for lf in items if lf["status"] == q]
    return success_list([landfill_out(lf) for lf in items])


@bp.get("/wte/landfills/<lid>")
def get_landfill(lid):
    require_role(READERS)
    lf = store.landfills.get(lid)
    if lf is None:
        raise err_not_found("landfill not found")
    return success_obj(landfill_out(lf))


@bp.post("/wte/ash-shipments")
def create_shipment():
    require_role(EO)
    b = body_json()
    require_fields(b, ["landfill_id", "tonnes", "shipped_on",
                       "disposal_fee_cents_per_tonne"])
    lf = store.landfills.get(b["landfill_id"])
    if lf is None:
        raise err_not_found("landfill not found")
    tonnes = to_decimal(b["tonnes"], "tonnes")
    if tonnes <= 0:
        raise err_invalid_request("tonnes must be > 0")
    shipped_on = parse_date(b["shipped_on"], "shipped_on")
    fee = to_int(b["disposal_fee_cents_per_tonne"], "disposal_fee_cents_per_tonne")
    if fee < 0:
        raise err_invalid_request("disposal_fee_cents_per_tonne must be >= 0")
    s = new_entity({
        "landfill_id": lf["id"],
        "tonnes": tonnes,
        "shipped_on": shipped_on,
        "disposal_fee_cents_per_tonne": fee,
        "status": "PLANNED",
        "reject_reason": None,
    })
    store.ash_shipments[s["id"]] = s
    return success_obj(shipment_out(s), 201)


@bp.get("/wte/ash-shipments")
def list_shipments():
    require_role(READERS)
    items = sorted(store.ash_shipments.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("landfill_id")
    if q is not None:
        items = [s for s in items if s["landfill_id"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [s for s in items if s["status"] == q]
    return success_list([shipment_out(s) for s in items])


@bp.get("/wte/ash-shipments/<sid>")
def get_shipment(sid):
    require_role(READERS)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    return success_obj(shipment_out(s))


@bp.post("/wte/ash-shipments/<sid>/submit-testing")
def submit_testing(sid):
    require_role(EO)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    if s["status"] != "PLANNED":
        raise err_invalid_state("shipment is not PLANNED")
    s["status"] = "TEST_PENDING"
    touch(s)
    return success_obj(shipment_out(s))


@bp.post("/wte/ash-shipments/<sid>/complete")
def complete_shipment(sid):
    require_role(EO)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    if s["status"] != "TEST_PENDING":
        raise err_invalid_state("shipment is not TEST_PENDING")
    lf = store.landfills.get(s["landfill_id"])
    if lf is None or lf["status"] != "ACTIVE":
        raise err_invalid_state("landfill is not ACTIVE")
    tests = [t for t in store.ash_tests.values() if t["shipment_id"] == s["id"]]
    if any(not t["passed"] for t in tests):
        raise err_422("ERR_ASH_TEST_FAILED", "a recorded ash test has passed == false")
    if not tests:
        raise err_422("ERR_TEST_REQUIRED", "no ash test recorded for the shipment")
    b = body_json()
    expected = b.get("expected_landfill_version")
    if expected is None or expected != lf["version"]:
        raise err_stale_version("expected_landfill_version does not match landfill version")
    if lf["remaining_capacity_tonnes"] < s["tonnes"]:
        raise err_422("ERR_LANDFILL_CAPACITY", "landfill remaining capacity is insufficient")
    disposed_today = sum(
        (x["tonnes"] for x in store.ash_shipments.values()
         if x["landfill_id"] == lf["id"] and x["shipped_on"] == s["shipped_on"]
         and x["status"] == "DISPOSED"), Decimal("0"))
    if disposed_today + s["tonnes"] > lf["daily_receipt_limit_tonnes"]:
        raise err_422("ERR_LANDFILL_CAPACITY", "daily receipt limit would be exceeded")
    s["status"] = "DISPOSED"
    touch(s)
    lf["remaining_capacity_tonnes"] = lf["remaining_capacity_tonnes"] - s["tonnes"]
    if lf["remaining_capacity_tonnes"] == 0:
        lf["status"] = "CLOSED"
    touch(lf)
    return success_obj(shipment_out(s))


@bp.post("/wte/ash-shipments/<sid>/reject")
def reject_shipment(sid):
    require_role(EO)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    if s["status"] != "TEST_PENDING":
        raise err_invalid_state("shipment is not TEST_PENDING")
    b = body_json()
    reason = b.get("reject_reason")
    if reason is None or (isinstance(reason, str) and not reason):
        raise err_invalid_request("reject_reason is required")
    s["reject_reason"] = reason
    s["status"] = "REJECTED"
    touch(s)
    return success_obj(shipment_out(s))


@bp.post("/wte/ash-shipments/<sid>/tests")
def create_test(sid):
    require_role(EO)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    if s["status"] != "TEST_PENDING":
        raise err_invalid_state("shipment is not TEST_PENDING")
    b = body_json()
    require_fields(b, ["parameter", "measured_value", "limit_value"])
    param = b["parameter"]
    if not isinstance(param, str) or not param:
        raise err_invalid_request("parameter must be a non-empty string")
    measured = to_decimal(b["measured_value"], "measured_value")
    limit = to_decimal(b["limit_value"], "limit_value")
    t = new_entity({
        "shipment_id": s["id"],
        "parameter": param,
        "measured_value": measured,
        "limit_value": limit,
        "passed": measured <= limit,
        "recorded_at": iso_now_logical(store),
    })
    store.ash_tests[t["id"]] = t
    touch(s)
    return success_obj(ash_test_out(t), 201)


@bp.get("/wte/ash-shipments/<sid>/tests")
def list_tests(sid):
    require_role(READERS_TESTS)
    s = store.ash_shipments.get(sid)
    if s is None:
        raise err_not_found("shipment not found")
    items = [t for t in store.ash_tests.values() if t["shipment_id"] == s["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    return success_list([ash_test_out(t) for t in items])
