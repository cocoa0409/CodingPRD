"""Boundary-precision checks: per-screen average threshold and embargo zero.

Design: Difficulty/boundary_precision_check
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, get_success_data, setup_festival,
    setup_open_release_plan, validate_error, validate_success,
)
from test_helpers.api_errors import ApiErrorId

DIST = TEST_USERS["dist_exec_headers"]
PROG = TEST_USERS["festival_prog_headers"]


class TestPerScreenAvgThresholdBoundary:
    def _open_plan(self, api):
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        plan, screenings = setup_open_release_plan(
            film, deal, target_market_codes=("NY", "LA"),
        )
        return film, plan, screenings

    def test_per_screen_avg_threshold_boundary_at_exactly_threshold(self, api):
        """PRD §3.5: "If the new `per_screen_avg_cents` is greater than or
        equal to the plan's `expansion_threshold_psa_cents`, and the plan's
        `platform_strategy` is not `WIDE_DIRECT`, and the plan is currently
        `OPENED`, then the plan transitions `OPENED → EXPANDING` and the
        triggering screening transitions `REPORTED → EXPANSION_TRIGGERED`."
        PRD §2.7: "Where a formula specifies integer division (the per-screen
        average), the result is rounded half-up to a whole cent."

        Design: Difficulty/boundary_precision_check/per_screen_avg_threshold_boundary_at_exactly_threshold
        """
        film, plan, screenings = self._open_plan(api)
        scr_ny = screenings["NY"]
        scr_la = screenings["LA"]

        # 49,999 / 5 = 9,999.8 -> round_half_up -> 10,000 == threshold
        reported_ny = validate_success(api.report_market_screening(
            plan["id"], scr_ny["id"],
            {"screen_count": 5, "weekend_gross_cents": 49_999}, DIST,
        ))
        assert reported_ny["per_screen_avg_cents"] == 10_000
        assert reported_ny["status"] == "EXPANSION_TRIGGERED"

        # Plan is now EXPANDING, so the LA report cannot re-fire the
        # OPENED -> EXPANDING transition; it lands as REPORTED.
        reported_la = validate_success(api.report_market_screening(
            plan["id"], scr_la["id"],
            {"screen_count": 5, "weekend_gross_cents": 50_000}, DIST,
        ))
        assert reported_la["per_screen_avg_cents"] == 10_000
        assert reported_la["status"] == "REPORTED"

        plan_after = get_success_data(api.get_release_plan(plan["id"], DIST))
        assert plan_after["status"] == "EXPANDING"

    def test_per_screen_avg_below_threshold_does_not_expand(self, api):
        """PRD §3.5: "On report the screening's `per_screen_avg_cents` is
        computed as the `weekend_gross_cents` divided by `screen_count`, with
        integer division rounding half-up to a whole cent; the screening
        transitions `SCHEDULED → REPORTED`" — a per-screen average strictly
        below the threshold leaves the plan OPENED and the screening REPORTED.

        Design: Difficulty/boundary_precision_check/per_screen_avg_threshold_boundary_at_exactly_threshold
        """
        film, plan, screenings = self._open_plan(api)
        scr_ny = screenings["NY"]

        # 49,995 / 5 = 9,999 exactly — one cent below the threshold
        reported = validate_success(api.report_market_screening(
            plan["id"], scr_ny["id"],
            {"screen_count": 5, "weekend_gross_cents": 49_995}, DIST,
        ))
        assert reported["per_screen_avg_cents"] == 9_999
        assert reported["status"] == "REPORTED"

        plan_after = get_success_data(api.get_release_plan(plan["id"], DIST))
        assert plan_after["status"] == "OPENED"


class TestPremiereSlotEmbargoZeroBoundary:
    def test_premiere_slot_embargo_zero_hours_boundary(self, api):
        """PRD §3.4: "a `review_embargo_lifts_at` instant that must be at or
        after `screening_ends_at`."
        PRD §5: `ERR_INVALID_WINDOW` 422 — "End before start, embargo before
        screening end, or offer expiry in the past".

        Design: Difficulty/boundary_precision_check/premiere_slot_embargo_zero_hours_boundary
        """
        festival = setup_festival()

        # Zero-hour embargo — lifts exactly when the screening ends: accepted
        slot_zero = validate_success(api.create_premiere_slot(
            festival["id"],
            {"section": "COMPETITION",
             "screening_starts_at": "2027-01-22T20:00:00Z",
             "screening_ends_at": "2027-01-22T22:00:00Z",
             "review_embargo_lifts_at": "2027-01-22T22:00:00Z"},
            PROG,
        ), expected_status=201)
        assert (slot_zero["review_embargo_lifts_at"]
                == slot_zero["screening_ends_at"])

        # Negative embargo — lifts one hour before the screening ends: rejected
        resp = api.create_premiere_slot(
            festival["id"],
            {"section": "PREMIERES",
             "screening_starts_at": "2027-01-23T20:00:00Z",
             "screening_ends_at": "2027-01-23T22:00:00Z",
             "review_embargo_lifts_at": "2027-01-23T21:00:00Z"},
            PROG,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_premiere_slot_embargo_over_one_week_rejected(self, api):
        """PRD §3.4: "If the embargo delay — the whole-hour gap between
        `screening_ends_at` and `review_embargo_lifts_at` — exceeds 168 hours
        (one week), the slot creation is rejected with `ERR_EMBARGO_TOO_LONG`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/premiere_slot_embargo_zero_hours_boundary
        """
        festival = setup_festival()
        resp = api.create_premiere_slot(
            festival["id"],
            {"section": "COMPETITION",
             "screening_starts_at": "2027-01-22T20:00:00Z",
             "screening_ends_at": "2027-01-22T22:00:00Z",
             "review_embargo_lifts_at": "2027-01-30T00:00:00Z"},  # 170h > 168h
            PROG,
        )
        validate_error(resp, ApiErrorId.ERR_EMBARGO_TOO_LONG)
