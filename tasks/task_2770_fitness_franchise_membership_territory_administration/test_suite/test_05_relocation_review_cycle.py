"""Relocation review: the bounded rework cycle and the radial buffer at approval time.

A relocation request may bounce between the brand and the franchisee twice; the third
round trip is refused. Separately, the proposed circle is measured against every other
operator's protected area both at submission and again at approval.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    file_relocation_request,
    make_franchise_owner_headers,
    read_club,
    read_relocation_request,
    read_territory,
    relocation_decision_payload,
    request_relocation_changes,
    setup_single_club_franchise,
    submit_relocation_request,
    withdraw_relocation_request,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _restate_and_submit(relocation_request_id: str, franchisee_id: str, lat: float, lng: float):
    """Resubmit a bounced request with restated geometry."""
    return api_client.submit_relocation_request(
        relocation_request_id,
        {"requested_lat": lat, "requested_lng": lng, "requested_radius_km": 5.0},
        make_franchise_owner_headers(franchisee_id),
    )


def _request_bounced_twice() -> dict:
    """A relocation request that has been through the full two-revision cycle and is
    sitting in CHANGES_REQUESTED for the third time."""
    scenario = setup_single_club_franchise(
        legal_name="Northline Fitness LLC",
        contact_email="ops@northlinefit.example",
        club_name="Northline Club",
    )
    franchisee_id = scenario["franchisee"]["id"]
    request = file_relocation_request(
        scenario["club"]["id"],
        franchisee_id,
        requested_lat=34.02,
        requested_lng=-118.02,
        requested_radius_km=5.0,
        justification="Landlord redevelopment forces a move",
    )
    submit_relocation_request(request["id"], franchisee_id)
    request_relocation_changes(request["id"], "Parking ratio below brand standard")
    validate_success(_restate_and_submit(request["id"], franchisee_id, 34.03, -118.03))
    request_relocation_changes(request["id"], "Frontage still insufficient")
    validate_success(_restate_and_submit(request["id"], franchisee_id, 34.04, -118.04))
    request_relocation_changes(request["id"], "Third pass: signage plan missing")
    scenario["request"] = request
    return scenario


def _neighbour_at_the_protection_boundary() -> dict:
    """Two operators 0.2 degrees of longitude apart. The first one's relocation proposal
    at −117.895 is 0.425 km inside the buffer; −117.9 sits exactly on it."""
    subject = setup_single_club_franchise(
        legal_name="Beacon Hill Fitness LLC",
        contact_email="ops@beaconhillfit.example",
        club_name="Beacon Hill Club",
        center_lat=34.0,
        center_lng=-118.0,
        protected_radius_km=5.0,
    )
    neighbour = setup_single_club_franchise(
        legal_name="Eastbrook Fitness LLC",
        contact_email="ops@eastbrookfit.example",
        club_name="Eastbrook Club",
        center_lat=34.0,
        center_lng=-117.8,
        protected_radius_km=3.0,
        open_the_club=False,
        with_plan=False,
    )
    request = file_relocation_request(
        subject["club"]["id"],
        subject["franchisee"]["id"],
        requested_lat=34.0,
        requested_lng=-117.895,
        requested_radius_km=5.0,
        justification="Anchor tenant is moving east along the corridor",
    )
    subject["request"] = request
    subject["neighbour"] = neighbour
    return subject


def test_third_round_trip_is_refused_at_the_revision_limit():
    """Two revisions are the cap, so the submission that would set revision_count to 3 is
    refused outright.

    PRD 3.1: "The cycle `SUBMITTED → CHANGES_REQUESTED → SUBMITTED` is capped at two
    revisions: a resubmission whose resulting `revision_count` would exceed 2 — a third
    round trip, which would set the counter to 3 — is refused with
    `ERR_RELOCATION_REVISION_LIMIT`, and the request stays where it was."

    Design: Difficulty/non_linear_state_machine/relocation_request_cycles_through_changes_requested_until_revision_limit
    """
    scenario = _request_bounced_twice()

    response = _restate_and_submit(
        scenario["request"]["id"], scenario["franchisee"]["id"], 34.05, -118.05
    )
    validate_error(response, ApiErrorId.ERR_RELOCATION_REVISION_LIMIT.value)


def test_refused_resubmission_keeps_the_last_accepted_geometry_and_counter():
    """The request stays in CHANGES_REQUESTED at revision 2, still carrying the geometry
    of the second successful resubmission rather than the rejected fourth proposal.

    PRD 3.1: "A submission may optionally restate `requested_lat`, `requested_lng` and
    `requested_radius_km`; whichever of the three are supplied overwrite the stored
    proposal, and `encroachment_km` is then recomputed from the new geometry."

    Design: Difficulty/non_linear_state_machine/relocation_request_cycles_through_changes_requested_until_revision_limit
    """
    scenario = _request_bounced_twice()
    _restate_and_submit(
        scenario["request"]["id"], scenario["franchisee"]["id"], 34.05, -118.05
    )

    request = read_relocation_request(scenario["request"]["id"])
    assert request["status"] == "CHANGES_REQUESTED"
    assert request["revision_count"] == 2
    assert request["requested_lat"] == 34.04
    assert request["requested_lng"] == -118.04
    assert request["encroachment_km"] is None


def test_an_unapproved_relocation_never_moves_the_territory_or_the_club():
    """Only approval rewrites the protected circle, so after three bounces the territory
    still sits on its granted centre with no relocation to its name.

    PRD 3.1: "When it clears, the request moves `SUBMITTED → APPROVED`,
    `decided_by_user_id` is stamped with the deciding identifier, the parent territory's
    `center_lat`, `center_lng` and `protected_radius_km` are rewritten to the requested
    values with `relocation_count` incremented by 1, and because the territory moved, the
    club's own `lat` and `lng` are rewritten to the same requested values."

    Design: Difficulty/non_linear_state_machine/relocation_request_cycles_through_changes_requested_until_revision_limit
    """
    scenario = _request_bounced_twice()
    _restate_and_submit(
        scenario["request"]["id"], scenario["franchisee"]["id"], 34.05, -118.05
    )

    territory = read_territory(scenario["territory"]["id"])
    assert territory["center_lat"] == 34.0
    assert territory["center_lng"] == -118.0
    assert territory["relocation_count"] == 0
    club = read_club(scenario["club"]["id"])
    assert club["lat"] == 34.0
    assert club["lng"] == -118.0


def test_withdrawing_the_draft_frees_the_club_to_file_a_fresh_request():
    """Abandoning the rejected proposal releases the club, which may immediately draft a
    new request against a compliant geometry.

    PRD 3.1: "The franchisee may also abandon its own request, moving it `DRAFT →
    WITHDRAWN` or `CHANGES_REQUESTED → WITHDRAWN` with an optional `reason`, which frees
    the club to draft a fresh one."

    Design: Difficulty/resource_temporal_overlap/territory_radial_buffer_rejects_physically_disjoint_circles_on_relocation
    """
    scenario = _neighbour_at_the_protection_boundary()
    franchisee_id = scenario["franchisee"]["id"]

    withdrawn = withdraw_relocation_request(scenario["request"]["id"], franchisee_id)
    assert withdrawn["status"] == "WITHDRAWN"

    replacement = file_relocation_request(
        scenario["club"]["id"],
        franchisee_id,
        requested_lat=34.0,
        requested_lng=-117.9,
        requested_radius_km=5.0,
        justification="Second siting attempt one block further west",
    )
    assert replacement["status"] == "DRAFT"
    assert replacement["revision_count"] == 0


def test_clearance_of_exactly_zero_is_accepted_and_approval_moves_both_geometries():
    """At −117.9 the circles are separated by precisely the sum of their radii plus the
    buffer, so the submission stores a 0.0 clearance and approval rewrites the territory
    and drags the club's coordinates with it.

    PRD 3.1: "The measurement is a deliberately simple planar approximation with no
    trigonometry, using fixed degrees-to-kilometre factors so that every implementation
    lands on the same cent-level answer."

    Design: Difficulty/resource_temporal_overlap/territory_radial_buffer_rejects_physically_disjoint_circles_on_relocation
    """
    scenario = _neighbour_at_the_protection_boundary()
    franchisee_id = scenario["franchisee"]["id"]
    withdraw_relocation_request(scenario["request"]["id"], franchisee_id)
    replacement = file_relocation_request(
        scenario["club"]["id"],
        franchisee_id,
        requested_lat=34.0,
        requested_lng=-117.9,
        requested_radius_km=5.0,
        justification="Second siting attempt one block further west",
    )

    submitted = submit_relocation_request(replacement["id"], franchisee_id)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["encroachment_km"] == 0.0

    decided = validate_success(
        api_client.decide_relocation_request(
            replacement["id"], relocation_decision_payload("APPROVE"), BRAND
        )
    )
    assert decided["status"] == "APPROVED"

    territory = read_territory(scenario["territory"]["id"])
    assert territory["center_lat"] == 34.0
    assert territory["center_lng"] == -117.9
    assert territory["protected_radius_km"] == 5.0
    assert territory["relocation_count"] == 1
    club = read_club(scenario["club"]["id"])
    assert club["lng"] == -117.9
    neighbour_territory = read_territory(scenario["neighbour"]["territory"]["id"])
    assert neighbour_territory["center_lng"] == -117.8
    assert neighbour_territory["relocation_count"] == 0
