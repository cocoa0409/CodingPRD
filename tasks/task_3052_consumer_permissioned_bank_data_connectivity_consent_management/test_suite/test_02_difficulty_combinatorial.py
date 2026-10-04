"""Difficulty queue A — combinatorial_formula instances."""

from test_helpers import (
    ApiErrorId,
    create_approved_recipient,
    create_consent_payload,
    get_success_data,
    make_admin_headers,
    make_consumer_headers,
    make_reviewer_headers,
    setup_active_stack,
    drive_consecutive_failures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _approve_and_enroll(api, name, policy, tier):
    admin = make_admin_headers()
    reviewer = make_reviewer_headers()
    recipient = get_success_data(
        api.create_recipient(
            {"name": name, "declared_use_case": "loans", "minimization_policy": policy}, admin
        )
    )
    recipient = get_success_data(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, reviewer)
    )
    get_success_data(api.create_tier_assignment(recipient["id"], {"tier_id": tier["id"]}, admin))
    return recipient


def test_identity_scope_rejected_for_strict_recipient(api):
    """PRD §3.4: "First, minimization: if any requested scope is forbidden by
    the recipient's `minimization_policy`, the capture is rejected with
    `ERR_SCOPE_VIOLATES_MINIMIZATION` — so an `IDENTITY`-only consent is
    refused for a `STRICT` recipient but passes the minimization gate for a
    `STANDARD` recipient."

    Design: Difficulty/combinatorial_formula/combinatorial_scope_coverage_three_input_set_logic
    """
    admin = make_admin_headers()
    tier = get_success_data(
        api.create_tier(
            {
                "tier_name": "BalIdent",
                "scopes_included": ["BALANCE", "IDENTITY"],
                "rate_class": "MEDIUM",
            },
            admin,
        )
    )
    strict = _approve_and_enroll(api, "StrictLoan", "STRICT", tier)

    resp = api.create_consent(
        strict["id"],
        create_consent_payload(
            consumer_ref="cons_c",
            data_scopes=["IDENTITY"],
            expected_recipient_version=strict["version"],
        ),
        make_consumer_headers("cons_c"),
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_VIOLATES_MINIMIZATION)

    consents, meta = validate_paginated(api.list_recipient_consents(strict["id"], admin))
    assert meta["total_count"] == 0, "no consent may be persisted for the rejected capture"


def test_identity_scope_accepted_for_standard_recipient_on_same_tier(api):
    """PRD §3.2: "`STANDARD` additionally permits `IDENTITY` but still forbids
    `INCOME` and `ASSETS`."
    PRD §3.4: "A successfully captured consent starts `ACTIVE`, and the
    platform immediately materializes one `DataScopeGrant` row per granted
    scope, each carrying the `consent_id` and the `scope` value."

    Design: Difficulty/combinatorial_formula/combinatorial_scope_coverage_three_input_set_logic
    """
    admin = make_admin_headers()
    tier = get_success_data(
        api.create_tier(
            {
                "tier_name": "BalIdent",
                "scopes_included": ["BALANCE", "IDENTITY"],
                "rate_class": "MEDIUM",
            },
            admin,
        )
    )
    standard = _approve_and_enroll(api, "StdLoan", "STANDARD", tier)

    consent = validate_success(
        api.create_consent(
            standard["id"],
            create_consent_payload(
                consumer_ref="cons_c",
                data_scopes=["IDENTITY"],
                expected_recipient_version=standard["version"],
            ),
            make_consumer_headers("cons_c"),
        ),
        expected_status=201,
    )
    assert consent["status"] == "ACTIVE"

    grants, meta = validate_paginated(api.list_consent_grants(consent["id"], admin))
    assert meta["total_count"] == 1, f"expected exactly 1 grant, got {meta['total_count']}"
    assert grants[0]["scope"] == "IDENTITY"


def test_institution_degraded_at_three_breakage_events(api):
    """PRD §3.1: "If the count is 5 or more, the institution is `BROKEN`; if
    it is 3 or 4, the institution is `DEGRADED`; below 3 it is `ACTIVE`."
    PRD §3.7: "An `INSTITUTION_DOWN` failure that brings `consecutive_failures`
    to 2 moves the connection to `BROKEN` and appends its breakage event."

    Design: Difficulty/combinatorial_formula/combinatorial_health_threshold_with_aging_and_recovery_reset
    """
    stack = setup_active_stack(
        api,
        institution_name="Prairie Trust",
        recipient_name="SavePath",
        consumer_ref="cons_d",
        reauth_cooldown_seconds=0,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]
    admin = stack["admin"]

    drive_consecutive_failures(api, conn_id, "cons_d", 2)
    broken = validate_success(api.get_connection(conn_id, consumer))
    assert broken["status"] == "BROKEN", (
        "two consecutive INSTITUTION_DOWN failures must break the connection"
    )
    reauthed = validate_success(api.reauth_connection(conn_id, {"valid": True}, consumer))
    assert reauthed["status"] == "ACTIVE"
    assert reauthed["consecutive_failures"] == 0
    drive_consecutive_failures(api, conn_id, "cons_d", 1)

    institution = validate_success(api.get_institution(stack["institution"]["id"], admin))
    assert institution["status"] == "DEGRADED", (
        f"3 breakage events in the window must yield DEGRADED, got {institution['status']}"
    )
    # The two-failure streak broke the connection mid-way; the intervening
    # reauth zeroed consecutive_failures, so the third failure is a fresh
    # streak of one and the connection stays ACTIVE.
    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "ACTIVE", (
        "consecutive_failures reset on reauth: a single new failure leaves the connection ACTIVE"
    )


def test_institution_returns_to_active_when_events_age_out(api):
    """PRD §3.1: "This recomputation runs after every refresh failure, after
    operator recovery, and lazily on any institution read — so old events
    aging out of the window can return a `DEGRADED` institution to `ACTIVE`
    without any explicit action."

    Design: Difficulty/combinatorial_formula/combinatorial_health_threshold_with_aging_and_recovery_reset
    """
    stack = setup_active_stack(
        api,
        institution_name="Prairie Trust",
        recipient_name="SavePath",
        consumer_ref="cons_d",
        reauth_cooldown_seconds=0,
    )
    inst_id = stack["institution"]["id"]
    admin = stack["admin"]

    drive_consecutive_failures(api, stack["connection"]["id"], "cons_d", 3)
    assert validate_success(api.get_institution(inst_id, admin))["status"] == "DEGRADED"

    # Advance the clock 86401 seconds so every event falls outside the window.
    validate_success(
        api.set_clock({"to_iso8601": "2026-09-02T00:00:01Z"}, admin)
    )
    aged = validate_success(api.get_institution(inst_id, admin))
    assert aged["status"] == "ACTIVE", (
        f"events aged out of the trailing window must return the institution to ACTIVE, "
        f"got {aged['status']}"
    )
