"""Brand filings: filing, examination, correction, recording and rejection."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, now, touch
from errors import ApiError
from middleware import caller_id, endpoint, require_owner
from response import object_response, paginate
from routes import lookup
from services import cascades, constants as C
from services.calculations import (
    conflict_group_key,
    effective_priority_at,
    filing_outranked_by,
    renewal_days_past_expiry,
    renewal_filing_fee,
    renewal_penalty_rate,
)
from util import days
from validation import (
    APPLICATION_TYPES,
    POSITION_CODES,
    SPECIES_CLASSES,
    body,
    opt_bool,
    opt_enum,
    opt_id,
    opt_int,
    opt_str,
    req_enum,
    req_id,
    req_int,
    req_state_code,
    req_str,
)

bp = Blueprint("brand_applications", __name__)


def _new_application_row(**fields):
    row = base_row()
    row.update(
        {
            "owner_id": None,
            "application_type": None,
            "prior_registration_id": None,
            "brand_symbol": None,
            "position_code": None,
            "species_class": None,
            "state_code": None,
            "documented_prior_use_years": 0,
            "prior_use_affidavit_on_file": False,
            "original_filed_at": now(),
            "effective_priority_at": now(),
            "correction_rounds": 0,
            "status": "SUBMITTED",
            "examined_by_user_id": None,
            "recorded_by_user_id": None,
            "assessed_filing_fee_cents": 0,
            "rejection_reason": None,
        }
    )
    row.update(fields)
    return row


@bp.post("/brand-applications")
@endpoint("LivestockOwner")
def file_application():
    payload = body()
    owner_id = req_id(payload, "owner_id")
    application_type = req_enum(payload, "application_type", APPLICATION_TYPES)
    brand_symbol = req_str(payload, "brand_symbol")
    position_code = req_enum(payload, "position_code", POSITION_CODES)
    species_class = req_enum(payload, "species_class", SPECIES_CLASSES)
    state_code = req_state_code(payload, "state_code")
    prior_registration_id = opt_id(payload, "prior_registration_id")
    documented_prior_use_years = opt_int(payload, "documented_prior_use_years", default=0, minimum=0)
    prior_use_affidavit_on_file = opt_bool(payload, "prior_use_affidavit_on_file", default=False)

    lookup.owner(owner_id)
    prior_registration = None
    if prior_registration_id is not None:
        prior_registration = lookup.registration(prior_registration_id)

    require_owner(owner_id)

    filed_at = now()
    if application_type == "RENEWAL" and prior_registration is not None:
        penalty_rate = renewal_penalty_rate(renewal_days_past_expiry(prior_registration))
        if penalty_rate is None:
            raise ApiError("ERR_REGISTRATION_UNRENEWABLE", "The record is beyond the recovery window.")
        filing_fee = renewal_filing_fee(penalty_rate)
    elif application_type == "RENEWAL":
        filing_fee = C.BASE_RENEWAL_FEE_CENTS
    else:
        filing_fee = C.NEW_FILING_FEE_CENTS

    row = _new_application_row(
        owner_id=owner_id,
        application_type=application_type,
        prior_registration_id=prior_registration_id,
        brand_symbol=brand_symbol,
        position_code=position_code,
        species_class=species_class,
        state_code=state_code,
        documented_prior_use_years=documented_prior_use_years,
        prior_use_affidavit_on_file=prior_use_affidavit_on_file,
        original_filed_at=filed_at,
        effective_priority_at=effective_priority_at(
            filed_at, documented_prior_use_years, prior_use_affidavit_on_file
        ),
        assessed_filing_fee_cents=filing_fee,
    )
    insert(db.applications, row)
    return object_response(row, 201)


@bp.post("/brand-registrations/<registration_id>/renewal-applications")
@endpoint("LivestockOwner")
def file_renewal_application(registration_id):
    payload = body()
    owner_id = req_id(payload, "owner_id")
    expected_registration_version = req_int(payload, "expected_registration_version")
    brand_symbol = opt_str(payload, "brand_symbol")
    if brand_symbol is not None and not brand_symbol.strip():
        raise ApiError("ERR_INVALID_REQUEST", "brand_symbol must not be empty.")
    position_code = opt_enum(payload, "position_code", POSITION_CODES)
    species_class = opt_enum(payload, "species_class", SPECIES_CLASSES)
    documented_prior_use_years = opt_int(payload, "documented_prior_use_years", default=0, minimum=0)
    prior_use_affidavit_on_file = opt_bool(payload, "prior_use_affidavit_on_file", default=False)

    registration = lookup.registration(registration_id)
    lookup.owner(owner_id)
    require_owner(owner_id)

    if registration["status"] not in ("ACTIVE", "GRACE", "ENCUMBERED"):
        raise ApiError("ERR_REGISTRATION_INVALID_STATE", "The record may no longer be renewed.")

    if expected_registration_version != registration["version"]:
        raise ApiError("ERR_STALE_REGISTRATION_VERSION", "The registration version has advanced.")

    penalty_rate = renewal_penalty_rate(renewal_days_past_expiry(registration))
    if penalty_rate is None:
        raise ApiError("ERR_REGISTRATION_UNRENEWABLE", "The record is more than 90 days past expiry.")

    filed_at = now()
    row = _new_application_row(
        owner_id=owner_id,
        application_type="RENEWAL",
        prior_registration_id=registration["id"],
        brand_symbol=brand_symbol if brand_symbol is not None else registration["brand_symbol"],
        position_code=position_code or registration["position_code"],
        species_class=species_class or registration["species_class"],
        state_code=registration["state_code"],
        documented_prior_use_years=documented_prior_use_years,
        prior_use_affidavit_on_file=prior_use_affidavit_on_file,
        original_filed_at=filed_at,
        effective_priority_at=effective_priority_at(
            filed_at, documented_prior_use_years, prior_use_affidavit_on_file
        ),
        assessed_filing_fee_cents=renewal_filing_fee(penalty_rate),
    )
    insert(db.applications, row)

    # Only the most recent renewal on a record survives.
    cascades.reject_pending_filings(
        registration, "SUPERSEDED_BY_LATER_RENEWAL", renewal_only=False, exclude_id=row["id"]
    )
    touch(registration)
    return object_response(row, 201)


@bp.get("/brand-applications/<application_id>")
@endpoint("LivestockOwner", "BrandRecorder", "BoardAdmin")
def read_application(application_id):
    return object_response(lookup.application(application_id))


@bp.get("/brand-applications")
@endpoint("LivestockOwner", "BrandRecorder", "BoardAdmin")
def list_applications():
    rows = lookup.filtered(
        db.applications,
        {
            "owner_id": request.args.get("owner_id"),
            "prior_registration_id": request.args.get("prior_registration_id"),
            "status": request.args.get("status"),
            "application_type": request.args.get("application_type"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/brand-applications/<application_id>/begin-examination")
@endpoint("BrandRecorder")
def begin_examination(application_id):
    application = lookup.application(application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", "The filing is not awaiting examination.")
    application["status"] = "UNDER_EXAMINATION"
    application["examined_by_user_id"] = caller_id()
    touch(application)
    return object_response(application)


@bp.post("/brand-applications/<application_id>/return")
@endpoint("BrandRecorder")
def return_for_correction(application_id):
    application = lookup.application(application_id)
    if application["status"] != "UNDER_EXAMINATION":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", "The filing is not under examination.")

    if application["correction_rounds"] < C.MAX_CORRECTION_ROUNDS:
        application["correction_rounds"] += 1
        application["status"] = "RETURNED_FOR_CORRECTION"
    else:
        application["correction_rounds"] += 1
        application["status"] = "REJECTED"
        application["rejection_reason"] = "MAX_CORRECTION_ROUNDS_EXHAUSTED"
    touch(application)
    return object_response(application)


@bp.post("/brand-applications/<application_id>/resubmit")
@endpoint("LivestockOwner")
def resubmit_application(application_id):
    payload = body()
    brand_symbol = opt_str(payload, "brand_symbol")
    if brand_symbol is not None and not brand_symbol.strip():
        raise ApiError("ERR_INVALID_REQUEST", "brand_symbol must not be empty.")
    position_code = opt_enum(payload, "position_code", POSITION_CODES)
    species_class = opt_enum(payload, "species_class", SPECIES_CLASSES)
    documented_prior_use_years = opt_int(payload, "documented_prior_use_years", minimum=0)
    prior_use_affidavit_on_file = opt_bool(payload, "prior_use_affidavit_on_file")

    application = lookup.application(application_id)
    require_owner(application["owner_id"])

    if application["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", "The filing is not awaiting correction.")

    if brand_symbol is not None:
        application["brand_symbol"] = brand_symbol
    if position_code is not None:
        application["position_code"] = position_code
    if species_class is not None:
        application["species_class"] = species_class
    if documented_prior_use_years is not None:
        application["documented_prior_use_years"] = documented_prior_use_years
    if prior_use_affidavit_on_file is not None:
        application["prior_use_affidavit_on_file"] = prior_use_affidavit_on_file

    # original_filed_at is never touched, so the queue position is not surrendered.
    application["effective_priority_at"] = effective_priority_at(
        application["original_filed_at"],
        application["documented_prior_use_years"],
        application["prior_use_affidavit_on_file"],
    )
    application["status"] = "SUBMITTED"
    touch(application)
    return object_response(application)


@bp.post("/brand-applications/<application_id>/record")
@endpoint("BrandRecorder")
def record_application(application_id):
    application = lookup.application(application_id)

    if caller_id() == application["examined_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The recording operator examined this filing.")

    if application["status"] != "UNDER_EXAMINATION":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", "The filing is not under examination.")

    if filing_outranked_by(application) is not None:
        raise ApiError("ERR_BRAND_CONFLICT_EXISTS", "An earlier claimant outranks this filing.")

    prior_registration = None
    if application["application_type"] == "RENEWAL":
        prior_registration = db.registrations.get(application["prior_registration_id"])
        if prior_registration is None or prior_registration["status"] not in C.REGISTRATION_GROUP_STATUSES:
            raise ApiError(
                "ERR_PRIOR_REGISTRATION_NOT_RENEWABLE", "The prior record is no longer renewable."
            )

    recorded_at = now()
    registration = base_row()
    registration.update(
        {
            "owner_id": application["owner_id"],
            "source_application_id": application["id"],
            "brand_symbol": application["brand_symbol"],
            "position_code": application["position_code"],
            "species_class": application["species_class"],
            "state_code": application["state_code"],
            "recorded_at": recorded_at,
            "expires_on": recorded_at + days(C.REGISTRATION_TERM_DAYS),
            "effective_priority_at": application["effective_priority_at"],
            "priority_rank": 1,
            "status": "ACTIVE",
            "superseded_by_registration_id": None,
            "encumbrance_count": 0,
        }
    )
    insert(db.registrations, registration)

    application["status"] = "RECORDED"
    application["recorded_by_user_id"] = caller_id()
    touch(application)

    if prior_registration is not None:
        prior_registration["status"] = "SUPERSEDED"
        prior_registration["superseded_by_registration_id"] = registration["id"]
        touch(prior_registration)

    cascades.rerank_conflict_group(registration, created_id=registration["id"])
    return object_response(registration, 201)


@bp.post("/brand-applications/<application_id>/reject")
@endpoint("BrandRecorder")
def reject_application(application_id):
    payload = body()
    rejection_reason = req_str(payload, "rejection_reason")
    application = lookup.application(application_id)
    if application["status"] not in ("UNDER_EXAMINATION", "CONFLICT_HOLD"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", "The filing may not be rejected from this state.")
    application["status"] = "REJECTED"
    application["rejection_reason"] = rejection_reason
    touch(application)
    return object_response(application)
