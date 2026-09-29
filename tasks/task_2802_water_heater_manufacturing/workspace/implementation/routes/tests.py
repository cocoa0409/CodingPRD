"""The efficiency-test programme and rating certifications (PRD 3.5 / 3.6)."""

from datetime import timedelta

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import actor_id, endpoint
from services import calc
from services.core import cascade_certification_revocation, resolve, rows

bp = Blueprint("tests", __name__)

TEST_TYPES = ("UEF", "FIRST_HOUR_RATING", "RECOVERY")
TEST_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "VOIDED")
CERT_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "REVOKED", "SUPERSEDED")

TEST_READ_ROLES = ["ComplianceEngineer", "CertificationApprover", "PlantAdmin", "QualityInspector"]
CERT_READ_ROLES = [
    "ComplianceEngineer",
    "CertificationApprover",
    "PlantAdmin",
    "QualityInspector",
    "WarrantyAnalyst",
]


# --------------------------------------------------------------------------
# Efficiency tests
# --------------------------------------------------------------------------

@bp.post("/efficiency-tests")
@endpoint(["ComplianceEngineer"])
def create_test():
    body = validation.json_body()
    product_model_id = validation.string(body, "product_model_id")
    test_cell_id = validation.string(body, "test_cell_id")
    test_type = validation.enum(body, "test_type", TEST_TYPES)
    sample_size = validation.integer(body, "sample_size", minimum=1, maximum=12)
    window_start = validation.timestamp(body, "window_start")
    window_end = validation.timestamp(body, "window_end")

    model = resolve("model", product_model_id)
    cell = resolve("test_cell", test_cell_id)

    # Position 25a: the requested window must leave a free parallel slot.
    overlapping = 0
    for other in rows("test"):
        if other["test_cell_id"] != cell["id"] or other["status"] != "SCHEDULED":
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            overlapping += 1
    if overlapping >= cell["parallel_slots"]:
        raise ApiError("ERR_TEST_CELL_CAPACITY_CONFLICT")

    # Position 25b: the cell's thermal recovery buffer between tests of one model.
    previous_end = None
    for other in rows("test"):
        if other["test_cell_id"] != cell["id"]:
            continue
        if other["product_model_id"] != model["id"]:
            continue
        if other["window_end"] <= window_start:
            if previous_end is None or other["window_end"] > previous_end:
                previous_end = other["window_end"]
    if previous_end is not None:
        if window_start - previous_end < timedelta(hours=cell["cooldown_hours"]):
            raise ApiError("ERR_TEST_CELL_COOLDOWN_VIOLATION")

    # Position 26: window orientation, evaluated after both cell checks.
    if window_start >= window_end:
        raise ApiError("ERR_INVALID_WINDOW")

    row = make_row(
        {
            "product_model_id": model["id"],
            "test_cell_id": cell["id"],
            "test_type": test_type,
            "sample_size": sample_size,
            "window_start": window_start,
            "window_end": window_end,
            "measured_value": None,
            "effective_minimum": None,
            "margin": None,
            "status": "SCHEDULED",
            "recorded_at": None,
        }
    )
    db.db.tests[row["id"]] = row
    return response.created(serializers.efficiency_test(row))


@bp.get("/efficiency-tests/<tid>")
@endpoint(TEST_READ_ROLES)
def read_test(tid):
    return response.ok(serializers.efficiency_test(resolve("test", tid)))


@bp.get("/efficiency-tests")
@endpoint(TEST_READ_ROLES)
def list_tests():
    product_model_id = validation.query_string("product_model_id")
    test_cell_id = validation.query_string("test_cell_id")
    test_type = validation.query_enum("test_type", TEST_TYPES)
    status = validation.query_enum("status", TEST_STATUSES)
    result = rows("test")
    if product_model_id is not None:
        result = [r for r in result if r["product_model_id"] == product_model_id]
    if test_cell_id is not None:
        result = [r for r in result if r["test_cell_id"] == test_cell_id]
    if test_type is not None:
        result = [r for r in result if r["test_type"] == test_type]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.efficiency_test)


@bp.post("/efficiency-tests/<tid>/record-result")
@endpoint(["QualityInspector"])
def record_result(tid):
    test = resolve("test", tid)
    body = validation.json_body()
    measured_value = validation.number(body, "measured_value")

    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TEST_STATE")
    if db.db.now() < test["window_end"]:
        raise ApiError("ERR_TEST_WINDOW_NOT_ELAPSED")

    model = db.db.models[test["product_model_id"]]
    if test["test_type"] == "UEF":
        effective_minimum = calc.uef_effective_minimum(
            model["fuel_type"],
            model["nominal_capacity_gallons"],
            model["insulation_r_value"],
            test["sample_size"],
        )
    else:
        effective_minimum = calc.RATING_FLOOR[test["test_type"]]

    margin = calc.test_margin(measured_value, effective_minimum)
    test["measured_value"] = measured_value
    test["effective_minimum"] = effective_minimum
    test["margin"] = margin
    test["status"] = calc.test_status(margin)
    test["recorded_at"] = db.db.now()
    touch(test)

    # Identical secondary effect on both branches.
    if model["certification_status"] == "UNCERTIFIED":
        model["certification_status"] = "TEST_PENDING"
        touch(model)

    return response.ok(serializers.efficiency_test(test))


# --------------------------------------------------------------------------
# Rating certifications
# --------------------------------------------------------------------------

@bp.post("/rating-certifications")
@endpoint(["ComplianceEngineer"])
def create_certification():
    body = validation.json_body()
    product_model_id = validation.string(body, "product_model_id")
    expected_version = validation.integer(body, "expected_product_model_version")

    model = resolve("model", product_model_id)
    # Position 7: parent version pinning precedes every state and business check.
    if expected_version != model["version"]:
        raise ApiError("ERR_STALE_PARENT_VERSION")

    superseded = [
        c
        for c in rows("certification")
        if c["product_model_id"] == model["id"] and c["status"] in ("DRAFT", "REJECTED")
    ]
    for cert in ordered(superseded):
        cert["status"] = "SUPERSEDED"
        touch(cert)

    row = make_row(
        {
            "product_model_id": model["id"],
            "status": "DRAFT",
            "certified_uef": None,
            "certified_fhr": None,
            "certified_recovery": None,
            "uef_test_count": None,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "effective_date": None,
            "label_serial_prefix": None,
            "reason_code": None,
        }
    )
    db.db.certifications[row["id"]] = row
    touch(model)
    return response.created(serializers.certification(row))


@bp.get("/rating-certifications/<cid>")
@endpoint(CERT_READ_ROLES)
def read_certification(cid):
    return response.ok(serializers.certification(resolve("certification", cid)))


@bp.get("/rating-certifications")
@endpoint(CERT_READ_ROLES)
def list_certifications():
    product_model_id = validation.query_string("product_model_id")
    status = validation.query_enum("status", CERT_STATUSES)
    result = rows("certification")
    if product_model_id is not None:
        result = [r for r in result if r["product_model_id"] == product_model_id]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.certification)


def _passed_values(model_id, test_type):
    tests = [
        t
        for t in rows("test")
        if t["product_model_id"] == model_id
        and t["test_type"] == test_type
        and t["status"] == "PASSED"
    ]
    return [t["measured_value"] for t in ordered(tests)]


@bp.post("/rating-certifications/<cid>/submit")
@endpoint(["ComplianceEngineer"])
def submit_certification(cid):
    cert = resolve("certification", cid)
    if cert["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")

    model_id = cert["product_model_id"]
    uef_values = _passed_values(model_id, "UEF")
    fhr_values = _passed_values(model_id, "FIRST_HOUR_RATING")
    rec_values = _passed_values(model_id, "RECOVERY")
    # Position 20: the test programme must be complete.
    if len(uef_values) < 3 or len(fhr_values) < 1 or len(rec_values) < 1:
        raise ApiError("ERR_INSUFFICIENT_TEST_SAMPLE")

    cert["certified_uef"] = calc.mean_of_rounded(uef_values, 2)
    fhr = calc.mean_of_rounded(fhr_values, 0)
    cert["certified_fhr"] = int(fhr) if fhr is not None else None
    cert["certified_recovery"] = calc.mean_of_rounded(rec_values, 1)
    cert["uef_test_count"] = len(uef_values)
    cert["submitted_by_user_id"] = actor_id()
    cert["reason_code"] = None
    cert["status"] = "SUBMITTED"
    touch(cert)
    return response.ok(serializers.certification(cert))


@bp.post("/rating-certifications/<cid>/approve")
@endpoint(["CertificationApprover"])
def approve_certification(cid):
    cert = resolve("certification", cid)
    body = validation.json_body()
    validation.timestamp(body, "effective_date")

    if cert["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")
    # Position 9: the preparer may not adjudicate.
    if actor_id() == cert["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_APPROVER_IS_SUBMITTER")

    model = db.db.models[cert["product_model_id"]]
    cert["status"] = "APPROVED"
    cert["approved_by_user_id"] = actor_id()
    # The stored effective_date is the logical-clock instant of the approval.
    cert["effective_date"] = db.db.now()
    cert["label_serial_prefix"] = model["model_code"]
    touch(cert)

    for other in ordered(
        [
            c
            for c in rows("certification")
            if c["product_model_id"] == model["id"]
            and c["id"] != cert["id"]
            and c["status"] == "APPROVED"
        ]
    ):
        other["status"] = "SUPERSEDED"
        touch(other)

    if model["certification_status"] != "DECERTIFIED":
        model["certification_status"] = "CERTIFIED"
        model["uef_rated"] = cert["certified_uef"]
        model["fhr_rated"] = cert["certified_fhr"]
        model["recovery_rate_rated"] = cert["certified_recovery"]
        model["label_serial_prefix"] = cert["label_serial_prefix"]
        touch(model)
    return response.ok(serializers.certification(cert))


@bp.post("/rating-certifications/<cid>/reject")
@endpoint(["CertificationApprover"])
def reject_certification(cid):
    cert = resolve("certification", cid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")

    if cert["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")
    if actor_id() == cert["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_APPROVER_IS_SUBMITTER")

    cert["status"] = "REJECTED"
    cert["reason_code"] = reason_code
    cert["certified_uef"] = None
    cert["certified_fhr"] = None
    cert["certified_recovery"] = None
    touch(cert)

    model = db.db.models[cert["product_model_id"]]
    if model["certification_status"] == "UNCERTIFIED":
        model["certification_status"] = "TEST_PENDING"
        touch(model)
    return response.ok(serializers.certification(cert))


@bp.post("/rating-certifications/<cid>/revoke")
@endpoint(["CertificationApprover"])
def revoke_certification(cid):
    cert = resolve("certification", cid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")

    if cert["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")

    cert["status"] = "REVOKED"
    cert["reason_code"] = reason_code
    touch(cert)
    cascade_certification_revocation(db.db.models[cert["product_model_id"]])
    return response.ok(serializers.certification(cert))
