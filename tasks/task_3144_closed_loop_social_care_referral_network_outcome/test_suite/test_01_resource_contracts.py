"""Resource contracts: creation defaults, system-managed fields, listing
filtering with pagination, and not-found handling (queue B corner coverage).
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NETWORK_DEFAULTS,
    assert_care_network, assert_organization, assert_client, assert_consent,
    set_clock, create_network, create_org, create_client, create_consent,
    setup_routed_referral, add_referral,
    make_case_worker_headers, make_org_admin_headers,
)


def test_network_creation_applies_documented_defaults():
    """PRD §2.9: "A `CareNetwork` is created by a `NetworkCoordinator` with a
    `name`, a `coordinator_org_name` naming the backbone coordinating
    organization, and four tunable policy knobs, each with a default applied
    when omitted: `max_reassignment_count` (default 3) caps how many times a
    referral may be re-routed after declines or withdrawn accepts before it
    must be cancelled; `auto_accept_window_hours` (default 72) is the number of
    hours a routed referral may sit unanswered before a coordinator may
    escalate it; `unresolved_aging_days` (default 30) is the age threshold
    beyond which a non-terminal referral counts as aging in funder reports; and
    `referral_expiry_days` (default 60) is the number of days a referral may
    sit routed with no accept before the aging sweep expires it."
    PRD §2.9: "All computed fields on the network initialize to 0 at creation."

    Design: Corner/entities/network_creation_applies_documented_defaults
    """
    set_clock()
    network = validate_success(api_client.create_network(
        {"name": "Net", "coordinator_org_name": "Coord"}, COORDINATOR),
        expected_status=201)
    assert_care_network(network)
    assert network["max_reassignment_count"] == NETWORK_DEFAULTS["max_reassignment_count"] == 3
    assert network["auto_accept_window_hours"] == 72
    assert network["unresolved_aging_days"] == 30
    assert network["referral_expiry_days"] == 60
    assert network["network_escrow_cents"] == 0
    assert network["network_escrow_reserved_cents"] == 0


def test_organization_created_pending_review_with_zero_balance():
    """PRD §3.2: "Registration leaves the organization in `PENDING_REVIEW` with
    a zeroed `payable_balance_cents`."
    PRD §2.7: "Balances that accrue, such as an organization's
    `payable_balance_cents`, never go negative".

    Design: Corner/entities/organization_created_pending_review_with_zero_balance
    """
    set_clock()
    org = create_org("Receiver R", "CBO", "EIN-R", activate=False)
    assert_organization(org)
    assert org["status"] == "PENDING_REVIEW"
    assert org["payable_balance_cents"] == 0


def test_client_optional_fields_default():
    """PRD §3.5: "Optional demographics — `annual_income_cents` (with `null`
    meaning undisclosed), `race` (one of `AMERICAN_INDIAN`, `ASIAN`, `BLACK`,
    `PACIFIC_ISLANDER`, `WHITE`, `MULTIRACIAL`, `UNDISCLOSED`), `ethnicity`
    (`HISPANIC`, `NON_HISPANIC`, `UNDISCLOSED`), preferred `language` (default
    `en`), and `veteran_status` (default false) — feed funder reporting. The
    client's `open_referral_count` starts at 0 and tracks how many of the
    client's referrals are not yet in a terminal state."

    Design: Corner/entities/client_optional_fields_default
    """
    set_clock()
    sender = create_org("Sender S", "CLINIC", "EIN-S", activate=False)
    client = validate_success(api_client.create_client(
        {"full_name": "K", "date_of_birth": "1990-01-01", "zip_code": "94110",
         "gender": "MALE"},
        make_case_worker_headers(sender["id"])), expected_status=201)
    assert_client(client)
    assert client["annual_income_cents"] is None
    assert client["race"] == "UNDISCLOSED"
    assert client["ethnicity"] == "UNDISCLOSED"
    assert client["language"] == "en"
    assert client["veteran_status"] is False
    assert client["open_referral_count"] == 0


def test_referral_get_nonexistent_returns_404():
    """PRD §2.6: "Endpoints whose paths nest one resource under another — for
    example an offering under an organization, or a consent under a client —
    validate path identifiers strictly left to right. The first identifier that
    does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP
    404), and no later segment is examined."

    Design: Corner/entities/referral_get_nonexistent_returns_404
    """
    set_clock()
    validate_error(api_client.get_referral(NON_EXISTENT_UUID, COORDINATOR),
                   ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_consent_revoked_at_null_until_revoked():
    """PRD §3.4: "A consent is born `ACTIVE`. Revocation — by the client's
    `CaseWorker`, by a coordinator, or by the agreement cascade — stamps
    `revoked_at` and propagates in three hops."
    PRD §2.4: "Every aging, escalation, expiry, and reporting rule in this
    document is evaluated against this clock."

    Design: Corner/entities/consent_revoked_at_null_until_revoked
    """
    set_clock()
    sender = create_org("Sender S", "CLINIC", "EIN-S", activate=False)
    receiver = create_org("Receiver R", "CBO", "EIN-R", activate=False)
    client = create_client(sender["id"])
    consent = validate_success(api_client.create_consent(
        client["id"],
        {"sender_org_id": sender["id"], "receiver_org_id": receiver["id"],
         "scope": "MINIMUM_NECESSARY"},
        make_case_worker_headers(sender["id"])), expected_status=201)
    assert_consent(consent)
    assert consent["status"] == "ACTIVE"
    assert consent["revoked_at"] is None

    set_clock("2026-09-10T12:00:00Z")
    revoked = validate_success(api_client.revoke_consent(
        consent["id"], make_case_worker_headers(sender["id"])))
    assert revoked["status"] == "REVOKED"
    assert isinstance(revoked["revoked_at"], str) and revoked["revoked_at"]
    assert revoked["revoked_at"].startswith("2026-09-10T12:00:00"), (
        "revoked_at is stamped with the server clock at revocation")


def test_referrals_list_filters_and_pagination():
    """PRD §3.5: "The referral list endpoint supports filters on `client_id`,
    `sender_org_id`, `receiver_org_id`, `service_offering_id`, `consent_id`,
    `status`, and an `aging_only` flag, alongside the standard pagination
    parameters".
    PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/referrals_list_filters_and_pagination
    """
    ctx, rf1 = setup_routed_referral(capacity_total=10)
    # Second referral: also ROUTED.
    rf2, _, _ = add_referral(ctx)
    rf2 = get_success_data(api_client.route_referral(
        rf2["id"], make_case_worker_headers(ctx["sender_id"])))
    # Third referral: stays DRAFT.
    rf3, _, _ = add_referral(ctx)

    page1, meta1 = validate_paginated(api_client.list_referrals(
        COORDINATOR, params={"status": "ROUTED", "limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert page1[0]["status"] == "ROUTED"
    assert meta1["total_count"] == 2, "the DRAFT referral is excluded by the filter"
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api_client.list_referrals(
        COORDINATOR, params={"status": "ROUTED", "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert page2[0]["status"] == "ROUTED"
    assert meta2["has_more"] is False

    routed_ids = {page1[0]["id"], page2[0]["id"]}
    assert routed_ids == {rf1["id"], rf2["id"]}
    assert rf3["id"] not in routed_ids
