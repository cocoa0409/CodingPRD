"""Envelope assembly: creation, addressing and account provisioning."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    make_account_headers,
    validate_error,
    validate_success,
)


def test_create_envelope_returns_created_status(api):
    """PRD §3.1: "An envelope is drafted by its owning account. The creation
    payload names the `sender_account_id` and supplies a `subject` and a
    `retention_policy_id`".
    PRD §3.1: "A freshly created envelope holds the `CREATED` status with
    `legal_hold` false".
    PRD §2.5: "`version` (integer): a server-managed counter that is incremented
    by one on every modification to the resource."
    PRD §2.11: "At sealing, a `seal_hash` is computed ..." — before sealing the
    envelope carries no seal, so `is_sealed` is false.
    PRD §4: "Operations that create a new, stand-alone resource, or that add a
    new, distinct resource to a collection, return a `201 Created` status code."

    Design: Corner/entities/envelope_create_returns_201_with_initial_state
    """
    account = validate_success(
        api.create_account(
            {"name": "Acme Signing", "state_code": "CA", "tier": "STANDARD", "page_allowance": 25},
            TEST_USERS["admin_headers"],
        ),
        201,
    )
    policy = validate_success(
        api.create_retention_policy(
            {
                "name": "Std Retention",
                "scope": "GLOBAL",
                "retention_years": 3,
                "purge_mode": "ANONYMIZE_METADATA",
                "purge_grace_days": 0,
            },
            TEST_USERS["admin_headers"],
        ),
        201,
    )

    res = api.create_envelope(
        {
            "sender_account_id": account["id"],
            "subject": "Created envelope",
            "routing_mode": "SEQUENTIAL",
            "expires_after_days": 120,
            "sender_visible_window_days": 30,
            "retention_policy_id": policy["id"],
        },
        make_account_headers(account["id"]),
    )
    envelope = validate_success(res, 201)

    assert envelope["status"] == "CREATED", (
        f"a freshly created envelope must be CREATED, got {envelope['status']}"
    )
    assert envelope["is_sealed"] is False, "a draft envelope is not sealed"
    assert envelope["version"] == 1, f"a new envelope starts at version 1, got {envelope['version']}"
    assert envelope["legal_hold"] is False
    assert envelope["sender_account_id"] == account["id"]


def test_get_nonexistent_envelope_returns_not_found(api):
    """PRD §2.7: "a missing envelope yields `ERR_ENVELOPE_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/envelope_get_nonexistent_returns_not_found
    """
    res = api.get_envelope(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    validate_error(res, ApiErrorId.ERR_ENVELOPE_NOT_FOUND)
    assert res.status_code == 404


def test_add_recipient_under_missing_envelope_rejected(api):
    """PRD §2.7: "The system resolves such a path strictly left to right and
    rejects the request at the first identifier that does not resolve, before
    any business rule is evaluated: a missing envelope yields
    `ERR_ENVELOPE_NOT_FOUND` (HTTP 404)".
    PRD §3.1: "Recipients are added with a `role` — `SIGNER`, `APPROVER` or
    `COPY` — and an `email`".

    Design: Corner/entities/recipient_create_requires_existing_envelope
    """
    account = validate_success(
        api.create_account(
            {"name": "Acme Signing", "state_code": "CA", "tier": "STANDARD", "page_allowance": 25},
            TEST_USERS["admin_headers"],
        ),
        201,
    )

    res = api.add_recipient(
        NON_EXISTENT_UUID,
        {
            "role": "SIGNER",
            "email": "orphan@example.com",
            "routing_order": 1,
            "auth_level": "EMAIL_ACCESS",
            "consent_accepted": True,
        },
        make_account_headers(account["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ENVELOPE_NOT_FOUND)
    assert res.status_code == 404


def test_place_field_without_field_type_rejected(api, admin_headers):
    """PRD §2.7: "priority 34 rejects a request whose required body fields are
    missing or whose enum-valued field carries a member outside its declared
    set, with `ERR_INVALID_REQUEST` (HTTP 400)".
    PRD §3.1: "Each field placement names the `envelope_document_id` it sits on
    and the `recipient_id` responsible for it, and declares a `field_type` drawn
    from `SIGNATURE`, `INITIAL`, `DATE`, `TEXT` or `CHECKBOX`".

    Design: Corner/entities/field_placement_missing_required_field_type_returns_invalid_request
    """
    account = validate_success(
        api.create_account(
            {"name": "Acme Signing", "state_code": "CA", "tier": "STANDARD", "page_allowance": 25},
            admin_headers,
        ),
        201,
    )
    policy = validate_success(
        api.create_retention_policy(
            {
                "name": "Std Retention",
                "scope": "GLOBAL",
                "retention_years": 3,
                "purge_mode": "ANONYMIZE_METADATA",
                "purge_grace_days": 0,
            },
            admin_headers,
        ),
        201,
    )
    account_headers = make_account_headers(account["id"])
    envelope = validate_success(
        api.create_envelope(
            {
                "sender_account_id": account["id"],
                "subject": "Field envelope",
                "routing_mode": "SEQUENTIAL",
                "expires_after_days": 120,
                "sender_visible_window_days": 30,
                "retention_policy_id": policy["id"],
            },
            account_headers,
        ),
        201,
    )
    document = validate_success(
        api.add_document(envelope["id"], {"name": "Field.pdf", "page_count": 3}, account_headers),
        201,
    )
    recipient = validate_success(
        api.add_recipient(
            envelope["id"],
            {
                "role": "SIGNER",
                "email": "field@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
            account_headers,
        ),
        201,
    )

    # field_type is deliberately omitted: it is a declared, non-optional enum.
    res = api.place_field(
        envelope["id"],
        {
            "envelope_document_id": document["id"],
            "recipient_id": recipient["id"],
            "page_number": 1,
        },
        account_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert res.status_code == 400


def test_account_defaults_applied_when_optionals_omitted(api, admin_headers):
    """PRD §3.1: "An operator creates one by supplying a display `name` and a
    `state_code` naming the United States jurisdiction the organization operates
    in, together with an optional `tier` and an optional `page_allowance`."
    PRD §3.1: "A new account opens in `ACTIVE` status with a `credit_balance` of
    1000 credit units, a `tier` of `STANDARD` and a `page_allowance` of 25 pages."

    Design: Corner/entities/account_defaults_applied_when_optional_fields_omitted
    """
    res = api.create_account({"name": "Defaults Co", "state_code": "TX"}, admin_headers)
    account = validate_success(res, 201)

    assert account["tier"] == "STANDARD", f"default tier must be STANDARD, got {account['tier']}"
    assert account["page_allowance"] == 25, (
        f"default page_allowance must be 25, got {account['page_allowance']}"
    )
    assert account["credit_balance"] == 1000, (
        f"default credit_balance must be 1000, got {account['credit_balance']}"
    )
    assert account["status"] == "ACTIVE", f"a new account must be ACTIVE, got {account['status']}"