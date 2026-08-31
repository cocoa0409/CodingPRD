"""The lockbox cycle: intake, assignment, placement, removal, return and retirement."""

from test_helpers import (
    ApiErrorId,
    create_listing,
    enroll_member,
    intake_lockbox,
    lockbox_action,
    place_lockbox,
    placement_payload,
    read_association,
    read_lockbox,
    read_placement,
    register_association,
    remove_placement,
    setup_assigned_box,
    setup_placed_box,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, close_listing, make_member_headers, withdraw_listing


def test_freshly_intaken_lockbox_cannot_be_placed_before_assignment(api, admin_headers):
    """PRD §2.6: "First, when a placement is being created the *addressed* entity for the
    transition check at step 9 is the lockbox, not the listing: a unit sitting in
    `IN_STOCK`, `MISSING`, `QUARANTINE` or `RETIRED` fails there with `ERR_INVALID_STATE`,
    whereas a unit that is already `PLACED` passes step 9 and is instead caught later at
    step 16 with `ERR_PLACEMENT_ALREADY_ACTIVE`."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC
    timestamps with three fractional-second digits, and `version`, an integer that begins at
    1 when the resource is created and increases by exactly 1 on every mutation the server
    accepts."

    Design: Corner/state_machines/lockbox_starts_in_stock_and_first_assign_is_the_only_legal_move
    """
    association = register_association()
    agent = enroll_member(association["id"])
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    listing = create_listing(association["id"], agent["id"])

    stored = read_lockbox(lockbox["id"])
    assert stored["status"] == "IN_STOCK"
    assert stored["version"] == 1

    # An AssociationAdmin places the box: PRD §2.1 exempts administrators from every
    # ownership check, so the ladder reaches the step-9 transition check on the lockbox
    # instead of stopping at step 6 for a box whose assigned_member_id is still empty.
    response = api.create_placement(
        placement_payload(lockbox["id"], listing["id"]), admin_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    rows, _ = validate_paginated(
        api.list_placements(admin_headers, params={"lockbox_id": lockbox["id"]})
    )
    assert rows == []


def test_retired_lockbox_refuses_further_assignment(api, admin_headers):
    """PRD §2.6: "Terminal lockdown at step 11 means that a `Lockbox` in `RETIRED`, a
    `Listing` in `CLOSED` or `WITHDRAWN`, a `LockboxPlacement` in `REMOVED`, an
    `AccessCredential` in `REVOKED` or `EXPIRED`, an `AccessGrant` in `DENIED`, `REVOKED`,
    `EXPIRED` or `CONSUMED`, a `ShowingAppointment` in `COMPLETED`, `CANCELLED` or
    `NO_SHOW`, a `BillingCharge` in `PAID`, `WAIVED` or `VOID`, and a `Member` in
    `TERMINATED` accept no further action of any kind."
    PRD §3.7: "A box in `IN_STOCK`, `MISSING` or `QUARANTINE` may be retired, which clears
    `assigned_member_id`, lowers `lockbox_total_count` by one and is terminal."

    Design: Corner/state_machines/retired_lockbox_terminal_lockdown_rejects_assign
    """
    association = register_association()
    agent = enroll_member(association["id"])
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    retired = lockbox_action(lockbox["id"], "RETIRE")
    assert retired["status"] == "RETIRED"

    response = api.lockbox_state(
        lockbox["id"],
        {
            "action": "ASSIGN",
            "member_id": agent["id"],
            "expected_lockbox_version": retired["version"],
        },
        admin_headers,
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ENTITY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert response.status_code == 409

    stored = read_lockbox(lockbox["id"])
    assert stored["status"] == "RETIRED"
    assert stored.get("assigned_member_id") is None

    association_state = read_association(association["id"])
    assert association_state["lockbox_total_count"] == 0
    assert association_state["unplaced_inventory_count"] == 0


def test_recover_on_a_box_that_was_never_missing_is_refused(api, admin_headers):
    """PRD §3.7: "Recovery is administrator-only, and it may only be requested while the
    box is actually `MISSING`; asking to recover a box in any other state is
    `ERR_RECOVERY_WINDOW_CLOSED`."

    Design: Corner/state_machines/lockbox_recover_from_non_missing_state_closes_recovery_window
    """
    ctx = setup_assigned_box()
    assigned = read_lockbox(ctx["lockbox_id"])

    response = api.lockbox_state(
        ctx["lockbox_id"],
        {"action": "RECOVER", "expected_lockbox_version": assigned["version"]},
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_RECOVERY_WINDOW_CLOSED.value)

    stored = read_lockbox(ctx["lockbox_id"])
    assert stored["status"] == "ASSIGNED"
    assert stored["version"] == 2


def test_lockbox_serves_two_listings_in_sequence_then_returns_to_stock(api, admin_headers):
    """PRD §3.4: "Removal writes `removed_at` at the current logical clock and drives the
    box `PLACED → ASSIGNED` with `current_listing_id` cleared, returning one unit to
    `unplaced_inventory_count` and lowering `active_placement_count` by one;
    `delinquent_placement_count`, `recovery_rate_pct` and `posture` are all recomputed."
    PRD §3.4: "Returning a box moves it from `ASSIGNED` back to `IN_STOCK`, clears
    `assigned_member_id`, and lowers `boxes_in_field_count` by one; it is refused unless no
    placement for that box is currently in `PLACED`, `REMOVAL_DUE` or `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/lockbox_place_remove_replace_return_cycle
    """
    ctx = setup_placed_box()
    remove_placement(ctx["placement_id"], ctx["agent_id"])

    second_listing = create_listing(
        ctx["association_id"],
        ctx["agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )
    second_placement = place_lockbox(
        ctx["lockbox_id"], second_listing["id"], ctx["agent_id"]
    )
    remove_placement(second_placement["id"], ctx["agent_id"])

    returned = lockbox_action(ctx["lockbox_id"], "RETURN")
    assert returned["status"] == "IN_STOCK"

    first = read_placement(ctx["placement_id"])
    second = read_placement(second_placement["id"])
    assert first["placement_status"] == "REMOVED"
    assert first["listing_id"] == ctx["listing_id"]
    assert second["placement_status"] == "REMOVED"
    assert second["listing_id"] == second_listing["id"]

    rows, _ = validate_paginated(
        api.list_placements(admin_headers, params={"lockbox_id": ctx["lockbox_id"]})
    )
    assert len(rows) == 2, "one physical unit produced two removed placement rows"


def test_returned_lockbox_clears_holder_and_listing_and_restores_stock(api, admin_headers):
    """PRD §3.4: "Returning a box moves it from `ASSIGNED` back to `IN_STOCK`, clears
    `assigned_member_id`, and lowers `boxes_in_field_count` by one; it is refused unless no
    placement for that box is currently in `PLACED`, `REMOVAL_DUE` or `DELINQUENT`."
    PRD §3.1: "The `unplaced_inventory_count` is the number in `IN_STOCK` or `ASSIGNED` —
    the pool of hardware the association can still deploy."

    Design: Difficulty/non_linear_state_machine/lockbox_place_remove_replace_return_cycle
    """
    ctx = setup_placed_box()
    remove_placement(ctx["placement_id"], ctx["agent_id"])
    second_listing = create_listing(
        ctx["association_id"],
        ctx["agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )
    second_placement = place_lockbox(
        ctx["lockbox_id"], second_listing["id"], ctx["agent_id"]
    )
    remove_placement(second_placement["id"], ctx["agent_id"])
    lockbox_action(ctx["lockbox_id"], "RETURN")

    stored = read_lockbox(ctx["lockbox_id"])
    assert stored["status"] == "IN_STOCK"
    assert stored.get("assigned_member_id") is None
    assert stored.get("current_listing_id") is None

    association = read_association(ctx["association_id"])
    assert association["unplaced_inventory_count"] == 1
    assert association["boxes_in_field_count"] == 0


def test_placing_a_box_removes_one_unit_from_unplaced_inventory(api, admin_headers):
    """PRD §3.4: "The association's `unplaced_inventory_count` falls by one,
    `active_placement_count` rises by one, and `posture` is recomputed."
    PRD §3.1: "The `unplaced_inventory_count` is the number in `IN_STOCK` or `ASSIGNED` —
    the pool of hardware the association can still deploy."

    Design: Difficulty/compensating_invariant/place_then_remove_conserves_unplaced_inventory_count
    """
    ctx = setup_assigned_box()
    for serial in ("LB-0002", "LB-0003"):
        intake_lockbox(
            ctx["association_id"],
            serial_number=serial,
            model="LB_STD",
            replacement_cost_cents=9000,
        )
    listing = create_listing(ctx["association_id"], ctx["agent_id"])

    before = read_association(ctx["association_id"])
    assert before["unplaced_inventory_count"] == 3
    assert before["boxes_in_field_count"] == 1

    place_lockbox(ctx["lockbox_id"], listing["id"], ctx["agent_id"])

    during = read_association(ctx["association_id"])
    assert during["unplaced_inventory_count"] == 2
    assert during["active_placement_count"] == 1


def test_removing_the_placement_returns_exactly_one_unit_to_inventory(api, admin_headers):
    """PRD §2.9: "What compensation does **not** do is equally load-bearing: revoked grants
    and cancelled showings are never resurrected, and the association's
    `unplaced_inventory_count` is conserved across the place-and-remove cycle — a placement
    removes one unit from unplaced inventory and its removal returns exactly one."

    Design: Difficulty/compensating_invariant/place_then_remove_conserves_unplaced_inventory_count
    """
    ctx = setup_assigned_box()
    for serial in ("LB-0002", "LB-0003"):
        intake_lockbox(
            ctx["association_id"],
            serial_number=serial,
            model="LB_STD",
            replacement_cost_cents=9000,
        )
    listing = create_listing(ctx["association_id"], ctx["agent_id"])
    placement = place_lockbox(ctx["lockbox_id"], listing["id"], ctx["agent_id"])
    remove_placement(placement["id"], ctx["agent_id"])

    after = read_association(ctx["association_id"])
    assert after["unplaced_inventory_count"] == 3
    assert after["boxes_in_field_count"] == 1
    assert after["active_placement_count"] == 0

    in_stock, _ = validate_paginated(
        api.list_lockboxes(
            admin_headers,
            params={"association_id": ctx["association_id"], "status": "IN_STOCK"},
        )
    )
    assigned, _ = validate_paginated(
        api.list_lockboxes(
            admin_headers,
            params={"association_id": ctx["association_id"], "status": "ASSIGNED"},
        )
    )
    assert len(in_stock) == 2
    assert len(assigned) == 1


def test_listing_close_sets_removal_deadline_from_close_date_plus_grace(api, admin_headers):
    """PRD §3.4: "The placement on that listing sitting in `PLACED` moves to
    `REMOVAL_DUE`, and its `removal_deadline` is computed as `close_date` advanced by the
    association's `removal_grace_days` whole days, taken at `00:00:00.000Z` on the resulting
    day."
    PRD §3.4: "Neither constrains the other: a placement can be `DELINQUENT` with
    `billing_status` still `NONE` — that is the missing-box path, where a replacement charge
    is raised instead of a late-removal charge — and a placement can be `REMOVED` with
    `billing_status` still `ACCRUED`, because retrieving the box late does not undo a penalty
    already accrued."

    Design: Corner/state_machines/listing_close_sets_removal_deadline_from_close_date_plus_grace
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    closed = close_listing(
        ctx["listing_id"], ctx["agent_id"], "2026-08-10", clock="2026-08-10T00:00:00Z"
    )

    assert closed["status"] == "CLOSED"
    assert closed["close_date"] == "2026-08-10"

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "REMOVAL_DUE"
    assert placement["removal_deadline"] == "2026-08-13T00:00:00.000Z"
    assert placement["billing_status"] == "NONE"
    assert placement.get("removed_at") is None

    assert read_lockbox(ctx["lockbox_id"])["status"] == "PLACED"


def test_listing_withdraw_anchors_removal_deadline_on_the_clock_date(api, admin_headers):
    """PRD §3.4: "Withdrawal behaves identically — a listing in `ACTIVE` or
    `UNDER_CONTRACT` may move to `WITHDRAWN`, running exactly the same three hops — with one
    difference: because no deal closed, the `removal_deadline` is anchored on the calendar
    date of the current logical clock advanced by `removal_grace_days` whole days, again at
    `00:00:00.000Z`."

    Design: Corner/state_machines/listing_withdraw_derives_removal_deadline_from_clock_date
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    withdrawn = withdraw_listing(
        ctx["listing_id"], ctx["agent_id"], clock="2026-08-08T00:00:00Z"
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn.get("close_date") is None

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "REMOVAL_DUE"
    assert placement["removal_deadline"] == "2026-08-11T00:00:00.000Z"


def test_member_cannot_be_terminated_while_holding_hardware(api, admin_headers):
    """PRD §3.2: "A member in `ACTIVE`, `PROBATION`, `SUSPENDED` or `EXPIRED` may be moved
    to `TERMINATED`, but only if they are holding no hardware — no lockbox may name them in
    `assigned_member_id` while sitting in `ASSIGNED`, `PLACED` or `MISSING`."
    PRD §2.6: "**Declared transition exists** (priority 40) — the addressed entity's current
    state admits the requested action, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/member_terminate_blocked_while_still_holding_a_lockbox
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    member = validate_success(api.get_member(ctx["agent_id"], admin_headers))

    response = api.member_event(
        ctx["agent_id"],
        {
            "event_type": "TERMINATE",
            "reason": "Left the industry",
            "expected_member_version": member["version"],
        },
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    still_active = validate_success(api.get_member(ctx["agent_id"], admin_headers))
    assert still_active["membership_status"] == "ACTIVE"

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "ASSIGNED"
    assert lockbox["assigned_member_id"] == ctx["agent_id"]
