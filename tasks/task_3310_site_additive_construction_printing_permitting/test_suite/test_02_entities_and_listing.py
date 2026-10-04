"""Entity creation, listing, retrieval, and computed-field tests (PRD §2, §3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SITE_MGR,
    assert_jurisdiction,
    assert_printer_setup,
    assert_site,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_printer_setup_payload,
    create_site,
    create_site_payload,
    current_site_version,
    get_success_data,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_jurisdiction_create_returns_declared_fields_and_active_status(api, platform_admin_headers):
    """PRD §3.1: "Every jurisdiction is created with `status` `ACTIVE`".
    PRD §2.5: "`version` — an integer starting at 1 that increments on every
    mutation." PRD §4: "Operations that create a new resource return
    `201 Created`; operations that modify an existing resource return
    `200 OK`."

    Design: Corner/entities/jurisdiction_create_returns_declared_fields_and_active_status
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_jurisdiction(create_jurisdiction_payload(code="JA"), platform_admin_headers)
    data = validate_success(resp, 201)
    assert_jurisdiction(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_site_create_with_optional_community_deployment_omitted(api):
    """PRD §3.2: "an optional `community_deployment_id` (null for a stand-alone
    site)" and "A new site enters `REGISTERED` with `posture` `OPERATING`."

    Design: Corner/entities/site_create_with_optional_community_deployment_omitted
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JA2")
    site = create_site(jurisdiction["id"], address="1 Solo St")
    assert_site(site)
    assert site.get("community_deployment_id") is None
    assert site["status"] == "REGISTERED"
    assert site["posture"] == "OPERATING"


def test_site_list_pagination_limit_offset_total_count_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit` (defaults
    to 10, minimum 1, maximum 100) and `offset` (defaults to 0) ... The `meta`
    object on list responses carries `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/site_list_pagination_limit_offset_total_count_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JA3")
    for address in ("1 A", "2 B", "3 C"):
        create_site(jurisdiction["id"], address=address)
    rows, meta = validate_paginated(
        api.list_jurisdiction_sites(
            jurisdiction["id"], SITE_MGR, params={"limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    rows2, meta2 = validate_paginated(
        api.list_jurisdiction_sites(
            jurisdiction["id"], SITE_MGR, params={"limit": 2, "offset": 2}
        )
    )
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_site_get_unknown_id_returns_not_found(api, site_manager_headers):
    """PRD §2.6: "The server validates path identifiers strictly left to right,
    returning `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
    exist or whose parent linkage does not match the path."

    Design: Corner/entities/site_get_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.get_site(NON_EXISTENT_UUID, site_manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_jurisdiction_create_missing_required_field_returns_invalid_request(
    api, platform_admin_headers
):
    """PRD §3.1 requires "an integer `alternative_means_review_days` (at least
    1)" on jurisdiction creation; PRD §2.11 item 14: "required
    fields present and well-formed (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/jurisdiction_create_missing_required_field_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = create_jurisdiction_payload(code="JX")
    del payload["alternative_means_review_days"]
    resp = api.create_jurisdiction(payload, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_printer_setup_computed_is_within_tolerance(api, print_operator_headers):
    """PRD §3.4: "The server derives `is_within_tolerance` — true when the
    measured deviation is at most the tolerance."

    Design: Corner/entities/printer_setup_computed_is_within_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JA4")
    site = create_site(jurisdiction["id"], address="5 E")
    version = current_site_version(site["id"])
    resp = api.create_printer_setup(
        site["id"],
        create_printer_setup_payload(
            version, leveling_tolerance_mm=5.0, measured_level_deviation_mm=7.0
        ),
        print_operator_headers,
    )
    data = validate_success(resp, 201)
    assert_printer_setup(data)
    assert data["is_within_tolerance"] is False, "7.0 deviation > 5.0 tolerance"


def test_printer_setup_within_tolerance_at_boundary(api, print_operator_headers):
    """PRD §3.4: "The server derives `is_within_tolerance` — true when the
    measured deviation is at most the tolerance." PRD §2.7: "Whenever this
    document describes a comparison as inclusive (at least, at most, no later
    than, no earlier than), the boundary value satisfies the check."

    Design: Corner/entities/printer_setup_computed_is_within_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JA4B")
    site = create_site(jurisdiction["id"], address="5 EB")
    version = current_site_version(site["id"])
    resp = api.create_printer_setup(
        site["id"],
        create_printer_setup_payload(
            version, leveling_tolerance_mm=5.0, measured_level_deviation_mm=5.0
        ),
        print_operator_headers,
    )
    data = validate_success(resp, 201)
    assert data["is_within_tolerance"] is True, "5.0 deviation <= 5.0 tolerance (inclusive)"


def test_system_fields_id_created_at_updated_at_server_stamped(api):
    """PRD §2.5: "`id` — a server-minted UUID with no type prefix" and
    "`version` — an integer starting at 1 that increments on every mutation";
    PRD §2.4: "The logical clock starts at `2026-09-01T00:00:00Z` before any
    test-driving call is made."

    Design: Corner/entities/system_fields_id_created_at_updated_at_server_stamped
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JA5")
    site = create_site(jurisdiction["id"], address="7 F", soil_class="B",
                       foundation_kind="PIER_AND_BEAM")
    assert site["version"] == 1
    assert is_valid_uuid(site["id"])
    assert site["created_at"].startswith("2026-09-01T00:00:00"), (
        f"server must stamp created_at from the logical clock, got {site['created_at']}"
    )
