"""Difficulty queue: cross_entity_state_dependency — gates on sibling state."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    create_draft,
    read_loan,
    set_clock,
    setup_draft_application,
    setup_loan_with_t1_released,
    validate_error,
    validate_success,
    verify_milestone,
)


def test_submit_gated_by_declaration_purpose_deadlines(api):
    """PRD §3.1: "A `PHYSICAL_DAMAGE` submission is accepted while the current logical instant is on or before the physical deadline — the deadline instant itself is inclusive — and an `ECONOMIC_INJURY` submission is accepted while the current instant is on or before the economic-injury deadline, likewise inclusive."
    PRD §2.4: "Each declaration's `status` is advanced to match the new instant: `OPEN` while the current instant is on or before `physical_filing_deadline`; `PHYSICAL_CLOSED` once the current instant is strictly after `physical_filing_deadline` but still on or before `economic_injury_filing_deadline`; `FULLY_CLOSED` once the current instant is strictly after `economic_injury_filing_deadline`."
    PRD §3.2: "Then the purpose-specific deadline applies: a `PHYSICAL_DAMAGE` submission with the current instant strictly after the declaration's `physical_filing_deadline` is rejected with `ERR_PHYSICAL_FILING_CLOSED` (HTTP 422), and an `ECONOMIC_INJURY` submission strictly after the `economic_injury_filing_deadline` is rejected with `ERR_EIDL_FILING_CLOSED` (HTTP 422) — both deadlines inclusive of their exact instant."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_declaration_purpose_deadlines
    """
    # Setup: DR-4821 declared 2026-10-01 (physical deadline 2026-12-30,
    # economic-injury deadline 2027-06-28). Three DRAFT applications from one
    # homeowner: A physical 06037, B physical 06037, C economic-injury 06059.
    ctx = setup_draft_application(requested_amount_cents=2500000)
    app_a_id = ctx["application"]["id"]
    app_b = create_draft(ctx, county_fips="06037",
                         loan_purpose="PHYSICAL_DAMAGE",
                         requested_amount_cents=2500000)
    app_c = create_draft(ctx, county_fips="06059",
                         loan_purpose="ECONOMIC_INJURY",
                         requested_amount_cents=2500000)

    # At exactly the physical deadline: A submits — the instant is inclusive.
    set_clock("2026-12-30T00:00:00Z", ctx["admin_headers"])
    resp = api.submit_application(app_a_id, ctx["applicant_headers"])
    submitted = validate_success(resp, EXPECTED_SUCCESS_STATUS["submit_application"])
    assert submitted["status"] == "SUBMITTED"

    # One second later the declaration has rolled to PHYSICAL_CLOSED: B fails.
    set_clock("2026-12-30T00:00:01Z", ctx["admin_headers"])
    resp = api.submit_application(app_b["id"], ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_PHYSICAL_FILING_CLOSED)
    app_b_after = validate_success(
        api.get_application(app_b["id"], ctx["applicant_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert app_b_after["status"] == "DRAFT"

    # At that same instant C still submits: the EIDL deadline gates it open.
    resp = api.submit_application(app_c["id"], ctx["applicant_headers"])
    submitted_c = validate_success(resp, EXPECTED_SUCCESS_STATUS["submit_application"])
    assert submitted_c["status"] == "SUBMITTED"


def test_tranche_release_gated_by_milestone_verification(api):
    """PRD §3.7: "A `ServicingAgent` releases a tranche, which requires the tranche to be `ELIGIBLE` — anything else, including an out-of-order release attempt or one whose verified-cost coverage is insufficient, is rejected with `ERR_TRANCHE_NOT_RELEASABLE` — and the loan's `lifecycle_status` to be `ACTIVE`, else `ERR_LOAN_NOT_ACTIVE`."
    PRD §3.7: "Eligibility is computed by walking the schedule in ascending `stage_number`: stage 1 is eligible exactly when the loan is `ACTIVE`, and each later stage becomes eligible when every earlier stage is `RELEASED` and the cumulative `verified_cost_cents` over the loan's `VERIFIED` milestones is at least the sum of the `amount_cents` of all earlier stages — equality at that boundary suffices."
    PRD §3.7: "On release the tranche's `released_at` is stamped with the current instant, the loan's `disbursed_total_cents` and `outstanding_balance_cents` each increase by the released amount, and the loan's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/tranche_release_gated_by_milestone_verification
    """
    # Setup: homeowner loan approved 20000000, accepted 2026-11-01, T1
    # (2500000) released; stage 2 (8750000) still SCHEDULED (verified total 0).
    ctx = setup_loan_with_t1_released()
    t2_id = ctx["tranches"][1]["id"]

    # The release fails while zero milestone cost is VERIFIED.
    resp = api.release_tranche(t2_id, ctx["servicing_headers"])
    validate_error(resp, ApiErrorId.ERR_TRANCHE_NOT_RELEASABLE)

    # A milestone VERIFIED at exactly the stage-1 amount flips eligibility.
    verify_milestone(ctx, claimed_cost_cents=2500000)

    # The identical release call now succeeds.
    resp = api.release_tranche(t2_id, ctx["servicing_headers"])
    released = validate_success(resp, EXPECTED_SUCCESS_STATUS["release_tranche"])
    assert released["status"] == "RELEASED"

    loan = read_loan(ctx)
    assert loan["disbursed_total_cents"] == 11250000
    assert loan["outstanding_balance_cents"] == 11250000
