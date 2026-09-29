"""The consistency model: one call, and everything it touches is already true.

There are no background jobs in this contract, so the completion call — the
deepest money-and-calendar settlement in the system — must return a response that
already carries the final figures, and the four other rows it re-derives must read
back current on the very next request.
"""
from test_helpers import (
    PLACEMENT_COORDINATOR,
    SETTLEMENT_CLOCK,
    assert_date_equals,
    assert_instant_equals,
    assert_stipend,
    factories as f,
    read_agreement,
    read_assessment,
    read_candidate,
    read_request,
    set_clock,
    setup_passed_assessment,
    validate_success,
)

FINAL_WEEKLY_CENTS = 12962
FINAL_WEEKS_CREDITED = 14
FINAL_GROSS_CENTS = 183968
FINAL_TRAVEL_CENTS = 137886
SETTLEMENT_DATE = "2026-12-08"
STATE_REPORT_DEADLINE = "2027-01-21"
CUT_SCORE = 70


def test_the_completion_response_already_carries_the_final_settlement(api):
    """No second read is needed to see the FINAL money or the closed request.

    PRD §3.9: "Completion moves `ACTIVE → COMPLETED`, records `completed_at` as
    the logical-clock instant and `settlement_date` as the logical-clock date,
    flips `stipend_variant` to `FINAL` and recomputes `weeks_credited`,
    `stipend_weekly_cents`, `stipend_gross_cents` and `travel_reimbursement_cents`
    — with the 2500-cent premium ... The agreement's `stipend_committed_cents` is
    re-derived from the new gross, but its `seats_committed` is **unchanged** ...
    the owning request moves `MATCHED → CLOSED`, and the candidate's
    `state_report_deadline` becomes the closed request's `term_end_date` plus 45
    days."  PRD §2.4: "The system is immediately consistent: by the time a
    mutating call returns, every derived counter, every cascaded state and every
    recomputed money figure described in this document is already observable."

    Design: Corner/consistency model/the_completion_response_already_carries_the_final_settlement
    """
    scenario = setup_passed_assessment(api)
    set_clock(api, SETTLEMENT_CLOCK)

    completed = validate_success(api.complete_placement(
        scenario.placement_id, f.complete_placement_payload(),
        PLACEMENT_COORDINATOR))

    assert completed["placement_status"] == "COMPLETED"
    assert_stipend(completed, variant="FINAL", weekly_cents=FINAL_WEEKLY_CENTS,
                   weeks_credited=FINAL_WEEKS_CREDITED,
                   gross_cents=FINAL_GROSS_CENTS,
                   travel_cents=FINAL_TRAVEL_CENTS)
    assert_instant_equals(completed["completed_at"], SETTLEMENT_CLOCK,
                          "completed_at")
    assert_date_equals(completed["settlement_date"], SETTLEMENT_DATE,
                       "settlement_date")
    assert read_request(api, scenario.request_id)["status"] == "CLOSED"
    assert_date_equals(
        read_candidate(api, scenario.candidate_id)["state_report_deadline"],
        STATE_REPORT_DEADLINE, "state_report_deadline")
    agreement = read_agreement(api, scenario.agreement_id)
    assert agreement["stipend_committed_cents"] == FINAL_GROSS_CENTS
    assert agreement["seats_committed"] == 1, "a completed placement stays committed"
    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "PASSED"
    assert assessment["total_score"] == CUT_SCORE
