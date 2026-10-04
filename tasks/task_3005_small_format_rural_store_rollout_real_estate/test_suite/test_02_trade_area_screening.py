"""Trade-area scoring variants, the rescreen loop, and OCC on screening."""

import pytest

from test_helpers import (
    ApiErrorId,
    create_active_rollout,
    create_existing_store,
    create_store,
    create_trade_area,
    get_success_data,
    screen_trade_area,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestAdjustedScoreVariant:
    """Cannibalization-adjusted trade-area scoring vs the standard variant."""

    def _setup_overlap_scenario(self, api):
        """ACTIVE program with one EXISTING store whose trade area is 10
        drive-minutes away with grocery_gap_pct 24, plus candidate area A."""
        rollout = create_active_rollout(name="P")
        t0 = create_trade_area(
            rollout["id"], name="T0", drive_time_minutes=10, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=24,
        )
        create_existing_store(rollout["id"], t0["id"], name="Legacy X")
        area = create_trade_area(
            rollout["id"], name="A", drive_time_minutes=15, household_count=2000,
            median_household_income_cents=4500000, grocery_gap_pct=20,
        )
        return rollout, area

    def test_trade_area_score_adjusted_by_nearby_overlap(self, api):
        """PRD §3.2: "When the overlap is greater than zero, the adjusted score
        is the raw score multiplied by 100 and then by 1 minus half the overlap
        fraction (the overlap percentage divided by 100, halved), rounded half
        up to two decimal places; when the overlap is zero the standard score
        stands."

        Design: Difficulty/dual_variant_calc/trade_area_score_adjusted_by_nearby_overlap
        """
        rollout, area = self._setup_overlap_scenario(api)
        resp = api.screen_trade_area(
            area["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_trade_area_version": area["version"],
            },
            ADMIN,
        )
        scored = validate_success(resp, 200)
        assert scored["status"] == "QUALIFIED"
        # Adjusted variant: overlap 24 (min(24, 25)) -> round(47.50 * 0.88, 2)
        # half up = 41.80; the standard variant for identical inputs is 47.50.
        assert scored["trade_area_score"] == pytest.approx(41.80, abs=0.01)
        assert scored["trade_area_score"] != pytest.approx(47.50, abs=0.001)
        assert scored["screening_count"] == 1

    def test_adjusted_score_differs_from_standard_for_identical_inputs(self, api):
        """PRD §3.2: "The raw score weights these components at 0.35, 0.25,
        0.20, and 0.20 respectively, and the **standard** score is the raw score
        multiplied by 100, rounded half up to two decimal places."
        PRD §3.2: "When the overlap is greater than zero, the adjusted score is
        the raw score multiplied by 100 and then by 1 minus half the overlap
        fraction (the overlap percentage divided by 100, halved), rounded half
        up to two decimal places; when the overlap is zero the standard score
        stands."

        Design: Difficulty/dual_variant_calc/trade_area_score_adjusted_by_nearby_overlap
        """
        rollout, area = self._setup_overlap_scenario(api)
        resp = api.screen_trade_area(
            area["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_trade_area_version": area["version"],
            },
            ADMIN,
        )
        scored = validate_success(resp, 200)
        # Standard variant would be 47.50 for these exact inputs; the presence
        # of the overlapping EXISTING store must move the stored score off it.
        assert scored["trade_area_score"] != pytest.approx(47.50, abs=0.001), (
            "score must be the adjusted variant, not the standard 47.50"
        )
        assert scored["trade_area_score"] < 47.50


class TestRescreenLoop:
    """SCREENING -> REJECTED -> QUALIFIED cycle with accumulating count."""

    def test_trade_area_reject_rescreen_qualify_cycle(self, api):
        """PRD §3.2: "A qualifying run moves the trade area `SCREENING →
        QUALIFIED` (or, on rescreen, `REJECTED → QUALIFIED`), increments
        `screening_count` by 1, and appends a `TRADE_AREA_QUALIFIED` event
        carrying the score snapshot. A failing run moves it to `REJECTED` —
        from `SCREENING`, from `QUALIFIED`, or staying at `REJECTED` on a
        still-failing rescreen — and increments `screening_count` by 1, with no
        event appended."

        Design: Difficulty/non_linear_state_machine/trade_area_reject_rescreen_qualify_cycle
        """
        rollout = create_active_rollout(name="P")
        area = create_trade_area(
            rollout["id"], name="A", drive_time_minutes=25, household_count=800,
            median_household_income_cents=4500000, grocery_gap_pct=15,
        )
        first = validate_success(
            api.screen_trade_area(
                area["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "expected_trade_area_version": area["version"],
                },
                ADMIN,
            ),
            200,
        )
        assert first["status"] == "REJECTED"
        assert first["trade_area_score"] == pytest.approx(34.68, abs=0.01)

        refreshed = get_success_data(
            api.update_trade_area(
                {
                    "rollout_program_id": rollout["id"],
                    "trade_area_id": area["id"],
                    "household_count": 2000,
                    "grocery_gap_pct": 20,
                    "drive_time_minutes": 15,
                },
                ADMIN,
            )
        )
        second = validate_success(
            api.screen_trade_area(
                area["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "expected_trade_area_version": refreshed["version"],
                },
                ADMIN,
            ),
            200,
        )
        assert second["status"] == "QUALIFIED"
        assert second["trade_area_score"] == pytest.approx(47.5, abs=0.01)
        assert second["screening_count"] == 2

    def test_failed_rescreen_keeps_rejected_and_counts(self, api):
        """PRD §3.2: "A failing run moves it to `REJECTED` — from `SCREENING`,
        from `QUALIFIED`, or staying at `REJECTED` on a still-failing rescreen —
        and increments `screening_count` by 1, with no event appended."

        Design: Difficulty/non_linear_state_machine/trade_area_reject_rescreen_qualify_cycle
        """
        rollout = create_active_rollout(name="P")
        area = create_trade_area(
            rollout["id"], name="A", drive_time_minutes=25, household_count=800,
            median_household_income_cents=4500000, grocery_gap_pct=15,
        )
        first = screen_trade_area(rollout["id"], area["id"])
        assert first["status"] == "REJECTED"
        # Still-failing rescreen: REJECTED stays REJECTED and the count climbs.
        second = screen_trade_area(rollout["id"], area["id"])
        assert second["status"] == "REJECTED"
        assert second["screening_count"] == 2


class TestScreeningOcc:
    def test_occ_stale_trade_area_version_rejected(self, api):
        """PRD §3.2: "Every scoring run — initial or rescreen — is a guarded
        write under optimistic concurrency (§2.9): the request must carry
        `expected_trade_area_version` matching the trade area's current
        `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412),
        because a prior screening or refresh has already advanced the trade area
        past the caller's view."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_trade_area_version_rejected
        """
        rollout = create_active_rollout(name="P")
        area = create_trade_area(
            rollout["id"], name="A", drive_time_minutes=25, household_count=800,
            median_household_income_cents=4500000, grocery_gap_pct=15,
        )
        first = validate_success(
            api.screen_trade_area(
                area["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "expected_trade_area_version": area["version"],
                },
                ADMIN,
            ),
            200,
        )
        assert first["status"] == "REJECTED"

        # Replay the pre-first-screen version: stale.
        resp = api.screen_trade_area(
            area["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_trade_area_version": area["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # The failed OCC attempt consumed no screening.
        after = get_success_data(api.get_trade_area(area["id"], ADMIN))
        assert after["status"] == "REJECTED"
        assert after["screening_count"] == 1


class TestScreeningGates:
    def test_error_program_not_active_on_screen(self, api):
        """PRD §3.1: "While `DRAFT`, the program refuses every child-creating
        and committing operation — screening, store creation, agreement
        activation, route planning, opening-plan creation, study creation,
        capital submission, and capital decisions all reject with
        `ERR_PROGRAM_NOT_ACTIVE` until activation has occurred."

        Design: Corner/errors/error_program_not_active_on_screen
        """
        rollout = create_active_rollout(name="P")
        area = create_trade_area(rollout["id"], name="A")
        # Return the program to DRAFT; no stores exist, so this is allowed.
        validate_success(api.deactivate_rollout(rollout["id"], ADMIN), 200)

        resp = api.screen_trade_area(
            area["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_trade_area_version": area["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

    def test_trade_area_create_out_of_range_gap_rejected(self, api):
        """PRD §3.2: "`grocery_gap_pct` (the percent of grocery demand
        currently unserved, from 0 to 100; a value outside that range fails as
        `ERR_VALIDATION`)"

        Design: Corner/entities/trade_area_create_out_of_range_gap_rejected
        """
        rollout = create_active_rollout(name="P")
        resp = api.create_trade_area(
            {
                "rollout_program_id": rollout["id"],
                "name": "BadGap",
                "drive_time_minutes": 20,
                "household_count": 1000,
                "median_household_income_cents": 4500000,
                "grocery_gap_pct": 140,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAdjustedScoreConditional:
    def test_trade_area_adjusted_score_requalify_check(self, api):
        """PRD §3.2: "When other stores of the same program already operate
        nearby, scoring switches to the **cannibalization-adjusted** variant."
        PRD §3.2: "when the overlap is zero the standard score stands."

        Design: Corner/validations/trade_area_adjusted_score_requalify_check
        """
        rollout = create_active_rollout(name="P")
        area = create_trade_area(
            rollout["id"], name="B", drive_time_minutes=20, household_count=3000,
            median_household_income_cents=4500000, grocery_gap_pct=20,
        )
        # No OPEN/EXISTING stores in the program: the standard variant applies.
        # raw = 0.35*0.5 + 0.25*0.4 + 0.2*(1-20/45) + 0.2*(3000/6000)
        #     = 0.486111... -> standard score 48.61.
        scored = screen_trade_area(rollout["id"], area["id"])
        assert scored["status"] == "QUALIFIED"
        assert scored["trade_area_score"] == pytest.approx(48.61, abs=0.01)


def test_store_create_missing_trade_area_id_rejected(api):
    """PRD §2.11: "request shape — required body fields must be present and
    well-typed and enum values must come from their declared sets, else
    `ERR_INVALID_REQUEST`"
    PRD §3.3: "both initiated by a `PROGRAM_ADMIN` supplying
    `rollout_program_id`, `trade_area_id`, and a `name`."

    Design: Corner/entities/store_create_missing_trade_area_id_rejected
    """
    rollout = create_active_rollout(name="P")
    create_trade_area(rollout["id"], name="A")  # an area exists, though unused
    resp = api.create_store(
        {"rollout_program_id": rollout["id"], "name": "NoArea"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_error_trade_area_not_qualified_on_store_create(api):
    """PRD §3.3: "The pipeline path creates a store in `PROPOSED` status and
    requires the referenced trade area to be `QUALIFIED`; a trade area in any
    other status yields `ERR_TRADE_AREA_NOT_QUALIFIED`."

    Design: Corner/errors/error_trade_area_not_qualified_on_store_create
    """
    rollout = create_active_rollout(name="P")
    area = create_trade_area(rollout["id"], name="A")  # stays SCREENING
    resp = api.create_store(
        {
            "rollout_program_id": rollout["id"],
            "trade_area_id": area["id"],
            "name": "S",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_AREA_NOT_QUALIFIED)
