"""Authentication, ownership scoping and the role matrix."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_household_user,
    api_client,
    build_user_headers,
    create_membership,
    get_membership,
    is_valid_uuid,
    mint_device,
    opaque_headers,
    owner_headers,
    set_clock,
    setup_active_membership,
    setup_refurb_source,
    validate_paginated,
    validate_success,
    verify_household_user,
)

TECH = TEST_USERS["service_technician_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# =========================================================================
# Queue B — Corner instances
# =========================================================================

def test_a_request_without_auth_headers_is_unauthenticated():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value
    that is not one of the declared roles, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated_before_any_existence_check
    """
    set_clock("2026-09-01T00:00:00Z")

    no_headers = api_client.get_membership(NON_EXISTENT_UUID, {})
    assert no_headers.status_code == 401, no_headers.text
    assert no_headers.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"
    assert no_headers.json()["response_type"] == "error"

    undeclared_role = api_client.get_membership(
        NON_EXISTENT_UUID, build_user_headers("someone", "NoSuchRole"))
    assert undeclared_role.status_code == 401, undeclared_role.text
    assert undeclared_role.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"


def test_missing_a_required_household_user_field_returns_invalid_request():
    """PRD §2.4: "People are attached to a membership as household users. Each
    carries a `display_name` shown on the leaderboard, a unique `email`, and a `role`
    drawn from `OWNER` and `MEMBER`, defaulting to `MEMBER`."
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

    Design: Corner/validations/missing_required_field_returns_invalid_request_before_the_existence_clause
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]

    res = api_client.create_household_user(m_id, {"email": "ghost@x.com"},
                                           owner_headers(m_id))
    assert res.status_code == 400, res.text
    assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    rows, meta = validate_paginated(
        api_client.list_membership_household_users(m_id, owner_headers(m_id)))
    assert meta["total_count"] == 0
    assert get_membership(m_id)["active_user_count"] == 0


def test_an_owner_cannot_pause_a_membership_it_does_not_own():
    """PRD §2.1: "Ownership checks on any resource that references a `Membership`
    compare that resource's foreign-key field to `X-User-ID`, so a household can only
    read and mutate the memberships, household users, devices, hardware orders,
    financing plans and enrollments that hang beneath its own membership row."
    PRD §2.1: "A well-formed request whose role is simply not permitted for the
    operation it attempts is refused with `ERR_UNAUTHORIZED` (HTTP 403) instead."

    Design: Corner/validations/owner_cannot_pause_a_foreign_membership
    """
    victim = setup_active_membership(clock_utc="2026-09-01T00:00:00Z",
                                     household_name="Rhone Household",
                                     serial="TREAD-3002", crew="CREW-B")
    attacker = setup_active_membership(clock_utc="2026-09-01T00:00:00Z",
                                       household_name="Fernwood Household")
    victim_id = victim["membership_id"]

    res = api_client.pause_membership(victim_id, {
        "pause_start_at": "2026-09-01T00:00:00Z",
        "pause_end_at": "2026-10-01T00:00:00Z",
        "expected_membership_version": get_membership(victim_id)["version"],
    }, owner_headers(attacker["membership_id"]))

    assert res.status_code == 403, res.text
    assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"
    assert get_membership(victim_id)["status"] == "ACTIVE"

    accepted = validate_success(api_client.pause_membership(victim_id, {
        "pause_start_at": "2026-09-01T00:00:00Z",
        "pause_end_at": "2026-10-01T00:00:00Z",
        "expected_membership_version": get_membership(victim_id)["version"],
    }, owner_headers(victim_id)), 200)
    assert accepted["status"] == "PAUSED"


def test_a_membership_owner_cannot_restock_parts_inventory():
    """PRD §2.1: "A well-formed request whose role is simply not permitted for the
    operation it attempts is refused with `ERR_UNAUTHORIZED` (HTTP 403) instead."
    PRD §4: "POST | `/fitness/parts-inventory/{partId}/restock` | Receive part units
    into stock | PlatformAdmin".

    Design: Corner/rbac/membership_owner_cannot_restock_parts_inventory
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]
    part = validate_success(api_client.create_part({
        "part_code": "TREAD-BELT-42",
        "compatible_sku": "TREAD",
        "safety_stock_qty": 2,
        "part_lot_key": "LOT-2026-09",
    }, ADMIN), 201)

    res = api_client.restock_part(part["id"], {"quantity": 10}, owner_headers(m_id))
    assert res.status_code == 403, res.text
    assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    after = validate_success(api_client.get_part(part["id"], TECH), 200)
    assert after["stock_received_qty"] == 0
    assert after["on_hand_qty"] == 0

    allowed = validate_success(api_client.restock_part(part["id"], {"quantity": 10}, ADMIN), 200)
    assert allowed["on_hand_qty"] == 10


def test_a_service_technician_cannot_pause_a_membership():
    """PRD §2.1: "A well-formed request whose role is simply not permitted for the
    operation it attempts is refused with `ERR_UNAUTHORIZED` (HTTP 403) instead."
    PRD §4: "POST | `/fitness/memberships/{membershipId}/pause` | Pause an active
    membership and bank a proration credit | MembershipOwner, PlatformAdmin".

    Design: Corner/rbac/technician_cannot_pause_a_membership
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]

    res = api_client.pause_membership(m_id, {
        "pause_start_at": "2026-09-01T00:00:00Z",
        "pause_end_at": "2026-10-01T00:00:00Z",
        "expected_membership_version": get_membership(m_id)["version"],
    }, TECH)

    assert res.status_code == 403, res.text
    assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    after = get_membership(m_id)
    assert after["status"] == "ACTIVE"
    assert after["accrued_pause_credit_cents"] == 0
    device = validate_success(api_client.get_device(base["device_id"], TECH), 200)
    assert device["activation_status"] == "ACTIVE"
    assert device["entitlement_lock"] is False

    allowed = validate_success(api_client.pause_membership(m_id, {
        "pause_start_at": "2026-09-01T00:00:00Z",
        "pause_end_at": "2026-10-01T00:00:00Z",
        "expected_membership_version": get_membership(m_id)["version"],
    }, owner_headers(m_id)), 200)
    assert allowed["status"] == "PAUSED"


def test_an_instructor_cannot_open_a_refurbishment_batch():
    """PRD §2.1: "A well-formed request whose role is simply not permitted for the
    operation it attempts is refused with `ERR_UNAUTHORIZED` (HTTP 403) instead."
    PRD §4: "POST | `/fitness/refurb-batches` | Open a refurbishment batch over a
    returned device | ServiceTechnician, PlatformAdmin".

    Design: Corner/rbac/instructor_cannot_create_a_refurb_batch
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")

    res = api_client.create_refurb_batch({
        "source_device_id": base["device_id"],
        "certification_grade": "A",
        "performance_resale_enabled": True,
    }, INSTRUCTOR)

    assert res.status_code == 403, res.text
    assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    rows, meta = validate_paginated(
        api_client.list_device_refurb_batches(base["device_id"], TECH))
    assert meta["total_count"] == 0

    allowed = validate_success(api_client.create_refurb_batch({
        "source_device_id": base["device_id"],
        "certification_grade": "A",
        "performance_resale_enabled": True,
    }, TECH), 201)
    assert allowed["status"] == "INSPECTING"


def test_anonymous_may_verify_a_token_and_nothing_else():
    """PRD §2.1: "The `Anonymous` role exists solely so that the verification step
    for a newly added household user can be exercised without a session. Everywhere
    else it is refused with `ERR_UNAUTHORIZED`."
    PRD §2.1: "for `Anonymous`, the unauthenticated caller that is permitted only to
    consume a verification token that was already issued by someone else."

    Design: Corner/rbac/anonymous_can_only_consume_a_verification_token
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]
    owner = add_household_user(m_id, display_name="Ada Quillon", email="ada@x.com",
                               role="OWNER", verify=False)

    refused = api_client.get_membership(m_id, TEST_USERS["anonymous_headers"])
    assert refused.status_code in (401, 403), refused.text
    assert refused.json()["data"]["error_id"] in ("ERR_UNAUTHENTICATED", "ERR_UNAUTHORIZED")

    verified = verify_household_user(owner["id"], owner["verification_token"])
    assert verified["status"] == "ACTIVE"
    assert verified["verified"] is True


def test_a_minted_device_starts_unassigned_and_dark():
    """PRD §3.3: "A technician supplies the `hardware_sku` and a globally unique
    `serial`, and the row opens in `UNASSIGNED` with `condition` of `NEW`,
    `entitlement_lock` true, `resale_cycle_count` zero and `total_workouts` zero."
    PRD §2.11: "`id` is a server-minted UUID with no type prefix or other decoration."

    Design: Corner/entities/device_create_ignores_client_supplied_status_and_starts_unassigned
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]

    device = validate_success(api_client.create_device(m_id, {
        "hardware_sku": "BIKE",
        "serial": "BIKE-0001",
    }, TECH), 201)

    assert is_valid_uuid(device["id"])
    assert device["activation_status"] == "UNASSIGNED"
    assert device["condition"] == "NEW"
    assert device["provenance_source"] is None
    assert device["entitlement_lock"] is True
    assert device["content_access_allowed"] is False
    assert device["resale_cycle_count"] == 0
    assert device["total_workouts"] == 0





# ---------------------------------------------------------------------------
# Deliberately not translated: the optimistic-concurrency guards.
#
# The guarded writes are activation, pause, cancellation and reactivation (each
# requiring `expected_membership_version`, rejected with
# ERR_MEMBERSHIP_STALE_VERSION at HTTP 412) and the device link (requiring
# `expected_device_version`, rejected with ERR_DEVICE_STALE_VERSION at HTTP 412).
# The PRD states the version field names and the two rejection identifiers, so the
# guards are named; but the meaning of "the version the caller last observed" is
# left open, since §2.11 also says `version` "begins at its initial value", without
# fixing that value. Two PRD-only readers can therefore disagree on what a correct
# request supplies, and any test hard-coding one reading would fail a faithful
# implementation. Per the concurrency-occ silence pattern these rules are left
# untested rather than asserted weakly or parked behind a skip mark.
# ---------------------------------------------------------------------------
