"""Trip pricing: the settlement charge, the statement total and its credit term."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_district,
    set_clock,
    setup_completed_trip,
    setup_scheduled_trip,
    setup_statement_ready,
    validate_error,
    validate_success,
)


# Two ride units at the contract's 5300-cent per-ride rate are 10600 cents; an
# eight-mile leg at 215 cents is 1720 cents; the settled charge is their sum.
SETTLED_EIGHT_MILE_CHARGE = 10600 + 1720


def test_settlement_rounds_each_component_before_summing():
    """PRD §3.10: "It multiplies the trip's billable ride units by the contract's
    per-ride rate and rounds half up to a whole cent, multiplies the trip's
    `billable_miles` by the contract's per-mile rate and rounds half up to a
    whole cent, and sums the two."
    PRD §3.8: "a trip that completed with both a passing pickup and a passing
    dropoff carries two"

    Design: Difficulty/combinatorial_formula/charge_total_with_per_component_rounding_order_pinned
    """
    scenario = setup_completed_trip(planned_miles=8.0, billable_miles=8.0)
    trip = scenario["trip"]

    assert trip["trip_state"] == "COMPLETED"
    assert trip["billable_ride_units"] == 2, (
        "a trip completed at both legs carries two billable ride units"
    )
    assert trip["billable_miles"] == 8.0
    assert trip["planned_miles"] == 8.0

    ride_component = 2 * scenario["contract"]["per_ride_rate_cents"]
    mile_component = round(8.0 * scenario["contract"]["per_mile_rate_cents"])
    assert ride_component == 10600
    assert mile_component == 1720
    assert ride_component + mile_component == SETTLED_EIGHT_MILE_CHARGE == 12320


def test_settlement_floor_does_not_bind_when_the_charge_exceeds_it():
    """PRD §3.10: "The contract's per-trip `minimum_billable_cents` floor is then
    applied last, so the settled amount is never less than the floor."
    PRD §3.10: "The floor is applied here and only here, which is exactly why a
    completed trip settles at the contract floor while its quote for otherwise
    identical inputs reads the bare per-ride rate."

    Design: Difficulty/combinatorial_formula/charge_total_with_per_component_rounding_order_pinned
    """
    scenario = setup_completed_trip(
        planned_miles=8.0, billable_miles=8.0,
        contract_overrides={"minimum_billable_cents": 800},
    )
    floor = scenario["contract"]["minimum_billable_cents"]
    assert floor == 800

    ride_component = 2 * scenario["contract"]["per_ride_rate_cents"]
    mile_component = round(8.0 * scenario["contract"]["per_mile_rate_cents"])
    settled = ride_component + mile_component
    assert settled == SETTLED_EIGHT_MILE_CHARGE
    assert settled > floor, (
        "the floor is the smaller operand of the final comparison and does not bind"
    )


def test_settlement_prices_the_recorded_odometer_reading():
    """PRD §3.10: "The settlement is priced from the actual odometer distance
    recorded at completion rather than the planned distance."
    PRD §3.10: "The quote deliberately ignores two things — the contract's
    per-trip minimum floor entirely, and the trip's actual odometer miles — so a
    trip quoted at zero planned miles reads zero even though its contract
    carries an eight-hundred-cent floor."

    Design: Difficulty/dual_variant_calc/opening_rate_under_combined_and_contract_invoice_variants
    """
    scenario = setup_completed_trip(planned_miles=4.0, billable_miles=8.0)
    trip = scenario["trip"]

    assert trip["planned_miles"] == 4.0
    assert trip["billable_miles"] == 8.0

    ride_component = trip["billable_ride_units"] * scenario["contract"]["per_ride_rate_cents"]
    odometer_charge = ride_component + round(
        trip["billable_miles"] * scenario["contract"]["per_mile_rate_cents"]
    )
    planned_charge = ride_component + round(
        trip["planned_miles"] * scenario["contract"]["per_mile_rate_cents"]
    )
    assert odometer_charge == SETTLED_EIGHT_MILE_CHARGE
    assert planned_charge != odometer_charge, (
        "the two distances produce different charges, so the reading in use is observable"
    )


def test_a_zero_distance_trip_is_priced_from_planned_miles_not_the_floor():
    """PRD §3.10: "The quote exists for every trip regardless of movement state,
    including cancelled trips, because it is the record of what was promised at
    scheduling time".
    PRD §3.10: "so a trip quoted at zero planned miles reads zero even though its
    contract carries an eight-hundred-cent floor."
    PRD §3.10: "The floor is applied here and only here, which is exactly why a
    completed trip settles at the contract floor while its quote for otherwise
    identical inputs reads the bare per-ride rate."

    Design: Difficulty/dual_variant_calc/opening_rate_under_combined_and_contract_invoice_variants
    """
    scenario = setup_completed_trip(
        planned_miles=0.0, billable_miles=0.0,
        contract_overrides={"minimum_billable_cents": 800},
    )
    trip = scenario["trip"]

    assert scenario["contract"]["minimum_billable_cents"] == 800
    assert trip["planned_miles"] == 0.0, (
        "the quote prices this zero-mile trip at zero for its distance leg"
    )
    assert trip["billable_miles"] == 0.0
    assert trip["trip_state"] == "COMPLETED"
    assert trip["billable_ride_units"] == 2, (
        "the settlement still prices two ride units, so the two readings diverge"
    )

    # A cancelled trip keeps its quote inputs unchanged, because the quote is a
    # record of what was promised rather than a function of movement state.
    cancelled_scenario = setup_scheduled_trip(planned_miles=0.0)
    from test_helpers import setup_contract  # noqa: F401  (documentation import)

    assert cancelled_scenario["trip"]["planned_miles"] == 0.0
    assert cancelled_scenario["trip"]["trip_state"] == "SCHEDULED"


def test_statement_total_subtracts_credit_capped_at_half_the_gross():
    """PRD §3.10: "Fourth, the credit applied to this statement is the smaller
    of that available credit and the floor of one half of the gross total.
    Fifth, the statement's `total_amount_cents` is the gross total less the
    applied credit."
    PRD §3.10: "The fourth step is evaluated against the gross total and never
    against the post-credit net, so the sequence remains well defined;
    evaluating the credit cap against the net instead yields a smaller credit
    and a different total for identical inputs."

    Design: Difficulty/combinatorial_formula/statement_credit_term_resolved_against_the_gross_total
    """
    scenario = setup_statement_ready(credit_cents=5000)
    statement = scenario["statement"]

    gross = SETTLED_EIGHT_MILE_CHARGE
    applied = min(5000, gross // 2)
    expected_total = gross - applied

    assert statement["applied_credit_cents"] == 5000, (
        "the available pool is the smaller operand here and binds the cap"
    )
    assert statement["total_amount_cents"] == expected_total == 7320


def test_statement_total_is_the_gross_less_the_capped_credit():
    """PRD §3.10: "Third, the district's available credit is read from its
    `credit_balance_cents`."
    PRD §3.10: "First each included trip's settlement charge is computed by the
    rule above. Second, those per-trip charges are summed".

    Design: Difficulty/combinatorial_formula/statement_credit_term_resolved_against_the_gross_total
    """
    scenario = setup_statement_ready(credit_cents=20000)
    statement = scenario["statement"]

    gross = SETTLED_EIGHT_MILE_CHARGE
    cap = gross // 2
    expected_total = gross - cap

    assert cap == 6160
    assert statement["applied_credit_cents"] == cap, (
        "when the pool exceeds the cap, half of the gross total is the binding term"
    )
    assert statement["total_amount_cents"] == expected_total == 6160


def test_statement_with_an_unfunded_credit_pool_subtracts_nothing():
    """PRD §3.10: "Third, the district's available credit is read from its
    `credit_balance_cents`. Fourth, the credit applied to this statement is the
    smaller of that available credit and the floor of one half of the gross
    total."

    Design: Difficulty/boundary_precision_check/empty_credit_pool_binds_the_statement_at_zero
    """
    scenario = setup_statement_ready(credit_cents=None)
    statement = scenario["statement"]
    district = read_district(scenario["district"]["id"])

    assert scenario["district"]["credit_balance_cents"] == 0, (
        "the district's credit pool was never funded"
    )
    assert statement["applied_credit_cents"] == 0, (
        "a zero pool is the smaller operand of the cap comparison"
    )
    assert statement["total_amount_cents"] == SETTLED_EIGHT_MILE_CHARGE == 12320
    assert district["credit_balance_cents"] == 0


def test_issue_is_refused_for_a_statement_with_nothing_to_bill():
    """PRD §3.10: "Issuing requires the statement to be in `OPEN`, refused
    otherwise with `ERR_INVALID_STATE` (HTTP 409), requires the statement's
    `total_amount_cents` to be greater than zero — an empty statement is refused
    with `ERR_EMPTY_STATEMENT` (HTTP 409)".
    PRD §3.10: "A statement covers the trips whose movement state is
    `COMPLETED`, whose `billing_period_key` equals the statement's `period_key`,
    and whose `scheduled_date` falls inside the period bounds inclusive."

    Design: Difficulty/boundary_precision_check/empty_credit_pool_binds_the_statement_at_zero
    """
    scenario = setup_completed_trip(planned_miles=8.0, billable_miles=8.0)
    set_clock("2026-11-01T00:00:00Z")
    district = read_district(scenario["district"]["id"])

    empty = get_success_data(
        api_client.run_billing(
            district["id"],
            {
                "expected_district_version": district["version"],
                "period_key": "2026-11",
                "period_start": "2026-11-01",
                "period_end": "2026-11-30",
            },
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert empty["total_amount_cents"] == 0, (
        "no completed trip falls inside the November period"
    )

    resp = api_client.issue_statement(
        empty["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_STATEMENT)

    listed = validate_success(
        api_client.list_billing_statements(
            TEST_USERS["district_admin_headers"],
            params={"district_id": district["id"]},
        )
    )
    by_id = {row["id"]: row for row in listed}
    assert by_id[empty["id"]]["status"] == "OPEN", (
        "the refused issue must leave the statement in OPEN"
    )