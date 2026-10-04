"""Submission gate chain, receipt window, referral OCC, and the re-referral
supersede semantics with its live-assignment guard."""
import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)

_PO = TEST_USERS["program_officer_headers"]
_RO = TEST_USERS["referral_officer_headers"]


def test_page_limit_exact_boundary():
    """PRD §3.2: "then the `research_strategy_page_count` must not exceed the announcement's `research_strategy_page_limit` (`ERR_PAGE_LIMIT_EXCEEDED`)"
    Pages equal to the limit submit cleanly; limit + 1 is rejected and the
    application stays DRAFT.

    Design: Difficulty/boundary_precision_check/page_limit_exact_boundary
    """
    ctx = fixtures.make_review_context(research_strategy_page_limit=12)
    pi_a = fixtures.make_applicant()
    pi_b = fixtures.make_applicant()
    app_ok = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        title="12 pages", research_strategy_page_count=12)
    app_over = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_b["id"],
        title="13 pages", research_strategy_page_count=13)

    ok = api_client.submit_application(app_ok["id"], make_applicant_headers(pi_a["id"]))
    assert validate_success(ok, 200)["status"] == "SUBMITTED", "pages == limit must pass"

    over = api_client.submit_application(app_over["id"], make_applicant_headers(pi_b["id"]))
    validate_error(over, ApiErrorId.ERR_PAGE_LIMIT_EXCEEDED)
    assert fixtures.refresh_application(app_over["id"])["status"] == "DRAFT"


def test_submit_certification_failure_beats_page_overflow():
    """PRD §2.7: "Every request is validated against a fixed, priority-ordered pipeline. When several checks could reject the same request, the earliest stage in this ordering wins, so the error a caller observes is always the highest-priority failure:"
    PRD §2.7: "8. **Institutional certifications.** An application flagging human-subjects or vertebrate-animal work requires the institution's corresponding certification or assurance to be present (`ERR_CERTIFICATION_MISSING`, HTTP 422) and unexpired relative to the governing date (`ERR_CERTIFICATION_EXPIRED`, HTTP 422)."
    PRD §2.7: "10. **Page limit.** The research strategy must fit the announcement's page limit (`ERR_PAGE_LIMIT_EXCEEDED`, HTTP 422)."
    Certifications (stage 8) precede the page limit (stage 10), so a
    submission violating both observes the certification error.

    Design: Difficulty/priority_pair_validation_conflict/submit_certification_failure_beats_page_overflow
    """
    ctx = fixtures.make_review_context(
        human_subjects_certification_expiry="2026-11-01T00:00:00Z",
        receipt_deadline="2026-12-01T00:00:00Z",
    )
    pi_a = fixtures.make_applicant()
    app = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        title="Cert app", research_strategy_page_count=13,
        human_subjects_involved=True)
    resp = api_client.submit_application(app["id"], make_applicant_headers(pi_a["id"]))
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED)
    assert fixtures.refresh_application(app["id"])["status"] == "DRAFT", (
        "a rejected submission must leave the application DRAFT (no partial transition)"
    )


def test_submit_requires_foa_open():
    """PRD §3.2: "Following the pipeline order of §2.7, the announcement must still be `OPEN` (`ERR_FOA_NOT_OPEN`)"
    PRD §3.1: "When the program office closes it, its status moves from `OPEN` to `CLOSED` and no further submissions against it are accepted; closing an already-`CLOSED` announcement is rejected with `ERR_FOA_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_foa_open
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    app = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"], title="Closed FOA app")
    fixtures.close_foa(ctx["foa"]["id"])
    resp = api_client.submit_application(app["id"], make_applicant_headers(pi_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FOA_NOT_OPEN)
    assert fixtures.refresh_application(app["id"])["status"] == "DRAFT"


def test_resubmit_submitted_application_rejected():
    """PRD §3.2: "Submission by the owning `Applicant` runs the announcement's full gate chain against a `DRAFT` application — submitting from any other status is rejected with `ERR_APPLICATION_NOT_SUBMITTABLE`."

    Design: Corner/state_machines/resubmit_submitted_application_rejected
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    app = fixtures.create_submitted_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"], title="Resubmit app")
    assert app["status"] == "SUBMITTED"
    resp = api_client.submit_application(app["id"], make_applicant_headers(pi_a["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTABLE)
    assert fixtures.refresh_application(app["id"])["status"] == "SUBMITTED"


def test_referral_from_draft_rejected():
    """PRD §3.3: "The application must be `SUBMITTED` or `REFERRED` — referral from any other status is rejected with `ERR_APPLICATION_NOT_REFERRABLE`."
    The request here carries the application's current version, so only the
    state gate can fire (the OCC expectation is satisfied).

    Design: Corner/state_machines/referral_from_draft_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section DR")
    pi_a = fixtures.make_applicant()
    app = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"], title="Draft ref app")
    resp = api_client.refer_application(
        app["id"],
        factories.referral_payload(section["id"], ctx["institute"]["id"], app["version"]),
        _RO)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_REFERRABLE)
    assert fixtures.refresh_application(app["id"])["status"] == "DRAFT"


def test_re_referral_supersedes_and_moves_section_count():
    """PRD §3.3: "Re-referral is a first-class operation: referring an already-`REFERRED` application supersedes the prior placement under a `REFERRED` to `REFERRED` transition, subject to the same target-state checks, the same OCC expectation, and one additional guard — the application's `live_assignment_count` must be zero, because reviewers have not yet been assigned (`ERR_LIVE_ASSIGNMENTS_EXIST` otherwise)."
    PRD §3.3: "When the re-referral changes the section, the old section's `assigned_application_count` decrements and the new section's increments; the application's `version` increments again."

    Design: Corner/state_machines/re_referral_supersedes_and_moves_section_count
    """
    ctx = fixtures.make_review_context()
    sec_a = fixtures.make_study_section(name="Section A", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section B", meeting_date="2027-05-01T00:00:00Z")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        sec_a["id"], ctx["institute"]["id"], title="Re-ref app")
    assert app["status"] == "REFERRED"
    referred_version = app["version"]

    moved = fixtures.refer_application_current_version(
        app["id"], sec_b["id"], ctx["institute"]["id"],
        expected_application_version=referred_version)
    assert moved["status"] == "REFERRED"
    assert moved["study_section_id"] == sec_b["id"]
    assert moved["version"] == referred_version + 1, (
        "the application's version increments again on re-referral"
    )
    assert fixtures.refresh_study_section(sec_a["id"])["assigned_application_count"] == 0
    assert fixtures.refresh_study_section(sec_b["id"])["assigned_application_count"] == 1


def test_re_referral_with_live_assignment_rejected():
    """PRD §3.3: "Re-referral is a first-class operation: referring an already-`REFERRED` application supersedes the prior placement under a `REFERRED` to `REFERRED` transition, subject to the same target-state checks, the same OCC expectation, and one additional guard — the application's `live_assignment_count` must be zero, because reviewers have not yet been assigned (`ERR_LIVE_ASSIGNMENTS_EXIST` otherwise)."
    PRD §3.4: "an application must hold at least two live assignments to remain under review, so when a decline drops an `UNDER_REVIEW` application below two live assignments, the application automatically falls back from `UNDER_REVIEW` to `REFERRED`, increments its `version`, and must attract new assignments before it can be scored."

    Design: Corner/state_machines/re_referral_with_live_assignment_rejected
    """
    ctx = fixtures.make_review_context()
    sec_a = fixtures.make_study_section(name="Section A", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section B", meeting_date="2027-05-01T00:00:00Z")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        sec_a["id"], ctx["institute"]["id"], title="Live app")
    r1 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    r2 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    fixtures.assign_reviewer(app["id"], r1["id"], "PRIMARY")
    a_2 = fixtures.assign_reviewer(app["id"], r2["id"], "SECONDARY")
    # Decline drops live assignments 2 -> 1: the application falls back to
    # REFERRED but still holds one live assignment.
    fixtures.respond_to_assignment(a_2["id"], r2["id"], "DECLINE")
    current = fixtures.refresh_application(app["id"])
    assert current["status"] == "REFERRED"
    assert current["live_assignment_count"] == 1

    resp = api_client.refer_application(
        app["id"],
        factories.referral_payload(sec_b["id"], ctx["institute"]["id"], current["version"]),
        _RO)
    validate_error(resp, ApiErrorId.ERR_LIVE_ASSIGNMENTS_EXIST)
    after = fixtures.refresh_application(app["id"])
    assert after["study_section_id"] == sec_a["id"], "rejected re-referral must not move the section"


def test_stale_referral_version_rejected():
    """PRD §2.6: "When the supplied value no longer matches the application's current `version`, the referral is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412): the caller is acting on a stale view of the application's referral state."

    Design: Corner/validations/stale_referral_version_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section OCC")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_submitted_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"], title="OCC app")
    stale_version = app["version"] - 1
    resp = api_client.refer_application(
        app["id"],
        factories.referral_payload(section["id"], ctx["institute"]["id"], stale_version),
        _RO)
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION)
    after = fixtures.refresh_application(app["id"])
    assert after["status"] == "SUBMITTED"
    assert after["study_section_id"] is None


def test_owner_mismatch_submit_forbidden():
    """PRD §2.1: "An entity-backed caller acting on a resource owned by a different entity is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.7: "5. **Entity-backed ownership.** For owner-scoped operations — submission, withdrawal, JIT item submission, progress-report creation, modification creation, transfer proposal, reviewer respond, conflict declaration, assignment respond, and critique submission — the caller's `X-User-ID` must match the owning entity as described in §2.1 (`ERR_NOT_RESOURCE_OWNER`, HTTP 403)."

    Design: Corner/validations/owner_mismatch_submit_forbidden
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    pi_b = fixtures.make_applicant()
    app = fixtures.make_draft_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"], title="Owned app")
    resp = api_client.submit_application(app["id"], make_applicant_headers(pi_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert fixtures.refresh_application(app["id"])["status"] == "DRAFT"
