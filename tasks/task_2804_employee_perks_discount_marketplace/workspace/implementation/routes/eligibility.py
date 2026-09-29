"""Eligibility batch validation and application (PRD 3.3)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError
from routes.employers import record_is_valid

bp = Blueprint("eligibility", __name__)


def _file_for(principal, row_id):
    row = support.fetch("eligibility_files", row_id)
    auth.check_employer_scope(principal, row["employer_id"])
    return row


@bp.get("/perks/eligibility-files/<row_id>")
def get_file(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    row = _file_for(principal, row_id)
    return response.ok(derive.file_json(row))


@bp.post("/perks/eligibility-files/<row_id>/validate")
def validate_file(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    row = _file_for(principal, row_id)
    if row["status"] != "RECEIVED":
        raise ApiError("ERR_FILE_INVALID_STATE",
                       "Validation is only accepted from RECEIVED.")
    employer = db.employers.get(row["employer_id"])
    if calc.batch_rejects(row["invalid_record_count"], row["record_count"]):
        # The employer's integration_status is deliberately left where it is.
        row["status"] = "REJECTED"
        row["rejection_reason"] = "INVALID_RECORD_RATIO_EXCEEDED"
        db.touch(row)
    else:
        row["status"] = "VALIDATED"
        db.touch(row)
        if employer is not None:
            employer["integration_status"] = "VALIDATED"
            db.touch(employer)
    return response.ok(derive.file_json(row))


@bp.post("/perks/eligibility-files/<row_id>/apply")
def apply_file(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN)
    row = _file_for(principal, row_id)
    if row["status"] != "VALIDATED":
        raise ApiError("ERR_FILE_INVALID_STATE",
                       "Application is only accepted from VALIDATED.")
    employer = db.employers.get(row["employer_id"])
    now = clock.now()

    existing = {}
    for membership in db.sorted_rows(db.memberships.values()):
        if membership["employer_id"] == row["employer_id"]:
            existing[membership["external_employee_ref"]] = membership

    batch_refs = set()
    for record in row["records"]:
        ref = record.get("external_employee_ref")
        if isinstance(ref, str):
            batch_refs.add(ref)

    created = 0
    updated = 0
    # Valid records are walked in records-array order, so the first element of a
    # membership listing is the first record of the first batch ever applied.
    for record in row["records"]:
        if not record_is_valid(record):
            continue
        ref = record["external_employee_ref"]
        valid_from = clock.parse_iso(record["eligibility_valid_from"])
        valid_until = clock.parse_iso(record["eligibility_valid_until"])
        membership = existing.get(ref)
        if membership is None:
            membership = db.insert(db.memberships, {
                "employer_id": row["employer_id"],
                "source_file_id": row["id"],
                "external_employee_ref": ref,
                "employment_status": record["employment_status"],
                "status": "ELIGIBLE",
                "region_code": record["region_code"],
                "eligibility_valid_from": valid_from,
                "eligibility_valid_until": valid_until,
                "last_employment_change_at": None,
            })
            existing[ref] = membership
            created += 1
        else:
            membership["employment_status"] = record["employment_status"]
            membership["region_code"] = record["region_code"]
            membership["eligibility_valid_from"] = valid_from
            membership["eligibility_valid_until"] = valid_until
            membership["source_file_id"] = row["id"]
            if (membership["status"] == "SUSPENDED"
                    and record["employment_status"] in ("ACTIVE", "LEAVE")):
                membership["status"] = "ELIGIBLE"
            db.touch(membership)
            updated += 1

    suspended = 0
    for membership in db.sorted_rows(db.memberships.values()):
        if membership["employer_id"] != row["employer_id"]:
            continue
        if membership["external_employee_ref"] in batch_refs:
            continue
        if cascade.suspend_membership(membership):
            suspended += 1

    row["status"] = "APPLIED"
    row["applied_at"] = now
    row["created_membership_count"] = created
    row["updated_membership_count"] = updated
    row["suspended_membership_count"] = suspended
    db.touch(row)
    if employer is not None:
        employer["last_sync_at"] = now
        employer["integration_status"] = "SYNCED"
        db.touch(employer)
    return response.ok(derive.file_json(row))
