"""Endpoint-level behaviour: withdrawal, computed reads and the two overwrites."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_power_kw,
    assert_spend_down_ratio,
)
from test_helpers.factories import (
    create_space_assignment_payload,
    rescope_payload,
    utility_upgrade_payload,
)
from test_helpers.test_users import make_dean_headers, make_faculty_headers

CLOCK = "2026-08-01T00:00:00Z"

TWO_CATEGORY_SPECS = [
    {
        "key": "equipment",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": "2026-07-01T00:00:00Z",
        "expires_on": "2027-07-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
    {
        "key": "personnel",
        "category": "PERSONNEL",
        "fiscal_year": 2027,
        "amount_cents": 8_000_000,
        "available_on": "2026-07-01T00:00:00Z",
        "expires_on": "2027-07-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
]


def test_withdrawing_a_scheduled_tranche_hard_deletes_it_and_redrives_the_rollups():
    """The withdrawal answers 204 with no body and leaves no readable row behind.

    PRD 3.2: "Withdrawal hard-deletes the tranche row and re-derives the package
    rollups; it returns no body."

    Design: Corner/endpoints/corner_ep_delete_scheduled_tranche_returns_204_and_recomputes_totals
    """
    scenario = fixtures.setup_draft_package(
        tranche_specs=TWO_CATEGORY_SPECS, clock=CLOCK, proposed_total_cents=20_000_000
    )
    package_id = scenario["package_id"]
    dropped = scenario["tranche"]["personnel"]
    kept = scenario["tranche"]["equipment"]

    response = api_client.delete_commitment_tranche(
        package_id, dropped["id"], fixtures.DEAN_OFFICE
    )
    assert response.status_code == 204, response.text
    assert response.text.strip() == ""

    validate_error(
        api_client.get_commitment_tranche(dropped["id"], fixtures.DEAN_OFFICE),
        "ERR_TRANCHE_NOT_FOUND", expected_status=404,
    )

    remaining = fixtures.read_package_tranches(package_id)
    assert [row["id"] for row in remaining] == [kept["id"]]

    package = fixtures.read_package(package_id)
    assert package["total_committed_cents"] == 12_000_000
    assert package["total_available_cents"] == 12_000_000
    assert package["proposed_total_cents"] == 20_000_000
    assert_spend_down_ratio(package["spend_down_ratio"], 0.0)
    assert fixtures.read_ledger(package_id) == []

    validate_error(
        api_client.delete_commitment_tranche(package_id, dropped["id"], fixtures.DEAN_OFFICE),
        "ERR_TRANCHE_NOT_FOUND", expected_status=404,
    )
    validate_error(
        api_client.submit_startup_package(package_id, fixtures.DEAN_OFFICE),
        "ERR_TRANCHE_SUM_MISMATCH", expected_status=422,
    )


SUMMARY_FIELDS = (
    "total_committed_cents",
    "total_encumbered_cents",
    "total_disbursed_cents",
    "total_available_cents",
    "total_expired_cents",
    "total_recaptured_cents",
    "total_carried_out_cents",
    "total_carried_in_cents",
    "dept_share_cents",
    "college_share_cents",
    "dean_share_cents",
    "balance_identity_holds",
)


def test_the_spend_summary_read_reports_the_ledger_it_is_derived_from():
    """Every figure in the summary is the accumulation of the package's own rows.

    PRD 2.9: "A package's spend-summary read exposes the rollups defined in §3.4
    together with total_carried_out_cents and total_carried_in_cents (the sums of
    carried_out_cents and carried_in_cents across the package's tranches), the three
    per-funder totals dept_share_cents, college_share_cents and dean_share_cents
    accumulated over the package's whole ledger, spend_down_ratio, and a boolean
    balance_identity_holds that reports whether the identity above is satisfied for
    every tranche of the package."

    Design: Corner/endpoints/corner_ep_spend_summary_computed_read_matches_the_ledger
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    space = fixtures.create_lab_space(building_code="BIOL", room_number="12")
    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                quoted_cents=12_001_000)

    summary = validate_success(
        api_client.get_package_spend_summary(
            scenario["package_id"], make_dean_headers(scenario["college_id"])
        )
    )

    assert summary["total_committed_cents"] == 20_000_000
    assert summary["total_encumbered_cents"] == 12_001_000
    assert summary["total_disbursed_cents"] == 0
    assert summary["total_available_cents"] == 7_999_000
    assert summary["total_expired_cents"] == 0
    assert summary["total_recaptured_cents"] == 0
    assert summary["total_carried_out_cents"] == 0
    assert summary["total_carried_in_cents"] == 0
    assert_spend_down_ratio(summary["spend_down_ratio"], 0.6001)
    assert summary["dept_share_cents"] == 5_400_450
    assert summary["college_share_cents"] == 4_200_350
    assert summary["dean_share_cents"] == 2_400_200
    assert (summary["dept_share_cents"] + summary["college_share_cents"]
            + summary["dean_share_cents"]) == 12_001_000
    assert summary["balance_identity_holds"] is True

    own_read = validate_success(
        api_client.get_package_spend_summary(
            scenario["package_id"], make_faculty_headers(scenario["faculty_id"])
        )
    )
    assert [own_read[field] for field in SUMMARY_FIELDS] == \
        [summary[field] for field in SUMMARY_FIELDS]
    assert_spend_down_ratio(own_read["spend_down_ratio"], 0.6001)


def test_a_utility_upgrade_overwrites_the_envelope_and_only_bumps_the_version():
    """Raising what a room can support is not a change of what the room is doing.

    PRD 3.5: "A successful upgrade overwrites the four envelope fields, leaves
    installed_power_kw and installed_fume_hoods untouched, does **not** change the
    room's status, and increments the room's version."

    Design: Corner/endpoints/corner_ep_utility_upgrade_raises_the_envelope_without_changing_status
    """
    fixtures.set_clock(CLOCK)
    space = fixtures.create_lab_space(
        building_code="BIOL", room_number="44", power_kw_capacity=100.0,
        chilled_water_available=False, fume_hood_count=1, floor_load_psf=250,
    )
    assert space["version"] == 1
    assert_power_kw(space["installed_power_kw"], 0.0)
    assert space["installed_fume_hoods"] == 0

    upgraded = validate_success(
        api_client.upgrade_lab_space_utilities(
            space["id"],
            utility_upgrade_payload(power_kw_capacity=400.0, fume_hood_count=4,
                                    chilled_water_available=True, floor_load_psf=600),
            fixtures.FACILITIES,
        )
    )
    assert_power_kw(upgraded["power_kw_capacity"], 400.0)
    assert upgraded["fume_hood_count"] == 4
    assert upgraded["chilled_water_available"] is True
    assert upgraded["floor_load_psf"] == 600
    assert upgraded["version"] == 2
    assert upgraded["status"] == "AVAILABLE"
    assert_power_kw(upgraded["installed_power_kw"], 0.0)
    assert upgraded["installed_fume_hoods"] == 0
    assert upgraded["allocated_share_pct"] == 0

    partial = {"power_kw_capacity": 500.0, "chilled_water_available": True,
               "floor_load_psf": 700}
    validate_error(
        api_client.upgrade_lab_space_utilities(space["id"], partial, fixtures.FACILITIES),
        "ERR_VALIDATION", expected_status=400,
    )
    unchanged = fixtures.read_space(space["id"])
    assert unchanged["fume_hood_count"] == 4
    assert unchanged["version"] == 2


RENOVATION_ONLY_SPECS = [
    {
        "key": "renovation",
        "category": "RENOVATION",
        "fiscal_year": 2027,
        "amount_cents": 20_000_000,
        "available_on": "2026-07-01T00:00:00Z",
        "expires_on": "2027-07-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
]

BID_PHASE = {
    "sequence_no": 1,
    "name": "Mechanical rough-in",
    "planned_start": "2026-09-01T00:00:00Z",
    "planned_end": "2026-09-30T00:00:00Z",
    "budget_cents": 8_000_000,
}


def test_rescoping_a_project_out_to_bid_returns_it_to_scoping_with_a_new_estimate():
    """The backwards edge rewrites the estimate and the tier and counts itself.

    PRD 3.6: "If the bids come back wrong, facilities can rescope, moving the project
    BID → SCOPING while supplying a revised_estimate_cents that replaces estimate_cents
    and a scope_tier that replaces the previous tier; rescope_count increases by one each
    time."

    Design: Corner/endpoints/corner_ep_rescope_returns_bid_project_to_scoping_with_a_new_estimate
    """
    scenario = fixtures.setup_draft_package(
        tranche_specs=RENOVATION_ONLY_SPECS, clock=CLOCK, proposed_total_cents=20_000_000
    )
    space = fixtures.create_lab_space(building_code="CHEM", room_number="240")
    project = fixtures.create_project(scenario["package_id"], space["id"],
                                      scope_tier="MODERATE", estimate_cents=8_000_000)
    fixtures.create_phase(project["id"], **BID_PHASE)
    at_bid = fixtures.solicit_bids(project["id"])
    assert at_bid["status"] == "BID"
    assert at_bid["version"] == 2
    assert at_bid["rescope_count"] == 0

    rescoped = validate_success(
        api_client.rescope_renovation_project(
            project["id"], rescope_payload(15_000_000, "GUT"), fixtures.FACILITIES
        )
    )
    assert rescoped["status"] == "SCOPING"
    assert rescoped["estimate_cents"] == 15_000_000
    assert rescoped["scope_tier"] == "GUT"
    assert rescoped["rescope_count"] == 1
    assert rescoped["version"] == 3
    assert rescoped["awarded_cents"] is None
    assert rescoped["subsidy_estimate_cents"] is None

    assert fixtures.read_ledger(scenario["package_id"]) == []
    assert fixtures.read_package(scenario["package_id"])["total_encumbered_cents"] == 0
    assert fixtures.read_space(space["id"])["status"] == "AVAILABLE"

    validate_error(
        api_client.rescope_renovation_project(
            project["id"], rescope_payload(9_000_000, "COSMETIC"), fixtures.FACILITIES
        ),
        "ERR_RENOVATION_STATE_INVALID", expected_status=409,
    )

    fixtures.solicit_bids(project["id"])
    cycled = validate_success(
        api_client.rescope_renovation_project(
            project["id"], rescope_payload(11_000_000, "MODERATE"), fixtures.FACILITIES
        )
    )
    assert cycled["rescope_count"] == 2
    assert cycled["status"] == "SCOPING"


def test_a_proposed_assignment_reserves_the_share_and_needs_both_sides_to_resolve():
    """The junction row counts against the room the moment it is proposed.

    PRD 3.5: "For the **room's reported allocated_share_pct**, the filter is different: it
    is the sum of share_pct over the room's PROPOSED and ACTIVE assignments whose
    half-open window contains the *current clock instant*, not the peak over all future
    instants and not the total ever granted."

    Design: Corner/endpoints/corner_ep_space_assignment_links_room_and_package_and_rejects_unknown_room
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    space = fixtures.create_lab_space(building_code="BIOL", room_number="61")
    assert space["version"] == 1

    def propose(space_id, faculty_id, expected_version):
        return api_client.create_space_assignment(
            create_space_assignment_payload(space_id, faculty_id, expected_version,
                                            share_pct=60),
            fixtures.DEAN_OFFICE,
        )

    assignment = validate_success(
        propose(space["id"], scenario["faculty_id"], space["version"]),
        expected_status=201,
    )
    assert assignment["status"] == "PROPOSED"
    assert assignment["share_pct"] == 60
    assert assignment["effective_to"] is None
    assert assignment["released_on"] is None
    assert assignment["space_id"] == space["id"]
    assert assignment["faculty_id"] == scenario["faculty_id"]

    occupied = fixtures.read_space(space["id"])
    assert occupied["allocated_share_pct"] == 60
    assert occupied["status"] == "AVAILABLE"
    assert occupied["version"] == 2

    validate_error(
        propose(NON_EXISTENT_UUID, scenario["faculty_id"], occupied["version"]),
        "ERR_SPACE_NOT_FOUND", expected_status=404,
    )
    validate_error(
        propose(space["id"], NON_EXISTENT_UUID, occupied["version"]),
        "ERR_FACULTY_NOT_FOUND", expected_status=404,
    )
    validate_error(
        propose(space["id"], scenario["faculty_id"], space["version"]),
        "ERR_STALE_SPACE_VERSION", expected_status=412,
    )

    still_one = fixtures.read_space(space["id"])
    assert still_one["allocated_share_pct"] == 60
    assert still_one["version"] == 2
