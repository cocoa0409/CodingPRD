"""Devices: pairing limits, count conservation, suspension gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_device,
    assert_family,
    create_child,
    create_family,
    make_parent_headers,
    pair_device,
    validate_error,
    validate_success,
)

ADMIN = None  # populated per-test from TEST_USERS via fixtures helper


def _admin(api):
    from test_helpers import TEST_USERS

    return TEST_USERS["platform_admin_headers"]


def test_device_limit_boundary_at_exactly_limit(api):
    """PRD §3.3: "The subscription tier caps how many devices a family may have
    paired simultaneously: `BASIC` allows 2, `STANDARD` allows 5, and `PREMIUM`
    allows 10, and the family's computed `device_limit` always reflects the
    current tier."
    PRD §3.3: "Pairing is permitted only while the family's `device_count` is
    strictly below its `device_limit`; a pair that would meet or exceed the
    limit is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/device_limit_boundary_at_exactly_limit
    """
    fam, parent = create_family(subscription_tier="BASIC")
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    # count 0 -> 1 (below limit 2): allowed.
    pair_device(child["id"], parent["id"], platform="ANDROID", nickname="B2-1")
    # count 1 -> 2 (below limit 2): allowed.
    resp = api.pair_device(
        child["id"], {"platform": "IOS", "nickname": "B2-2"}, headers
    )
    validate_success(resp, expected_status=201)

    fam_now = validate_success(api.get_family(fam["id"], _admin(api)))
    assert fam_now["device_count"] == 2

    # count 2 >= limit 2: rejected.
    resp = api.pair_device(
        child["id"], {"platform": "CHROMEBOOK", "nickname": "B2-3"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_LIMIT_EXCEEDED)

    fam_now = validate_success(api.get_family(fam["id"], _admin(api)))
    assert fam_now["device_count"] == 2, "rejected pair must not change device_count"


def test_device_limit_premium_allows_ten(api):
    """PRD §3.3: "`BASIC` allows 2, `STANDARD` allows 5, and `PREMIUM` allows
    10, and the family's computed `device_limit` always reflects the current
    tier."
    PRD §3.3: "Pairing is permitted only while the family's `device_count` is
    strictly below its `device_limit`; a pair that would meet or exceed the
    limit is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/device_limit_boundary_at_exactly_limit
    """
    fam, parent = create_family(subscription_tier="PREMIUM")
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    for i in range(10):
        resp = api.pair_device(
            child["id"], {"platform": "ANDROID", "nickname": f"P-{i}"}, headers
        )
        validate_success(resp, expected_status=201)

    resp = api.pair_device(
        child["id"], {"platform": "ANDROID", "nickname": "P-11"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_LIMIT_EXCEEDED)


def test_device_pair_unpair_count_conservation(api):
    """PRD §2.8: "The `FamilyAccount.device_count` equals the number of devices
    across all children of the family whose `pairing_status` is `PAIRED`;
    pairing a device increases it by one and unpairing decreases it by one, a
    compensating pair that keeps the counter equal to the true count at every
    moment."
    PRD §3.3: "Unpairing flips the device's `pairing_status` from `PAIRED` to
    `UNPAIRED`, recomputes the family's `device_count` down by one, and
    increments the device's `version`."

    Design: Difficulty/compensating_invariant/device_pair_unpair_count_conservation
    """
    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    dev1 = pair_device(child["id"], parent["id"], platform="ANDROID", nickname="N-1")
    pair_device(child["id"], parent["id"], platform="IOS", nickname="N-2")
    fam_now = validate_success(api.get_family(fam["id"], _admin(api)))
    assert fam_now["device_count"] == 2

    unpaired = validate_success(api.unpair_device(dev1["id"], headers))
    assert unpaired["pairing_status"] == "UNPAIRED"
    fam_now = validate_success(api.get_family(fam["id"], _admin(api)))
    assert fam_now["device_count"] == 1

    pair_device(child["id"], parent["id"], platform="CHROMEBOOK", nickname="N-3")
    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert_family(fam_now)
    assert fam_now["device_count"] == 2


def test_derived_device_count_reconciles_immediately(api):
    """PRD §2.8: "The `FamilyAccount.device_count` equals the number of devices
    across all children of the family whose `pairing_status` is `PAIRED`;
    pairing a device increases it by one and unpairing decreases it by one, a
    compensating pair that keeps the counter equal to the true count at every
    moment."

    Design: Corner/cross_cutting/derived_device_count_reconciles_immediately
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    pair_device(child["id"], parent["id"], platform="ANDROID", nickname="DR-1")
    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["device_count"] == 1


def test_pairing_requires_family_active(api):
    """PRD §3.3: "Pairing also requires the family to be `ACTIVE` — a
    `SUSPENDED` family cannot pair, consent, or ingest, and any of these
    attempted against a suspended family is rejected with
    `ERR_FAMILY_SUSPENDED`."
    PRD §3.15: "A `PlatformAdmin` may suspend or reactivate a family through the
    family state operation, moving `account_status` between `ACTIVE` and
    `SUSPENDED` in either direction; each transition increments the family's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/pairing_requires_family_active
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    resp = api.set_family_state(fam["id"], {"to_status": "SUSPENDED"}, _admin(api))
    validate_success(resp)

    resp = api.pair_device(
        child["id"], {"platform": "ANDROID", "nickname": "X-1"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_FAMILY_SUSPENDED)

    resp = api.set_family_state(fam["id"], {"to_status": "ACTIVE"}, _admin(api))
    validate_success(resp)

    resp = api.pair_device(
        child["id"], {"platform": "ANDROID", "nickname": "X-1"}, headers
    )
    validate_success(resp, expected_status=201)
    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["device_count"] == 1


def test_suspended_family_blocks_consent(api):
    """PRD §3.15: "Suspension is a gate, not a cascade: while `account_status`
    is `SUSPENDED`, pairing devices, consenting connections, and ingesting
    content are all rejected with `ERR_FAMILY_SUSPENDED`, but existing records,
    alerts, and cases remain readable and otherwise unaffected."

    Design: Difficulty/cross_entity_state_dependency/pairing_requires_family_active
    """
    from test_helpers import create_connection

    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])
    conn = create_connection(child["id"], parent["id"])

    resp = api.set_family_state(fam["id"], {"to_status": "SUSPENDED"}, _admin(api))
    validate_success(resp)

    resp = api.set_connection_state(conn["id"], {"to_status": "ACTIVE"}, headers)
    validate_error(resp, ApiErrorId.ERR_FAMILY_SUSPENDED)


def test_suspended_family_beats_device_limit_rejected(api):
    """PRD §3.15: "Suspension is a gate, not a cascade: while `account_status`
    is `SUSPENDED`, pairing devices, consenting connections, and ingesting
    content are all rejected with `ERR_FAMILY_SUSPENDED`, but existing records,
    alerts, and cases remain readable and otherwise unaffected."
    PRD §3.3: "Pairing is permitted only while the family's `device_count` is
    strictly below its `device_limit`; a pair that would meet or exceed the
    limit is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_family_beats_device_limit_rejected
    """
    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])
    children = []
    for i in range(5):
        child = create_child(fam["id"], parent["id"], display_name=f"Kid H{i + 1}")
        children.append(child)
        pair_device(child["id"], parent["id"], platform="ANDROID", nickname=f"H{i + 1}")

    fam_now = validate_success(api.get_family(fam["id"], _admin(api)))
    assert fam_now["device_count"] == 5

    resp = api.set_family_state(fam["id"], {"to_status": "SUSPENDED"}, _admin(api))
    validate_success(resp)

    resp = api.pair_device(
        children[4]["id"], {"platform": "IOS", "nickname": "H6-overflow"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_FAMILY_SUSPENDED)


def test_suspended_family_pairing_fails_even_below_limit(api):
    """PRD §3.15: "Suspension is a gate, not a cascade: while `account_status`
    is `SUSPENDED`, pairing devices, consenting connections, and ingesting
    content are all rejected with `ERR_FAMILY_SUSPENDED`, but existing records,
    alerts, and cases remain readable and otherwise unaffected."

    Design: Difficulty/priority_pair_validation_conflict/suspended_family_beats_device_limit_rejected
    """
    fam, parent = create_family(subscription_tier="PREMIUM")
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    resp = api.set_family_state(fam["id"], {"to_status": "SUSPENDED"}, _admin(api))
    validate_success(resp)

    resp = api.pair_device(
        child["id"], {"platform": "ANDROID", "nickname": "below-limit"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_FAMILY_SUSPENDED)


def test_downgrade_over_device_limit_rejected(api):
    """PRD §3.3: "The same code guards downgrades: a tier change that would
    leave the family's `device_count` above the new tier's limit is rejected
    with `ERR_DEVICE_LIMIT_EXCEEDED`."

    Design: Corner/validations/downgrade_over_device_limit_rejected
    """
    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])
    pair_device(child["id"], parent["id"], platform="ANDROID", nickname="DG-1")
    pair_device(child["id"], parent["id"], platform="IOS", nickname="DG-2")
    pair_device(child["id"], parent["id"], platform="CHROMEBOOK", nickname="DG-3")

    resp = api.change_subscription(
        fam["id"],
        {"new_tier": "BASIC", "expected_family_version": fam["version"]},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_LIMIT_EXCEEDED)

    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["subscription_tier"] == "STANDARD"


def test_device_count_conservation_across_children(api):
    """PRD §2.8: "The `FamilyAccount.device_count` equals the number of devices
    across all children of the family whose `pairing_status` is `PAIRED`;
    pairing a device increases it by one and unpairing decreases it by one, a
    compensating pair that keeps the counter equal to the true count at every
    moment."

    Design: Difficulty/compensating_invariant/device_pair_unpair_count_conservation
    """
    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])
    child_a = create_child(fam["id"], parent["id"], display_name="Kid A")
    child_b = create_child(fam["id"], parent["id"], display_name="Kid B")

    pair_device(child_a["id"], parent["id"], platform="ANDROID", nickname="A-1")
    dev_b1 = pair_device(child_b["id"], parent["id"], platform="IOS", nickname="B-1")

    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["device_count"] == 2, "count spans all children of the family"

    validate_success(api.unpair_device(dev_b1["id"], headers))
    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["device_count"] == 1
