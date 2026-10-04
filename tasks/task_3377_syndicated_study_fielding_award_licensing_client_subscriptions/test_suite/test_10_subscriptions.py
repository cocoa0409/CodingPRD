"""Subscriptions: closed-interval windows, adjacency overlap, and entity-backed
ownership on creation (PRD §2.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_study,
    create_subscription,
    create_subscription_payload,
    make_client_user_headers,
    register_client,
    set_clock,
    validate_error,
    validate_success,
    api_client,
)


def _client_with_three_subs():
    """Bare study + ClientA; S1/S2 adjacent (touching), S3 starting the day after S1 ends."""
    study = create_study(min_sample_per_brand=1)
    client = register_client()
    cl = client["id"]
    s1 = create_subscription(cl, study["id"], tier="DIAGNOSTIC",
                             starts_at="2026-10-20T00:00:00Z", ends_at="2027-10-19T00:00:00Z")
    s2 = create_subscription(cl, study["id"], tier="DIAGNOSTIC",
                             starts_at="2027-10-19T00:00:00Z", ends_at="2028-10-18T00:00:00Z")
    s3 = create_subscription(cl, study["id"], tier="BENCHMARK",
                             starts_at="2027-10-20T00:00:00Z", ends_at="2028-10-19T00:00:00Z")
    return study, client, s1, s2, s3


def test_activation_at_window_start_then_adjacent_successor_conflicts(api):
    """PRD §3.8: "The logical clock must fall within the closed window from
    `starts_at` through `ends_at` inclusive, failing with
    `ERR_SUBSCRIPTION_WINDOW_INVALID` outside it. And no other `ACTIVE`
    subscription may exist for the same (`client_id`, `study_id`) pair whose
    closed window intersects this one; because both intervals are closed,
    adjacency counts as conflict — another active subscription ending exactly on
    this one's `starts_at` still overlaps and fails the activation with
    `ERR_SUBSCRIPTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_closed_interval_touching_conflicts
    """
    _, client, s1, s2, _ = _client_with_three_subs()
    cl = client["id"]

    set_clock("2026-10-20T00:00:00Z")  # exactly S1.starts_at: window is inclusive
    activated = validate_success(
        api.subscription_state(s1["id"], {"to_status": "ACTIVE"}, make_client_user_headers(cl))
    )
    assert activated["status"] == "ACTIVE"

    set_clock("2027-10-19T00:00:00Z")  # S2.starts_at == S1.ends_at
    resp = api.subscription_state(s2["id"], {"to_status": "ACTIVE"}, make_client_user_headers(cl))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP)
    after = validate_success(api.get_subscription(s2["id"], make_client_user_headers(cl)))
    assert after["status"] == "TRIAL", "a failed activation changes nothing"


def test_successor_starting_day_after_predecessor_end_activates(api):
    """PRD §3.8: "because both intervals are closed, adjacency counts as conflict
    — another active subscription ending exactly on this one's `starts_at` still
    overlaps and fails the activation with `ERR_SUBSCRIPTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_closed_interval_touching_conflicts
    """
    _, client, s1, s2, s3 = _client_with_three_subs()
    cl = client["id"]

    set_clock("2026-10-20T00:00:00Z")
    validate_success(
        api.subscription_state(s1["id"], {"to_status": "ACTIVE"}, make_client_user_headers(cl))
    )
    set_clock("2027-10-19T00:00:00Z")
    resp = api.subscription_state(s2["id"], {"to_status": "ACTIVE"}, make_client_user_headers(cl))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP)

    set_clock("2027-10-20T00:00:00Z")  # one day past S1.ends_at: no intersection
    activated = validate_success(
        api.subscription_state(s3["id"], {"to_status": "ACTIVE"}, make_client_user_headers(cl))
    )
    assert activated["status"] == "ACTIVE", "one day of separation suffices under closed semantics"
    after_s2 = validate_success(api.get_subscription(s2["id"], make_client_user_headers(cl)))
    assert after_s2["status"] == "TRIAL"


def test_subscription_activate_before_window_returns_409(api):
    """PRD §3.8: "The logical clock must fall within the closed window from
    `starts_at` through `ends_at` inclusive, failing with
    `ERR_SUBSCRIPTION_WINDOW_INVALID` outside it."

    Design: Corner/errors/subscription_activate_before_window_returns_409
    """
    study = create_study(min_sample_per_brand=1)
    client = register_client()
    sub = create_subscription(client["id"], study["id"], tier="DIAGNOSTIC",
                              starts_at="2026-12-01T00:00:00Z", ends_at="2027-11-30T00:00:00Z")

    set_clock("2026-10-20T00:00:00Z")  # two months before the window opens
    resp = api.subscription_state(
        sub["id"], {"to_status": "ACTIVE"}, make_client_user_headers(client["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_WINDOW_INVALID)
    after = validate_success(api.get_subscription(sub["id"], make_client_user_headers(client["id"])))
    assert after["status"] == "TRIAL"


def test_subscription_ownership_forbidden(api):
    """PRD §2.1: "a `ClientUser` may create a subscription or a license quote only
    for its own client record, may list and read only subscriptions and licenses
    whose `client_id` equals `X-User-ID`, and reads insights as its own client
    identity."
    PRD §2.1: "A request whose role is declared but not authorized for the target
    endpoint — or that fails an ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/subscription_ownership_forbidden
    """
    study = create_study(min_sample_per_brand=1)
    client_a = register_client(name="ClientA")
    client_b = register_client(name="ClientB", client_type="AGENCY")

    resp = api_client.create_subscription(
        create_subscription_payload(client_b["id"], study["id"], tier="DIAGNOSTIC"),
        make_client_user_headers(client_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    subs_b = validate_success(
        api.list_subscriptions(make_client_user_headers(client_b["id"]),
                               params={"client_id": client_b["id"]})
    )
    assert subs_b == [], "no subscription may be created for another client"
