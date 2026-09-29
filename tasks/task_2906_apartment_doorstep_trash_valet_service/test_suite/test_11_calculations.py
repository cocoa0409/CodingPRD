"""Settlement and fine arithmetic: the pass-through line list, the SLA weights, the uplift."""

from test_helpers import (
    ANALYST_DRAFTER,
    ANALYST_ISSUER,
    api_client,
    assert_fine_amounts,
    assert_resident_ledger,
    assert_statement_waterfall,
    factories,
    fixtures,
    make_property_manager_headers,
    validate_success,
)

SETTLEMENT_CONTRACT = {
    "per_unit_monthly_fee_cents": 3495,
    "property_revenue_share_bps": 1500,
    "sla_missed_threshold_bps": 1000,
}


def _community_with_one_missed_night(resident_kwargs, resident_units=(101, 102)):
    """A four-door community whose only September night closes MISSED and ACCRUED."""
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=resident_units,
        resident_kwargs=resident_kwargs,
        contract=dict(SETTLEMENT_CONTRACT),
        with_contractor=False,
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    closed = fixtures.close_night(night["id"])
    assert closed["verification_status"] == "MISSED"
    assert closed["billing_status"] == "ACCRUED"
    world["night"] = closed
    fixtures.set_clock("2026-09-30T23:00:00Z")
    world["statement"] = fixtures.draft_statement(world["contract"]["id"], "2026-09")
    return world


# --------------------------------------------------------------------------
# The FINAL gross is a line list, and an opted-out resident has no line
# --------------------------------------------------------------------------
def test_a_resident_with_passthrough_disabled_contributes_no_line_at_all():
    """One of two fully occupying residents is excluded, so the gross is 3495 not 6990.

    PRD 3.8: "Then, for each resident of the contract's community whose
    `fee_passthrough_enabled` is true — regardless of that resident's own `status`,
    so a resident who has since moved out still contributes the days they occupied
    — count that resident's billable days as the number of dates in the month that
    fall on or after their `move_in_date` and, when a `move_out_date` exists,
    strictly before it. ... Residents whose `fee_passthrough_enabled` is false
    contribute nothing and are excluded from the line list entirely."

    Design: Corner/calculations/passthrough_excludes_the_resident_whose_passthrough_is_disabled
    """
    world = _community_with_one_missed_night(
        {
            101: {"move_in_date": "2026-08-01"},
            102: {"move_in_date": "2026-08-01", "fee_passthrough_enabled": False},
        }
    )

    issued = validate_success(
        api_client.issue_statement(world["statement"]["id"], ANALYST_ISSUER)
    )

    assert issued["variant"] == "FINAL"
    assert issued["status"] == "ISSUED"
    assert_statement_waterfall(
        issued,
        gross_cents=3495,
        sla_credit_rate_bps=1200,
        credit_cents=419,
        share_cents=461,
        net_cents=2615,
        missed_service_bps=10000,
        scheduled_night_count=1,
        missed_equivalent_nights=1.0,
    )
    assert issued["gross_passthrough_cents"] != 6990, (
        "counting the opted-out resident would double the gross"
    )
    assert fixtures.read_night(world["night"]["id"])["billing_status"] == "CREDITED"
    assert fixtures.read_contract(world["contract"]["id"])["last_invoiced_period"] == "2026-09"


# --------------------------------------------------------------------------
# Each line is rounded on its own, before the lines are added
# --------------------------------------------------------------------------
def test_each_resident_line_is_rounded_before_the_lines_are_added():
    """Two lines of exactly 1980.5 cents round to 1981 apiece, giving 3962 not 3961.

    PRD 3.8: "Multiply the exact daily rate by that day count and **round the
    resulting line half up to whole cents**. Finally add the rounded lines
    together. ... The rounding order there is pinned and the forbidden alternative
    — adding the exact line values and rounding the total once — differs by up to
    half a cent per resident. Worked through: a fee of 3495 cents across a
    thirty-day month gives an exact daily rate of 116.5 cents; a resident present
    all thirty days lines at 3495, and two residents present seventeen days each
    line at exactly 1980.5, which rounds to 1981 apiece, for a gross of 7457.
    Summing the exact values first would have produced 7456."

    Design: Corner/calculations/passthrough_lines_round_half_up_once_per_resident_line
    """
    world = _community_with_one_missed_night(
        {
            101: {"move_in_date": "2026-09-14"},
            102: {"move_in_date": "2026-09-14"},
        }
    )

    issued = validate_success(
        api_client.issue_statement(world["statement"]["id"], ANALYST_ISSUER)
    )

    assert issued["variant"] == "FINAL"
    assert_statement_waterfall(
        issued,
        gross_cents=3962,
        sla_credit_rate_bps=1200,
        credit_cents=475,
        share_cents=523,
        net_cents=2964,
        missed_service_bps=10000,
        scheduled_night_count=1,
        missed_equivalent_nights=1.0,
    )
    assert issued["gross_passthrough_cents"] not in (3960, 3961), (
        "3961 sums the exact lines first; 3960 rounds each line to even"
    )


# --------------------------------------------------------------------------
# A PARTIAL night weighs one half in the shortfall ratio
# --------------------------------------------------------------------------
def test_a_partial_night_weighs_half_a_missed_night_and_that_shows_in_the_money():
    """One PARTIAL of four scheduled gives 1250 bps and the tier-one rate, not tier two.

    PRD 3.8: "`missed_equivalent_nights` weighs a `MISSED` night as a whole failure
    and a `PARTIAL` night as half of one: it is the count of `MISSED` nights plus
    one half multiplied by the count of `PARTIAL` nights."

    PRD 3.8: "When `missed_service_bps` is at or above the threshold but below the
    tier-two entry point of 2000 basis points, the rate is 500 basis points."

    Design: Corner/calculations/partial_night_counts_as_half_a_missed_night_in_the_sla_ratio
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101, 102, 103, 104),
        resident_kwargs={unit: {"move_in_date": "2026-08-01"} for unit in (101, 102, 103, 104)},
        contract=dict(SETTLEMENT_CONTRACT),
        service_date="2026-09-01",
    )
    fixtures.record_scan(
        world["route"]["id"], world["contractor"]["id"], world["residents"][101]["id"]
    )
    partial = fixtures.close_night(world["night"]["id"])
    assert partial["verification_status"] == "PARTIAL"
    assert partial["coverage_bps"] == 2500
    for service_date in ("2026-09-02", "2026-09-03", "2026-09-06"):
        fixtures.schedule_night(world["contract"]["id"], service_date)

    statement = validate_success(
        api_client.create_statement(
            world["contract"]["id"],
            factories.statement_payload(
                "2026-09", fixtures.read_contract(world["contract"]["id"])["version"]
            ),
            ANALYST_DRAFTER,
        ),
        expected_status=201,
    )

    assert statement["variant"] == "PROVISIONAL"
    assert_statement_waterfall(
        statement,
        gross_cents=13980,
        sla_credit_rate_bps=500,
        credit_cents=699,
        share_cents=1992,
        net_cents=11289,
        missed_service_bps=1250,
        scheduled_night_count=4,
        missed_equivalent_nights=0.5,
    )
    assert statement["net_due_from_property_cents"] != 10457, (
        "weighting the PARTIAL night as a whole missed night would net 10457"
    )


# --------------------------------------------------------------------------
# The seasonal uplift multiplies inside the single rounding step
# --------------------------------------------------------------------------
def test_a_peak_night_uplifts_the_fine_by_a_quarter_before_the_only_rounding():
    """2500 by 0.5 by 1.25 is exactly 1562.5, which rounds half up to 1563.

    PRD 3.6: "**Seasonal uplift.** When the scan's night has a
    `seasonal_volume_index` of 120 or more, the amount is multiplied by a further
    1.25 and `seasonal_uplift_applied` records true; otherwise the factor is 1.0
    and `seasonal_uplift_applied` records false."

    PRD 3.6: "A first early set-out on a night indexed at 130 works out as 2500
    multiplied by 0.5 multiplied by 1.25, giving exactly 1562.5, which rounds to
    1563 and clears the floor untouched."

    Design: Corner/calculations/fine_seasonal_uplift_applies_at_the_peak_volume_index
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
        night_kwargs={"seasonal_volume_index": 130},
    )
    property_id = world["property"]["id"]
    resident_id = world["residents"][101]["id"]
    scan = fixtures.record_scan(
        world["route"]["id"],
        world["contractor"]["id"],
        resident_id,
        scan_result="TAGGED_NOT_SERVICED",
        container_type="LOOSE_BAG",
        non_compliance_type="EARLY_SET_OUT",
    )
    assert scan["tag_status"] == "OPEN", "a first early set-out is not auto-fined"

    fine = validate_success(
        api_client.assess_fine(
            scan["id"],
            factories.manual_fine_payload("second notice posted on the door"),
            make_property_manager_headers(property_id),
        ),
        expected_status=201,
    )

    assert_fine_amounts(
        fine,
        base_cents=2500,
        escalation_multiplier=0.5,
        amount_cents=1563,
        uncapped_amount_cents=1563,
        seasonal_uplift_applied=True,
    )
    assert fine["origin"] == "MANUAL"
    assert fine["status"] == "ASSESSED"
    assert fine["offense_ordinal"] == 1
    assert fine["assessed_by_user_id"] == property_id
    assert fixtures.read_scan(scan["id"])["tag_status"] == "FINED"
    assert_resident_ledger(
        fixtures.read_resident(resident_id),
        outstanding_cents=1563,
        collections_status="CURRENT",
    )
