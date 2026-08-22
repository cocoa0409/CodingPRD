"""Removal from bond, the independent bond axis, excise tax and TTB reporting."""
import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_ID,
    SECOND_COMPLIANCE_OFFICER_ID,
    ApiErrorId,
    approve_release_order,
    assert_lot,
    assert_release_order,
    assert_ttb_report,
    assert_ttb_reconciles,
    create_release_order_payload,
    create_ttb_report_payload,
    execute_release_order,
    new_client,
    new_release_order,
    new_ttb_report,
    prepare_ttb_report,
    set_clock,
    setup_contract_with_lot,
    setup_executed_blend_trial,
    setup_housed_aging_lot,
    setup_requested_release_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_rejected_release_order_is_terminal_and_leaves_the_lot_alone(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 3.8: "A `ComplianceOfficer` may instead reject a `REQUESTED` order,
    which stores the supplied `rejection_reason`, sets the order to `REJECTED`
    and leaves the lot completely untouched."
    PRD 3.8: "`EXECUTED`, `REJECTED` and `CANCELLED` are all terminal."

    Design: Corner/state_machines/corner_release_order_rejected_is_terminal_and_locks_further_actions
    """
    scenario = setup_requested_release_order(gallons=100.00)
    order_id = scenario["release_order"]["id"]
    rejected = validate_success(
        api.release_order_transition(
            order_id,
            {"action": "REJECT", "rejection_reason": "Label approval not on file."},
            compliance_officer_headers,
        )
    )
    assert rejected["status"] == "REJECTED"

    response = api.release_order_transition(
        order_id, {"action": "APPROVE"}, compliance_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    stored = validate_success(api.get_release_order(order_id, facility_admin_headers))
    assert_release_order(stored)
    assert stored["status"] == "REJECTED"
    assert stored["rejection_reason"] == "Label approval not on file."
    assert stored["approved_by_user_id"] is None
    assert stored["excise_tax_cents"] == 0

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["bond_status"] == "IN_BOND"
    assert lot["volume_gallons"] == pytest.approx(3135.00, abs=0.01)


def test_a_transfer_in_bond_prices_at_zero_and_never_tax_determines_the_lot(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 3.8: "Approval stamps `approved_by_user_id` and diverges by type: for
    a `TAXPAID_REMOVAL` the lot moves along the bond axis from `IN_BOND` to
    `TAX_DETERMINED`, because the tax has now been determined against it; for a
    `TRANSFER_IN_BOND` the lot is deliberately **left** at `IN_BOND`, because a
    transfer never determines tax."
    PRD 3.8: "On a `TRANSFER_IN_BOND`, `excise_tax_cents` stays 0, the lot's
    `volume_gallons` is reduced by the removed `gallons`, the client's
    `taxpaid_gallons_ytd` is **not** touched at all, and the lot's `bond_status`
    becomes `TRANSFERRED_IN_BOND` when the removal drains it to exactly zero and
    is otherwise left at `IN_BOND`."

    Design: Corner/calculations/corner_excise_tax_is_zero_for_transfer_in_bond_branch
    """
    scenario = setup_housed_aging_lot(delivery_ticket="DT-H1")
    order = new_release_order(
        scenario["lot"]["id"],
        scenario["rep_headers"],
        release_type="TRANSFER_IN_BOND",
        gallons=500.00,
        destination_permit_number="BW-CA-99001",
    )

    approved = approve_release_order(order["id"])
    assert approved["status"] == "APPROVED"
    mid = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert mid["bond_status"] == "IN_BOND", "the transfer branch never tax-determines"

    executed = validate_success(
        api.release_order_transition(
            order["id"], {"action": "EXECUTE"}, compliance_officer_headers
        )
    )
    assert executed["status"] == "EXECUTED"
    assert executed["excise_tax_cents"] == 0
    assert executed["executed_at"] == "2026-09-01T00:00:00.000Z"

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["volume_gallons"] == pytest.approx(2635.00, abs=0.01)
    assert lot["bond_status"] == "IN_BOND", "a partial transfer leaves the lot in bond"

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["taxpaid_gallons_ytd"] == pytest.approx(0.00, abs=0.01)
    assert client["bond_gallons_in_bond"] == pytest.approx(2635.00, abs=0.01)


def test_approval_is_refused_when_the_lot_cannot_cover_the_requested_gallons(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 3.8: "The order must stand in `REQUESTED`; the lot's `bond_status`
    must be `IN_BOND` and its `production_status` must be either `AGING` or
    `BOTTLED`, with either failure refused as `ERR_INVALID_STATE`; the lot must
    hold at least the requested `gallons`, or the request is refused with
    `ERR_INSUFFICIENT_LOT_VOLUME`; and the owning client must be `ACTIVE`, or
    the request is refused with `ERR_CLIENT_NOT_ACTIVE`."

    Design: Corner/errors/corner_release_gallons_exceeding_lot_volume_rejected
    """
    scenario = setup_requested_release_order(gallons=4000.00, delivery_ticket="DT-Z1")

    response = api.release_order_transition(
        scenario["release_order"]["id"], {"action": "APPROVE"}, compliance_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_LOT_VOLUME.value, 422)

    stored = validate_success(
        api.get_release_order(scenario["release_order"]["id"], facility_admin_headers)
    )
    assert stored["status"] == "REQUESTED"
    assert stored["approved_by_user_id"] is None

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["bond_status"] == "IN_BOND"
    assert lot["volume_gallons"] == pytest.approx(3135.00, abs=0.01)


def test_the_destination_permit_pairing_is_enforced_in_both_directions(
    api, facility_admin_headers
):
    """PRD 3.8: "A transfer must name the receiving winery's
    `destination_permit_number`; a taxpaid removal must omit that field or send
    it as null. Either violation of that pairing is refused with
    `ERR_DESTINATION_PERMIT_REQUIRED`."

    Design: Corner/errors/corner_transfer_in_bond_without_destination_permit_rejected
    """
    scenario = setup_contract_with_lot(delivery_ticket="DT-AA1")

    missing = api.create_release_order(
        create_release_order_payload(
            scenario["lot"]["id"], release_type="TRANSFER_IN_BOND", gallons=100.00
        ),
        scenario["rep_headers"],
    )
    validate_error(missing, ApiErrorId.ERR_DESTINATION_PERMIT_REQUIRED.value, 422)

    extra = api.create_release_order(
        create_release_order_payload(
            scenario["lot"]["id"],
            release_type="TAXPAID_REMOVAL",
            gallons=100.00,
            destination_permit_number="BW-CA-99001",
        ),
        scenario["rep_headers"],
    )
    validate_error(extra, ApiErrorId.ERR_DESTINATION_PERMIT_REQUIRED.value, 422)

    rows, meta = validate_paginated(
        api.list_release_orders(
            facility_admin_headers, params={"lot_id": scenario["lot"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_overlapping_reporting_windows_are_refused_while_abutting_ones_are_not(
    api, compliance_officer_headers
):
    """PRD 3.9: "The window must be sane — `period_end` strictly after
    `period_start`, otherwise `ERR_INVALID_INTERVAL` — and it must not overlap
    any other report for the same client standing in `OPEN`, `PREPARED`, `FILED`
    or `AMENDED`, otherwise `ERR_TTB_PERIOD_OVERLAP`."

    Design: Corner/validations/corner_ttb_period_overlap_rejected
    """
    set_clock("2026-10-20T00:00:00Z")
    client = new_client()
    first = new_ttb_report(
        client["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )

    response = api.create_ttb_report(
        create_ttb_report_payload(
            client["id"],
            period_start="2026-09-15T00:00:00Z",
            period_end="2026-10-15T00:00:00Z",
        ),
        compliance_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_TTB_PERIOD_OVERLAP.value, 409)

    abutting = validate_success(
        api.create_ttb_report(
            create_ttb_report_payload(
                client["id"],
                period_start="2026-10-01T00:00:00Z",
                period_end="2026-11-01T00:00:00Z",
            ),
            compliance_officer_headers,
        ),
        201,
    )
    assert abutting["status"] == "OPEN", (
        "a window opening exactly at the incumbent's exclusive period_end is free"
    )

    rows, _ = validate_paginated(
        api.list_ttb_reports(compliance_officer_headers, params={"client_id": client["id"]})
    )
    assert sorted(row["id"] for row in rows) == sorted([first["id"], abutting["id"]])


def test_amending_a_predecessor_breaks_the_opening_and_blocks_the_next_filing(
    api, compliance_officer_headers, second_compliance_officer_headers,
    facility_admin_headers
):
    """PRD 3.9: "The `opening_gallons` line is the `closing_gallons` of that
    client's own previously `FILED` reports whose `period_end` falls at or
    before this report's `period_start`, choosing the one with the latest
    `period_end` and breaking ties by the earliest `created_at`; it is 0 when no
    such report exists."
    PRD 3.9: "Corrections are made by amending a `FILED` report, which moves it
    to `AMENDED`, increments `amendment_count` by 1, and recomputes the client's
    `last_filed_period_end` because this report no longer counts as filed;
    preparing it again under whatever `variant` the correction calls for returns
    it to `PREPARED`, from which it can be filed once more."
    PRD 3.9: "Filing is permitted only when that figure is exactly 0.00 — an
    unbalanced report is refused with `ERR_TTB_VARIANCE_UNBALANCED`, which is
    the point of the recall loop."

    Design: Corner/errors/corner_ttb_file_blocked_when_amended_predecessor_breaks_the_opening
    """
    scenario = setup_contract_with_lot(delivery_ticket="DT-AD1")
    client_id = scenario["client"]["id"]

    set_clock("2026-10-01T00:00:00Z")
    september = new_ttb_report(
        client_id, period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z"
    )
    prepared_september = prepare_ttb_report(september["id"])
    assert prepared_september["produced_gallons"] == pytest.approx(3135.00, abs=0.01)
    assert prepared_september["variance_gallons"] == pytest.approx(0.00, abs=0.01)

    filed_september = validate_success(
        api.ttb_report_transition(
            september["id"], {"action": "FILE"}, second_compliance_officer_headers
        )
    )
    assert filed_september["status"] == "FILED"
    assert filed_september["closing_gallons"] == pytest.approx(3135.00, abs=0.01)

    october = new_ttb_report(
        client_id, period_start="2026-10-01T00:00:00Z", period_end="2026-11-01T00:00:00Z"
    )
    set_clock("2026-11-01T00:00:00Z")
    first_pass = prepare_ttb_report(october["id"])
    assert first_pass["opening_gallons"] == pytest.approx(3135.00, abs=0.01)
    assert first_pass["variance_gallons"] == pytest.approx(0.00, abs=0.01)

    amended = validate_success(
        api.ttb_report_transition(
            september["id"], {"action": "AMEND"}, second_compliance_officer_headers
        )
    )
    assert amended["status"] == "AMENDED"
    assert amended["amendment_count"] == 1

    validate_success(
        api.ttb_report_transition(
            october["id"], {"action": "RECALL"}, compliance_officer_headers
        )
    )
    second_pass = prepare_ttb_report(october["id"])
    assert second_pass["opening_gallons"] == pytest.approx(0.00, abs=0.01), (
        "no FILED predecessor survives the amendment"
    )
    assert second_pass["variance_gallons"] == pytest.approx(3135.00, abs=0.01)

    response = api.ttb_report_transition(
        october["id"], {"action": "FILE"}, second_compliance_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_TTB_VARIANCE_UNBALANCED.value, 422)

    stored = validate_success(
        api.get_ttb_report(october["id"], facility_admin_headers)
    )
    assert stored["status"] == "PREPARED"
    assert stored["filed_by_user_id"] is None

    client = validate_success(api.get_client(client_id, facility_admin_headers))
    assert client["last_filed_period_end"] is None


# ── The bond axis moves independently of the production axis ─────────


def test_the_bond_axis_closes_its_cycle_while_production_holds_at_aging(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 3.4: "A lot carries **two independent status axes**, and this is the
    single most important structural fact about it."
    PRD 3.8: "The bond axis is therefore a small cycle plus two exits. A lot
    sits at `IN_BOND` until a taxpaid removal is approved, at which point it
    moves to `TAX_DETERMINED`; a partial removal, or the cancellation of the
    approved order, returns it to `IN_BOND`, and that `IN_BOND` to
    `TAX_DETERMINED` to `IN_BOND` cycle may repeat for every partial removal."
    PRD 3.8: "None of these moves ever writes `production_status`, and none of
    the production transitions in §3.4 ever writes `bond_status`."

    Design: Difficulty/non_linear_state_machine/lot_bond_axis_cycles_while_production_axis_holds_at_aging
    """
    scenario = setup_requested_release_order(gallons=100.00, delivery_ticket="DT-4001")
    order_id = scenario["release_order"]["id"]

    approve_release_order(order_id)
    mid = validate_success(api.get_lot(scenario["lot"]["id"], compliance_officer_headers))
    assert_lot(mid)
    assert mid["bond_status"] == "TAX_DETERMINED"
    assert mid["production_status"] == "AGING", "approval never writes the production axis"

    execute_release_order(order_id)
    after = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert after["bond_status"] == "IN_BOND", (
        "a partial removal returns the bond axis to IN_BOND, closing the cycle"
    )
    assert after["production_status"] == "AGING"
    assert after["volume_gallons"] == pytest.approx(3035.00, abs=0.01)
    assert after["aging_start_at"] == "2026-09-01T00:00:00.000Z", (
        "neither bond-axis transition disturbs the storage clock"
    )


def test_a_partial_taxpaid_removal_prices_at_the_first_excise_band(
    api, facility_admin_headers
):
    """PRD 3.8: "The federal credit structure gives three bands: the first
    30,000 gallons of the year price at 7 cents per gallon, the gallons from
    30,000 up to 130,000 price at 17 cents per gallon, and everything beyond
    130,000 gallons prices at 107 cents per gallon."
    PRD 3.1: "`taxpaid_gallons_ytd` accumulates the gallons removed under a
    `TAXPAID_REMOVAL` release order that has reached `EXECUTED`, counting only
    orders whose `executed_at` falls in the same calendar year as the logical
    clock's current instant, and is likewise carried to two decimal places."

    Design: Difficulty/non_linear_state_machine/lot_bond_axis_cycles_while_production_axis_holds_at_aging
    """
    scenario = setup_requested_release_order(gallons=100.00, delivery_ticket="DT-4001")
    order_id = scenario["release_order"]["id"]
    approve_release_order(order_id)

    executed = execute_release_order(order_id)

    assert executed["excise_tax_cents"] == 700, (
        f"100.00 gallons at 7 cents, got {executed['excise_tax_cents']}"
    )

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["taxpaid_gallons_ytd"] == pytest.approx(100.00, abs=0.01)
    assert client["bond_gallons_in_bond"] == pytest.approx(3035.00, abs=0.01)


# ── The bonded-book freeze while a period is under preparation ───────


def _setup_approved_release_under_a_prepared_period():
    """An APPROVED 500-gallon taxpaid removal on a client whose September report
    sits in PREPARED with the clock inside its window."""
    scenario = setup_requested_release_order(gallons=500.00, delivery_ticket="DT-9101")
    scenario["release_order"] = approve_release_order(scenario["release_order"]["id"])
    report = new_ttb_report(
        scenario["client"]["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    scenario["report"] = prepare_ttb_report(report["id"])
    return scenario


def test_execution_is_frozen_while_a_prepared_period_contains_the_clock(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 2.9: "The bonded books are additionally frozen while a period is
    under preparation. When a client has any `TTBReport` sitting in status
    `PREPARED` whose window contains the logical clock's current instant, no
    release order for that client may be executed, and the attempt is rejected
    with `ERR_REPORTING_PERIOD_LOCKED` (409)."

    Design: Difficulty/cross_entity_state_dependency/release_execute_gated_by_prepared_ttb_period
    """
    scenario = _setup_approved_release_under_a_prepared_period()

    response = api.release_order_transition(
        scenario["release_order"]["id"], {"action": "EXECUTE"}, compliance_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_REPORTING_PERIOD_LOCKED.value, 409)

    order = validate_success(
        api.get_release_order(scenario["release_order"]["id"], facility_admin_headers)
    )
    assert order["status"] == "APPROVED"
    assert order["executed_at"] is None

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["volume_gallons"] == pytest.approx(3135.00, abs=0.01)
    assert lot["bond_status"] == "TAX_DETERMINED"


def test_recalling_the_report_lifts_the_freeze_on_the_same_execute_call(
    api, compliance_officer_headers, facility_admin_headers
):
    """PRD 2.9: "Recalling the report or filing it lifts the freeze."
    PRD 3.9: "An officer who is unhappy with the figures recalls the report,
    moving `PREPARED` back to `OPEN`, which resets every computed figure to 0
    and clears `prepared_by_user_id` to null; that recall loop may repeat until
    the figures balance."

    Design: Difficulty/cross_entity_state_dependency/release_execute_gated_by_prepared_ttb_period
    """
    scenario = _setup_approved_release_under_a_prepared_period()
    api.release_order_transition(
        scenario["release_order"]["id"], {"action": "EXECUTE"}, compliance_officer_headers
    )

    validate_success(
        api.ttb_report_transition(
            scenario["report"]["id"], {"action": "RECALL"}, compliance_officer_headers
        )
    )
    executed = validate_success(
        api.release_order_transition(
            scenario["release_order"]["id"], {"action": "EXECUTE"}, compliance_officer_headers
        )
    )

    assert executed["status"] == "EXECUTED"
    assert executed["excise_tax_cents"] == 3500, (
        f"500.00 gallons at 7 cents, got {executed['excise_tax_cents']}"
    )

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["volume_gallons"] == pytest.approx(2635.00, abs=0.01)
    assert lot["bond_status"] == "IN_BOND"

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["taxpaid_gallons_ytd"] == pytest.approx(500.00, abs=0.01)


# ── Segregation of duties outranks the period-closed check ───────────


def _setup_prepared_report_on_a_quiet_client():
    """A PREPARED report for a client with no wine at all, so every
    reconciliation line is 0.00 and the variance gate cannot mask the pair."""
    set_clock("2026-09-01T00:00:00Z")
    client = new_client(
        name="Howell Ridge Wines",
        ttb_permit_number="BW-CA-15003",
        contact_email="compliance@howellridge.example",
    )
    report = new_ttb_report(
        client["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    prepared = prepare_ttb_report(report["id"])
    return {"client": client, "report": prepared}


def test_filing_as_your_own_preparer_reports_segregation_of_duties(
    api, compliance_officer_headers
):
    """PRD 2.9: "A bonded report is prepared by one compliance user and filed by
    another: the `X-User-ID` filing a report must differ from the
    `prepared_by_user_id` recorded at preparation."
    PRD 2.5: "Requests are validated in a strictly ordered ladder, and the
    **first** rung that fails decides the response."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_period_not_closed_on_ttb_file
    """
    scenario = _setup_prepared_report_on_a_quiet_client()
    assert scenario["report"]["variance_gallons"] == pytest.approx(0.00, abs=0.01), (
        "the variance gate is satisfied and cannot mask the pair under test"
    )

    response = api.ttb_report_transition(
        scenario["report"]["id"], {"action": "FILE"}, compliance_officer_headers
    )

    error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_PERIOD_NOT_CLOSED.value, (
        "the segregation rung sits above the period-closed rung"
    )


def test_the_period_closed_check_only_becomes_visible_to_a_second_officer(
    api, second_compliance_officer_headers, facility_admin_headers
):
    """PRD 2.5: "a report's `period_end` must be at or before the logical
    clock's current instant when filing, otherwise `ERR_PERIOD_NOT_CLOSED`"
    PRD 3.9: "A successful filing stamps `filed_by_user_id` and `filed_at`, and
    recomputes the client's `last_filed_period_end`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_period_not_closed_on_ttb_file
    """
    scenario = _setup_prepared_report_on_a_quiet_client()
    report_id = scenario["report"]["id"]

    response = api.ttb_report_transition(
        report_id, {"action": "FILE"}, second_compliance_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_CLOSED.value, 422)

    set_clock("2026-10-01T00:00:00Z")
    filed = validate_success(
        api.ttb_report_transition(
            report_id, {"action": "FILE"}, second_compliance_officer_headers
        )
    )
    assert_ttb_report(filed)
    assert filed["status"] == "FILED"
    assert filed["prepared_by_user_id"] == COMPLIANCE_OFFICER_ID
    assert filed["filed_by_user_id"] == SECOND_COMPLIANCE_OFFICER_ID
    assert filed["filed_at"] == "2026-10-01T00:00:00.000Z"

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["last_filed_period_end"] == "2026-10-01T00:00:00.000Z"


# ── BONDED against GROSS on identical stored data ────────────────────


def _setup_september_book_with_a_blend_and_a_removal():
    """One September of production: two intake lots, one executed blend and one
    executed 100-gallon taxpaid removal, with the clock moved into October and a
    reporting period opened."""
    scenario = setup_executed_blend_trial(draw_a=750.00, draw_b=250.00)
    order = new_release_order(
        scenario["blend_lot"]["id"], scenario["rep_headers"], gallons=100.00, cases=40
    )
    approve_release_order(order["id"])
    execute_release_order(order["id"])
    set_clock("2026-10-01T00:00:00Z")
    scenario["report"] = new_ttb_report(
        scenario["client"]["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    return scenario


def test_the_bonded_reading_treats_a_blend_merge_as_producing_nothing(
    api, compliance_officer_headers
):
    """PRD 3.9: "Under **`BONDED`**, the default, a blend merge is an internal
    bond-to-bond move that produces nothing: `produced_gallons` totals the
    `volume_gallons` at creation of that client's lots whose `origin` is
    `INTAKE` and whose `created_at` falls inside the window, and `loss_gallons`
    totals the losses booked inside the window — press losses plus declared
    blending losses — plus the total `gallons_consumed` of that client's runs
    completed inside the window, because bulk wine packaged into cased goods
    leaves the bulk bonded account and must appear on that line or the physical
    closing count will not reconcile."

    Design: Difficulty/dual_variant_calc/ttb_reconciliation_bonded_versus_gross_produced_gallons
    """
    scenario = _setup_september_book_with_a_blend_and_a_removal()

    data = validate_success(
        api.ttb_report_transition(
            scenario["report"]["id"],
            {"action": "PREPARE", "variant": "BONDED"},
            compliance_officer_headers,
        )
    )

    assert_ttb_report(data)
    assert data["produced_gallons"] == pytest.approx(2431.25, abs=0.01), (
        f"1565.00 + 866.25 gallons of intake lots, got {data['produced_gallons']}"
    )
    assert data["loss_gallons"] == pytest.approx(20.00, abs=0.01), (
        f"only the declared blending loss, got {data['loss_gallons']}"
    )
    assert data["opening_gallons"] == pytest.approx(0.00, abs=0.01)
    assert data["removed_taxpaid_gallons"] == pytest.approx(100.00, abs=0.01)
    assert data["removed_in_bond_gallons"] == pytest.approx(0.00, abs=0.01)
    assert data["closing_gallons"] == pytest.approx(2311.25, abs=0.01)
    assert data["variance_gallons"] == pytest.approx(0.00, abs=0.01)
    assert_ttb_reconciles(data)


def test_the_gross_reading_counts_the_blend_lot_and_its_component_draw(
    api, compliance_officer_headers
):
    """PRD 3.9: "Under **`GROSS`**, every minted lot counts as production and
    every gallon drawn into a blend counts as a removal to internal transfer:
    `produced_gallons` is the `BONDED` figure plus the total `volume_gallons` at
    creation of that client's lots whose `origin` is `BLEND` and whose
    `created_at` falls inside the window, and `loss_gallons` is the `BONDED`
    figure less the total `projected_loss_gallons` of the trials executed inside
    the window plus the total `total_component_gallons` of those same trials."
    PRD 3.9: "The preparation action carries an optional `variant` field
    selecting which reading to apply; the supplied value is stored on the
    report's `variant`, and when the action omits it the report's `variant` is
    left at `BONDED`."

    Design: Difficulty/dual_variant_calc/ttb_reconciliation_bonded_versus_gross_produced_gallons
    """
    scenario = _setup_september_book_with_a_blend_and_a_removal()

    data = validate_success(
        api.ttb_report_transition(
            scenario["report"]["id"],
            {"action": "PREPARE", "variant": "GROSS"},
            compliance_officer_headers,
        )
    )

    assert data["variant"] == "GROSS"
    assert data["produced_gallons"] == pytest.approx(3411.25, abs=0.01), (
        f"2431.25 plus the 980.00-gallon blend lot, got {data['produced_gallons']}"
    )
    assert data["loss_gallons"] == pytest.approx(1000.00, abs=0.01), (
        f"20.00 less 20.00 plus the 1000.00 gallons drawn into the blend, got "
        f"{data['loss_gallons']}"
    )
    assert data["closing_gallons"] == pytest.approx(2311.25, abs=0.01)
    assert data["variance_gallons"] == pytest.approx(0.00, abs=0.01)
    assert_ttb_reconciles(data)


def test_both_readings_agree_on_the_physical_count_and_the_removal_lines(
    api, compliance_officer_headers
):
    """PRD 3.9: "The `closing_gallons` line is a physical count taken at
    preparation time: the total `volume_gallons` across that client's lots whose
    `bond_status` is `IN_BOND` at that instant."
    PRD 3.9: "For identical data `GROSS` reports a larger `produced_gallons` and
    a larger `loss_gallons` than `BONDED`, and both readings still reconcile to
    a zero variance."

    Design: Difficulty/dual_variant_calc/ttb_reconciliation_bonded_versus_gross_produced_gallons
    """
    scenario = _setup_september_book_with_a_blend_and_a_removal()
    report_id = scenario["report"]["id"]

    bonded = validate_success(
        api.ttb_report_transition(
            report_id, {"action": "PREPARE", "variant": "BONDED"}, compliance_officer_headers
        )
    )
    validate_success(
        api.ttb_report_transition(
            report_id, {"action": "RECALL"}, compliance_officer_headers
        )
    )
    gross = validate_success(
        api.ttb_report_transition(
            report_id, {"action": "PREPARE", "variant": "GROSS"}, compliance_officer_headers
        )
    )

    assert bonded["closing_gallons"] == pytest.approx(
        gross["closing_gallons"], abs=0.01
    ), "the physical count is variant-independent"
    assert bonded["closing_gallons"] == pytest.approx(2311.25, abs=0.01)
    assert gross["produced_gallons"] - bonded["produced_gallons"] == pytest.approx(
        980.00, abs=0.01
    ), "the difference is exactly the blend lot's minted volume"
    assert gross["produced_gallons"] > bonded["produced_gallons"]
    assert gross["loss_gallons"] > bonded["loss_gallons"]
    assert bonded["removed_taxpaid_gallons"] == pytest.approx(
        gross["removed_taxpaid_gallons"], abs=0.01
    )
    assert bonded["removed_in_bond_gallons"] == pytest.approx(
        gross["removed_in_bond_gallons"], abs=0.01
    )
    assert bonded["variance_gallons"] == pytest.approx(0.00, abs=0.01)
    assert gross["variance_gallons"] == pytest.approx(0.00, abs=0.01)
