"""Outcome measurements, claim lines, invoices, care transitions, the clock."""

from flask import Blueprint

from db import STORE
from middleware import body, query, require
from response import array_response, object_response, page
from services import intake, invoicing, set_clock
from services import outcomes as outcome_service

bp = Blueprint("outcomes", __name__)


# --- outcome measurements --------------------------------------------------
@bp.route("/msk/outcome-measurements", methods=["POST"])
def record_measurement():
    user_id, role = require(["Member"], "POST /msk/outcome-measurements")
    return object_response(dict(outcome_service.record_measurement(body(), user_id)), 201)


@bp.route("/msk/outcome-measurements", methods=["GET"])
def list_measurements():
    require(
        ["ClinicalOps", "EnrollmentOps", "BillingOps", "Member"],
        "GET /msk/outcome-measurements",
    )
    rows = STORE.all("OutcomeMeasurement")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    status = query("measurement_status")
    if status:
        rows = [r for r in rows if r["measurement_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/outcome-measurements/<measurement_id>", methods=["GET"])
def read_measurement(measurement_id):
    require(
        ["ClinicalOps", "EnrollmentOps", "BillingOps", "Member"],
        "GET /msk/outcome-measurements/{id}",
    )
    row = STORE.need("OutcomeMeasurement", measurement_id, "OutcomeMeasurement")
    return object_response(dict(row))


@bp.route("/msk/outcome-measurements/<measurement_id>/supersede", methods=["POST"])
def supersede_measurement(measurement_id):
    require(
        ["ClinicalReviewService"],
        "POST /msk/outcome-measurements/{id}/supersede",
    )
    return object_response(
        dict(outcome_service.supersede_measurement(measurement_id, body()))
    )


@bp.route("/msk/outcome-measurements/<measurement_id>/finalize", methods=["POST"])
def finalize_measurement(measurement_id):
    require(
        ["ClinicalReviewService"],
        "POST /msk/outcome-measurements/{id}/finalize",
    )
    return object_response(dict(outcome_service.finalize_measurement(measurement_id)))


# --- claim lines -----------------------------------------------------------
@bp.route("/msk/claim-lines", methods=["POST"])
def record_claim_line():
    require(["EnrollmentOps"], "POST /msk/claim-lines")
    return object_response(dict(outcome_service.record_claim_line(body())), 201)


@bp.route("/msk/claim-lines", methods=["GET"])
def list_claim_lines():
    require(
        ["EnrollmentOps", "BillingOps", "ClinicalOps"], "GET /msk/claim-lines"
    )
    rows = STORE.all("ClaimLine")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    measurement_id = query("outcome_measurement_id")
    if measurement_id:
        window = STORE.get("OutcomeMeasurement", measurement_id)
        if window is None:
            from errors import not_found

            raise not_found("OutcomeMeasurement")
        rows = [
            r for r in rows
            if window["window_start_week"] <= r["claim_service_week"]
            <= window["window_end_week"]
        ]
    week = query("claim_service_week")
    if week:
        rows = [r for r in rows if str(r["claim_service_week"]) == week]
    source = query("claim_source")
    if source:
        rows = [r for r in rows if r["claim_source"] == source]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/claim-lines/<claim_id>", methods=["GET"])
def read_claim_line(claim_id):
    require(
        ["EnrollmentOps", "BillingOps", "ClinicalOps"], "GET /msk/claim-lines/{id}"
    )
    row = STORE.need("ClaimLine", claim_id, "ClaimLine")
    return object_response(dict(row))


@bp.route("/msk/claim-lines/<claim_id>/supersede", methods=["POST"])
def supersede_claim_line(claim_id):
    require(["EnrollmentOps"], "POST /msk/claim-lines/{id}/supersede")
    return object_response(
        dict(outcome_service.supersede_claim_line(claim_id, body()))
    )


@bp.route("/msk/claim-lines/<claim_id>/reinstate", methods=["POST"])
def reinstate_claim_line(claim_id):
    require(["EnrollmentOps"], "POST /msk/claim-lines/{id}/reinstate")
    return object_response(
        dict(outcome_service.reinstate_claim_line(claim_id, body()))
    )


# --- fee invoices ----------------------------------------------------------
def _invoice_view(row):
    view = dict(row)
    view.pop("_milestone_group", None)
    return view


@bp.route("/msk/fee-invoices", methods=["POST"])
def create_invoice():
    require(["BillingOps"], "POST /msk/fee-invoices")
    row = invoicing.create_invoice(body())
    return object_response(_invoice_view(row), 201)


@bp.route("/msk/fee-invoices", methods=["GET"])
def list_invoices():
    require(["BillingOps", "ClinicalOps"], "GET /msk/fee-invoices")
    rows = STORE.all("FeeInvoice")
    client_id = query("client_account_id")
    if client_id:
        rows = [r for r in rows if r["client_account_id"] == client_id]
    status = query("invoice_status")
    if status:
        rows = [r for r in rows if r["invoice_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/fee-invoices/<invoice_id>", methods=["GET"])
def read_invoice(invoice_id):
    require(["BillingOps", "ClinicalOps"], "GET /msk/fee-invoices/{id}")
    row = STORE.need("FeeInvoice", invoice_id, "FeeInvoice")
    return object_response(_invoice_view(row))


@bp.route("/msk/fee-invoices/<invoice_id>/finalize", methods=["POST"])
def finalize_invoice(invoice_id):
    require(["BillingOps"], "POST /msk/fee-invoices/{id}/finalize")
    row = invoicing.finalize_invoice(invoice_id)
    return object_response(_invoice_view(row))


@bp.route("/msk/fee-invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    require(["BillingOps"], "POST /msk/fee-invoices/{id}/void")
    row = invoicing.void_invoice(invoice_id)
    return object_response(_invoice_view(row))


@bp.route("/msk/fee-invoices/<invoice_id>/reopen", methods=["POST"])
def reopen_invoice(invoice_id):
    require(["BillingOps"], "POST /msk/fee-invoices/{id}/reopen")
    row = invoicing.reopen_invoice(invoice_id)
    return object_response(_invoice_view(row))


# --- care transitions -------------------------------------------------------
@bp.route("/msk/care-transitions", methods=["POST"])
def open_transition():
    require(["Clinician"], "POST /msk/care-transitions")
    return object_response(dict(intake.open_care_transition(body())), 201)


@bp.route("/msk/care-transitions", methods=["GET"])
def list_transitions():
    require(["ClinicalOps", "EnrollmentOps"], "GET /msk/care-transitions")
    rows = STORE.all("CareTransition")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    status = query("transition_status")
    if status:
        rows = [r for r in rows if r["transition_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/care-transitions/<transition_id>", methods=["GET"])
def read_transition(transition_id):
    require(["ClinicalOps", "EnrollmentOps"], "GET /msk/care-transitions/{id}")
    row = STORE.need("CareTransition", transition_id, "CareTransition")
    return object_response(dict(row))


@bp.route("/msk/care-transitions/<transition_id>/complete", methods=["POST"])
def complete_transition(transition_id):
    user_id, role = require(
        ["Clinician"], "POST /msk/care-transitions/{id}/complete"
    )
    row = intake.complete_care_transition(transition_id, user_id)
    return object_response(dict(row))


# --- logical clock ---------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require(["ClinicalOps"], "POST /_clock/set_current_utc")
    payload = body()
    if payload.get("current_utc") is None:
        from errors import invalid_reference

        raise invalid_reference("current_utc is required.")
    set_clock(payload["current_utc"])
    return object_response({})