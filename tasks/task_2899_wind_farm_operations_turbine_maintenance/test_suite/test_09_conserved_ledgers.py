"""Two conserved totals held to the unit and to the cent across long sequences."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_crane_costs,
    assert_farm_buckets,
    assert_stock_line,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    CRANE_MOBILIZED,
    CRANE_REQUESTED,
    REPLACEMENT_CANCELLED,
    REPLACEMENT_EXECUTED,
    REPLACEMENT_PLANNED,
    SETTLEMENT_APPROVED,
    SETTLEMENT_DRAFT,
    SETTLEMENT_VOID,
    STOCK_BELOW_REORDER_POINT,
    STOCK_IN_STOCK,
    STOCK_OUT_OF_STOCK,
    WO_IN_PROGRESS,
)
from test_helpers.factories import landowner_settlement_payload, replacement_payload
from test_helpers.fixtures import (
    read_crane,
    read_farm,
    read_replacement,
    read_settlement,
    read_spare_part,
    read_work_order,
    setup_conserved_stock_line,
    setup_opex_ledger_farm,
)
from test_helpers.test_users import (
    make_commercial_headers,
    make_crew_lead_headers,
    make_engineer_headers,
    make_planner_headers,
    make_site_admin_headers,
)


def _replacement(api, site, component_type="GEARBOX", estimated_lift_hours=12):
    """Draw one unit from the conserved stock line under the in-progress order."""
    return api.create_component_replacement(
        replacement_payload(
            site["order"]["id"],
            site["part"]["id"],
            component_type=component_type,
            estimated_lift_hours=estimated_lift_hours,
        ),
        make_planner_headers(),
    )


def test_two_refusals_and_a_cancellation_never_move_the_conserved_unit_total(api):
    """The three sub-counters swing while the accounted total sits still at two.

    The contract states: "Each `SparePart` line carries `quantity_on_hand`,
    `quantity_reserved` and `quantity_consumed`, plus a conserved total,
    `total_units_accounted`, which must always equal their sum."  It continues: "Only
    a goods receipt raises `total_units_accounted`; every reservation, execution and
    cancellation merely moves units between the three buckets and leaves the total
    untouched."  Of the derived status it states: "A line's `status` is always
    derived, never supplied: it is `OUT_OF_STOCK` when `quantity_on_hand` is exactly
    0, `BELOW_REORDER_POINT` when `quantity_on_hand` is above 0 but strictly below
    `reorder_point`, and `IN_STOCK` when `quantity_on_hand` is at or above
    `reorder_point`."  And: "`procurement_flag` is true exactly when `status` is
    anything other than `IN_STOCK`."  Of a cancellation it states: "One unit returns
    from the part's `quantity_reserved` to its `quantity_on_hand`, leaving
    `total_units_accounted` unchanged, and the part's `status` and `procurement_flag`
    are re-derived from the restored balance."  And of the parent hop: "When the
    parent is in any other state this hop does nothing."

    Design: Difficulty/compensating_invariant/spare_part_unit_conservation_survives_refusals_cancellation_execution_and_a_receipt
    """
    site = setup_conserved_stock_line(api)
    part_id = site["part"]["id"]

    assert_stock_line(
        read_spare_part(api, part_id),
        2,
        0,
        0,
        2,
        status=STOCK_IN_STOCK,
        procurement_flag=False,
    )

    first = validate_success(_replacement(api, site), 201)
    assert first["state"] == REPLACEMENT_PLANNED
    assert_stock_line(
        read_spare_part(api, part_id),
        1,
        1,
        0,
        2,
        status=STOCK_BELOW_REORDER_POINT,
        procurement_flag=True,
    )

    wrong_type = _replacement(api, site, component_type="BLADE", estimated_lift_hours=4)
    validate_error(wrong_type, "ERR_SPARE_PART_TYPE_MISMATCH", 422)
    assert_stock_line(read_spare_part(api, part_id), 1, 1, 0, 2)

    second = validate_success(_replacement(api, site, estimated_lift_hours=6), 201)
    assert_stock_line(
        read_spare_part(api, part_id),
        0,
        2,
        0,
        2,
        status=STOCK_OUT_OF_STOCK,
        procurement_flag=True,
    )

    before_refusal = read_spare_part(api, part_id)
    empty_draw = _replacement(api, site, estimated_lift_hours=3)
    validate_error(empty_draw, "ERR_SPARE_PART_UNAVAILABLE", 422)
    assert_stock_line(read_spare_part(api, part_id), 0, 2, 0, 2, status=STOCK_OUT_OF_STOCK)
    assert_version_unchanged(before_refusal, read_spare_part(api, part_id))

    cancelled = validate_success(
        api.cancel_replacement(
            second["id"], "second gearbox deferred to next campaign", make_planner_headers()
        )
    )
    assert cancelled["state"] == REPLACEMENT_CANCELLED
    assert cancelled["execution_path"] is None
    assert_cents(cancelled["allocated_crane_cost_cents"], 0, "cancelled.allocated_crane_cost_cents")
    assert_stock_line(
        read_spare_part(api, part_id),
        1,
        1,
        0,
        2,
        status=STOCK_BELOW_REORDER_POINT,
        procurement_flag=True,
    )
    assert read_crane(api, site["crane"]["id"])["state"] == CRANE_REQUESTED
    assert read_work_order(api, site["order"]["id"])["state"] == WO_IN_PROGRESS


def test_only_the_goods_receipt_raises_the_total_that_execution_merely_shuffles(api):
    """A refused branch, a crane reservation, an execution and a receipt in one line.

    The contract states: "It is permitted only when the replacement's
    `component_type` is `GENERATOR` **and** the reserved part's `uptower_repairable`
    is true; a part that is not up-tower repairable is refused with
    `ERR_UPTOWER_NOT_PERMITTED`."  Of execution it states: "Both branches move exactly
    one unit from the part's `quantity_reserved` into its `quantity_consumed`, leaving
    `total_units_accounted` unchanged."  It continues: "On the **crane-lift branch**,
    the replacement's `allocated_crane_cost_cents` is added to the farm's
    `maintenance_spend_cents` and the same amount to its `opex_accrued_cents`."  Of a
    receipt it states: "A goods receipt, also a `SiteAdmin` action, adds a
    `quantity_received` to `quantity_on_hand` and to `total_units_accounted`, and
    re-derives `status` and `procurement_flag` from the new balance — this is the only
    event in the system that raises the conserved total."  And of the reservation:
    "A successful reservation sets `execution_path` to `CRANE_LIFT`, stores the
    `crane_mobilization_id`, moves the mobilization `REQUESTED → MOBILIZED` if it was
    still `REQUESTED`, increments its `reserved_replacement_count` by 1, and reprices
    the whole mobilization."

    Design: Difficulty/compensating_invariant/spare_part_unit_conservation_survives_refusals_cancellation_execution_and_a_receipt
    """
    site = setup_conserved_stock_line(api)
    part_id = site["part"]["id"]
    replacement = validate_success(_replacement(api, site), 201)

    wrong_branch = api.plan_uptower(replacement["id"], make_planner_headers())
    validate_error(wrong_branch, "ERR_UPTOWER_NOT_PERMITTED", 422)
    assert read_replacement(api, replacement["id"])["state"] == REPLACEMENT_PLANNED
    assert_stock_line(read_spare_part(api, part_id), 1, 1, 0, 2)

    validate_success(
        api.reserve_crane(replacement["id"], site["crane"]["id"], make_planner_headers())
    )
    assert_stock_line(
        read_spare_part(api, part_id), 1, 1, 0, 2, status=STOCK_BELOW_REORDER_POINT
    )
    crane = read_crane(api, site["crane"]["id"])
    assert crane["state"] == CRANE_MOBILIZED
    assert crane["reserved_replacement_count"] == 1
    assert_crane_costs(
        crane,
        lift_days=2,
        standby_days=0,
        billable_days=2,
        subtotal_cents=19600000,
        volume_credit_cents=1176000,
        total_crane_cost_cents=18424000,
    )
    assert_cents(
        read_replacement(api, replacement["id"])["allocated_crane_cost_cents"],
        18424000,
        "replacement.allocated_crane_cost_cents",
    )

    executed = validate_success(
        api.execute_replacement(replacement["id"], make_crew_lead_headers(site["crew"]["id"]))
    )
    assert executed["state"] == REPLACEMENT_EXECUTED
    assert_stock_line(
        read_spare_part(api, part_id),
        1,
        0,
        1,
        2,
        status=STOCK_BELOW_REORDER_POINT,
        procurement_flag=True,
    )
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        opex_accrued_cents=18424000,
        maintenance_spend_cents=18424000,
        landowner_payable_cents=0,
        road_maintenance_reserve_cents=0,
        community_fund_balance_cents=0,
    )

    validate_success(api.receive_spare_part(part_id, 3, make_site_admin_headers()))
    assert_stock_line(
        read_spare_part(api, part_id),
        4,
        0,
        1,
        5,
        status=STOCK_IN_STOCK,
        procurement_flag=False,
    )


def _p14_settlement(api, farm_id, expected_version):
    """The one settlement body used for parcel P-14 over July 2026."""
    return api.create_landowner_settlement(
        farm_id,
        landowner_settlement_payload(
            expected_version,
            parcel_code="P-14",
            royalty_basis="METERED_ONLY",
            period_start_utc="2026-07-01T00:00:00Z",
            period_end_utc="2026-08-01T00:00:00Z",
            royalty_pct=4.0,
            minimum_payment_cents=200000,
            energy_price_cents_per_kwh=6,
            road_damage_assessment_cents=15000,
        ),
        make_commercial_headers(),
    )


def test_a_draft_posts_nothing_and_approval_splits_it_across_three_buckets(api):
    """Labour and royalty reach the same conserved total from two different sources.

    The contract states: "Each `WindFarm` carries four accumulating buckets —
    `landowner_payable_cents`, `road_maintenance_reserve_cents`,
    `community_fund_balance_cents` and `maintenance_spend_cents` — plus a conserved
    total, `opex_accrued_cents`, which must always equal the sum of those four."  Of
    completion it states: "Alongside those hops, completion posts the labour cost to
    the site ledger, adding `labor_cost_cents` both to the farm's
    `maintenance_spend_cents` and to its `opex_accrued_cents`."  Of a draft it states:
    "A drafted settlement sits in `state` `DRAFT` with `void_reason` null, and it posts
    **nothing** to the farm ledger — a draft is not part of `opex_accrued_cents`."  Of
    approval it states: "Approval makes four postings in one transaction:
    `payment_cents` is added to the farm's `landowner_payable_cents`; `road_levy_cents`
    plus `road_damage_assessment_cents` is added to `road_maintenance_reserve_cents`;
    `community_levy_cents` is added to `community_fund_balance_cents`; and the total of
    those three postings is added to `opex_accrued_cents`, preserving the invariant of
    §2.10 exactly."  Of the levies it states: "`road_levy_cents` is `payment_cents`
    multiplied by the farm's `road_levy_pct` divided by 100, rounded half up to a whole
    cent, and `community_levy_cents` is `payment_cents` multiplied by the farm's
    `community_levy_pct` divided by 100, likewise rounded half up."

    Design: Difficulty/compensating_invariant/farm_opex_ledger_reconciles_to_the_cent_after_a_settlement_is_approved_then_voided
    """
    site = setup_opex_ledger_farm(api)

    completed = validate_success(
        api.complete_work_order(site["order"]["id"], 7.5, make_engineer_headers())
    )
    assert_cents(completed["labor_cost_cents"], 675000, "order.labor_cost_cents")
    after_labour = read_farm(api, site["farm"]["id"])
    assert_farm_buckets(
        after_labour,
        opex_accrued_cents=675000,
        maintenance_spend_cents=675000,
        landowner_payable_cents=0,
        road_maintenance_reserve_cents=0,
        community_fund_balance_cents=0,
    )

    drafted = validate_success(
        _p14_settlement(api, site["farm"]["id"], after_labour["version"]), 201
    )
    assert drafted["state"] == SETTLEMENT_DRAFT
    assert drafted["void_reason"] is None
    assert_two_dp(drafted["metered_kwh"], 1041750, "settlement.metered_kwh")
    assert_two_dp(drafted["deemed_kwh"], 0, "settlement.deemed_kwh")
    assert_cents(drafted["royalty_cents"], 250020, "settlement.royalty_cents")
    assert_cents(drafted["payment_cents"], 250020, "settlement.payment_cents")
    assert_cents(drafted["road_levy_cents"], 6251, "settlement.road_levy_cents")
    assert_cents(drafted["community_levy_cents"], 3750, "settlement.community_levy_cents")

    after_draft = read_farm(api, site["farm"]["id"])
    assert after_draft["version"] == after_labour["version"] + 1
    assert_farm_buckets(
        after_draft,
        opex_accrued_cents=675000,
        maintenance_spend_cents=675000,
        landowner_payable_cents=0,
    )

    approved = validate_success(
        api.approve_landowner_settlement(drafted["id"], make_commercial_headers())
    )
    assert approved["state"] == SETTLEMENT_APPROVED
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        opex_accrued_cents=950021,
        landowner_payable_cents=250020,
        road_maintenance_reserve_cents=21251,
        community_fund_balance_cents=3750,
        maintenance_spend_cents=675000,
    )


def test_the_void_returns_the_ledger_to_the_labour_figure_with_no_residue(api):
    """The reversal is exact, and a second cycle over the same parcel lands identically.

    The contract states: "Voiding an approved settlement drives it `APPROVED → VOID`,
    stores the `void_reason`, and is a pure compensating action: it subtracts
    `payment_cents` from `landowner_payable_cents`, `road_levy_cents` plus
    `road_damage_assessment_cents` from `road_maintenance_reserve_cents`,
    `community_levy_cents` from `community_fund_balance_cents`, and the same total from
    `opex_accrued_cents`."  It continues: "The settlement's own computed amounts are
    left intact for audit, and the ledger invariant holds exactly after the reversal
    with no rounding drift."  And: "`VOID` is terminal, and a voided settlement no
    longer blocks a fresh settlement over the same parcel and period."  Of the guard it
    states: "A successful draft creation increments the farm's `version` by 1, which
    means a client drafting two settlements in sequence must re-read the farm between
    them."  Of the buckets it states: "Voiding an approved settlement is a compensating
    action, decrementing each bucket by exactly the amount the approval credited, so
    that the invariant holds exactly and no rounding drift accumulates."

    Design: Difficulty/compensating_invariant/farm_opex_ledger_reconciles_to_the_cent_after_a_settlement_is_approved_then_voided
    """
    site = setup_opex_ledger_farm(api)
    validate_success(api.complete_work_order(site["order"]["id"], 7.5, make_engineer_headers()))
    first = validate_success(
        _p14_settlement(api, site["farm"]["id"], read_farm(api, site["farm"]["id"])["version"]),
        201,
    )
    validate_success(api.approve_landowner_settlement(first["id"], make_commercial_headers()))

    voided = validate_success(
        api.void_landowner_settlement(
            first["id"],
            "parcel boundary re-survey moved two turbines off P-14",
            make_commercial_headers(),
        )
    )
    assert voided["state"] == SETTLEMENT_VOID
    assert voided["void_reason"] == "parcel boundary re-survey moved two turbines off P-14"
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        opex_accrued_cents=675000,
        landowner_payable_cents=0,
        road_maintenance_reserve_cents=0,
        community_fund_balance_cents=0,
        maintenance_spend_cents=675000,
    )

    audited = read_settlement(api, first["id"])
    assert_cents(audited["payment_cents"], 250020, "voided.payment_cents")
    assert_cents(audited["road_levy_cents"], 6251, "voided.road_levy_cents")
    assert_cents(audited["community_levy_cents"], 3750, "voided.community_levy_cents")

    second = validate_success(
        _p14_settlement(api, site["farm"]["id"], read_farm(api, site["farm"]["id"])["version"]),
        201,
    )
    assert second["state"] == SETTLEMENT_DRAFT
    assert_cents(second["payment_cents"], 250020, "second.payment_cents")
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        opex_accrued_cents=675000,
        maintenance_spend_cents=675000,
        landowner_payable_cents=0,
    )

    validate_success(api.approve_landowner_settlement(second["id"], make_commercial_headers()))
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        opex_accrued_cents=950021,
        landowner_payable_cents=250020,
        road_maintenance_reserve_cents=21251,
        community_fund_balance_cents=3750,
        maintenance_spend_cents=675000,
    )
