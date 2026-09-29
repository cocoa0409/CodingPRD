"""Inclusive limits, checked from both sides with everything else held equal."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_DRAFT,
    AGREEMENT_STATUS_QUALIFIED,
    WELL_ROLE_BACKGROUND,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS

COMMITMENT_WINDOW = {"commitment_start_on": "2026-01-01", "commitment_end_on": "2026-12-31"}


def case_two_agreements_astride_the_loi_ceiling(api):
    """Two agreements identical but for a single hundredth of a percent of carbon."""
    world = fixtures.seed_unit(api, "IMP-0011")
    at_limit = fixtures.draft_agreement(
        api, world, "AGR-AT-LIMIT", loi_percent=6.00, **COMMITMENT_WINDOW
    )
    over_limit = fixtures.draft_agreement(
        api, world, "AGR-OVER-LIMIT", loi_percent=6.01, **COMMITMENT_WINDOW
    )
    world["at_limit_id"] = at_limit["id"]
    world["over_limit_id"] = over_limit["id"]
    world["at_limit"] = at_limit
    world["over_limit"] = over_limit
    return world


def qualify(api, world, agreement_id):
    return api.qualify_reuse_agreement(
        agreement_id, factories.qualify_agreement_payload("2026-08-01"), world["geotech_headers"]
    )


def read_agreement(api, agreement_id):
    return get_success_data(api.get_reuse_agreement(agreement_id, UTILITY_ADMIN_HEADERS))


def case_two_networks_astride_the_downgradient_floor(api):
    """Unit A with three downgradient wells and unit B with two, nothing else differing."""
    world = fixtures.seed_unit(api, "IMP-0012")
    fixtures.install_standard_network(api, world["unit_id"], world["hydro_headers"])
    fixtures.configure_program(api, world["program_id"], world["hydro_headers"])

    short_unit = fixtures.create_unit(api, "IMP-0013")
    world["short_unit_id"] = short_unit["id"]
    world["short_program_id"] = short_unit["monitoring_program_id"]
    fixtures.install_well(
        api, short_unit["id"], world["hydro_headers"], "BG-01", WELL_ROLE_BACKGROUND
    )
    fixtures.install_well(api, short_unit["id"], world["hydro_headers"], "DG-01")
    fixtures.install_well(api, short_unit["id"], world["hydro_headers"], "DG-02")
    fixtures.configure_program(api, world["short_program_id"], world["hydro_headers"])
    return world


def test_ash_at_exactly_six_percent_loss_on_ignition_meets_the_class_f_specification(api):
    """The ceiling is inclusive, so 6.00 qualifies with a score of 70.30.

    PRD: The boolean `meets_astm_c618_class_f` is true exactly when all three of the following hold: `loi_percent` is at most 6.00, `retained_325_percent` is at most 34.00, and `oxide_sum_percent` is at least 70.00. All three comparisons are inclusive at the limit, so 6.00, 34.00 and 70.00 respectively all meet the specification while 6.01, 34.01 and 69.99 all fail it.
    PRD: An agreement that clears both checks records `qualified_on` and `qualified_by` from the acting engineer's header identity, and then branches on its recomputed score: a score of at least 50.00 moves it `DRAFT` -> `QUALIFIED`
    Design: Difficulty/boundary_precision_check/loi_exactly_six_percent_meets_class_f_and_six_point_zero_one_fails
    """
    world = case_two_agreements_astride_the_loi_ceiling(api)
    assert world["at_limit"]["meets_astm_c618_class_f"] is True

    qualified = get_success_data(qualify(api, world, world["at_limit_id"]))

    assert qualified["meets_astm_c618_class_f"] is True
    a.assert_two_dp(qualified["qualification_score"], 70.30, "qualification_score")
    assert qualified["status"] == AGREEMENT_STATUS_QUALIFIED
    assert qualified["qualified_by"] == world["geotech_id"]


def test_ash_one_hundredth_above_the_ceiling_is_refused_and_keeps_its_draft(api):
    """6.01 fails the specification outright while scoring only 0.03 lower.

    PRD: Ash that fails the Class F specification is refused outright with `ERR_ASH_QUALITY_FAILS_SPEC` (HTTP 422) and the agreement stays in `DRAFT` - the operator may revise nothing about it, but the record is not burned.
    Design: Difficulty/boundary_precision_check/loi_exactly_six_percent_meets_class_f_and_six_point_zero_one_fails
    """
    world = case_two_agreements_astride_the_loi_ceiling(api)
    assert world["over_limit"]["meets_astm_c618_class_f"] is False
    a.assert_two_dp(world["over_limit"]["qualification_score"], 70.27, "qualification_score")

    response = qualify(api, world, world["over_limit_id"])

    validate_error(response, ApiErrorId.ASH_QUALITY_FAILS_SPEC.value)
    unchanged = read_agreement(api, world["over_limit_id"])
    assert unchanged["status"] == AGREEMENT_STATUS_DRAFT
    assert unchanged["qualified_on"] is None
    assert unchanged["qualified_by"] is None


def test_exactly_three_downgradient_wells_certifies_the_network(api):
    """The floor is inclusive, so a network sitting on it is ready.

    PRD: The readiness test the server runs looks at four things at once: that at least 1 certified background well exists, that at least 3 certified downgradient wells exist, and that both background window bounds have been configured to non-null values. Both well comparisons are inclusive, so exactly three certified downgradient wells is sufficient.
    PRD: On success the program records `network_certified` true, `network_certified_on` from the supplied date, and `network_certified_by` from the acting hydrogeologist's header identity.
    Design: Difficulty/boundary_precision_check/exactly_three_downgradient_wells_certifies_network_and_two_does_not
    """
    world = case_two_networks_astride_the_downgradient_floor(api)

    program = fixtures.certify_network(
        api, world["program_id"], world["hydro_headers"], "2025-01-05"
    )

    assert program["network_certified"] is True
    a.assert_date(program["network_certified_on"], "2025-01-05", "network_certified_on")
    assert program["network_certified_by"] == world["hydro_id"]
    assert program["background_well_count"] == 1
    assert program["downgradient_well_count"] == 3


def test_two_downgradient_wells_leaves_the_network_uncertified(api):
    """One well short of the floor is refused and nothing is stamped.

    PRD: A network short of a background well is refused with `ERR_NO_BACKGROUND_WELL` (HTTP 422), and one short of downgradient wells with `ERR_INSUFFICIENT_DOWNGRADIENT_WELLS` (HTTP 422)
    Design: Difficulty/boundary_precision_check/exactly_three_downgradient_wells_certifies_network_and_two_does_not
    """
    world = case_two_networks_astride_the_downgradient_floor(api)

    response = api.certify_network(
        world["short_program_id"],
        factories.certify_network_payload("2025-01-05"),
        world["hydro_headers"],
    )

    validate_error(response, ApiErrorId.INSUFFICIENT_DOWNGRADIENT_WELLS.value)
    program = fixtures.read_program(api, world["short_program_id"])
    assert program["network_certified"] is False
    assert program["network_certified_on"] is None
    assert program["network_certified_by"] is None
    assert program["downgradient_well_count"] == 2
