"""Composite setup helpers.

Each helper drives the API from an empty database to the state a test needs.
All of them use the lenient setup validator so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error, and all
ownership-gated calls carry the owning entity row's id as the acting identity
(via make_candidate_headers / make_employer_headers).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_application_payload,
    create_certification_payload,
    create_document_payload,
    create_employer_payload,
    create_interview_payload,
    create_license_verification_payload,
    create_nurse_payload,
    create_offer_payload,
    create_requisition_payload,
)
from .test_users import ADMIN, make_candidate_headers, make_employer_headers


def _data(response, label):
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - diagnostics only
        raise AssertionError(f"Setup failed at {label}: {exc} — {response.text}") from exc


def set_clock(instant: str = DEFAULT_CLOCK):
    resp = api_client.set_clock(instant, ADMIN)
    assert 200 <= resp.status_code < 300, (
        f"Setting the clock to {instant} failed: {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Single-entity builders
# ---------------------------------------------------------------------------

def create_employer(**overrides) -> dict:
    """Register an employer (ACTIVE, credit_balance_cents 0)."""
    payload = create_employer_payload(**overrides)
    return _data(api_client.create_employer(payload, ADMIN), "create employer")


def create_draft_nurse(**overrides) -> dict:
    """Register a nurse in DRAFT. Headers are unbound: self-registration is not
    ownership-gated (the row does not exist yet)."""
    payload = create_nurse_payload(**overrides)
    resp = api_client.create_nurse(
        payload, make_candidate_headers(f"seed-nurse-{payload['email']}")
    )
    return _data(resp, "create nurse")


def add_license(nurse: dict, **overrides) -> dict:
    payload = create_license_verification_payload(nurse["id"], **overrides)
    resp = api_client.create_license_verification(payload, make_candidate_headers(nurse["id"]))
    return _data(resp, "create license verification")


def submit_nurse(nurse: dict) -> dict:
    return _data(
        api_client.submit_nurse(nurse["id"], make_candidate_headers(nurse["id"])),
        "submit nurse",
    )


def verify_license(verification: dict) -> dict:
    return _data(api_client.verify_license(verification["id"], ADMIN), "verify license")


def create_certification(nurse: dict, **overrides) -> dict:
    payload = create_certification_payload(nurse["id"], **overrides)
    resp = api_client.create_certification(payload, make_candidate_headers(nurse["id"]))
    return _data(resp, "create certification")


def create_requisition(employer: dict, **overrides) -> dict:
    payload = create_requisition_payload(employer["id"], **overrides)
    resp = api_client.create_requisition(payload, make_employer_headers(employer["id"]))
    return _data(resp, "create requisition")


def fresh_nurse_version(nurse_id: str) -> int:
    """Re-read the nurse to obtain the current OCC version."""
    nurse = _data(
        api_client.get_nurse(nurse_id, make_candidate_headers(nurse_id)),
        "re-read nurse",
    )
    return nurse["version"]


def fresh_requisition_version(requisition_id: str, employer: dict) -> int:
    req = _data(
        api_client.get_requisition(requisition_id, make_employer_headers(employer["id"])),
        "re-read requisition",
    )
    return req["version"]


def create_application(requisition: dict, nurse: dict, employer: dict, **overrides) -> dict:
    if "expected_nurse_version" not in overrides:
        overrides["expected_nurse_version"] = fresh_nurse_version(nurse["id"])
    payload = create_application_payload(requisition["id"], nurse["id"],
                                         overrides.pop("expected_nurse_version"), **overrides)
    resp = api_client.create_application(payload, make_employer_headers(employer["id"]))
    return _data(resp, "create application")


def review_application(application: dict, nurse: dict) -> dict:
    return _data(
        api_client.review_application(application["id"], make_candidate_headers(nurse["id"])),
        "review application",
    )


def schedule_interview(application: dict, employer: dict, **overrides) -> dict:
    payload = create_interview_payload(**overrides)
    resp = api_client.schedule_interview(
        application["id"], payload, make_employer_headers(employer["id"])
    )
    return _data(resp, "schedule interview")


def complete_interview(interview: dict, employer: dict) -> dict:
    return _data(
        api_client.complete_interview(interview["id"], make_employer_headers(employer["id"])),
        "complete interview",
    )


def open_screening(application: dict, employer: dict) -> dict:
    resp = api_client.create_screening(
        {"application_id": application["id"]}, make_employer_headers(employer["id"])
    )
    return _data(resp, "open screening")


def verify_screening_credentials(screening: dict) -> dict:
    return _data(api_client.verify_credentials(screening["id"], ADMIN), "verify credentials")


def clear_screening_background(screening: dict) -> dict:
    return _data(api_client.clear_background(screening["id"], ADMIN), "clear background")


def upload_document(application: dict, nurse: dict, doc_type="SIGNED_CONTRACT") -> dict:
    payload = create_document_payload(application["id"], doc_type=doc_type)
    resp = api_client.create_document(payload, make_candidate_headers(nurse["id"]))
    return _data(resp, "upload document")


def approve_document(document: dict, employer: dict) -> dict:
    return _data(
        api_client.approve_document(document["id"], make_employer_headers(employer["id"])),
        "approve document",
    )


def issue_offer(application: dict, requisition: dict, employer: dict, **overrides) -> dict:
    if "expected_requisition_version" not in overrides:
        overrides["expected_requisition_version"] = fresh_requisition_version(
            requisition["id"], employer
        )
    expected = overrides.pop("expected_requisition_version")
    payload = create_offer_payload(expected, **overrides)
    resp = api_client.issue_offer(
        application["id"], payload, make_employer_headers(employer["id"])
    )
    return _data(resp, "issue offer")


# ---------------------------------------------------------------------------
# Composite pipelines
# ---------------------------------------------------------------------------

def setup_active_nurse(**nurse_overrides) -> dict:
    """Clock at the default + one ACTIVE license-verified nurse.

    Returns {"nurse", "license"}.
    """
    set_clock()
    nurse = create_draft_nurse(**nurse_overrides)
    lic = add_license(nurse)
    submit_nurse(nurse)
    verify_license(lic)
    nurse = _data(
        api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"])),
        "re-read nurse after activation",
    )
    assert nurse["status"] == "ACTIVE", f"nurse did not activate: {nurse}"
    return {"nurse": nurse, "license": lic}


def setup_employer_with_requisition(**req_overrides) -> dict:
    """One ACTIVE employer with one OPEN requisition.

    Returns {"employer", "requisition"}.
    """
    employer = create_employer(**req_overrides.pop("employer_overrides", {}))
    requisition = create_requisition(employer, **req_overrides)
    return {"employer": employer, "requisition": requisition}


def setup_marketplace(**req_overrides) -> dict:
    """Clock + ACTIVE nurse + employer with an OPEN requisition.

    Returns {"nurse", "license", "employer", "requisition"}.
    """
    n = setup_active_nurse()
    e = setup_employer_with_requisition(**req_overrides)
    return {**n, **e}


def setup_application_under_review(**overrides) -> dict:
    """Marketplace + application moved SUBMITTED -> UNDER_REVIEW.

    Returns {"nurse", "employer", "requisition", "application"}.
    """
    ctx = setup_marketplace(**overrides.pop("req_overrides", {}))
    app = create_application(ctx["requisition"], ctx["nurse"], ctx["employer"], **overrides)
    app = review_application(app, ctx["nurse"])
    assert app["status"] == "UNDER_REVIEW", f"application not under review: {app}"
    return {**ctx, "application": app}


def setup_application_interviewing(**overrides) -> dict:
    """UNDER_REVIEW application + one SCHEDULED interview (application INTERVIEWING).

    Returns the UNDER_REVIEW context plus "interview".
    """
    ctx = setup_application_under_review(**overrides)
    iv = schedule_interview(ctx["application"], ctx["employer"])
    assert iv["status"] == "SCHEDULED", f"interview not scheduled: {iv}"
    return {**ctx, "interview": iv}


def setup_application_with_completed_interview(**overrides) -> dict:
    """INTERVIEWING application whose interview is COMPLETED (clock advanced past
    the window)."""
    ctx = setup_application_interviewing(**overrides)
    set_clock("2026-09-02T12:00:00Z")
    iv = complete_interview(ctx["interview"], ctx["employer"])
    assert iv["status"] == "COMPLETED", f"interview not completed: {iv}"
    return {**ctx, "interview": iv}


def setup_offer_issued(**overrides) -> dict:
    """Full compliance pipeline: completed interview + screening COMPLETE +
    SIGNED_CONTRACT APPROVED + offer ISSUED.

    Returns the completed-interview context plus "screening", "document",
    "offer". The clock sits at 2026-09-02T12:00:00Z.
    """
    ctx = setup_application_with_completed_interview(**overrides)
    scr = open_screening(ctx["application"], ctx["employer"])
    scr = verify_screening_credentials(scr)
    scr = clear_screening_background(scr)
    assert scr["overall_status"] == "COMPLETE", f"screening not complete: {scr}"
    doc = upload_document(ctx["application"], ctx["nurse"], doc_type="SIGNED_CONTRACT")
    doc = approve_document(doc, ctx["employer"])
    assert doc["status"] == "APPROVED", f"document not approved: {doc}"
    offer = issue_offer(ctx["application"], ctx["requisition"], ctx["employer"])
    assert offer["status"] == "ISSUED", f"offer not issued: {offer}"
    return {**ctx, "screening": scr, "document": doc, "offer": offer}


def setup_placement_accepted(**overrides) -> dict:
    """Offer accepted: Placement PENDING_START exists, nurse HIRED, invoice ISSUED.

    Returns the offer-issued context plus "placement".
    """
    ctx = setup_offer_issued(**overrides)
    placement = _data(
        api_client.accept_offer(ctx["offer"]["id"], make_candidate_headers(ctx["nurse"]["id"])),
        "accept offer",
    )
    assert placement["status"] == "PENDING_START", f"placement not pending: {placement}"
    return {**ctx, "placement": placement}


def setup_placement_terminated_in_guarantee(**overrides) -> dict:
    """Placement created, clock advanced 15 days into the 60-day guarantee, then
    terminated.  Returns the accepted context plus "terminated"."""
    ctx = setup_placement_accepted(**overrides)
    set_clock("2026-10-30T00:00:00Z")
    terminated = _data(
        api_client.terminate_placement(
            ctx["placement"]["id"], make_employer_headers(ctx["employer"]["id"])
        ),
        "terminate placement",
    )
    assert terminated["status"] == "TERMINATED_IN_GUARANTEE", (
        f"placement not terminated: {terminated}"
    )
    return {**ctx, "placement": terminated}


def get_placement_invoice(placement: dict, employer: dict) -> dict:
    """The single PLACEMENT_FEE invoice wired to a placement."""
    resp = api_client.list_invoices(
        make_employer_headers(employer["id"]), params={"placement_id": placement["id"]}
    )
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly one invoice, saw {meta}"
    return rows[0]
