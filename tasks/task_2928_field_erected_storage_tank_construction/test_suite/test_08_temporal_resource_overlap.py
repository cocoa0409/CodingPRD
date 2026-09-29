"""Two windowed resources whose interval semantics deliberately disagree.

Radiography is pairwise exclusive per tank on closed intervals after a symmetric
60-minute buffer, so buffered windows that merely touch conflict. A water permit
is additive per source on half-open intervals with no buffer, so a window that
starts exactly when another ends is free.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_EXAM_WINDOW_CONFLICT, ERR_WITHDRAWAL_CAPACITY_CONFLICT
from test_helpers.assertions import assert_money, assert_source_ledger
from test_helpers.constants import (
    CLOCK_BASE,
    COURSE_WELDED,
    NDE_METHOD_RT,
    NDE_METHOD_UT,
    NDE_SCHEDULED,
    NDE_VOIDED,
    SEAM_EXAM_SCHEDULED,
    SEAM_WELDED,
    SOURCE_MUNICIPAL,
    WITHDRAWAL_CANCELLED,
    WITHDRAWAL_RESERVED,
)
from test_helpers.factories import nde_report_payload
from test_helpers.test_users import ES1, QC1

# The RT window already booked on TK-101's first seam, and the neighbours that
# probe its buffered edges to the second.
BOOKED_START = "2026-08-11T10:00:00Z"
BOOKED_END = "2026-08-11T11:00:00Z"
TOUCHING_START = "2026-08-11T12:00:00Z"
TOUCHING_END = "2026-08-11T13:00:00Z"
ONE_SECOND_CLEAR_START = "2026-08-11T12:00:01Z"


class TestRtWindowBufferedClosedIntervalExclusion:
    def _two_tanks_with_one_rt_window_booked(self, api):
        ctx = X.welded_course(api, seam_labels=("V1", "V2", "V3"))
        ctx.other = X.welded_course(
            api,
            seam_labels=("V1",),
            tank_kwargs={"tank_tag": "TK-102"},
            welder_kwargs={"welder_stamp": "W-08", "full_name": "T. Nakamura"},
        )
        ctx.booked = X.schedule_nde(api, ctx.seams[0]["id"], BOOKED_START, BOOKED_END)
        return ctx

    def test_a_window_that_only_touches_after_buffering_conflicts(self, api):
        """The new window starts one hour after the booked one ends, and still loses.

        PRD: "Overlap is judged on closed intervals: the buffered start being no
        later than the existing window's end, together with the existing window's
        start being no later than the buffered end, is a conflict — so buffered
        windows that merely touch **do** conflict."

        Design: Difficulty/resource_temporal_overlap/rt_window_buffered_closed_interval_exclusion_per_tank
        """
        ctx = self._two_tanks_with_one_rt_window_booked(api)
        assert ctx.booked["status"] == NDE_SCHEDULED

        validate_error(
            api.create_nde_report(
                nde_report_payload(ctx.seams[1]["id"], TOUCHING_START, TOUCHING_END),
                QC1,
            ),
            ERR_EXAM_WINDOW_CONFLICT,
        )

        assert X.read_seam(api, ctx.seams[1]["id"])["status"] == SEAM_WELDED
        rows, meta = X.list_rows(
            api, api.list_nde_reports(QC1, {"weld_seam_id": ctx.seams[1]["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_one_second_of_clearance_is_enough(self, api):
        """Instants are compared to the second, so 12:00:01Z books.

        PRD: "Instants are compared to the second."

        Design: Difficulty/resource_temporal_overlap/rt_window_buffered_closed_interval_exclusion_per_tank
        """
        ctx = self._two_tanks_with_one_rt_window_booked(api)
        api.create_nde_report(
            nde_report_payload(ctx.seams[1]["id"], TOUCHING_START, TOUCHING_END), QC1
        )

        report = X.schedule_nde(api, ctx.seams[1]["id"], ONE_SECOND_CLEAR_START, TOUCHING_END)

        assert report["status"] == NDE_SCHEDULED
        assert report["method"] == NDE_METHOD_RT
        assert X.read_seam(api, ctx.seams[1]["id"])["status"] == SEAM_EXAM_SCHEDULED

    def test_the_exclusion_is_filtered_by_method_and_scoped_to_one_tank(self, api):
        """A UT shot inside the booked window, and an identical RT window on TK-102.

        PRD: "The rule applies only when both the new and the existing report use
        `RT`; `UT`, `MT`, `PT` and `VT` examinations never conflict with anything,
        and a voided report frees its window entirely."

        Design: Difficulty/resource_temporal_overlap/rt_window_buffered_closed_interval_exclusion_per_tank
        """
        ctx = self._two_tanks_with_one_rt_window_booked(api)

        ultrasonic = X.schedule_nde(
            api,
            ctx.seams[2]["id"],
            "2026-08-11T10:30:00Z",
            "2026-08-11T10:45:00Z",
            method=NDE_METHOD_UT,
            technician_stamp="UT-1",
        )
        assert ultrasonic["status"] == NDE_SCHEDULED
        assert ultrasonic["method"] == NDE_METHOD_UT

        other_tank = X.schedule_nde(api, ctx.other.seam_id, BOOKED_START, BOOKED_END)
        assert other_tank["status"] == NDE_SCHEDULED

    def test_voiding_the_report_frees_its_window_for_a_rebooking(self, api):
        """The same window is refused, then bookable once the holder is VOIDED.

        PRD: "A report still `SCHEDULED` — a window that was never shot — moves
        `SCHEDULED → VOIDED`, and the seam falls back from `EXAM_SCHEDULED` to
        `WELDED`, or to `RT_ACCEPTED` when the seam had already been accepted
        before this re-examination was scheduled; the host course status is
        re-derived accordingly."

        Design: Difficulty/resource_temporal_overlap/rt_window_buffered_closed_interval_exclusion_per_tank
        """
        ctx = self._two_tanks_with_one_rt_window_booked(api)
        X.schedule_nde(api, ctx.seams[1]["id"], ONE_SECOND_CLEAR_START, TOUCHING_END)

        voided = X.void_nde(api, ctx.booked["id"], void_reason="film fogged in transit")
        assert voided["status"] == NDE_VOIDED
        assert X.read_seam(api, ctx.seams[0]["id"])["status"] == SEAM_WELDED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

        rebooked = X.schedule_nde(api, ctx.seams[0]["id"], BOOKED_START, BOOKED_END)
        assert rebooked["status"] == NDE_SCHEDULED

        rows, meta = X.list_rows(
            api, api.list_nde_reports(QC1, {"weld_seam_id": ctx.seams[0]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"]: row["status"] for row in rows} == {
            ctx.booked["id"]: NDE_VOIDED,
            rebooked["id"]: NDE_SCHEDULED,
        }


# The three reserved windows that bring the source exactly to its 900 gpm ceiling
# between 11:00Z and 11:30Z on 2026-08-12.
W1_WINDOW = ("2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z")
W2_WINDOW = ("2026-08-12T10:00:00Z", "2026-08-12T14:00:00Z")
W3_WINDOW = ("2026-08-12T11:00:00Z", "2026-08-12T11:30:00Z")
CONTENDED_WINDOW = ("2026-08-12T11:15:00Z", "2026-08-12T11:20:00Z")
ABUTTING_WINDOW = ("2026-08-12T12:00:00Z", "2026-08-12T13:00:00Z")


class TestWithdrawalHalfOpenAdditiveRateEnvelope:
    def _source_at_its_rate_ceiling(self, api):
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        source = X.create_water_source(
            api,
            source_name="Municipal Hydrant 12",
            source_type=SOURCE_MUNICIPAL,
            permitted_volume_gal=2000000.0,
            max_concurrent_rate_gpm=900.0,
        )
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=350000.0)
        ctx = X.Ctx(
            tank=tank, tank_id=tank["id"], source=source, source_id=source["id"],
            plan=plan, plan_id=plan["id"],
        )
        ctx.w1 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *W1_WINDOW, 300.0, 100000.0
        )
        ctx.w2 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *W2_WINDOW, 300.0, 100000.0
        )
        ctx.w3 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *W3_WINDOW, 300.0, 50000.0
        )
        return ctx

    def test_the_summed_peak_is_accepted_exactly_at_the_ceiling(self, api):
        """Three overlapping windows of 300 gpm total exactly 900.0 gpm.

        PRD: "That peak figure, carried to 1 decimal place rounded half up, may not
        exceed the source's `max_concurrent_rate_gpm`; exactly at the ceiling the
        reservation is accepted, and above it the request is rejected with
        `ERR_WITHDRAWAL_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/water_withdrawal_half_open_additive_rate_envelope_per_source
        """
        ctx = self._source_at_its_rate_ceiling(api)

        assert ctx.w3["status"] == WITHDRAWAL_RESERVED
        assert ctx.w3["cancellation_reason"] is None
        assert_money(ctx.w3["rate_gpm"], 300.0, "rate_gpm")
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 250000.00, 0.00, 1750000.00
        )

    def test_a_tenth_of_a_gallon_over_the_ceiling_is_refused(self, api):
        """The 0.1 gpm window overlaps all three, so the peak would be 900.1.

        PRD: "The rate envelope is evaluated by collecting every withdrawal against
        the **same** source whose `status` is `RESERVED` and whose window overlaps
        the proposed one under half-open semantics — that is, the existing window
        starts strictly before the proposed end and the proposed start is strictly
        before the existing end — and adding the proposed `rate_gpm` to the sum of
        the overlapping windows' rates."

        Design: Difficulty/resource_temporal_overlap/water_withdrawal_half_open_additive_rate_envelope_per_source
        """
        ctx = self._source_at_its_rate_ceiling(api)
        before = X.read_water_source(api, ctx.source_id)

        validate_error(
            api.create_water_withdrawal(
                {
                    "hydrotest_plan_id": ctx.plan_id,
                    "water_source_id": ctx.source_id,
                    "window_start_utc": CONTENDED_WINDOW[0],
                    "window_end_utc": CONTENDED_WINDOW[1],
                    "rate_gpm": 0.1,
                    "reserved_volume_gal": 100.0,
                    "expected_water_source_version": before["version"],
                },
                ES1,
            ),
            ERR_WITHDRAWAL_CAPACITY_CONFLICT,
        )

        after = X.read_water_source(api, ctx.source_id)
        assert after["version"] == before["version"]
        assert_source_ledger(after, 250000.00, 0.00, 1750000.00)
        rows, meta = X.list_rows(
            api, api.list_water_withdrawals(ES1, {"water_source_id": ctx.source_id})
        )
        assert meta["total_count"] == 3

    def test_a_window_starting_exactly_when_another_ends_does_not_overlap(self, api):
        """12:00:00Z is w1's end, and half-open semantics leave it free.

        PRD: "The window runs from `window_start_utc` to `window_end_utc` and is
        **half-open**: a window that starts exactly when another ends does not
        overlap it."

        Design: Difficulty/resource_temporal_overlap/water_withdrawal_half_open_additive_rate_envelope_per_source
        """
        ctx = self._source_at_its_rate_ceiling(api)

        abutting = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *ABUTTING_WINDOW, 300.0, 100000.0
        )

        assert abutting["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 350000.00, 0.00, 1650000.00
        )

    def test_cancelling_one_window_frees_rate_for_the_request_it_refused(self, api):
        """The byte-identical reservation lands once w3 stops consuming rate.

        PRD: "On success it moves `RESERVED → CANCELLED`, the reason is stored, the
        source's `reserved_volume_gal` falls and its `available_volume_gal` rises by
        the released `reserved_volume_gal`, the cancelled window stops participating
        in both the rate-overlap check and the permitted-volume check, and the
        owning plan's cost fields are recomputed with the withdrawal excluded."

        Design: Difficulty/resource_temporal_overlap/water_withdrawal_half_open_additive_rate_envelope_per_source
        """
        ctx = self._source_at_its_rate_ceiling(api)
        api.create_water_withdrawal(
            {
                "hydrotest_plan_id": ctx.plan_id,
                "water_source_id": ctx.source_id,
                "window_start_utc": CONTENDED_WINDOW[0],
                "window_end_utc": CONTENDED_WINDOW[1],
                "rate_gpm": 0.1,
                "reserved_volume_gal": 100.0,
                "expected_water_source_version": X.source_version(api, ctx.source_id),
            },
            ES1,
        )
        ctx.w5 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *ABUTTING_WINDOW, 300.0, 100000.0
        )

        cancelled = X.cancel_withdrawal(
            api, ctx.w3["id"], cancellation_reason="crew reassigned"
        )
        assert cancelled["status"] == WITHDRAWAL_CANCELLED
        assert cancelled["cancellation_reason"] == "crew reassigned"
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 300000.00, 0.00, 1700000.00
        )

        replay = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *CONTENDED_WINDOW, 0.1, 100.0
        )
        assert replay["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 300100.00, 0.00, 1699900.00
        )

        rows, meta = X.list_rows(
            api,
            api.list_water_withdrawals(
                ES1, {"water_source_id": ctx.source_id, "status": WITHDRAWAL_RESERVED}
            ),
        )
        assert meta["total_count"] == 4
        assert {row["id"] for row in rows} == {
            ctx.w1["id"], ctx.w2["id"], ctx.w5["id"], replay["id"]
        }
