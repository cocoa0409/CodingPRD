"""Boundaries probed from both sides at the precision the contract states.

An ISO-8601 instant held to the second, an aggregate gallons-per-minute rate at one
decimal place, and a four-decimal ratio against an inclusive-from-below tier table.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_WELDER_NOT_QUALIFIED,
    ERR_WITHDRAWAL_CAPACITY_CONFLICT,
)
from test_helpers.assertions import assert_instant, assert_source_ledger
from test_helpers.constants import (
    BASE_EXAMINATION_PCT,
    COURSE_FITTED,
    DECISION_ACCEPT,
    DECISION_REJECT,
    DEFAULT_CONTINUITY_LIMIT_DAYS,
    DEFECT_POROSITY,
    DISPOSAL_REUSE_NEXT_TANK,
    ESCALATED_EXAMINATION_PCT,
    POSTURE_RESTRICTED,
    SEAM_FIT_READY,
    SEAM_RT_ACCEPTED,
    SEAM_RT_REJECTED,
    SEAM_WELDED,
    WELDER_LAPSED,
    WELDER_QUALIFIED,
    WITHDRAWAL_RESERVED,
)
from test_helpers.assertions import assert_reject_rate, assert_tank_state
from test_helpers.test_users import ES1, welder_headers

CONTINUITY_EXPIRY = "2026-11-28T00:00:00Z"
ONE_SECOND_LATE = "2026-11-28T00:00:01Z"
REFRESHED_EXPIRY = "2027-05-27T00:00:00Z"


class TestWelderContinuityExpiryInstantIsInclusive:
    def _two_welders_and_two_unwelded_seams(self, api):
        ctx = X.erecting_tank(api)
        ctx.welder_a = X.create_welder(
            api, welder_stamp="W-07", continuity_limit_days=DEFAULT_CONTINUITY_LIMIT_DAYS
        )
        ctx.welder_b = X.create_welder(
            api, welder_stamp="W-08", full_name="T. Okafor",
            continuity_limit_days=DEFAULT_CONTINUITY_LIMIT_DAYS,
        )
        ctx.seam_a = X.create_seam(api, ctx.course_id, "V1", 1)
        ctx.seam_b = X.create_seam(api, ctx.course_id, "V2", 2)
        return ctx

    def test_the_continuity_window_is_the_qualification_date_plus_the_limit(self, api):
        """A welder qualified 2026-06-01 with a 180-day limit expires 2026-11-28T00:00:00Z.

        PRD: "`continuity_expires_at_utc` is that base date advanced by
        `continuity_limit_days` days and is held to the second"

        Design: Difficulty/boundary_precision_check/welder_continuity_expiry_instant_inclusive
        """
        ctx = self._two_welders_and_two_unwelded_seams(api)

        for welder in (ctx.welder_a, ctx.welder_b):
            assert_instant(welder["continuity_expires_at_utc"], CONTINUITY_EXPIRY, "expiry")
            assert_instant(
                welder["last_weld_date_utc"], "2026-06-01T00:00:00Z", "last weld date"
            )
            assert welder["qualification_status"] == WELDER_QUALIFIED

    def test_a_weld_exactly_at_the_expiry_instant_is_accepted_and_resets_the_curve(self, api):
        """The boundary is inclusive in the welder's favour.

        PRD: "The boundary is inclusive in the welder's favour: exactly at
        `continuity_expires_at_utc` the welder is still `QUALIFIED`, and one second
        later they are `LAPSED`."

        Design: Difficulty/boundary_precision_check/welder_continuity_expiry_instant_inclusive
        """
        ctx = self._two_welders_and_two_unwelded_seams(api)
        X.set_clock(api, CONTINUITY_EXPIRY)

        seam = X.weld(api, ctx.seam_a["id"], ctx.welder_a["id"])

        assert seam["status"] == SEAM_WELDED
        assert_instant(seam["welded_at_utc"], CONTINUITY_EXPIRY, "welded_at_utc")

        welder = X.read_welder(api, ctx.welder_a["id"])
        assert welder["qualification_status"] == WELDER_QUALIFIED
        assert_instant(welder["last_weld_date_utc"], CONTINUITY_EXPIRY, "last weld date")
        assert_instant(welder["continuity_expires_at_utc"], REFRESHED_EXPIRY, "refreshed expiry")

    def test_a_weld_one_second_past_the_expiry_is_refused_and_lapses_the_welder(self, api):
        """One second past the instant the same welder may no longer weld.

        PRD: "a welder whose `continuity_expires_at_utc` is strictly before the
        logical clock moves `QUALIFIED → LAPSED`"

        Design: Difficulty/boundary_precision_check/welder_continuity_expiry_instant_inclusive
        """
        ctx = self._two_welders_and_two_unwelded_seams(api)
        X.set_clock(api, ONE_SECOND_LATE)

        validate_error(
            api.weld_log(
                ctx.seam_b["id"],
                {"welder_id": ctx.welder_b["id"]},
                welder_headers(ctx.welder_b["id"]),
            ),
            ERR_WELDER_NOT_QUALIFIED,
        )

        welder = X.read_welder(api, ctx.welder_b["id"])
        assert welder["qualification_status"] == WELDER_LAPSED
        assert_instant(welder["last_weld_date_utc"], "2026-06-01T00:00:00Z", "last weld date")

        seam = X.read_seam(api, ctx.seam_b["id"])
        assert seam["status"] == SEAM_FIT_READY
        assert seam["welder_id"] is None


class TestWithdrawalAggregateRateAtTheCeiling:
    def _source_holding_two_overlapping_windows(self, api):
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        source = X.create_water_source(
            api, permitted_volume_gal=5000000.0, max_concurrent_rate_gpm=900.0
        )
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=400000.0,
                             disposal_method=DISPOSAL_REUSE_NEXT_TANK)
        for _ in range(2):
            X.reserve_withdrawal(
                api, plan["id"], source["id"], "2026-08-11T00:00:00Z",
                "2026-08-11T12:00:00Z", 300.0, 100000.0,
            )
        return source["id"], plan["id"]

    def test_an_overlapping_peak_exactly_at_the_ceiling_is_accepted(self, api):
        """Three overlapping 300 gpm windows reach exactly the 900 gpm limit.

        PRD: "That peak figure, carried to 1 decimal place rounded half up, may
        not exceed the source's `max_concurrent_rate_gpm`; exactly at the ceiling
        the reservation is accepted"

        Design: Difficulty/boundary_precision_check/withdrawal_aggregate_rate_exactly_at_permit_ceiling
        """
        source_id, plan_id = self._source_holding_two_overlapping_windows(api)

        third = X.reserve_withdrawal(
            api, plan_id, source_id, "2026-08-11T06:00:00Z", "2026-08-11T18:00:00Z",
            300.0, 100000.0,
        )

        assert third["status"] == WITHDRAWAL_RESERVED
        source = X.read_water_source(api, source_id)
        assert_source_ledger(source, reserved=300000.00, consumed=0.00, available=4700000.00)

    def test_a_tenth_of_a_gallon_past_the_ceiling_is_refused(self, api):
        """A 0.1 gpm window overlapping all three pushes the peak to 900.1 gpm.

        PRD: "and above it the request is rejected with
        `ERR_WITHDRAWAL_CAPACITY_CONFLICT`."

        Design: Difficulty/boundary_precision_check/withdrawal_aggregate_rate_exactly_at_permit_ceiling
        """
        source_id, plan_id = self._source_holding_two_overlapping_windows(api)
        X.reserve_withdrawal(
            api, plan_id, source_id, "2026-08-11T06:00:00Z", "2026-08-11T18:00:00Z",
            300.0, 100000.0,
        )

        validate_error(
            api.create_water_withdrawal(
                {
                    "hydrotest_plan_id": plan_id,
                    "water_source_id": source_id,
                    "window_start_utc": "2026-08-11T11:59:59Z",
                    "window_end_utc": "2026-08-11T20:00:00Z",
                    "rate_gpm": 0.1,
                    "reserved_volume_gal": 1000.0,
                    "expected_water_source_version": X.source_version(api, source_id),
                },
                ES1,
            ),
            ERR_WITHDRAWAL_CAPACITY_CONFLICT,
        )

    def test_a_window_that_starts_exactly_when_another_ends_contributes_nothing(self, api):
        """Half-open semantics let a full 900 gpm window abut the previous one.

        PRD: "that is, the existing window starts strictly before the proposed end
        and the proposed start is strictly before the existing end"

        Design: Difficulty/boundary_precision_check/withdrawal_aggregate_rate_exactly_at_permit_ceiling
        """
        source_id, plan_id = self._source_holding_two_overlapping_windows(api)
        X.reserve_withdrawal(
            api, plan_id, source_id, "2026-08-11T06:00:00Z", "2026-08-11T18:00:00Z",
            300.0, 100000.0,
        )

        abutting = X.reserve_withdrawal(
            api, plan_id, source_id, "2026-08-11T18:00:00Z", "2026-08-11T23:00:00Z",
            900.0, 100000.0,
        )

        assert abutting["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, source_id),
            reserved=400000.00, consumed=0.00, available=4600000.00,
        )


class TestWeldRejectRateAtTheEscalationBoundary:
    def _four_accepted_examinations_and_a_fifth_window(self, api):
        """Five welded seams, three accepted radiographs and two open windows."""
        ctx = X.welded_course(api, seam_labels=("V1", "V2", "V3", "V4", "V5"))
        for index in range(3):
            X.accept_examination(api, ctx.seams[index]["id"], f"2026-08-1{index + 1}", 0)
        ctx.pending = []
        for index, day in ((3, "2026-08-14"), (4, "2026-08-15")):
            start, end = X.rt_window(day, 0)
            ctx.pending.append(X.schedule_nde(api, ctx.seams[index]["id"], start, end))
        return ctx

    def test_a_clean_examination_history_leaves_the_base_percentage_in_force(self, api):
        """Three acceptances and no rejection keep the rate at zero.

        PRD: "a rate below 0.25 leaves the base 10.0 percent in force."

        Design: Difficulty/boundary_precision_check/weld_reject_rate_exactly_at_escalation_tier_boundary
        """
        ctx = self._four_accepted_examinations_and_a_fifth_window(api)

        tank = X.read_tank(api, ctx.tank_id)
        assert_reject_rate(tank["weld_reject_rate"], 0.0)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)

    def test_a_rate_of_exactly_one_quarter_escalates_the_mandated_coverage(self, api):
        """One rejection in four reported examinations is exactly 0.2500.

        PRD: "The boundaries are inclusive from below, so a rate of exactly 0.2500
        escalates to 50.0."

        Design: Difficulty/boundary_precision_check/weld_reject_rate_exactly_at_escalation_tier_boundary
        """
        ctx = self._four_accepted_examinations_and_a_fifth_window(api)

        X.report_nde(api, ctx.pending[0]["id"], DECISION_REJECT, 1, 4, DEFECT_POROSITY)

        tank = X.read_tank(api, ctx.tank_id)
        assert_reject_rate(tank["weld_reject_rate"], 0.2500)
        assert tank["required_examination_pct"] == pytest.approx(ESCALATED_EXAMINATION_PCT)

    def test_a_fifth_acceptance_drops_below_the_boundary_and_de_escalates(self, api):
        """One rejection in five reported examinations is 0.2000, back to the base band.

        PRD: "`required_examination_pct` is then selected from the rounded rate in
        three bands: a rate of 0.50 or higher mandates 100.0 percent examination; a
        rate of at least 0.25 but below 0.50 mandates 50.0 percent; and a rate
        below 0.25 leaves the base 10.0 percent in force."

        Design: Difficulty/boundary_precision_check/weld_reject_rate_exactly_at_escalation_tier_boundary
        """
        ctx = self._four_accepted_examinations_and_a_fifth_window(api)
        X.report_nde(api, ctx.pending[0]["id"], DECISION_REJECT, 1, 4, DEFECT_POROSITY)

        X.report_nde(api, ctx.pending[1]["id"], DECISION_ACCEPT, 0, 4)

        tank = X.read_tank(api, ctx.tank_id)
        assert_reject_rate(tank["weld_reject_rate"], 0.2000)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)
        assert_tank_state(tank, posture=POSTURE_RESTRICTED, nonconformance_count=1)

        assert X.read_seam(api, ctx.seams[3]["id"])["status"] == SEAM_RT_REJECTED
        assert X.read_seam(api, ctx.seams[4]["id"])["status"] == SEAM_RT_ACCEPTED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED
