"""Business-rule validation corners: capability, last-order-date boundary,
production notice, transit window, and suspended-dealer submission
(PRD §2.7, §3.1, §3.3, §3.5, §3.6)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_and_lock_configuration,
    create_configuration,
    create_order,
    create_phase,
    get_order,
    lock_configuration,
    make_dealer_headers,
    make_lock_payload,
    make_module_entry,
    make_reserve_slot_payload,
    make_submit_payload,
    reserve_slot,
    set_logical_clock,
    setup_acknowledged_order,
    setup_dealer_world,
    setup_locked_world,
    suspend_dealer,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_submit_rejects_insufficient_capability(api):
    """PRD §2.7: "order submission requires the dealer's level to be at least
    the level required by every module category in the configuration:
    `SYSTEMS` modules require level 3" and §3.5: "(else
    `ERR_CAPABILITY_INSUFFICIENT`)".

    Design: Corner/validations/val_submit_rejects_insufficient_capability
    """
    ctx = setup_dealer_world(
        api, capability=2, family_specs=(("SYS-7500", "SYSTEMS", 42),)
    )
    spec = create_and_lock_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("WORKSTATION_6X6", "A", 1)],
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CAPABILITY_INSUFFICIENT)


def test_sunsetting_lock_boundary_15th_ok_16th_rejected(api):
    """PRD §3.3: "configurations referencing the family may lock only while
    the clock date is on or before `last_order_date`" and §3.4: "a referenced
    `SUNSETTING` family rejects the lock with `ERR_LAST_ORDER_DATE_PASSED`
    once the clock date is past its `last_order_date`."

    Design: Corner/validations/val_sunsetting_lock_boundary_15th_ok_16th_rejected
    """
    ctx = setup_dealer_world(
        api, family_specs=(("SEAT-2200", "SEATING", 28),)
    )
    family = ctx["families"]["SEATING"]
    spec_a = create_configuration(api, ctx["dealer"]["id"], name="Spec A")
    spec_b = create_configuration(api, ctx["dealer"]["id"], name="Spec B")
    sunset = validate_success(
        api.update_product_family(
            family["id"],
            {"lifecycle_status": "SUNSETTING", "last_order_date": "2026-10-15"},
            ADMIN,
        ),
        200,
    )
    assert sunset["lifecycle_status"] == "SUNSETTING"

    # On the last order date itself the lock is still permitted (<= boundary).
    set_logical_clock(api, "2026-10-15T00:00:00Z")
    locked_a = lock_configuration(api, spec_a, ctx["dealer"]["id"])
    assert locked_a["status"] == "LOCKED"

    # One day later the same lock is rejected.
    set_logical_clock(api, "2026-10-16T00:00:00Z")
    resp = api.lock_configuration(
        spec_b["id"], make_lock_payload(spec_b["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LAST_ORDER_DATE_PASSED)


def test_production_notice_boundary_rejected_then_ok(api):
    """PRD §3.6: "the `production_date` must be at least 2 calendar days
    after the clock date (else `ERR_PRODUCTION_NOTICE_VIOLATION`)" — at clock
    2026-09-01, 2026-09-02 fails and 2026-09-03 succeeds.

    Design: Corner/validations/val_production_notice_boundary_rejected_then_ok
    """
    ctx = setup_acknowledged_order(api)
    phase = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"])

    resp = api.reserve_slot(
        phase["id"],
        make_reserve_slot_payload(production_date="2026-09-02"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOTICE_VIOLATION)

    scheduled = reserve_slot(
        api, phase["id"], ctx["dealer"]["id"], production_date="2026-09-03"
    )
    assert scheduled["logistics_status"] == "SCHEDULED"


def test_transit_window_boundary_rejected_then_ok(api):
    """PRD §3.6: "the `production_date` must be no later than the order's
    `requested_install_date` minus the plant's transit allowance — 4 calendar
    days for `PLANT_GR`, 6 for `PLANT_DAL` (else
    `ERR_TRANSIT_WINDOW_VIOLATION`)" — against install 2026-12-15,
    2026-12-12 fails and 2026-12-11 succeeds.

    Design: Corner/validations/val_transit_window_boundary_rejected_then_ok
    """
    ctx = setup_acknowledged_order(api)
    ph1 = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"],
                       floor_number=1, phase_sequence=1)
    ph2 = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"],
                       floor_number=1, phase_sequence=2)

    resp = api.reserve_slot(
        ph1["id"],
        make_reserve_slot_payload(production_date="2026-12-12"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRANSIT_WINDOW_VIOLATION)

    scheduled = reserve_slot(
        api, ph2["id"], ctx["dealer"]["id"], production_date="2026-12-11"
    )
    assert scheduled["logistics_status"] == "SCHEDULED"


def test_submit_rejected_while_dealer_suspended(api):
    """PRD §3.1: "A suspended dealer cannot submit orders — any attempt is
    rejected with `ERR_DEALER_SUSPENDED`."

    Design: Corner/validations/val_submit_rejected_while_dealer_suspended
    """
    ctx = setup_locked_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
    )
    suspend_dealer(api, ctx["dealer"]["id"])

    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEALER_SUSPENDED)
    assert get_order(
        api, order["id"], make_dealer_headers(ctx["dealer"]["id"])
    )["status"] == "DRAFT"
