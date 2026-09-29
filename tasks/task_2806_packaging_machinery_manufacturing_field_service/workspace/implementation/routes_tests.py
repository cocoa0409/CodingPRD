"""Factory and site acceptance testing, the performance guarantee and the
rework / displacement cascade (PRD 3.5, 3.6)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("tests", __name__)

TEST_STATUSES = ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")
TEST_READERS = ("QualityInspector", "ApplicationEngineer", "ProductionPlanner",
                "ServiceManager", "PlatformAdmin")
LIVE_TEST_STATUSES = ("SCHEDULED", "IN_PROGRESS")


@bp.post("/acceptance-tests")
def create_acceptance_test():
    auth.authorize(("QualityInspector",))
    payload = validation.body()
    machine_order_id = validation.req_str(payload, "machine_order_id", 1, None)
    kind = validation.req_enum(payload, "kind", ("FAT", "SAT"))
    scheduled_on = validation.req_date(payload, "scheduled_on")
    required_operators_trained = validation.opt_int(
        payload, "required_operators_trained", 0, None, 0)
    order = domain.must_get("machine_orders", machine_order_id)
    siblings = domain.children("acceptance_tests", "machine_order_id", order["id"])
    if kind == "FAT":
        if order["fulfillment_status"] != "IN_BUILD":
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "A factory test may only be booked while the order "
                           "is IN_BUILD.")
    else:
        if order["fulfillment_status"] != "INSTALLED":
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "A site test may only be booked while the order "
                           "is INSTALLED.")
        passed_fats = [test for test in siblings
                       if test["kind"] == "FAT" and test["status"] == "PASSED"]
        if passed_fats:
            fat = passed_fats[-1]
            if store.parse_date(scheduled_on) < store.parse_date(fat["scheduled_on"]):
                raise ApiError("ERR_SAT_BEFORE_FAT",
                               "A site test may not be dated before its "
                               "factory test.")
    if any(test["kind"] == kind and test["status"] in LIVE_TEST_STATUSES
           for test in siblings):
        raise ApiError("ERR_DUPLICATE_ACCEPTANCE_TEST",
                       "A live %s test already exists for this order." % kind)
    row = store.insert("acceptance_tests", {
        "machine_order_id": order["id"],
        "kind": kind,
        "scheduled_on": scheduled_on,
        "customer_product_supplied": False,
        "containers_supplied_count": 0,
        "measured_rate_cpm": 0,
        "measured_efficiency_pct": 0,
        "operators_trained_count": 0,
        "required_operators_trained": required_operators_trained,
        "attainment_pct": 0,
        "guarantee_met": False,
        "status": "SCHEDULED",
    })
    return envelope.created(row)


@bp.get("/acceptance-tests")
def list_acceptance_tests():
    auth.authorize(TEST_READERS)
    limit, offset = validation.pagination()
    filters = {
        "machine_order_id": validation.query_str("machine_order_id"),
        "kind": validation.query_enum("kind", ("FAT", "SAT")),
        "status": validation.query_enum("status", TEST_STATUSES),
    }
    items = [row for row in store.rows("acceptance_tests")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/acceptance-tests/<acceptance_test_id>")
def read_acceptance_test(acceptance_test_id):
    auth.authorize(TEST_READERS)
    return envelope.ok(domain.must_get("acceptance_tests", acceptance_test_id))


@bp.post("/acceptance-tests/<acceptance_test_id>/start")
def start_acceptance_test(acceptance_test_id):
    auth.authorize(("QualityInspector",))
    payload = validation.body()
    customer_product_supplied = validation.req_bool(
        payload, "customer_product_supplied")
    containers_supplied_count = validation.req_int(
        payload, "containers_supplied_count", 0)
    test = domain.must_get("acceptance_tests", acceptance_test_id)
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TEST_STATE",
                       "Only a SCHEDULED test may be started.")
    if not customer_product_supplied:
        raise ApiError("ERR_CUSTOMER_PRODUCT_REQUIRED",
                       "The customer's own product must be supplied.")
    minimum = (calc.MIN_FAT_CONTAINERS if test["kind"] == "FAT"
               else calc.MIN_SAT_CONTAINERS)
    if containers_supplied_count < minimum:
        raise ApiError("ERR_INSUFFICIENT_CONTAINERS",
                       "A %s run needs at least %d supplied containers."
                       % (test["kind"], minimum))
    test["customer_product_supplied"] = customer_product_supplied
    test["containers_supplied_count"] = containers_supplied_count
    test["status"] = "IN_PROGRESS"
    store.touch(test)
    return envelope.ok(test)


@bp.post("/acceptance-tests/<acceptance_test_id>/finalize")
def finalize_acceptance_test(acceptance_test_id):
    auth.authorize(("QualityInspector",))
    payload = validation.body()
    measured_rate_cpm = validation.req_int(payload, "measured_rate_cpm", 0)
    measured_efficiency_pct = validation.req_pct(
        payload, "measured_efficiency_pct", Decimal("0.00"), Decimal("100.00"))
    operators_trained_count = validation.opt_int(
        payload, "operators_trained_count", 0, None, 0)
    test = domain.must_get("acceptance_tests", acceptance_test_id)
    if test["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TEST_STATE",
                       "Only an IN_PROGRESS test may be finalized.")
    if (test["kind"] == "SAT"
            and operators_trained_count < int(test["required_operators_trained"])):
        raise ApiError("ERR_OPERATOR_TRAINING_INCOMPLETE",
                       "The site crew training log is incomplete.")
    order = store.get("machine_orders", test["machine_order_id"])
    model = domain.order_model(order)
    customer = domain.order_customer(order)
    attainment_pct, guarantee_met = calc.guarantee_attainment(
        measured_rate_cpm, measured_efficiency_pct, model["nameplate_rate_cpm"],
        order["guarantee_basis"], customer["product_variation_pct"],
        model["guarantee_efficiency_pct"])
    test["measured_rate_cpm"] = measured_rate_cpm
    test["measured_efficiency_pct"] = measured_efficiency_pct
    test["operators_trained_count"] = operators_trained_count
    test["attainment_pct"] = attainment_pct
    test["guarantee_met"] = guarantee_met
    test["status"] = "PASSED" if guarantee_met else "FAILED"
    store.touch(test)
    if test["kind"] == "FAT":
        if guarantee_met:
            _fat_passed(order)
        else:
            _fat_failed(order)
    elif guarantee_met:
        _sat_passed(order)
    return envelope.ok(test)


def _order_slot(order, statuses):
    for slot in store.rows("build_slots"):
        if slot["machine_order_id"] == order["id"] and slot["status"] in statuses:
            return slot
    return None


def _fat_passed(order):
    if order["fulfillment_status"] == "IN_BUILD":
        domain.set_order_fulfillment(order, "FAT_PASSED")
    slot = _order_slot(order, ("IN_BUILD",))
    if slot is not None:
        slot["status"] = "COMPLETED"
        store.touch(slot)
        domain.recompute_line_committed_days(
            store.get("production_lines", slot["production_line_id"]))


def _fat_failed(order):
    # hop one -- the order's own counters
    failures = int(order["fat_failure_count"]) + 1
    order["fat_failure_count"] = failures
    order["rework_days"] = int(order["rework_days"]) + calc.REWORK_DAYS_PER_FAT_FAILURE
    abandoned = failures >= calc.MAX_FAT_FAILURES
    order["fulfillment_status"] = "CANCELLED" if abandoned else "FAT_FAILED"
    store.touch(order)
    slot = _order_slot(order, ("IN_BUILD", "REWORK_HOLD"))
    if abandoned:
        # the override: the slot is released rather than held for rework
        if slot is not None:
            slot["status"] = "RELEASED"
            store.touch(slot)
            domain.recompute_line_committed_days(
                store.get("production_lines", slot["production_line_id"]))
        domain.recompute_customer_open_orders(domain.order_customer(order))
        return
    if slot is None:
        return
    # hop two -- the slot is held and lengthened by the new rework days
    slot["status"] = "REWORK_HOLD"
    domain.recompute_slot_geometry(slot, order)
    store.touch(slot)
    line = store.get("production_lines", slot["production_line_id"])
    # hop three -- ledger against the longer slot, then the displacement sweep
    domain.recompute_line_committed_days(line)
    buffer_days = int(line["changeover_buffer_days"])
    sweep_start = store.parse_date(slot["start_date"])
    sweep_end = store.parse_date(store.add_days(slot["end_date"], buffer_days))
    displaced = False
    for other in store.rows("build_slots"):
        if other["id"] == slot["id"]:
            continue
        if other["production_line_id"] != line["id"]:
            continue
        if other["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        other_start = store.parse_date(other["start_date"])
        if not (sweep_start <= other_start < sweep_end):
            continue
        was_confirmed = other["status"] == "CONFIRMED"
        other["status"] = "DISPLACED"
        store.touch(other)
        displaced = True
        if was_confirmed:
            other_order = store.get("machine_orders", other["machine_order_id"])
            if (other_order is not None
                    and other_order["fulfillment_status"] == "SLOTTED"):
                domain.set_order_fulfillment(other_order, "ENGINEERED")
    # hop four -- the ledger again, now that the displaced slots have left
    if displaced:
        domain.recompute_line_committed_days(line)


def _sat_passed(order):
    if order["fulfillment_status"] == "INSTALLED":
        domain.set_order_fulfillment(order, "ACCEPTED")
        domain.recompute_customer_open_orders(domain.order_customer(order))
    for machine in store.rows("installed_machines"):
        if machine["machine_order_id"] == order["id"]:
            if machine["status"] == "INSTALLED":
                machine["status"] = "ACCEPTED"
                store.touch(machine)
            break
