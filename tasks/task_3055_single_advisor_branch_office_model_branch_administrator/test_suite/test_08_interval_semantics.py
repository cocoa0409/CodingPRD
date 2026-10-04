"""Interval semantics: half-open territory assignments vs closed lease terms."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_advisor, create_territory, create_branch,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_territory_half_open_adjacency_allowed():
    """PRD §3.2: "Territory intervals must not collide: a new assignment whose
    half-open interval intersects the territory's current interval is rejected
    with `ERR_TERRITORY_OVERLAP`. Adjacency is allowed — a new assignment
    beginning exactly at the moment the existing interval ends does not
    overlap, because the existing end is exclusive."

    Design: Difficulty/resource_temporal_overlap/territory_assignment_half_open_adjacency_allowed
    """
    advisor_a = create_advisor()
    advisor_b = create_advisor()
    territory = create_territory()

    validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor_a["id"],
            "assignment_start": "2026-01-01T00:00:00Z",
            "assignment_end": "2026-06-01T00:00:00Z",
        },
        ADMIN,
    ))

    # Overlapping: one second before the existing end.
    validate_error(
        api_client.assign_territory(
            territory["id"],
            {
                "advisor_id": advisor_b["id"],
                "assignment_start": "2026-05-31T23:59:59Z",
                "assignment_end": "2026-12-01T00:00:00Z",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_TERRITORY_OVERLAP,
    )

    # Adjacent: exactly at the existing end is allowed.
    reassigned = validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor_b["id"],
            "assignment_start": "2026-06-01T00:00:00Z",
            "assignment_end": "2026-12-01T00:00:00Z",
        },
        ADMIN,
    ))
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_advisor_id"] == advisor_b["id"]


def test_territory_overlap_contained_interval_rejected():
    """PRD §3.2: "Territory intervals must not collide: a new assignment whose
    half-open interval intersects the territory's current interval is rejected
    with `ERR_TERRITORY_OVERLAP`. Adjacency is allowed — a new assignment
    beginning exactly at the moment the existing interval ends does not
    overlap, because the existing end is exclusive."

    Design: Difficulty/resource_temporal_overlap/territory_assignment_half_open_adjacency_allowed
    """
    advisor_a = create_advisor()
    advisor_b = create_advisor()
    territory = create_territory()

    validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor_a["id"],
            "assignment_start": "2026-01-01T00:00:00Z",
            "assignment_end": "2026-06-01T00:00:00Z",
        },
        ADMIN,
    ))

    # Fully contained interval also intersects.
    validate_error(
        api_client.assign_territory(
            territory["id"],
            {
                "advisor_id": advisor_b["id"],
                "assignment_start": "2026-02-01T00:00:00Z",
                "assignment_end": "2026-03-01T00:00:00Z",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_TERRITORY_OVERLAP,
    )

    current = get_success_data(api_client.get_territory(territory["id"], ADMIN))
    assert current["assigned_advisor_id"] == advisor_a["id"]


def test_lease_closed_interval_adjacency_conflicts():
    """PRD §3.3: "Approval requires the branch to be `PROPOSED`, requires
    `territory_id` to be set with a territory that is not `RETIRED`, and is
    subject to the lease-overlap rule: a branch may not sign a lease whose
    closed occupancy interval intersects another `SIGNED` lease at the same
    site address. Lease intervals are closed — both `term_start` and
    `term_end` are inclusive, with `term_end` on or after `term_start` — so
    unlike territory assignments, adjacency conflicts: a new lease starting
    the day after an existing lease's last day still touches the boundary,
    and the request is rejected with `ERR_LEASE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_closed_interval_adjacency_conflicts
    """
    territory_a = create_territory()
    territory_b = create_territory()
    branch_a, _ = create_branch(
        territory_a["id"], site_address="1 Shared Plaza",
    )
    validate_success(api_client.approve_site(
        branch_a["id"],
        {
            "monthly_rent_cents": 150000,
            "term_start": "2026-08-01T00:00:00Z",
            "term_end": "2027-07-31T00:00:00Z",
        },
        ADMIN,
    ))
    branch_b, _ = create_branch(
        territory_b["id"], site_address="1 Shared Plaza",
    )

    # term_start equal to the existing term_end: closed intervals touch.
    validate_error(
        api_client.approve_site(
            branch_b["id"],
            {
                "monthly_rent_cents": 160000,
                "term_start": "2027-07-31T00:00:00Z",
                "term_end": "2028-07-30T00:00:00Z",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_LEASE_OVERLAP,
    )

    # One day later is clear of the closed interval.
    approved = validate_success(api_client.approve_site(
        branch_b["id"],
        {
            "monthly_rent_cents": 160000,
            "term_start": "2027-08-01T00:00:00Z",
            "term_end": "2028-07-31T00:00:00Z",
        },
        ADMIN,
    ))
    assert approved["operating_status"] == "SITE_APPROVED"


def test_lease_overlap_same_site_only():
    """PRD §3.3: "Approval requires the branch to be `PROPOSED`, requires
    `territory_id` to be set with a territory that is not `RETIRED`, and is
    subject to the lease-overlap rule: a branch may not sign a lease whose
    closed occupancy interval intersects another `SIGNED` lease at the same
    site address. Lease intervals are closed — both `term_start` and
    `term_end` are inclusive, with `term_end` on or after `term_start` — so
    unlike territory assignments, adjacency conflicts: a new lease starting
    the day after an existing lease's last day still touches the boundary,
    and the request is rejected with `ERR_LEASE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_closed_interval_adjacency_conflicts
    """
    territory_a = create_territory()
    territory_b = create_territory()
    branch_a, _ = create_branch(territory_a["id"], site_address="1 Shared Plaza")
    validate_success(api_client.approve_site(
        branch_a["id"],
        {
            "monthly_rent_cents": 150000,
            "term_start": "2026-08-01T00:00:00Z",
            "term_end": "2027-07-31T00:00:00Z",
        },
        ADMIN,
    ))
    # Different site address with a fully overlapping window: allowed.
    branch_b, _ = create_branch(territory_b["id"], site_address="2 Other Plaza")
    approved = validate_success(api_client.approve_site(
        branch_b["id"],
        {
            "monthly_rent_cents": 150000,
            "term_start": "2026-08-01T00:00:00Z",
            "term_end": "2027-07-31T00:00:00Z",
        },
        ADMIN,
    ))
    assert approved["operating_status"] == "SITE_APPROVED"
