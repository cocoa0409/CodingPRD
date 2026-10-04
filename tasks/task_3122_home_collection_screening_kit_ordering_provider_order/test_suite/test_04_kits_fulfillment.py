"""Kit fulfillment: creation (OCC + exclusivity + state gating), shipping,
reminder cadence, returns, and abandonment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_kit_for,
    create_kit_payload,
    create_order,
    get_kit,
    get_order,
    get_success_data,
    setup_eligible_order,
    setup_kit_ordered,
    setup_kit_returned,
    setup_kit_shipped,
    setup_resulted,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
FA = TEST_USERS["fulfillment_agent_headers"]


# ---------------------------------------------------------------------------
# Kit creation: OCC (queue B cross_cutting) + exclusivity (queue A overlap)
# ---------------------------------------------------------------------------

def test_occ_stale_version_on_second_kit_creation(api):
    """PRD §2.7: "A kit-creation request must carry `expected_order_version`,
    a non-optional field holding the `version` of the `ScreeningOrder` as the
    client last observed it. If another writer has advanced the order's
    version since that observation — for example, by creating a replacement
    kit that legitimately consumed the order's single outstanding-kit slot —
    the client's view is stale, and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    PRD §2.9: "then state-machine preconditions on the addressed resource,
    then the optimistic-concurrency version check where one applies".

    Both the state precondition (order no longer `ELIGIBLE` after the first
    kit creation) and the OCC version check fail on the replayed request;
    PRD names both error_ids for this operation without further resolving
    the race, so either earliest-failure reading is accepted.

    Design: Corner/cross_cutting_layers/occ_stale_version_on_kit_creation
    """
    ctx = setup_eligible_order()
    observed_version = ctx["order"]["version"]
    validate_success(
        api.create_kit(ctx["order"]["id"], create_kit_payload(observed_version), FA),
        expected_status=201,
    )
    # Second attempt with the same (now stale) observed version.
    resp = api.create_kit(ctx["order"]["id"], create_kit_payload(observed_version), FA)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_ORDER_INVALID_STATE]
    )

    kits, _ = validate_paginated(api.list_order_kits(ctx["order"]["id"], PA))
    assert len(kits) == 1


def test_occ_stale_version_explicitly_behind_current(api):
    """PRD §2.7: "If another writer has advanced the order's version since
    that observation — for example, by creating a replacement kit that
    legitimately consumed the order's single outstanding-kit slot — the
    client's view is stale, and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    The order is still in `ELIGIBLE`, so the state precondition holds and
    only the OCC version check can reject.

    Design: Corner/cross_cutting_layers/occ_stale_version_on_kit_creation
    """
    ctx = setup_eligible_order()
    stale_version = ctx["order"]["version"] - 1  # version observed before confirm
    resp = api.create_kit(ctx["order"]["id"], create_kit_payload(stale_version), FA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_order(ctx["order"]["id"])["status"] == "ELIGIBLE"


def test_in_flight_order_mutual_exclusion_rejects_second_kit(api):
    """PRD §3.4: "A further exclusivity rule applies: no other
    `ScreeningOrder` for the same patient may currently sit in any of
    `ELIGIBLE`, `KIT_ORDERED`, `KIT_SHIPPED`, `KIT_RETURNED`, `IN_LAB`, or
    `RECOLLECTION_REQUESTED` — if one does, creation is rejected with
    `ERR_ACTIVE_ORDER_EXISTS` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/in_flight_order_mutual_exclusion_per_patient
    """
    ctx = setup_kit_shipped()
    # Second order for the same patient, confirmed ELIGIBLE.
    order2 = create_order(ctx["patient"], ctx["provider"])
    order2 = validate_success(api.confirm_eligibility(order2["id"], PA))

    resp = api.create_kit(order2["id"], create_kit_payload(order2["version"]), FA)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_ORDER_EXISTS)


def test_in_flight_order_mutual_exclusion_preserves_second_order(api):
    """PRD §3.4: "A further exclusivity rule applies: no other
    `ScreeningOrder` for the same patient may currently sit in any of
    `ELIGIBLE`, `KIT_ORDERED`, `KIT_SHIPPED`, `KIT_RETURNED`, `IN_LAB`, or
    `RECOLLECTION_REQUESTED` — if one does, creation is rejected with
    `ERR_ACTIVE_ORDER_EXISTS` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/in_flight_order_mutual_exclusion_per_patient
    """
    ctx = setup_kit_shipped()
    order2 = create_order(ctx["patient"], ctx["provider"])
    order2 = validate_success(api.confirm_eligibility(order2["id"], PA))

    resp = api.create_kit(order2["id"], create_kit_payload(order2["version"]), FA)
    assert resp.status_code == 409
    after = get_order(order2["id"])
    assert after["status"] == "ELIGIBLE"
    assert after["version"] == order2["version"]


# ---------------------------------------------------------------------------
# Kit creation gating on parent order state (queue A cross-entity dep)
# ---------------------------------------------------------------------------

def test_kit_creation_on_cancelled_order_rejected(api):
    """PRD §3.4: "Once an order is `ELIGIBLE`, a `FulfillmentAgent` creates
    its kit. The request carries `expected_order_version` per the
    optimistic-concurrency rule of §2.7, and the order's state must be
    `ELIGIBLE` (else `ERR_ORDER_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/kit_ship_requires_order_in_kit_ordered
    """
    ctx = setup_eligible_order()
    validate_success(api.cancel_order(ctx["order"]["id"], PA))
    current = get_order(ctx["order"]["id"])

    resp = api.create_kit(ctx["order"]["id"], create_kit_payload(current["version"]), FA)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)


def test_kit_creation_on_cancelled_order_creates_no_kit(api):
    """PRD §3.4: "Once an order is `ELIGIBLE`, a `FulfillmentAgent` creates
    its kit. The request carries `expected_order_version` per the
    optimistic-concurrency rule of §2.7, and the order's state must be
    `ELIGIBLE` (else `ERR_ORDER_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/kit_ship_requires_order_in_kit_ordered
    """
    ctx = setup_eligible_order()
    validate_success(api.cancel_order(ctx["order"]["id"], PA))
    current = get_order(ctx["order"]["id"])

    validate_error(
        api.create_kit(ctx["order"]["id"], create_kit_payload(current["version"]), FA),
        ApiErrorId.ERR_ORDER_INVALID_STATE,
    )
    kits, _ = validate_paginated(api.list_order_kits(ctx["order"]["id"], PA))
    assert kits == []


# ---------------------------------------------------------------------------
# Shipping: cadence creation, ship state gating, abandonment
# ---------------------------------------------------------------------------

def test_ship_immediately_visible_on_order_read(api):
    """PRD §3.4: "Shipping stamps `shipped_at` on both kit and order with the
    logical clock's current instant, moves the kit `ORDERED → SHIPPED` and
    the order `KIT_ORDERED → KIT_SHIPPED`, computes the order's
    `abandonment_due_at` as the date 45 days after the ship date, and creates
    the reminder cadence: exactly three `Reminder` rows with `sequence_no` 1,
    2, and 3, whose `scheduled_for` dates are 7, 14, and 28 days respectively
    after the ship date."

    Design: Corner/consistency_model/immediate_visibility_of_transition_effects
    """
    set_clock()
    ctx = setup_kit_ordered()
    kit = validate_success(api.ship_kit(ctx["kit"]["id"], FA))
    assert kit["status"] == "SHIPPED"
    assert kit["shipped_at"] is not None
    assert str(kit["shipped_at"])[:10] == "2026-09-01"

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "KIT_SHIPPED"
    # Ship date 2026-09-01 + 45 days == 2026-10-16.
    assert str(order["abandonment_due_at"])[:10] == "2026-10-16"

    reminders, _ = validate_paginated(api.list_order_reminders(order["id"], PA))
    by_seq = {r["sequence_no"]: r for r in reminders}
    assert set(by_seq) == {1, 2, 3}
    assert str(by_seq[1]["scheduled_for"])[:10] == "2026-09-08"
    assert str(by_seq[2]["scheduled_for"])[:10] == "2026-09-15"
    assert str(by_seq[3]["scheduled_for"])[:10] == "2026-09-29"
    assert all(r["status"] == "SCHEDULED" for r in reminders)
    assert all(r.get("sent_at") is None for r in reminders)


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "The `version` is an integer that increments by exactly 1 on
    every mutation of that resource."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    set_clock()
    ctx = setup_eligible_order()
    assert ctx["order"]["version"] == 2  # create (1) + confirm (+1)

    kit = create_kit_for(ctx["order"])
    assert get_order(ctx["order"]["id"])["version"] == 3

    validate_success(api.ship_kit(kit["id"], FA))
    assert get_order(ctx["order"]["id"])["version"] == 4

    validate_success(api.return_kit(kit["id"], FA))
    assert get_order(ctx["order"]["id"])["version"] == 5


def test_ship_from_returned_kit_rejected_invalid_state(api):
    """PRD §3.4: "The kit must be in `ORDERED` status (else
    `ERR_KIT_INVALID_STATE`) and its parent order must be in `KIT_ORDERED`
    (else `ERR_ORDER_INVALID_STATE`)."

    Design: Corner/state_machines/ship_from_returned_kit_rejected_invalid_state
    """
    ctx = setup_kit_returned()
    resp = api.ship_kit(ctx["kit"]["id"], FA)
    validate_error(resp, ApiErrorId.ERR_KIT_INVALID_STATE)
    assert get_kit(ctx["kit"]["id"])["status"] == "RETURNED"


def test_return_before_due_skips_scheduled_reminders(api):
    """PRD §3.4: "The order moves `KIT_SHIPPED → KIT_RETURNED` with its own
    `returned_at` stamped, every still-`SCHEDULED` reminder on the order
    flips to `SKIPPED`, and the order's `version` increments."

    Design: Corner/state_machines/return_before_due_skips_scheduled_reminders
    """
    set_clock()
    ctx = setup_kit_shipped()
    set_clock("2026-09-03T00:00:00Z")  # before the first reminder (2026-09-08)
    validate_success(api.return_kit(ctx["kit"]["id"], FA))

    reminders, _ = validate_paginated(api.list_order_reminders(ctx["order"]["id"], PA))
    assert len(reminders) == 3
    assert all(r["status"] == "SKIPPED" for r in reminders)
    by_seq = {r["sequence_no"]: r for r in reminders}
    assert str(by_seq[1]["scheduled_for"])[:10] == "2026-09-08"
    assert str(by_seq[2]["scheduled_for"])[:10] == "2026-09-15"
    assert str(by_seq[3]["scheduled_for"])[:10] == "2026-09-29"


def test_reminder_partial_dispatch_chronological(api):
    """PRD §3.4: "Dispatch requires the order to be in `KIT_SHIPPED` (else
    `ERR_ORDER_INVALID_STATE`) and releases every reminder for that order
    whose `scheduled_for` date has been reached by the current logical date;
    each released reminder is stamped with `sent_at` and moves
    `SCHEDULED → SENT`."

    Design: Corner/calculations/reminder_cadence_partial_dispatch_chronological
    """
    set_clock()
    ctx = setup_kit_shipped()
    set_clock("2026-09-10T00:00:00Z")  # only reminder 1 (2026-09-08) is due

    dispatched = validate_success(api.dispatch_reminders(ctx["order"]["id"], PA))
    assert isinstance(dispatched, list)
    assert len(dispatched) == 1
    assert dispatched[0]["sequence_no"] == 1
    assert dispatched[0]["status"] == "SENT"
    assert dispatched[0].get("sent_at")

    reminders, _ = validate_paginated(api.list_order_reminders(ctx["order"]["id"], PA))
    by_seq = {r["sequence_no"]: r for r in reminders}
    assert by_seq[1]["status"] == "SENT"
    assert by_seq[2]["status"] == "SCHEDULED"
    assert by_seq[3]["status"] == "SCHEDULED"
    assert str(by_seq[2]["scheduled_for"])[:10] == "2026-09-15"
    assert str(by_seq[3]["scheduled_for"])[:10] == "2026-09-29"


# ---------------------------------------------------------------------------
# Abandonment cascade (queue A transitive_cascade)
# ---------------------------------------------------------------------------

def _setup_shipped_then_advance_to(iso):
    set_clock()
    ctx = setup_kit_shipped()
    set_clock(iso)
    return ctx


def test_abandonment_flips_order_kit_and_reminders(api):
    """PRD §3.7: "An order sitting in `KIT_SHIPPED` whose `abandonment_due_at`
    date has been reached or passed transitions `KIT_SHIPPED → ABANDONED`:
    the outstanding kit moves to `EXPIRED_STABILIZATION`, every
    still-`SCHEDULED` reminder moves to `SKIPPED`, and the order's `version`
    increments."

    Design: Difficulty/transitive_cascade/abandonment_cascade_depth2
    """
    # Ship on 2026-09-01; abandonment_due_at == 2026-10-16 (ship date + 45 days).
    ctx = _setup_shipped_then_advance_to("2026-10-16T00:00:00Z")

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "ABANDONED"
    assert get_kit(ctx["kit"]["id"])["status"] == "EXPIRED_STABILIZATION"

    reminders, _ = validate_paginated(api.list_order_reminders(order["id"], PA))
    assert len(reminders) == 3
    assert all(r["status"] == "SKIPPED" for r in reminders)


def test_abandonment_increments_order_version(api):
    """PRD §3.7: "An order sitting in `KIT_SHIPPED` whose `abandonment_due_at`
    date has been reached or passed transitions `KIT_SHIPPED → ABANDONED`:
    the outstanding kit moves to `EXPIRED_STABILIZATION`, every
    still-`SCHEDULED` reminder moves to `SKIPPED`, and the order's `version`
    increments."

    Design: Difficulty/transitive_cascade/abandonment_cascade_depth2
    """
    ctx = _setup_shipped_then_advance_to("2026-10-16T00:00:00Z")
    order = get_order(ctx["order"]["id"])
    # create(1) + confirm + kit + ship + abandonment = 5
    assert order["version"] == 5
    assert order["status"] == "ABANDONED"


# ---------------------------------------------------------------------------
# SLA computed read
# ---------------------------------------------------------------------------

def test_sla_variants_diverge_on_unreturned_order(api):
    """PRD §3.4: "When the kit has not been returned, the provisional variant
    counts days from the ship date to the current logical date, while the
    return-logistics variant — the one used for adherence reporting — counts
    the full 45-day abandonment allowance regardless of how much time has
    actually elapsed."

    Design: Difficulty/dual_variant_calc/sla_provisional_vs_return_logistics_on_abandoned_order
    """
    set_clock()
    ctx = setup_kit_shipped()
    set_clock("2026-10-15T00:00:00Z")  # ship date + 44 days, one before due

    data = validate_success(api.get_order_sla(ctx["order"]["id"], PA))
    assert data["provisional_days"] == 44
    assert data["return_logistics_days"] == 45


def test_sla_variants_order_still_shipped_day_before_abandonment(api):
    """PRD §3.4: "computes the order's `abandonment_due_at` as the date 45
    days after the ship date".
    PRD §3.7: "An order sitting in `KIT_SHIPPED` whose `abandonment_due_at`
    date has been reached or passed transitions `KIT_SHIPPED → ABANDONED`".

    Design: Difficulty/dual_variant_calc/sla_provisional_vs_return_logistics_on_abandoned_order
    """
    set_clock()
    ctx = setup_kit_shipped()
    set_clock("2026-10-15T00:00:00Z")  # one day before abandonment_due_at

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "KIT_SHIPPED"
    data = validate_success(api.get_order_sla(order["id"], PA))
    assert data["provisional_days"] == 44
    assert data["return_logistics_days"] == 45


def test_sla_variants_agree_on_returned_order(api):
    """PRD §3.4: "When the order's `returned_at` is set, both variants agree:
    each is the number of days from the ship date to the return date."

    Design: Corner/calculations/sla_precision_on_returned_order
    """
    set_clock()
    ctx = setup_kit_shipped()
    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.return_kit(ctx["kit"]["id"], FA))

    data = validate_success(api.get_order_sla(ctx["order"]["id"], PA))
    assert data["provisional_days"] == 5
    assert data["return_logistics_days"] == 5


def test_clock_default_provisional_sla_zero_on_ship_day(api):
    """PRD §2.5: "At startup the logical clock reads 2026-09-01T00:00:00Z".
    PRD §3.4: "When the kit has not been returned, the provisional variant
    counts days from the ship date to the current logical date".

    Design: Corner/endpoints/clock_default_before_any_set
    """
    # No clock-set call: the server starts at 2026-09-01T00:00:00Z.
    ctx = setup_kit_shipped()
    data = validate_success(api.get_order_sla(ctx["order"]["id"], PA))
    assert data["provisional_days"] == 0


# ---------------------------------------------------------------------------
# Cancel lockdown
# ---------------------------------------------------------------------------

def test_cancel_from_terminal_resulted_rejected(api):
    """PRD §3.3: "Cancellation is available to a `Provider` or `ProgramAdmin`
    while the order sits in `PENDING_ELIGIBILITY` or `ELIGIBLE`. From either
    state the order moves to `CANCELLED` with a `version` increment; a cancel
    attempted from any other state is rejected with
    `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409)."

    Design: Corner/state_machines/cancel_from_terminal_resulted_rejected
    """
    ctx = setup_resulted("NEGATIVE")
    resp = api.cancel_order(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
    assert get_order(ctx["order"]["id"])["status"] == "RESULTED"
