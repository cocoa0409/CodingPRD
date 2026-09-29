"""HR input files: submission, standardization validation and resubmission."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serial
import services
import store
import validate as v
from auth import require
from common import (
    GLOBAL_PAYROLL_OPS,
    PAYROLL_CONTROLLER,
    REGION_ELEMENT_SETS,
    REGIONS,
    SOURCE_SYSTEMS,
    ApiError,
    now,
)
from response import created, object_response
from store import new_row, touch

bp = Blueprint("inputs", __name__)

DRIFT_LIMIT = Decimal("20.00")


@bp.post("/payroll/input-files")
@require(GLOBAL_PAYROLL_OPS, PAYROLL_CONTROLLER)
def create_input_file():
    body = v.json_body()
    cycle_id = v.req_id(body, "cycle_id")
    source_system = v.req_enum(body, "source_system", SOURCE_SYSTEMS)
    record_count = v.req_int(body, "record_count", 0)
    gross_declared = v.req_int(body, "gross_declared_minor", 1)
    elements = v.req_str_map(body, "country_elements")
    region = v.req_enum(body, "residency_region_of_transfer", REGIONS)

    cycle = store.get_cycle(cycle_id)
    engagement = store.engagement_of_cycle(cycle)

    if region != engagement["data_residency_region"]:
        raise ApiError(
            "ERR_DATA_RESIDENCY_VIOLATION",
            "The extract may not be transferred into a region the engagement has not agreed to.",
        )
    if cycle["status"] != "DRAFT":
        raise ApiError("ERR_CYCLE_INVALID_STATE", "Only a DRAFT cycle accepts an HR extract.")
    if now() > cycle["input_cutoff_at"]:
        raise ApiError("ERR_INPUT_CUTOFF_PASSED", "The input cutoff for this cycle has passed.")
    if record_count == 0:
        raise ApiError("ERR_EMPTY_INPUT_FILE", "An extract must describe at least one record.")

    row = new_row(
        {
            "cycle_id": cycle_id,
            "source_system": source_system,
            "record_count": record_count,
            "gross_declared_minor": gross_declared,
            "country_elements": elements,
            "residency_region_of_transfer": region,
            "submitted_at": now(),
            "status": "RECEIVED",
            "rejection_code": None,
            "validated_record_count": 0,
        }
    )
    store.input_files[row["id"]] = row

    cycle["input_submitter_user_id"] = g.user_id
    touch(cycle)
    return created(serial.input_file(row))


@bp.post("/payroll/input-files/<ident>/validate")
@require(GLOBAL_PAYROLL_OPS)
def validate_input_file(ident):
    extract = store.get_input_file(ident)
    cycle = store.get_cycle(extract["cycle_id"])
    if extract["status"] != "RECEIVED" or cycle["status"] != "DRAFT":
        raise ApiError(
            "ERR_INPUT_FILE_INVALID_STATE",
            "Validation requires a RECEIVED extract on a DRAFT cycle.",
        )
    engagement = store.engagement_of_cycle(cycle)

    required = REGION_ELEMENT_SETS[engagement["data_residency_region"]]
    if calc.missing_elements(extract["country_elements"], required):
        extract["status"] = "REJECTED"
        extract["rejection_code"] = "MISSING_ELEMENTS"
        extract["validated_record_count"] = 0
        touch(extract)
        return object_response(serial.input_file(extract))

    baseline = None
    if cycle["prior_cycle_id"] is not None and cycle["prior_cycle_id"] in store.cycles:
        baseline = store.approved_run_of_cycle(cycle["prior_cycle_id"])
    if baseline is not None:
        drift = calc.record_count_drift_pct(
            extract["record_count"], baseline["employee_count"]
        )
        if drift > DRIFT_LIMIT:
            extract["status"] = "REJECTED"
            extract["rejection_code"] = "RECORD_COUNT_DRIFT"
            touch(extract)
            return object_response(serial.input_file(extract))

    for other in store.input_files_of_cycle(cycle["id"]):
        if other["id"] != extract["id"] and other["status"] == "VALIDATED":
            other["status"] = "SUPERSEDED"
            touch(other)

    extract["status"] = "VALIDATED"
    extract["validated_record_count"] = extract["record_count"]
    extract["rejection_code"] = None
    touch(extract)

    services.mint_system_evidence(cycle["id"], "CTRL_INPUT_INTEGRITY")
    return object_response(serial.input_file(extract))


@bp.post("/payroll/input-files/<ident>/resubmit")
@require(GLOBAL_PAYROLL_OPS, PAYROLL_CONTROLLER)
def resubmit_input_file(ident):
    body = v.json_body()
    record_count = v.req_int(body, "record_count", 0)
    gross_declared = v.req_int(body, "gross_declared_minor", 1)
    elements = v.req_str_map(body, "country_elements")

    extract = store.get_input_file(ident)
    cycle = store.get_cycle(extract["cycle_id"])
    if extract["status"] != "REJECTED" or cycle["status"] != "DRAFT":
        raise ApiError(
            "ERR_INPUT_FILE_INVALID_STATE",
            "Resubmission requires a REJECTED extract on a DRAFT cycle.",
        )
    if now() > cycle["input_cutoff_at"]:
        raise ApiError("ERR_INPUT_CUTOFF_PASSED", "The input cutoff for this cycle has passed.")
    if record_count == 0:
        raise ApiError("ERR_EMPTY_INPUT_FILE", "An extract must describe at least one record.")

    extract["record_count"] = record_count
    extract["gross_declared_minor"] = gross_declared
    extract["country_elements"] = elements
    extract["status"] = "RECEIVED"
    extract["rejection_code"] = None
    extract["submitted_at"] = now()
    touch(extract)
    return object_response(serial.input_file(extract))
