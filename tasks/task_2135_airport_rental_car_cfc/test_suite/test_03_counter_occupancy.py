"""Occupying counter and ready-return space over half-open intervals."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_counter_assignment,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _space_and_agreement(api, space_label="T1-A02"):
    scenario = fx.setup_active_agreement(api)
    scenario["space"] = fx.create_counter_space(
        api, scenario["facility"]["id"], space_label=space_label
    )
    return scenario


def test_adjacent_counter_window_is_accepted(api):
    """PRD §3.3: "Exclusive occupancy comes last of the three: the reservation is rejected
    with `ERR_COUNTER_SPACE_OCCUPIED` (HTTP 409) when some existing assignment on the same
    `counter_space_id`, whose status is `ALLOCATED` or `ACTIVE`, satisfies both halves of the
    half-open overlap test — the new start date is strictly earlier than the existing end
    date, and the existing start date is strictly earlier than the new end date."
    PRD §3.3: "Because both comparisons are strict, a new window whose start date equals an
    existing window's end date does not collide, and back-to-back tenancies on a single
    counter are legal."

    Design: Difficulty/resource_temporal_overlap/counter_space_half_open_interval_permits_adjacency_rejects_overlap
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    fx.create_counter_assignment(
        api,
        agreement_id,
        space_id,
        operator,
        effective_start_date="2026-01-01",
        effective_end_date="2026-04-01",
    )

    version = fx.read_agreement_version(api, agreement_id, operator)
    response = api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id,
            space_id,
            version,
            effective_start_date="2026-04-01",
            effective_end_date="2026-07-01",
        ),
        operator,
    )
    adjacent = validate_success(response, 201)

    assert_counter_assignment(adjacent)
    assert adjacent["status"] == "ALLOCATED", (
        "a window starting on the incumbent's end date does not collide"
    )
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["assignment_count"] == 2
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 2


def test_overlapping_counter_window_is_rejected(api):
    """PRD §3.3: "Exclusive occupancy comes last of the three: the reservation is rejected
    with `ERR_COUNTER_SPACE_OCCUPIED` (HTTP 409) when some existing assignment on the same
    `counter_space_id`, whose status is `ALLOCATED` or `ACTIVE`, satisfies both halves of the
    half-open overlap test — the new start date is strictly earlier than the existing end
    date, and the existing start date is strictly earlier than the new end date."
    PRD §2.3: "Counter assignments filter on `agreement_id`, `counter_space_id` and `status`."

    Design: Difficulty/resource_temporal_overlap/counter_space_half_open_interval_permits_adjacency_rejects_overlap
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-01-01", effective_end_date="2026-04-01",
    )
    fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-04-01", effective_end_date="2026-07-01",
    )

    version = fx.read_agreement_version(api, agreement_id, operator)
    response = api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id,
            space_id,
            version,
            effective_start_date="2026-03-31",
            effective_end_date="2026-06-30",
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_SPACE_OCCUPIED.value, 409)
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["assignment_count"] == 2, "the collided create must add no assignment"
    _rows, meta = validate_paginated(
        api.list_counter_assignments(ADMIN, params={"counter_space_id": space_id})
    )
    assert meta["total_count"] == 2


def test_term_containment_is_reported_before_space_occupancy(api):
    """PRD §3.3: "Term containment comes next: the requested window must lie inside the
    agreement's closed term running from `term_start_date` through `term_end_date` inclusive,
    and a window that pokes outside it in either direction is rejected with
    `ERR_OUTSIDE_AGREEMENT_TERM` (HTTP 422)."
    PRD §3.3: "Four business rules guard the reservation, and their relative order matters
    when a payload violates more than one."
    PRD §3.3: "Exclusive occupancy comes last of the three: the reservation is rejected with
    `ERR_COUNTER_SPACE_OCCUPIED` (HTTP 409) when some existing assignment on the same
    `counter_space_id`, whose status is `ALLOCATED` or `ACTIVE`, satisfies both halves of the
    half-open overlap test — the new start date is strictly earlier than the existing end
    date, and the existing start date is strictly earlier than the new end date."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_17_beats_constraint_priority_18_on_counter_assignment
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-01-01", effective_end_date="2026-04-01",
    )

    version = fx.read_agreement_version(api, agreement_id, operator)
    # 2025-12-01 falls before term_start_date AND the window collides with the incumbent.
    response = api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id,
            space_id,
            version,
            effective_start_date="2025-12-01",
            effective_end_date="2026-03-01",
        ),
        operator,
    )

    error = validate_error(response, ApiErrorId.ERR_OUTSIDE_AGREEMENT_TERM.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_COUNTER_SPACE_OCCUPIED.value, (
        "term containment is checked before exclusive occupancy"
    )


def test_out_of_term_counter_request_leaves_no_trace(api):
    """PRD §3.3: "Term containment comes next: the requested window must lie inside the
    agreement's closed term running from `term_start_date` through `term_end_date` inclusive,
    and a window that pokes outside it in either direction is rejected with
    `ERR_OUTSIDE_AGREEMENT_TERM` (HTTP 422)."
    PRD §3.3: "A successful reservation is created in `ALLOCATED` status. It raises the
    counter space's `assignment_count` by 1 and the agreement's `counter_units_assigned` by 1,
    and advances both the agreement's `version` and the counter space's `version` by 1 each."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_17_beats_constraint_priority_18_on_counter_assignment
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-01-01", effective_end_date="2026-04-01",
    )

    version = fx.read_agreement_version(api, agreement_id, operator)
    api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id, space_id, version,
            effective_start_date="2025-12-01", effective_end_date="2026-03-01",
        ),
        operator,
    )

    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["assignment_count"] == 1, (
        "the rejected reservation must not raise assignment_count"
    )
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 1


def test_activation_blocked_while_agreement_is_suspended(api):
    """PRD §3.3: "Activation moves an assignment `ALLOCATED → ACTIVE`. It requires the
    assignment to be in `ALLOCATED`, requires the counter space's `active_assignment_id` to be
    null so that no other tenant physically holds the position, and requires the referenced
    agreement's `contract_status` to be exactly `ACTIVE` — an agreement sitting in `DRAFT`,
    `SUSPENDED`, `EXPIRED` or `TERMINATED` cannot have space activated against it, and the
    attempt is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/counter_activation_blocked_by_suspended_agreement
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    operator = scenario["operator"]
    assignment = fx.create_counter_assignment(
        api, agreement_id, scenario["space"]["id"], operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )
    validate_success(api.suspend_agreement(agreement_id, ADMIN))

    response = api.activate_counter_assignment(assignment["id"], operator)

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["contract_status"] == "SUSPENDED"


def test_blocked_activation_leaves_the_space_unoccupied(api):
    """PRD §3.3: "Activation moves an assignment `ALLOCATED → ACTIVE`. It requires the
    assignment to be in `ALLOCATED`, requires the counter space's `active_assignment_id` to be
    null so that no other tenant physically holds the position, and requires the referenced
    agreement's `contract_status` to be exactly `ACTIVE` — an agreement sitting in `DRAFT`,
    `SUSPENDED`, `EXPIRED` or `TERMINATED` cannot have space activated against it, and the
    attempt is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.3: "On success the space's `active_assignment_id` is set to the activating
    assignment's `id`, and both the assignment's `version` and the space's `version` advance
    by 1."

    Design: Difficulty/cross_entity_state_dependency/counter_activation_blocked_by_suspended_agreement
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    assignment = fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )
    validate_success(api.suspend_agreement(agreement_id, ADMIN))

    api.activate_counter_assignment(assignment["id"], operator)

    stored = validate_success(api.get_counter_assignment(assignment["id"], ADMIN))
    assert stored["status"] == "ALLOCATED", "the refused activation must not move the row"
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["active_assignment_id"] is None, "no tenant physically holds the position"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 1


def test_activation_writes_the_space_active_assignment_pointer(api):
    """PRD §3.3: "On success the space's `active_assignment_id` is set to the activating
    assignment's `id`, and both the assignment's `version` and the space's `version` advance
    by 1."
    PRD §3.1: "A new space begins unoccupied, with `active_assignment_id` null and
    `assignment_count` of 0; the latter counts the assignments on that space whose status is
    either `ALLOCATED` or `ACTIVE`."

    Design: Corner/state_machines/activating_a_counter_assignment_sets_the_space_active_pointer
    """
    scenario = _space_and_agreement(api)
    operator = scenario["operator"]
    space_id = scenario["space"]["id"]
    assignment = fx.create_counter_assignment(
        api, scenario["agreement"]["id"], space_id, operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )

    activated = validate_success(api.activate_counter_assignment(assignment["id"], operator))

    assert activated["status"] == "ACTIVE"
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["active_assignment_id"] == assignment["id"], (
        "the space must point at the activating assignment"
    )
    assert space["assignment_count"] == 1


def test_suspension_demotes_an_active_counter_assignment(api):
    """PRD §3.2: "Suspending an agreement carries it from `ACTIVE` to `SUSPENDED`, and it does
    not merely change a label: every counter assignment of that agreement currently in
    `ACTIVE` status falls back to `ALLOCATED`, and the `active_assignment_id` of each
    corresponding counter space is cleared to null, so the physical positions are surrendered
    while the suspension lasts."

    Design: Corner/state_machines/suspending_an_agreement_demotes_its_active_counter_assignment
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    assignment = fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )
    validate_success(api.activate_counter_assignment(assignment["id"], operator))

    suspended = validate_success(api.suspend_agreement(agreement_id, ADMIN))

    assert suspended["contract_status"] == "SUSPENDED"
    stored = validate_success(api.get_counter_assignment(assignment["id"], ADMIN))
    assert stored["status"] == "ALLOCATED", "the tenant surrenders the position on suspension"
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["active_assignment_id"] is None
    assert space["assignment_count"] == 1, (
        "demotion keeps the assignment in the ALLOCATED-or-ACTIVE tally"
    )
    assert suspended["counter_units_assigned"] == 1
    assert suspended["compliance_status"] == "COMPLIANT"


def test_releasing_a_released_assignment_is_rejected(api):
    """PRD §3.3: "Release is available from either `ALLOCATED` or `ACTIVE`, and both branches
    land in the terminal `RELEASED` status. Releasing from `ALLOCATED` lowers the counter
    space's `assignment_count` by 1 and the agreement's `counter_units_assigned` by 1, and
    stamps `released_on_date` with the logical clock's calendar date."
    PRD §2.6: "State: the target resource sits in a from-state that the requested transition
    declares, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/releasing_a_counter_assignment_twice_returns_invalid_state
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    assignment = fx.create_counter_assignment(
        api, agreement_id, space_id, operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )
    validate_success(api.release_counter_assignment(assignment["id"], operator))

    response = api.release_counter_assignment(assignment["id"], operator)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(api.get_counter_assignment(assignment["id"], ADMIN))
    assert stored["status"] == "RELEASED"
    assert stored["released_on_date"] == "2026-08-01", (
        "released_on_date carries the logical clock's calendar date"
    )
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["assignment_count"] == 0, "the tally must not go negative on a second release"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 0


def test_counter_window_with_end_before_start_is_rejected(api):
    """PRD §3.3: "Date sanity comes first: `effective_start_date` must be strictly earlier
    than `effective_end_date`, and a payload that reverses or collapses the window is rejected
    with `ERR_INVALID_DATE_RANGE` (HTTP 422)."

    Design: Corner/validations/counter_assignment_with_end_before_start_is_rejected
    """
    scenario = _space_and_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    space_id = scenario["space"]["id"]
    operator = scenario["operator"]
    version = fx.read_agreement_version(api, agreement_id, operator)

    response = api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id, space_id, version,
            effective_start_date="2026-05-01", effective_end_date="2026-02-01",
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)
    space = validate_success(api.get_counter_space(space_id, ADMIN))
    assert space["assignment_count"] == 0
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["version"] == version, (
        "a rejected reservation must not advance the agreement's version"
    )


def test_counter_assignment_list_filters_by_space_and_agreement(api):
    """PRD §2.3: "Counter assignments filter on `agreement_id`, `counter_space_id` and
    `status`."
    PRD §2.3: "Every filter is optional, and filters combine conjunctively."

    Design: Corner/endpoints/counter_assignment_filtered_list_returns_only_the_named_space
    """
    scenario = _space_and_agreement(api, space_label="T1-A02")
    agreement_id = scenario["agreement"]["id"]
    operator = scenario["operator"]
    space_1 = scenario["space"]
    space_2 = fx.create_counter_space(
        api, scenario["facility"]["id"], space_label="T1-A03"
    )
    assignment_1 = fx.create_counter_assignment(
        api, agreement_id, space_1["id"], operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )
    assignment_2 = fx.create_counter_assignment(
        api, agreement_id, space_2["id"], operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )

    by_space, space_meta = validate_paginated(
        api.list_counter_assignments(ADMIN, params={"counter_space_id": space_2["id"]})
    )
    by_agreement, agreement_meta = validate_paginated(
        api.list_counter_assignments(
            ADMIN, params={"agreement_id": agreement_id, "status": "ALLOCATED"}
        )
    )

    assert space_meta["total_count"] == 1
    assert by_space[0]["id"] == assignment_2["id"]
    assert agreement_meta["total_count"] == 2
    assert {row["id"] for row in by_agreement} == {assignment_1["id"], assignment_2["id"]}
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 2


def test_stale_agreement_version_blocks_counter_assignment(api):
    """PRD §2.9: "A request creating a counter assignment must carry
    `expected_agreement_version`, holding the `version` of the `ConcessionAgreement` named by
    `agreement_id` as the client last observed it. If any writer has advanced that agreement's
    `version` since — an execution, a suspension, another counter assignment, an accepted
    report — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot
    bind space to an agreement whose term dates, counter tally or compliance posture it has
    not seen."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_counter_assignment_create_returns_conflict
    """
    scenario = _space_and_agreement(api, space_label="T1-A02")
    agreement_id = scenario["agreement"]["id"]
    operator = scenario["operator"]
    space_2 = fx.create_counter_space(
        api, scenario["facility"]["id"], space_label="T1-A03"
    )
    stale_version = fx.read_agreement_version(api, agreement_id, operator)
    fx.create_counter_assignment(
        api, agreement_id, scenario["space"]["id"], operator,
        effective_start_date="2026-02-01", effective_end_date="2026-05-01",
    )

    response = api.create_counter_assignment(
        f.counter_assignment_payload(
            agreement_id, space_2["id"], stale_version,
            effective_start_date="2026-02-01", effective_end_date="2026-05-01",
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    space = validate_success(api.get_counter_space(space_2["id"], ADMIN))
    assert space["assignment_count"] == 0, "the free space must remain unbooked"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["counter_units_assigned"] == 1
    _rows, meta = validate_paginated(
        api.list_counter_assignments(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
