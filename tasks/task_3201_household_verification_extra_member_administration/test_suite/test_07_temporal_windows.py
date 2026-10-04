"""Temporal semantics: travel-pass half-open overlap, reissue cooldown,
enforcement grace, computed ends_at."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    create_account,
    create_account_with_device,
    create_policy_payload,
    get_account,
    get_success_data,
    instants_equal,
    issue_challenge,
    set_clock,
    validate_error,
)


def test_travel_pass_half_open_adjacency(api):
    """PRD §3.5: "the new half-open window — inclusive at `starts_at`, exclusive
    at `ends_at` — must not intersect any other `ACTIVE` pass of the same device,
    and a violation is rejected with `ERR_TRAVEL_PASS_OVERLAP` (HTTP 409). Because
    the windows are half-open, back-to-back passes whose start equals the prior
    pass's end are allowed."

    Design: Difficulty/resource_temporal_overlap/travel_pass_half_open_adjacency
    """
    account, household, device, owner_h = create_account_with_device(
        email="to1@x.com",
        device_network="fp-away-1",
        device_geo="geo-away-1",
        device_type="MOBILE",
        trust=False,
    )
    pass1 = get_success_data(
        api.grant_travel_pass(
            device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-09-01T00:00:00Z"}, owner_h
        )
    )

    overlap = api.grant_travel_pass(
        device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-09-14T23:59:00Z"}, owner_h
    )
    validate_error(overlap, ApiErrorId.ERR_TRAVEL_PASS_OVERLAP)

    pass2 = get_success_data(
        api.grant_travel_pass(
            device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-09-15T00:00:00Z"}, owner_h
        )
    )
    assert instants_equal(pass1["ends_at"], "2026-09-15T00:00:00Z")
    assert pass2["status"] == "ACTIVE"
    assert instants_equal(pass2["starts_at"], "2026-09-15T00:00:00Z")


def test_travel_pass_containment_rejected(api):
    """PRD §3.5: "the new half-open window — inclusive at `starts_at`, exclusive
    at `ends_at` — must not intersect any other `ACTIVE` pass of the same device,
    and a violation is rejected with `ERR_TRAVEL_PASS_OVERLAP` (HTTP 409)." A pass
    fully contained in an earlier ACTIVE pass intersects it.

    Design: Difficulty/resource_temporal_overlap/travel_pass_half_open_adjacency
    """
    account, household, device, owner_h = create_account_with_device(
        email="to1b@x.com",
        device_network="fp-away-1",
        device_geo="geo-away-1",
        device_type="MOBILE",
        trust=False,
    )
    get_success_data(
        api.grant_travel_pass(
            device["id"], {"grant_type": "TEMPORARY_30D", "starts_at": "2026-09-01T00:00:00Z"}, owner_h
        )
    )
    contained = api.grant_travel_pass(
        device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-09-05T00:00:00Z"}, owner_h
    )
    validate_error(contained, ApiErrorId.ERR_TRAVEL_PASS_OVERLAP)

    adjacent = get_success_data(
        api.grant_travel_pass(
            device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-10-01T00:00:00Z"}, owner_h
        )
    )
    assert adjacent["status"] == "ACTIVE"


def test_challenge_reissue_cooldown_buffer(api):
    """PRD §3.4: "An `EXPIRED` challenge can be reissued — by the `AccountOwner`
    or `PlatformAdmin` — only once at least 300 seconds have elapsed beyond its
    `expires_at`; an earlier attempt is rejected with `ERR_CHALLENGE_COOLDOWN`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/challenge_reissue_cooldown_buffer
    """
    account, owner_h = create_account(email="to2@x.com")
    challenge = issue_challenge(account["id"])  # EMAIL, expires at 00:15:00

    set_clock("2026-09-01T00:16:00Z")  # past expiry, inside the 300s buffer
    early = api.reissue_challenge(challenge["id"], owner_h)
    validate_error(early, ApiErrorId.ERR_CHALLENGE_COOLDOWN)

    set_clock("2026-09-01T00:20:00Z")  # 300s after expires_at
    reissued = get_success_data(api.reissue_challenge(challenge["id"], owner_h))
    assert reissued["status"] == "PENDING"
    assert reissued["attempts_used"] == 0


def test_challenge_reissue_requires_expired_state(api):
    """PRD §3.4: "An `EXPIRED` challenge can be reissued — by the `AccountOwner`
    or `PlatformAdmin` — only once at least 300 seconds have elapsed beyond its
    `expires_at`; an earlier attempt is rejected with `ERR_CHALLENGE_COOLDOWN`
    (HTTP 409)." A still-PENDING unexpired challenge cannot be reissued.

    Design: Difficulty/resource_temporal_overlap/challenge_reissue_cooldown_buffer
    """
    account, owner_h = create_account(email="to2b@x.com")
    challenge = issue_challenge(account["id"])  # PENDING, unexpired

    resp = api.reissue_challenge(challenge["id"], owner_h)
    assert resp.status_code >= 400, "a PENDING unexpired challenge cannot be reissued"

    after = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
    assert after["status"] == "PENDING"
    assert after["code"] == challenge["code"], "the original code survives a refused reissue"


def test_travel_pass_ends_at_computed(api):
    """PRD §3.5: "the pass's `ends_at` is derived as exactly 14 or 30 days after
    `starts_at` respectively, and the pass begins `ACTIVE`."

    Design: Corner/calculations/travel_pass_ends_at_computed
    """
    account, household, device, owner_h = create_account_with_device(
        email="corner-ends@x.com",
        device_network="fp-away-1",
        device_geo="geo-away-1",
        device_type="MOBILE",
        trust=False,
    )
    pass_ = get_success_data(
        api.grant_travel_pass(
            device["id"], {"grant_type": "TEMPORARY_30D", "starts_at": "2026-09-01T00:00:00Z"}, owner_h
        )
    )
    assert instants_equal(pass_["ends_at"], "2026-10-01T00:00:00Z")
    assert pass_["status"] == "ACTIVE"


def test_periodic_challenge_blocked_during_grace(api):
    """PRD §3.4: "A challenge with `challenge_reason` `PERIODIC` may only be
    issued when the account's region has an `ACTIVE` `EnforcementPolicy` with
    `enforcement_enabled` true and the current logical time is at or past the
    policy's `effective_from` plus its `grace_days`; otherwise issuance is
    rejected with `ERR_ENFORCEMENT_GRACE_ACTIVE` (HTTP 409)."

    Design: Corner/errors/periodic_challenge_blocked_during_grace
    """
    policy = get_success_data(
        api.create_policy(
            create_policy_payload(
                region_code="NA",
                enforcement_enabled=True,
                grace_days=7,
                messaging_variant="SOFT",
                effective_from="2026-09-10T00:00:00Z",
            ),
            admin_headers(),
        )
    )
    get_success_data(api.activate_policy(policy["id"], admin_headers()))

    account, owner_h = create_account(email="corner-grace@x.com")
    set_clock("2026-09-15T00:00:00Z")  # inside the grace window
    resp = api.issue_challenge(
        account["id"], {"channel": "EMAIL", "challenge_reason": "PERIODIC"}, admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_ENFORCEMENT_GRACE_ACTIVE)

    set_clock("2026-09-17T00:00:00Z")  # grace elapsed (effective + 7 days)
    challenge = get_success_data(
        api.issue_challenge(
            account["id"], {"channel": "EMAIL", "challenge_reason": "PERIODIC"}, admin_headers()
        )
    )
    assert challenge["status"] == "PENDING"
    assert get_account(account["id"])["verification_posture"] == "CHALLENGE_PENDING"
