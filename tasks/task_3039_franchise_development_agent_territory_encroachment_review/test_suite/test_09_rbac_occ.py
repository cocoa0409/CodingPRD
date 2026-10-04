"""Role/ownership authorization, segregation of duties, and OCC on territory
version (PRD §2.1, §2.5, §2.7, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_application,
    create_franchisee,
    create_mandate,
    create_site_application_payload,
    create_store,
    create_territory,
    get_territory,
    make_development_agent_headers,
    setup_assigned_territory,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_site_application_create_with_stale_territory_version_412(api):
    """PRD §2.5: "Creating a site application requires the request to carry
    `expected_territory_version` — a non-optional field holding the client's
    last observed `version` of the target territory. If the territory's
    current `version` has advanced since (for example because another writer
    created an application against it or reassigned it), the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "the create itself increments the territory's `version` by 1"

    Design: Corner/cross_cutting_layers/site_application_create_with_stale_territory_version_412
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    observed = ctx["territory"]["version"]
    first = validate_success(
        api.create_site_application(
            create_site_application_payload(ctx["territory"]["id"], applicant["id"], observed,
                                            proposed_address="1 First Ave"),
            da_headers), 201)
    # The first create bumped the territory version; the same observed version
    # is now stale for a second create.
    resp = api.create_site_application(
        create_site_application_payload(ctx["territory"]["id"], applicant["id"], observed,
                                        proposed_address="2 Second Ave",
                                        proposed_lat=40.06, proposed_lng=-75.06,
                                        proposed_open_date="2027-02-01T00:00:00Z"),
        da_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_territory(ctx["territory"]["id"])["version"] == observed + 1
    rows, meta = validate_paginated(
        api.list_territory_site_applications(ctx["territory"]["id"], da_headers))
    assert meta["total_count"] == 1


def test_site_application_create_with_current_territory_version_succeeds(api):
    """PRD §2.5: "Creating a site application requires the request to carry
    `expected_territory_version` — a non-optional field holding the client's
    last observed `version` of the target territory."
    PRD §3.2: "the create itself increments the territory's `version` by 1 —
    which is exactly why a second agent's concurrent create, observed against
    the older version, fails stale."

    Design: Corner/cross_cutting_layers/site_application_create_with_stale_territory_version_412
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"])
    assert app["status"] == "DRAFT"
    # Re-read the current version and create a second application successfully.
    fresh_v = get_territory(ctx["territory"]["id"])["version"]
    second = validate_success(
        api.create_site_application(
            create_site_application_payload(ctx["territory"]["id"], applicant["id"], fresh_v,
                                            proposed_address="2 Second Ave"),
            da_headers), 201)
    assert second["status"] == "DRAFT"
    assert get_territory(ctx["territory"]["id"])["version"] == fresh_v + 1


def test_development_agent_cannot_schedule_in_foreign_territory(api, franchisor_ops_headers):
    """PRD §3.5: "The caller must be the assigned agent of the store's
    territory."
    PRD §2.1: "When `X-User-Role` is `DevelopmentAgent`, `X-User-ID` is the
    `id` of the acting DevelopmentAgent record; ownership checks on any
    resource that references a territory compare the territory's
    `assigned_agent_id` to `X-User-ID`." and "Attempting an operation outside
    the caller's role, or failing an entity-backed ownership check, is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/development_agent_cannot_schedule_in_foreign_territory
    """
    t1 = create_territory(code="T-RB-3A", region="RBAC A")
    t2 = create_territory(code="T-RB-3B", region="RBAC B")
    da1 = create_agent(legal_name="DA One", contact_email="da1@example.com")
    da2 = create_agent(legal_name="DA Two", contact_email="da2@example.com")
    validate_success(api.assign_agent(t1["id"], {"agent_id": da1["id"]}, franchisor_ops_headers), 200)
    validate_success(api.assign_agent(t2["id"], {"agent_id": da2["id"]}, franchisor_ops_headers), 200)
    owner = create_franchisee()
    store = create_store(t1["id"], owner["id"])
    mandate = create_mandate(store["id"])
    resp = api.schedule_remodel_mandate(
        mandate["id"],
        {"closure_start": "2026-10-01T00:00:00Z", "closure_end": "2026-10-15T00:00:00Z"},
        make_development_agent_headers(da2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    from test_helpers import get_remodel_mandate
    assert get_remodel_mandate(mandate["id"])["status"] == "ISSUED"
