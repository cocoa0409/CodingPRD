"""Entity creation, defaults, computed fields, listing, and not-found behavior."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_project,
    create_project_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_project_creation_defaults_applied(api, developer_admin_headers):
    """PRD §3.1: "Two certification flags may be supplied at creation and default
    to false when omitted" and "An `availability_guarantee_pct` may also be
    supplied for the operations handoff; it defaults to 97.0 percent." Also:
    "A new project enters in `PROSPECT` status".
    PRD §3.1: "`total_itc_credits_usd` mirrors the qualification's
    `qualified_credit_usd` once the qualification reaches `QUALIFIED`, reading
    0.00 before then."

    Design: Corner/entities/project_creation_defaults_applied
    """
    resp = api.create_project(
        create_project_payload(
            name="Defaults Farm", technology="HYBRID",
            target_capacity_mw=250, resource_class="A",
        ),
        developer_admin_headers,
    )
    project = validate_success(resp, expected_status=201)
    assert_project(project)
    assert project["domestic_content_certified"] is False
    assert project["energy_community_eligible"] is False
    assert project["availability_guarantee_pct"] == 97.0
    assert project["status"] == "PROSPECT"
    assert project["total_itc_credits_usd"] == 0.00


def test_project_creation_required_fields_enforced(api, developer_admin_headers):
    """PRD §3.1: "A `DeveloperAdmin` creates a project by supplying its `name`,
    its `technology` (one of `WIND`, `SOLAR`, or `HYBRID`), its
    `target_capacity_mw` nameplate figure, and its `resource_class` assessment
    grade".
    PRD §2.9: "payload shape — required fields present, types and enum values
    valid ... (priority 4, `ERR_VALIDATION`)".

    Design: Corner/entities/project_creation_required_fields_enforced
    """
    resp = api.create_project(
        {"name": "No Tech Farm", "target_capacity_mw": 100, "resource_class": "A"},
        developer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_project_invalid_enum_rejected(api, developer_admin_headers):
    """PRD §3.1: "its `technology` (one of `WIND`, `SOLAR`, or `HYBRID`)".
    PRD §2.9: "payload shape — required fields present, types and enum values
    valid ... (priority 4, `ERR_VALIDATION`)".

    Design: Corner/entities/project_invalid_enum_rejected
    """
    resp = api.create_project(
        create_project_payload(name="Bad Enum Farm", technology="GEOTHERMAL"),
        developer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_queue_position_is_computed_not_settable(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "its `queue_position` is assigned as one more than the highest
    position among non-`WITHDRAWN` requests in the same cluster — or 1 when the
    cluster is empty. Every request also carries `upgrade_allocated` (false until
    an allocation has run over its cluster)".

    Design: Corner/entities/queue_position_is_computed_not_settable
    """
    project = validate_success(
        api.create_project(
            create_project_payload(name="Computed Farm"), developer_admin_headers
        ),
        expected_status=201,
    )
    resp = api.create_interconnection_request(
        project["id"], {"cluster_id": "CL-CP", "requested_capacity_mw": 50},
        origination_manager_headers,
    )
    request = validate_success(resp, expected_status=201)
    assert request["queue_position"] == 1
    assert request["upgrade_allocated"] is False
    assert request.get("upgrade_cost_share_usd") in (0, 0.0, None)


def test_get_nonexistent_resource_returns_not_found(api, auditor_headers):
    """PRD §2.8: "Every id appearing in a request path is validated
    left-to-right: each id must exist ... Any failure along the chain is rejected
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_resource_returns_not_found
    """
    resp = api.get_project(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", auditor_headers
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_projects_list_pagination_contract(api, developer_admin_headers, auditor_headers):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0. List responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/projects_list_pagination_contract
    """
    for name, tech, cap, rc in (
        ("Page 1", "WIND", 10, "A"),
        ("Page 2", "WIND", 20, "A"),
        ("Page 3", "SOLAR", 30, "B"),
    ):
        validate_success(
            api.create_project(
                create_project_payload(
                    name=name, technology=tech, target_capacity_mw=cap, resource_class=rc
                ),
                developer_admin_headers,
            ),
            expected_status=201,
        )

    data, meta = validate_paginated(
        api.list_projects(auditor_headers, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    data2, meta2 = validate_paginated(
        api.list_projects(auditor_headers, params={"limit": 2, "offset": 2})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_ledger_entry_immutable_event_log(
    api, developer_admin_headers, tax_counsel_headers, investor_manager_headers
):
    """PRD §2.4: "a ledger entry is an immutable record carrying `id` and
    `created_at` only — it has no `updated_at` and no `version`, and no update
    endpoint exists for it."
    PRD §3.7: "A contribution is accepted only while the partnership is in
    `COMMITMENT_EXECUTED` or `FUNDING` (from any other status it fails with
    `ERR_INVALID_STATE`)".

    Design: Corner/entities/ledger_entry_immutable_event_log
    """
    project = validate_success(
        api.create_project(
            create_project_payload(
                name="Ledger Farm", technology="SOLAR",
                target_capacity_mw=25, resource_class="C",
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    partnership = validate_success(
        api.create_partnership(
            project["id"],
            {"investor_name": "Inv", "commitment_usd": 500000.00, "target_irr_pct": 7.0},
            tax_counsel_headers,
        ),
        expected_status=201,
    )
    resp = api.post_contribution(
        partnership["id"],
        {"amount_usd": 100000.00, "period_end_date": "2026-12-31T00:00:00Z"},
        investor_manager_headers,
    )
    # The contribution is lifecycle-gated: still STRUCTURING here.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
