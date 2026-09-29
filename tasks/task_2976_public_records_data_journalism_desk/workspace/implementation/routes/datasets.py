"""Dataset and FieldDefinition endpoints (PRD section 3.6)."""
from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_DATA_REPORTER, ROLE_MANAGING_EDITOR,
                        authenticate)
from services import cascades, daycalc

bp = Blueprint("datasets", __name__)

FORMATS = ("CSV", "XLSX", "PDF_SCAN", "FIXED_WIDTH", "API_JSON")
SENSITIVITY_TIERS = ("PUBLIC", "RESTRICTED", "CONFIDENTIAL", "SOURCE_LINKED")
DATA_TYPES = ("STRING", "INTEGER", "DECIMAL", "DATE", "BOOLEAN")
KNOWN_ISSUE_CODES = ("TRUNCATED", "MIXED_FORMAT", "INCONSISTENT_CODING",
                     "OUT_OF_RANGE", "DUPLICATE_KEYS")
SUPPRESSION_METHODS = ("HASH_REDACT", "DROP_COLUMN", "COARSEN_BUCKET", "TOP_CODE")
QUARANTINE_REASON_CODES = ("SOURCE_INTEGRITY", "MISMATCHED_TOTALS",
                           "UNRESOLVED_NULLS", "LEGAL_HOLD")
MAX_FIELD_DEFINITIONS = 40

DATASET_NAME_PATTERN = r"^[a-z0-9\-]{1,80}$"
FIELD_NAME_PATTERN = r"^[a-z0-9_]{1,80}$"

DELIVERABLE_REQUEST_STATUSES = ("RELEASED", "PARTIALLY_RELEASED")


def _invalid_dataset_state(dataset):
    return ApiError("ERR_INVALID_DATASET_STATE",
                    "The operation is not declared from dataset status %s." % dataset["status"])


@bp.post("/datasets")
def create_dataset():
    authenticate([ROLE_DATA_REPORTER])
    payload = v.body()
    request_id = v.field_string(payload, "request_id", min_len=1, non_blank=True)
    investigation_id = v.field_string(payload, "investigation_id", min_len=1, non_blank=True,
                                      optional=True, default=None, nullable=True)
    name = v.field_string(payload, "name", min_len=1, max_len=80, non_blank=True,
                          pattern=DATASET_NAME_PATTERN,
                          pattern_desc="must use only lowercase letters, digits and hyphens")
    negotiated_format = v.field_enum(payload, "negotiated_format", FORMATS)
    expected_field_count = v.field_int(payload, "expected_field_count", minimum=1, maximum=500)
    sensitivity_tier = v.field_enum(payload, "sensitivity_tier", SENSITIVITY_TIERS)
    # Rung 6 -- references in declared order
    request_row = db.get_request(request_id)
    investigation = None
    if investigation_id is not None:
        investigation = db.get_investigation(investigation_id)
    # Rung 31 -- a named investigation must belong to the same desk as the request
    if investigation is not None and investigation["desk_id"] != request_row["desk_id"]:
        raise ApiError("ERR_DATASET_NOT_LINKED",
                       "The named investigation belongs to a different desk than the request.")
    # Rung 36 -- the slug is globally unique across the whole API
    for existing in db.all_of("datasets"):
        if existing["name"] == name:
            raise ApiError("ERR_DATASET_NAME_CONFLICT",
                           "Dataset name '%s' is already in use." % name)
    dataset = db.insert("datasets", {
        "request_id": request_id,
        "investigation_id": investigation_id,
        "name": name,
        "negotiated_format": negotiated_format,
        "delivered_format": None,
        "format_negotiation_status": "REQUESTED",
        "record_count": 0,
        "expected_field_count": expected_field_count,
        "field_definition_count": 0,
        "documentation_status": "INCOMPLETE",
        "known_issue_count": 0,
        "sensitivity_tier": sensitivity_tier,
        "status": "RAW",
        "allocated_cost_cents": 0,
        "quarantine_reason_code": None,
        "retention_expires_at": None,
    })
    return response.created_response(db.serialize(dataset))


@bp.get("/datasets/<dataset_id>")
def get_dataset(dataset_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_dataset(dataset_id)))


@bp.get("/datasets")
def list_datasets():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("datasets"), ["request_id", "investigation_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/datasets/<dataset_id>/delivery")
def record_delivery(dataset_id):
    authenticate([ROLE_DATA_REPORTER])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    delivered_format = v.field_enum(payload, "delivered_format", FORMATS)
    record_count = v.field_int(payload, "record_count", minimum=0)
    if dataset["status"] != "RAW":
        raise _invalid_dataset_state(dataset)
    request_row = db.find("records_requests", dataset["request_id"])
    if request_row is None or request_row["status"] not in DELIVERABLE_REQUEST_STATUSES:
        raise ApiError("ERR_SOURCE_REQUEST_UNRESOLVED",
                       "The parent records request has not produced records yet.")
    desk = db.find("desks", request_row["desk_id"])
    dataset["delivered_format"] = delivered_format
    dataset["record_count"] = record_count
    dataset["status"] = "CLEANING"
    dataset["format_negotiation_status"] = (
        "AGREED" if delivered_format == dataset["negotiated_format"] else "REFUSED"
    )
    dataset["retention_expires_at"] = daycalc.retention_expires_at(
        clock.now(), desk["retention_policy_days"]
    )
    db.touch(dataset)
    return response.object_response(db.serialize(dataset))


@bp.post("/datasets/<dataset_id>/field-definitions")
def create_field_definition(dataset_id):
    authenticate([ROLE_DATA_REPORTER])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    field_name = v.field_string(payload, "field_name", min_len=1, max_len=80, non_blank=True,
                                pattern=FIELD_NAME_PATTERN,
                                pattern_desc="must use only lowercase letters, digits and underscores")
    data_type = v.field_enum(payload, "data_type", DATA_TYPES)
    null_rate_pct = v.field_number(payload, "null_rate_pct", minimum=0.0, maximum=100.0)
    reidentification_risk = v.field_int(payload, "reidentification_risk", minimum=0, maximum=10)
    is_source_identifying = v.field_bool(payload, "is_source_identifying")
    known_issue_codes = v.field_enum_list(payload, "known_issue_codes", KNOWN_ISSUE_CODES,
                                          optional=True, default=[])
    # Rung 10 -- documentation is only accepted while RAW or CLEANING
    if dataset["status"] not in ("RAW", "CLEANING"):
        raise _invalid_dataset_state(dataset)
    existing = db.fields_of_dataset(dataset_id)
    # Rung 36 -- unique within its dataset
    for row in existing:
        if row["field_name"] == field_name:
            raise ApiError("ERR_FIELD_NAME_CONFLICT",
                           "Field name '%s' is already documented on this dataset." % field_name)
    # Rung 37 -- at most 40 documented columns
    if len(existing) >= MAX_FIELD_DEFINITIONS:
        raise ApiError("ERR_FIELD_LIMIT_EXCEEDED",
                       "A dataset may carry at most %d field definitions." % MAX_FIELD_DEFINITIONS)
    field = db.insert("field_definitions", {
        "dataset_id": dataset_id,
        "field_name": field_name,
        "data_type": data_type,
        "null_rate_pct": null_rate_pct,
        "known_issue_codes": known_issue_codes,
        "reidentification_risk": reidentification_risk,
        "is_source_identifying": is_source_identifying,
        "suppression_applied": False,
        "suppression_method": None,
    })
    dataset["field_definition_count"] = dataset["field_definition_count"] + 1
    dataset["known_issue_count"] = dataset["known_issue_count"] + len(known_issue_codes)
    dataset["documentation_status"] = (
        "COMPLETE" if dataset["field_definition_count"] >= dataset["expected_field_count"]
        else "INCOMPLETE"
    )
    db.touch(dataset)
    return response.created_response(db.serialize(field))


@bp.get("/datasets/<dataset_id>/field-definitions")
def list_field_definitions(dataset_id):
    authenticate(ALL_ROLES)
    db.get_dataset(dataset_id)
    limit, offset = v.pagination()
    rows = db.fields_of_dataset(dataset_id)
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/datasets/<dataset_id>/field-suppressions")
def apply_suppression(dataset_id):
    authenticate([ROLE_DATA_REPORTER, ROLE_MANAGING_EDITOR])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    field_definition_id = v.field_string(payload, "field_definition_id", min_len=1, non_blank=True)
    suppression_method = v.field_enum(payload, "suppression_method", SUPPRESSION_METHODS)
    # Rung 6 -- ERR_FIELD_NOT_FOUND also when the match belongs to another dataset
    field = db.find("field_definitions", field_definition_id)
    if field is None or field["dataset_id"] != dataset_id:
        raise ApiError("ERR_FIELD_NOT_FOUND",
                       "No field definition on this dataset matches the supplied id.")
    # Rung 10 -- the dataset must not be QUARANTINED
    if dataset["status"] == "QUARANTINED":
        raise _invalid_dataset_state(dataset)
    field["suppression_applied"] = True
    field["suppression_method"] = suppression_method
    db.touch(field)
    return response.object_response(db.serialize(field))


@bp.post("/datasets/<dataset_id>/cleaning-lock")
def cleaning_lock(dataset_id):
    authenticate([ROLE_DATA_REPORTER])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    v.field_text(payload, "cleaning_notes")
    if dataset["status"] != "CLEANING":
        raise _invalid_dataset_state(dataset)
    # Rung 34 then rung 35
    if dataset["documentation_status"] != "COMPLETE":
        raise ApiError("ERR_DATASET_DOCUMENTATION_INCOMPLETE",
                       "The dataset's documentation_status must be COMPLETE before the cleaning lock.")
    if dataset["format_negotiation_status"] != "AGREED":
        raise ApiError("ERR_FORMAT_NOT_NEGOTIATED",
                       "The dataset's format_negotiation_status must be AGREED before the cleaning lock.")
    dataset["status"] = "CLEAN_LOCKED"
    db.touch(dataset)
    return response.object_response(db.serialize(dataset))


@bp.post("/datasets/<dataset_id>/quarantine")
def quarantine(dataset_id):
    authenticate([ROLE_MANAGING_EDITOR])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    reason = v.field_enum(payload, "quarantine_reason_code", QUARANTINE_REASON_CODES)
    if dataset["status"] != "CLEAN_LOCKED":
        raise _invalid_dataset_state(dataset)
    cascades.quarantine_dataset(dataset, reason)
    return response.object_response(db.serialize(dataset))


@bp.post("/datasets/<dataset_id>/requalification")
def requalification(dataset_id):
    authenticate([ROLE_DATA_REPORTER])
    dataset = db.get_dataset(dataset_id)
    payload = v.body()
    v.field_text(payload, "remediation_notes")
    if dataset["status"] != "QUARANTINED":
        raise _invalid_dataset_state(dataset)
    dataset["status"] = "CLEANING"
    dataset["quarantine_reason_code"] = None
    db.touch(dataset)
    return response.object_response(db.serialize(dataset))
