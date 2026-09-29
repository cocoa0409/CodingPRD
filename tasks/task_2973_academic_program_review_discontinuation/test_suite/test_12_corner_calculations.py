"""Corner cases in the derived arithmetic: viability composite, rolling window,
the small-program ceiling, severance-cap truncation, statutory notice pay and the
agency-notice deadline sweep."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_hr_partner_headers,
    make_provost_proposer_headers,
    make_review_coordinator_headers,
)

# --- Fixture A (§3.1 / §3.2), one term at a time ----------------------------
# term 1: 30 heads, 300 credit hours, 12,000,000 cents, 4 completions, demand 42
# term 2: 24 heads, 240 credit hours, 11,000,000 cents, 3 completions, demand 40
# term 3: 20 heads, 200 credit hours, 11,000,000 cents, 2 completions, demand 42
TERM_1, TERM_2, TERM_3 = constants.FIXTURE_A_SNAPSHOTS


def _snapshot(api, program_id, payload):
    """Append one observation and return the 201 body's data."""
    return validate_success(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(**payload),
            make_review_coordinator_headers(),
        ),
        201,
    )


def test_viability_composite_matches_the_four_factor_weighted_sum(api):
    """The composite is rebuilt from scratch on every snapshot write.

    §3.2's four factors are recomputed over the whole rolling window on each
    append, the enrollment factor clamps at 0 instead of going negative, and the
    small-program ceiling of 39.99 stops applying by itself once the window's
    headcount reaches 60. After term 1 the earned sum is 49.2333... but the
    window holds only 30 heads, so the ceiling drops it to 39.99 — which is
    below the 40.00 improvement bound and therefore bands the program NONVIABLE.
    After term 3 the window holds 74 heads and the earned 29.0601... stands.

    Design: Corner/calculations/viability_composite_matches_the_four_factor_weighted_sum
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]

    # --- term 1 -----------------------------------------------------------
    snapshot_1 = _snapshot(api, program_id, TERM_1)
    assert snapshot_1["cost_per_credit_hour_cents"] == 40000, (
        "§3.1 per-term diagnostic: round_half_up(12000000 / 300)"
    )
    after_first = fixtures.read_program(api, program_id)
    assert after_first["snapshot_count"] == 1
    # enrollment 50.00 (flat window) x 0.35 + completion 33.3333... x 0.25
    # + demand 42 x 0.20 + efficiency 75.00 x 0.20 = 49.2333..., ceilinged to
    # 39.99 because the window enrolled only 30 of the 60 heads §3.2 requires.
    assertions.assert_viability(after_first, 40000, 40000, 39.99, "NONVIABLE")

    # --- term 2 -----------------------------------------------------------
    snapshot_2 = _snapshot(api, program_id, TERM_2)
    assert snapshot_2["cost_per_credit_hour_cents"] == 45833, (
        "§3.1 per-term diagnostic: round_half_up(11000000 / 240)"
    )
    after_second = fixtures.read_program(api, program_id)
    assert after_second["snapshot_count"] == 2
    # rolling = round_half_up(23000000 / 540) = 42593, latest = 45833.
    # enrollment clamps to 0 (a -20% trend gives 50 - 50), completion
    # 32.4074..., demand 40 from term 2 alone, efficiency 70.4341... ->
    # 30.1886..., already under the 39.99 ceiling so the override is inert.
    assertions.assert_viability(after_second, 42593, 45833, 30.19, "NONVIABLE")

    # --- term 3 -----------------------------------------------------------
    snapshot_3 = _snapshot(api, program_id, TERM_3)
    assert snapshot_3["cost_per_credit_hour_cents"] == 55000, (
        "§3.1 per-term diagnostic: round_half_up(11000000 / 200)"
    )
    after_third = fixtures.read_program(api, program_id)
    assert after_third["snapshot_count"] == 3
    # enrollment_score 0 x 0.35 (clamped up from -33.33), completion_score
    # 30.4054... x 0.25, demand_score 42 x 0.20 from term 3 only, and
    # efficiency_score 65.2940... x 0.20 = 29.0601... -> 29.06. NOT 39.99: the
    # window now enrols 74 heads, so §3.2's small-program override is off.
    assertions.assert_viability(
        after_third,
        constants.FIXTURE_A_ROLLING_CPH_CENTS,
        constants.FIXTURE_A_LATEST_CPH_CENTS,
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        constants.FIXTURE_A_BAND,
    )

    # The stored value is what a later read returns; §2.7 recomputes on write.
    on_read = validate_success(
        api.get_program(program_id, make_provost_proposer_headers())
    )
    assertions.assert_decimal_equals(
        on_read["composite_score"], 29.06, "composite_score on read"
    )
    assert on_read["viability_band"] == "NONVIABLE"


def test_rolling_window_drops_the_oldest_term_when_a_fourth_snapshot_lands(api):
    """A fourth observation evicts term 1 from every program-level rollup.

    §3.1's rolling window is the three highest `term_index` observations, so the
    program-level figures move to terms 2-4 while the term-1 row itself is
    untouched and still carries its own diagnostic. A rollup over all four
    snapshots would give 43000 cents per credit hour; the window gives 48438.

    Design: Corner/calculations/rolling_window_drops_the_oldest_term_when_a_fourth_snapshot_lands
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    created = fixtures.append_snapshots(api, program_id, constants.FIXTURE_A_SNAPSHOTS)
    snapshot_1_id = created[0]["id"]

    before = fixtures.read_program(api, program_id)
    assertions.assert_viability(
        before,
        constants.FIXTURE_A_ROLLING_CPH_CENTS,
        constants.FIXTURE_A_LATEST_CPH_CENTS,
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        constants.FIXTURE_A_BAND,
    )

    # --- the fourth observation -------------------------------------------
    snapshot_4 = _snapshot(
        api,
        program_id,
        {
            "term_code": "2027SP",
            "term_index": 4,
            "enrollment_headcount": 20,
            "credit_hours": 200,
            "direct_cost_cents": 9000000,
            "completions_count": 2,
            "market_demand_index": 42,
        },
    )
    assert snapshot_4["cost_per_credit_hour_cents"] == 45000

    after = fixtures.read_program(api, program_id)
    assert after["snapshot_count"] == 4, "nothing is ever deleted (§3.1)"
    # rolling = round_half_up(31000000 / 640) = 48438 over terms 2-4 only;
    # 34000000+9000000 over 940 hours would give 43000 and is wrong.
    # composite from window headcount 64: enrollment 8.3333... (a -16.6667%
    # trend from term 2 to term 4), completion 27.34375, demand 42,
    # efficiency 61.9348... -> 30.5395... -> 30.54.
    assertions.assert_viability(after, 48438, 45000, 30.54, "NONVIABLE")

    rows, meta = validate_paginated(
        api.list_metric_snapshots(program_id, make_review_coordinator_headers())
    )
    assert meta["total_count"] == 4
    by_id = {row["id"]: row for row in rows}
    assert by_id[snapshot_1_id]["cost_per_credit_hour_cents"] == 40000, (
        "the evicted row keeps its own per-term diagnostic"
    )
    assert by_id[snapshot_4["id"]]["cost_per_credit_hour_cents"] == 45000


def test_small_program_floor_applies_at_59_heads_and_not_at_60(api):
    """Two identical programs, one head apart, land in different bands.

    §3.2's small-program test is a strict `<` against 60 heads in the rolling
    window: a window of exactly 60 keeps its earned 80.50 and bands
    CONTINUE_ELIGIBLE, while a window of 59 is replaced by the 39.99 ceiling —
    which is below the 40.00 improvement bound, so the ceiling drops an
    otherwise strong program straight into NONVIABLE.

    Design: Corner/calculations/small_program_floor_applies_at_59_heads_and_not_at_60
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    big = fixtures.create_program(
        api,
        code="BIG-BA",
        name="Big Program BA",
        degree_level="UNDERGRADUATE",
        department_code="BIG",
    )
    small = fixtures.create_program(
        api,
        code="SML-BA",
        name="Small Program BA",
        degree_level="UNDERGRADUATE",
        department_code="SML",
    )

    def terms(headcounts):
        return [
            {
                "term_code": code,
                "term_index": index,
                "enrollment_headcount": heads,
                "credit_hours": 300,
                "direct_cost_cents": 3000000,
                "completions_count": completions,
                "market_demand_index": 90,
            }
            for code, index, heads, completions in zip(
                ("2025FA", "2026SP", "2026FA"), (1, 2, 3), headcounts, (13, 13, 14)
            )
        ]

    fixtures.append_snapshots(api, big["id"], terms((20, 20, 20)))
    fixtures.append_snapshots(api, small["id"], terms((20, 20, 19)))

    big_after = fixtures.read_program(api, big["id"])
    small_after = fixtures.read_program(api, small["id"])

    # BIG-BA: window headcount is exactly 60, so no ceiling applies.
    # enrollment 50 x 0.35 + completion 100 x 0.25 (clamped from 166.67)
    # + demand 90 x 0.20 + efficiency 100 x 0.20 (clamped from 300) = 80.50.
    assertions.assert_viability(big_after, 10000, 10000, 80.50, "CONTINUE_ELIGIBLE")

    # SML-BA: window headcount 59, and the earned sum would have been 76.125
    # (enrollment 37.50 from the -5% trend, completion 100, demand 90,
    # efficiency 100). The stored value must be the 39.99 ceiling.
    assertions.assert_viability(small_after, 10000, 10000, 39.99, "NONVIABLE")
    assertions.assert_decimal_equals(
        small_after["composite_score"],
        constants.SMALL_PROGRAM_SCORE_CEILING,
        "SML-BA composite_score",
    )

    # §3.11 step 3 on the same window: floor(0.15 x 9000000).
    for program in (big_after, small_after):
        assert program["severance_budget_cap_cents"] == 1350000


def test_severance_cap_floors_the_fraction_instead_of_rounding_half_up(api):
    """One window, two rounding modes: the cap truncates, the quotient half-ups.

    §2.7 and §3.11 step 3 truncate the severance ceiling downward to whole
    cents, so 0.15 x 34,000,010 = 5,100,001.5 becomes 5,100,001 and never
    5,100,002 — while the same window's cost-per-credit-hour quotient is still
    rounded half up.

    Design: Corner/calculations/severance_cap_floors_the_fraction_instead_of_rounding_half_up
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    nudged = [dict(TERM_1, direct_cost_cents=12000010), dict(TERM_2), dict(TERM_3)]
    created = fixtures.append_snapshots(api, program_id, nudged)

    appointment = validate_success(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(
                faculty_number="F-ADJ-1",
                tenure_status="ADJUNCT",
                fte=0.25,
                annual_salary_cents=4000000,
            ),
            make_hr_partner_headers(),
        ),
        201,
    )

    after = fixtures.read_program(api, program_id)
    assert after["severance_budget_cap_cents"] == 5100001, (
        "floor(0.15 x 34000010); 5100002 is round_half_up and is wrong"
    )
    # The same 34,000,010-cent window still rounds its quotient half up:
    # 34000010 / 740 = 45945.9594... -> 45946.
    assertions.assert_viability(
        after,
        constants.FIXTURE_A_ROLLING_CPH_CENTS,
        constants.FIXTURE_A_LATEST_CPH_CENTS,
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        constants.FIXTURE_A_BAND,
    )
    assert created[0]["cost_per_credit_hour_cents"] == 40000, (
        "round_half_up(12000010 / 300) = 40000.0333... -> 40000"
    )

    # round_half_up(4000000 x 0.25 x 30 / 365) = 82191.78... -> 82192, which
    # fits inside the 5,100,001-cent ceiling, so the walk funds position 1.
    assert appointment["notice_pay_cents"] == 82192
    assert appointment["reduction_sequence_position"] == 1
    assertions.assert_waterfall(
        after,
        baseline=0.25,
        assigned_pool=0.25,
        retained=0.00,
        reducible=0.25,
        severance_cap_cents=5100001,
        liability_cents=82192,
        deferred=0.00,
    )


def test_notice_pay_applies_statutory_notice_days_per_tenure_status(api):
    """All four statutory notice lengths are observable on an unfunded roster.

    §3.11 prices `notice_pay_cents` for every appointment in the order *before*
    the walk runs, so a program whose cost window is empty — and whose severance
    ceiling is therefore 0 — populates all four figures while funding nobody:
    every `reduction_sequence_position` stays null. The 365-day divisor makes
    three of the four amounts non-round.

    Design: Corner/calculations/notice_pay_applies_statutory_notice_days_per_tenure_status
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]

    adjunct = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )
    non_tenure_track = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-NTT-1",
        tenure_status="NON_TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=7200000,
    )
    tenure_track = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TT-1",
        tenure_status="TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=9000000,
    )
    tenured = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=12000000,
    )

    # round_half_up(annual_salary_cents x fte x statutory_days / 365)
    assert adjunct["notice_pay_cents"] == 82192, "30 ADJUNCT days: 82191.78... -> 82192"
    assert non_tenure_track["notice_pay_cents"] == 1775342, "90 days: 1775342.46..."
    assert tenure_track["notice_pay_cents"] == 4438356, "180 days: 4438356.16..."
    assert tenured["notice_pay_cents"] == 12000000, "365 days: exactly one year"

    appointments = fixtures.list_appointments(api, program_id)
    assert len(appointments) == 4
    for row in appointments:
        assert row["reduction_sequence_position"] is None, (
            "a 0-cent ceiling breaks the walk before the first ADJUNCT is funded"
        )

    after = fixtures.read_program(api, program_id)
    # An empty rolling cost window sums to 0 cents, so 15% of it truncates to 0.
    assertions.assert_waterfall(
        after,
        baseline=3.25,
        assigned_pool=3.25,
        retained=0.00,
        reducible=3.25,
        severance_cap_cents=0,
        liability_cents=0,
        deferred=3.25,
    )


def test_overdue_sweep_marks_only_strictly_past_due_notices(api):
    """A sweep at exactly `due_at` expires nothing; one second later it does.

    §3.7's overdue comparison is strictly greater than `due_at`. Both auto-minted
    deadlines anchor on the decision's `ratified_at` of 2026-09-15T10:00:00Z and
    preserve its time of day exactly: the 30-day accreditor notice falls due at
    2026-10-15T10:00:00Z and the 45-day state notice at 2026-10-30T10:00:00Z, so
    the state notice is untouched on the day the accreditor notice expires. An
    OVERDUE notice is still an unacknowledged one.

    Design: Corner/calculations/overdue_sweep_marks_only_strictly_past_due_notices
    """
    ctx = fixtures.setup_ratified_discontinuation(api)
    ratified_at = ctx.decision["ratified_at"]
    assertions.assert_instant_equals(
        ratified_at, fixtures.CLOCK_AT_RATIFICATION, "decision.ratified_at"
    )

    notices = fixtures.list_notifications(api, ctx.decision["id"])
    assert len(notices) == 2
    accreditor = next(n for n in notices if n["agency_type"] == "ACCREDITOR")
    state_agency = next(n for n in notices if n["agency_type"] == "STATE_AGENCY")
    assert accreditor["agency_code"] == constants.AUTO_MINTED_ACCREDITOR_CODE
    assert state_agency["agency_code"] == constants.AUTO_MINTED_STATE_AGENCY_CODE
    accreditor_due_at = assertions.add_days(ratified_at, 30)
    assertions.assert_instant_equals(
        accreditor["due_at"], accreditor_due_at, "ACCREDITOR.due_at"
    )
    assertions.assert_instant_equals(
        state_agency["due_at"],
        assertions.add_days(ratified_at, 45),
        "STATE_AGENCY.due_at",
    )

    # --- sweep 1: the clock sits exactly on the accreditor deadline --------
    fixtures.set_clock(api, accreditor_due_at)
    first = validate_success(
        api.run_compliance_sweep(make_review_coordinator_headers())
    )
    assertions.assert_instant_equals(first["swept_at"], accreditor_due_at, "swept_at")
    assert first["marked_overdue_count"] == 0, "equality does not expire a notice"
    assert first["marked_overdue_notification_ids"] == []
    for notice in fixtures.list_notifications(api, ctx.decision["id"]):
        assert notice["status"] == "PENDING"
        assert notice["overdue_marked_at"] is None

    # --- sweep 2: one second later ----------------------------------------
    one_second_late = assertions.add_seconds(accreditor_due_at, 1)
    fixtures.set_clock(api, one_second_late)
    second = validate_success(
        api.run_compliance_sweep(make_review_coordinator_headers())
    )
    assert second["marked_overdue_count"] == 1
    assert second["marked_overdue_notification_ids"] == [accreditor["id"]]

    swept = {n["id"]: n for n in fixtures.list_notifications(api, ctx.decision["id"])}
    assert swept[accreditor["id"]]["status"] == "OVERDUE"
    assertions.assert_instant_equals(
        swept[accreditor["id"]]["overdue_marked_at"], one_second_late, "overdue_marked_at"
    )
    assert swept[state_agency["id"]]["status"] == "PENDING"
    assert swept[state_agency["id"]]["overdue_marked_at"] is None

    # §3.7: the sweep touches neither counter nor posture.
    decision = fixtures.read_decision(api, ctx.decision["id"])
    assert decision["unacknowledged_notification_count"] == 2
    cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert cycle["compliance_posture"] == "NOTICES_PENDING"


def test_manual_notice_on_an_unratified_decision_anchors_due_at_on_the_clock(api):
    """With `ratified_at` still null the deadline anchors on the logical clock.

    §3.7's anchor is the decision's `ratified_at` when that stamp exists and the
    current clock instant otherwise. On a decision still in PROPOSED, the manual
    FEDERAL notice's 60-day offset must therefore run from 2026-09-20T08:30:00Z —
    the clock five days after the proposal — giving 2026-11-19T08:30:00Z, not
    from the proposal instant and not from the decision's `created_at`. The row
    is MANUAL, and it makes an unratified decision start carrying an
    unacknowledged notice, which is how `compliance_posture` becomes
    NOTICES_PENDING before ratification.

    Design: Corner/calculations/manual_notice_on_an_unratified_decision_anchors_due_at_on_the_clock
    """
    ctx = fixtures.carry_cycle_to_response_submitted(api)
    fixtures.set_clock(api, "2026-09-15T10:00:00Z")
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert decision["state"] == "PROPOSED"
    assert decision["ratified_at"] is None

    clock_at_filing = "2026-09-20T08:30:00Z"
    fixtures.set_clock(api, clock_at_filing)

    notice = validate_success(
        api.create_agency_notification(
            decision["id"],
            factories.agency_notification_payload(
                agency_type="FEDERAL", agency_code="USDOE"
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert notice["status"] == "PENDING"
    assert notice["origin"] == "MANUAL"
    assert notice["agency_code"] == "USDOE"
    assert notice["agency_type"] == "FEDERAL"
    # 2026-09-20T08:30:00Z + 60 x 24h = 2026-11-19T08:30:00Z.
    assertions.assert_instant_equals(
        notice["due_at"], assertions.add_days(clock_at_filing, 60), "FEDERAL.due_at"
    )
    assertions.assert_instant_equals(
        notice["due_at"], "2026-11-19T08:30:00Z", "FEDERAL.due_at"
    )
    assert notice["sent_at"] is None
    assert notice["acknowledged_at"] is None
    assert notice["transmitted_reference"] is None
    assert notice["overdue_marked_at"] is None

    # Filing a notice is not a transition on the decision.
    after = fixtures.read_decision(api, decision["id"])
    assert after["state"] == "PROPOSED"
    assert after["ratified_at"] is None
    assert after["notification_count"] == 1
    assert after["unacknowledged_notification_count"] == 1

    cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert cycle["compliance_posture"] == "NOTICES_PENDING"
