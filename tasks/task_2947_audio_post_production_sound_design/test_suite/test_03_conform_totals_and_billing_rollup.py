"""Per-cue conform arithmetic, the empty-cue boundary and the pinned billing roll-up."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_EMPTY_STEM_SET
from test_helpers.assertions import assert_billing_chain, assert_decimal
from test_helpers.test_users import EDITOR_HEADERS


class TestConformRoundsEachCueBeforeSumming:
    """The conform totals are pinned per cue, then summed."""

    def test_three_ninety_five_second_cues_total_four_point_seven_four_minutes(self, world):
        """Rounding each cue first yields 4.74 minutes and 7110 cents, not 4.75 and 7125.

        PRD §3.3: "Summing raw seconds first and dividing once at the end is
        **forbidden** and produces a different, wrong answer: three cues of 95 seconds
        each give 1.58 plus 1.58 plus 1.58, which is 4.74 minutes and a
        `conform_fee_cents` of 7110, whereas summing to 285 seconds and dividing once
        yields 4.75 minutes and 7125 cents."

        Design: Difficulty/combinatorial_formula/stem_conform_per_cue_rounding_before_summation
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(95, 95, 95))

        assert package["status"] == "CONFORMED"
        assert package["cue_count"] == 3
        assert_decimal(package["total_stem_minutes"], 4.74)
        assert package["total_stem_minutes"] != 4.75
        assert package["conform_fee_cents"] == 7110
        assert package["conform_fee_cents"] != 7125
        assert package["conform_round"] == 1
        assert package["stale_reason"] is None

        project_after = world.get_project(project["id"])
        assert project_after["conformed_stem_count"] == 1
        assert project_after["pipeline_stage"] == "PREMIX"
        assert world.ledger(project["id"])["conform_fee_total_cents"] == 7110

    def test_a_single_ninety_second_cue_is_the_second_reference_point(self, world):
        """One 90-second cue pins 1.50 minutes and 2250 cents.

        PRD §3.3: "As a second reference point, a single cue of 90 seconds gives
        `total_stem_minutes` 1.50 and `conform_fee_cents` 2250."

        Design: Difficulty/combinatorial_formula/stem_conform_per_cue_rounding_before_summation
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(90,))

        assert package["cue_count"] == 1
        assert_decimal(package["total_stem_minutes"], 1.50)
        assert package["conform_fee_cents"] == 2250

        ledger = world.ledger(project["id"])
        assert ledger["conform_fee_total_cents"] == 2250
        assert ledger["pre_discount_total_cents"] == 2250
        assert ledger["billing_total_cents"] == 2250
        assert_billing_chain(ledger)


class TestConformWithNoActiveCues:
    """Zero active cues is the empty-input boundary of the conform totals."""

    def test_conform_without_a_single_cue_is_refused_and_changes_nothing(self, world, api):
        """The empty package stays in DRAFT with all three totals at zero.

        PRD §3.3: "A package with zero `ACTIVE` cues is rejected with
        `ERR_EMPTY_STEM_SET`; a project whose lock is broken must be re-locked before any
        conform can succeed, because a `FROZEN` posture rejects the attempt with
        `ERR_PROJECT_FROZEN`."

        Design: Difficulty/boundary_precision_check/conform_with_zero_active_cues_is_the_empty_boundary
        """
        project = world.locked_project()
        package = world.stem_package(project["id"], stem_layout="STEREO")

        validate_error(
            api.conform_stem_package(package["id"], {}, EDITOR_HEADERS), ERR_EMPTY_STEM_SET, 422
        )

        unchanged = world.get_stem_package(package["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["cue_count"] == 0
        assert_decimal(unchanged["total_stem_minutes"], 0.00)
        assert unchanged["conform_fee_cents"] == 0
        assert unchanged["conform_round"] == 0
        assert unchanged["conformed_at_utc"] is None
        assert world.get_project(project["id"])["pipeline_stage"] == "EDITORIAL"

    def test_one_cue_flips_the_very_same_conform_call_to_success(self, world, api):
        """A single 30-second cue makes the same request pin 0.50 minutes and 750 cents.

        PRD §3.3: "When the conformed count moves from 0 to 1 and the project sits at
        `EDITORIAL`, `pipeline_stage` advances to `PREMIX`."

        Design: Difficulty/boundary_precision_check/conform_with_zero_active_cues_is_the_empty_boundary
        """
        project = world.locked_project()
        package = world.stem_package(project["id"], stem_layout="STEREO")
        validate_error(
            api.conform_stem_package(package["id"], {}, EDITOR_HEADERS), ERR_EMPTY_STEM_SET, 422
        )

        version = world.get_stem_package(package["id"])["version"]
        validate_success(
            api.create_music_cue(
                package["id"],
                f.music_cue_payload(version, cue_number="1M1", duration_seconds=30),
                EDITOR_HEADERS,
            ),
            201,
        )
        conformed = validate_success(
            api.conform_stem_package(package["id"], {}, EDITOR_HEADERS), 200
        )

        assert conformed["status"] == "CONFORMED"
        assert conformed["cue_count"] == 1
        assert_decimal(conformed["total_stem_minutes"], 0.50)
        assert conformed["conform_fee_cents"] == 750
        assert conformed["conform_round"] == 1
        assert world.get_project(project["id"])["pipeline_stage"] == "PREMIX"


class TestBillingRollUpOrder:
    """The volume discount is selected before the rush surcharge is applied."""

    def _rush_project_ledger(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=150000)
        mixer = world.mixer(certified_platforms=["THEATRICAL", "STREAMING"])
        talent = world.voice_talent(union_status="UNION", daily_cap_minutes=240, min_call_minutes=60)
        asset = world.library_asset(license_type="RIGHTS_MANAGED", fee_cents=30000)
        project = world.locked_project(turnaround_class="RUSH")
        package = world.conformed_package(project["id"], cue_durations=(120, 120))
        world.asset_usage(
            asset["id"], package["id"], usage_seconds=100, territory_declared="WORLDWIDE"
        )
        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T09:45:00Z",
        )
        world.confirm_adr(session["id"])
        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
        )
        assert booking["provisional_cost_cents"] == 720000
        return world.ledger(project["id"])

    def test_the_discount_tier_is_keyed_on_the_pre_surcharge_subtotal(self, world):
        """900000 falls in the middle tier, so the discount is 45000 and the base 855000.

        PRD §3.8: "Step six selects the volume-discount rate from the tier whose bounds
        contain `pre_discount_total_cents` — 0.00 for a subtotal from 0 through 499999
        cents inclusive, 0.05 for a subtotal from 500000 through 999999 cents inclusive,
        and 0.08 for a subtotal of 1000000 cents or more with no upper bound — and
        `volume_discount_cents` is `pre_discount_total_cents` multiplied by that rate,
        rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/project_billing_discount_tier_before_rush_surcharge
        """
        ledger = self._rush_project_ledger(world)

        assert ledger["stage_cost_subtotal_cents"] == 720000
        assert ledger["adr_cost_cents"] == 54000
        assert ledger["conform_fee_total_cents"] == 6000
        assert ledger["license_fee_accrued_cents"] == 120000
        assert ledger["pre_discount_total_cents"] == 900000
        assert ledger["volume_discount_cents"] == 45000
        assert ledger["discounted_base_cents"] == 855000
        assert_billing_chain(ledger)

    def test_the_rush_surcharge_is_computed_on_the_post_discount_base(self, world):
        """The surcharge is 171000 on 855000, giving 1026000 rather than 993600.

        PRD §3.8: "Step eight, `rush_surcharge_cents` is `discounted_base_cents`
        multiplied by the surcharge percentage for the project's `turnaround_class` —
        0.00 for `STANDARD`, 0.10 for `EXPEDITED` and 0.20 for `RUSH` — rounded half up
        to whole cents; the surcharge is computed on the **post-discount** base."

        Design: Difficulty/combinatorial_formula/project_billing_discount_tier_before_rush_surcharge
        """
        ledger = self._rush_project_ledger(world)

        assert ledger["rush_surcharge_cents"] == 171000
        assert ledger["billing_total_cents"] == 1026000
        assert ledger["billing_total_cents"] != 993600
        assert_billing_chain(ledger)
