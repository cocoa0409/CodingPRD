"""Disease testing (PRD 3.3)."""

from flask import Blueprint

import auth
import cascades
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("health", __name__)


@bp.post("/sires/<sire_id>/health-tests")
def order_health_test(sire_id):
    values = validate.parse([
        F("facility_id", "id", required=True),
        F("test_type", "enum", required=True, enum=config.TEST_TYPES),
        F("sample_date", "date", required=True),
        F("validity_days", "integer", required=True, min=0),
        F("retest_of_test_id", "id", default=None),
    ])
    auth.require_role(config.ROLE_STAFF_VET)
    sire = resolve.need("sires", sire_id)
    resolve.need("facilities", values["facility_id"])
    target = resolve.optional("health_tests", values["retest_of_test_id"])
    # Band 4 -- one outstanding PENDING test per (sire, test_type).
    for existing in store.DB["health_tests"].values():
        if (existing["sire_id"] == sire["id"] and existing["test_type"] == values["test_type"]
                and existing["result"] == "PENDING"):
            fail("ERR_DUPLICATE_PENDING_TEST",
                 "This bull already carries a PENDING %s test." % values["test_type"])
    # Band 9 -- referential: the retest target must be re-runnable.
    if target is not None:
        if (target["sire_id"] != sire["id"] or target["test_type"] != values["test_type"]
                or target["result"] not in ("POSITIVE", "INCONCLUSIVE")):
            fail("ERR_INVALID_RETEST_TARGET",
                 "A retest target must be the same bull's same-type POSITIVE or INCONCLUSIVE test.")
    # Band 10 -- temporal.
    if store.dt_of(values["sample_date"]) > store.clock():
        fail("ERR_SAMPLE_DATE_FUTURE", "sample_date may not be later than the logical clock.")
    rec = store.new_record("health_tests", {
        "sire_id": sire["id"],
        "facility_id": values["facility_id"],
        "test_type": values["test_type"],
        "sample_date": values["sample_date"],
        "validity_days": values["validity_days"],
        "result": "PENDING",
        "valid_until": None,
        "resulted_at": None,
        "recorded_by_user_id": None,
        "retest_of_test_id": values["retest_of_test_id"],
    })
    return envelope.created(serializers.health_test(rec))


@bp.get("/health-tests/<test_id>")
def read_health_test(test_id):
    auth.require_role(config.ROLE_STAFF_VET, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_EXPORT_COORD)
    rec = resolve.need("health_tests", test_id)
    return envelope.ok(serializers.health_test(rec))


@bp.get("/health-tests")
def list_health_tests():
    auth.require_role(config.ROLE_STAFF_VET, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_EXPORT_COORD, config.ROLE_FACILITY_MANAGER)
    limit, offset = validate.pagination()
    sire_id = validate.qstr("sire_id")
    facility_id = validate.qstr("facility_id")
    test_type = validate.qenum("test_type", config.TEST_TYPES)
    result = validate.qenum("result", config.TEST_RESULTS)
    retest_of_test_id = validate.qstr("retest_of_test_id")
    items = []
    for rec in store.rows("health_tests"):
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if facility_id is not None and rec["facility_id"] != facility_id:
            continue
        if test_type is not None and rec["test_type"] != test_type:
            continue
        if result is not None and rec["result"] != result:
            continue
        if retest_of_test_id is not None and rec["retest_of_test_id"] != retest_of_test_id:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.health_test)


@bp.post("/health-tests/<test_id>/result")
def record_health_test_result(test_id):
    values = validate.parse([
        F("result", "enum", required=True, enum=config.RESULT_VERDICTS),
    ])
    auth.require_role(config.ROLE_STAFF_VET)
    user = auth.require_user_id()
    rec = resolve.need("health_tests", test_id)
    if rec["result"] != "PENDING":
        fail("ERR_HEALTH_TEST_STATE", "Only a PENDING test may be resulted.")
    verdict = values["result"]
    rec["result"] = verdict
    rec["resulted_at"] = store.clock_iso()
    rec["recorded_by_user_id"] = user
    if verdict == "NEGATIVE":
        rec["valid_until"] = store.iso(
            store.plus_days(store.dt_of(rec["sample_date"]), rec["validity_days"]))
    store.touch(rec)
    if verdict == "POSITIVE" and rec["test_type"] in config.BASE_REQUIRED_TEST_TYPES:
        sire = store.get("sires", rec["sire_id"])
        if sire is not None and sire["collection_status"] == "ELIGIBLE":
            cascades.suspend_sire(sire, config.SUSP_POSITIVE_TEST,
                                  config.CANCEL_SIRE_SUSPENDED, "at_or_after")
    return envelope.ok(serializers.health_test(rec))
