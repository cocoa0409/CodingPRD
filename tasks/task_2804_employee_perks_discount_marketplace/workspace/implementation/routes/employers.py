"""Employer clients, branded storefronts and eligibility batches (PRD 3.3, 3.4)."""
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

bp = Blueprint("employers", __name__)

REQUIRED_RECORD_KEYS = ("external_employee_ref", "employment_status", "region_code",
                        "eligibility_valid_from", "eligibility_valid_until")


def _employer_for(principal, row_id):
    """EmployerAdmin scope is decided on the path id alone, before existence."""
    if principal.is_employer_admin and row_id != principal.user_id:
        auth.deny_scope()
    return support.fetch("employers", row_id)


@bp.post("/perks/employers")
def create_employer():
    auth.require(auth.PLATFORM_ADMIN)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "name", "type": "str", "required": True, "min_len": 1, "max_len": 200},
        {"name": "region_code", "type": "enum", "required": True,
         "values": validate.REGIONS},
        {"name": "employee_count_declared", "type": "int", "required": True,
         "min": 1, "max": 1000000},
        {"name": "revenue_share_enabled", "type": "bool", "default": False},
        {"name": "privacy_min_cohort_size", "type": "int", "min": 2, "max": 25,
         "default": calc.DEFAULT_PRIVACY_MIN_COHORT_SIZE},
    ])
    row = db.insert(db.employers, {
        "name": data["name"],
        "region_code": data["region_code"],
        "employee_count_declared": data["employee_count_declared"],
        "revenue_share_enabled": bool(data["revenue_share_enabled"]),
        "privacy_min_cohort_size": data["privacy_min_cohort_size"],
        "integration_status": "NOT_CONFIGURED",
        "storefront_status": "DRAFT",
        "brand_color_hex": None,
        "logo_url": None,
        "hero_headline": None,
        "featured_categories": None,
        "last_sync_at": None,
        "suspension_reason": None,
    })
    return response.created(derive.employer_json(row))


@bp.get("/perks/employers/<row_id>")
def get_employer(row_id):
    principal = auth.require(auth.PLATFORM_ADMIN, auth.EMPLOYER_ADMIN,
                             auth.PARTNER_MANAGER)
    row = _employer_for(principal, row_id)
    return response.ok(derive.employer_json(row))


@bp.get("/perks/employers")
def list_employers():
    auth.require(auth.PLATFORM_ADMIN, auth.PARTNER_MANAGER)
    region = support.arg("region_code")
    posture = support.arg("program_posture")
    integration = support.arg("integration_status")
    storefront = support.arg("storefront_status")
    rows = []
    for row in db.employers.values():
        if not support.matches(row, "region_code", region):
            continue
        if posture is not None and derive.program_posture(row) != posture:
            continue
        if not support.matches(row, "integration_status", integration):
            continue
        if not support.matches(row, "storefront_status", storefront):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.employer_json)


@bp.patch("/perks/employers/<row_id>")
def update_employer(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    row = _employer_for(principal, row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "revenue_share_enabled", "type": "bool"},
        {"name": "privacy_min_cohort_size", "type": "int", "min": 2, "max": 25},
        {"name": "employee_count_declared", "type": "int", "min": 1, "max": 1000000},
    ])
    for field in ("revenue_share_enabled", "privacy_min_cohort_size",
                  "employee_count_declared"):
        if data[field] is not None:
            row[field] = data[field]
    db.touch(row)
    return response.ok(derive.employer_json(row))


@bp.post("/perks/employers/<row_id>/storefront")
def brand_storefront(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN)
    row = _employer_for(principal, row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "brand_color_hex", "type": "str", "required": True},
        {"name": "logo_url", "type": "str", "required": True},
        {"name": "hero_headline", "type": "str", "required": True},
        {"name": "featured_categories", "type": "enum_list", "required": True,
         "values": validate.CATEGORIES, "min_len": 0, "max_len": 7},
    ])
    if row["storefront_status"] not in ("DRAFT", "BRANDED"):
        raise ApiError("ERR_EMPLOYER_INVALID_STATE",
                       "Branding is only accepted while the storefront is DRAFT "
                       "or BRANDED.")
    row["brand_color_hex"] = data["brand_color_hex"]
    row["logo_url"] = data["logo_url"]
    row["hero_headline"] = data["hero_headline"]
    row["featured_categories"] = data["featured_categories"]
    row["storefront_status"] = "BRANDED"
    db.touch(row)
    return response.ok(derive.employer_json(row))


@bp.post("/perks/employers/<row_id>/storefront/publish")
def publish_storefront(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN)
    row = _employer_for(principal, row_id)
    if row["storefront_status"] not in ("BRANDED", "SUSPENDED"):
        raise ApiError("ERR_EMPLOYER_INVALID_STATE",
                       "Publishing is only accepted from BRANDED or SUSPENDED.")
    row["storefront_status"] = "PUBLISHED"
    row["suspension_reason"] = None
    db.touch(row)
    return response.ok(derive.employer_json(row))


@bp.post("/perks/employers/<row_id>/storefront/suspend")
def suspend_storefront(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("employers", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "suspension_reason", "type": "str", "required": True},
    ])
    if row["storefront_status"] != "PUBLISHED":
        raise ApiError("ERR_EMPLOYER_INVALID_STATE",
                       "Only a PUBLISHED storefront can be suspended.")
    row["storefront_status"] = "SUSPENDED"
    row["suspension_reason"] = data["suspension_reason"]
    db.touch(row)
    # The posture is now FROZEN, so every PENDING redemption of this employer
    # is voided and its offer's reserved inventory released.
    cascade.void_pending_for_employer(row, "PROGRAM_FROZEN")
    return response.ok(derive.employer_json(row))


def record_is_valid(record):
    """The four invalidity tests of PRD 3.3, applied element by element."""
    for key in REQUIRED_RECORD_KEYS:
        if key not in record or record[key] is None:
            return False
    if record["employment_status"] not in validate.EMPLOYMENT_STATUSES:
        return False
    if record["region_code"] not in validate.REGIONS:
        return False
    valid_from = clock.parse_iso(record["eligibility_valid_from"])
    valid_until = clock.parse_iso(record["eligibility_valid_until"])
    if valid_from is None or valid_until is None:
        return False
    if valid_until <= valid_from:
        return False
    return True


@bp.post("/perks/employers/<row_id>/eligibility-files")
def load_eligibility_file(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN)
    employer = _employer_for(principal, row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "expected_employer_version", "type": "int", "required": True},
        {"name": "effective_from", "type": "datetime", "required": True},
        {"name": "checksum", "type": "str", "required": True,
         "min_len": 1, "max_len": 128},
        {"name": "records", "type": "obj_list", "required": True,
         "min_len": 1, "max_len": 5000},
    ])
    seen = set()
    for record in data["records"]:
        ref = record.get("external_employee_ref")
        if not isinstance(ref, str):
            continue
        if ref in seen:
            raise ApiError("ERR_DUPLICATE_EMPLOYEE_REF",
                           "Two records share the employee reference '%s'." % ref)
        seen.add(ref)
    support.occ(employer, body, "expected_employer_version")

    records = data["records"]
    invalid = sum(1 for record in records if not record_is_valid(record))
    row = db.insert(db.eligibility_files, {
        "employer_id": employer["id"],
        "effective_from": data["effective_from"],
        "checksum": data["checksum"],
        "records": records,
        "record_count": len(records),
        "invalid_record_count": invalid,
        "valid_record_count": len(records) - invalid,
        "status": "RECEIVED",
        "rejection_reason": None,
        "created_membership_count": 0,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
        "applied_at": None,
    })
    # A new batch always pulls the integration dimension back to FILE_RECEIVED.
    employer["integration_status"] = "FILE_RECEIVED"
    db.touch(employer)
    return response.created(derive.file_json(row))


@bp.get("/perks/employers/<row_id>/eligibility-files")
def list_eligibility_files(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    employer = _employer_for(principal, row_id)
    status = support.arg("status")
    rows = [f for f in db.eligibility_files.values()
            if f["employer_id"] == employer["id"]
            and support.matches(f, "status", status)]
    return support.paged_sorted(rows, derive.file_json)
