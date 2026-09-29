"""Money and score arithmetic: floors, ceilings, tiers, weights and caps."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import (
    assert_decimal,
    assert_hour_ledger,
    assert_hour_ledger_identity,
    assert_instants_equal,
)
from test_helpers.constants import QC_TWO_USER_ID, QC_VERDICT_FAIL
from test_helpers.test_users import EDITOR_HEADERS, SUPERVISOR_HEADERS


class TestMinimumSessionFloor:
    """A short window still reserves and bills the facility minimum."""

    def test_a_one_hour_window_reserves_two_hours_and_pins_240000(self, world):
        """The literal hour never reaches the booking or the project's hour ledger.

        PRD §3.6: "Then `reserved_hours`, the figure stored on the booking, is the greater
        of `requested_hours` and the facility's **two-hour minimum session** — a one-hour
        window still reserves and bills 2.00 hours."

        Design: Corner/calculations/min_session_hours_floor_lifts_a_one_hour_reservation
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000)
        mixer = world.mixer(full_name="Floor Fay", certified_platforms=["STREAMING"])
        project = world.project(title="Min Session")

        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T11:00:00Z",
        )

        assert_decimal(booking["reserved_hours"], 2.00)
        assert booking["provisional_cost_cents"] == 240000
        assert booking["billable_hours_final"] is None
        assert booking["final_cost_cents"] is None

        assert_hour_ledger(world.get_project(project["id"]), 2.00, 0.00, 38.00)
        assert world.ledger(project["id"])["stage_cost_subtotal_cents"] == 240000


class TestQuarterHourQuantisation:
    """One minute of overrun costs a whole quarter-hour, billed at time and a half."""

    def test_a_two_hour_one_minute_occupation_bills_2_25_hours(self, world):
        """2.25 billable hours at 100000 plus the 1.5 factor on 0.25 gives 237500.

        PRD §3.6: "That elapsed figure is then quantised **upward** to the next whole
        quarter-hour: divide by 0.25, take the ceiling, multiply back by 0.25."

        Design: Corner/calculations/one_minute_overrun_rounds_up_a_full_quarter_hour
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Quarter Quinn", certified_platforms=["STREAMING"])
        project = world.project(title="Quarter Hour")

        closed = world.completed_booking(
            project["id"],
            stage["id"],
            mixer["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            completed_at="2026-09-14T12:01:00Z",
            booking_type="PREMIX",
            platform="STREAMING",
        )

        assert_decimal(closed["billable_hours_final"], 2.25)
        assert_decimal(closed["overtime_hours"], 0.25)
        assert closed["final_cost_cents"] == 237500
        assert_instants_equal(closed["actual_end_utc"], "2026-09-14T12:01:00Z")

        assert_hour_ledger(world.get_project(project["id"]), 0.00, 2.25, 37.75)
        assert world.ledger(project["id"])["billing_total_cents"] == 237500


class TestRushIsTwoSeparateLevers:
    """The stage multiplier and the billing surcharge are different mechanisms."""

    def _two_projects_on_one_stage_day(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(full_name="Rush Rina", certified_platforms=["STREAMING"])
        rush = world.project(title="Rush Project", turnaround_class="RUSH")
        standard = world.project(title="Standard Project", turnaround_class="STANDARD")
        return stage, mixer, rush, standard

    def test_the_stage_multiplier_applies_once_and_the_surcharge_is_separate(self, world):
        """576000 against 360000 for the same window, then a 20% surcharge on top.

        PRD §3.6: "A three-hour window on a stage billing 120000 cents an hour for a
        `STANDARD` project therefore reserves 3.00 hours and pins a
        `provisional_cost_cents` of 360000; the identical window on a `RUSH` project pins
        576000; and a one-hour window on that stage pins 240000 against 2.00 reserved
        hours."

        Design: Corner/calculations/rush_turnaround_multiplier_is_applied_exactly_once
        """
        stage, mixer, rush, standard = self._two_projects_on_one_stage_day(world)

        rush_booking = world.booking(
            rush["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
        )
        standard_booking = world.booking(
            standard["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T14:00:00Z",
            window_end_utc="2026-09-14T17:00:00Z",
        )

        assert_decimal(rush_booking["reserved_hours"], 3.00)
        assert rush_booking["provisional_cost_cents"] == 576000
        assert_decimal(standard_booking["reserved_hours"], 3.00)
        assert standard_booking["provisional_cost_cents"] == 360000

        rush_ledger = world.ledger(rush["id"])
        assert rush_ledger["stage_cost_subtotal_cents"] == 576000
        assert rush_ledger["volume_discount_cents"] == 28800
        assert rush_ledger["rush_surcharge_cents"] == 109440
        assert rush_ledger["billing_total_cents"] == 656640

        standard_ledger = world.ledger(standard["id"])
        assert standard_ledger["volume_discount_cents"] == 0
        assert standard_ledger["rush_surcharge_cents"] == 0
        assert standard_ledger["billing_total_cents"] == 360000


class TestNonUnionIgnoresTheMinimumCall:
    """The minimum call is stored for every talent but spends only union money."""

    def test_a_forty_five_minute_non_union_call_bills_forty_five_minutes(self, world):
        """45.00 minutes at 600 cents gives 27000, not the 60-minute union figure.

        PRD §3.5: "For `NON_UNION` talent, `billable_minutes` is exactly
        `scheduled_minutes` — the minimum call is ignored — and the non-union rate of
        **600 cents per billable minute** applies."

        Design: Corner/calculations/non_union_adr_ignores_the_min_call_minutes_field
        """
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Nonunion Nell", union_status="NON_UNION", daily_cap_minutes=240,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Non Union ADR")

        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T09:45:00Z",
            lines_scheduled=9,
        )

        assert_decimal(session["billable_minutes"], 45.00)
        assert session["session_cost_cents"] == 27000

        confirmed = world.confirm_adr(session["id"])
        assert confirmed["status"] == "CONFIRMED"

        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 27000
        assert ledger["billing_total_cents"] == 27000


class TestLicenceExpiryBoundaries:
    """Three expiry positions against one clock: at, inside and past the window."""

    def test_thirty_days_clears_and_the_clock_instant_has_expired(self, world, api):
        """Intake reads 25.00 while the audit, seeing the expired cut, reads 85.00.

        PRD §3.4: "Note the strictness of the expiry test — an asset whose `expires_at_utc`
        is exactly the current logical-clock instant has **expired** and does not clear."

        Design: Corner/calculations/license_expiry_boundaries_at_thirty_days_and_at_the_clock
        """
        world.set_clock("2026-09-01T00:00:00Z")
        at_the_window = world.library_asset(
            asset_code="EXP-A", kind="MUSIC_LIBRARY", license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE", fee_cents=10000,
            expires_at_utc="2026-10-01T00:00:00Z",
        )
        past_the_window = world.library_asset(
            asset_code="EXP-C", kind="SFX", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=500,
            expires_at_utc="2026-10-01T00:00:01Z",
        )
        already_expired = world.library_asset(
            asset_code="EXP-B", kind="MUSIC_LIBRARY", license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE", fee_cents=10000,
            expires_at_utc="2026-09-01T00:00:00Z",
        )
        project = world.project(title="Expiry Boundaries")
        package = world.stem_package(project["id"])

        near = world.asset_usage(at_the_window["id"], package["id"], usage_seconds=30)
        clear = world.asset_usage(past_the_window["id"], package["id"], usage_seconds=30)
        expired = world.asset_usage(already_expired["id"], package["id"], usage_seconds=30)

        assert near["clearance_status"] == "CLEARED"
        assert near["accrued_fee_cents"] == 10000
        assert clear["clearance_status"] == "CLEARED"
        assert clear["accrued_fee_cents"] == 500
        assert expired["clearance_status"] == "UNLICENSED"
        assert expired["unlicensed_reason"] == "ASSET_EXPIRED"
        assert expired["accrued_fee_cents"] == 0
        assert expired["cleared_at_utc"] is None
        assert world.get_asset(already_expired["id"])["status"] == "ACTIVE"

        project_after = world.get_project(project["id"])
        assert_decimal(project_after["license_risk_score_intake"], 25.00)
        assert_decimal(project_after["license_risk_score_audit"], 85.00)
        assert project_after["unlicensed_usage_count"] == 1
        assert project_after["license_fee_accrued_cents"] == 10500
        assert project_after["posture"] == "RESTRICTED"
        assert world.ledger(project["id"])["billing_total_cents"] == 10500

        cleared, meta = validate_paginated(
            api.list_asset_usages(
                EDITOR_HEADERS,
                {"stem_package_id": package["id"], "clearance_status": "CLEARED"},
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in cleared} == {near["id"], clear["id"]}


class TestVolumeDiscountTierBoundary:
    """The tier is a whole-subtotal rate, so one cent moves the entire total."""

    def test_one_extra_cent_flips_the_whole_subtotal_into_the_five_percent_tier(self, world):
        """499999 attracts nothing; 500000 attracts 25000 and bills 475000.

        PRD §3.8: "Step six selects the volume-discount rate from the tier whose bounds
        contain `pre_discount_total_cents` — 0.00 for a subtotal from 0 through 499999 cents
        inclusive, 0.05 for a subtotal from 500000 through 999999 cents inclusive, and 0.08
        for a subtotal of 1000000 cents or more with no upper bound — and
        `volume_discount_cents` is `pre_discount_total_cents` multiplied by that rate,
        rounded half up to whole cents."

        Design: Corner/calculations/volume_discount_tier_boundary_at_pre_discount_five_hundred_thousand
        """
        world.set_clock("2026-09-01T00:00:00Z")
        big = world.library_asset(
            asset_code="TIER-BIG", kind="MUSIC_LIBRARY", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=499999,
        )
        one_cent = world.library_asset(
            asset_code="TIER-ONE-CENT", kind="SFX", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=1,
        )
        project = world.project(title="Tier Boundary")
        package = world.stem_package(project["id"], stem_layout="STEREO")

        big_usage = world.asset_usage(big["id"], package["id"], usage_seconds=30)
        below = world.ledger(project["id"])
        assert below["pre_discount_total_cents"] == 499999
        assert below["volume_discount_cents"] == 0
        assert below["billing_total_cents"] == 499999
        assert below["rush_surcharge_cents"] == 0

        cent_usage = world.asset_usage(one_cent["id"], package["id"], usage_seconds=30)
        at_boundary = world.ledger(project["id"])
        assert at_boundary["pre_discount_total_cents"] == 500000
        assert at_boundary["volume_discount_cents"] == 25000
        assert at_boundary["billing_total_cents"] == 475000
        assert at_boundary["rush_surcharge_cents"] == 0

        assert big_usage["accrued_fee_cents"] == 499999
        assert cent_usage["accrued_fee_cents"] == 1
        project_after = world.get_project(project["id"])
        assert project_after["license_fee_accrued_cents"] == 500000
        assert_decimal(project_after["license_risk_score_intake"], 10.00)


class TestRiskScoreCapAppliesOnce:
    """Six rights-managed usages raise the raw score past the ceiling."""

    def test_the_raw_one_hundred_and_twenty_is_clamped_once_at_the_end(self, world, api):
        """Both variants read exactly 100.00 while the licence money stays at 6000.

        PRD §3.4: "The four products are summed, the sum is rounded half up, and the result
        is then capped at 100.00."

        Design: Corner/calculations/license_risk_score_cap_is_applied_after_summation
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Score Cap")
        package = world.stem_package(project["id"])
        assets = [
            world.library_asset(
                asset_code=f"CAP-{index}", kind="MUSIC_LIBRARY",
                license_type="RIGHTS_MANAGED", territory_scope="WORLDWIDE", fee_cents=1000,
            )
            for index in range(1, 7)
        ]

        for asset in assets[:5]:
            world.asset_usage(asset["id"], package["id"], usage_seconds=30)
        at_five = world.get_project(project["id"])
        assert_decimal(at_five["license_risk_score_intake"], 100.00)

        world.asset_usage(assets[5]["id"], package["id"], usage_seconds=30)

        at_six = world.get_project(project["id"])
        assert_decimal(at_six["license_risk_score_intake"], 100.00)
        assert_decimal(at_six["license_risk_score_audit"], 100.00)
        assert at_six["unlicensed_usage_count"] == 0
        assert at_six["posture"] == "OPEN"
        assert at_six["license_fee_accrued_cents"] == 6000
        assert world.ledger(project["id"])["billing_total_cents"] == 6000

        usages, meta = validate_paginated(
            api.list_asset_usages(EDITOR_HEADERS, {"stem_package_id": package["id"]})
        )
        assert meta["total_count"] == 6
        assert len(usages) == 6
        for usage in usages:
            assert usage["accrued_fee_cents"] == 1000


class TestHourLedgerIdentityAcrossBothTerms:
    """A closed session and an open reservation sit in different terms at once."""

    def test_reserved_and_consumed_hours_still_sum_to_the_authorized_figure(self, world):
        """3.25 consumed plus 2.00 reserved plus 34.75 available equals the 40.00 grant.

        PRD §3.6: "All three are carried to two decimal places, and the identity that
        `stage_hours_reserved` plus `stage_hours_consumed` plus `stage_hours_available`
        equals `stage_hours_authorized` must hold after **every** mutation."

        Design: Corner/calculations/stage_hour_ledger_identity_holds_across_completed_and_reserved
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage_a = world.mix_stage(hourly_rate_cents=100000)
        stage_b = world.mix_stage(hourly_rate_cents=50000)
        mixer_one = world.mixer(full_name="Ledger Lou", certified_platforms=["STREAMING"])
        mixer_two = world.mixer(full_name="Ledger Mo", certified_platforms=["STREAMING"])
        project = world.locked_project(title="Ledger Identity")

        reserved_only = world.booking(
            project["id"],
            stage_b["id"],
            mixer_two["id"],
            booking_type="PRINTMASTER",
            platform="STREAMING",
            window_start_utc="2026-09-14T14:00:00Z",
            window_end_utc="2026-09-14T16:00:00Z",
            client_attendance="REMOTE",
        )
        closed = world.completed_booking(
            project["id"],
            stage_a["id"],
            mixer_one["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
            completed_at="2026-09-14T13:01:00Z",
            booking_type="PREMIX",
            platform="STREAMING",
        )

        assert_decimal(closed["billable_hours_final"], 3.25)
        assert closed["final_cost_cents"] == 337500
        still_reserved = world.get_booking(reserved_only["id"])
        assert still_reserved["status"] == "RESERVED"
        assert_decimal(still_reserved["reserved_hours"], 2.00)
        assert still_reserved["provisional_cost_cents"] == 100000

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 2.00, 3.25, 34.75)
        assert_hour_ledger_identity(project_after)
        assert_decimal(project_after["stage_hours_authorized"], 40.00)

        ledger = world.ledger(project["id"])
        assert ledger["stage_cost_subtotal_cents"] == 437500
        assert ledger["billing_total_cents"] == 437500


class TestAllThreeRejectionCodesInDeclaredOrder:
    """A submission that trips every check reports a canonical ordered list."""

    def test_the_three_codes_are_emitted_in_the_fixed_declared_order(self, world, api):
        """-23.49 LUFS, -1.99 dBTP and no M&E stems fail loudness, peak and stems.

        PRD §3.7: "However many conditions fire, the codes are always emitted in one fixed
        order regardless of the order in which they were tested:
        `LOUDNESS_OUT_OF_TOLERANCE` first, then `TRUE_PEAK_EXCEEDED`, then
        `ME_STEMS_MISSING`."

        Design: Corner/calculations/qc_verdict_emits_all_three_rejection_codes_in_declared_order
        """
        environment = world.prepared_environment(
            platform="STREAMING",
            spec={
                "spec_label": "Streaming Triple Fail Spec",
                "target_lufs": -24.00,
                "tolerance_lu": 0.50,
                "true_peak_max_dbtp": -2.00,
                "requires_me_stems": True,
                "max_remediation_rounds": 2,
            },
            project={"title": "Triple Fail"},
        )
        deliverable_id = environment["deliverable"]["id"]

        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-23.49,
            measured_true_peak_dbtp=-1.99,
            me_stems_present=False,
        )
        report = world.qc_evaluate(deliverable_id)

        assert report["verdict"] == QC_VERDICT_FAIL
        assert_decimal(report["deviation_lu"], 0.51)
        assert report["rejection_codes"] == [
            "LOUDNESS_OUT_OF_TOLERANCE",
            "TRUE_PEAK_EXCEEDED",
            "ME_STEMS_MISSING",
        ]
        assert report["round"] == 0
        assert report["evaluated_by_user_id"] == QC_TWO_USER_ID

        rejected = world.get_deliverable(deliverable_id)
        assert rejected["status"] == "QC_REJECTED"
        assert rejected["qc_rejection_codes"] == [
            "LOUDNESS_OUT_OF_TOLERANCE",
            "TRUE_PEAK_EXCEEDED",
            "ME_STEMS_MISSING",
        ]
        assert rejected["remediation_round"] == 0

        _reports, meta = validate_paginated(
            api.list_qc_reports(deliverable_id, SUPERVISOR_HEADERS)
        )
        assert meta["total_count"] == 1
