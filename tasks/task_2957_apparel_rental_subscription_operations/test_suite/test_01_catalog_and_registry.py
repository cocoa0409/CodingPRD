"""Catalog acquisition, technician registry, depth planning and the logical clock.

Covers the provisioning half of the service: membership plan tiers, technician
certifications, style acquisition with its derived depth block, physical fleet
build-out, the pagination and enum contracts on collection reads, and the
admin-only logical clock that every window comparison is measured against.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_DUPLICATE_CODE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_STYLE_NOT_FOUND,
    ERR_WINDOW_IN_PAST,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_depth_fields,
    assert_error,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import Scenario, standard_catalog


def test_membership_plan_creation_returns_every_declared_field(scenario: Scenario) -> None:
    """A created plan echoes all eight commercial inputs plus its housekeeping block.

    PRD §3.1: "Four numbers define what the tier entitles a member to: `item_slots`, the maximum number of garment units the member may hold or have committed at one time, which must be at least 1 and at most 8"

    Design: Corner/entities/entity_membership_plan_creation_returns_every_declared_field
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    plan = assert_created(
        scenario.client.create_membership_plan(F.sig4_plan_payload(), scenario.admin)
    )

    assert_fields(
        plan,
        code=K.PLAN_SIG4_CODE,
        name=K.PLAN_SIG4_NAME,
        item_slots=K.PLAN_SIG4_ITEM_SLOTS,
        monthly_swaps_allowed=K.PLAN_SIG4_SWAPS_ALLOWED,
        shipping_cadence_days=K.PLAN_SIG4_CADENCE_DAYS,
    )
    assert_money(
        plan,
        monthly_fee_cents=K.PLAN_SIG4_MONTHLY_FEE_CENTS,
        waiver_monthly_fee_cents=K.PLAN_SIG4_WAIVER_FEE_CENTS,
        waiver_coverage_cents=K.PLAN_SIG4_WAIVER_COVERAGE_CENTS,
    )
    assert_common_fields(plan, expected_version=1)


def test_style_retrieval_returns_stored_row_with_derived_depth_fields(
    scenario: Scenario,
) -> None:
    """A style read carries the stored acquisition inputs and the derived depth block.

    PRD §3.1: "`depth_gap_units` is the shortfall of active units against required units, floored at zero so a style that is over-bought reports a gap of zero rather than a negative number"

    Design: Corner/entities/entity_style_retrieval_returns_stored_row_with_derived_depth_fields
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()

    read = assert_ok(scenario.client.get_style(style["id"], scenario.planner))

    assert_fields(read, style_code=K.STYLE_GOWN_CODE, size_run=K.STYLE_GOWN_SIZE_RUN)
    assert_money(
        read,
        retail_price_cents=K.STYLE_GOWN_RETAIL_CENTS,
        acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
    )
    assert_depth_fields(
        read,
        floor_ready_unit_count=0,
        active_unit_count=0,
        required_depth_units=3,
        depth_gap_units=3,
        replenishment_flag=True,
        demand_score=0,
    )


def test_rental_unit_listing_is_paginated_with_total_count_and_has_more(
    scenario: Scenario,
) -> None:
    """Two pages of a three-unit fleet report a stable total and a truthful has_more.

    PRD §2.3: "`total_count` is the number of records matching the filters before pagination is applied and `has_more` indicates whether any matching record remains beyond the current page"

    Design: Corner/entities/entity_rental_unit_listing_is_paginated_with_total_count_and_has_more
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()
    scenario.add_units(
        style["id"], (K.UNIT_GOWN_001, K.UNIT_GOWN_002, K.UNIT_GOWN_003)
    )

    first_page = scenario.client.list_rental_units(
        scenario.planner, {"style_id": style["id"], "limit": 2, "offset": 0}
    )
    second_page = scenario.client.list_rental_units(
        scenario.planner, {"style_id": style["id"], "limit": 2, "offset": 2}
    )

    assert_list(
        first_page, total_count=3, has_more=True, limit=2, offset=0, page_size=2
    )
    assert_list(second_page, total_count=3, has_more=False, offset=2, page_size=1)


def test_member_get_with_unknown_id_returns_member_not_found(scenario: Scenario) -> None:
    """A member path identifier that resolves to nothing reports the member family.

    PRD §2.5: "An unresolvable identifier yields 404 with the error matching the missing resource kind"

    Design: Corner/entities/entity_member_get_with_unknown_id_returns_member_not_found
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    response = scenario.client.get_member(K.UNKNOWN_UUID, scenario.admin)

    assert_error(response, ERR_MEMBER_NOT_FOUND)


def test_style_creation_missing_required_field_returns_invalid_request(
    scenario: Scenario,
) -> None:
    """Acquiring a style without its retail price is a shape rejection, not an enum one.

    PRD §3.1: "Two prices are captured at acquisition and they serve different purposes: `retail_price_cents`, the manufacturer retail price, is the base for all residual-value and resale arithmetic"

    Design: Corner/entities/entity_style_creation_missing_required_field_returns_invalid_request
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    body = F.gown_style_payload()
    del body["retail_price_cents"]

    response = scenario.client.create_style(body, scenario.planner)

    assert_error(response, ERR_INVALID_REQUEST)
    assert_list(scenario.client.list_styles(scenario.planner), total_count=0)


def test_technician_defaults_applied_when_optional_flags_omitted(
    scenario: Scenario,
) -> None:
    """A technician registered with no flags opens uncertified and ACTIVE.

    PRD §2.10: "`repair_certified` defaults to false and, when true, permits the technician to sign off repair completion and to clear a biohazard quarantine"

    Design: Corner/entities/entity_technician_defaults_applied_when_optional_flags_omitted
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    technician = assert_created(
        scenario.client.create_technician(
            F.technician_payload(K.TECH_UNCERTIFIED_CODE, K.TECH_UNCERTIFIED_NAME),
            scenario.admin,
        )
    )

    assert_fields(
        technician,
        employee_code=K.TECH_UNCERTIFIED_CODE,
        full_name=K.TECH_UNCERTIFIED_NAME,
        repair_certified=False,
        photography_certified=False,
        status=K.TECH_ACTIVE,
    )
    assert_common_fields(technician, expected_version=1)


def test_style_computed_depth_is_not_the_supplied_planned_depth(scenario: Scenario) -> None:
    """A planner's intended depth is stored but never substituted for the derivation.

    PRD §3.1: "`planned_depth_units` is recorded for merchandising reference only and is never enforced against the actual fleet."

    Design: Corner/entities/entity_style_computed_depth_is_not_the_supplied_planned_depth
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    style = assert_created(
        scenario.client.create_style(
            F.gown_style_payload(planned_depth_units=9), scenario.planner
        )
    )

    assert_fields(style, planned_depth_units=9)
    assert_depth_fields(
        style,
        required_depth_units=3,
        depth_gap_units=3,
        replenishment_flag=True,
        active_unit_count=0,
    )


def test_rental_unit_system_fields_are_minted_by_the_server(scenario: Scenario) -> None:
    """A freshly bought garment opens on the floor with every event stamp still null.

    PRD §3.1: "A newly added unit opens `IN_STOCK` and `FLOOR_READY`, with `turns_completed` at 0 and `quarantine_hold` false, and it is therefore immediately allocatable."

    Design: Corner/entities/entity_rental_unit_system_fields_are_minted_by_the_server
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()

    unit = assert_created(
        scenario.client.create_rental_unit(
            style["id"],
            F.rental_unit_payload(
                K.UNIT_GOWN_001,
                K.SIZE_M,
                acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
                condition_grade=K.GRADE_A,
            ),
            scenario.planner,
        )
    )

    assert_unit_position(
        unit,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=K.GRADE_A,
        quarantine_hold=False,
    )
    assert_fields(unit, turns_completed=0, style_id=style["id"])
    assert_money(unit, cumulative_servicing_cost_cents=0, realized_revenue_cents=0)
    assert_null(unit, "last_returned_at", "retired_at", "retirement_reason")
    assert_common_fields(unit, expected_version=1)


def test_style_category_outside_the_declared_enum_returns_422(scenario: Scenario) -> None:
    """An undeclared category is an enum rejection and persists nothing.

    PRD §2.5: "Rank 9 checks that every enum-typed body field, and every enum-typed list filter, carries a declared member value, otherwise `ERR_INVALID_ENUM_VALUE` (422)."

    Design: Corner/entities/entity_style_category_outside_the_declared_enum_returns_422
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    response = scenario.client.create_style(
        F.gown_style_payload(category=K.CATEGORY_OUTERWEAR_INVALID), scenario.planner
    )

    assert_error(response, ERR_INVALID_ENUM_VALUE)
    assert_list(scenario.client.list_styles(scenario.planner), total_count=0)


def test_rental_unit_creation_under_unknown_style_returns_style_not_found(
    scenario: Scenario,
) -> None:
    """Adding depth beneath a style that does not exist reports the style family.

    PRD §3.1: "an unresolvable style identifier anywhere yields `ERR_STYLE_NOT_FOUND`"

    Design: Corner/entities/entity_rental_unit_creation_under_unknown_style_returns_style_not_found
    """
    scenario.set_clock(K.CLOCK_AUG_03)

    response = scenario.client.create_rental_unit(
        K.UNKNOWN_UUID,
        F.rental_unit_payload(
            K.UNIT_GOWN_001,
            K.SIZE_M,
            acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
            condition_grade=K.GRADE_A,
        ),
        scenario.planner,
    )

    assert_error(response, ERR_STYLE_NOT_FOUND)
    assert_list(scenario.client.list_rental_units(scenario.planner), total_count=0)


def test_duplicate_style_code_is_rejected_while_a_fresh_code_passes(
    scenario: Scenario,
) -> None:
    """The uniqueness constraint bites on the code alone and lets a new code through.

    PRD §3.1: "A style whose `style_code` collides with an existing one is refused at rank 11 with `ERR_DUPLICATE_CODE`"

    Design: Corner/validations/validation_duplicate_style_code_is_rejected_while_a_fresh_code_passes
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    scenario.create_style()

    collision = scenario.client.create_style(
        F.style_payload(
            style_code=K.STYLE_GOWN_CODE,
            brand="Copycat",
            category=K.CATEGORY_DRESS,
            retail_price_cents=9900,
            acquisition_cost_cents=4000,
            size_run=[K.SIZE_S],
            expected_rental_turns_per_unit=5,
            planned_eol_value_cents=500,
            forecast_monthly_requests=1,
            avg_rental_days=3,
        ),
        scenario.planner,
    )
    fresh = scenario.client.create_style(F.knit_style_payload(), scenario.planner)

    assert_error(collision, ERR_DUPLICATE_CODE)
    assert_fields(assert_created(fresh), style_code=K.STYLE_KNIT_CODE)
    rows, _ = assert_list(
        scenario.client.list_styles(scenario.planner, {"limit": 50}), total_count=2
    )
    assert all(row["brand"] != "Copycat" for row in rows), (
        f"the refused style was persisted anyway: {[row['brand'] for row in rows]}"
    )


def test_pagination_limit_zero_and_negative_offset_are_rejected(
    scenario: Scenario,
) -> None:
    """A page size of zero and a negative offset both fail the pagination rung.

    PRD §2.3: "A `limit` that is not an integer or falls outside the range from 1 to 100 inclusive, or an `offset` that is negative or not an integer, is rejected at rank 10 of the validation ladder with `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/validations/validation_pagination_limit_zero_is_rejected_while_limit_one_passes
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()
    scenario.add_units(style["id"], (K.UNIT_GOWN_001, K.UNIT_GOWN_002))

    zero_limit = scenario.client.list_rental_units(
        scenario.planner, {"style_id": style["id"], "limit": 0}
    )
    negative_offset = scenario.client.list_rental_units(
        scenario.planner, {"style_id": style["id"], "offset": -1}
    )
    single = scenario.client.list_rental_units(
        scenario.planner, {"style_id": style["id"], "limit": 1}
    )

    assert_error(zero_limit, ERR_INVALID_PAGINATION)
    assert_error(negative_offset, ERR_INVALID_PAGINATION)
    assert_list(single, total_count=2, has_more=True, limit=1, page_size=1)


def test_undeclared_enum_members_are_refused_in_bodies_and_in_list_filters(
    scenario: Scenario,
) -> None:
    """The enum rung guards write bodies and collection filters with the same code.

    PRD §2.3: "must carry a declared member of that enum; anything else is rejected at rank 9 with `ERR_INVALID_ENUM_VALUE` (422)"

    Design: Corner/validations/validation_undeclared_enum_members_are_refused_in_bodies_and_in_list_filters
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()
    scenario.add_units(style["id"], (K.UNIT_GOWN_001,))

    undeclared_body = scenario.client.create_style(
        F.cape_style_payload(category=K.CATEGORY_COUTURE_INVALID), scenario.planner
    )
    undeclared_filter = scenario.client.list_rental_units(
        scenario.planner, {"availability_state": K.AVAIL_ON_HOLD_INVALID}
    )
    declared_filter = scenario.client.list_rental_units(
        scenario.planner, {"availability_state": K.AVAIL_IN_STOCK}
    )

    assert_error(undeclared_body, ERR_INVALID_ENUM_VALUE)
    assert_list(scenario.client.list_styles(scenario.planner), total_count=1)
    assert_error(undeclared_filter, ERR_INVALID_ENUM_VALUE)
    rows, _ = assert_list(
        declared_filter, total_count=1, has_more=False, page_size=1
    )
    assert_unit_position(rows[0], availability_state=K.AVAIL_IN_STOCK)


def test_technician_patch_flips_one_certification_only(scenario: Scenario) -> None:
    """Revoking the repair flag leaves the photography flag and the status alone.

    PRD §2.10: "A `PlatformAdmin` provisions technicians and may later revise `repair_certified`, `photography_certified` or `status` on an existing technician record."

    Design: Corner/endpoints/endpoint_technician_patch_flips_one_certification_only
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    scenario.create_inspector()
    repairer = scenario.create_repairer()

    patched = assert_ok(
        scenario.client.update_technician(
            repairer["id"],
            F.technician_patch_payload(repair_certified=False),
            scenario.admin,
        )
    )

    assert_fields(
        patched,
        employee_code=K.TECH_REPAIRER_CODE,
        full_name=K.TECH_REPAIRER_NAME,
        repair_certified=False,
        photography_certified=True,
        status=K.TECH_ACTIVE,
    )
    assert_common_fields(patched, expected_version=2)
    assert_list(
        scenario.client.list_technicians(scenario.admin, {"status": K.TECH_ACTIVE}),
        total_count=2,
    )


def test_depth_plan_patch_rederives_the_requirement_but_not_from_planned_depth(
    scenario: Scenario,
) -> None:
    """A revised forecast re-runs the derivation while planned depth stays inert.

    PRD §3.1: "Revising the plan later is a targeted operation: the planner may supply any combination of `forecast_monthly_requests`, `avg_rental_days` and `planned_depth_units`, and omitted fields keep their stored values."

    Design: Corner/endpoints/endpoint_depth_plan_patch_rederives_the_requirement_but_not_from_planned_depth
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style()
    scenario.add_units(style["id"], (K.UNIT_GOWN_001,))

    revised = assert_ok(
        scenario.client.update_depth_plan(
            style["id"],
            F.depth_plan_payload(forecast_monthly_requests=10, avg_rental_days=5),
            scenario.planner,
        )
    )
    assert_fields(
        revised,
        forecast_monthly_requests=10,
        avg_rental_days=5,
        planned_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
    )
    assert_depth_fields(
        revised,
        active_unit_count=1,
        required_depth_units=3,
        depth_gap_units=2,
        replenishment_flag=True,
    )

    inert = assert_ok(
        scenario.client.update_depth_plan(
            style["id"], F.depth_plan_payload(planned_depth_units=9), scenario.planner
        )
    )
    assert_fields(inert, planned_depth_units=9, forecast_monthly_requests=10)
    assert_depth_fields(inert, required_depth_units=3, depth_gap_units=2)
    assert_list(
        scenario.client.list_styles(scenario.planner, {"replenishment_flag": True}),
        total_count=1,
    )


def test_clock_endpoint_moves_the_window_boundary_it_is_compared_against(
    scenario: Scenario,
) -> None:
    """Booking yesterday is refused and booking the clock's own day is matched.

    PRD §3.3: "the start date must not be earlier than the current logical clock date, so a member may book for today or any future day but never for yesterday"

    Design: Corner/endpoints/endpoint_clock_endpoint_moves_the_window_boundary_it_is_compared_against
    """
    catalog = standard_catalog(scenario)

    echoed = scenario.set_clock(K.CLOCK_AUG_20_0900)
    assert_instant(echoed["current_utc"], K.CLOCK_AUG_20_0900, "current_utc")

    yesterday = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id, K.SIZE_M, *K.WINDOW_AUG_19_23
        ),
        Scenario.member_headers(catalog.member),
    )
    assert_error(yesterday, ERR_WINDOW_IN_PAST)

    today = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_24
    )
    assert_fields(today, state=K.RES_MATCHED)
    assert_instant(today["matched_at"], K.CLOCK_AUG_20_0900, "matched_at")
    assert_list(
        scenario.client.list_reservations(Scenario.member_headers(catalog.member)),
        total_count=1,
    )
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]), availability_state=K.AVAIL_RESERVED
    )


def test_required_depth_is_a_ceiling_at_an_exact_planning_month_multiple(
    scenario: Scenario,
) -> None:
    """Sixty committed garment-days require exactly two units, never three.

    PRD §3.1: "so 60 committed garment-days give exactly 2 required units while 61 give 3"

    Design: Difficulty/boundary_precision_check/required_depth_ceil_at_exact_planning_month_multiple
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style(F.knit_style_payload())

    read = assert_ok(scenario.client.get_style(style["id"], scenario.planner))

    assert_fields(
        read,
        forecast_monthly_requests=K.STYLE_KNIT_FORECAST_MONTHLY,
        avg_rental_days=K.STYLE_KNIT_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_KNIT_PLANNED_DEPTH,
    )
    assert_depth_fields(
        read,
        active_unit_count=0,
        required_depth_units=2,
        depth_gap_units=2,
        replenishment_flag=True,
    )


def test_required_depth_steps_up_one_unit_just_past_the_planning_month_multiple(
    scenario: Scenario,
) -> None:
    """One more forecast request crosses the multiple and buys a whole extra unit.

    PRD §3.1: "`required_depth_units` is that committed-day figure divided by the thirty-day planning month and **rounded up to the next whole unit**"

    Design: Difficulty/boundary_precision_check/required_depth_ceil_at_exact_planning_month_multiple
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    style = scenario.create_style(F.knit_style_payload())

    revised = assert_ok(
        scenario.client.update_depth_plan(
            style["id"],
            F.depth_plan_payload(forecast_monthly_requests=11),
            scenario.planner,
        )
    )

    assert_fields(
        revised,
        forecast_monthly_requests=11,
        avg_rental_days=K.STYLE_KNIT_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_KNIT_PLANNED_DEPTH,
    )
    assert_depth_fields(
        revised,
        active_unit_count=0,
        required_depth_units=3,
        depth_gap_units=3,
        replenishment_flag=True,
    )
