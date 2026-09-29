"""State-machine shape: initial states, valid edges, refused edges and terminal locks."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_tranche_balances,
    assert_unit_balances,
)
from test_helpers.constants import (
    FY2027_AVAILABLE_ON,
    FY2027_EXPIRES_ON,
    FY2028_AVAILABLE_ON,
    FY2028_EXPIRES_ON,
)
from test_helpers.test_users import make_dean_headers, make_dean_office_headers

CLOCK = "2026-08-01T00:00:00Z"
PROPOSER = "U-DEANOFFICE-1"
SECOND_OFFICER = "U-DEANOFFICE-2"


def test_a_new_package_starts_draft_on_the_negotiation_axis_and_unavailable_on_the_spend_axis():
    """Creation seeds both parallel axes at their own initial states.

    PRD 3.2: "A new package is created with negotiation_status DRAFT, spend_status
    NOT_YET_AVAILABLE, negotiation_round 1, counter_total_cents null, all three
    signature fields null, settlement_variant null, and recaptured_unspent_cents,
    transferred_balance_cents and college_holdback_cents all 0."

    Design: Corner/state_machines/corner_sm_new_package_starts_draft_on_both_parallel_axes
    """
    units = fixtures.setup_mini_units(CLOCK)
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])

    package = fixtures.create_draft_package(faculty["id"], units["dean_office"]["id"],
                                            proposed_total_cents=20_000_000)

    assert package["negotiation_status"] == "DRAFT"
    assert package["spend_status"] == "NOT_YET_AVAILABLE"
    assert package["negotiation_round"] == 1
    assert package["activated_on"] is None
    assert package["closed_out_on"] is None
    assert package["proposed_by_user_id"] is None
    assert package["endorsed_by_user_id"] is None
    assert package["approved_by_user_id"] is None


def test_submitting_a_draft_stamps_the_proposer_and_leaves_the_spend_axis_alone():
    """The first signature is taken from the acting identity, and no money moves.

    PRD 3.3: "On success the acting user's identifier is recorded as
    proposed_by_user_id — this is the first of the three segregated signatures."

    Design: Corner/state_machines/corner_sm_submit_advances_draft_to_submitted_and_stamps_proposer
    """
    scenario = fixtures.setup_draft_package()
    version_before = scenario["package"]["version"]

    submitted = fixtures.submit_package(scenario["package_id"])

    assert submitted["negotiation_status"] == "SUBMITTED"
    assert submitted["proposed_by_user_id"] == PROPOSER
    assert submitted["version"] == version_before + 1
    assert submitted["spend_status"] == "NOT_YET_AVAILABLE"

    tranche = fixtures.read_tranche(scenario["tranche"]["equipment"]["id"])
    assert tranche["status"] == "SCHEDULED"
    assert tranche["opened_on"] is None

    department = fixtures.read_unit(scenario["department_id"])
    assert_unit_balances(department, reserved_cents=0)
    assert department["available_pool_cents"] == 400_000_000


def test_approving_a_package_that_was_never_submitted_is_refused_on_state():
    """The state gate is the first rule a never-submitted package actually fails.

    PRD 3.3: "Four conditions must hold: the package is in DEAN_REVIEW; the acting
    identifier equals the package's college_unit_id, else ERR_UNIT_SCOPE_VIOLATION; the
    acting identifier is neither proposed_by_user_id nor endorsed_by_user_id, else
    ERR_SEGREGATION_OF_DUTIES; and, for each of the three funder units, that unit's
    available_pool_cents is at least its share of the package's total_committed_cents
    under the split of §2.7, else ERR_UNIT_POOL_EXCEEDED."

    Design: Corner/state_machines/corner_sm_approve_from_draft_is_rejected_with_package_state_invalid
    """
    scenario = fixtures.setup_draft_package()

    response = api_client.approve_startup_package(
        scenario["package_id"], make_dean_headers(scenario["college_id"])
    )
    validate_error(response, "ERR_PACKAGE_STATE_INVALID", expected_status=409)

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "DRAFT"
    assert package["approved_by_user_id"] is None
    assert package["proposed_by_user_id"] is None
    assert package["endorsed_by_user_id"] is None

    for unit_id in (scenario["department_id"], scenario["college_id"],
                    scenario["dean_office_id"]):
        assert_unit_balances(fixtures.read_unit(unit_id), reserved_cents=0)


def test_a_second_submit_is_refused_rather_than_silently_replayed():
    """Re-submitting an already submitted package neither succeeds nor rewrites the proposer.

    PRD 2.13: "ERR_PACKAGE_STATE_INVALID (409) — the package's negotiation_status permits
    the requested transition."

    Design: Corner/state_machines/corner_sm_repeated_submit_is_rejected_rather_than_idempotent
    """
    scenario = fixtures.setup_draft_package()
    submitted = fixtures.submit_package(scenario["package_id"])

    response = api_client.submit_startup_package(
        scenario["package_id"], make_dean_office_headers(SECOND_OFFICER)
    )
    validate_error(response, "ERR_PACKAGE_STATE_INVALID", expected_status=409)

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "SUBMITTED"
    assert package["proposed_by_user_id"] == PROPOSER
    assert package["version"] == submitted["version"]


def test_a_closed_out_package_has_no_outgoing_edge_left():
    """CLOSED_OUT refuses activation and refuses a second close-out alike.

    PRD 3.3: "CLOSED_OUT and SUPERSEDED are its two terminal states."

    Design: Corner/state_machines/corner_sm_closed_out_terminal_state_rejects_every_further_transition
    """
    scenario = fixtures.setup_mini_active()
    fixtures.close_out_package(scenario["package_id"], scenario["headers"]["dean"])

    validate_error(
        api_client.activate_startup_package(scenario["package_id"], fixtures.DEAN_OFFICE),
        "ERR_PACKAGE_STATE_INVALID", expected_status=409,
    )
    validate_error(
        api_client.close_out_startup_package(
            scenario["package_id"], scenario["headers"]["dean"]
        ),
        "ERR_PACKAGE_STATE_INVALID", expected_status=409,
    )

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "CLOSED_OUT"
    assert package["spend_status"] == "SETTLED"

    tranche = fixtures.read_tranche(scenario["tranche"]["equipment"]["id"])
    assert_tranche_balances(tranche, status="EXPIRED", expired_cents=20_000_000,
                            available_balance_cents=0)

    department = fixtures.read_unit(scenario["department_id"])
    assert_unit_balances(department, reserved_cents=0, refunded_cents=9_000_000)
    assert department["available_pool_cents"] == 400_000_000
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         refunded_cents=7_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         refunded_cents=4_000_000)


def test_submitting_a_package_with_no_tranche_at_all_reports_the_missing_schedule():
    """The tranche-existence gate is checked before the sum gate.

    PRD 3.3: "Two conditions are checked, in this order: the package must have at least
    one commitment tranche, or the submission fails with ERR_NO_TRANCHES_DEFINED; and the
    sum of every tranche's amount_cents must equal proposed_total_cents exactly, with
    zero tolerance, or the submission fails with ERR_TRANCHE_SUM_MISMATCH."

    Design: Corner/state_machines/corner_sm_submit_without_any_tranche_returns_no_tranches_defined
    """
    scenario = fixtures.setup_draft_package(tranche_specs=[])

    response = api_client.submit_startup_package(
        scenario["package_id"], make_dean_office_headers(PROPOSER)
    )
    validate_error(response, "ERR_NO_TRANCHES_DEFINED", expected_status=422)

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "DRAFT"
    assert package["proposed_by_user_id"] is None


ONE_CENT_SHORT_SPECS = [
    {
        "key": "equipment",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 19_999_999,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]


def test_a_schedule_one_cent_short_of_the_headline_cannot_be_submitted():
    """The sum gate is a pure equality on the schedule, with zero tolerance.

    PRD 3.3: "Two conditions are checked, in this order: the package must have at least
    one commitment tranche, or the submission fails with ERR_NO_TRANCHES_DEFINED; and the
    sum of every tranche's amount_cents must equal proposed_total_cents exactly, with
    zero tolerance, or the submission fails with ERR_TRANCHE_SUM_MISMATCH."

    Design: Corner/state_machines/corner_sm_submit_with_tranche_sum_mismatch_is_rejected
    """
    scenario = fixtures.setup_draft_package(tranche_specs=ONE_CENT_SHORT_SPECS)

    response = api_client.submit_startup_package(
        scenario["package_id"], make_dean_office_headers(PROPOSER)
    )
    validate_error(response, "ERR_TRANCHE_SUM_MISMATCH", expected_status=422)

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_committed_cents"] == 19_999_999
    assert package["proposed_total_cents"] == 20_000_000
    assert package["negotiation_status"] == "DRAFT"

    fixtures.add_tranche(scenario["package_id"], amount_cents=1)
    submitted = fixtures.submit_package(scenario["package_id"])
    assert submitted["negotiation_status"] == "SUBMITTED"
    assert submitted["total_committed_cents"] == 20_000_000


def test_approval_reserves_each_funder_share_and_re_derives_the_available_pool():
    """Approval puts pool money at risk without encumbering a single tranche.

    PRD 3.3: "On success the acting identifier is stored as approved_by_user_id, and each
    funder unit's reserved_cents rises by exactly its computed share of
    total_committed_cents, with available_pool_cents re-derived accordingly."

    Design: Corner/state_machines/corner_sm_approve_reserves_funder_shares_and_recomputes_available_pool
    """
    scenario = fixtures.setup_draft_package()
    fixtures.submit_package(scenario["package_id"])
    fixtures.endorse_package(scenario["package_id"], scenario["department_id"])

    approved = fixtures.approve_package(scenario["package_id"], scenario["college_id"])

    assert approved["negotiation_status"] == "APPROVED"
    assert approved["approved_by_user_id"] == scenario["college_id"]

    department = fixtures.read_unit(scenario["department_id"])
    college = fixtures.read_unit(scenario["college_id"])
    dean_office = fixtures.read_unit(scenario["dean_office_id"])

    assert_unit_balances(department, reserved_cents=9_000_000, committed_cents=0,
                         disbursed_cents=0, refunded_cents=0)
    assert_unit_balances(college, reserved_cents=7_000_000, committed_cents=0,
                         disbursed_cents=0, refunded_cents=0)
    assert_unit_balances(dean_office, reserved_cents=4_000_000, committed_cents=0,
                         disbursed_cents=0, refunded_cents=0)
    assert department["available_pool_cents"] == 391_000_000
    assert college["available_pool_cents"] == 893_000_000
    assert dean_office["available_pool_cents"] == 296_000_000
    assert (department["reserved_cents"] + college["reserved_cents"]
            + dean_office["reserved_cents"] == 20_000_000)

    assert fixtures.read_tranche(scenario["tranche"]["equipment"]["id"])["status"] == "SCHEDULED"
    assert approved["spend_status"] == "NOT_YET_AVAILABLE"


TWO_WINDOW_SPECS = [
    {
        "key": "now",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "later",
        "category": "EQUIPMENT",
        "fiscal_year": 2028,
        "amount_cents": 8_000_000,
        "available_on": FY2028_AVAILABLE_ON,
        "expires_on": FY2028_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]


def test_activation_opens_only_the_tranche_whose_window_contains_the_clock():
    """A future-dated tranche stays SCHEDULED while the current one opens.

    PRD 3.4: "Tranches whose window has not opened yet stay SCHEDULED; tranches whose
    window has already closed also stay SCHEDULED and can only ever be expired or
    recaptured later."

    Design: Corner/state_machines/corner_sm_activate_opens_only_tranches_whose_window_contains_the_clock
    """
    scenario = fixtures.setup_active_package(tranche_specs=TWO_WINDOW_SPECS)
    package = scenario["package"]

    assert package["negotiation_status"] == "ACTIVE"
    assert package["spend_status"] == "SPENDING"
    assert_instant_equals(package["activated_on"], CLOCK)

    opened = fixtures.read_tranche(scenario["tranche"]["now"]["id"])
    assert opened["status"] == "OPEN"
    assert_instant_equals(opened["opened_on"], CLOCK)

    waiting = fixtures.read_tranche(scenario["tranche"]["later"]["id"])
    assert waiting["status"] == "SCHEDULED"
    assert waiting["opened_on"] is None

    assert package["total_committed_cents"] == 20_000_000
    assert package["total_available_cents"] == 20_000_000
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         reserved_cents=9_000_000, committed_cents=0)


def test_receiving_an_order_that_was_never_placed_is_refused_on_item_state():
    """A REQUESTED order has no shipment to receive and has committed nothing.

    PRD 2.13: "ERR_SPEND_ITEM_STATE_INVALID (409) — the EquipmentOrder, StaffAppointment
    or SpaceAssignment is in a status from which the requested action is declared."

    Design: Corner/state_machines/corner_sm_receive_before_place_is_rejected_spend_item_state_invalid
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    order = fixtures.create_order(scenario["package_id"], space["id"],
                                  quoted_cents=5_000_000)

    response = api_client.receive_equipment_order(order["id"], fixtures.FACILITIES)
    validate_error(response, "ERR_SPEND_ITEM_STATE_INVALID", expected_status=409)

    stored = fixtures.read_order(order["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["placed_on"] is None
    assert stored["delivered_on"] is None

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            encumbered_cents=0, available_balance_cents=20_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=0)


def test_releasing_the_only_assignment_returns_the_room_to_available():
    """Closing the window empties the room's occupancy without touching the ledger.

    PRD 3.5: "The room's allocated_share_pct is re-derived, and if it falls to 0 the room
    moves ASSIGNED → AVAILABLE."

    Design: Corner/state_machines/corner_sm_release_returns_space_to_available_with_zero_allocated_share
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    assignment = fixtures.create_active_assignment(space, scenario["faculty_id"],
                                                   share_pct=100,
                                                   effective_from=CLOCK)

    occupied = fixtures.read_space(space["id"])
    assert occupied["status"] == "ASSIGNED"
    assert occupied["allocated_share_pct"] == 100

    released = fixtures.release_assignment(assignment["id"], CLOCK)

    assert released["status"] == "RELEASED"
    assert_instant_equals(released["released_on"], CLOCK)
    assert_instant_equals(released["effective_to"], CLOCK)

    vacated = fixtures.read_space(space["id"])
    assert vacated["allocated_share_pct"] == 0
    assert vacated["status"] == "AVAILABLE"

    assert fixtures.read_ledger(scenario["package_id"]) == []


def test_a_cancelled_order_is_terminal_and_refuses_a_second_cancellation():
    """The first cancel lands in CANCELLED for free; the second is refused outright.

    PRD 3.7: "Cancellation by the dean's office is available from REQUESTED, ORDERED,
    DELIVERED and UTILITY_BLOCKED, and always lands the order in CANCELLED."

    Design: Corner/state_machines/corner_sm_cancelled_order_is_terminal_and_rejects_a_second_cancel
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space()
    order = fixtures.create_order(scenario["package_id"], space["id"],
                                  quoted_cents=5_000_000)

    cancelled = validate_success(
        api_client.cancel_equipment_order(order["id"], fixtures.DEAN_OFFICE)
    )
    assert cancelled["status"] == "CANCELLED"
    assert fixtures.read_ledger(scenario["package_id"]) == []

    validate_error(
        api_client.cancel_equipment_order(order["id"], fixtures.DEAN_OFFICE),
        "ERR_SPEND_ITEM_STATE_INVALID", expected_status=409,
    )

    stored = fixtures.read_order(order["id"])
    assert stored["status"] == "CANCELLED"
    assert stored["version"] == cancelled["version"]

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            available_balance_cents=20_000_000, encumbered_cents=0)
