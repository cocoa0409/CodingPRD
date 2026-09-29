"""Cost-share splitting, ratio precision, waterfall ordering and the retention floor."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_row_amount_and_shares,
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
    rows_of_kind,
)
from test_helpers.constants import (
    FY2027_AVAILABLE_ON,
    FY2027_EXPIRES_ON,
    FY2028_AVAILABLE_ON,
    FY2028_EXPIRES_ON,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_a_remainder_tie_hands_the_odd_cent_to_the_department():
    """Two funders tie on the fractional part, so the fixed ordinal decides.

    PRD 2.7: "Distribute the remainder by the largest fractional part first rule: sort the
    three funders by the discarded fractional part of their exact product in descending
    order, breaking any tie by the fixed funder ordering department, then college, then
    dean's office — never by identifier and never by creation timestamp — and give one
    extra cent to each of the first *remainder* funders in that order."

    Design: Corner/calculations/corner_calc_cost_share_split_breaks_a_remainder_tie_by_funder_ordinal
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    tranche_id = scenario["tranche"]["equipment"]["id"]

    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                               quoted_cents=12_000_010)

    encumbrances = rows_of_kind(fixtures.read_tranche_ledger(tranche_id), "ENCUMBRANCE")
    assert len(encumbrances) == 1
    assert_row_amount_and_shares(encumbrances[0], 12_000_010, 5_400_005, 4_200_003,
                                 2_400_002)
    assert 5_400_005 + 4_200_003 + 2_400_002 == 12_000_010

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         committed_cents=5_400_005, reserved_cents=9_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         committed_cents=4_200_003, reserved_cents=7_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         committed_cents=2_400_002, reserved_cents=4_000_000)


def test_the_spend_down_ratio_rounds_half_up_at_the_fourth_decimal():
    """A ratio of 0.60005 is stored as 0.6001, not truncated to 0.6000.

    PRD 3.4: "Finally, spend_down_ratio is total_disbursed_cents plus
    total_encumbered_cents, divided by total_committed_cents, rounded half up to four
    decimal places, and defined as 0.0 when total_committed_cents is 0."

    Design: Corner/calculations/corner_calc_spend_down_ratio_rounds_half_up_at_the_fourth_decimal
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()

    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                               quoted_cents=12_001_000)

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_encumbered_cents"] == 12_001_000
    assert package["total_disbursed_cents"] == 0
    assert_spend_down_ratio(package["spend_down_ratio"], 0.6001)
    assert package["total_available_cents"] == 7_999_000

    tranche_id = scenario["tranche"]["equipment"]["id"]
    assert_tranche_balances(fixtures.read_tranche(tranche_id),
                            available_balance_cents=7_999_000)
    encumbrances = rows_of_kind(fixtures.read_tranche_ledger(tranche_id), "ENCUMBRANCE")
    assert_row_amount_and_shares(encumbrances[0], 12_001_000, 5_400_450, 4_200_350,
                                 2_400_200)


LATE_THEN_EARLY_SPECS = [
    {
        "key": "late",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "early",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 8_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": "2027-01-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
]


def test_the_waterfall_drains_the_earliest_expiring_tranche_before_the_later_one():
    """Ordering is by expires_on, not by the order the tranches were created in.

    PRD 3.4: "Otherwise the candidates are ordered by expires_on ascending, ties broken by
    fiscal_year ascending, further ties broken by created_at ascending — never by
    identifier — so that the soonest-expiring money is always consumed first."

    Design: Corner/calculations/corner_calc_waterfall_fills_the_earliest_expiring_tranche_first
    """
    scenario = fixtures.setup_active_package(tranche_specs=LATE_THEN_EARLY_SPECS)
    space = fixtures.create_lab_space()
    early_id = scenario["tranche"]["early"]["id"]
    late_id = scenario["tranche"]["late"]["id"]

    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                               quoted_cents=10_000_000)

    early_rows = rows_of_kind(fixtures.read_tranche_ledger(early_id), "ENCUMBRANCE")
    late_rows = rows_of_kind(fixtures.read_tranche_ledger(late_id), "ENCUMBRANCE")
    assert len(early_rows) == 1 and len(late_rows) == 1
    assert_row_amount_and_shares(early_rows[0], 8_000_000, 3_600_000, 2_800_000, 1_600_000)
    assert_row_amount_and_shares(late_rows[0], 2_000_000, 900_000, 700_000, 400_000)

    drained = fixtures.read_tranche(early_id)
    assert_tranche_balances(drained, available_balance_cents=0,
                            encumbered_cents=8_000_000, status="OPEN")
    assert_tranche_balances(fixtures.read_tranche(late_id),
                            available_balance_cents=10_000_000,
                            encumbered_cents=2_000_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         committed_cents=4_500_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         committed_cents=3_500_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         committed_cents=2_000_000)

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_encumbered_cents"] == 10_000_000
    assert package["total_available_cents"] == 10_000_000


OPEN_AND_SCHEDULED_SPECS = [
    {
        "key": "open",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "scheduled",
        "category": "EQUIPMENT",
        "fiscal_year": 2028,
        "amount_cents": 8_000_000,
        "available_on": FY2028_AVAILABLE_ON,
        "expires_on": FY2028_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]


def test_expired_balances_leave_the_available_total_but_stay_in_the_committed_total():
    """Close-out expires both tranches, and only one of the two rollups notices.

    PRD 3.4: "total_available_cents, by contrast, is the sum of available_balance_cents
    over only those tranches in status SCHEDULED or OPEN — an OBLIGATED, CARRIED_FORWARD,
    EXPIRED or RECAPTURED balance is not available."

    Design: Corner/calculations/corner_calc_available_total_excludes_expired_tranches_after_closeout
    """
    scenario = fixtures.setup_active_package(tranche_specs=OPEN_AND_SCHEDULED_SPECS)
    open_id = scenario["tranche"]["open"]["id"]
    scheduled_id = scenario["tranche"]["scheduled"]["id"]

    before = fixtures.read_package(scenario["package_id"])
    assert before["total_available_cents"] == 20_000_000

    fixtures.close_out_package(scenario["package_id"], scenario["headers"]["dean"])

    assert fixtures.read_tranche(open_id)["status"] == "EXPIRED"
    assert fixtures.read_tranche(scheduled_id)["status"] == "EXPIRED"

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_available_cents"] == 0
    assert package["total_committed_cents"] == 20_000_000
    assert package["total_expired_cents"] == 20_000_000
    assert_spend_down_ratio(package["spend_down_ratio"], 0.0)

    expiries = rows_of_kind(fixtures.read_ledger(scenario["package_id"]), "EXPIRY")
    assert len(expiries) == 2
    by_amount = {row["amount_cents"]: row for row in expiries}
    assert_row_amount_and_shares(by_amount[12_000_000], 12_000_000, 5_400_000,
                                 4_200_000, 2_400_000)
    assert_row_amount_and_shares(by_amount[8_000_000], 8_000_000, 3_600_000,
                                 2_800_000, 1_600_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         refunded_cents=9_000_000, reserved_cents=0)


def test_a_counteroffer_at_the_exact_recommitment_floor_is_accepted():
    """One cent below the floor is refused; the floor itself is enough.

    PRD 3.9: "The recommitment floor must be met: sum the available_balance_cents of the
    predecessor's tranches in status SCHEDULED or OPEN to get the predecessor's unspent
    balance, add 2,500,000 cents of genuinely new money — twenty-five thousand dollars —
    and the counteroffer's proposed_total_cents must be at least that floor, else
    ERR_RECOMMITMENT_BELOW_FLOOR."

    Design: Corner/calculations/corner_calc_retention_floor_accepts_the_exact_floor_and_rejects_one_cent_below
    """
    scenario = fixtures.setup_mini_active()
    fixtures.record_departure_notice(scenario["faculty_id"], "OUTSIDE_OFFER", "2026-12-01")

    def counteroffer(proposed_total_cents):
        return api_client.create_startup_package(
            {
                "faculty_id": scenario["faculty_id"],
                "package_kind": "RETENTION_COUNTEROFFER",
                "superseded_package_id": scenario["package_id"],
                "dean_unit_id": scenario["dean_office_id"],
                "dept_share_pct": 45,
                "college_share_pct": 35,
                "dean_share_pct": 20,
                "proposed_total_cents": proposed_total_cents,
                "spend_deadline_on": "2029-06-30",
            },
            fixtures.DEAN_OFFICE,
        )

    validate_error(counteroffer(22_499_999), "ERR_RECOMMITMENT_BELOW_FLOOR",
                   expected_status=422)

    accepted = validate_success(counteroffer(22_500_000), expected_status=201)
    assert accepted["package_kind"] == "RETENTION_COUNTEROFFER"
    assert accepted["superseded_package_id"] == scenario["package_id"]
    assert accepted["negotiation_status"] == "DRAFT"

    predecessor = fixtures.read_package(scenario["package_id"])
    assert predecessor["negotiation_status"] == "ACTIVE"
    assert predecessor["spend_status"] == "FROZEN"

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            status="OPEN", available_balance_cents=20_000_000)
