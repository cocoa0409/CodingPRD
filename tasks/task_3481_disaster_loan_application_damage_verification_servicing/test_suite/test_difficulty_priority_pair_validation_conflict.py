"""Difficulty queue: priority_pair_validation_conflict — pinned guard ordering."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    application_decision_payload,
    dispute_verification,
    set_clock,
    setup_application_in_decision_pending,
    setup_draft_application,
    validate_error,
    validate_success,
)


def test_decision_state_gate_beats_collateral_fiscal(api):
    """PRD §3.6: "Before any money is computed, a physical file must carry a settled loss figure: for a `PHYSICAL_DAMAGE` application, the latest damage verification must be in `COMPLETED` — a `DISPUTED` or otherwise open verification blocks approval with `ERR_VERIFICATION_REQUIRED` (HTTP 409)."
    PRD §3.6: "This state-family gate is evaluated before any fiscal check, so an open verification is reported as such rather than being masked by a collateral or affordability failure."
    PRD §2.6: "On application approval, the damage-verification state gate is evaluated before any fiscal check, so an open verification surfaces as `ERR_VERIFICATION_REQUIRED` rather than being masked by a collateral computation."

    Design: Difficulty/priority_pair_validation_conflict/decision_state_gate_beats_collateral_fiscal
    """
    # Setup: homeowner physical application (requested 20000000, so any approval
    # would exceed the 2500000 collateral threshold) in DECISION_PENDING, then
    # the applicant disputes the verification — legal pre-approval — leaving the
    # latest verification DISPUTED while the application sits DECISION_PENDING.
    ctx = setup_application_in_decision_pending()
    dispute_verification(ctx)
    app_id = ctx["application"]["id"]

    # Trigger: APPROVED decision with no collateral fields — the fiscal check
    # would also fail, but the state-family gate must be reported first.
    resp = api.decide_application(
        app_id, application_decision_payload(decision="APPROVED"),
        ctx["approver_headers"])
    error = validate_error(resp, ApiErrorId.ERR_VERIFICATION_REQUIRED)
    assert error["error_id"] == "ERR_VERIFICATION_REQUIRED"
    assert error["error_id"] != "ERR_COLLATERAL_REQUIRED"

    # Nothing moved: still DECISION_PENDING, no loan created.
    app = validate_success(api.get_application(app_id, ctx["approver_headers"]),
                           EXPECTED_SUCCESS_STATUS["get_application"])
    assert app["status"] == "DECISION_PENDING"
    assert app["loan_id"] is None


def test_submit_deadline_temporal_beats_county_referential(api):
    """PRD §3.2: "Then the purpose-specific deadline applies: a `PHYSICAL_DAMAGE` submission with the current instant strictly after the declaration's `physical_filing_deadline` is rejected with `ERR_PHYSICAL_FILING_CLOSED` (HTTP 422), and an `ECONOMIC_INJURY` submission strictly after the `economic_injury_filing_deadline` is rejected with `ERR_EIDL_FILING_CLOSED` (HTTP 422) — both deadlines inclusive of their exact instant."
    PRD §3.2: "Because eligibility is evaluated after the deadlines, a past-deadline submission to an ineligible county reports the deadline error."
    PRD §2.6: "On application submission, the purpose-specific filing-deadline checks are evaluated before county eligibility, so a late submission to an ineligible county reports the deadline error."

    Design: Difficulty/priority_pair_validation_conflict/submit_deadline_temporal_beats_county_referential
    """
    # Setup: DR-4821 covers counties 06037 and 06059 only; this DRAFT names
    # county 99999 (genuinely ineligible) for PHYSICAL_DAMAGE.
    ctx = setup_draft_application(county_fips="99999",
                                  requested_amount_cents=2500000)
    app_id = ctx["application"]["id"]

    # Trigger: one second past the physical filing deadline (2026-12-30).
    set_clock("2026-12-31T00:00:01Z", ctx["admin_headers"])
    resp = api.submit_application(app_id, ctx["applicant_headers"])
    error = validate_error(resp, ApiErrorId.ERR_PHYSICAL_FILING_CLOSED)
    # The temporal rule fires first; the county failure is never reported.
    assert error["error_id"] == "ERR_PHYSICAL_FILING_CLOSED"
    assert error["error_id"] != "ERR_COUNTY_NOT_ELIGIBLE"

    app = validate_success(api.get_application(app_id, ctx["applicant_headers"]),
                           EXPECTED_SUCCESS_STATUS["get_application"])
    assert app["status"] == "DRAFT"
