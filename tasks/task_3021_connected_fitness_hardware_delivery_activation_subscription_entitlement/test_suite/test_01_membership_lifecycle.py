"""Membership lifecycle: activation gating, pause/resume proration, cancellation
cascades and automatic termination."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_household_user,
    api_client,
    cancel_membership,
    create_membership,
    get_membership,
    link_device,
    membership_version,
    owner_headers,
    plus_days,
    set_clock,
    setup_active_membership,
    setup_member_users,
    setup_terminated_membership,
    validate_paginated,
    validate_success,
    verify_household_user,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
ANON = TEST_USERS["anonymous_headers"]


# =========================================================================
# Queue A — Difficulty instances
# =========================================================================

def test_pause_credit_rounds_up_and_cancel_from_active_rounds_down():
    """PRD §3.4: "On success `pause_started_at` is stamped from the logical clock,
    posture moves to `RESTRICTED`, every `ACTIVE` device is locked, and
    `accrued_pause_credit_cents` is banked by the unused-days variant of the
    proration: the exact number of days remaining until `paid_through_at` is
    measured, rounded *up* to the next whole day, capped at 30, divided by 30,
    multiplied by the household's `monthly_fee_cents` and rounded half up to whole
    cents."
    PRD §3.4: "From `ACTIVE`, the household's `accrued_pause_credit_cents` is
    recomputed on the remaining-days variant: the same leftover-day measurement,
    but rounded *down* rather than up, so the same membership evaluated on the same
    clock yields a strictly smaller credit than the pause basis produced."

    Design: Difficulty/dual_variant_calc/pause_credit_variants_diverge_for_one_partial_leftover_day
    """
    base_a = setup_active_membership(clock_utc="2026-09-01T00:00:00Z",
                                     household_name="Fernwood Household")
    base_b = setup_active_membership(clock_utc="2026-09-01T00:00:00Z",
                                     household_name="Larkspur Household",
                                     serial="TREAD-0002", crew="CREW-B")
    m_a = base_a["membership_id"]
    m_b = base_b["membership_id"]

    assert get_membership(m_a)["paid_through_at"] == "2026-10-01T00:00:00Z"
    assert get_membership(m_b)["paid_through_at"] == "2026-10-01T00:00:00Z"
    set_clock("2026-09-17T12:00:00Z")

    paused = validate_success(api_client.pause_membership(m_a, {
        "pause_start_at": "2026-09-17T12:00:00Z",
        "pause_end_at": "2026-10-01T12:00:00Z",
        "expected_membership_version": membership_version(m_a),
    }, owner_headers(m_a)), 200)

    cancelled = validate_success(api_client.cancel_membership(m_b, {
        "expected_membership_version": membership_version(m_b),
    }, owner_headers(m_b)), 200)

    assert paused["status"] == "PAUSED"
    assert paused["accrued_pause_credit_cents"] == 2800
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["accrued_pause_credit_cents"] == 2600

    # 2800 == round_half_up(6000 * ceil(13.5) / 30), 2600 == round_half_up(6000 * floor(13.5) / 30)
    assert paused["accrued_pause_credit_cents"] != cancelled["accrued_pause_credit_cents"]
    assert paused["pause_started_at"] == "2026-09-17T12:00:00Z"
    assert cancelled["pause_started_at"] is None


def test_pause_locks_every_device_and_resume_returns_the_credit_as_paid_through_time():
    """PRD §3.4: "On success `pause_started_at` is stamped from the logical clock,
    posture moves to `RESTRICTED`, every `ACTIVE` device is locked, and
    `accrued_pause_credit_cents` is banked by the unused-days variant of the
    proration: the exact number of days remaining until `paid_through_at` is
    measured, rounded *up* to the next whole day, capped at 30, divided by 30,
    multiplied by the household's `monthly_fee_cents` and rounded half up to whole
    cents."
    PRD §3.4: "On resume, `pause_started_at` is cleared, posture returns to `OPEN`,
    every locked device becomes `ACTIVE` with its latch cleared, and the credit is
    converted by dividing `accrued_pause_credit_cents` by `monthly_fee_cents`,
    multiplying by 30, flooring to whole days, and adding that many days to
    `paid_through_at`; the credit is then zeroed."

    Design: Difficulty/dual_variant_calc/pause_credit_variants_diverge_for_one_partial_leftover_day
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]
    d_id = base["device_id"]
    assert base["membership"]["status"] == "ACTIVE"

    set_clock("2026-09-17T12:00:00Z")
    paused = validate_success(api_client.pause_membership(m_id, {
        "pause_start_at": "2026-09-17T12:00:00Z",
        "pause_end_at": "2026-10-01T12:00:00Z",
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)

    assert paused["posture"] == "RESTRICTED"
    assert paused["accrued_pause_credit_cents"] == 2800
    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "LOCKED"
    assert device["entitlement_lock"] is True
    assert device["content_access_allowed"] is False

    resumed = validate_success(api_client.resume_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)

    assert resumed["status"] == "ACTIVE"
    assert resumed["posture"] == "OPEN"
    assert resumed["pause_started_at"] is None
    assert resumed["accrued_pause_credit_cents"] == 0
    # floor(2800 / 6000 * 30) == 14 whole days on top of the 1 October anchor
    assert resumed["paid_through_at"] == "2026-10-15T00:00:00Z"

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "ACTIVE"
    assert device["entitlement_lock"] is False
    assert device["content_access_allowed"] is True


def test_cancellation_locks_devices_and_suspends_every_counted_user():
    """PRD §3.4: "In both cases the membership becomes `CANCELLED`, posture
    recomputes to `FROZEN` with `attr_frozen_reason` null, every device in `ACTIVE`,
    `LINKED`, `DELIVERED` or `LOCKED` moves to `LOCKED` with its latch set, and every
    household user who is `ACTIVE` or `PENDING_VERIFICATION` becomes `SUSPENDED`
    with `suspended_reason` of `MEMBERSHIP_CANCELLED`."
    PRD §3.4: "From `ACTIVE`, the household's `accrued_pause_credit_cents` is
    recomputed on the remaining-days variant: the same leftover-day measurement,
    but rounded *down* rather than up, so the same membership evaluated on the same
    clock yields a strictly smaller credit than the pause basis produced."

    Design: Difficulty/transitive_cascade/membership_cancellation_cascade_propagates_two_hops_to_household_users
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]
    d_id = base["device_id"]
    extra = setup_member_users(m_id, 2, verified=True)

    set_clock("2026-09-17T12:00:00Z")
    cancelled = validate_success(api_client.cancel_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["posture"] == "FROZEN"
    assert cancelled["attr_frozen_reason"] is None
    assert cancelled["accrued_pause_credit_cents"] == 2600

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "LOCKED"
    assert device["entitlement_lock"] is True
    assert device["content_access_allowed"] is False

    for user_id in [base["owner"]["id"]] + [u["id"] for u in extra]:
        user = validate_success(api_client.get_household_user(user_id, owner_headers(m_id)), 200)
        assert user["status"] == "SUSPENDED"
        assert user["suspended_reason"] == "MEMBERSHIP_CANCELLED"

    after = get_membership(m_id)
    assert after["active_user_count"] == 0
    assert after["safety_gate_open"] is True

    rows, meta = validate_paginated(api_client.list_household_users(
        owner_headers(m_id), params={"membership_id": m_id, "status": "SUSPENDED"}))
    assert meta["total_count"] == 3
    assert len(rows) == 3


def test_activation_is_refused_while_the_device_is_still_only_delivered():
    """PRD §3.3: "Three conditions must hold. The membership must be `PROVISIONAL`;
    a second sequential activation observes `ACTIVE` and is refused by this same
    clause, surfacing as `ERR_INVALID_STATE` (HTTP 409). The household must have at
    least one user counting toward `active_user_count`, that is, at least one
    household user whose status is `ACTIVE` or `PENDING_VERIFICATION`. And at least
    one device whose `membership_id` matches the membership must have reached
    `LINKED` or `ACTIVE`, because activation requires a linked device."

    Design: Difficulty/cross_entity_state_dependency/membership_activation_depends_on_device_link_state
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False)
    m_id = base["membership_id"]
    d_id = base["device_id"]

    validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)
    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "DELIVERED"

    res = api_client.activate_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"
    assert get_membership(m_id)["status"] == "PROVISIONAL"


def test_linking_the_device_then_activating_flips_it_live_and_clears_the_latch():
    """PRD §3.3: "On success the membership becomes `ACTIVE`, its billing anchors are
    re-stamped to the logical clock and to thirty days beyond it, every `LINKED`
    device on the membership becomes `ACTIVE` with its `entitlement_lock` cleared,
    and the posture recomputes to `OPEN`."
    PRD §3.3: "The unit moves from `DELIVERED` to `LINKED`, its `membership_id` is
    set from the payload, and `activated_at` is stamped with the logical clock."

    Design: Difficulty/cross_entity_state_dependency/membership_activation_depends_on_device_link_state
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False)
    m_id = base["membership_id"]
    d_id = base["device_id"]

    validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)
    link_device(d_id, base["serial"], m_id)

    linked = validate_success(api_client.get_device(d_id, TECH), 200)
    assert linked["activation_status"] == "LINKED"
    assert linked["membership_id"] == m_id

    activated = validate_success(api_client.activate_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)

    assert activated["status"] == "ACTIVE"
    assert activated["posture"] == "OPEN"
    assert activated["billing_cycle_start_at"] == "2026-09-05T13:30:00Z"
    assert activated["paid_through_at"] == "2026-10-05T13:30:00Z"

    after = validate_success(api_client.get_device(d_id, TECH), 200)
    assert after["activation_status"] == "ACTIVE"
    assert after["entitlement_lock"] is False
    assert after["content_access_allowed"] is True


def test_financing_plan_loops_current_to_delinquent_and_back_on_catch_up():
    """PRD §3.5: "Recording a failed installment increments `retry_count` by one.
    While `retry_count` is below 3 the plan stays `CURRENT`; at `retry_count` of 3
    the plan crosses into `DELINQUENT` and `delinquency_count` is incremented by
    one. So the boundary is exact: two failures leave the plan current, and the
    third makes it delinquent."
    PRD §3.5: "A payment landing on a `DELINQUENT` plan returns it to `CURRENT`,
    increments `installments_paid`, increments `installments_late`, resets
    `retry_count` to zero, and recomputes the parent's `unpaid_financing_count`;
    when that count falls to zero and the membership is `DELINQUENT`, the membership
    cascades back to `ACTIVE` with posture recomputed to `OPEN`."

    Design: Difficulty/non_linear_state_machine/financing_plan_delinquency_cycles_back_to_current
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 119_900,
        "term_months": 12,
        "apr_bps": 900,
    }, owner_headers(m_id)), 201)
    validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)

    first = validate_success(api_client.fail_installment(plan["id"], {}, ADMIN), 200)
    second = validate_success(api_client.fail_installment(plan["id"], {}, ADMIN), 200)
    third = validate_success(api_client.fail_installment(plan["id"], {}, ADMIN), 200)

    assert first["status"] == "CURRENT" and first["retry_count"] == 1
    assert second["status"] == "CURRENT" and second["retry_count"] == 2
    assert third["status"] == "DELINQUENT" and third["delinquency_count"] == 1

    membership = get_membership(m_id)
    assert membership["unpaid_financing_count"] == 1
    assert membership["status"] == "DELINQUENT"
    assert membership["posture"] == "RESTRICTED"

    cured = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert cured["status"] == "CURRENT"
    assert cured["installments_late"] == 1
    assert cured["retry_count"] == 0

    membership = get_membership(m_id)
    assert membership["status"] == "ACTIVE"
    assert membership["posture"] == "OPEN"
    assert membership["unpaid_financing_count"] == 0

    # the cycle repeats: a second full triplet crosses the boundary again
    for _ in range(3):
        repeated = validate_success(api_client.fail_installment(plan["id"], {}, ADMIN), 200)
    assert repeated["status"] == "DELINQUENT"
    assert repeated["delinquency_count"] == 2
    assert repeated["safety_disable_latched"] is False
    assert get_membership(m_id)["safety_gate_open"] is True
    assert get_membership(m_id)["attr_frozen_reason"] is None


def test_delinquency_restricts_the_household_without_touching_content_or_safety():
    """PRD §3.5: "When that count reaches at least one and the membership is still
    `ACTIVE`, the membership itself cascades to `DELINQUENT` and its posture
    recomputes to `RESTRICTED`."
    PRD §2.6: "`RESTRICTED` blocks the creation of new hardware orders and new
    financing plans but leaves content streaming fully enabled — restriction is not
    a lockout."
    PRD §2.7: "The membership carries `safety_gate_open`, which is true while
    hardware safety functions remain enabled and which no delinquency or financing
    state may ever clear."

    Design: Difficulty/non_linear_state_machine/financing_plan_delinquency_cycles_back_to_current
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 119_900,
        "term_months": 12,
        "apr_bps": 900,
    }, owner_headers(m_id)), 201)
    validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    for _ in range(3):
        validate_success(api_client.fail_installment(plan["id"], {}, ADMIN), 200)

    membership = get_membership(m_id)
    assert membership["status"] == "DELINQUENT"
    assert membership["posture"] == "RESTRICTED"
    assert membership["unpaid_financing_count"] == 1
    assert membership["safety_gate_open"] is True
    assert membership["attr_frozen_reason"] is None

    device = validate_success(api_client.get_device(base["device_id"], TECH), 200)
    assert device["content_access_allowed"] is True
    assert device["entitlement_lock"] is False

    plan_after = validate_success(api_client.get_financing_plan(plan["id"], owner_headers(m_id)), 200)
    assert plan_after["safety_disable_latched"] is False


def test_first_installment_absorbs_the_whole_remainder():
    """PRD §3.5: "That total is divided by the term to produce a base installment,
    floored to whole cents, and the remainder — the total less the base multiplied
    by the term — is computed separately. The very first installment is the base
    plus the entire remainder; every subsequent installment is the base alone."

    Design: Difficulty/combinatorial_formula/installment_ceil_first_installment_then_floor_rest_amortizes_exactly
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 119_900,
        "term_months": 12,
        "apr_bps": 900,
    }, owner_headers(m_id)), 201)

    # total due = round_half_up(119900 * 1.09) = 130691; base = floor(130691/12) = 10890
    # remainder = 130691 - 12 * 10890 = 11, so the first installment is 10901
    assert plan["monthly_installment_cents"] == 10901
    assert plan["status"] == "ORIGINATED"
    assert plan["safety_disable_latched"] is False

    first = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert first["installments_paid"] == 1
    assert first["status"] == "CURRENT"

    second = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert second["installments_paid"] == 2


def test_rolling_correction_unwinds_the_most_recent_installment():
    """PRD §3.5: "A platform administrator may apply a rolling correction to a
    `CURRENT` plan, which decrements `installments_paid` by one — removing the most
    recent successful installment from the schedule — and rebases
    `monthly_installment_cents` on the reduced paid count."

    Design: Difficulty/combinatorial_formula/installment_ceil_first_installment_then_floor_rest_amortizes_exactly
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    m_id = base["membership_id"]

    plan = validate_success(api_client.create_financing_plan({
        "membership_id": m_id,
        "order_id": base["order_id"],
        "principal_cents": 119_900,
        "term_months": 12,
        "apr_bps": 900,
    }, owner_headers(m_id)), 201)
    assert plan["monthly_installment_cents"] == 10901

    validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    paid = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert paid["installments_paid"] == 2

    corrected = validate_success(
        api_client.rolling_correction(plan["id"], {}, ADMIN), 200)
    assert corrected["installments_paid"] == 1

    again = validate_success(api_client.pay_installment(plan["id"], {}, owner_headers(m_id)), 200)
    assert again["installments_paid"] == 2


def test_closing_a_visit_delivers_the_device_and_recaptures_the_order():
    """PRD §3.2: "The physical unit moves from `UNASSIGNED` to `DELIVERED`, its
    `provenance_source` is stamped `NEW_SALE`, its `activated_at` is set to the
    logical clock, and its `warranty_expires_at` is set exactly 365 days beyond that
    instant."
    PRD §3.2: "The parent order moves from `DELIVERY_SCHEDULED` to `DELIVERED`, and
    it is here — and only here — that the chronological variant of the order total
    runs: the order's `delivery_fee_cents` is written from the delivery charge for
    the actual zone, and its `captured_total_cents` is written on the same pinned
    pre-finance basis used at order time, now with a non-zero delivery component."

    Design: Difficulty/transitive_cascade/delivery_completion_cascades_three_hops_and_creates_a_service_order
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", zone="RURAL",
                                   crew="CREW-R", complete=False,
                                   financing_method="FULL_PAYMENT")
    d_id = base["device_id"]

    done = validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)
    assert done["status"] == "COMPLETED"

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "DELIVERED"
    assert device["provenance_source"] == "NEW_SALE"
    assert device["warranty_expires_at"] == "2027-09-05T13:30:00Z"

    order = validate_success(
        api_client.get_hardware_order(base["order_id"], owner_headers(base["membership_id"])), 200)
    assert order["status"] == "DELIVERED"
    # RURAL TREAD: min(3 * 3000, 3000 + 2 * 900) == 4800
    assert order["delivery_fee_cents"] == 4800
    assert order["captured_total_cents"] == 300_800
    assert order["finance_charge_cents"] == 0


def test_a_damaged_grade_synthesises_a_safety_critical_service_order():
    """PRD §3.2: "When the recorded grade is `DAMAGED`, the platform automatically
    opens a service order against the delivered device with `reported_fault_code` of
    `FRAME_CRACK`."
    PRD §3.6: "The `fault_class` is `SAFETY_CRITICAL` when the reported code is
    `NO_POWER` or `FRAME_CRACK`, and `COSMETIC` for every other code. Its `priority`
    is `PRIORITY_SAFETY` for any safety-critical fault."

    Design: Difficulty/transitive_cascade/delivery_completion_cascades_three_hops_and_creates_a_service_order
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", zone="RURAL",
                                   crew="CREW-R", complete=False)
    d_id = base["device_id"]

    done = validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "DAMAGED"}, TECH), 200)
    assert done["status"] == "COMPLETED"
    assert done["completion_grade"] == "DAMAGED"

    rows, meta = validate_paginated(
        api_client.list_service_orders(TECH, params={"device_id": d_id}))
    assert meta["total_count"] == 1
    seeded = rows[0]
    assert seeded["reported_fault_code"] == "FRAME_CRACK"
    assert seeded["fault_class"] == "SAFETY_CRITICAL"
    assert seeded["priority"] == "PRIORITY_SAFETY"


# =========================================================================
# Queue B — Corner instances
# =========================================================================

def test_membership_starts_provisional_with_the_tier_stream_default():
    """PRD §2.4: "A new membership is `PROVISIONAL` with posture `OPEN`, an
    `active_user_count` of zero, an open `safety_gate_open` flag, and billing anchors
    already stamped: `billing_cycle_start_at` is set to the current logical clock and
    `paid_through_at` is set 30 days beyond it."
    PRD §2.5: "Its resolution is: when the membership's `concurrent_limit_override`
    is non-null, that override is the effective limit; otherwise the plan-tier
    default applies, which is 4 streams for `PLUS` and 10 streams for `BUSINESS`."

    Design: Corner/entities/membership_create_defaults_the_concurrent_override_and_starts_provisional
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()

    assert membership["status"] == "PROVISIONAL"
    assert membership["posture"] == "OPEN"
    assert membership["concurrent_limit_override"] is None
    assert membership["concurrent_limit_effective"] == 4
    assert membership["active_user_count"] == 0
    assert membership["safety_gate_open"] is True
    assert membership["billing_cycle_start_at"] == "2026-09-01T00:00:00Z"
    assert membership["paid_through_at"] == "2026-10-01T00:00:00Z"


def test_membership_summary_resolves_the_override_as_the_effective_limit():
    """PRD §2.5: "Its resolution is: when the membership's `concurrent_limit_override`
    is non-null, that override is the effective limit; otherwise the plan-tier
    default applies, which is 4 streams for `PLUS` and 10 streams for `BUSINESS`."

    Design: Corner/entities/membership_summary_omits_fields_that_are_not_declared_reads
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership(concurrent_limit_override=2)
    m_id = membership["id"]

    summary = validate_success(api_client.get_membership_summary(m_id, owner_headers(m_id)), 200)

    assert summary["concurrent_limit_override"] == 2
    assert summary["concurrent_limit_effective"] == 2
    assert summary["total_streams_observed"] == 0
    assert summary["unpaid_financing_count"] == 0
    assert summary["attr_frozen_reason"] is None
    assert summary["household_name"] == membership["household_name"]

    read = get_membership(m_id)
    assert read["concurrent_limit_effective"] == summary["concurrent_limit_effective"]
    assert read["posture"] == summary["posture"]


def test_second_owner_on_a_membership_is_refused():
    """PRD §2.4: "Exactly one `OWNER` may exist per membership at any time; an
    attempt to add a second owner is refused with `ERR_OWNER_ALREADY_EXISTS`."

    Design: Corner/errors/second_owner_on_a_membership_returns_owner_already_exists
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]
    owner = add_household_user(m_id, display_name="Ada Fernwood", email="ada@x.com",
                               role="OWNER")

    res = api_client.create_household_user(m_id, {
        "display_name": "Bea Fernwood",
        "email": "bea@x.com",
        "role": "OWNER",
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_OWNER_ALREADY_EXISTS"

    rows, meta = validate_paginated(
        api_client.list_membership_household_users(m_id, owner_headers(m_id)))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == owner["id"]
    assert get_membership(m_id)["active_user_count"] == 1


def test_verifying_with_a_wrong_token_leaves_the_user_pending():
    """PRD §2.4: "The token is consumed later by a verification request that
    supplies `verification_token`; that step sets `verified` to true and moves
    `status` to `ACTIVE`."
    PRD §2.4: "Until verification lands, the user nonetheless counts toward the
    household's `active_user_count`, because the count deliberately includes both
    `ACTIVE` and `PENDING_VERIFICATION` members."

    Design: Corner/state_machines/household_user_verify_with_a_wrong_token_leaves_the_pending_state
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]
    owner = add_household_user(m_id, display_name="Ada Fernwood", email="ada@x.com",
                               role="OWNER", verify=False)

    res = api_client.verify_household_user(
        owner["id"], {"verification_token": "not-the-token"}, ANON)
    assert res.status_code >= 400, res.text

    still = validate_success(api_client.get_household_user(owner["id"], owner_headers(m_id)), 200)
    assert still["status"] == "PENDING_VERIFICATION"
    assert still["verified"] is False
    assert get_membership(m_id)["active_user_count"] == 1

    verified = verify_household_user(owner["id"], owner["verification_token"])
    assert verified["status"] == "ACTIVE"
    assert verified["verified"] is True


def test_resuming_an_active_membership_is_refused_without_moving_the_pause_ledger():
    """PRD §3.4: "A `MembershipOwner` resumes a `PAUSED` membership with the
    caller's `expected_membership_version`, requiring that the membership is
    `PAUSED`, that `unpaid_financing_count` is zero, and that the household still
    has at least one user counting toward `active_user_count`."

    Design: Corner/state_machines/membership_resume_from_active_returns_invalid_state
    """
    base = setup_active_membership()
    m_id = base["membership_id"]
    d_id = base["device_id"]
    before = get_membership(m_id)

    res = api_client.resume_membership(m_id, {
        "expected_membership_version": before["version"],
    }, owner_headers(m_id))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"

    after = get_membership(m_id)
    assert after["status"] == "ACTIVE"
    assert after["pause_started_at"] is None
    assert after["accrued_pause_credit_cents"] == 0

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "ACTIVE"
    assert device["entitlement_lock"] is False


def test_cancelled_membership_survives_until_the_grace_period_is_exceeded():
    """PRD §3.4: "A `CANCELLED` membership whose billing anchor has gone more than
    180 days stale terminates: it becomes `TERMINATED`, every device on it becomes
    `DECOMMISSIONED` with `content_access_allowed` false and `total_workouts` frozen
    at its current value, every `SUSPENDED` household user becomes `REMOVED`, and
    posture recomputes to `FROZEN`."

    Design: Corner/state_machines/cancelled_membership_terminates_and_decommissions_devices_via_ops_sweep
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]
    d_id = base["device_id"]

    cancel_membership(m_id)
    set_clock("2026-12-01T12:00:00Z")
    validate_success(api_client.run_ops({}, ADMIN), 200)
    assert get_membership(m_id)["status"] == "CANCELLED"

    set_clock(plus_days("2026-09-01T00:00:00Z", 181))
    sweep = validate_success(api_client.run_ops({}, ADMIN), 200)
    assert sweep["terminated_memberships"] == 1

    membership = get_membership(m_id)
    assert membership["status"] == "TERMINATED"
    assert membership["posture"] == "FROZEN"

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "DECOMMISSIONED"
    assert device["entitlement_lock"] is True
    assert device["content_access_allowed"] is False
    assert device["total_workouts"] == 0

    owner = validate_success(
        api_client.get_household_user(base["owner"]["id"], owner_headers(m_id)), 200)
    assert owner["status"] == "REMOVED"


def test_terminated_membership_refuses_further_lifecycle_actions():
    """PRD §3.4: "`TERMINATED` is the membership's terminal state, and any further
    lifecycle action against it is refused with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/sold_refurb_batch_rejects_a_second_sell
    """
    base = setup_terminated_membership()
    m_id = base["membership_id"]
    assert get_membership(m_id)["status"] == "TERMINATED"

    for action in ("activate", "resume", "cancel", "reactivate"):
        payload = {"expected_membership_version": membership_version(m_id)}
        res = getattr(api_client, f"{action}_membership")(m_id, payload, owner_headers(m_id))
        assert res.status_code == 409, f"{action} -> {res.status_code}: {res.text}"
        assert res.json()["data"]["error_id"] == "ERR_ALREADY_TERMINAL"


def test_repair_cannot_be_scheduled_on_a_decommissioned_device():
    """PRD §3.6: "Repair may not be scheduled for a device that has been
    decommissioned; such a request is refused with `ERR_DISPATCH_DEVICE_NOT_OPERATIONAL`
    (HTTP 409)."

    Design: Corner/errors/scheduling_a_repair_on_a_decommissioned_device_returns_not_operational
    """
    base = setup_terminated_membership()
    d_id = base["device_id"]
    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "DECOMMISSIONED"

    part = validate_success(api_client.create_part({
        "part_code": "TREAD-BELT-42",
        "compatible_sku": "TREAD",
        "safety_stock_qty": 2,
        "part_lot_key": "LOT-2026-09",
    }, ADMIN), 201)
    validate_success(api_client.restock_part(part["id"], {"quantity": 4}, ADMIN), 200)

    service_order = validate_success(api_client.create_service_order({
        "device_id": d_id,
        "reported_fault_code": "NO_POWER",
        "diagnosis_note": "unit decommissioned by the ops sweep",
    }, TECH), 201)
    # reserve so the order is otherwise schedulable: only the decommission
    # clause can refuse the booking
    validate_success(api_client.reserve_part(
        service_order["id"], {"part_id": part["id"], "quantity": 1}, TECH), 200)

    res = api_client.schedule_service_order(service_order["id"], {
        "scheduled_start_at": "2027-03-05T09:00:00Z",
        "scheduled_end_at": "2027-03-05T11:00:00Z",
    }, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_DISPATCH_DEVICE_NOT_OPERATIONAL"

    after = validate_success(api_client.get_service_order(service_order["id"], TECH), 200)
    assert after["status"] == "PART_RESERVED"
    assert after["safety_functions_maintained"] is True


def test_cascade_suspension_is_readable_immediately_from_the_sibling_read():
    """PRD §2.4: "When a user is suspended the platform records why in
    `suspended_reason`, one of `EVICTED_BY_CONCURRENCY`, `MEMBERSHIP_CANCELLED` or
    `REACTIVATION_UNPAID`."
    PRD §2.6: "Posture is recomputed on every mutation that touches membership
    state, whether directly on the membership or on any of its devices, household
    users, financing plans or class enrollments."

    Design: Corner/consistency_model/membership_household_users_view_without_inflight_cancellation
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]
    set_clock("2026-09-17T12:00:00Z")

    cancelled = validate_success(api_client.cancel_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)
    assert cancelled["posture"] == "FROZEN"
    assert cancelled["accrued_pause_credit_cents"] == 2600

    rows, meta = validate_paginated(api_client.list_household_users(
        owner_headers(m_id), params={"membership_id": m_id, "status": "SUSPENDED"}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["status"] == "SUSPENDED"
    assert rows[0]["suspended_reason"] == "MEMBERSHIP_CANCELLED"

    assert get_membership(m_id)["active_user_count"] == 0

def test_reactivation_reverses_the_cancellation_cascade_on_both_hops():
    """PRD §3.4: "On success the billing anchors are re-stamped thirty days forward
    from the logical clock, any banked pause credit is consumed and zeroed, posture
    recomputes to `OPEN`, every locked device becomes `ACTIVE` with its latch
    cleared, and every household user suspended for `MEMBERSHIP_CANCELLED` becomes
    `ACTIVE` with `suspended_reason` cleared."
    PRD §3.4: "The membership lands in `REACTIVATED`, a transient waypoint rather
    than a resting state: on the next system step it settles automatically into
    `ACTIVE` with posture recomputed to `OPEN`."

    Design: Difficulty/transitive_cascade/membership_cancellation_cascade_propagates_two_hops_to_household_users
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z")
    m_id = base["membership_id"]
    d_id = base["device_id"]
    extra = setup_member_users(m_id, 2, verified=True)

    set_clock("2026-09-17T12:00:00Z")
    cancelled = validate_success(api_client.cancel_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_membership(m_id)["active_user_count"] == 0

    reactivated = validate_success(api_client.reactivate_membership(m_id, {
        "expected_membership_version": membership_version(m_id),
    }, owner_headers(m_id)), 200)

    assert reactivated["status"] in ("REACTIVATED", "ACTIVE")
    assert reactivated["posture"] == "OPEN"
    assert reactivated["accrued_pause_credit_cents"] == 0
    assert reactivated["billing_cycle_start_at"] == "2026-09-17T12:00:00Z"
    assert reactivated["paid_through_at"] == "2026-10-17T12:00:00Z"

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["activation_status"] == "ACTIVE"
    assert device["entitlement_lock"] is False
    assert device["content_access_allowed"] is True

    for user_id in [base["owner"]["id"]] + [u["id"] for u in extra]:
        user = validate_success(api_client.get_household_user(user_id, owner_headers(m_id)), 200)
        assert user["status"] == "ACTIVE"
        assert user["suspended_reason"] is None

    assert get_membership(m_id)["active_user_count"] == 3
    assert get_membership(m_id)["safety_gate_open"] is True
