"""Cross-cutting access control and the not-found error families.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_FOUND,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CHANGE_REQUEST_NOT_FOUND,
    ERR_KEYSET_NOT_FOUND,
    ERR_PATCH_NOT_FOUND,
    ERR_SITE_EVENT_NOT_FOUND,
    ERR_SITE_NOT_FOUND,
    ERR_TALKGROUP_NOT_FOUND,
    ERR_TALKPATH_REQUEST_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_UNIT_NOT_FOUND,
)
from test_helpers.assertions import assert_fields, assert_pagination_meta
from test_helpers.constants import (
    AGENCY_TYPE_LAW,
    AGENCY_TYPE_REGIONAL_AUTHORITY,
    BACKUP_GENERATOR,
    NONEXISTENT_ID,
)
from test_helpers.test_users import (
    CHANGE_CONTROL_BOARD,
    FLEET_ENGINEER,
    KEY_CUSTODIAN,
    RF_ENGINEER,
    SECURITY_OFFICER,
    SYSTEM_ADMIN,
    UNDECLARED_ROLE_HEADERS,
    make_agency_radio_manager_headers,
    make_dispatcher_headers,
)


def test_not_found_error_id_differs_for_every_path_resource_family(
    api: ApiClient, clock_at_start: str
):
    """One never-minted UUID, eleven single-resource reads, eleven *different*
    error identifiers — the not-found family is chosen by the path segment that
    failed to resolve, not by a single generic 404.

    PRD 2.4: "Path identifiers are resolved strictly left to right, and the first
    identifier that fails to resolve decides the error."

    PRD 2.4: "The system's path identifiers are `agency_id`, `site_id`,
    `template_id`, `unit_id`, `keyset_id`, `campaign_id`, `talkgroup_id`,
    `patch_id`, `event_id`, `change_request_id`, and `request_id`; they map
    respectively to `ERR_AGENCY_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_TEMPLATE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_KEYSET_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_TALKGROUP_NOT_FOUND`, `ERR_PATCH_NOT_FOUND`,
    `ERR_SITE_EVENT_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, and
    `ERR_TALKPATH_REQUEST_NOT_FOUND`."

    PRD 2.4: "5. Path identifiers resolve, left to right — otherwise the not-found
    error of the failing segment."

    Design: Corner/errors/error_not_found_for_every_path_resource_family
    """
    families = (
        ("agency_id", api.get_agency, ERR_AGENCY_NOT_FOUND),
        ("site_id", api.get_site, ERR_SITE_NOT_FOUND),
        ("template_id", api.get_template, ERR_TEMPLATE_NOT_FOUND),
        ("unit_id", api.get_unit, ERR_UNIT_NOT_FOUND),
        ("keyset_id", api.get_keyset, ERR_KEYSET_NOT_FOUND),
        ("campaign_id", api.get_otar_campaign, ERR_CAMPAIGN_NOT_FOUND),
        ("talkgroup_id", api.get_talkgroup, ERR_TALKGROUP_NOT_FOUND),
        ("patch_id", api.get_interop_patch, ERR_PATCH_NOT_FOUND),
        ("event_id", api.get_site_event, ERR_SITE_EVENT_NOT_FOUND),
        ("change_request_id", api.get_change_request, ERR_CHANGE_REQUEST_NOT_FOUND),
        ("request_id", api.get_talkpath_request, ERR_TALKPATH_REQUEST_NOT_FOUND),
    )

    seen = {}
    for segment, getter, expected_error_id in families:
        body = validate_error(getter(NONEXISTENT_ID, SYSTEM_ADMIN), expected_error_id, 404)
        seen[segment] = body["error_id"]

    assert len(seen) == 11, "all eleven path identifier families must be exercised"
    assert len(set(seen.values())) == 11, (
        f"each family must answer with its own error_id, got {seen}"
    )


def test_undeclared_role_header_is_unauthenticated_not_unauthorized(
    api: ApiClient, clock_at_start: str
):
    """A header pair that is well formed but names a role outside the eight is an
    authentication failure, not an authorisation one: the read answers
    `ERR_UNAUTHENTICATED`, and the very same read under a declared role succeeds.

    PRD 2.1: "The system recognises exactly eight roles, spelled exactly as
    follows: `SystemAdmin`, `RFEngineer`, `FleetEngineer`, `ChangeControlBoard`,
    `KeyCustodian`, `SecurityOfficer`, `AgencyRadioManager`, and `Dispatcher`."

    PRD 2.1: "An `X-User-Role` value outside that set of eight is likewise rejected
    with `ERR_UNAUTHENTICATED`."

    PRD 2.4: "2. `X-User-Role` is one of the eight declared roles — otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/error_unauthenticated_when_user_role_header_is_not_a_declared_role
    """
    site = fx.register_site(
        api,
        site_code="AUT-1",
        name="Auth One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )

    refused = api.get_site(site["id"], UNDECLARED_ROLE_HEADERS)
    body = validate_error(refused, ERR_UNAUTHENTICATED, 401)
    assert body["error_id"] != ERR_UNAUTHORIZED, (
        "an undeclared role fails authentication before authorisation is considered"
    )

    # The endpoint itself was fine; only the role spelling was not.
    allowed = validate_success(api.get_site(site["id"], SYSTEM_ADMIN), 200)
    assert_fields(allowed, id=site["id"], site_code="AUT-1")


def test_dispatcher_cannot_create_a_site(api: ApiClient, clock_at_start: str):
    """Site registration is a `SystemAdmin` exclusive: the identical body is refused
    with `ERR_UNAUTHORIZED` under `Dispatcher` and accepted under `SystemAdmin`, so
    the refusal is authority and not payload validation.

    PRD 2.1: "When the headers are well formed but the acting role is not among the
    roles authorised for the requested operation, the rejection is
    `ERR_UNAUTHORIZED` instead."

    PRD 2.1: "`SystemAdmin` covers regional-authority operations and finance: the
    agency registry, site registration, fee assessment, incident declaration, and
    the logical clock."

    PRD 2.1: "Write authority is narrow and is listed per endpoint in Section 4."

    Design: Corner/rbac/rbac_dispatcher_cannot_create_a_site
    """
    agency = fx.register_agency(
        api,
        name="RBAC Dispatch Agency",
        agency_code="RBD01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    body = f.site_payload(
        site_code="RBD-1",
        name="RBAC Site One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )

    refused = api.create_site(body, make_dispatcher_headers(agency["id"]))
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    # Nothing was written: the register is still empty.
    rows, meta = validate_paginated(api.list_sites(SYSTEM_ADMIN))
    assert rows == [], "a refused create must not leave a site behind"
    assert_pagination_meta(meta, total_count=0, has_more=False)

    # The same body under the authorised role is accepted, proving it was valid.
    created = validate_success(api.create_site(body, SYSTEM_ADMIN), 201)
    assert_fields(created, site_code="RBD-1", name="RBAC Site One", channel_capacity=4)


def test_every_declared_role_may_read_the_site_register(
    api: ApiClient, clock_at_start: str
):
    """Reads are universal: all eight declared roles — six opaque operator roles and
    both agency-backed roles — get the same one-row site register back.

    PRD 2.1: "Every read endpoint in the system is available to all eight roles."

    PRD 2.1: "The system recognises exactly eight roles, spelled exactly as
    follows: `SystemAdmin`, `RFEngineer`, `FleetEngineer`, `ChangeControlBoard`,
    `KeyCustodian`, `SecurityOfficer`, `AgencyRadioManager`, and `Dispatcher`."

    Design: Corner/rbac/rbac_every_declared_role_may_read_the_site_register
    """
    agency = fx.register_agency(
        api,
        name="Shared Read Agency",
        agency_code="SHR01",
        agency_type=AGENCY_TYPE_REGIONAL_AUTHORITY,
        recorder_retention_days=365,
    )
    site = fx.register_site(
        api,
        site_code="SHR-1",
        name="Shared One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
    )

    all_eight = (
        SYSTEM_ADMIN,
        RF_ENGINEER,
        FLEET_ENGINEER,
        CHANGE_CONTROL_BOARD,
        KEY_CUSTODIAN,
        SECURITY_OFFICER,
        make_agency_radio_manager_headers(agency["id"]),
        make_dispatcher_headers(agency["id"]),
    )
    assert len(all_eight) == 8, "the register must be read once per declared role"

    for headers in all_eight:
        rows, meta = validate_paginated(api.list_sites(headers))
        assert_pagination_meta(meta, total_count=1, has_more=False)
        assert len(rows) == 1, f"{headers} must see the single site row"
        assert_fields(rows[0], id=site["id"], site_code="SHR-1", name="Shared One")
