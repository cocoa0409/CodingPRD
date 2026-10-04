"""Territory grants, distributor lifecycle, OCC, and cascades (PRD §2.5/§2.6/§3.1)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_account,
    assert_distributor,
    create_distributor,
    create_grant_payload,
    create_order,
    create_product,
    create_territory,
    create_visit,
    get_lot_for_run,
    get_order,
    get_success_data,
    grant_territory,
    make_distributor_rep_headers,
    propose_account,
    review_visit,
    set_clock,
    setup_active_distributor,
    setup_allocated_order,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
    is_valid_uuid,
)
from datetime import datetime, timezone

ADMIN = TEST_USERS["brand_admin_headers"]


def test_suspended_distributor_cannot_create_orders(api):
    """PRD §2.9: "An operation that creates an order, delivery, service visit, promo
    program, or training certification requires the acting distributor's `status` to
    be `ACTIVE` and is otherwise rejected with `ERR_DISTRIBUTOR_NOT_ACTIVE`."

    Order creation is gated on the distributor's state, not on anything in the order
    payload: while SUSPENDED the create is rejected.

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_distributor_active
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    resp = api.suspend_distributor(net["distributor"]["id"], ADMIN)
    validate_success(resp)
    resp = api.create_order(
        {"delivery_week": "2026-09-07",
         "lines": [{"product_id": product["id"], "qty_requested": 5}]},
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_NOT_ACTIVE)
    distributor = get_success_data(api.get_distributor(net["distributor"]["id"], ADMIN))
    assert distributor["status"] == "SUSPENDED"


def test_reinstated_distributor_creates_orders_again(api):
    """PRD §3.1: "Reinstatement moves `SUSPENDED` → `ACTIVE`." and PRD §3.3:
    "`allocation_status`, beginning at `PENDING`"."

    After reinstatement the same order creation succeeds and the order is born with
    its allocation dimension PENDING.

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_distributor_active
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    validate_success(api.suspend_distributor(net["distributor"]["id"], ADMIN))
    validate_success(api.reinstate_distributor(net["distributor"]["id"], ADMIN))
    resp = api.create_order(
        {"delivery_week": "2026-09-07",
         "lines": [{"product_id": product["id"], "qty_requested": 5}]},
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["allocation_status"] == "PENDING"
    assert order["fulfillment_status"] == "UNSHIPPED"


def test_distributor_create_applies_defaults(api):
    """PRD §3.1: "An optional `service_level_tier` — one of `STANDARD`, `PREFERRED`,
    or `ELITE` — defaults to `STANDARD` when omitted and later drives allocation
    priority during weekly ordering (§3.3). A new distributor's `status` is
    `PROSPECT`: it exists on paper but cannot yet operate." and PRD §2.4: "Every
    resource is addressed by an `id`, a server-minted UUID with no type prefix,
    assigned at creation."

    Design: Corner/entities/distributor_create_applies_defaults
    """
    resp = api.create_distributor({"code": "D1", "name": "Dist One"}, ADMIN)
    distributor = validate_success(resp, expected_status=201)
    assert_distributor(distributor)
    assert distributor["status"] == "PROSPECT"
    assert distributor["service_level_tier"] == "STANDARD"
    assert distributor["version"] == 1, "version starts on creation"
    assert is_valid_uuid(distributor["id"])


def test_distributor_duplicate_code_rejected(api):
    """PRD §3.1: "A `BrandAdmin` registers a distributor with a `code` and a `name`;
    the `code` must be unique across all distributors, and a collision is rejected
    with `ERR_DUPLICATE_CODE`."

    Design: Corner/entities/distributor_create_duplicate_code_rejected
    """
    validate_success(api.create_distributor({"code": "D1", "name": "Dist One"}, ADMIN),
                     expected_status=201)
    resp = api.create_distributor({"code": "D1", "name": "Dist Clone"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


def test_territory_grant_activates_prospect_distributor(api):
    """PRD §3.1: "If the named distributor is still a `PROSPECT`, this first grant
    flips it to `ACTIVE`; from then on it may operate." and "A successful grant
    records `granted_distributor_id` as the named distributor, stamps `granted_at`
    with the current logical time, clears `revoked_at`, and increments the
    territory's `version`."

    The grant transition itself activates the distributor; no separate activation
    endpoint exists.

    Design: Corner/state_machines/territory_grant_activates_prospect_distributor
    """
    distributor = create_distributor(code="D1", name="Dist One")
    assert distributor["status"] == "PROSPECT"
    territory = create_territory(code="T1", name="North", region="NE")
    granted = grant_territory(territory, distributor["id"])
    assert granted["status"] == "GRANTED"
    assert granted["granted_distributor_id"] == distributor["id"]
    distributor = get_success_data(api.get_distributor(distributor["id"], ADMIN))
    assert distributor["status"] == "ACTIVE"


def test_distributor_terminate_cascades_territory_and_orders(api):
    """PRD §3.1: "Termination revokes every territory currently `GRANTED` to the
    distributor (each becomes `REVOKED` with `revoked_at` set to the current time)
    and cancels every one of its orders whose `allocation_status` is `PENDING`,
    `ALLOCATED`, `PARTIAL`, or `SHORTED` while its `fulfillment_status` is still
    `UNSHIPPED`, releasing each cancelled order's allocated lot units back to
    availability in reverse first-expiry order — lots with the latest `expires_at`
    are released first, ties broken by the latest `created_at` first."

    Design: Corner/state_machines/distributor_terminate_cascades_territory_and_orders
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    alloc = setup_allocated_order(net["distributor"], product, qty_requested=10)
    assert get_order(alloc["order"]["id"])["allocation_status"] == "ALLOCATED"

    terminated = validate_success(
        api.terminate_distributor(net["distributor"]["id"], ADMIN))
    assert terminated["status"] == "TERMINATED"

    territory = get_success_data(api.get_territory(net["territory"]["id"], ADMIN))
    assert territory["status"] == "REVOKED"
    assert territory["granted_distributor_id"] is None

    order = get_order(alloc["order"]["id"])
    assert order["allocation_status"] == "CANCELLED"
    lot = get_lot_for_run(alloc["run"]["id"])
    assert lot["available_units"] == 10 and lot["allocated_units"] == 0, (
        "the terminated distributor's allocated units return to availability"
    )


def test_revoked_territory_regrant_blocked_until_cooling_off(api):
    """PRD §2.5: "A territory in `REVOKED` is treated as, and persisted as, `OPEN`
    once the logical clock has reached at least 30 days after its `revoked_at`
    timestamp; the cooling-off elapsed, the territory is effectively open again, and
    the persisted flip increments the territory's `version`." and PRD §3.1: "the
    territory must be effectively `OPEN` — which includes a `REVOKED` territory
    whose 30-day cooling-off has elapsed".

    Ten days after revocation the regrant fails state legality; thirty-one days
    after, the lazy flip has reopened the territory and the grant succeeds.

    Design: Corner/validations/revoked_territory_regrant_blocked_until_cooling_off
    """
    distributor_1 = create_distributor(code="D1", name="Dist One")
    distributor_2 = create_distributor(code="D2", name="Dist Two")
    territory = create_territory(code="T1", name="North", region="NE")
    territory = grant_territory(territory, distributor_1["id"])
    revoked = validate_success(api.revoke_territory(territory["id"], ADMIN))

    set_clock("2026-09-11T00:00:00Z")  # revoked at 2026-09-01: only +10 days
    resp = api.grant_territory(
        territory["id"],
        create_grant_payload(distributor_2["id"], revoked["version"]),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-10-02T00:00:00Z")  # +31 days: cooling-off has elapsed
    data, _meta = validate_paginated(api.list_territories(ADMIN))
    current = next(t for t in data if t["id"] == territory["id"])
    assert current["status"] == "OPEN", "the lazy read persists the cooling-off flip"
    granted = validate_success(api.grant_territory(
        territory["id"],
        create_grant_payload(distributor_2["id"], current["version"]),
        ADMIN,
    ))
    assert granted["status"] == "GRANTED"
    assert granted["granted_distributor_id"] == distributor_2["id"]


def test_territory_grant_stale_version_rejected_then_fresh_succeeds(api):
    """PRD §2.6: "If another writer has advanced the territory's `version` since that
    observation, the grant is rejected with `ERR_STALE_VERSION` (HTTP 412),
    preventing the client from overwriting a grant state it has not seen. Because a
    grant from `GRANTED` legitimately supersedes the prior holder, the client's
    observed version is the only reliable guard."

    A superseding grant carrying the pre-grant version (1) is rejected 412; the same
    grant carrying the current version (2) succeeds and advances the territory to
    version 3.

    Design: Corner/cross_cutting_layers/territory_grant_occ_stale_then_fresh
    """
    distributor_1 = create_distributor(code="D1", name="Dist One")
    distributor_2 = create_distributor(code="D2", name="Dist Two")
    territory = create_territory(code="T1", name="North", region="NE")
    stale_version = territory["version"]
    granted = grant_territory(territory, distributor_1["id"])
    fresh_version = granted["version"]

    resp = api.grant_territory(
        territory["id"], create_grant_payload(distributor_2["id"], stale_version), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    superseded = validate_success(api.grant_territory(
        territory["id"], create_grant_payload(distributor_2["id"], fresh_version), ADMIN))
    assert superseded["granted_distributor_id"] == distributor_2["id"]
    assert superseded["version"] == fresh_version + 1 == 3, (
        "each grant increments the territory version by exactly 1"
    )


def test_distributor_suspend_cancels_only_open_visits(api):
    """PRD §3.1: "Suspension moves `ACTIVE` → `SUSPENDED` and cancels every service
    visit of that distributor still in `SCHEDULED` or `REWORK`, moving each to
    `CANCELLED`."

    The cascade is conditional on non-terminal visit status: the SCHEDULED visit is
    cancelled while the VERIFIED visit is untouched.

    Design: Corner/cross_cutting_layers/distributor_suspend_cancels_open_visits
    """
    net = setup_active_distributor()
    account = propose_account(net["distributor"], net["territory"])
    account = approve_account(account["id"])
    visit_open = create_visit(account, net["distributor"],
                              "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    visit_done = create_visit(account, net["distributor"],
                              "2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z")
    visit_done = submit_visit(visit_done, net["distributor"], score=90)
    visit_done = review_visit(visit_done, "VERIFY")
    assert visit_done["status"] == "VERIFIED"

    validate_success(api.suspend_distributor(net["distributor"]["id"], ADMIN))

    visit_open = get_success_data(api.get_service_visit(visit_open["id"], ADMIN))
    assert visit_open["status"] == "CANCELLED", (
        "only SCHEDULED/REWORK visits are cancelled by the suspension cascade"
    )
    visit_done = get_success_data(api.get_service_visit(visit_done["id"], ADMIN))
    assert visit_done["status"] == "VERIFIED"


def test_created_distributor_visible_immediately_with_clock_default(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field." and
    PRD §2.5: "At server startup, before any clock operation, the logical clock reads
    exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time
    thereafter."

    The creation is visible in the very next list read with its server-minted fields:
    status PROSPECT and created_at reading the logical clock's startup default
    (compared as instants, since PRD §2.4 mandates three fractional digits).

    Design: Corner/consistency_model/immediate_read_after_write
    """
    created = validate_success(
        api.create_distributor({"code": "D1", "name": "Dist One"}, ADMIN),
        expected_status=201)
    data, _meta = validate_paginated(api.list_distributors(ADMIN))
    found = next(d for d in data if d["id"] == created["id"])
    assert found["status"] == "PROSPECT"
    assert datetime.fromisoformat(found["created_at"].replace("Z", "+00:00")) == \
        datetime(2026, 9, 1, tzinfo=timezone.utc), (
        f"created_at must record the logical clock default, got {found['created_at']}"
    )
