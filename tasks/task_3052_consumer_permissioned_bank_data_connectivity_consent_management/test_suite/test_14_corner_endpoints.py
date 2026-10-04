"""Corner queue B — endpoints section instances."""

from test_helpers import (
    ApiErrorId,
    capture_consent,
    create_agreement_payload,
    create_consent_payload,
    create_institution_with_agreement,
    create_approved_recipient,
    make_admin_headers,
    make_consumer_headers,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_consent_create_supersedes_prior_consent_and_repoints_connection(api):
    """PRD §3.4: "Capturing a consent for a `(consumer_ref, recipient)` pair
    that already has `ACTIVE` consents supersedes every one of them: each
    prior consent moves to `SUPERSEDED`, and each of the superseded consent's
    connections is re-pointed to the new consent when the new consent's scopes
    are a superset of the old consent's scopes — in which case a
    `CONNECTION_MIGRATED` webhook is emitted — or is moved to `DISCONNECTED`
    when the scopes are not a superset, with a `CONSENT_REVOKED` webhook
    emitted instead."

    Design: Corner/endpoints/consent_create_supersedes_prior_consent_and_repoints_connection
    """
    stack = setup_active_stack(
        api,
        institution_name="Supersede Bank",
        recipient_name="SupersedeApp",
        consumer_ref="cons_af",
        data_scopes=["BALANCE"],
        permitted_fields_by_scope={
            "BALANCE": ["current_cents"],
            "TRANSACTIONS": ["amount_cents"],
        },
        tier_scopes=["BALANCE", "TRANSACTIONS"],
        rate_class="MEDIUM",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]
    old_consent = stack["consent"]
    conn_id = stack["connection"]["id"]

    current = validate_success(api.get_recipient(stack["recipient"]["id"], admin))
    new_consent = validate_success(
        api.create_consent(
            stack["recipient"]["id"],
            create_consent_payload(
                consumer_ref="cons_af",
                data_scopes=["BALANCE", "TRANSACTIONS"],
                expires_at="2027-06-30T00:00:00Z",
                expected_recipient_version=current["version"],
            ),
            consumer,
        ),
        expected_status=201,
    )

    superseded = validate_success(api.get_consent(old_consent["id"], consumer))
    assert superseded["status"] == "SUPERSEDED"

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "ACTIVE", (
        "a superset-scope consent must re-point (not disconnect) the connection"
    )
    assert connection["consent_id"] == new_consent["id"], (
        f"connection must be re-pointed to the new consent {new_consent['id']}, "
        f"got {connection['consent_id']}"
    )

    events, meta = validate_paginated(
        api.list_connection_webhook_events(
            conn_id, admin, params={"event_type": "CONNECTION_MIGRATED"}
        )
    )
    assert meta["total_count"] == 1, "re-pointing must emit one CONNECTION_MIGRATED webhook"


def test_stale_version_on_agreement_create_rejected(api):
    """PRD §2.7: "publishing a new institution agreement: the
    agreement-creation request must carry `expected_institution_version`
    matching the target institution's current `version`. Because the new
    agreement supersedes the previously active one, a mismatch means the
    client was drafting against an outdated institutional posture, and the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/stale_version_on_agreement_create_rejected
    """
    admin = make_admin_headers()
    inst = create_institution_with_agreement(api, name="OccBank", rate_limit_per_hour=50)
    institution = inst["institution"]
    first = inst["agreement"]

    stale_version = institution["version"]  # the pre-first-agreement version
    resp = api.create_agreement(
        institution["id"],
        create_agreement_payload(
            rate_limit_per_hour=75,
            permitted_fields_by_scope={"BALANCE": ["current_cents"]},
            expected_institution_version=stale_version,
        ),
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    agreements, meta = validate_paginated(api.list_agreements(institution["id"], admin))
    assert meta["total_count"] == 1, "the stale create must not persist a second agreement"
    assert agreements[0]["id"] == first["id"]
    assert agreements[0]["active"] is True

    reread = validate_success(api.get_institution(institution["id"], admin))
    assert reread["version"] == institution["version"] + 1, (
        "only the successful first agreement create may bump the institution version"
    )
