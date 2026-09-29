"""Breadth probes over the declared validation rules.

Each probe drives one rule into its refusal and then, in the same test, drives
the neighbouring case that must still be accepted, so a rule that is applied
too widely fails as loudly as one that is not applied at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DISCIPLINE_HYDROGEOLOGY,
    METHOD_CLOSURE_BY_REMOVAL,
    METHOD_CLOSURE_IN_PLACE,
    PHASE_DETECTION,
    PLAN_STATUS_DRAFT,
    POSTURE_COMPLIANT,
    STABILITY_UNASSESSED,
    WELL_ROLE_BACKGROUND,
    WELL_STATUS_CERTIFIED,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS

# Exactly 29 characters, one short of the contract's floor, and exactly 30.
JUSTIFICATION_29 = "County order requires removal"
JUSTIFICATION_30 = "County order requires removals"

PLAN_COSTS = {
    "in_place_capital_usd_cents": 100000000,
    "in_place_annual_care_usd_cents": 1000000,
    "removal_capital_usd_cents": 900000000,
    "removal_annual_care_usd_cents": 1000000,
    "care_period_years": 30,
}


def test_future_event_dates_are_refused_while_a_window_bound_may_run_ahead(api):
    """Three enumerated event dates are refused; the window bound and the clock date are not.

    PRD: A group of event dates may never be dated in the future relative to the current date: a unit's `cessation_date`, a stability assessment's `assessed_on`, a well's `installed_on`, a sampling round's `sampled_on`, a shipment's `shipped_on`, a cap inspection's `inspected_on`, and a public posting's `posted_on` and `community_meeting_held_on`. Any of these carrying a date after the current date is rejected with `ERR_FUTURE_DATE_NOT_ALLOWED` (HTTP 422). Window boundaries are deliberately exempt from that rule and may be dated in the future: a monitoring program's `background_window_start_on` and `background_window_end_on`
    Design: Corner/validations/future_event_dates_are_rejected_while_window_bounds_are_not
    """
    world = fixtures.seed_unit(api, "IMP-0133")
    hydro = world["hydro_headers"]

    future_unit = api.create_unit(
        factories.unit_payload("IMP-0134", unit_name="Ash Pond 134", cessation_date="2026-09-01"),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(future_unit, ApiErrorId.FUTURE_DATE_NOT_ALLOWED.value)
    _, unit_page = validate_paginated(api.list_units(UTILITY_ADMIN_HEADERS))
    assert unit_page["total_count"] == 1

    future_assessment = api.create_stability_assessment(
        factories.stability_payload(world["unit_id"], "2026-08-02"), world["geotech_headers"]
    )
    validate_error(future_assessment, ApiErrorId.FUTURE_DATE_NOT_ALLOWED.value)
    assert (
        fixtures.read_unit(api, world["unit_id"])["governing_stability_verdict"]
        == STABILITY_UNASSESSED
    )

    future_well = api.create_well(
        factories.background_well_payload(world["unit_id"], "BG-01", installed_on="2026-08-02"),
        hydro,
    )
    validate_error(future_well, ApiErrorId.FUTURE_DATE_NOT_ALLOWED.value)

    program = validate_success(
        api.patch_program(
            world["program_id"],
            factories.program_config_payload(
                background_window_end_on="2026-12-31", comparison_basis=factories.OMIT
            ),
            hydro,
        )
    )
    a.assert_date(
        program["background_window_end_on"], "2026-12-31", "background_window_end_on"
    )

    today_well = validate_success(
        api.create_well(
            factories.background_well_payload(world["unit_id"], "BG-01", installed_on="2026-08-01"),
            hydro,
        ),
        201,
    )
    a.assert_date(today_well["installed_on"], "2026-08-01", "installed_on")
    assert today_well["well_status"] == WELL_STATUS_CERTIFIED

    recounted = fixtures.read_program(api, world["program_id"])
    assert recounted["background_well_count"] == 1
    assert recounted["downgradient_well_count"] == 0


def test_a_duplicate_code_is_refused_in_its_own_scope_and_nowhere_else(api):
    """A unit code is global, a licence number is per state, a well code is per unit.

    PRD: `unit_code` is unique across all disposal units, `agreement_code` is unique across all reuse agreements, `license_number` is unique per `license_state`, `well_code` is unique per unit, `event_code` and `evaluation_code` are each unique per monitoring program, `plan_code` is unique per unit, and `shipment_code` is unique per agreement. A collision in any of those scopes is `ERR_DUPLICATE_CODE` (HTTP 409).
    Design: Corner/validations/duplicate_codes_are_refused_while_distinct_codes_are_accepted
    """
    world = fixtures.seed_unit(api, "IMP-0135")
    hydro = world["hydro_headers"]
    first_well = fixtures.install_well(
        api, world["unit_id"], hydro, "BG-01", WELL_ROLE_BACKGROUND
    )

    duplicate_unit = api.create_unit(
        factories.unit_payload(
            "IMP-0135", unit_name="Ash Pond 135 Duplicate", plant_code="PLNT02"
        ),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(duplicate_unit, ApiErrorId.DUPLICATE_CODE.value)

    longer_code = validate_success(
        api.create_unit(
            factories.unit_payload("IMP-0135B", unit_name="Ash Pond 135B", plant_code="PLNT02"),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    duplicate_license = api.create_professional(
        factories.professional_payload("Other Hydro", "HG-33003", DISCIPLINE_HYDROGEOLOGY),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(duplicate_license, ApiErrorId.DUPLICATE_CODE.value)

    duplicate_well = api.create_well(
        factories.background_well_payload(
            world["unit_id"], "BG-01", screen_top_ft=23.00, screen_bottom_ft=43.00
        ),
        hydro,
    )
    validate_error(duplicate_well, ApiErrorId.DUPLICATE_CODE.value)

    same_code_other_unit = validate_success(
        api.create_well(factories.background_well_payload(longer_code["id"], "BG-01"), hydro), 201
    )
    assert same_code_other_unit["unit_id"] == longer_code["id"]

    untouched = validate_success(api.get_well(first_well["id"], UTILITY_ADMIN_HEADERS))
    a.assert_two_dp(untouched["screen_top_ft"], 20.00, "screen_top_ft")
    a.assert_two_dp(untouched["screen_bottom_ft"], 40.00, "screen_bottom_ft")


def test_a_justification_is_demanded_only_when_the_selection_diverges(api):
    """29 characters is refused, 30 is accepted, and the aligned plan needs none at all.

    PRD: Whenever `selected_method` differs from the computed `recommended_method`, `selection_justification` must be present and at least 30 characters long, or the request is refused with `ERR_METHOD_JUSTIFICATION_REQUIRED` (HTTP 422).
    Design: Corner/validations/method_justification_is_required_only_when_the_selection_diverges
    """
    world = fixtures.seed_unit(api, "IMP-0136")

    unjustified = api.create_closure_plan(
        factories.closure_plan_payload(
            world["unit_id"], "CP-0136-A", METHOD_CLOSURE_BY_REMOVAL, **PLAN_COSTS
        ),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(unjustified, ApiErrorId.METHOD_JUSTIFICATION_REQUIRED.value)

    one_short = api.create_closure_plan(
        factories.closure_plan_payload(
            world["unit_id"],
            "CP-0136-B",
            METHOD_CLOSURE_BY_REMOVAL,
            selection_justification=JUSTIFICATION_29,
            **PLAN_COSTS,
        ),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(one_short, ApiErrorId.METHOD_JUSTIFICATION_REQUIRED.value)

    justified = validate_success(
        api.create_closure_plan(
            factories.closure_plan_payload(
                world["unit_id"],
                "CP-0136-C",
                METHOD_CLOSURE_BY_REMOVAL,
                selection_justification=JUSTIFICATION_30,
                **PLAN_COSTS,
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    assert len(justified["selection_justification"]) == 30
    assert justified["recommended_method"] == METHOD_CLOSURE_IN_PLACE
    assert justified["selected_method"] == METHOD_CLOSURE_BY_REMOVAL

    aligned = validate_success(
        api.create_closure_plan(
            factories.closure_plan_payload(
                world["unit_id"], "CP-0136-D", METHOD_CLOSURE_IN_PLACE, **PLAN_COSTS
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    assert aligned.get("selection_justification") is None
    assert aligned["status"] == PLAN_STATUS_DRAFT

    for label, plan in (("justified", justified), ("aligned", aligned)):
        a.assert_cents(plan["in_place_pv_usd_cents"], 119600444, f"{label}.in_place_pv_usd_cents")
        a.assert_cents(plan["removal_pv_usd_cents"], 919600444, f"{label}.removal_pv_usd_cents")
        a.assert_two_dp(plan["cost_variance_pct"], 86.99, f"{label}.cost_variance_pct")


def test_the_background_check_is_reached_before_the_comparison_check(api):
    """A program with no data at all reports the background refusal, not the comparison one.

    PRD: 41. Enough background values exist for the evaluation, else `ERR_INSUFFICIENT_BACKGROUND_DATA`.
    PRD: 42. A compliance measurement exists after the background window, else `ERR_NO_COMPLIANCE_MEASUREMENT`.
    Design: Corner/validations/background_data_check_runs_before_the_compliance_measurement_check
    """
    stocked = fixtures.seed_unit(api, "IMP-0137")
    hydro = stocked["hydro_headers"]
    stocked_wells = fixtures.install_standard_network(api, stocked["unit_id"], hydro)
    fixtures.configure_program(api, stocked["program_id"], hydro)
    fixtures.certify_network(api, stocked["program_id"], hydro, "2025-01-05")
    last_round = None
    for code, sampled_on, validated_on, value in (
        ("BG-R1", "2025-02-10", "2025-02-11", 0.5000),
        ("BG-R2", "2025-05-12", "2025-05-13", 0.6000),
        ("BG-R3", "2025-08-11", "2025-08-12", 0.5500),
        ("BG-R4", "2025-11-10", "2025-11-11", 0.5800),
    ):
        last_round = fixtures.validated_round(
            api,
            stocked["program_id"],
            hydro,
            code,
            sampled_on,
            [(stocked_wells["BG-01"]["id"], value)],
            validated_on=validated_on,
        )

    barren = fixtures.seed_unit(api, "IMP-0138")
    barren_wells = fixtures.install_standard_network(api, barren["unit_id"], hydro)
    fixtures.configure_program(api, barren["program_id"], hydro)
    fixtures.certify_network(api, barren["program_id"], hydro, "2025-01-05")

    no_data = api.create_statistical_evaluation(
        factories.evaluation_payload(
            barren["program_id"], barren_wells["DG-01"]["id"], "EV-BARREN"
        ),
        barren["stats_headers"],
    )
    validate_error(no_data, ApiErrorId.INSUFFICIENT_BACKGROUND_DATA.value)

    no_comparison = api.create_statistical_evaluation(
        factories.evaluation_payload(
            stocked["program_id"], stocked_wells["DG-01"]["id"], "EV-STOCKED"
        ),
        stocked["stats_headers"],
    )
    validate_error(no_comparison, ApiErrorId.NO_COMPLIANCE_MEASUREMENT.value)

    _, page = validate_paginated(api.list_statistical_evaluations(UTILITY_ADMIN_HEADERS))
    assert page["total_count"] == 0

    stocked_program = fixtures.read_program(api, stocked["program_id"])
    assert stocked_program["phase"] == PHASE_DETECTION
    assert stocked_program["last_validated_event_id"] == last_round["id"]
    a.assert_date(
        stocked_program["next_sampling_due_date"], "2026-05-11", "next_sampling_due_date"
    )
    barren_program = fixtures.read_program(api, barren["program_id"])
    assert barren_program["phase"] == PHASE_DETECTION
    assert barren_program["last_validated_event_id"] is None
    assert barren_program["next_sampling_due_date"] is None
    assert (
        fixtures.read_unit(api, stocked["unit_id"])["compliance_posture"] == POSTURE_COMPLIANT
    )
