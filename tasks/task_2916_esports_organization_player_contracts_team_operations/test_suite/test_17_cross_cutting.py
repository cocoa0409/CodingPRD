"""Both concurrency tokens, exercised on one fixture.

Each of these two writes is additive: repeating it with different arguments is
ordinary product behaviour, so nothing in the request itself is wrong. Only the
parent's version tells the client that the picture it was reasoning about has moved
on, and a refused token must leave the parent's counters where they were.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_general_manager_headers,
    make_league_admin_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_replayed_parent_version_is_refused_and_the_refreshed_one_is_accepted():
    """The same legitimate body fails on a stale token and succeeds on a re-read one, twice over.

    PRD: "Two write operations in this system are **additive** — repeating them with different
    arguments is legitimate product behaviour, so a client cannot discover from the result alone that
    it was reasoning about a stale parent."
    PRD: "A `POST /sponsorship-deals/{id}/deliverables` request must carry `expected_deal_version` as
    a mandatory body field, holding the `version` of that `SponsorshipDeal` as the client last read
    it."
    PRD: "If the value does not equal the deal's current `version` — because another writer has
    placed a deliverable, activated the deal or otherwise advanced it since the client's read — the
    placement is rejected with `ERR_DEAL_VERSION_STALE` and HTTP 412, and no assignment is created."
    PRD: "A `POST /roster-moves` request must carry `expected_organization_version` as a mandatory
    body field, holding the `version` of the filing `Organization` as the client last read it."
    PRD: "If the value does not equal the organization's current `version`, the filing is rejected
    with `ERR_ORGANIZATION_VERSION_STALE` and HTTP 412, and no move is created."
    PRD: "Neither check consults its own resource's `version`; both consult the named parent — the
    deal in the first case, the organization in the second."
    PRD: "The deal's `assigned_count` increases and the deal's own `version` advances — which, by
    design, invalidates any other client's `expected_deal_version` and forces it to re-read before
    placing its own deliverable."

    Design: Corner/cross-cutting complexity layers/stale_parent_versions_are_refused_and_the_refreshed_version_succeeds
    """
    ctx = fixtures.setup_signed_player()
    org_id = ctx["org"]["id"]
    admin_headers = make_league_admin_headers()
    gm_headers = make_general_manager_headers(org_id)
    sponsor_headers = make_sponsorship_manager_headers(org_id)

    deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Voltcharge Energy",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=3,
    )
    deal_version_after_activation = deal["version"]

    first_placement = validate_success(
        api_client.create_deliverable_assignment(
            deal["id"],
            factories.create_deliverable_payload(
                ctx["contract"]["id"],
                deal_version_after_activation,
                deliverable_type="STREAM_SEGMENT",
                due_at="2026-08-20T00:00:00Z",
            ),
            sponsor_headers,
        ),
        201,
    )
    refreshed_deal_version = fixtures.current_deal_version(deal["id"], org_id)
    assert refreshed_deal_version > deal_version_after_activation

    replayed_body = factories.create_deliverable_payload(
        ctx["contract"]["id"],
        deal_version_after_activation,
        deliverable_type="SOCIAL_POST",
        due_at="2026-08-21T00:00:00Z",
    )
    validate_error(
        api_client.create_deliverable_assignment(deal["id"], replayed_body, sponsor_headers),
        ApiErrorId.ERR_DEAL_VERSION_STALE.value,
        412,
    )

    accepted_body = dict(replayed_body)
    accepted_body["expected_deal_version"] = refreshed_deal_version
    second_placement = validate_success(
        api_client.create_deliverable_assignment(deal["id"], accepted_body, sponsor_headers),
        201,
    )

    deliverables, deliverables_meta = validate_paginated(
        api_client.list_deal_deliverables(
            deal["id"], sponsor_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert deliverables_meta["total_count"] == 2
    assert {row["id"] for row in deliverables} == {
        first_placement["id"],
        second_placement["id"],
    }
    assert fixtures.read_deal(deal["id"], org_id)["assigned_count"] == 2

    stale_organization_version = validate_success(
        api_client.get_organization(org_id, admin_headers)
    )["version"]
    patched = validate_success(
        api_client.update_organization(
            org_id, {"annual_salary_budget_cents": 55000000}, admin_headers
        )
    )
    assert patched["version"] > stale_organization_version

    stale_filing = factories.create_roster_move_payload(
        org_id,
        ctx["player"]["id"],
        "RELEASE",
        ctx["contract"]["id"],
        stale_organization_version,
        effective_at="2026-08-10T00:00:00Z",
    )
    validate_error(
        api_client.create_roster_move(stale_filing, gm_headers),
        ApiErrorId.ERR_ORGANIZATION_VERSION_STALE.value,
        412,
    )

    _no_moves, no_moves_meta = validate_paginated(
        api_client.list_roster_moves(
            gm_headers, params={"organization_id": org_id, "limit": 10, "offset": 0}
        )
    )
    assert no_moves_meta["total_count"] == 0

    fresh_filing = dict(stale_filing)
    fresh_filing["expected_organization_version"] = patched["version"]
    filed = validate_success(api_client.create_roster_move(fresh_filing, gm_headers), 201)
    assert filed["move_status"] == "PENDING"

    moves, moves_meta = validate_paginated(
        api_client.list_roster_moves(
            gm_headers, params={"organization_id": org_id, "limit": 10, "offset": 0}
        )
    )
    assert moves_meta["total_count"] == 1
    assert [row["id"] for row in moves] == [filed["id"]]
