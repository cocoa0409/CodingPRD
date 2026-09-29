"""The two optimistic-concurrency guards, and one derived field re-derived by a sibling.

Both guards read the live parent row rather than a per-endpoint counter, and both
answer a precondition failure with 412 rather than the 409 a state gate would
use. The third case is the one derived value that a write to a *different* row
recomputes.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_STALE_TANK_VERSION,
    ERR_STALE_WATER_SOURCE_VERSION,
)
from test_helpers.assertions import (
    assert_list_total,
    assert_money,
    assert_object_envelope,
    assert_source_ledger,
    assert_thickness,
    assert_unchanged,
)
from test_helpers.constants import (
    CLOCK_BASE,
    COURSE1_REQUIRED_DESIGN_IN,
    COURSE1_REQUIRED_TEST_IN,
    COURSE2_REQUIRED_DESIGN_IN,
    COURSE2_REQUIRED_TEST_IN,
    GOVERNING_DESIGN,
    PHASE_DESIGN_REGISTERED,
    PHASE_FOUNDATION_ACCEPTED,
    PLAN_DRAFT,
    PLAN_SUPERSEDED,
    THICKNESS_ADEQUATE,
    THICKNESS_DEFICIENT,
    WITHDRAWAL_RESERVED,
)
from test_helpers.factories import (
    hydrotest_plan_payload,
    shell_course_payload,
    withdrawal_payload,
)
from test_helpers.test_users import ES1, PE1


class TestHydrotestPlanTankVersionGuard:
    def test_a_stale_tank_version_is_a_412_and_the_accepted_create_makes_it_stale_again(
        self, api
    ):
        """Refused, refreshed, accepted, and stale once more on the very same body.

        PRD: "Creating a hydrostatic test plan requires a non-optional `expected_tank_version`
        field in the request body, carrying the `version` of the target `Tank` as the
        client last observed it. If that value does not equal the tank's current
        `version`, the create is rejected with `ERR_STALE_TANK_VERSION` (HTTP 412). The
        guard exists because a new plan legitimately supersedes the tank's prior draft or
        rejected plan and re-points the tank's `active_hydrotest_plan_id`; a writer
        working from an outdated view of the tank would silently discard a plan it never
        saw. Every successful create advances the tank's `version` by 1, so a second
        create still carrying the older value fails."

        PRD: "Creating a plan supersedes whatever plan the tank already had in `DRAFT` or
        `REJECTED`: the older plan moves to the terminal `SUPERSEDED`, the new plan's
        `previous_plan_id` is pointed at it, and the tank's `version` is incremented by 1.
        A superseded plan that was still `DRAFT` also has its `RESERVED` withdrawal
        windows cancelled with `cancellation_reason` `PLAN_SUPERSEDED` and their volume
        released; a plan that was already `REJECTED` released its reservations at
        rejection time and has none left to release. `previous_plan_id` stays null for a
        tank's first plan."

        Design: Corner/cross_cutting_complexity_layers/hydrotest_plan_create_enforces_the_tank_version_precondition
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        version_at_creation = tank["version"]
        assert version_at_creation == 1

        source = X.create_water_source(api)
        package = X.create_foundation_package(api, tank["id"])
        X.create_survey(api, package["id"], X.UNIFORM_BASELINE, 0.0)
        X.accept_foundation(api, package["id"])

        # The acceptance cascade advanced the tank, so the client's first read is stale.
        validate_error(
            api.create_hydrotest_plan(
                hydrotest_plan_payload(tank["id"], source["id"], version_at_creation), PE1
            ),
            ERR_STALE_TANK_VERSION,
            412,
        )
        assert_list_total(api.list_hydrotest_plans(PE1, {"tank_id": tank["id"]}), 0)
        refused_tank = X.read_tank(api, tank["id"])
        assert refused_tank["active_hydrotest_plan_id"] is None
        assert refused_tank["construction_phase"] == PHASE_FOUNDATION_ACCEPTED

        after_acceptance = refused_tank["version"]
        assert after_acceptance == version_at_creation + 1

        first_plan = assert_object_envelope(
            api.create_hydrotest_plan(
                hydrotest_plan_payload(tank["id"], source["id"], after_acceptance), PE1
            ),
            201,
        )
        assert first_plan["status"] == PLAN_DRAFT
        assert first_plan["previous_plan_id"] is None
        # PRD points the pointer only on approval — "On `APPROVE` the plan moves
        # `DRAFT → APPROVED` ... and the tank's `active_hydrotest_plan_id` is
        # pointed at the plan" — so a merely created DRAFT plan leaves it null.
        assert X.read_tank(api, tank["id"])["active_hydrotest_plan_id"] is None

        # The very body that just worked is now stale, because the create moved the tank.
        validate_error(
            api.create_hydrotest_plan(
                hydrotest_plan_payload(tank["id"], source["id"], after_acceptance), PE1
            ),
            ERR_STALE_TANK_VERSION,
            412,
        )
        after_first_plan = X.read_tank(api, tank["id"])
        assert after_first_plan["version"] == after_acceptance + 1
        assert after_first_plan["construction_phase"] == PHASE_FOUNDATION_ACCEPTED

        second_plan = assert_object_envelope(
            api.create_hydrotest_plan(
                hydrotest_plan_payload(tank["id"], source["id"], after_first_plan["version"]),
                PE1,
            ),
            201,
        )
        assert second_plan["status"] == PLAN_DRAFT
        assert second_plan["previous_plan_id"] == first_plan["id"]

        superseded = X.read_plan(api, first_plan["id"])
        assert superseded["status"] == PLAN_SUPERSEDED
        assert superseded["previous_plan_id"] is None
        assert X.read_tank(api, tank["id"])["active_hydrotest_plan_id"] is None
        assert_list_total(api.list_hydrotest_plans(PE1, {"tank_id": tank["id"]}), 2)


class TestWithdrawalWaterSourceVersionGuard:
    def test_the_stale_reservation_is_refused_before_capacity_and_leaves_the_ledger_alone(
        self, api
    ):
        """Two overlapping windows that fit the envelope, separated only by the guard.

        PRD: "Reserving a water withdrawal window requires a non-optional
        `expected_water_source_version` field in the request body, carrying the `version`
        of the target `WaterSource` as the client last observed it. If that value does not
        equal the source's current `version`, the reservation is rejected with
        `ERR_STALE_WATER_SOURCE_VERSION` (HTTP 412). Each reservation consumes part of the
        source's `available_volume_gal` and part of its concurrent-rate envelope, so a
        writer holding an outdated view of the source would size its reservation against
        capacity that has already been committed. Every accepted reservation advances the
        source's `version` by 1."

        PRD: "Seventh and eighth come the two optimistic-concurrency guards of §2.6:
        `expected_tank_version` on hydrostatic plan creation, then
        `expected_water_source_version` on withdrawal reservation."

        PRD: "The temporal checks follow: window ordering (`ERR_INVALID_WINDOW`), radiographic
        window exclusivity (`ERR_EXAM_WINDOW_CONFLICT`), water permit currency
        (`ERR_WATER_PERMIT_EXPIRED`), hold-period elapse (`ERR_HOLD_PERIOD_NOT_ELAPSED`),
        and concurrent withdrawal rate capacity (`ERR_WITHDRAWAL_CAPACITY_CONFLICT`)."

        PRD: "Each withdrawal is priced at the moment it is reserved. Its `withdrawal_cost_usd`
        is `reserved_volume_gal` divided by the 1,000 gallons in a thousand-gallon unit,
        multiplied by the source's `water_cost_usd_per_kgal`, rounded half up to 2 decimal
        places. The plan's `water_cost_usd` is then the **sum of those already-rounded
        per-withdrawal amounts**, taken over every withdrawal of the plan whose `status`
        is `RESERVED` or `CONSUMED`, processed in `created_at` order."

        PRD: "Disposal is priced once, on the plan's aggregate volume. Sum `reserved_volume_gal`
        across the same input set and divide by 1,000 to obtain the plan's volume in
        thousands of gallons, then select a disposal multiplier from that figure: at or
        below 500 thousand gallons the multiplier is 1.00; above 500 and at or below 2,000
        thousand gallons it is 0.85; and above 2,000 thousand gallons it is 0.70.
        `disposal_cost_usd` is the volume in thousands of gallons multiplied by
        `disposal_cost_usd_per_kgal` multiplied by that multiplier, rounded half up to 2
        decimal places."

        Design: Corner/cross_cutting_complexity_layers/withdrawal_reservation_enforces_the_water_source_version_precondition
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        version_at_creation = source["version"]
        assert version_at_creation == 1
        plan = X.create_plan(api, tank["id"], source["id"])
        assert plan["status"] == PLAN_DRAFT
        assert X.source_version(api, source["id"]) == version_at_creation

        first = assert_object_envelope(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"],
                    source["id"],
                    "2026-08-11T00:00:00Z",
                    "2026-08-11T10:00:00Z",
                    400.0,
                    400000.0,
                    version_at_creation,
                ),
                ES1,
            ),
            201,
        )
        assert first["status"] == WITHDRAWAL_RESERVED
        assert_money(first["withdrawal_cost_usd"], 1332.00, "first withdrawal cost")
        assert_source_ledger(
            X.read_water_source(api, source["id"]), 400000.00, 0.00, 1600000.00
        )

        # 400 + 400 gpm is inside the 900 gpm envelope and 800 000 gal is inside the
        # permit, so only the stale precondition can be refusing this.
        validate_error(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"],
                    source["id"],
                    "2026-08-11T05:00:00Z",
                    "2026-08-11T15:00:00Z",
                    400.0,
                    400000.0,
                    version_at_creation,
                ),
                ES1,
            ),
            ERR_STALE_WATER_SOURCE_VERSION,
            412,
        )
        assert_list_total(
            api.list_water_withdrawals(ES1, {"water_source_id": source["id"]}), 1
        )
        assert_source_ledger(
            X.read_water_source(api, source["id"]), 400000.00, 0.00, 1600000.00
        )

        after_first = X.source_version(api, source["id"])
        assert after_first == version_at_creation + 1

        second = assert_object_envelope(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"],
                    source["id"],
                    "2026-08-11T05:00:00Z",
                    "2026-08-11T15:00:00Z",
                    400.0,
                    400000.0,
                    after_first,
                ),
                ES1,
            ),
            201,
        )
        assert second["status"] == WITHDRAWAL_RESERVED
        assert_money(second["withdrawal_cost_usd"], 1332.00, "second withdrawal cost")

        source_now = X.read_water_source(api, source["id"])
        assert_source_ledger(source_now, 800000.00, 0.00, 1200000.00)
        assert source_now["version"] == after_first + 1

        priced = X.read_plan(api, plan["id"])
        assert_money(priced["water_cost_usd"], 2664.00, "plan water cost")
        assert_money(priced["disposal_cost_usd"], 1428.00, "plan disposal cost")


class TestLowerCourseInsertionReDerivesTheUpperCourse:
    def test_the_inserted_bottom_course_lifts_and_clears_the_course_above_it(self, api):
        """Nobody addresses course 2, yet every derived field of course 2 moves.

        PRD: "First the geometry: the course's `course_bottom_elevation_ft` is the sum of
        `course_width_ft` over every course of the same tank with a lower `course_number`,
        taken in ascending order, so the bottom course sits at elevation 0. Courses of
        other tanks never contribute. The course's `design_liquid_height_ft` is then the
        tank's `design_liquid_level_ft` less that bottom elevation — the head of liquid
        standing above the bottom of this particular course."

        PRD: "Both thickness variants are evaluated one foot above the bottom of the course, so
        both use the design liquid height reduced by one foot. The design-condition
        thickness, `required_thickness_design_in`, is the one-foot-method coefficient 2.6,
        multiplied by the design liquid height less one foot, multiplied by the tank's
        `diameter_ft`, multiplied by the tank's `product_specific_gravity`, all divided by
        the product of `allowable_stress_design_psi` and the tank's `joint_efficiency`,
        and then with the tank's `corrosion_allowance_in` added on. The
        hydrostatic-test-condition thickness, `required_thickness_test_in`, is the same
        coefficient 2.6, multiplied by the design liquid height less one foot, multiplied
        by `diameter_ft`, divided by the product of `allowable_stress_test_psi` and
        `joint_efficiency` — with no specific gravity term, because the test medium is
        water, and with **no corrosion allowance added**. That asymmetry is deliberate:
        the corrosion allowance belongs to the design case only and never to the test
        case."

        PRD: "The governing requirement, `required_thickness_in`, is the largest of three
        candidates: the rounded design-condition thickness, the rounded test-condition
        thickness, and the tank's `min_nominal_thickness_in` diameter floor from §3.1; it
        too is expressed to 3 decimal places. `governing_case` records which candidate
        produced it — `DESIGN`, `TEST` or `MIN_NOMINAL` — and ties are broken in exactly
        that order, so `DESIGN` wins a tie against `TEST` and `TEST` wins a tie against
        `MIN_NOMINAL`. Finally, `thickness_verdict` is `ADEQUATE` when the ordered
        `plate_thickness_in` is greater than or equal to `required_thickness_in`, and
        `DEFICIENT` otherwise. Because the elevation stack of a course depends on the
        courses below it, adding a lower course re-evaluates the calculation for the
        courses whose elevation stack changed."

        Design: Corner/cross_cutting_complexity_layers/lower_course_insertion_re_derives_the_upper_course_thickness
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)

        upper = X.create_course(api, tank["id"], 2, plate_thickness_in=0.375)
        assert upper["course_bottom_elevation_ft"] == pytest.approx(0.0)
        assert upper["design_liquid_height_ft"] == pytest.approx(40.0)
        assert_thickness(
            upper["required_thickness_design_in"], COURSE1_REQUIRED_DESIGN_IN, "design case"
        )
        assert_thickness(
            upper["required_thickness_test_in"], COURSE1_REQUIRED_TEST_IN, "test case"
        )
        assert_thickness(
            upper["required_thickness_in"], COURSE1_REQUIRED_DESIGN_IN, "governing requirement"
        )
        assert upper["governing_case"] == GOVERNING_DESIGN
        assert upper["thickness_verdict"] == THICKNESS_DEFICIENT

        lower = assert_object_envelope(
            api.create_shell_course(shell_course_payload(tank["id"], 1), PE1), 201
        )
        assert lower["course_bottom_elevation_ft"] == pytest.approx(0.0)
        assert_thickness(
            lower["required_thickness_in"], COURSE1_REQUIRED_DESIGN_IN, "governing requirement"
        )
        assert lower["thickness_verdict"] == THICKNESS_ADEQUATE

        lifted = X.read_course(api, upper["id"])
        assert lifted["course_bottom_elevation_ft"] == pytest.approx(8.0)
        assert lifted["design_liquid_height_ft"] == pytest.approx(32.0)
        assert_thickness(
            lifted["required_thickness_design_in"], COURSE2_REQUIRED_DESIGN_IN, "design case"
        )
        assert_thickness(
            lifted["required_thickness_test_in"], COURSE2_REQUIRED_TEST_IN, "test case"
        )
        assert_thickness(
            lifted["required_thickness_in"], COURSE2_REQUIRED_DESIGN_IN, "governing requirement"
        )
        assert lifted["governing_case"] == GOVERNING_DESIGN
        assert lifted["thickness_verdict"] == THICKNESS_ADEQUATE

        assert_unchanged(
            upper,
            lifted,
            "course_number",
            "course_width_ft",
            "plate_thickness_in",
            "allowable_stress_design_psi",
            "allowable_stress_test_psi",
            "material_spec",
        )
        assert_list_total(api.list_shell_courses(PE1, {"tank_id": tank["id"]}), 2)
        assert X.read_tank(api, tank["id"])["construction_phase"] == PHASE_DESIGN_REGISTERED
