"""State, fiscal-window and predecessor rules of the validation ladder."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_no_rows_of_kind,
    assert_row_amount_and_shares,
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
    rows_of_kind,
)
from test_helpers.constants import FY2027_AVAILABLE_ON, FY2027_EXPIRES_ON
from test_helpers.factories import year_end_rollover_payload

CLOCK = "2026-08-01T00:00:00Z"

EQUIPMENT_AND_RENOVATION_SPECS = [
    {
        "key": "equipment",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "renovation",
        "category": "RENOVATION",
        "fiscal_year": 2027,
        "amount_cents": 8_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]

COSMETIC_PHASES = [
    {
        "sequence_no": 1,
        "name": "Demolition",
        "planned_start": "2026-09-01T00:00:00Z",
        "planned_end": "2026-09-10T00:00:00Z",
        "budget_cents": 3_000_000,
    },
    {
        "sequence_no": 2,
        "name": "Casework",
        "planned_start": "2026-09-13T00:00:00Z",
        "planned_end": "2026-09-20T00:00:00Z",
        "budget_cents": 3_000_000,
    },
]


def test_substantial_completion_with_a_phase_still_running_is_refused():
    """Every phase must be COMPLETE with a recorded actual before the ledger settles.

    PRD 2.13: "ERR_PHASES_INCOMPLETE (409) — every phase of the project is in status
    COMPLETE with a non-null actual_cost_cents."

    Design: Corner/validations/corner_val_substantial_completion_with_an_active_phase_returns_phases_incomplete
    """
    scenario = fixtures.setup_active_package(tranche_specs=EQUIPMENT_AND_RENOVATION_SPECS)
    space = fixtures.create_lab_space()
    project, phases = fixtures.setup_awarded_project(
        scenario["package_id"], space["id"], 6_000_000, scenario["headers"]["dean"],
        phase_specs=COSMETIC_PHASES,
        project_overrides={"scope_tier": "COSMETIC", "estimate_cents": 6_000_000},
    )

    fixtures.start_phase(project["id"], phases[0]["id"])
    fixtures.complete_phase(project["id"], phases[0]["id"], 3_000_000)
    fixtures.start_phase(project["id"], phases[1]["id"])

    validate_error(
        api_client.substantial_completion(project["id"], fixtures.FACILITIES),
        "ERR_PHASES_INCOMPLETE", expected_status=409,
    )

    stored = fixtures.read_project(project["id"])
    assert stored["status"] == "IN_PROGRESS"
    assert stored["completed_on"] is None
    assert stored["cost_variance_cents"] is None

    second = [p for p in fixtures.read_phases(project["id"])
              if p["sequence_no"] == 2][0]
    assert second["status"] == "ACTIVE"
    assert second["actual_cost_cents"] is None

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["renovation"]["id"]),
                            encumbered_cents=6_000_000, available_balance_cents=2_000_000)

    ledger = fixtures.read_ledger(scenario["package_id"])
    assert_no_rows_of_kind(ledger, "DISBURSEMENT")
    assert_no_rows_of_kind(ledger, "RELEASE")

    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"


def test_closing_out_a_package_with_an_open_encumbrance_is_refused():
    """The gate is a pure encumbrance check: release the money and it opens.

    PRD 2.13: "ERR_OPEN_ENCUMBRANCES_BLOCK_CLOSEOUT (409) — no tranche of the package is
    OBLIGATED and no equipment order, staff appointment or renovation project of the
    package still holds an encumbrance."

    Design: Corner/validations/corner_val_closeout_with_an_open_encumbrance_is_rejected
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    order = fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                        quoted_cents=5_000_000)
    tranche_id = scenario["tranche"]["equipment"]["id"]

    validate_error(
        api_client.close_out_startup_package(scenario["package_id"],
                                             scenario["headers"]["dean"]),
        "ERR_OPEN_ENCUMBRANCES_BLOCK_CLOSEOUT", expected_status=409,
    )

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "ACTIVE"
    assert package["spend_status"] == "SPENDING"
    assert package["closed_out_on"] is None
    assert package["total_encumbered_cents"] == 5_000_000
    assert fixtures.read_tranche(tranche_id)["status"] == "OPEN"
    assert_no_rows_of_kind(fixtures.read_ledger(scenario["package_id"]), "EXPIRY")
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         reserved_cents=9_000_000)

    fixtures.cancel_order(order["id"])
    closed = fixtures.close_out_package(scenario["package_id"],
                                        scenario["headers"]["dean"])
    assert closed["negotiation_status"] == "CLOSED_OUT"


def test_approval_is_refused_when_one_funder_pool_cannot_carry_its_share():
    """The reservation is atomic across the three funders, so one shortfall blocks it.

    PRD 2.13: "ERR_UNIT_POOL_EXCEEDED (422) — each of the three funder units has an
    available_pool_cents at least equal to its share of proposed_total_cents."

    Design: Corner/validations/corner_val_approve_beyond_a_departments_pool_returns_unit_pool_exceeded
    """
    scenario = fixtures.setup_draft_package(
        pool_overrides={"department_pool_cents": 5_000_000}
    )
    fixtures.submit_package(scenario["package_id"])
    fixtures.endorse_package(scenario["package_id"], scenario["department_id"])

    validate_error(
        api_client.approve_startup_package(scenario["package_id"],
                                           scenario["headers"]["dean"]),
        "ERR_UNIT_POOL_EXCEEDED", expected_status=422,
    )

    department = fixtures.read_unit(scenario["department_id"])
    assert department["available_pool_cents"] == 5_000_000

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "DEAN_REVIEW"
    assert package["approved_by_user_id"] is None

    for unit_id in (scenario["department_id"], scenario["college_id"],
                    scenario["dean_office_id"]):
        assert_unit_balances(fixtures.read_unit(unit_id), reserved_cents=0)
    assert fixtures.read_tranche(scenario["tranche"]["equipment"]["id"])["status"] == "SCHEDULED"


def test_a_rollover_for_a_year_that_has_not_closed_yet_is_refused():
    """The fiscal year must be over before its residual balances can be settled.

    PRD 2.13: "ERR_ROLLOVER_FISCAL_YEAR_NOT_ELAPSED (409) — the requested fiscal year's
    window has closed, meaning the clock is at or after the July 1st instant of the
    requested fiscal_year."

    Design: Corner/validations/corner_val_rollover_before_the_year_closes_is_rejected
    """
    scenario = fixtures.setup_mini_active()

    validate_error(
        api_client.year_end_rollover(scenario["package_id"],
                                     year_end_rollover_payload(fiscal_year=2027),
                                     fixtures.DEAN_OFFICE),
        "ERR_ROLLOVER_FISCAL_YEAR_NOT_ELAPSED", expected_status=409,
    )

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            status="OPEN", available_balance_cents=20_000_000,
                            expired_cents=0)

    ledger = fixtures.read_ledger(scenario["package_id"])
    for kind in ("EXPIRY", "CARRYFORWARD_OUT", "CARRYFORWARD_IN"):
        assert_no_rows_of_kind(ledger, kind)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         reserved_cents=9_000_000, refunded_cents=0)


def test_the_same_fiscal_year_cannot_be_rolled_over_twice():
    """The replay is refused and, crucially, writes no second EXPIRY row.

    PRD 2.13: "ERR_ROLLOVER_ALREADY_RUN (409) — no tranche of the requested fiscal year is
    already in status CARRIED_FORWARD or EXPIRED; the rollover for a year runs at most
    once."

    Design: Corner/validations/corner_val_second_rollover_for_the_same_year_is_rejected
    """
    scenario = fixtures.setup_mini_active()
    tranche_id = scenario["tranche"]["equipment"]["id"]
    fixtures.set_clock("2027-07-01T00:00:00Z")

    fixtures.rollover_fiscal_year(scenario["package_id"], 2027)

    assert_tranche_balances(fixtures.read_tranche(tranche_id), status="EXPIRED",
                            expired_cents=20_000_000, available_balance_cents=0,
                            carried_out_cents=0)
    expiries = rows_of_kind(fixtures.read_ledger(scenario["package_id"]), "EXPIRY")
    assert len(expiries) == 1
    assert_row_amount_and_shares(expiries[0], 20_000_000, 9_000_000, 7_000_000, 4_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         refunded_cents=9_000_000, reserved_cents=0)

    validate_error(
        api_client.year_end_rollover(scenario["package_id"],
                                     year_end_rollover_payload(fiscal_year=2027),
                                     fixtures.DEAN_OFFICE),
        "ERR_ROLLOVER_ALREADY_RUN", expected_status=409,
    )

    assert len(rows_of_kind(fixtures.read_ledger(scenario["package_id"]), "EXPIRY")) == 1
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         refunded_cents=9_000_000)
    package = fixtures.read_package(scenario["package_id"])
    assert package["total_expired_cents"] == 20_000_000
    assert_spend_down_ratio(package["spend_down_ratio"], 0.0)


def test_an_internal_transfer_notice_without_a_target_unit_is_refused():
    """The transfer target is mandatory for exactly one intent, and nothing freezes.

    PRD 2.13: "ERR_TRANSFER_TARGET_REQUIRED (422) — when departure_intent is
    INTERNAL_TRANSFER, target_funding_unit_id is present, names an existing DEPARTMENT unit
    other than the faculty member's current unit, and shares the same parent college; and
    no target unit is supplied for any other intent."

    Design: Corner/validations/corner_val_internal_transfer_without_a_target_unit_is_rejected
    """
    scenario = fixtures.setup_mini_active()
    physics = fixtures.create_sibling_department(scenario["college_id"],
                                                name="Department of Physics")

    validate_error(
        api_client.record_departure_notice(
            scenario["faculty_id"],
            {"departure_intent": "INTERNAL_TRANSFER",
             "departure_effective_on": "2026-12-01"},
            fixtures.DEAN_OFFICE,
        ),
        "ERR_TRANSFER_TARGET_REQUIRED", expected_status=422,
    )

    faculty = fixtures.read_faculty(scenario["faculty_id"])
    assert faculty["appointment_status"] == "ACTIVE"
    assert faculty["departure_intent"] is None
    assert faculty["departure_effective_on"] is None
    assert fixtures.read_package(scenario["package_id"])["spend_status"] == "SPENDING"

    noticed = fixtures.record_departure_notice(
        scenario["faculty_id"], "INTERNAL_TRANSFER", "2026-12-01",
        target_funding_unit_id=physics["id"],
    )
    assert noticed["appointment_status"] == "DEPARTURE_NOTICE"
    assert noticed["target_funding_unit_id"] == physics["id"]


def test_separating_before_the_effective_date_is_refused():
    """The gate is inclusive, so the effective date itself is due.

    PRD 2.13: "ERR_SEPARATION_NOT_DUE (409) — the clock is at or after the faculty member's
    departure_effective_on."

    Design: Corner/validations/corner_val_separating_before_the_effective_date_is_rejected
    """
    scenario = fixtures.setup_mini_active()
    fixtures.record_departure_notice(scenario["faculty_id"], "DEPARTURE", "2026-12-01")

    validate_error(
        api_client.separate_faculty(scenario["faculty_id"], fixtures.DEAN_OFFICE),
        "ERR_SEPARATION_NOT_DUE", expected_status=409,
    )

    faculty = fixtures.read_faculty(scenario["faculty_id"])
    assert faculty["appointment_status"] == "DEPARTURE_NOTICE"
    assert faculty["separated_on"] is None

    package = fixtures.read_package(scenario["package_id"])
    assert package["spend_status"] == "FROZEN"
    assert package["negotiation_status"] == "ACTIVE"

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            status="OPEN", available_balance_cents=20_000_000)
    assert_no_rows_of_kind(fixtures.read_ledger(scenario["package_id"]), "RECAPTURE")

    fixtures.set_clock("2026-12-01T00:00:00Z")
    separated = fixtures.separate_faculty(scenario["faculty_id"])
    assert separated["appointment_status"] == "DEPARTED"


def test_a_counteroffer_against_an_active_faculty_member_is_refused():
    """Only an OUTSIDE_OFFER notice makes a predecessor package counterable.

    PRD 2.13: "ERR_PREDECESSOR_NOT_ELIGIBLE (422) — the superseded package is in
    negotiation_status ACTIVE, belongs to the same faculty member, and that faculty member
    is in appointment_status DEPARTURE_NOTICE with departure_intent OUTSIDE_OFFER."

    Design: Corner/validations/corner_val_counteroffer_for_an_active_faculty_returns_predecessor_not_eligible
    """
    scenario = fixtures.setup_mini_active()

    def counteroffer():
        return api_client.create_startup_package(
            {
                "faculty_id": scenario["faculty_id"],
                "package_kind": "RETENTION_COUNTEROFFER",
                "superseded_package_id": scenario["package_id"],
                "dean_unit_id": scenario["dean_office_id"],
                "dept_share_pct": 45,
                "college_share_pct": 35,
                "dean_share_pct": 20,
                "proposed_total_cents": 30_000_000,
                "spend_deadline_on": "2029-06-30",
            },
            fixtures.DEAN_OFFICE,
        )

    validate_error(counteroffer(), "ERR_PREDECESSOR_NOT_ELIGIBLE", expected_status=422)
    assert fixtures.read_package(scenario["package_id"])["negotiation_status"] == "ACTIVE"

    fixtures.record_departure_notice(scenario["faculty_id"], "OUTSIDE_OFFER", "2026-12-01")
    accepted = validate_success(counteroffer(), expected_status=201)
    assert accepted["superseded_package_id"] == scenario["package_id"]


def test_activating_a_counteroffer_over_an_obligated_predecessor_is_refused():
    """The recommitment cascade will not run while the predecessor still owes money.

    PRD 2.13: "ERR_PREDECESSOR_HAS_OPEN_ENCUMBRANCES (409) — no tranche of the superseded
    package is in status OBLIGATED and its total_encumbered_cents is 0."

    Design: Corner/validations/corner_val_activating_a_counteroffer_over_an_obligated_predecessor_is_rejected
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    fixtures.setup_placed_order(scenario["package_id"], space["id"], quoted_cents=5_000_000)
    fixtures.record_departure_notice(scenario["faculty_id"], "OUTSIDE_OFFER", "2026-12-01")

    fixtures.set_clock("2027-07-01T00:00:00Z")
    fixtures.rollover_fiscal_year(scenario["package_id"], 2027)

    old_tranche_id = scenario["tranche"]["equipment"]["id"]
    assert_tranche_balances(fixtures.read_tranche(old_tranche_id), status="OBLIGATED",
                            encumbered_cents=5_000_000, available_balance_cents=0,
                            expired_cents=15_000_000)

    successor = validate_success(
        api_client.create_startup_package(
            {
                "faculty_id": scenario["faculty_id"],
                "package_kind": "RETENTION_COUNTEROFFER",
                "superseded_package_id": scenario["package_id"],
                "dean_unit_id": scenario["dean_office_id"],
                "dept_share_pct": 45,
                "college_share_pct": 35,
                "dean_share_pct": 20,
                "proposed_total_cents": 22_500_000,
                "spend_deadline_on": "2029-06-30",
            },
            fixtures.DEAN_OFFICE,
        ),
        expected_status=201,
    )
    fixtures.add_tranche(successor["id"], category="EQUIPMENT", fiscal_year=2028,
                        amount_cents=22_500_000, available_on="2027-07-01T00:00:00Z",
                        expires_on="2028-07-01T00:00:00Z", carryforward_policy="NONE")
    fixtures.negotiate_to_approved(successor["id"], scenario["units"])

    validate_error(
        api_client.activate_startup_package(successor["id"], fixtures.DEAN_OFFICE),
        "ERR_PREDECESSOR_HAS_OPEN_ENCUMBRANCES", expected_status=409,
    )

    stored_successor = fixtures.read_package(successor["id"])
    assert stored_successor["negotiation_status"] == "APPROVED"
    assert stored_successor["spend_status"] == "NOT_YET_AVAILABLE"
    assert stored_successor["activated_on"] is None

    predecessor = fixtures.read_package(scenario["package_id"])
    assert predecessor["negotiation_status"] == "ACTIVE"
    assert predecessor["spend_status"] == "FROZEN"
    assert fixtures.read_faculty(scenario["faculty_id"])["appointment_status"] \
        == "DEPARTURE_NOTICE"

    for package_id in (scenario["package_id"], successor["id"]):
        ledger = fixtures.read_ledger(package_id)
        assert_no_rows_of_kind(ledger, "RECAPTURE")
        assert_no_rows_of_kind(ledger, "CARRYFORWARD_IN")
