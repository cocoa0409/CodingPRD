"""Exclusivity over an occupied resource, probed at the adjacency boundary.

A field's ground is an area and a field's commitment is a half-open interval of crop
years; in both cases touching is permitted and intruding is not, and both rules are
scoped so that a neighbour's holdings are irrelevant.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_COMMITMENT_PERIOD_OVERLAP,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_FIELD_BOUNDARY_OVERLAP,
    ERR_PRACTICE_COOLDOWN_ACTIVE,
)
from test_helpers.assertions import assert_acres
from test_helpers.constants import (
    CLOCK_2030,
    ENROLLMENT_DRAFT,
    PRACTICE_REDUCED_TILLAGE,
    SOIL_CLAY,
    SOIL_SAND,
)
from test_helpers.factories import (
    boundary_payload,
    enrollment_payload,
    grower_payload,
    practice_standard_payload,
)
from test_helpers.test_users import ADMIN_HEADERS


def _reduced_tillage_standard(scenario):
    """A second published methodology for a different practice code."""
    return get_success_data(
        scenario.api.create_practice_standard(
            practice_standard_payload(
                practice_code=PRACTICE_REDUCED_TILLAGE,
                max_prior_adoption_pct=25.00,
                uncertainty_base_pct=12.00,
                sequestration_rate_per_acre=0.2000,
                modeled_baseline_rate_per_acre=0.1500,
                telemetry_required=False,
            ),
            ADMIN_HEADERS,
        )
    )


def test_touching_rectangles_are_admitted_and_intruding_ones_are_not(scenario):
    """A shared edge and a shared corner both have zero intersection area and register, while
    a one-unit intrusion and an enclosing rectangle are both refused.

    PRD §3.1: "Zero-area intersections are explicitly permitted: two fields may share an
    edge exactly, and two fields may meet at a single corner. A one-grid-unit intrusion
    into the interior, however, is an overlap and is refused."

    Design: Difficulty/resource_temporal_overlap/field_boundary_rectangles_touch_versus_intrude
    """
    scenario.set_clock()
    scenario.create_grower()
    scenario.create_field(field_name="Quilt A", county_code="ND-017")

    east = get_success_data(
        scenario.api.create_field(
            scenario.grower_id,
            boundary_payload(2000, 0, 4000, 2000, field_name="Quilt B shares the east edge",
                             soil_group=SOIL_CLAY, county_code="ND-017"),
            ADMIN_HEADERS,
        )
    )
    corner = get_success_data(
        scenario.api.create_field(
            scenario.grower_id,
            boundary_payload(2000, 2000, 4000, 4000,
                             field_name="Quilt C touches only the corner",
                             soil_group=SOIL_SAND, county_code="ND-017"),
            ADMIN_HEADERS,
        )
    )

    assert_acres(east["mapped_acres"], 1000.00)
    assert_acres(corner["mapped_acres"], 1000.00)

    intruder = scenario.api.create_field(
        scenario.grower_id,
        boundary_payload(1999, 0, 3999, 2000, field_name="Quilt D intrudes one unit",
                         county_code="ND-017"),
        ADMIN_HEADERS,
    )
    swallower = scenario.api.create_field(
        scenario.grower_id,
        boundary_payload(0, 0, 4000, 4000, field_name="Quilt E swallows A",
                         gross_acres=4010.00, county_code="ND-017"),
        ADMIN_HEADERS,
    )

    validate_error(intruder, ERR_FIELD_BOUNDARY_OVERLAP, 409)
    validate_error(swallower, ERR_FIELD_BOUNDARY_OVERLAP, 409)
    fields, _meta = validate_paginated(
        scenario.api.list_fields({"grower_id": scenario.grower_id}, ADMIN_HEADERS)
    )
    assert len(fields) == 3


def test_boundary_exclusivity_is_scoped_to_one_grower(scenario):
    """A second grower may register the identical rectangle, because the check only looks at
    the fields of the same grower.

    PRD §3.1: "Fields belonging to other growers are irrelevant to this check."

    Design: Difficulty/resource_temporal_overlap/field_boundary_rectangles_touch_versus_intrude
    """
    scenario.set_clock()
    scenario.create_grower()
    scenario.create_field(field_name="Quilt A", county_code="ND-017")
    neighbour = get_success_data(
        scenario.api.create_grower(
            grower_payload(legal_name="Neighbour Acres", operator_type="SOLE_PROPRIETOR",
                           mailing_state="ND"),
            ADMIN_HEADERS,
        )
    )

    same_ground = get_success_data(
        scenario.api.create_field(
            neighbour["id"],
            boundary_payload(0, 0, 2000, 2000, field_name="Same rectangle other grower",
                             county_code="ND-017"),
            ADMIN_HEADERS,
        )
    )

    assert_acres(same_ground["mapped_acres"], 1000.00)
    assert same_ground["grower_id"] == neighbour["id"]
    mine, _meta = validate_paginated(
        scenario.api.list_fields({"grower_id": scenario.grower_id}, ADMIN_HEADERS)
    )
    assert len(mine) == 1


def test_a_commitment_interval_still_occupies_its_final_crop_year(scenario):
    """A five-year commitment opened in 2026 still holds 2030, so a different practice
    starting in 2030 is refused on the temporal rule alone.

    PRD §3.3: "A new enrollment on the same field whose interval intersects the interval of
    a non-terminal enrollment is refused with `ERR_COMMITMENT_PERIOD_OVERLAP`, while an
    interval that begins exactly at the incumbent's end year is accepted because the
    incumbent's range excludes that year."

    Design: Difficulty/resource_temporal_overlap/commitment_period_half_open_interval_adjacency
    """
    scenario.set_clock()
    scenario.publish_standard()
    tillage = _reduced_tillage_standard(scenario)
    scenario.create_grower()
    scenario.mapped_field(field_name="Interval Quarter", county_code="OH-041")
    incumbent = scenario.create_enrollment()
    scenario.set_clock(CLOCK_2030)

    response = scenario.api.create_enrollment(
        enrollment_payload(scenario.field_id, tillage["id"], commitment_years=4,
                           start_crop_year=2030, per_credit_share_pct=55.00),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_COMMITMENT_PERIOD_OVERLAP, 409)
    # The practice code differs and nothing was terminated, so neither neighbouring rule fired.
    assert ERR_DUPLICATE_ENROLLMENT not in response.text
    assert ERR_PRACTICE_COOLDOWN_ACTIVE not in response.text
    assert scenario.reload_enrollment(incumbent["id"])["status"] == ENROLLMENT_DRAFT


def test_a_commitment_starting_at_the_exclusive_end_year_is_admitted(scenario):
    """The same request moved one crop year later begins exactly where the incumbent's
    half-open interval ends, and is accepted.

    PRD §3.3: "Treat an enrollment's occupied interval as the half-open range of crop years
    beginning at its `start_crop_year` and ending immediately before `start_crop_year` plus
    `commitment_years` — so a five-year commitment starting in 2026 occupies 2026 through
    2030 inclusive and releases the field for 2031."

    Design: Difficulty/resource_temporal_overlap/commitment_period_half_open_interval_adjacency
    """
    scenario.set_clock()
    scenario.publish_standard()
    tillage = _reduced_tillage_standard(scenario)
    scenario.create_grower()
    scenario.mapped_field(field_name="Interval Quarter", county_code="OH-041")
    scenario.create_enrollment()
    scenario.set_clock(CLOCK_2030)

    successor = get_success_data(
        scenario.api.create_enrollment(
            enrollment_payload(scenario.field_id, tillage["id"], commitment_years=4,
                               start_crop_year=2031, per_credit_share_pct=55.00),
            ADMIN_HEADERS,
        )
    )

    assert successor["start_crop_year"] == 2031
    assert successor["commitment_years"] == 4
    assert successor["practice_code"] == PRACTICE_REDUCED_TILLAGE
    assert successor["status"] == ENROLLMENT_DRAFT
    enrollments, _meta = validate_paginated(
        scenario.api.list_enrollments({"field_id": scenario.field_id}, ADMIN_HEADERS)
    )
    assert len(enrollments) == 2
