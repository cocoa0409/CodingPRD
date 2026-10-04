"""Service dispatch, parts logistics and the safety floor over financing."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_household_user,
    api_client,
    create_membership,
    create_service_order,
    get_device,
    get_membership,
    get_order,
    get_part,
    get_service_order,
    mint_device,
    owner_headers,
    place_order,
    set_clock,
    setup_active_membership,
    setup_delinquent_household,
    setup_financing_plan,
    setup_parts_scenario,
    pay_installments,
    validate_paginated,
    validate_success,
)

TECH = TEST_USERS["service_technician_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

CREW_WINDOW = {"scheduled_start_at": "2026-09-08T09:00:00Z",
               "scheduled_end_at": "2026-09-08T11:00:00Z"}


# =========================================================================
# Queue A — Difficulty instances
# =========================================================================

def test_a_failed_repair_loops_the_service_order_back_to_scheduled():
    """PRD §3.6: "A failed repair returns the order from `REPAIR_IN_PROGRESS` to
    `SCHEDULED`, and it latches `failure_before_part` true whenever no part was
    reserved at the moment of failure, capturing the fact that a repair attempt was
    made without a part in hand."

    Design: Difficulty/non_linear_state_machine/service_order_failed_repair_loops_back_to_scheduled
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    service_order = create_service_order({
        "device_id": base["device_id"],
        "reported_fault_code": "NO_POWER",
        "diagnosis_note": "unit will not power on",
    }, TECH)
    assert service_order["fault_class"] == "SAFETY_CRITICAL"

    validate_success(api_client.schedule_service_order(
        service_order["id"], CREW_WINDOW, TECH), 200)
    validate_success(api_client.start_repair(service_order["id"], {}, TECH), 200)

    looped = validate_success(api_client.fail_repair(
        service_order["id"], {"diagnosis_note": "power rail replacement needed"}, TECH), 200)

    assert looped["status"] == "SCHEDULED"
    assert looped["failure_before_part"] is True
    assert looped["safety_functions_maintained"] is True
    assert looped["part_id"] is None
    assert looped["reserved_part_qty"] == 0


def test_a_safety_critical_order_schedules_without_a_part_but_a_cosmetic_one_does_not():
    """PRD §3.6: "A `DISPATCH_PENDING_PART` order is schedulable only when its fault
    class is `SAFETY_CRITICAL`, which lets a safety-critical repair proceed without a
    part precisely because the safety function has to be restored first. A cosmetic
    order with no part reserved is refused with `ERR_PART_REQUIRED_FOR_SCHEDULING`
    (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/service_order_failed_repair_loops_back_to_scheduled
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")

    safety = create_service_order({
        "device_id": base["device_id"],
        "reported_fault_code": "NO_POWER",
        "diagnosis_note": "dead unit",
    }, TECH)
    assert safety["fault_class"] == "SAFETY_CRITICAL"
    assert safety["priority"] == "PRIORITY_SAFETY"

    scheduled = validate_success(api_client.schedule_service_order(
        safety["id"], CREW_WINDOW, TECH), 200)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["part_id"] is None
    assert scheduled["safety_functions_maintained"] is True

    cosmetic = create_service_order({
        "device_id": base["device_id"],
        "reported_fault_code": "BELT_SLIP",
        "diagnosis_note": "cosmetic belt abrasion",
    }, TECH)
    assert cosmetic["fault_class"] == "COSMETIC"

    res = api_client.schedule_service_order(cosmetic["id"], {
        "scheduled_start_at": "2026-09-07T09:00:00Z",
        "scheduled_end_at": "2026-09-07T11:00:00Z",
    }, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PART_REQUIRED_FOR_SCHEDULING"
    assert get_service_order(cosmetic["id"])["status"] == "DISPATCHED"
    assert get_device(base["device_id"])["entitlement_lock"] is False


def test_the_scratch_leg_of_the_installation_cap_refuses_more_than_five_flights():
    """PRD §3.2: "One safety clause gates the close: the carry itself may not exceed
    five stair flights unless the building has a working elevator. Concretely,
    completion requires that `stair_flights` is at most 5 or that `has_elevator` is
    true; when neither holds the request is refused with `ERR_STAIR_CAP_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/delivery_crew_half_open_window_admits_abutting_and_rejects_contained
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False,
                                   stair_flights=5, has_elevator=False)
    assert base["appointment"]["stair_flights"] == 5

    at_cap = validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)
    assert at_cap["status"] == "COMPLETED"

    over = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False,
                                   stair_flights=6, has_elevator=False,
                                   serial="TREAD-0007", crew="CREW-Y")
    res = api_client.complete_delivery_appointment(
        over["appointment_id"], {"completion_grade": "CLEAN"}, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_STAIR_CAP_EXCEEDED"

    with_elevator = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False,
                                            stair_flights=6, has_elevator=True,
                                            serial="TREAD-0008", crew="CREW-X")
    done = validate_success(api_client.complete_delivery_appointment(
        with_elevator["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)
    assert done["status"] == "COMPLETED"


def test_delinquency_blocks_a_new_order_without_touching_content_or_safety():
    """PRD §3.1: "Orders may not be placed at all while the household is commercially
    distressed. When the membership posture is `RESTRICTED` or `FROZEN`, order
    placement and financing origination are refused with `ERR_POSTURE_RESTRICTED`
    (HTTP 409)."
    PRD §2.6: "`RESTRICTED` blocks the creation of new hardware orders and new
    financing plans but leaves content streaming fully enabled — restriction is not
    a lockout."

    Design: Difficulty/priority_pair_validation_conflict/delivered_order_cancel_priority_state_beats_business_fiscal
    """
    base = setup_delinquent_household()
    m_id = base["membership_id"]
    assert get_membership(m_id)["posture"] == "RESTRICTED"

    res = api_client.create_hardware_order(m_id, {
        "hardware_sku": "TREAD",
        "subtotal_cents": 296_000,
        "financing_method": "FULL_PAYMENT",
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_POSTURE_RESTRICTED"

    membership = get_membership(m_id)
    assert membership["safety_gate_open"] is True
    device = get_device(base["device_id"])
    assert device["content_access_allowed"] is True


def test_a_financed_delivered_order_cannot_be_cancelled_after_delivery():
    """PRD §3.5: "A `DELIVERED` order may be cancelled only when it was paid in
    full — a financed order may not be cancelled after delivery, and such an attempt
    is refused with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/delivered_order_cancel_priority_state_beats_business_fiscal
    """
    base = setup_delinquent_household()
    m_id = base["membership_id"]
    o_id = base["order_id"]

    res = api_client.cancel_hardware_order(o_id, {}, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"

    order = get_order(o_id, m_id)
    assert order["status"] == "DELIVERED"

    membership = get_membership(m_id)
    assert membership["status"] == "DELINQUENT"
    assert membership["unpaid_financing_count"] == 1


def test_redeeming_a_credit_on_a_denied_dispute_is_refused_on_the_dispute_gate():
    """PRD §3.2: "The fiscal dispute gate is evaluated first, so an order whose
    dispute resolution is `DENIED` is refused with `ERR_REFUND_DISPUTE_DENIED` (HTTP
    409) even when the household would also have blocked it; only after that gate
    clears is the purchase gate evaluated, and a membership in `RESTRICTED` or
    `FROZEN` posture causes the redemption to be refused with `ERR_PURCHASE_BLOCKED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/redemptive_credit_priority_dispute_gate_beats_purchase_block
    """
    base = setup_delinquent_household()
    m_id = base["membership_id"]
    o_id = base["order_id"]

    validate_success(api_client.file_refund_dispute(
        o_id, {"resolution": "DENIED"}, ADMIN), 200)
    order = get_order(o_id, m_id)
    assert order["refund_dispute_status"] == "DENIED"
    assert get_membership(m_id)["posture"] == "RESTRICTED"

    res = api_client.redeem_refund(o_id, {
        "redeem_credit_cents": 25_000,
        "expected_membership_version": get_membership(m_id)["version"],
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_REFUND_DISPUTE_DENIED"


def test_reserving_exactly_the_reservable_quantity_is_admitted():
    """PRD §3.6: "And the reservation must not strip the shelf too bare: the
    admission boundary is that the requested quantity may be at most the part's
    `on_hand_qty` minus its `safety_stock_qty`. A request for exactly that remaining
    reservable quantity is admitted."

    Design: Difficulty/boundary_precision_check/parts_safety_stock_exact_and_one_past_boundary
    """
    base = setup_parts_scenario(restock_qty=7, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    part = get_part(part_id)
    assert part["on_hand_qty"] == 7
    assert part["safety_stock_qty"] == 2
    assert part["on_hand_qty"] - part["safety_stock_qty"] == 5

    reserved = validate_success(api_client.reserve_part(
        so_id, {"part_id": part_id, "quantity": 5}, TECH), 200)
    assert reserved["status"] == "PART_RESERVED"
    assert reserved["reserved_part_qty"] == 5

    part = get_part(part_id)
    assert part["reserved_qty"] == 5
    assert part["on_hand_qty"] == 2
    assert part["on_hand_qty"] == part["safety_stock_qty"]


def test_one_unit_past_the_reservable_quantity_is_refused():
    """PRD §3.6: "A request for exactly that remaining reservable quantity is
    admitted; a request one unit beyond it is refused with `ERR_PART_SAFETY_STOCK`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/parts_safety_stock_exact_and_one_past_boundary
    """
    base = setup_parts_scenario(restock_qty=7, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    part = get_part(part_id)
    assert part["on_hand_qty"] - part["safety_stock_qty"] == 5

    # one unit past the reservable quantity of 5 is refused
    res = api_client.reserve_part(so_id, {"part_id": part_id, "quantity": 6}, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PART_SAFETY_STOCK"

    part = get_part(part_id)
    assert part["reserved_qty"] == 0
    assert part["on_hand_qty"] == 7
    assert part["stock_received_qty"] - part["reserved_qty"] - part["consumed_qty"] == part["on_hand_qty"]
    assert get_service_order(so_id)["status"] == "DISPATCHED"


def test_releasing_a_reservation_restores_the_stock_position_exactly():
    """PRD §3.6: "A reservation may also be released back to stock by a platform
    administrator through a release request that supplies the `service_order_id` and
    a `quantity` to return; it returns the order to `DISPATCH_PENDING_PART` with
    `part_id` cleared and `reserved_part_qty` zeroed, reduces the part's
    `reserved_qty` by the released quantity, and recomputes the stock position."

    Design: Difficulty/compensating_invariant/parts_reservation_release_returns_the_stock_position_to_its_start
    """
    base = setup_parts_scenario(restock_qty=7, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    before = get_part(part_id)
    assert before["stock_received_qty"] == 7
    assert before["reserved_qty"] == 0
    assert before["consumed_qty"] == 0
    assert before["on_hand_qty"] == 7

    reserved = validate_success(api_client.reserve_part(
        so_id, {"part_id": part_id, "quantity": 3}, TECH), 200)
    assert reserved["status"] == "PART_RESERVED"

    released = validate_success(api_client.release_reservation(
        part_id, {"service_order_id": so_id, "quantity": 3}, ADMIN), 200)
    assert released["status"] == "DISPATCH_PENDING_PART"
    assert released["part_id"] is None
    assert released["reserved_part_qty"] == 0

    after = get_part(part_id)
    assert after["stock_received_qty"] == before["stock_received_qty"] == 7
    assert after["reserved_qty"] == before["reserved_qty"] == 0
    assert after["consumed_qty"] == before["consumed_qty"] == 0
    assert after["on_hand_qty"] == before["on_hand_qty"] == 7



def test_a_partial_release_returns_only_the_released_units_to_stock():
    """PRD §3.6: "A reservation may also be released back to stock by a platform
    administrator through a release request that supplies the `service_order_id` and
    a `quantity` to return; it returns the order to `DISPATCH_PENDING_PART` with
    `part_id` cleared and `reserved_part_qty` zeroed, reduces the part's
    `reserved_qty` by the released quantity, and recomputes the stock position."
    PRD §3.6: "`on_hand_qty` is always `stock_received_qty` minus `reserved_qty`
    minus `consumed_qty`."

    Design: Difficulty/compensating_invariant/parts_reservation_release_returns_the_stock_position_to_its_start
    """
    base = setup_parts_scenario(restock_qty=7, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    validate_success(api_client.reserve_part(so_id, {"part_id": part_id, "quantity": 3}, TECH), 200)
    reserved = get_part(part_id)
    assert reserved["reserved_qty"] == 3
    assert reserved["on_hand_qty"] == 4

    released = validate_success(api_client.release_reservation(
        part_id, {"service_order_id": so_id, "quantity": 1}, ADMIN), 200)
    # release clears the order's own reservation and returns it to park
    assert released["status"] == "DISPATCH_PENDING_PART"
    assert released["part_id"] is None
    assert released["reserved_part_qty"] == 0

    partial = get_part(part_id)
    # only the released unit returns to stock: 3 - 1 == 2 still held
    assert partial["reserved_qty"] == 2
    assert partial["on_hand_qty"] == 5
    assert (partial["stock_received_qty"] - partial["reserved_qty"]
            - partial["consumed_qty"]) == partial["on_hand_qty"]
    assert get_service_order(so_id)["reserved_part_qty"] == 0


def test_the_last_installment_parks_the_plan_at_paid_off():
    """PRD §3.5: "A payment from `CURRENT` that brings the paid count to exactly the
    term moves the plan to `PAID_OFF`, its terminal settled state."
    PRD §3.5: "From `ORIGINATED` the plan requires that the next payment would not
    exceed the term; an attempt to pay past the term is refused with
    `ERR_INSTALLMENT_COUNT_EXCEEDED` (HTTP 409), and a payment against an
    already-settled plan is refused with `ERR_PLAN_ALREADY_PAID_OFF` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/final_installment_boundary_parks_the_plan_at_paid_off
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 120_000,
        "term_months": 6,
        "apr_bps": 0,
    }, owner_headers(m_id)), 201)
    assert plan["monthly_installment_cents"] == 20_000

    for _ in range(5):
        fifth = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert fifth["status"] == "CURRENT"
    assert fifth["installments_paid"] == 5

    sixth = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert sixth["status"] == "PAID_OFF"
    assert sixth["installments_paid"] == 6
    assert sixth["safety_disable_latched"] is False


def test_a_payment_beyond_the_term_is_refused():
    """PRD §3.5: "a payment against an already-settled plan is refused with
    `ERR_PLAN_ALREADY_PAID_OFF` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/final_installment_boundary_parks_the_plan_at_paid_off
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 120_000,
        "term_months": 6,
        "apr_bps": 0,
    }, owner_headers(m_id)), 201)
    for _ in range(6):
        settled = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert settled["status"] == "PAID_OFF"

    res = api_client.pay_installment(plan["id"], {}, owner_headers(m_id))
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PLAN_ALREADY_PAID_OFF"

    after = validate_success(api_client.get_financing_plan(plan["id"], owner_headers(m_id)), 200)
    assert after["installments_paid"] == 6
    assert after["status"] == "PAID_OFF"


def test_the_stream_ceiling_admits_at_the_boundary_and_refuses_one_past_it():
    """PRD §2.5: "When a start-stream request would raise the household past its
    ceiling, the platform does not simply refuse. The start-stream payload names the
    machine the user is streaming on through `device_serial`. It evicts one
    non-owner member: the eviction candidate set is restricted to household users on
    the same membership whose `role` is `MEMBER` and whose status is `ACTIVE`,
    excluding the requesting user itself."
    PRD §2.5: "If the candidate set is empty, no eviction is possible and the
    request is refused with `ERR_CONCURRENT_LIMIT_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/concurrent_stream_limit_exact_boundary_admits_and_one_past_evicts
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z",
                                   concurrent_limit_override=2)
    m_id = base["membership_id"]

    # only the OWNER is present, so the owner's own stream lands exactly on the
    # boundary (1 + 1 <= 2) and is admitted without evicting anyone
    assert get_membership(m_id)["active_user_count"] == 1
    assert get_membership(m_id)["concurrent_limit_effective"] == 2

    started = validate_success(api_client.start_stream(
        base["owner"]["id"], {"device_serial": base["serial"]}, owner_headers(m_id)), 200)
    assert started["streaming_device_serial"] == base["serial"]

    member = add_household_user(m_id, display_name="Bea Fernwood", email="bea@x.com",
                                role="MEMBER")

    membership = get_membership(m_id)
    assert membership["active_user_count"] == 2
    assert membership["concurrent_limit_effective"] == 2

    # one past the boundary (2 + 1 > 2): the only other ACTIVE member is the
    # caller itself, and the OWNER is never evicted, so the set is empty
    res = api_client.start_stream(member["id"], {
        "device_serial": base["serial"],
        "expected_membership_version": get_membership(m_id)["version"],
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_CONCURRENT_LIMIT_EXCEEDED"

    after_member = validate_success(
        api_client.get_household_user(member["id"], owner_headers(m_id)), 200)
    assert after_member["status"] == "ACTIVE"
    assert after_member["eviction_count"] == 0
    assert get_membership(m_id)["active_user_count"] == 2


def test_the_owner_is_never_evicted_even_when_the_ceiling_is_full():
    """PRD §2.5: "The `OWNER` is never evicted under any circumstance. If the
    candidate set is empty, no eviction is possible and the request is refused with
    `ERR_CONCURRENT_LIMIT_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/concurrent_stream_limit_exact_boundary_admits_and_one_past_evicts
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z",
                                   concurrent_limit_override=1)
    m_id = base["membership_id"]
    assert get_membership(m_id)["concurrent_limit_effective"] == 1

    res = api_client.start_stream(
        base["owner"]["id"], {"device_serial": base["serial"]}, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_CONCURRENT_LIMIT_EXCEEDED"

    owner = validate_success(
        api_client.get_household_user(base["owner"]["id"], owner_headers(m_id)), 200)
    assert owner["status"] == "ACTIVE"
    assert owner["role"] == "OWNER"
    assert owner["eviction_count"] == 0


def test_failures_below_the_third_strike_leave_the_plan_current():
    """PRD §3.5: "So the boundary is exact: two failures leave the plan current, and
    the third makes it delinquent."

    Design: Difficulty/non_linear_state_machine/financing_plan_delinquency_cycles_back_to_current
    """
    from test_helpers import setup_financing_plan, pay_installments

    base = setup_financing_plan()  # noqa: F811 - imported at module scope too
    m_id = base["membership_id"]
    pay_installments(base, 1)

    first = validate_success(api_client.fail_installment(base["plan_id"], {}, ADMIN), 200)
    second = validate_success(api_client.fail_installment(base["plan_id"], {}, ADMIN), 200)

    assert first["status"] == "CURRENT"
    assert first["retry_count"] == 1
    assert second["status"] == "CURRENT"
    assert second["retry_count"] == 2
    assert second["delinquency_count"] == 0
    assert get_membership(m_id)["unpaid_financing_count"] == 0


# =========================================================================
# Queue B — Corner instances
# =========================================================================

def test_a_zero_quantity_reservation_moves_no_stock():
    """PRD §3.6: "the admission boundary is that the requested quantity may be at
    most the part's `on_hand_qty` minus its `safety_stock_qty`."

    Design: Corner/calculations/parts_reservation_at_zero_quantity_moves_no_stock
    """
    base = setup_parts_scenario(restock_qty=5, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    res = api_client.reserve_part(so_id, {"part_id": part_id, "quantity": 0}, TECH)
    assert res.status_code >= 400, res.text

    part = get_part(part_id)
    assert part["reserved_qty"] == 0
    assert part["on_hand_qty"] == 5

    exact = validate_success(api_client.reserve_part(
        so_id, {"part_id": part_id, "quantity": 3}, TECH), 200)
    assert exact["reserved_part_qty"] == 3
    assert exact["status"] == "PART_RESERVED"
    assert get_part(part_id)["on_hand_qty"] == 2


def test_a_cosmetic_fault_with_no_stock_parks_the_order_pending_a_part():
    """PRD §3.6: "When a cosmetic fault cannot be served because no part is
    available, the order does not stall in `DISPATCHED` — a rejected reservation
    attempt for a cosmetic fault parks it in `DISPATCH_PENDING_PART`, and the
    rejection surfaces as `ERR_PART_INSUFFICIENT` (HTTP 409)."

    Design: Corner/errors/cosmetic_fault_with_no_stock_parks_the_service_order_pending_a_part
    """
    base = setup_parts_scenario(restock_qty=0, safety_stock_qty=2)
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    assert get_part(part_id)["on_hand_qty"] == 0

    res = api_client.reserve_part(so_id, {"part_id": part_id, "quantity": 1}, TECH)
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PART_INSUFFICIENT"

    after = get_service_order(so_id)
    assert after["status"] == "DISPATCH_PENDING_PART"
    assert after["safety_functions_maintained"] is True

    schedule_res = api_client.schedule_service_order(so_id, {
        "scheduled_start_at": "2026-09-06T13:00:00Z",
        "scheduled_end_at": "2026-09-06T15:00:00Z",
    }, TECH)
    assert schedule_res.status_code == 409, schedule_res.text
    assert schedule_res.json()["data"]["error_id"] == "ERR_PART_REQUIRED_FOR_SCHEDULING"

    device = get_device(base["device_id"])
    assert device["entitlement_lock"] is False
    assert device["content_access_allowed"] is True


def test_a_part_for_a_foreign_sku_is_refused_on_compatibility():
    """PRD §3.6: "Two compatibility gates apply. The reserved part's `compatible_sku`
    must equal the device's `hardware_sku`; a mismatch is refused with
    `ERR_PART_SKU_MISMATCH` (HTTP 409)."

    Design: Corner/validations/part_reservation_for_a_foreign_sku_returns_part_sku_mismatch
    """
    set_clock("2026-09-05T13:30:00Z")
    membership = create_membership()
    m_id = membership["id"]
    add_household_user(m_id, display_name="Ada Quillon", email="ada@x.com", role="OWNER")
    device = mint_device(m_id, hardware_sku="BIKE", serial="BIKE-0001")
    order = place_order(m_id, device["id"], hardware_sku="BIKE", subtotal_cents=149_000)
    appointment = api_client.create_delivery_appointment({
        "device_id": device["id"],
        "hardware_order_id": order["id"],
        "start_at": "2026-09-05T13:00:00Z",
        "end_at": "2026-09-05T15:00:00Z",
        "zone": "METRO",
        "technician_crew_code": "CREW-A",
        "stair_flights": 0,
        "has_elevator": False,
    }, TECH)
    appointment = validate_success(appointment, 201)
    validate_success(api_client.schedule_delivery_appointment(
        appointment["id"], {"start_at": "2026-09-05T13:00:00Z",
                            "end_at": "2026-09-05T15:00:00Z"}, TECH), 200)
    validate_success(api_client.start_delivery_appointment(appointment["id"], {}, TECH), 200)
    validate_success(api_client.complete_delivery_appointment(
        appointment["id"], {"completion_grade": "CLEAN"}, TECH), 200)

    part = validate_success(api_client.create_part({
        "part_code": "TREAD-BELT-42",
        "compatible_sku": "TREAD",
        "safety_stock_qty": 2,
        "part_lot_key": "LOT-2026-09",
    }, ADMIN), 201)
    validate_success(api_client.restock_part(part["id"], {"quantity": 5}, ADMIN), 200)
    service_order = validate_success(api_client.create_service_order({
        "device_id": device["id"],
        "reported_fault_code": "BELT_SLIP",
        "diagnosis_note": "drivetrain noise",
    }, TECH), 201)

    res = api_client.reserve_part(service_order["id"],
                                  {"part_id": part["id"], "quantity": 2}, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PART_SKU_MISMATCH"

    after_part = get_part(part["id"])
    assert after_part["reserved_qty"] == 0
    assert after_part["on_hand_qty"] == 5
    after_order = get_service_order(service_order["id"])
    assert after_order["status"] == "DISPATCHED"
    assert after_order["part_id"] is None
    assert after_order["fault_class"] == "COSMETIC"


def test_reserving_a_safety_critical_fault_waits_for_the_part_instead_of_parking():
    """PRD §3.6: "Parking for want of a part is impermissible for safety-critical
    faults, because the safety function must be restored regardless of parts
    availability."

    Design: Difficulty/non_linear_state_machine/service_order_failed_repair_loops_back_to_scheduled
    """
    base = setup_parts_scenario(restock_qty=4, safety_stock_qty=2,
                                fault_code="FRAME_CRACK")
    part_id = base["part_id"]
    so_id = base["service_order_id"]

    reserved = validate_success(api_client.reserve_part(
        so_id, {"part_id": part_id, "quantity": 2}, TECH), 200)
    assert reserved["status"] == "PART_RESERVED"
    assert reserved["fault_class"] == "SAFETY_CRITICAL"
    assert reserved["priority"] == "PRIORITY_SAFETY"
    # on_hand_qty is now 2 == safety_stock_qty, so nothing further is reservable
    assert get_part(part_id)["on_hand_qty"] == 2

    cosmetic = get_service_order(so_id)
    assert cosmetic["status"] == "PART_RESERVED"

    # A second safety-critical fault cannot reserve past the safety floor, and
    # unlike a cosmetic fault it does not park for want of a part.
    second = create_service_order({
        "device_id": base["device_id"],
        "reported_fault_code": "FRAME_CRACK",
        "diagnosis_note": "second safety fault on the same unit",
    }, TECH)
    assert second["fault_class"] == "SAFETY_CRITICAL"

    unschedulable = api_client.reserve_part(
        second["id"], {"part_id": part_id, "quantity": 1}, TECH)
    assert unschedulable.status_code == 409, unschedulable.text
    assert unschedulable.json()["data"]["error_id"] == "ERR_PART_SAFETY_STOCK"
    # safety-critical faults never park: the order stays DISPATCHED
    assert get_service_order(second["id"])["status"] == "DISPATCHED"
    assert get_service_order(second["id"])["safety_functions_maintained"] is True


def test_service_orders_list_narrows_by_device_part_and_status():
    """PRD §2.3: "Every paginated list response carries four pagination fields inside
    the `meta` object of the envelope: `limit`, `offset`, `total_count` and
    `has_more`."

    Design: Corner/endpoints/service_orders_list_filters_by_device_and_part
    """
    base = setup_parts_scenario(restock_qty=6, safety_stock_qty=2)
    part_id = base["part_id"]
    d_id = base["device_id"]

    belt = base["service_order_id"]
    sensor = validate_success(api_client.create_service_order({
        "device_id": d_id,
        "reported_fault_code": "SENSOR_FAULT",
        "diagnosis_note": "cadence sensor",
    }, TECH), 201)
    validate_success(api_client.reserve_part(belt, {"part_id": part_id, "quantity": 2}, TECH), 200)

    rows, meta = validate_paginated(
        api_client.list_service_orders(TECH, params={"device_id": d_id}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_service_orders(TECH, params={"part_id": part_id}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == belt

    rows, meta = validate_paginated(
        api_client.list_service_orders(TECH, params={"status": "DISPATCHED"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == sensor["id"]

    rows, meta = validate_paginated(api_client.list_part_service_orders(part_id, TECH))
    assert meta["total_count"] == 1
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta


def test_the_stock_position_is_recomputed_rather_than_kept_as_a_running_total():
    """PRD §3.6: "Every one of those movements recomputes `on_hand_qty` from the
    identity above, so no separate decrement of `on_hand_qty` is ever performed."

    Design: Corner/calculations/parts_reservation_at_zero_quantity_moves_no_stock
    """
    base = setup_parts_scenario(restock_qty=7, safety_stock_qty=2)
    part_id = base["part_id"]

    validate_success(api_client.restock_part(part_id, {"quantity": 3}, ADMIN), 200)
    part = get_part(part_id)
    assert part["stock_received_qty"] == 10
    assert part["on_hand_qty"] == 10

    validate_success(api_client.reserve_part(
        base["service_order_id"], {"part_id": part_id, "quantity": 4}, TECH), 200)
    part = get_part(part_id)
    assert part["reserved_qty"] == 4
    assert part["on_hand_qty"] == 6
    assert part["stock_received_qty"] - part["reserved_qty"] - part["consumed_qty"] == 6


def test_a_viewer_can_resolve_the_part_that_a_service_order_reserved():
    """PRD §3.6: "Parts are reserved from inventory. A technician supplies a `part_id`
    and a `quantity`, and the order moves into `PART_RESERVED` with `part_id` and
    `reserved_part_qty` recorded."

    Design: Corner/endpoints/service_orders_list_filters_by_device_and_part
    """
    base = setup_parts_scenario(restock_qty=5, safety_stock_qty=2)
    reserved = validate_success(api_client.reserve_part(
        base["service_order_id"], {"part_id": base["part_id"], "quantity": 2}, TECH), 200)
    assert reserved["part_id"] == base["part_id"]
    assert reserved["reserved_part_qty"] == 2

    rows, meta = validate_paginated(
        api_client.list_service_order_parts(base["service_order_id"], TECH))
    assert meta["total_count"] >= 1
    assert any(row["id"] == base["part_id"] for row in rows)

def test_scheduling_branches_on_the_service_order_fault_class():
    """PRD §3.6: "A `DISPATCH_PENDING_PART` order is schedulable only when its fault
    class is `SAFETY_CRITICAL`, which lets a safety-critical repair proceed without a
    part precisely because the safety function has to be restored first."
    PRD §3.6: "The `fault_class` is `SAFETY_CRITICAL` when the reported code is
    `NO_POWER` or `FRAME_CRACK`, and `COSMETIC` for every other code."

    Design: Difficulty/cross_entity_state_dependency/service_order_scheduling_depends_on_service_order_fault_class
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    d_id = base["device_id"]

    safety = create_service_order({
        "device_id": d_id, "reported_fault_code": "NO_POWER",
        "diagnosis_note": "dead unit",
    }, TECH)
    cosmetic = create_service_order({
        "device_id": d_id, "reported_fault_code": "SENSOR_FAULT",
        "diagnosis_note": "cadence sensor intermittent",
    }, TECH)

    assert safety["fault_class"] == "SAFETY_CRITICAL"
    assert safety["priority"] == "PRIORITY_SAFETY"
    assert cosmetic["fault_class"] == "COSMETIC"

    scheduled = validate_success(api_client.schedule_service_order(
        safety["id"], CREW_WINDOW, TECH), 200)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["part_id"] is None
    assert scheduled["safety_functions_maintained"] is True

    refused = api_client.schedule_service_order(cosmetic["id"], {
        "scheduled_start_at": "2026-09-08T13:00:00Z",
        "scheduled_end_at": "2026-09-08T15:00:00Z",
    }, TECH)
    assert refused.status_code == 409, refused.text
    assert refused.json()["data"]["error_id"] == "ERR_PART_REQUIRED_FOR_SCHEDULING"

    assert get_service_order(safety["id"])["safety_functions_maintained"] is True
    assert get_service_order(cosmetic["id"])["safety_functions_maintained"] is True


def test_an_empty_shelf_parks_only_the_cosmetic_fault():
    """PRD §3.6: "Parking for want of a part is impermissible for safety-critical
    faults, because the safety function must be restored regardless of parts
    availability."
    PRD §3.6: "When a cosmetic fault cannot be served because no part is available,
    the order does not stall in `DISPATCHED` — a rejected reservation attempt for a
    cosmetic fault parks it in `DISPATCH_PENDING_PART`, and the rejection surfaces as
    `ERR_PART_INSUFFICIENT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/service_order_scheduling_depends_on_service_order_fault_class
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    d_id = base["device_id"]

    empty = validate_success(api_client.create_part({
        "part_code": "TREAD-BELT-42",
        "compatible_sku": "TREAD",
        "safety_stock_qty": 2,
        "part_lot_key": "LOT-2026-09",
    }, ADMIN), 201)

    safety = create_service_order({
        "device_id": d_id, "reported_fault_code": "NO_POWER",
        "diagnosis_note": "dead unit",
    }, TECH)
    cosmetic = create_service_order({
        "device_id": d_id, "reported_fault_code": "SOFTWARE_CRASH",
        "diagnosis_note": "unit reboots under load",
    }, TECH)
    assert safety["fault_class"] == "SAFETY_CRITICAL"
    assert cosmetic["fault_class"] == "COSMETIC"

    # the cosmetic branch: no part available, so it parks and surfaces
    # ERR_PART_INSUFFICIENT
    refused = api_client.reserve_part(cosmetic["id"],
                                      {"part_id": empty["id"], "quantity": 1}, TECH)
    assert refused.status_code == 409, refused.text
    assert refused.json()["data"]["error_id"] == "ERR_PART_INSUFFICIENT"
    assert get_service_order(cosmetic["id"])["status"] == "DISPATCH_PENDING_PART"

    # the safety-critical branch: refused without a part, but it must NEVER park
    safety_refused = api_client.reserve_part(safety["id"],
                                             {"part_id": empty["id"], "quantity": 1}, TECH)
    assert safety_refused.status_code == 409, safety_refused.text
    assert get_service_order(safety["id"])["status"] == "DISPATCHED"

    parked = api_client.schedule_service_order(cosmetic["id"], {
        "scheduled_start_at": "2026-09-08T13:00:00Z",
        "scheduled_end_at": "2026-09-08T15:00:00Z",
    }, TECH)
    assert parked.status_code == 409, parked.text
    assert parked.json()["data"]["error_id"] == "ERR_PART_REQUIRED_FOR_SCHEDULING"

    restored = validate_success(api_client.schedule_service_order(
        safety["id"], CREW_WINDOW, TECH), 200)
    assert restored["status"] == "SCHEDULED"


def test_a_restricted_household_is_refused_on_the_purchase_gate():
    """PRD §3.2: "only after that gate clears is the purchase gate evaluated, and a
    membership in `RESTRICTED` or `FROZEN` posture causes the redemption to be
    refused with `ERR_PURCHASE_BLOCKED` (HTTP 409)."
    PRD §2.6: "`FROZEN` is selected when the membership status is `CANCELLED` or
    `TERMINATED`, or when any financing plan on the membership has reached
    `DEFAULTED`, or when the freeze reason is set. `RESTRICTED` is selected when the
    membership status is `PAUSED` or `DELINQUENT`, or when `unpaid_financing_count`
    is at least 1."

    Design: Difficulty/priority_pair_validation_conflict/redemptive_credit_priority_dispute_gate_beats_purchase_block
    """
    base = setup_delinquent_household()
    m_id = base["membership_id"]
    o_id = base["order_id"]

    order = get_order(o_id, m_id)
    assert order["refund_dispute_status"] == "NONE"
    assert get_membership(m_id)["posture"] == "RESTRICTED"

    res = api_client.redeem_refund(o_id, {
        "redeem_credit_cents": 25_000,
        "expected_membership_version": get_membership(m_id)["version"],
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_PURCHASE_BLOCKED"

    after = get_order(o_id, m_id)
    assert after["status"] == "DELIVERED"
    assert after["refund_dispute_status"] == "NONE"
