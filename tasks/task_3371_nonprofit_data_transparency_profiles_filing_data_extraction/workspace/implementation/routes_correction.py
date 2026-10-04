"""Correction requests: filing them and driving the review state machine."""

from flask import Blueprint

import auth
import calc
import clock
import listing
import response
import store
import svc
import webutil
from errors import (
    ApiError,
    ERR_FIELD_NOT_CORRECTABLE,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_EXTRACTED_FIELD_VERSION,
)

bp = Blueprint("corrections", __name__)

DECISIONS = ("CLAIM", "RETURN_FOR_INFO", "ACCEPT", "PARTIALLY_ACCEPT", "REJECT", "WITHDRAW")
VERIFIER_DECISIONS = ("CLAIM", "RETURN_FOR_INFO", "ACCEPT", "PARTIALLY_ACCEPT", "REJECT")
NOTE_REQUIRED = ("RETURN_FOR_INFO", "REJECT")
CORRECTABLE = ("NORMALIZED", "CORRECTED")

CREATE_FIELDS = (
    "requested_value", "evidence_url", "justification", "expected_extracted_field_version",
)
DECIDE_FIELDS = ("decision", "review_note", "corrected_value")


def _field_organization(field):
    filing = store.find("filings", field.get("filing_id"))
    if filing is None:
        return None, None
    return filing, filing.get("organization_id")


@bp.route("/nonprofits/extracted-fields/<field_id>/correction-requests", methods=["POST"])
def create_correction_request(field_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_ORGANIZATION_USER,))
    field = svc.get_extracted_field(field_id)
    filing, organization_id = _field_organization(field)
    auth.require_owner(acting, organization_id, "extracted data")

    data = webutil.body()
    webutil.reject_unknown(data, CREATE_FIELDS)
    requested_value = webutil.as_string(data, "requested_value")
    evidence_url = webutil.as_string(data, "evidence_url")
    justification = webutil.as_string(data, "justification")
    expected_version = webutil.as_int(data, "expected_extracted_field_version")

    if expected_version != field.get("version"):
        raise ApiError(
            ERR_STALE_EXTRACTED_FIELD_VERSION,
            "expected_extracted_field_version does not match the field's current version.",
        )

    if field.get("normalization_status") not in CORRECTABLE:
        raise ApiError(
            ERR_FIELD_NOT_CORRECTABLE,
            "A field in %s status has no settled value to dispute."
            % field.get("normalization_status"),
        )

    request_row = store.new_row(
        organization_id=organization_id,
        target_extracted_field_id=field_id,
        requested_value=requested_value,
        evidence_url=evidence_url,
        justification=justification,
        status="SUBMITTED",
        submitted_by_user_id=acting.user_id,
        decided_by_user_id=None,
        review_note=None,
        requested_at=clock.fmt_dt(clock.now()),
        decided_at=None,
    )
    store.insert("correction_requests", request_row)
    store.touch(field)

    org = store.find("organizations", organization_id)
    if org is not None:
        svc.recompute_counters(org)
        svc.maybe_suspend(org)
    return response.ok(svc.ser_correction(request_row), status=201)


@bp.route("/nonprofits/extracted-fields/<field_id>/correction-requests", methods=["GET"])
def list_field_correction_requests(field_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_ORGANIZATION_USER,
    ))
    svc.get_extracted_field(field_id)
    rows = store.where("correction_requests", target_extracted_field_id=field_id)
    return listing.list_endpoint(rows, svc.ser_correction, (("status", "status", "str"),))


def _apply_accepted_value(field, raw_value):
    cents = calc.normalize_cents(raw_value, field.get("raw_format"))
    if cents is None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "The supplied value cannot be converted to cents for this line.",
        )
    return cents


@bp.route("/nonprofits/correction-requests/<correction_id>/decide", methods=["POST"])
def decide_correction_request(correction_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_ORGANIZATION_USER))
    request_row = svc.get_correction(correction_id)

    data = webutil.body()
    webutil.reject_unknown(data, DECIDE_FIELDS)
    decision = webutil.as_enum(data, "decision", DECISIONS)
    review_note = data.get("review_note")
    corrected_value = data.get("corrected_value")

    # Authorization: each decision belongs to exactly one role.
    if acting.role == auth.ROLE_PLATFORM_VERIFIER and decision not in VERIFIER_DECISIONS:
        raise ApiError(
            ERR_FORBIDDEN_ROLE, "A PlatformVerifier may not drive decision %s." % decision
        )
    if acting.role == auth.ROLE_ORGANIZATION_USER and decision != "WITHDRAW":
        raise ApiError(
            ERR_FORBIDDEN_ROLE, "An OrganizationUser may only withdraw a correction request."
        )
    if decision == "WITHDRAW" and acting.user_id != request_row.get("submitted_by_user_id"):
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Only the submitter may withdraw a correction request.",
        )

    # Request shape (rung 4).
    if decision in NOTE_REQUIRED:
        if not isinstance(review_note, str) or review_note.strip() == "":
            raise ApiError(ERR_INVALID_REQUEST, "review_note must be non-empty.")
    if decision == "PARTIALLY_ACCEPT":
        if not isinstance(corrected_value, str) or corrected_value.strip() == "":
            raise ApiError(ERR_INVALID_REQUEST, "corrected_value must be supplied.")

    field = store.find("extracted_fields", request_row.get("target_extracted_field_id"))
    if field is None:
        raise ApiError(ERR_INVALID_STATE, "The disputed extracted field no longer exists.")
    filing = store.find("filings", field.get("filing_id"))

    if decision == "PARTIALLY_ACCEPT":
        current = field.get("normalized_value_cents") if field is not None else None
        candidate = _apply_accepted_value(field, corrected_value)
        requested_cents = _apply_accepted_value(field, request_row.get("requested_value"))
        if candidate == current or candidate == requested_cents:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "corrected_value must differ from both the current value and requested_value.",
            )

    status = request_row.get("status")

    if decision == "CLAIM":
        if status != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED request can be claimed.")
        if acting.user_id == request_row.get("submitted_by_user_id"):
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "The deciding user must differ from the submitting user.",
            )
        request_row["status"] = "UNDER_REVIEW"
        request_row["decided_by_user_id"] = acting.user_id
        store.touch(request_row)

    elif decision == "RETURN_FOR_INFO":
        if status != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Only a request under review can be returned.")
        request_row["status"] = "SUBMITTED"
        request_row["decided_by_user_id"] = None
        request_row["review_note"] = review_note
        store.touch(request_row)

    elif decision == "ACCEPT":
        if status != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Only a request under review can be accepted.")
        if filing is None or filing.get("status") not in ("NORMALIZED", "DISPUTED"):
            raise ApiError(
                ERR_INVALID_STATE,
                "The target field's filing must be NORMALIZED or DISPUTED.",
            )
        if acting.user_id == request_row.get("submitted_by_user_id"):
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "The deciding user must differ from the submitting user.",
            )
        field["normalized_value_cents"] = _apply_accepted_value(
            field, request_row.get("requested_value")
        )
        field["normalization_status"] = "CORRECTED"
        field["is_verified"] = True
        field["correction_count"] = (field.get("correction_count") or 0) + 1
        store.touch(field)
        if filing.get("status") == "NORMALIZED":
            filing["status"] = "DISPUTED"
        svc.recompute_filing_totals(filing)
        store.touch(filing)
        request_row["status"] = "ACCEPTED"
        request_row["decided_by_user_id"] = acting.user_id
        request_row["decided_at"] = clock.fmt_dt(clock.now())
        request_row["review_note"] = review_note
        store.touch(request_row)

    elif decision == "PARTIALLY_ACCEPT":
        if status != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Only a request under review can be partially accepted.")
        field["normalized_value_cents"] = _apply_accepted_value(field, corrected_value)
        field["normalization_status"] = "CORRECTED"
        field["correction_count"] = (field.get("correction_count") or 0) + 1
        if filing is not None:
            if filing.get("status") == "NORMALIZED":
                filing["status"] = "DISPUTED"
            svc.recompute_filing_totals(filing)
            store.touch(filing)
        request_row["status"] = "PARTIALLY_ACCEPTED"
        request_row["decided_by_user_id"] = acting.user_id
        request_row["decided_at"] = clock.fmt_dt(clock.now())
        request_row["review_note"] = review_note
        store.touch(request_row)

    elif decision == "REJECT":
        if status != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Only a request under review can be rejected.")
        request_row["status"] = "REJECTED"
        request_row["decided_by_user_id"] = acting.user_id
        request_row["decided_at"] = clock.fmt_dt(clock.now())
        request_row["review_note"] = review_note
        store.touch(request_row)

    else:  # WITHDRAW
        if status not in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError(ERR_INVALID_STATE, "Only an open request can be withdrawn.")
        request_row["status"] = "WITHDRAWN"
        store.touch(request_row)

    org = store.find("organizations", request_row.get("organization_id"))
    if org is not None:
        if decision in ("ACCEPT", "PARTIALLY_ACCEPT"):
            svc.recompute_revenue(org)
            svc.recompute_scores(org)
            svc.recompute_disclosure(org)
            svc.apply_profile_floor_cascade(org)
            svc.apply_seal_floor_cascade(org)
        svc.recompute_counters(org)
        svc.maybe_suspend(org)
        if decision in ("ACCEPT", "PARTIALLY_ACCEPT"):
            store.touch(org)
    return response.ok(svc.ser_correction(request_row))
