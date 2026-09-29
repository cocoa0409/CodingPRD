"""Certificates: issuance, extension, modification by reissue, lapse sweep and reports."""

from flask import Blueprint

import auth
import calc
import cascades
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("certificates", __name__)

READ_ROLES = auth.STAFF_AND_PARTIES
REPORT_READ_ROLES = ["ProgramAdmin", "IntakeAnalyst", "DecisionOfficer", "Applicant"]
BASES = ("CASH", "ACCRUAL")
APPROVED_STATES = ("APPROVED", "APPROVED_WITH_CONDITIONS")


def _require_active(cert):
    if cert["lifecycle_status"] not in services.ACTIVE_CERT_STATES:
        raise ApiError("ERR_CERTIFICATE_NOT_ACTIVE",
                       "The certificate is not in an active lifecycle state.")


@bp.post("/certificates")
def issue_certificate():
    user_id, _role = auth.identity(["DecisionOfficer"])
    body = shape.body()
    application_id = shape.string_field(body, "application_id")
    limit_cents = shape.int_field(body, "approved_expenditure_limit_cents", minimum=1)
    milestone_date = shape.date_field(body, "implementation_milestone_date")
    basis = shape.enum_field(body, "expenditure_basis", BASES, required=False, default="CASH")
    conditions = shape.array_field(body, "conditions", required=False, default=[])
    required_pct = shape.number_field(body, "required_completion_pct_at_milestone",
                                      required=False, default=25, minimum=0, maximum=100)

    app = services.application(application_id)

    if app["status"] not in APPROVED_STATES:
        raise ApiError("ERR_APPLICATION_NOT_APPROVED",
                       "Only an approved application may be certificated.")

    services.require_no_hold(app["id"])

    closes = app.get("appeal_window_closes_at")
    if closes is None or not clock.now() > clock.parse_instant(closes):
        raise ApiError("ERR_APPEAL_WINDOW_OPEN",
                       "The application's appeal window has not closed yet.")

    if app["allocated_bed_count"] == 0:
        raise ApiError("ERR_NEED_EXHAUSTED",
                       "The application holds no allocated beds to certificate.")

    for other in services.certificates_of_application(app["id"]):
        if other["lifecycle_status"] in services.ACTIVE_CERT_STATES:
            raise ApiError("ERR_DUPLICATE_LOI",
                           "This application already has a live certificate.")

    record = store.create("certificates", {
        "application_id": app["id"],
        "authorized_bed_count": app["allocated_bed_count"],
        "approved_expenditure_limit_cents": limit_cents,
        "expenditure_ceiling_cents": calc.expenditure_ceiling(limit_cents),
        "expenditure_basis": basis,
        "cumulative_expenditure_cash_cents": 0,
        "cumulative_expenditure_accrual_cents": 0,
        "implementation_milestone_date": milestone_date,
        "required_completion_pct_at_milestone": required_pct,
        "latest_completion_pct": 0,
        "conditions": conditions,
        "issued_by_user_id": user_id,
        "superseded_certificate_id": None,
        "extension_days_granted_total": 0,
        "lifecycle_status": "ISSUED",
        "lifecycle_status_before_suspension": None,
        "expenditure_status": "WITHIN_LIMIT",
    })

    area = services.area_of_certificate(record)
    if area is not None:
        services.credit_area(area, beds=record["authorized_bed_count"], cents=limit_cents)
        store.touch(area)
    return envelope.ok(record, 201)


@bp.get("/certificates/<record_id>")
def read_certificate(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.certificate(record_id))


@bp.get("/certificates")
def list_certificates():
    auth.identity(READ_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("application_id", "superseded_certificate_id", "lifecycle_status")
    rows = shape.apply_filters(store.sort_created(store.rows("certificates")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/certificates/run-lapse-sweep")
def run_lapse_sweep():
    auth.identity(["ProgramAdmin"])
    return envelope.ok(cascades.run_lapse_sweep())


@bp.post("/certificates/<record_id>/extend")
def extend_certificate(record_id):
    auth.identity(["DecisionOfficer"])
    body = shape.body()
    requested_days = shape.int_field(body, "requested_days", minimum=0)
    shape.string_field(body, "justification", required=False, default=None)
    cert = services.certificate(record_id)

    _require_active(cert)
    services.require_no_hold(cert["application_id"])

    granted, remaining = calc.extension_grant(
        requested_days, cert["extension_days_granted_total"])
    if remaining <= 0:
        raise ApiError("ERR_EXTENSION_CAP_EXHAUSTED",
                       "The lineage's cumulative extension allowance is exhausted.")

    cert["extension_days_granted_total"] = cert["extension_days_granted_total"] + granted
    cert["implementation_milestone_date"] = clock.add_days_to_date_string(
        cert["implementation_milestone_date"], granted)
    store.touch(cert)
    return envelope.ok(cert)


@bp.post("/certificates/<record_id>/modify")
def modify_certificate(record_id):
    user_id, _role = auth.identity(["DecisionOfficer"])
    body = shape.body()
    expected_version = shape.int_field(body, "expected_certificate_version", minimum=0)
    new_limit = shape.int_field(body, "new_approved_expenditure_limit_cents",
                                required=False, default=None, minimum=0)
    new_beds = shape.int_field(body, "new_authorized_bed_count",
                               required=False, default=None, minimum=0)
    new_milestone = shape.date_field(body, "new_implementation_milestone_date",
                                     required=False, default=None)
    cert = services.certificate(record_id)

    _require_active(cert)
    services.require_no_hold(cert["application_id"])

    if expected_version != cert["version"]:
        raise ApiError("ERR_STALE_CERTIFICATE_VERSION",
                       "expected_certificate_version does not match the certificate's version.")

    old_limit = cert["approved_expenditure_limit_cents"]
    old_beds = cert["authorized_bed_count"]
    governing = services.governing_expenditure(cert)
    cycle_row = services.cycle_of_certificate(cert)

    if new_limit is not None and new_limit < governing:
        raise ApiError("ERR_MODIFICATION_BELOW_COMMITTED",
                       "The new expenditure limit is below the governing cumulative "
                       "expenditure.")
    if (new_beds is not None and new_beds < old_beds
            and cert["lifecycle_status"] == "IMPLEMENTED"):
        raise ApiError("ERR_MODIFICATION_BELOW_COMMITTED",
                       "The new bed count is below the beds already released to the "
                       "planning area.")
    if new_beds is not None and new_beds > old_beds:
        pool = cycle_row["unallocated_bed_need"] if cycle_row else 0
        if (new_beds - old_beds) > pool:
            raise ApiError("ERR_NEED_EXHAUSTED",
                           "The bed increase exceeds the cycle's unallocated need.")

    limit_cents = old_limit if new_limit is None else new_limit
    beds = old_beds if new_beds is None else new_beds
    milestone = cert["implementation_milestone_date"] if new_milestone is None else new_milestone

    if cert["lifecycle_status"] == "SUSPENDED":
        successor_lifecycle = cert.get("lifecycle_status_before_suspension") or "ISSUED"
    else:
        successor_lifecycle = cert["lifecycle_status"]

    cert["lifecycle_status"] = "SUPERSEDED"
    if new_limit is not None and new_limit > old_limit:
        cert["expenditure_status"] = "LIMIT_AMENDED"
    store.touch(cert)

    successor = store.create("certificates", {
        "application_id": cert["application_id"],
        "authorized_bed_count": beds,
        "approved_expenditure_limit_cents": limit_cents,
        "expenditure_ceiling_cents": calc.expenditure_ceiling(limit_cents),
        "expenditure_basis": cert["expenditure_basis"],
        "cumulative_expenditure_cash_cents": 0,
        "cumulative_expenditure_accrual_cents": 0,
        "implementation_milestone_date": milestone,
        "required_completion_pct_at_milestone": cert["required_completion_pct_at_milestone"],
        "latest_completion_pct": 0,
        "conditions": list(cert["conditions"]),
        "issued_by_user_id": user_id,
        "superseded_certificate_id": cert["id"],
        "extension_days_granted_total": cert["extension_days_granted_total"],
        "lifecycle_status": successor_lifecycle,
        "lifecycle_status_before_suspension": None,
        "expenditure_status": "WITHIN_LIMIT",
    })
    services.recompute_certificate_fiscal(successor)

    area = services.area_of_certificate(successor)
    if area is not None:
        services.credit_area(area, cents=(limit_cents - old_limit), beds=(beds - old_beds))
        store.touch(area)
    if cycle_row is not None and beds != old_beds:
        services.credit_pool(cycle_row, -(beds - old_beds))
        store.touch(cycle_row)
    return envelope.ok(successor, 201)


# --- progress reports --------------------------------------------------------

@bp.post("/progress-reports")
def file_progress_report():
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    certificate_id = shape.string_field(body, "certificate_id")
    period_end = shape.date_field(body, "period_end_date")
    disbursed = shape.int_field(body, "disbursed_cents", minimum=0)
    obligated = shape.int_field(body, "obligated_cents", minimum=0)
    completion = shape.number_field(body, "physical_completion_pct", minimum=0, maximum=100)
    attestations = shape.array_field(body, "condition_attestations", required=False, default=[])
    expected_version = shape.int_field(body, "expected_certificate_version", minimum=0)

    cert = services.certificate(certificate_id)
    app = store.get("applications", cert["application_id"])
    services.require_owner(user_id, app["applicant_id"] if app else None)

    _require_active(cert)
    services.require_not_barred(services.applicant_of_certificate(cert))

    if expected_version != cert["version"]:
        raise ApiError("ERR_STALE_CERTIFICATE_VERSION",
                       "expected_certificate_version does not match the certificate's version.")

    if (disbursed + obligated) > 2 * cert["approved_expenditure_limit_cents"]:
        raise ApiError("ERR_EXPENDITURE_LIMIT_EXCEEDED",
                       "The period's own expenditure exceeds twice the approved limit.")

    record = store.create("progress_reports", {
        "certificate_id": cert["id"],
        "period_end_date": period_end,
        "disbursed_cents": disbursed,
        "obligated_cents": obligated,
        "physical_completion_pct": completion,
        "condition_attestations": attestations,
        "filed_by_user_id": user_id,
        "status": "ACCEPTED",
    })
    cascades.apply_progress_report(cert, record)
    return envelope.ok(record, 201)


@bp.get("/certificates/<record_id>/progress-reports")
def list_progress_reports(record_id):
    auth.identity(REPORT_READ_ROLES)
    cert = services.certificate(record_id)
    limit, offset = shape.pagination()
    rows = store.sort_created([r for r in store.rows("progress_reports")
                               if r["certificate_id"] == cert["id"]])
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))
