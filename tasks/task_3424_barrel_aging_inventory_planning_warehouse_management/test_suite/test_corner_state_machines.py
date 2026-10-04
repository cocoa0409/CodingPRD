"""Corner-design translations: state-machine edges and terminal lockdowns.

Each test exercises one transition rule: DUMPED terminality (PRD §3.4),
bonded-report filing from-states and the full amend cycle (PRD §3.7), the
blend-batch revision loop and ABORTED terminality (PRD §3.5), label
activation (PRD §3.5), reservation consume from-state (PRD §3.6), and the
program bubble-up lock when the consumed quota is reached (PRD §3.6).
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    accept_report,
    amend_report,
    consume_reservation,
    create_active_label,
    create_blend_batch,
    create_commissioned_rickhouse,
    create_label_payload,
    create_program,
    create_report,
    create_reservation,
    create_reservation_payload,
    create_validated_batch,
    file_report,
    fill_mature_barrel,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    get_program_fresh,
    get_success_data,
    reconcile_report,
    reject_report,
    release_reservation,
    set_clock,
    setup_program_with_mature_barrel,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_dump_already_dumped_returns_invalid_state(api, warehouse_manager_headers):
    """PRD §3.4: "A `WarehouseManager` may dump a barrel in either `AGING` or
    `MATURE_ELIGIBLE`; from both states the destination is `DUMPED`".
    PRD §3.3: "The maturation dimension, `maturation_status`, runs `FILLED` →
    `AGING` → `MATURE_ELIGIBLE`, with `DUMPED` as a terminal exit from either
    `AGING` or `MATURE_ELIGIBLE`."

    Design: Corner/state_machines/dump_already_dumped_returns_invalid_state
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-S1",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # AGING (min_maturation 48)

    set_clock("2028-09-02T00:00:00Z")
    dumped = validate_success(api.dump_barrel(barrel["id"], warehouse_manager_headers))
    assert dumped["maturation_status"] == "DUMPED"
    version_after_dump = dumped["version"]

    validate_error(
        api.dump_barrel(barrel["id"], warehouse_manager_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_barrel_fresh(barrel["id"])
    assert after["maturation_status"] == "DUMPED", "DUMPED is terminal"
    assert after["version"] == version_after_dump, (
        "the rejected second dump mutates nothing (no version bump)"
    )


def test_file_open_report_returns_invalid_state(api, bonded_preparer_headers):
    """PRD §3.7: "The report is created `OPEN`."
    PRD §3.7: "the amend loop returns the report to a re-fileable state, and
    filing accepts a report from either `RECONCILED` or `AMENDED`."

    Design: Corner/state_machines/file_open_report_returns_invalid_state
    """
    report = create_report("2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z")
    assert report["state"] == "OPEN"

    validate_error(
        api.file_bonded_report(report["id"], bonded_preparer_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_success_data(api.get_bonded_report(report["id"], bonded_preparer_headers))
    assert after["state"] == "OPEN", "filing an OPEN report changes nothing"


def test_revise_proposed_batch_returns_invalid_state(api, master_blender_headers):
    """PRD §3.5: "The batch is created `PROPOSED`."
    PRD §3.5: "Revising sends it `VALIDATED` → `PROPOSED`, increments the
    `version`, and leaves its components in place — retained and editable
    again under the proposal-time rules above."

    Design: Corner/state_machines/revise_proposed_batch_returns_invalid_state
    """
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Rev Loop", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    # Clock is still the startup default 2026-09-01, so the 2030-09-01
    # bottling date lies strictly in the future as required.
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    assert batch["state"] == "PROPOSED"

    validate_error(
        api.revise_blend_batch(batch["id"], master_blender_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_blend_batch_fresh(batch["id"])
    assert after["state"] == "PROPOSED", "the revision loop only runs VALIDATED -> PROPOSED"


def test_consume_released_reservation_returns_invalid_state(api, program_director_headers):
    """PRD §3.6: "Only an `ACTIVE` reservation can be consumed — and because
    expiry is lazy, a reservation whose `expires_at` has passed has already
    become `EXPIRED` by the time it is read, so consuming a lapsed reservation
    fails the from-state check with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §3.6: "`CONSUMED`, `RELEASED`, and `EXPIRED` are the reservation's
    terminal states."

    Design: Corner/state_machines/consume_released_reservation_returns_invalid_state
    """
    ctx = setup_program_with_mature_barrel(
        program_overrides={"name": "Consume After Release"},
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-S5",
    )
    program = ctx["program"]  # required_barrel_count 1, window 45 days
    barrel = ctx["barrel"]

    reservation = create_reservation(program["id"], barrel["id"])
    assert reservation["state"] == "ACTIVE"
    released = release_reservation(reservation["id"])
    assert released["state"] == "RELEASED"

    validate_error(
        api.consume_reservation(reservation["id"], program_director_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    data, _meta = validate_paginated(
        api.list_barrel_reservations(barrel["id"], program_director_headers)
    )
    assert len(data) == 1 and data[0]["state"] == "RELEASED", (
        "RELEASED is terminal: the rejected consume leaves it untouched"
    )
    program_after = get_program_fresh(program["id"])
    assert program_after["state"] == "SELECTION", "no consume happened, so no bubble-up fired"


def test_bonded_report_amend_cycle_completes():
    """PRD §3.7: "Reconciling computes seven figures, moves the report `OPEN` →
    `RECONCILED`, records the preparer's `X-User-ID` as `prepared_by_user_id`,
    and increments the report's `version`."
    PRD §3.7: "Filing moves a report `RECONCILED` → `FILED` under the same
    `BondedPreparer` role, records the filer's `X-User-ID` as
    `filed_by_user_id`, and increments the `version`."
    PRD §3.7: "a `ComplianceOfficer` accepts a `FILED` report, moving it to the
    terminal `ACCEPTED`, or rejects it, moving it to `REJECTED`".
    PRD §3.7: "a clean decision records the officer as `decided_by_user_id`
    and increments the `version`."
    PRD §3.7: "Amending moves a `REJECTED` report to `AMENDED` and increments
    its `version`; the amend loop returns the report to a re-fileable state,
    and filing accepts a report from either `RECONCILED` or `AMENDED`."

    Design: Corner/state_machines/bonded_report_amend_cycle_completes
    """
    # Period [2026-01-01, 2026-07-01) is already closed at the startup clock
    # 2026-09-01, so reconciliation is immediately legal.
    report = create_report(
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", preparer_user_id="prep-1",
    )
    assert report["state"] == "OPEN" and report["version"] == 1

    reconciled = reconcile_report(report["id"], at_clock=DEFAULT_CLOCK_ISO, preparer_user_id="prep-1")
    assert reconciled["state"] == "RECONCILED" and reconciled["version"] == 2
    assert reconciled["prepared_by_user_id"] == "prep-1"

    filed = file_report(report["id"], preparer_user_id="prep-1")
    assert filed["state"] == "FILED" and filed["version"] == 3
    assert filed["filed_by_user_id"] == "prep-1"

    rejected = reject_report(report["id"], officer_user_id="officer-1")
    assert rejected["state"] == "REJECTED" and rejected["version"] == 4
    assert rejected["decided_by_user_id"] == "officer-1"

    amended = amend_report(report["id"], preparer_user_id="prep-1")
    assert amended["state"] == "AMENDED" and amended["version"] == 5, (
        "REJECTED -> AMENDED loop edge"
    )

    refiled = file_report(report["id"], preparer_user_id="prep-1")
    assert refiled["state"] == "FILED" and refiled["version"] == 6, (
        "AMENDED -> FILED loop edge"
    )

    accepted = accept_report(report["id"], officer_user_id="officer-1")
    assert accepted["state"] == "ACCEPTED" and accepted["version"] == 7
    assert accepted["decided_by_user_id"] == "officer-1"


def test_aborted_batch_rejects_further_transitions(api, master_blender_headers):
    """PRD §3.5: "`COMMITTED` and `ABORTED` are the batch's terminal states —
    the only exit from `COMMITTED` is the abort described above."
    PRD §3.5: "From `VALIDATED`, aborting moves the batch to `ABORTED` and
    increments its `version`; no barrel was drawn, so no barrel is touched."

    Design: Corner/state_machines/aborted_batch_rejects_further_transitions
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-S7",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])
    label = create_active_label(name="Abort Test", age_statement_years=1, spirit_type="BOURBON")
    batch = create_validated_batch(label["id"], barrel["id"], 10.0)
    assert batch["state"] == "VALIDATED"

    aborted = validate_success(api.abort_blend_batch(batch["id"], master_blender_headers))
    assert aborted["state"] == "ABORTED"

    validate_error(
        api.validate_blend_batch(batch["id"], master_blender_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_blend_batch_fresh(batch["id"])
    assert after["state"] == "ABORTED", "ABORTED is terminal"
    barrel_after = get_barrel_fresh(barrel["id"])
    assert barrel_after["current_volume_ledger_liters"] == 200.00, (
        "the abort came from VALIDATED, so the 10.0 L draw was never deducted"
    )


def test_label_double_activate_returns_invalid_state(api, master_blender_headers):
    """PRD §3.5: "A new label is `REGISTERED`; activation by a `MasterBlender`
    moves it `REGISTERED` → `ACTIVE` and increments its `version`."

    Design: Corner/state_machines/label_double_activate_returns_invalid_state
    """
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Double Tap", age_statement_years=0, spirit_type="RYE"),
            master_blender_headers,
        )
    )
    assert label["state"] == "REGISTERED" and label["version"] == 1

    activated = validate_success(api.activate_label(label["id"], master_blender_headers))
    assert activated["state"] == "ACTIVE" and activated["version"] == 2

    validate_error(
        api.activate_label(label["id"], master_blender_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_success_data(api.get_label(label["id"], master_blender_headers))
    assert after["state"] == "ACTIVE"
    assert after["version"] == 2, "activation is not idempotent: the rejected retry bumps nothing"


def test_program_locks_when_quota_consumed(api, program_director_headers):
    """PRD §3.6: "It also bubbles up: when the program's count of `CONSUMED`
    reservations reaches `required_barrel_count`, the program itself
    transitions `SELECTION` → `LOCKED`, a transition that increments the
    program's `version` and closes the door — a `LOCKED` program accepts no
    further reservations, and attempts fail its state gate."
    PRD §3.6: "The program's `available_slots` is derived:
    `required_barrel_count` minus its reservations in `ACTIVE`, minus its
    reservations in `CONSUMED`."

    Design: Corner/state_machines/program_locks_when_quota_consumed
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-S8",
    )
    barrel_1 = fill_mature_barrel(ctx["slots"][0]["id"])
    barrel_2 = fill_mature_barrel(ctx["slots"][1]["id"])
    program = create_program(
        name="Lock Check", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )
    reservation = create_reservation(program["id"], barrel_1["id"])
    assert reservation["state"] == "ACTIVE"

    consumed = consume_reservation(reservation["id"])
    assert consumed["state"] == "CONSUMED"

    locked = get_program_fresh(program["id"])
    assert locked["state"] == "LOCKED", (
        "consuming the quota-filling reservation bubble-locks the program"
    )
    assert locked["available_slots"] == 0, "1 required - 0 ACTIVE - 1 CONSUMED"

    # The state gate rejects a reservation against the LOCKED program even
    # with a fresh expected_program_version (PRD §2.7).
    resp = api.create_reservation(
        program["id"],
        create_reservation_payload(barrel_2["id"], locked["version"]),
        program_director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    data, _meta = validate_paginated(
        api.list_barrel_reservations(barrel_2["id"], program_director_headers)
    )
    assert data == [], "no reservation was persisted for the second barrel"
