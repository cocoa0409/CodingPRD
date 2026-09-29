"""One annual test, and every consequence already visible in its own response.

The recapture, the exposure arithmetic and the recertification sweep all land
inside the request that caused them, and the immediate reads that follow can
only confirm what the response already said.
"""
from test_helpers import (
    REVIEWER_ANNUAL_USER_ID,
    SETUP_CLOCK,
    annual_test_payload,
    assert_cents,
    assert_instant,
    assert_pct,
    get_success_data,
    make_reviewer_headers,
    read_award,
    read_cba,
    read_qalicb,
    read_qei,
    read_qlici,
    set_clock,
    setup_at_risk_investment,
)

PLACEMENT_CENTS = 30_000_000
CURE_DEADLINE_AT = "2028-02-28T00:00:00.000Z"
YEAR_TWO_WINDOW_START = "2027-09-01T00:00:00.000Z"
YEAR_TWO_WINDOW_END = "2028-08-31T00:00:00.000Z"
EXPOSURE_AT_TWO_YEARS_CENTS = 10_600_000


def test_the_failing_test_reports_its_own_recapture_and_its_own_sweep(api):
    """A single write, and the sweep it triggered is in the same body.

    PRD: "A failing test against an investment *already* in `AT_RISK` whose
    `cure_deadline_at` the logical clock has passed is the end of the road: the
    investment moves to `RECAPTURED`, the test's `recapture_triggered` is set
    true, and `recapture_trigger_type` is set to `SUBSTANTIALLY_ALL_FAILURE` — or
    to `REINVESTMENT_BREACH` when the same test's `breached_obligation_count` is
    greater than 0, since returned capital left idle past its window is a
    different sin from capital that never qualified."

    PRD: "In every case the award's `at_risk_qei_count` and
    `recaptured_qei_count` are recomputed, its `compliance_posture` re-derived,
    and both the investment's and the award's `version` incremented."

    PRD: "Its `window_start_at` is the investment's `issued_at` advanced by 365
    days multiplied by one less than the requested year; its `window_end_at` is
    the `issued_at` advanced by 365 days multiplied by the requested year; and
    `window_days` is always 365 under the fixed-year convention."

    PRD: "The test is also the system's epoch boundary, and it performs three
    sweeps."

    PRD: "It sweeps every business funded by a qualifying sub-allocation of this
    investment out of `CERTIFIED` and into `RECERTIFICATION_DUE` when that
    business's `last_certified_at` lies strictly more than 365 days before the
    logical clock, counting them in `recertification_swept_qalicb_count`."

    PRD: "The order in which the test updates the investment is pinned as well:
    `compliance_years_completed` is set to the tested `compliance_year` **before**
    any recapture arithmetic runs, so an exposure computed in the same request
    reads the year just completed and not the year before it."

    PRD: "Otherwise the claimed amount is the gross `qei_amount_cents` multiplied
    by the ladder's basis points for the completed year count, divided by 10000
    and rounded half-up."

    PRD: "The `recapture_exposure_cents` is the claimed amount plus that interest
    — two independent roundings, never one combined multiplication."

    PRD: "If the allocatee's `certification_status` is `DECERTIFIED`, or the
    award has at least one investment whose `compliance_status` is `RECAPTURED`,
    the posture is `FROZEN`, which bars both new investment issuance and new
    sub-allocation deployment."

    PRD: "An agreement can also be breached from outside, when its business is
    disqualified by a second consecutive failed eligibility test, and it can be
    closed from outside, when its parent award's compliance period closes at
    settlement."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    scenario = setup_at_risk_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=135,
        principal_cents=PLACEMENT_CENTS,
    )
    warned = read_qei(api, scenario.qei["id"])
    assert warned["compliance_status"] == "AT_RISK"
    assert_instant(warned["cure_deadline_at"], CURE_DEADLINE_AT, "cure_deadline_at")
    assert warned["compliance_years_completed"] == 1

    set_clock(api, YEAR_TWO_WINDOW_END)
    reported = get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(2),
            make_reviewer_headers(REVIEWER_ANNUAL_USER_ID),
        )
    )
    assert reported["compliance_year"] == 2
    assert_instant(
        reported["window_start_at"], YEAR_TWO_WINDOW_START, "window_start_at"
    )
    assert_instant(reported["window_end_at"], YEAR_TWO_WINDOW_END, "window_end_at")
    assert reported["window_days"] == 365
    assert_pct(reported["measured_pct_direct"], 31.58, "measured_pct_direct")
    assert reported["result"] == "FAIL"
    assert reported["recapture_triggered"] is True
    assert reported["breached_obligation_count"] == 0
    assert reported["recertification_swept_qalicb_count"] == 1, (
        "the sweep is reported by the request that performed it"
    )

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "RECAPTURED"
    assert qei["compliance_years_completed"] == 2
    assert qei["recapture_trigger_type"] == "SUBSTANTIALLY_ALL_FAILURE"
    assert_cents(
        qei["recapture_exposure_cents"],
        EXPOSURE_AT_TWO_YEARS_CENTS,
        "recapture_exposure_cents",
    )

    business = read_qalicb(api, scenario.qalicb["id"])
    assert business["eligibility_status"] == "RECERTIFICATION_DUE"

    award = read_award(api, scenario.award["id"])
    assert award["recaptured_qei_count"] == 1
    assert award["at_risk_qei_count"] == 0
    assert award["compliance_posture"] == "FROZEN"

    agreement = read_cba(api, scenario.cba["id"])
    assert agreement["status"] == "ACTIVE", "recapture never touches the agreement"

    placement = read_qlici(api, scenario.qlici["id"])
    assert placement["status"] == "DEPLOYED"
    assert_cents(
        placement["outstanding_principal_cents"],
        PLACEMENT_CENTS,
        "outstanding_principal_cents",
    )
