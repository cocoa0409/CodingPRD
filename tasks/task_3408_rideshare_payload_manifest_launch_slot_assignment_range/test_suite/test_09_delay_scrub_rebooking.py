"""Delay and scrub cascades, rebooking rights and fees, contract OCC, and the
clock-driven expiry sweep."""
from test_helpers import (
    ApiErrorId,
    assert_delay_event,
    assert_same_instant,
    confirm_assignment,
    create_assignment,
    create_customer,
    create_granted_customer_license,
    create_mission,
    create_port,
    create_range_slot,
    create_signed_contract,
    delay_mission,
    get_assignment,
    get_contract,
    get_mission,
    lock_manifest,
    mission_version,
    payload_entry,
    publish_exclusion_window,
    rebook_contract,
    rebook_payload,
    reserve_slot,
    review_assignment,
    set_clock,
    setup_locked_mission,
    setup_provisional_assignments,
    setup_range_scheduled_mission,
    sign_contract,
    transition_license,
    validate_error,
    validate_success,
    verify_assignment,
    api_client,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers

MOPS = TEST_USERS["mission_ops_headers"]
REG = TEST_USERS["regulator_headers"]
RO = TEST_USERS["range_officer_headers"]

DELAY_OPEN = "2026-11-01T00:00:00Z"
DELAY_CLOSE = "2026-11-10T00:00:00Z"


def _setup_delay_safe_range_scheduled():
    """RANGE_SCHEDULED mission whose contract window [2026-10-01, 2026-11-30]
    still covers the delay target [2026-11-01, 2026-11-10]."""
    return setup_range_scheduled_mission(
        contract_overrides={"window_close_utc": "2026-11-30T00:00:00Z"}
    )


def test_delay_regresses_range_scheduled_mission_to_manifest_locked(api):
    """PRD §3.7: "If the mission stood in `RANGE_SCHEDULED`, the containment
    test decides the slot's fate: when the `CONFIRMED` slot no longer contains
    the new window — containment requiring the slot's `window_open_utc` on or
    before the new open and the slot's `window_close_utc` on or after the new
    close — the slot is released to `RELEASED`, `slot_released` is recorded
    true, and the mission drops back from `RANGE_SCHEDULED` to
    `MANIFEST_LOCKED`, that automatic hop incrementing the mission's `version`
    again."

    Design: Difficulty/non_linear_state_machine/mission_cycles_range_scheduled_back_to_manifest_locked_on_delay
    """
    ctx = _setup_delay_safe_range_scheduled()
    event = delay_mission(ctx["mission"]["id"], reason_code="RANGE_CONFLICT")
    assert_delay_event(event)
    assert event["slot_released"] is True
    assert event["assignments_removed_count"] == 0, (
        "contract window 2026-11-30 still covers the new window"
    )
    mission = get_mission(ctx["mission"]["id"])
    assert mission["status"] == "MANIFEST_LOCKED", "regressed from RANGE_SCHEDULED"
    assert_same_instant(mission["window_open_utc"], DELAY_OPEN)
    assert_same_instant(mission["window_close_utc"], DELAY_CLOSE)


def test_delay_with_contained_contract_releases_slot_but_keeps_assignment(api):
    """PRD §3.7: "Contracts whose window still covers the new mission window
    are untouched."
    PRD §3.7: "A slot that still contains the new window is never released by a
    delay" — and its complement, a slot that no longer contains the new window,
    "is released to `RELEASED`".

    Design: Difficulty/non_linear_state_machine/mission_cycles_range_scheduled_back_to_manifest_locked_on_delay
    """
    ctx = _setup_delay_safe_range_scheduled()
    delay_mission(ctx["mission"]["id"], reason_code="RANGE_CONFLICT")
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RELEASED"
    assert get_assignment(ctx["assignments"][0]["id"])["status"] == "INTEGRATED", (
        "the cascade did not touch the covered contract's assignment"
    )


def test_delay_cascade_releases_slot_and_counts_removals(api):
    """PRD §3.7: "The sweep visits every contract whose `target_mission_id`
    names this mission or that holds a live assignment on it; a contract whose
    `window_close_utc` falls before the new mission `window_close_utc` is
    impacted. For each impacted contract, every live assignment of its payloads
    on this mission moves to `REMOVED` — each removal running the full release
    cascade of §3.3 — and once its last live assignment has left, the contract
    falls back from `MANIFESTED` to `SIGNED` with `rebook_eligible` set true."
    PRD §3.7: "`assignments_removed_count` records how many assignments the
    cascade removed, and the mission's commitment fields are recomputed once
    the sweep completes."

    Design: Difficulty/transitive_cascade/delay_cascade_releases_slot_removes_assignments_flags_contracts
    """
    ctx = setup_range_scheduled_mission()  # contract window close 2026-10-31
    event = delay_mission(ctx["mission"]["id"], reason_code="VEHICLE_STACKING")
    assert_delay_event(event)
    assert event["slot_released"] is True
    assert event["assignments_removed_count"] == 1, (
        "contract window 2026-10-31 < new close 2026-11-10: the contract is impacted"
    )
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RELEASED"
    mission = get_mission(ctx["mission"]["id"])
    assert mission["status"] == "MANIFEST_LOCKED"
    assert mission["committed_mass_kg"] == 0 and mission["firm_mass_kg"] == 0, (
        "hop 4: commitment recomputed after the removal sweep"
    )


def test_delay_cascade_reverts_payload_and_flags_contract(api):
    """PRD §3.7: "For each impacted contract, every live assignment of its
    payloads on this mission moves to `REMOVED` — each removal running the full
    release cascade of §3.3 — and once its last live assignment has left, the
    contract falls back from `MANIFESTED` to `SIGNED` with `rebook_eligible`
    set true."
    PRD §3.3: "Removal releases capacity: the mission's commitment fields are
    recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a
    version increment"

    Design: Difficulty/transitive_cascade/delay_cascade_releases_slot_removes_assignments_flags_contracts
    """
    ctx = setup_range_scheduled_mission()
    delay_mission(ctx["mission"]["id"], reason_code="VEHICLE_STACKING")
    assert get_assignment(ctx["assignments"][0]["id"])["status"] == "REMOVED", (
        "hop 3: INTEGRATED assignment removed by the cascade"
    )
    payloads = validate_success(
        api_client.list_contract_payloads(ctx["contract"]["id"], MOPS), 200
    )
    assert payloads[0]["status"] == "REGISTERED"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SIGNED"
    assert contract["rebook_eligible"] is True
    assert contract["rebookings_remaining"] == 1, (
        "the cascade only flags; the free right is untouched"
    )


def _setup_range_scheduled_with_blocking_second_slot():
    """Mission-1 RANGE_SCHEDULED (contract window covers the delay target);
    mission-2's slot S2 [2026-10-20T00:30, 2026-10-22] on CCAFS sits 30 minutes
    after S1's close — inside the 45-minute turnaround buffer."""
    ctx = setup_range_scheduled_mission(
        contract_overrides={"window_close_utc": "2026-11-30T00:00:00Z"}
    )
    m2 = create_mission(
        mission_name="Transporter-X6",
        window_open_utc="2026-10-20T00:00:00Z",
        window_close_utc="2026-10-25T00:00:00Z",
        mass_capacity_kg=50,
        volume_capacity_m3=1.0,
    )
    s2 = create_range_slot(
        m2["id"], range_code="CCAFS",
        window_open_utc="2026-10-20T00:30:00Z",
        window_close_utc="2026-10-22T00:00:00Z",
    )
    return ctx, s2


def test_confirmed_slot_blocks_next_operator_until_delay_releases_it(api):
    """PRD §3.5: "Reserving a `REQUESTED` slot moves it to `RESERVED` only if it
    clears the turnaround buffer against every other slot on the same
    `range_code` that stands in `RESERVED` or `CONFIRMED`"
    PRD §3.7: "when the `CONFIRMED` slot no longer contains the new window —
    containment requiring the slot's `window_open_utc` on or before the new open
    and the slot's `window_close_utc` on or after the new close — the slot is
    released to `RELEASED`, `slot_released` is recorded true"

    Design: Difficulty/compensating_invariant/confirm_then_delay_releases_range_capacity_for_next_operator
    """
    ctx, s2 = _setup_range_scheduled_with_blocking_second_slot()
    blocked = api_client.reserve_range_slot(s2["id"], RO)
    validate_error(blocked, ApiErrorId.ERR_RANGE_WINDOW_CONFLICT)

    event = delay_mission(ctx["mission"]["id"], reason_code="RANGE_CONFLICT")
    assert event["slot_released"] is True
    assert event["assignments_removed_count"] == 0, "selective cascade: covered contract untouched"
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RELEASED", "compensating action freed the range"
    assert get_assignment(ctx["assignments"][0]["id"])["status"] == "INTEGRATED"


def test_range_capacity_freed_by_delay_accepts_next_operator(api):
    """PRD §3.5: "Slots in `REQUESTED`, `RELEASED`, or `CONSUMED` never
    participate in the conflict check."

    Design: Difficulty/compensating_invariant/confirm_then_delay_releases_range_capacity_for_next_operator
    """
    ctx, s2 = _setup_range_scheduled_with_blocking_second_slot()
    blocked = api_client.reserve_range_slot(s2["id"], RO)
    validate_error(blocked, ApiErrorId.ERR_RANGE_WINDOW_CONFLICT)

    delay_mission(ctx["mission"]["id"], reason_code="RANGE_CONFLICT")
    reserved = reserve_slot(s2["id"])
    assert reserved["status"] == "RESERVED", (
        "the RELEASED slot no longer participates; the range occupation count returns to one"
    )


def test_scrub_releases_slot_reverts_contract_and_locks_terminal(api):
    """PRD §3.7: "Every assignment in `PROVISIONAL`, `CONFIRMED`, or
    `INTEGRATED` moves to `REMOVED`; each payload returns to `REGISTERED`; and
    each contract left with no remaining live assignments while standing in
    `MANIFESTED` returns to `SIGNED` with `rebook_eligible` set true. From
    `RANGE_SCHEDULED`, the mission's `RESERVED` or `CONFIRMED` slot is released
    to `RELEASED`. The mission's commitment fields are recomputed — all zero
    once the sweep completes."
    PRD §3.8: "`COMPLETED` and `SCRUBBED` are the mission's terminal states."

    Design: Corner/state_machines/scrub_releases_slot_reverts_contract_and_locks_terminal
    """
    ctx = setup_range_scheduled_mission()
    resp = api_client.scrub_mission(ctx["mission"]["id"], "VEHICLE_GROUNDED", MOPS)
    scrubbed = validate_success(resp, 200)
    assert scrubbed["status"] == "SCRUBBED"

    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RELEASED"
    assert get_assignment(ctx["assignments"][0]["id"])["status"] == "REMOVED"
    payloads = validate_success(
        api_client.list_contract_payloads(ctx["contract"]["id"], MOPS), 200
    )
    assert payloads[0]["status"] == "REGISTERED"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SIGNED" and contract["rebook_eligible"] is True
    assert get_mission(ctx["mission"]["id"])["committed_mass_kg"] == 0

    late = api_client.delay_mission(
        ctx["mission"]["id"],
        {"new_window_open_utc": DELAY_OPEN, "new_window_close_utc": DELAY_CLOSE,
         "reason_code": "TOO_LATE"},
        MOPS,
    )
    validate_error(late, ApiErrorId.ERR_INVALID_STATE)


def test_delay_to_non_later_window_rejected(api):
    """PRD §3.7: "The new open must be strictly after the mission's current
    `window_open_utc` — a sideways or backward move is rejected with
    `ERR_DELAY_REGRESSION` (HTTP 422) — and the new close must be strictly after
    the new open."

    Design: Corner/errors/delay_to_non_later_window_rejected
    """
    ctx = setup_locked_mission()
    resp = api_client.delay_mission(
        ctx["mission"]["id"],
        {"new_window_open_utc": "2026-10-10T00:00:00Z",
         "new_window_close_utc": "2026-10-22T00:00:00Z",
         "reason_code": "NOT_REALLY_LATER"},
        MOPS,
    )
    validate_error(resp, ApiErrorId.ERR_DELAY_REGRESSION)
    mission = get_mission(ctx["mission"]["id"])
    assert_same_instant(mission["window_open_utc"], "2026-10-10T00:00:00Z")
    assert_same_instant(mission["window_close_utc"], "2026-10-20T00:00:00Z")
    events = validate_success(
        api_client.list_mission_delay_events(ctx["mission"]["id"], MOPS), 200
    )
    assert events == [], "a rejected delay records no DelayEvent"


def test_delay_flagged_rebooking_charges_no_fee_and_keeps_rights(api):
    """PRD §3.7: "The fee depends on which of three doors stands open, checked
    in this order. If `rebook_eligible` is true, the rebooking is free: no fee
    is charged, `rebookings_remaining` is left unchanged, and the flag is
    cleared to false."

    Design: Corner/calculations/delay_flagged_rebooking_charges_no_fee_and_keeps_rights
    """
    ctx = setup_range_scheduled_mission()  # contract window [10-01, 10-31]
    delay_mission(ctx["mission"]["id"], reason_code="VEHICLE_STACKING")
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SIGNED" and contract["rebook_eligible"] is True

    m2 = create_mission(
        mission_name="Transporter-D4",
        window_open_utc="2026-10-25T00:00:00Z",
        window_close_utc="2026-10-28T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    after = rebook_contract(
        contract["id"], ctx["customer"]["id"], m2["id"], contract["version"]
    )
    assert after["total_rebooking_fees_cents"] == 0, (
        "the eligibility waiver fires, not the 50% near-bracket"
    )
    assert after["rebookings_remaining"] == 1, "the right is NOT consumed"
    assert after["rebook_eligible"] is False, "the flag is cleared by use"
    assert after["target_mission_id"] == m2["id"]
    assert after["status"] == "SIGNED"


def test_rebook_of_manifested_contract_rejected(api):
    """PRD §3.7: "The contract must stand in `SIGNED` and the target mission
    must be `MANIFEST_OPEN`, else `ERR_REBOOKING_NOT_ELIGIBLE` (HTTP 409)"

    Design: Corner/errors/rebook_of_manifested_contract_rejected
    """
    ctx = setup_provisional_assignments()
    m2 = create_mission(
        mission_name="Transporter-B2",
        window_open_utc="2026-10-16T00:00:00Z",
        window_close_utc="2026-10-26T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "MANIFESTED"
    resp = api_client.rebook_contract(
        contract["id"],
        rebook_payload(m2["id"], contract["version"]),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REBOOKING_NOT_ELIGIBLE)
    after = get_contract(contract["id"])
    assert after["target_mission_id"] is None
    assert after["rebookings_remaining"] == 1


def test_occ_stale_contract_version_rejected_on_rebook(api):
    """PRD §2.8: "Rebooking a contract requires the non-optional field
    `expected_contract_version`, carrying the client's last observed `version`
    of the contract. A mismatch with the contract's current `version` is
    rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), protecting the
    client's view of `rebookings_remaining` and accumulated fees."

    Design: Corner/complexity_layers/occ_stale_contract_version_rejected_on_rebook
    """
    set_clock()
    customer = create_customer()
    m2 = create_mission(
        mission_name="Transporter-B2",
        window_open_utc="2026-10-16T00:00:00Z",
        window_close_utc="2026-10-26T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    m3 = create_mission(
        mission_name="Transporter-C3",
        window_open_utc="2026-10-20T00:00:00Z",
        window_close_utc="2026-10-30T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    contract, _ = create_signed_contract(customer["id"], [payload_entry()])
    v_signed = contract["version"]

    first = rebook_contract(contract["id"], customer["id"], m2["id"], v_signed)
    assert first["target_mission_id"] == m2["id"]

    stale = api_client.rebook_contract(
        contract["id"],
        rebook_payload(m3["id"], v_signed),
        make_customer_headers(customer["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    after = get_contract(contract["id"])
    assert after["target_mission_id"] == m2["id"], "the losing rebook changed nothing"
    assert after["rebookings_remaining"] == 0, "the right was consumed exactly once"


def test_expiry_sweep_on_clock_set_expires_contract_and_license(api):
    """PRD §3.9: "Each contract still in `SIGNED` whose `window_close_utc` lies
    before the current logical time moves to `EXPIRED`, with `rebook_eligible`
    cleared to false and its `version` incremented. Each license still in
    `GRANTED` whose `valid_until` lies before the current logical time moves to
    `EXPIRED` with its `version` incremented and — in deliberate contrast to
    revocation — no assignment cascade. Contracts in `DRAFT`, `MANIFESTED`, or
    `FULFILLED` are never swept, and neither are licenses in `SUBMITTED`,
    `DENIED`, or `REVOKED`."

    Design: Corner/complexity_layers/expiry_sweep_on_clock_set_expires_contract_and_license
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port = create_port(mission["id"])
    ctx_x, _ = create_signed_contract(
        customer["id"],
        [payload_entry(payload_name="PLX", mass_kg=50, volume_m3=1.0,
                       interface_class="CUBESAT")],
    )
    contract, payloads = create_signed_contract(customer["id"], [payload_entry()])
    lic = create_granted_customer_license(
        customer["id"], valid_until="2026-10-15T00:00:00Z"
    )
    a1 = create_assignment(mission["id"], payloads[0]["id"], port["id"])

    set_clock("2026-11-01T00:00:00Z")

    expired = get_contract(ctx_x["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["rebook_eligible"] is False

    manifested = get_contract(contract["id"])
    assert manifested["status"] == "MANIFESTED", "MANIFESTED contracts are never swept"

    license_after = validate_success(api_client.get_license(lic["id"], REG), 200)
    assert license_after["status"] == "EXPIRED"

    assert get_assignment(a1["id"])["status"] == "PROVISIONAL", (
        "expiry does NOT cascade; only REVOKED does"
    )
    assert get_mission(mission["id"])["committed_mass_kg"] == 100
