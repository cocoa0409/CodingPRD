"""Signature batches, their lines, affidavit verification and compensation."""

from flask import Blueprint

import response
import validation as v
from db import (db, fmt_instant, get_batch, get_circulator, get_county,
                get_cure_period, get_petition, get_signature_record,
                new_resource, now, records_of_batch, serialize, touch)
from errors import ApiError
from middleware import (require_auth, require_batch_owner,
                        require_petition_owner)
from services import calculations as calc
from services import cascades
from services import verification

READ_ROLES = ("SosAdmin", "ElectionsExaminer", "Proponent", "CountyClerk",
              "CirculatorAgent")
RECORD_READ_ROLES = ("SosAdmin", "ElectionsExaminer", "CountyClerk", "Proponent",
                     "Challenger")

bp = Blueprint("batches", __name__)


# ---------------------------------------------------------------------------
# filing
# ---------------------------------------------------------------------------
@bp.route("/signature-batches", methods=["POST"])
def file_batch():
    user_id, role = require_auth(["CirculatorAgent", "Proponent"])
    body = v.body()
    petition_id = v.as_id(v.required(body, "petition_id"), "petition_id")
    circulator_id = v.as_id(v.required(body, "circulator_id"), "circulator_id")
    county_id = v.as_id(v.required(body, "county_id"), "county_id")
    affidavit_signed = v.as_bool(v.required(body, "affidavit_signed"), "affidavit_signed")
    is_supplemental = v.as_bool(v.optional(body, "is_supplemental", False),
                                "is_supplemental")
    cure_period_id = v.optional(body, "cure_period_id")
    if cure_period_id is not None:
        cure_period_id = v.as_id(cure_period_id, "cure_period_id")

    petition = get_petition(petition_id)
    circulator = get_circulator(circulator_id)
    county = get_county(county_id)
    cure_period = None
    if cure_period_id is not None:
        cure_period = get_cure_period(cure_period_id)
        if cure_period["petition_id"] != petition["id"]:
            raise ApiError("ERR_CURE_PERIOD_NOT_FOUND")

    if role == "CirculatorAgent" and circulator["id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    require_petition_owner(petition, user_id, role)

    if circulator["registration_status"] == "REVOKED":
        raise ApiError("ERR_CIRCULATOR_REVOKED")
    if circulator["registration_status"] != "REGISTERED":
        raise ApiError("ERR_CIRCULATOR_NOT_REGISTERED")

    assignment = None
    for candidate in db.assignments.values():
        if candidate["petition_id"] == petition["id"] \
                and candidate["circulator_id"] == circulator["id"] \
                and candidate["status"] == "ACTIVE":
            assignment = candidate
            break
    if assignment is None:
        raise ApiError("ERR_NO_ACTIVE_ASSIGNMENT")
    if county["county_code"] not in assignment["assigned_county_codes"]:
        raise ApiError("ERR_COUNTY_NOT_IN_ASSIGNMENT")
    if is_supplemental and cure_period is None:
        raise ApiError("ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD")
    if cure_period is not None and not is_supplemental:
        raise ApiError("ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD")
    if cure_period is not None and cure_period["status"] != "OPEN":
        raise ApiError("ERR_CURE_PERIOD_NOT_OPEN")

    filed_at = now()
    batch = new_resource({
        "petition_id": petition["id"],
        "circulator_id": circulator["id"],
        "county_id": county["id"],
        "cure_period_id": cure_period["id"] if cure_period is not None else None,
        "is_supplemental": is_supplemental,
        "affidavit_signed": affidavit_signed,
        "affidavit_notary_id": None,
        "filed_at": fmt_instant(filed_at),
        "raw_count": 0,
        "accepted_raw_count": 0,
        "format_defect_count": 0,
        "checked_signature_count": 0,
        "verification_cost_cents": 0,
        "status": "RECEIVED",
        "status_before_invalidation": None,
        "invalidation_reason": None,
        "_filed_at_dt": filed_at,
        "_accepted_before_invalidation": None,
    })
    db.batches[batch["id"]] = batch
    return response.single(serialize(batch), 201)


@bp.route("/signature-batches/<batch_id>", methods=["GET"])
def read_batch(batch_id):
    require_auth(READ_ROLES)
    return response.single(serialize(get_batch(batch_id)))


@bp.route("/signature-batches", methods=["GET"])
def list_batches():
    require_auth(READ_ROLES)
    return response.listing(list(db.batches.values()), {
        "petition_id": ("str", "petition_id"),
        "circulator_id": ("str", "circulator_id"),
        "county_id": ("str", "county_id"),
        "cure_period_id": ("str", "cure_period_id"),
        "status": ("str", "status"),
        "is_supplemental": ("bool", "is_supplemental"),
    })


# ---------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------
@bp.route("/signature-batches/<batch_id>/signatures", methods=["POST"])
def add_signature(batch_id):
    user_id, role = require_auth(["CirculatorAgent", "Proponent"])
    body = v.body()
    line_number = v.as_int(v.required(body, "line_number"), "line_number", minimum=1)
    signer_name = v.as_string(v.required(body, "signer_name"), "signer_name")
    claimed_voter_id_number = v.as_string(v.required(body, "claimed_voter_id_number"),
                                          "claimed_voter_id_number")
    signed_on, signed_on_dt = v.as_instant(v.required(body, "signed_on"), "signed_on")
    signature_hash = v.as_string(v.required(body, "signature_hash"), "signature_hash")

    batch = get_batch(batch_id)
    require_batch_owner(batch, user_id, role)
    if batch["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    for existing in records_of_batch(batch["id"]):
        if existing["line_number"] == line_number:
            raise ApiError("ERR_DUPLICATE_LINE_NUMBER")

    petition = db.petitions[batch["petition_id"]]
    cleared_at = petition["_cleared_at_dt"]
    deadline = petition["_circulation_deadline_dt"]
    if cleared_at is None or deadline is None \
            or signed_on_dt < cleared_at or signed_on_dt > deadline:
        raise ApiError("ERR_SIGNED_OUTSIDE_WINDOW")
    if batch["is_supplemental"] and batch["cure_period_id"]:
        cure_period = db.cure_periods.get(batch["cure_period_id"])
        if cure_period is not None:
            if signed_on_dt < cure_period["_opened_at_dt"] \
                    or signed_on_dt >= cure_period["_deadline_at_dt"]:
                raise ApiError("ERR_SIGNED_OUTSIDE_WINDOW")

    record = new_resource({
        "batch_id": batch["id"],
        "line_number": line_number,
        "signer_name": signer_name,
        "claimed_voter_id_number": claimed_voter_id_number,
        "signed_on": signed_on,
        "signature_hash": signature_hash,
        "matched_voter_record_id": None,
        "duplicate_of_signature_id": None,
        "validated_in_round_id": None,
        "in_sample": False,
        "validation_status": "PENDING",
        "status_before_void": None,
        "void_reason": None,
        "manual_match_override_applied": False,
        "_signed_on_dt": signed_on_dt,
    })
    db.signature_records[record["id"]] = record
    batch["raw_count"] += 1
    touch(batch)
    calc.recompute_petition_counts(petition)
    touch(petition)
    return response.single(serialize(record), 201)


@bp.route("/signature-batches/<batch_id>/verify-affidavit", methods=["POST"])
def verify_affidavit(batch_id):
    user_id, role = require_auth(["CountyClerk"])
    body = v.body()
    notary_id = v.as_string(v.required(body, "affidavit_notary_id"),
                            "affidavit_notary_id")
    defect_lines = v.optional(body, "format_defect_line_numbers", [])
    defect_lines = v.as_int_array(defect_lines, "format_defect_line_numbers",
                                 minimum=1)
    batch = get_batch(batch_id)
    require_batch_owner(batch, user_id, role)
    if batch["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_BATCH_STATE")

    records = records_of_batch(batch["id"])
    by_line = {r["line_number"]: r for r in records}
    for line_number in defect_lines:
        if line_number not in by_line:
            raise ApiError("ERR_LINE_NUMBER_NOT_FOUND")
    if batch["raw_count"] < 1:
        raise ApiError("ERR_BATCH_EMPTY")

    for line_number in defect_lines:
        record = by_line[line_number]
        record["validation_status"] = "INVALID_FORMAT_DEFECT"
        touch(record)
    batch["affidavit_notary_id"] = notary_id
    batch["format_defect_count"] = len(defect_lines)
    if len(defect_lines) >= batch["raw_count"]:
        batch["accepted_raw_count"] = 0
        batch["status"] = "REJECTED_FORMAT"
    else:
        batch["accepted_raw_count"] = batch["raw_count"] - len(defect_lines)
        batch["status"] = "AFFIDAVIT_VERIFIED"
    touch(batch)
    petition = db.petitions[batch["petition_id"]]
    calc.recompute_petition_counts(petition)
    touch(petition)
    return response.single(serialize(batch))


# ---------------------------------------------------------------------------
# invalidation and its compensating reinstatement
# ---------------------------------------------------------------------------
@bp.route("/signature-batches/<batch_id>/invalidate", methods=["POST"])
def invalidate_batch(batch_id):
    require_auth(["SosAdmin"])
    body = v.body()
    reason = v.as_string(v.required(body, "invalidation_reason"), "invalidation_reason")
    batch = get_batch(batch_id)
    if batch["status"] in ("REJECTED_FORMAT", "INVALIDATED"):
        raise ApiError("ERR_BATCH_ALREADY_TERMINAL")
    cascades.invalidate_batch(batch, "BATCH_INVALIDATED", reason)
    petition = db.petitions[batch["petition_id"]]
    cascades.recompute_petition_ledgers(petition)
    return response.single(serialize(batch))


@bp.route("/signature-batches/<batch_id>/reinstate", methods=["POST"])
def reinstate_batch(batch_id):
    require_auth(["SosAdmin"])
    body = v.body()
    reason = v.optional(body, "invalidation_reason")
    if reason is not None:
        reason = v.as_string(reason, "invalidation_reason")
    batch = get_batch(batch_id)
    if batch["status"] != "INVALIDATED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    circulator = db.circulators.get(batch["circulator_id"])
    if circulator is not None and circulator["registration_status"] == "REVOKED":
        raise ApiError("ERR_CIRCULATOR_REVOKED")
    if cascades.substantiated_referral_names_batch(batch["id"]):
        raise ApiError("ERR_FRAUD_SUBSTANTIATED_BATCH")
    cascades.reinstate_batch(batch, reason)
    petition = db.petitions[batch["petition_id"]]
    cascades.recompute_petition_ledgers(petition)
    return response.single(serialize(batch))


# ---------------------------------------------------------------------------
# signature records
# ---------------------------------------------------------------------------
@bp.route("/signature-records/<signature_record_id>", methods=["GET"])
def read_record(signature_record_id):
    require_auth(RECORD_READ_ROLES)
    return response.single(serialize(get_signature_record(signature_record_id)))


@bp.route("/signature-records", methods=["GET"])
def list_records():
    require_auth(RECORD_READ_ROLES)
    return response.listing(list(db.signature_records.values()), {
        "batch_id": ("str", "batch_id"),
        "matched_voter_record_id": ("str", "matched_voter_record_id"),
        "duplicate_of_signature_id": ("str", "duplicate_of_signature_id"),
        "validated_in_round_id": ("str", "validated_in_round_id"),
        "validation_status": ("str", "validation_status"),
        "in_sample": ("bool", "in_sample"),
    })


@bp.route("/signature-records/<signature_record_id>/validate", methods=["POST"])
def validate_record(signature_record_id):
    user_id, role = require_auth(["CountyClerk"])
    body = v.body()
    manual_override = v.as_bool(v.optional(body, "manual_match_override", False),
                                "manual_match_override")
    record = get_signature_record(signature_record_id)
    batch = db.batches[record["batch_id"]]
    require_batch_owner(batch, user_id, role)

    rnd = db.rounds.get(record["validated_in_round_id"]) \
        if record["validated_in_round_id"] else None
    if not record["in_sample"] or rnd is None or rnd["status"] != "OPEN" \
            or record["validation_status"] != "PENDING":
        raise ApiError("ERR_SIGNATURE_NOT_IN_OPEN_ROUND")

    verification.validate_line(record, manual_override)
    touch(record)
    circulator = db.circulators.get(batch["circulator_id"])
    if circulator is not None:
        calc.recompute_credibility(circulator)
        touch(circulator)
    return response.single(serialize(record))
