"""Commissioning tests: booking windows and recording computed verdicts."""

from flask import Blueprint, request

import shape
import store
from calc import commissioning_verdict
from common import TEST_TYPES, kw
from envelope import collection, created, ok
from errors import ApiError, invalid
from rules import require_no_test_window_conflict
from security import guard, path_ref, ref

bp = Blueprint("tests", __name__)

READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
    "ManufacturerWarrantyAgent",
)

MEASURED_FIELDS = {
    "BACKUP_TRANSITION": "transition_ms",
    "CAPACITY_DISCHARGE": "delivered_kwh",
    "ANTI_ISLANDING": "anti_islanding_trip_ms",
    "FIRMWARE_BASELINE": "reported_firmware_version",
}


@bp.route("/commissioning-tests", methods=["POST"])
@guard("CertifiedInstaller")
def create_test(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    system = ref("battery_system", system_id)
    test_type = payload.enum("test_type", TEST_TYPES)
    window_start, window_end = shape.window(payload)

    require_no_test_window_conflict(system["installer_id"], window_start, window_end)

    for existing in store.rows("tests"):
        if (
            existing["battery_system_id"] == system["id"]
            and existing["test_type"] == test_type
        ):
            raise ApiError(
                "ERR_DUPLICATE_TEST",
                "The bank already holds a %s test." % test_type,
            )

    record = store.insert(
        "tests",
        {
            "battery_system_id": system_id,
            "test_type": test_type,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "result": "PENDING",
            "transition_ms": None,
            "delivered_kwh": None,
            "anti_islanding_trip_ms": None,
            "reported_firmware_version": None,
            "recorded_at": None,
        },
    )
    return created(store.view(record))


@bp.route("/commissioning-tests/<test_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_test(actor, test_id):
    record = path_ref(actor, "test", test_id)
    return ok(store.view(record))


@bp.route("/commissioning-tests", methods=["GET"])
@guard(*READ_ROLES)
def list_tests(actor):
    records = store.where(
        "tests",
        battery_system_id=request.args.get("battery_system_id"),
        test_type=request.args.get("test_type"),
        status=request.args.get("status"),
        result=request.args.get("result"),
    )
    return collection(records)


@bp.route("/commissioning-tests/<test_id>/record-result", methods=["POST"])
@guard("CertifiedInstaller")
def record_result(actor, test_id):
    test = path_ref(actor, "test", test_id)
    payload = shape.body()

    test_type = test["test_type"]
    expected = MEASURED_FIELDS[test_type]
    for kind, field in MEASURED_FIELDS.items():
        if kind != test_type and payload.present(field):
            raise invalid(
                "Field '%s' does not belong to a %s test." % (field, test_type)
            )

    transition_ms = None
    delivered_kwh = None
    anti_islanding_trip_ms = None
    reported_firmware_version = None
    if expected == "transition_ms":
        transition_ms = payload.integer("transition_ms")
    elif expected == "delivered_kwh":
        delivered_kwh = payload.number("delivered_kwh")
    elif expected == "anti_islanding_trip_ms":
        anti_islanding_trip_ms = payload.integer("anti_islanding_trip_ms")
    else:
        reported_firmware_version = payload.firmware("reported_firmware_version")

    if test["status"] != "SCHEDULED":
        raise invalid("The test result has already been recorded.")

    test["transition_ms"] = transition_ms
    test["delivered_kwh"] = kw(delivered_kwh) if delivered_kwh is not None else None
    test["anti_islanding_trip_ms"] = anti_islanding_trip_ms
    test["reported_firmware_version"] = reported_firmware_version
    test["status"] = "RECORDED"
    test["recorded_at"] = store.now()
    system = store.get("battery_systems", test["battery_system_id"])
    test["result"] = commissioning_verdict(test, system)
    store.touch(test)
    return ok(store.view(test))
