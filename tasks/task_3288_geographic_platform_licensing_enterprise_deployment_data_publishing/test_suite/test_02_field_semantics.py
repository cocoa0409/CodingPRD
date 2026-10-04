"""Field-level corner tests: defaults, required fields, enum constraints,
system-field immutability, and body foreign-key ordering."""
from test_helpers import (
    ApiErrorId,
    LA_HEADERS,
    NON_EXISTENT_UUID,
    create_named_user_payload,
    get_success_data,
    make_named_user_headers,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import create_draft_item, invite_user, set_clock, setup_org


def test_named_user_create_missing_email_rejected(api):
    """PRD section 2.10: "**Body shape (priority 2.5).** All required input
    fields must be present with matching types, and enum fields must carry
    members of their declared enum; unknown body fields are ignored — else
    `ERR_INVALID_REQUEST`."
    PRD section 3.6: "A `LicenseAdmin` invites a named user by supplying the
    `organization_id`, a `username` and `email` (each unique within the
    organization; a collision is rejected with `ERR_DUPLICATE_VALUE`), the
    `named_user_level` — one of `VIEWER`, `EDITOR`, `FIELD_WORKER`, `CREATOR`,
    `PROFESSIONAL`, or `PROFESSIONAL_PLUS` — and the
    `home_license_grant_id`."

    Design: Corner/entities/named_user_create_missing_email_returns_invalid_request
    """
    base = setup_base_chain()
    payload = create_named_user_payload(base["org"]["id"], base["grant"]["id"], username="noemail")
    del payload["email"]
    resp = api.create_named_user(payload, LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows = api.list_named_users(LA_HEADERS, params={"organization_id": base["org"]["id"]}).json()["data"]
    assert rows == [], f"no NamedUser row must persist; got {rows}"


def test_named_user_create_invalid_level_enum_rejected(api):
    """PRD section 2.10: "**Body shape (priority 2.5).** All required input
    fields must be present with matching types, and enum fields must carry
    members of their declared enum; unknown body fields are ignored — else
    `ERR_INVALID_REQUEST`."
    PRD section 3.6: "the `named_user_level` — one of `VIEWER`, `EDITOR`,
    `FIELD_WORKER`, `CREATOR`, `PROFESSIONAL`, or `PROFESSIONAL_PLUS`".

    Design: Corner/entities/named_user_create_with_invalid_level_enum_rejected
    """
    base = setup_base_chain()
    payload = create_named_user_payload(
        base["org"]["id"], base["grant"]["id"],
        username="x", email="x@meridian.example", named_user_level="SUPERUSER")
    resp = api.create_named_user(payload, LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows = api.list_named_users(LA_HEADERS, params={"organization_id": base["org"]["id"]}).json()["data"]
    assert rows == []


def test_named_user_system_fields_ignore_client_input(api):
    """PRD section 2.11: "Unknown body fields are ignored rather than
    rejected."
    PRD section 3.6: "The new user record starts in `INVITED` status."
    PRD section 2.4: "`version` (integer): a system-managed integer that
    increments on every mutation of the resource".

    Design: Corner/entities/named_user_status_is_system_set_and_input_ignored
    """
    base = setup_base_chain()
    payload = create_named_user_payload(
        base["org"]["id"], base["grant"]["id"], username="eve", email="eve@meridian.example")
    payload["status"] = "ACTIVE"
    payload["version"] = 99
    resp = api.create_named_user(payload, LA_HEADERS)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "INVITED"
    assert data["version"] == 1


def test_named_user_body_fk_checked_in_input_order(api):
    """PRD section 2.6: "Create endpoints whose request bodies reference other
    entities by foreign key resolve those references in the endpoint's
    declared input order — `organization_id` before `license_product_id`
    before `home_license_grant_id`, and so on — and surface the first missing
    reference with the corresponding 404."

    Design: Corner/entities/named_user_body_fk_checked_in_input_order
    """
    set_clock()
    missing_org = "00000000-0000-4000-8000-000000000001"
    missing_grant = "00000000-0000-4000-8000-000000000002"
    payload = create_named_user_payload(missing_org, missing_grant, username="a", email="a@x.example")
    resp = api.create_named_user(payload, LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_FOUND)

    org = setup_org()
    payload = create_named_user_payload(org["id"], missing_grant, username="a", email="a@x.example")
    resp = api.create_named_user(payload, LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND)


def test_content_item_get_round_trips_stored_fields(api):
    """PRD section 3.9: "ContentItems are created by `NamedUser` principals in
    `DRAFT` status with sharing level `PRIVATE`, with `owner_named_user_id`
    recorded from `X-User-ID`."
    PRD section 2.2: "operations that create or modify a resource will return
    the created or updated resource object in the data field."

    Design: Corner/entities/content_item_get_round_trips_stored_fields
    """
    base = setup_with_user()
    item = create_draft_item(
        base["org"]["id"], base["user"]["id"],
        title="Trailheads", item_kind="FEATURE_LAYER", storage_bytes=2048,
        contains_licensed_basemap=False, offline_enabled=False)
    resp = api.get_content_item(item["id"], make_named_user_headers(base["user"]["id"]))
    data = validate_success(resp)
    assert data["title"] == "Trailheads"
    assert data["item_kind"] == "FEATURE_LAYER"
    assert data["storage_bytes"] == 2048
    assert data["sharing_level"] == "PRIVATE"
    assert data["status"] == "DRAFT"
    assert data["owner_named_user_id"] == base["user"]["id"]
    assert data["contains_licensed_basemap"] is False
    assert data["offline_enabled"] is False


def test_content_item_create_applies_boolean_defaults(api):
    """PRD section 3.9: "three optional fields: `derived_from_item_id`
    (present when the item is a derivative work of another item),
    `contains_licensed_basemap` (defaulting to false), and `offline_enabled`
    (defaulting to false)."

    Design: Corner/entities/content_item_create_applies_boolean_defaults
    """
    base = setup_with_user()
    resp = api.create_content_item(
        {
            "organization_id": base["org"]["id"],
            "title": "Defaults",
            "item_kind": "WEB_MAP",
            "storage_bytes": 10,
        },
        make_named_user_headers(base["user"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["contains_licensed_basemap"] is False
    assert data["offline_enabled"] is False
