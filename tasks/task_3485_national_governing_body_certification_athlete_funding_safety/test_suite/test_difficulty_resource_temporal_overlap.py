"""Difficulty tests: resource_temporal_overlap — two resources with opposite
interval semantics: certification-cycle windows are half-open (touching
allowed) while commercial-deal exclusivity windows are closed with a
mandatory one-day gap (touching rejected).
"""
from test_helpers import (
    ApiErrorId,
    create_certification_cycle,
    create_commercial_deal,
    create_governing_body,
    setup_certified_body,
    setup_eligible_athlete,
    validate_error,
    validate_paginated,
)


def test_certification_cycle_half_open_adjacency(api, committee_admin_headers):
    """PRD certification-cycle section: "the new window must not overlap any
    existing cycle of the same body, though windows that merely touch — one's
    start equal to a prior cycle's end — are permitted (a true overlap is
    rejected with `ERR_CYCLE_WINDOW_OVERLAP`)".

    Design: Difficulty/resource_temporal_overlap/certification_cycle_half_open_adjacency
    """
    body = create_governing_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    cycle_a = create_certification_cycle(
        body["id"],
        api=api,
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-12-01T00:00:00Z",
    )
    assert cycle_a["status"] == "SCHEDULED"

    # Interior overlap with [2026-09-01, 2026-12-01): rejected.
    resp = api.create_certification_cycle(
        body["id"],
        {
            "window_start": "2026-10-15T00:00:00Z",
            "window_end": "2027-02-01T00:00:00Z",
        },
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

    # Half-open adjacency: starting exactly at the prior cycle's window_end
    # is permitted.
    cycle_c = create_certification_cycle(
        body["id"],
        api=api,
        window_start="2026-12-01T00:00:00Z",
        window_end="2027-03-01T00:00:00Z",
    )
    assert cycle_c["status"] == "SCHEDULED"

    cycles, meta = validate_paginated(
        api.list_certification_cycles(body["id"], committee_admin_headers)
    )
    assert meta["total_count"] == 2, (
        f"the body must hold exactly the two legal cycles, got {meta['total_count']}"
    )
    assert len(cycles) == 2


def test_deal_exclusivity_closed_interval_gap(api, committee_admin_headers):
    """PRD commercial-rights section: "exclusivity is a **closed** interval
    per athlete, so a new window that overlaps another non-terminal deal of
    the same athlete — or that sits closer than one full day to it — is
    rejected with `ERR_DEAL_EXCLUSIVITY_OVERLAP`, while a gap of exactly one
    day or more is permitted."

    Design: Difficulty/resource_temporal_overlap/deal_exclusivity_closed_interval_gap
    """
    body = setup_certified_body(
        api=api,
        name="US Climb",
        sport_code="CLMB",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Rue Crag", date_of_birth="1999-07-07"
    )
    deal_a = create_commercial_deal(
        athlete["id"],
        api=api,
        sponsor_name="Sponsor A",
        gross_value_cents=100000,
        basis="GROSS_BASIS",
        exclusivity_start="2027-01-01T00:00:00Z",
        exclusivity_end="2027-03-31T00:00:00Z",
    )
    assert deal_a["status"] == "PROPOSED"

    # Closed interval: a deal starting exactly on A's exclusivity_end touches
    # it and is rejected.
    resp = api.create_commercial_deal(
        athlete["id"],
        {
            "sponsor_name": "Sponsor B",
            "gross_value_cents": 100000,
            "basis": "GROSS_BASIS",
            "exclusivity_start": "2027-03-31T00:00:00Z",
            "exclusivity_end": "2027-05-01T00:00:00Z",
        },
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEAL_EXCLUSIVITY_OVERLAP)

    # A start exactly one full day after A's end clears the mandatory gap.
    deal_c = create_commercial_deal(
        athlete["id"],
        api=api,
        sponsor_name="Sponsor C",
        gross_value_cents=100000,
        basis="GROSS_BASIS",
        exclusivity_start="2027-04-01T00:00:00Z",
        exclusivity_end="2027-06-30T00:00:00Z",
    )
    assert deal_c["status"] == "PROPOSED"
