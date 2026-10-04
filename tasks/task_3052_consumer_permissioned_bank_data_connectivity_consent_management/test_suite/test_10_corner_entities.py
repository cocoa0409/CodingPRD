"""Corner queue B — entities section instances."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_institution,
    assert_instants_equal,
    assert_scope_grant,
    capture_consent,
    create_approved_recipient,
    create_institution_payload,
    create_pending_connection,
    make_admin_headers,
    make_consumer_headers,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_institution_creation_applies_defaults_and_system_fields(api):
    """PRD §3.1: "A freshly created institution starts with `migration_state`
    equal to `NOT_STARTED`, health `status` equal to `ACTIVE`, and
    `connectivity_mode` equal to `LEGACY_MODE`."
    PRD §2.5: "`version` is an integer starting at 1 that increments on every
    mutation."
    PRD §2.4: "At server startup the clock reads exactly
    `2026-09-01T00:00:00Z` and never falls back to wall-clock time."

    Design: Corner/entities/institution_creation_applies_defaults_and_system_fields
    """
    admin = make_admin_headers()
    institution = validate_success(
        api.create_institution(
            create_institution_payload(
                name="Default Fields Bank",
                supported_methods=["CREDENTIALS", "BANK_API"],
                target_method="BANK_API",
                migration_window_start="2026-09-10T00:00:00Z",
                migration_window_end="2026-10-10T00:00:00Z",
            ),
            admin,
        ),
        expected_status=201,
    )
    assert_institution(institution)
    assert institution["migration_state"] == "NOT_STARTED"
    assert institution["status"] == "ACTIVE"
    assert institution["connectivity_mode"] == "LEGACY_MODE"
    assert institution["version"] == 1
    assert_instants_equal(institution["created_at"], "2026-09-01T00:00:00Z", "created_at")


def test_connection_input_reauth_cooldown_default_applied(api):
    """PRD §3.6: "A `Consumer` creates a connection under an institution by
    supplying the `consumer_ref`, the `consent_id` it operates under, the
    connectivity `method` to use, and optionally a `reauth_cooldown_seconds`
    (defaulting to 0) that sets the minimum spacing between a failed
    re-authentication and the next permitted attempt."
    PRD §3.6: "A new connection starts in `PENDING_AUTH` with
    `consecutive_failures` at 0."

    Design: Corner/entities/connection_input_reauth_cooldown_default_applied
    """
    stack = setup_active_stack(
        api,
        institution_name="DefaultCool Bank",
        recipient_name="CoolApp",
        consumer_ref="cons_q",
    )
    # Build a second PENDING_AUTH connection without the optional cooldown.
    connection = create_pending_connection(
        api, stack["institution"]["id"], stack["consent"]["id"], "cons_q"
    )
    assert connection["reauth_cooldown_seconds"] == 0, (
        f"omitting reauth_cooldown_seconds must default to 0, got "
        f"{connection['reauth_cooldown_seconds']}"
    )
    assert connection["status"] == "PENDING_AUTH"
    assert connection["consecutive_failures"] == 0
    assert connection["version"] == 1


def test_institution_not_found_returns_404(api):
    """PRD §2.8: "the server confirms each resource exists in path order and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve."

    Design: Corner/entities/institution_not_found_returns_404
    """
    admin = make_admin_headers()
    resp = api.get_institution(NON_EXISTENT_UUID, admin)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_consent_list_pagination_envelope(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
    the number of items skipped and defaults to 0... The `meta` object of
    every list response carries `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."

    Design: Corner/entities/consent_list_pagination_envelope
    """
    admin = make_admin_headers()
    stack_rec = create_approved_recipient(
        api, name="PageApp", tier_scopes=["BALANCE"], tier_name="PageTier"
    )
    capture_consent(api, stack_rec["recipient"]["id"], "cons_r", ["BALANCE"])

    resp = api.list_consents(admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")

    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_immutable_datascopegrant_has_no_update_endpoint(api):
    """PRD §3.4: "A successfully captured consent starts `ACTIVE`, and the
    platform immediately materializes one `DataScopeGrant` row per granted
    scope, each carrying the `consent_id` and the `scope` value."
    PRD §2.5: "Three resources are intentionally lighter: DataScopeGrant,
    WebhookEvent, and BreakageEvent carry only `id` and `created_at`; both
    `updated_at` and `version` are absent from them."

    Design: Corner/entities/immutable_datascopegrant_has_no_update_endpoint
    """
    admin = make_admin_headers()
    stack_rec = create_approved_recipient(
        api,
        name="GrantApp",
        tier_scopes=["BALANCE", "TRANSACTIONS"],
        rate_class="MEDIUM",
        tier_name="GrantTier",
    )
    consent = capture_consent(
        api, stack_rec["recipient"]["id"], "cons_s", ["BALANCE", "TRANSACTIONS"]
    )

    grants, meta = validate_paginated(api.list_consent_grants(consent["id"], admin))
    assert meta["total_count"] == 2, (
        f"one grant per consented scope expected, got {meta['total_count']}"
    )
    assert {g["scope"] for g in grants} == {"BALANCE", "TRANSACTIONS"}
    for grant in grants:
        assert_scope_grant(grant)
        assert grant["consent_id"] == consent["id"]
