"""Blending trials: projection, the revision cycle, execution and unwind."""
import pytest

from test_helpers import (
    FACILITY_ADMIN_ID,
    ApiErrorId,
    approve_release_order,
    assert_blend_trial,
    assert_lot,
    assert_vessel,
    assert_vessel_allocation,
    blend_component,
    contract_gallons_invariant,
    execute_blend_trial,
    execute_release_order,
    new_blend_trial,
    new_release_order,
    setup_approved_blend_trial,
    setup_executed_blend_trial,
    setup_submitted_blend_trial,
    setup_two_aging_lots,
    submit_blend_trial,
    validate_error,
    validate_paginated,
    validate_success,
)

# 14500 - 4000 = 10500 lb = 5.25 t at 24.00 Brix → 866.25 gallons, Rutherford fruit
LOAD_5_25T_CABERNET_RUTHERFORD = {
    "gross_weight_lbs": 14500,
    "tare_weight_lbs": 4000,
    "varietal": "CABERNET_SAUVIGNON",
    "appellation": "RUTHERFORD",
    "block_code": "R04",
    "brix": 24.00,
    "ph": 3.55,
}


def test_approval_is_refused_when_no_ava_clears_the_eighty_five_percent_share(
    api, facility_admin_headers
):
    """PRD 3.5: "Approval moves `SUBMITTED` to `APPROVED`, stamping
    `approved_by_user_id` with the approving admin's identifier. It requires
    `projected_blend_gallons` to be greater than zero, and it requires the blend
    to be AVA-eligible: the facility only executes blends under its bonded label
    programme when a dominant appellation clears the 85.00 percent share, so a
    trial whose `projected_appellation_label` has fallen back to `CALIFORNIA` is
    refused with `ERR_APPELLATION_INELIGIBLE`."

    Design: Corner/errors/corner_blend_approve_blocked_when_no_ava_reaches_85_percent
    """
    base = setup_two_aging_lots(
        load_b=LOAD_5_25T_CABERNET_RUTHERFORD, lot_code_b="CS-RUT-26-01"
    )
    scenario = setup_submitted_blend_trial(
        scenario=base, draw_a=750.00, draw_b=250.00, declared_loss_pct=2.00
    )
    trial = scenario["trial"]
    assert trial["projected_varietal_label"] == "CABERNET_SAUVIGNON"
    assert trial["projected_appellation_label"] == "CALIFORNIA", (
        "750.00 of 1000.00 gallons is a 75.00 percent OAKVILLE share"
    )

    response = api.blend_trial_transition(
        trial["id"], {"action": "APPROVE"}, facility_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_APPELLATION_INELIGIBLE.value, 422)

    stored = validate_success(api.get_blend_trial(trial["id"], facility_admin_headers))
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_user_id"] is None

    lot_a = validate_success(api.get_lot(scenario["lot_a"]["id"], facility_admin_headers))
    lot_b = validate_success(api.get_lot(scenario["lot_b"]["id"], facility_admin_headers))
    assert lot_a["volume_gallons"] == pytest.approx(1565.00, abs=0.01)
    assert lot_b["volume_gallons"] == pytest.approx(866.25, abs=0.01)


def test_unwind_is_refused_once_wine_has_left_the_result_lot(api, facility_admin_headers):
    """PRD 3.5: "An executed blend can be unwound by a `FacilityAdmin`, but only
    while the result lot is untouched: its `volume_gallons` must still equal the
    trial's `projected_blend_gallons` and its `loss_gallons` must still equal
    `projected_loss_gallons`. If any wine has been bottled out of it, blended
    onward, or released from it, the unwind is refused with
    `ERR_BLEND_ALREADY_CONSUMED`."

    Design: Corner/errors/corner_blend_unwind_rejected_after_result_lot_drawn_down
    """
    scenario = setup_executed_blend_trial(draw_a=750.00, draw_b=250.00)
    blend_lot_id = scenario["blend_lot"]["id"]
    order = new_release_order(blend_lot_id, scenario["rep_headers"], gallons=100.00, cases=40)
    approve_release_order(order["id"])
    executed = execute_release_order(order["id"])
    assert executed["excise_tax_cents"] == 700

    drawn = validate_success(api.get_lot(blend_lot_id, facility_admin_headers))
    assert drawn["volume_gallons"] == pytest.approx(880.00, abs=0.01)

    response = api.blend_trial_transition(
        scenario["trial"]["id"], {"action": "UNWIND"}, facility_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_BLEND_ALREADY_CONSUMED.value, 422)

    trial = validate_success(
        api.get_blend_trial(scenario["trial"]["id"], facility_admin_headers)
    )
    assert trial["status"] == "EXECUTED"
    assert trial["result_lot_id"] == blend_lot_id

    lot_a = validate_success(api.get_lot(scenario["lot_a"]["id"], facility_admin_headers))
    lot_b = validate_success(api.get_lot(scenario["lot_b"]["id"], facility_admin_headers))
    assert lot_a["volume_gallons"] == pytest.approx(815.00, abs=0.01), (
        "a refused unwind restores nothing"
    )
    assert lot_b["volume_gallons"] == pytest.approx(616.25, abs=0.01)


def test_the_submitting_client_rep_may_not_approve_its_own_trial(
    api, facility_admin_headers
):
    """PRD 2.1: "For example, on the blend-trial transitions endpoint only a
    `ClientRep` may send `SUBMIT` while only a `FacilityAdmin` may send
    `REQUEST_REVISION`, `APPROVE`, `REJECT` or `UNWIND`; on the release-order
    transitions endpoint only a `ComplianceOfficer` may send `APPROVE`, `REJECT`
    or `EXECUTE` while only a `ClientRep` may send `CANCEL`; on the
    vessel-condition endpoint only a `CellarSupervisor` may send `CLEAN` while
    only a `FacilityAdmin` may send `DECOMMISSION` or `RECOMMISSION`; on the
    vessel-allocation transitions endpoint only a `CellarSupervisor` may send
    `RELEASE` while only a `FacilityAdmin` may send `CANCEL`; and on the
    work-order transitions endpoint `SCHEDULE`, `START` and the `IN_PROGRESS`
    completion are the `CellarSupervisor`'s actions, the completion of a
    disputed order is the `FacilityAdmin`'s, and `DISPUTE` and `CANCEL` are the
    `ClientRep`'s."

    Design: Corner/rbac/corner_client_rep_cannot_approve_its_own_blend_trial
    """
    scenario = setup_submitted_blend_trial(draw_a=750.00, draw_b=250.00)
    trial = scenario["trial"]
    assert trial["submitted_by_user_id"] == scenario["client"]["id"], (
        "a ClientRep's X-User-ID is the id of the Client it acts for"
    )

    response = api.blend_trial_transition(
        trial["id"], {"action": "APPROVE"}, scenario["rep_headers"]
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    approved = validate_success(
        api.blend_trial_transition(
            trial["id"], {"action": "APPROVE"}, facility_admin_headers
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == FACILITY_ADMIN_ID


# ── The SUBMITTED → REVISION_REQUESTED → SUBMITTED cycle ─────────────


def _setup_trial_at_round_one():
    """Two AGING lots and a SUBMITTED trial drawing 400.00 and 100.00 at 1.00 %."""
    scenario = setup_two_aging_lots()
    trial = new_blend_trial(
        scenario["contract"]["id"],
        scenario["rep_headers"],
        [
            blend_component(scenario["lot_a"]["id"], 400.00),
            blend_component(scenario["lot_b"]["id"], 100.00),
        ],
        declared_loss_pct=1.00,
    )
    scenario["created_trial"] = trial
    scenario["trial"] = submit_blend_trial(trial["id"], scenario["rep_headers"])
    return scenario


def test_two_revision_rounds_return_the_trial_to_submitted_at_round_three(
    api, facility_admin_headers
):
    """PRD 3.5: "A new trial opens in `DRAFT` at `round_number` 1, with
    `result_lot_id`, `submitted_by_user_id`, `approved_by_user_id` and
    `revision_note` all null, and its projections already computed."
    PRD 3.5: "Each resubmission increments `round_number` by 1, clears
    `revision_note` back to null, re-stamps `submitted_by_user_id` with the
    acting user, and recomputes every projected figure."
    PRD 3.5: "This `SUBMITTED` to `REVISION_REQUESTED` to `SUBMITTED` cycle may
    repeat as many times as the parties need."

    Design: Difficulty/non_linear_state_machine/blend_trial_revision_cycle_reaches_round_three
    """
    scenario = _setup_trial_at_round_one()
    trial_id = scenario["trial"]["id"]
    assert scenario["created_trial"]["round_number"] == 1

    first_revision = validate_success(
        api.blend_trial_transition(
            trial_id,
            {
                "action": "REQUEST_REVISION",
                "revision_note": "Too much Merlot on the mid-palate.",
            },
            facility_admin_headers,
        )
    )
    assert first_revision["status"] == "REVISION_REQUESTED"
    assert first_revision["revision_note"] == "Too much Merlot on the mid-palate."

    round_two = validate_success(
        api.revise_blend_trial(
            trial_id,
            {
                "components": [
                    blend_component(scenario["lot_a"]["id"], 700.00),
                    blend_component(scenario["lot_b"]["id"], 100.00),
                ],
                "declared_loss_pct": 1.00,
            },
            scenario["rep_headers"],
        )
    )
    assert round_two["round_number"] == 2
    assert round_two["status"] == "SUBMITTED"

    validate_success(
        api.blend_trial_transition(
            trial_id,
            {"action": "REQUEST_REVISION", "revision_note": "Now too tannic — pull it back."},
            facility_admin_headers,
        )
    )
    round_three = validate_success(
        api.revise_blend_trial(
            trial_id,
            {
                "components": [
                    blend_component(scenario["lot_a"]["id"], 750.00),
                    blend_component(scenario["lot_b"]["id"], 250.00),
                ],
                "declared_loss_pct": 2.00,
            },
            scenario["rep_headers"],
        )
    )
    assert_blend_trial(round_three)
    assert round_three["round_number"] == 3
    assert round_three["status"] == "SUBMITTED", (
        "the cycle returns to the very state it started in"
    )
    assert round_three["revision_note"] is None, "each resubmission clears the note"


def test_the_third_round_projections_are_recomputed_from_the_new_draw(
    api, facility_admin_headers
):
    """PRD 3.5: "The `projected_alcohol_pct` is volume-weighted over the gallons
    actually drawn rather than over each source lot's whole volume: total,
    across components, each component's `volume_gallons` multiplied by its
    source lot's `alcohol_pct`, divide by `total_component_gallons`, and round
    half up to two decimal places; when any named source lot still has a null
    `alcohol_pct` the projection is null."
    PRD 3.5: "The `projected_loss_gallons` is that total multiplied by
    `declared_loss_pct` and divided by 100, rounded half up to two decimal
    places; the facility does not execute a trial declaring more than a
    five-percent loss."
    PRD 3.5: "When that share is at least 75.00 percent,
    `projected_varietal_label` is the dominant varietal's name; otherwise it is
    `RED_BLEND`."

    Design: Difficulty/non_linear_state_machine/blend_trial_revision_cycle_reaches_round_three
    """
    scenario = _setup_trial_at_round_one()
    trial_id = scenario["trial"]["id"]

    validate_success(
        api.blend_trial_transition(
            trial_id,
            {"action": "REQUEST_REVISION", "revision_note": "Too much Merlot on the mid-palate."},
            facility_admin_headers,
        )
    )
    validate_success(
        api.revise_blend_trial(
            trial_id,
            {
                "components": [
                    blend_component(scenario["lot_a"]["id"], 700.00),
                    blend_component(scenario["lot_b"]["id"], 100.00),
                ],
                "declared_loss_pct": 1.00,
            },
            scenario["rep_headers"],
        )
    )
    validate_success(
        api.blend_trial_transition(
            trial_id,
            {"action": "REQUEST_REVISION", "revision_note": "Now too tannic — pull it back."},
            facility_admin_headers,
        )
    )

    data = validate_success(
        api.revise_blend_trial(
            trial_id,
            {
                "components": [
                    blend_component(scenario["lot_a"]["id"], 750.00),
                    blend_component(scenario["lot_b"]["id"], 250.00),
                ],
                "declared_loss_pct": 2.00,
            },
            scenario["rep_headers"],
        )
    )

    assert data["total_component_gallons"] == pytest.approx(1000.00, abs=0.01)
    assert data["projected_loss_gallons"] == pytest.approx(20.00, abs=0.01)
    assert data["projected_blend_gallons"] == pytest.approx(980.00, abs=0.01)
    assert data["projected_alcohol_pct"] == pytest.approx(14.19, abs=0.01), (
        f"(750 x 14.52 + 250 x 13.20) / 1000 is 14.19, got "
        f"{data['projected_alcohol_pct']}"
    )
    assert data["projected_varietal_label"] == "CABERNET_SAUVIGNON", (
        "a 750.00 of 1000.00 gallon draw is exactly the 75.00 percent line"
    )


# ── The four-hop draw-down cascade of a blend execution ──────────────


def _setup_approved_full_draw_trial():
    """Two housed AGING lots and an APPROVED trial that will drain lot_b."""
    base = setup_two_aging_lots(gallons_a=2000, gallons_b=1000)
    return setup_approved_blend_trial(
        scenario=base, draw_a=750.00, draw_b=866.25, declared_loss_pct=2.00
    )


def test_blend_execution_consumes_the_fully_drawn_lot_and_releases_its_allocation(
    api, facility_admin_headers
):
    """PRD 3.5: "In the first, each source lot has its component volume
    subtracted from its `volume_gallons`; a source lot drawn to exactly zero
    gallons moves `AGING` to `CONSUMED` and takes the new blend lot's identifier
    as its `parent_lot_id`."
    PRD 3.5: "In the second, each source lot that just entered `CONSUMED` forces
    its own `COMMITTED` allocation — the one whose `lot_id` names that lot — to
    move `COMMITTED` to `RELEASED`, stamping `released_at` and computing
    `occupied_days`."

    Design: Difficulty/transitive_cascade/blend_execute_cascade_lot_to_allocation_to_vessel_to_contract
    """
    scenario = _setup_approved_full_draw_trial()
    before = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert before["gallons_allocated"] == pytest.approx(3000.00, abs=0.01)

    executed = execute_blend_trial(
        scenario["trial"]["id"], scenario["contract"]["id"], scenario["rep_headers"]
    )
    blend_lot_id = executed["result_lot_id"]

    drained = validate_success(api.get_lot(scenario["lot_b"]["id"], facility_admin_headers))
    assert_lot(drained)
    assert drained["volume_gallons"] == pytest.approx(0.00, abs=0.01)
    assert drained["production_status"] == "CONSUMED"
    assert drained["parent_lot_id"] == blend_lot_id

    allocation = validate_success(
        api.get_vessel_allocation(scenario["allocation_b"]["id"], facility_admin_headers)
    )
    assert_vessel_allocation(allocation)
    assert allocation["status"] == "RELEASED"
    assert allocation["released_at"] == "2026-09-01T00:00:00.000Z"


def test_blend_execution_dirties_the_freed_vessel_and_recomputes_the_counters(
    api, facility_admin_headers
):
    """PRD 3.5: "In the third, each allocation that just entered `RELEASED` sets
    its vessel's `condition` to `DIRTY` and its `last_released_at` to that
    allocation's `end_at`, incrementing the vessel's `version`."
    PRD 3.5: "In the fourth, each contract behind those vessels recomputes
    `gallons_allocated` and `barrel_slots_used` from the allocations surviving
    in `RESERVED` or `COMMITTED`, incrementing the contract's `version`."

    Design: Difficulty/transitive_cascade/blend_execute_cascade_lot_to_allocation_to_vessel_to_contract
    """
    scenario = _setup_approved_full_draw_trial()

    execute_blend_trial(
        scenario["trial"]["id"], scenario["contract"]["id"], scenario["rep_headers"]
    )

    freed_vessel = validate_success(
        api.get_vessel(scenario["vessel_b"]["id"], facility_admin_headers)
    )
    assert_vessel(freed_vessel)
    assert freed_vessel["condition"] == "DIRTY"
    assert freed_vessel["last_released_at"] == "2026-11-01T00:00:00.000Z"

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(2000.00, abs=0.01), (
        f"3000.00 less the freed 1000-gallon allocation, got "
        f"{contract['gallons_allocated']}"
    )

    partial = validate_success(api.get_lot(scenario["lot_a"]["id"], facility_admin_headers))
    assert partial["volume_gallons"] == pytest.approx(815.00, abs=0.01)
    assert partial["production_status"] == "AGING", "a partial draw breaks no link"
    assert partial["parent_lot_id"] is None

    kept = validate_success(
        api.get_vessel_allocation(scenario["allocation_a"]["id"], facility_admin_headers)
    )
    assert kept["status"] == "COMMITTED"
    still_clean = validate_success(
        api.get_vessel(scenario["vessel_a"]["id"], facility_admin_headers)
    )
    assert still_clean["condition"] == "CLEAN"


def test_blend_execution_mints_the_result_lot_with_its_projected_figures(
    api, facility_admin_headers
):
    """PRD 3.5: "On success a new lot is minted with `origin` `BLEND`, its
    `lot_code` taken from the trial's `target_lot_code`, the trial's
    `contract_id`, `volume_gallons` set to `projected_blend_gallons`,
    `loss_gallons` set to `projected_loss_gallons`, `alcohol_pct` set to
    `projected_alcohol_pct`, `varietal_label` set to
    `projected_varietal_label` and `appellation_label` set to
    `projected_appellation_label`, its `varietal` and `appellation` set to the
    dominant values the projection found, a null `brix_at_crush` and an empty
    `source_intake_ids`, `production_status` `AGING` with `aging_start_at`
    stamped from the logical clock, and `bond_status` `IN_BOND`."

    Design: Difficulty/transitive_cascade/blend_execute_cascade_lot_to_allocation_to_vessel_to_contract
    """
    scenario = _setup_approved_full_draw_trial()

    executed = execute_blend_trial(
        scenario["trial"]["id"], scenario["contract"]["id"], scenario["rep_headers"]
    )
    assert executed["status"] == "EXECUTED"

    blend_lot = validate_success(
        api.get_lot(executed["result_lot_id"], facility_admin_headers)
    )
    assert_lot(blend_lot)
    assert blend_lot["origin"] == "BLEND"
    assert blend_lot["lot_code"] == "BLEND-26-01"
    assert blend_lot["volume_gallons"] == pytest.approx(1583.92, abs=0.01), (
        f"1616.25 less the 32.33-gallon declared loss, got "
        f"{blend_lot['volume_gallons']}"
    )
    assert blend_lot["loss_gallons"] == pytest.approx(32.33, abs=0.01)
    assert blend_lot["production_status"] == "AGING"
    assert blend_lot["bond_status"] == "IN_BOND"
    assert blend_lot["brix_at_crush"] is None
    assert blend_lot["source_intake_ids"] == []
    assert blend_lot["varietal_label"] == "RED_BLEND", (
        "MERLOT leads at 53.60 percent, short of the 75.00 percent line"
    )
    assert blend_lot["appellation_label"] == "OAKVILLE", (
        "both components are OAKVILLE fruit, a 100.00 percent share"
    )


# ── Unwind as a true compensation ───────────────────────────────────


def _list_contract_lots(api, contract_id, headers):
    rows, _ = validate_paginated(
        api.list_lots(headers, params={"contract_id": contract_id, "limit": 100})
    )
    return rows


def test_unwind_restores_the_source_lots_and_empties_the_result_lot(
    api, facility_admin_headers
):
    """PRD 3.5: "A permitted unwind is a true compensation: each source lot's
    `volume_gallons` is restored by exactly the component volume drawn at
    execution, each source lot's `parent_lot_id` returns to null, and a source
    lot sitting in `CONSUMED` returns to `AGING` — the only path out of that
    terminal production state."
    PRD 3.5: "The result lot is emptied, with `volume_gallons` and
    `loss_gallons` set to 0, `production_status` set to `CONSUMED` and
    `component_manifest` set to an empty array. The trial moves to `UNWOUND`,
    which is terminal, and its `result_lot_id` returns to null."

    Design: Difficulty/compensating_invariant/blend_unwind_conserves_contract_gallons_plus_losses
    """
    scenario = _setup_approved_full_draw_trial()
    executed = execute_blend_trial(
        scenario["trial"]["id"], scenario["contract"]["id"], scenario["rep_headers"]
    )
    blend_lot_id = executed["result_lot_id"]

    unwound = validate_success(
        api.blend_trial_transition(
            scenario["trial"]["id"], {"action": "UNWIND"}, facility_admin_headers
        )
    )
    assert unwound["status"] == "UNWOUND"
    assert unwound["result_lot_id"] is None

    lot_a = validate_success(api.get_lot(scenario["lot_a"]["id"], facility_admin_headers))
    assert lot_a["volume_gallons"] == pytest.approx(1565.00, abs=0.01)
    assert lot_a["loss_gallons"] == pytest.approx(0.00, abs=0.01)

    lot_b = validate_success(api.get_lot(scenario["lot_b"]["id"], facility_admin_headers))
    assert lot_b["volume_gallons"] == pytest.approx(866.25, abs=0.01)
    assert lot_b["loss_gallons"] == pytest.approx(0.00, abs=0.01)
    assert lot_b["production_status"] == "AGING", (
        "unwinding is the only path out of CONSUMED"
    )
    assert lot_b["parent_lot_id"] is None

    blend_lot = validate_success(api.get_lot(blend_lot_id, facility_admin_headers))
    assert blend_lot["volume_gallons"] == pytest.approx(0.00, abs=0.01)
    assert blend_lot["loss_gallons"] == pytest.approx(0.00, abs=0.01)
    assert blend_lot["production_status"] == "CONSUMED"
    assert blend_lot["component_manifest"] == []


def test_contract_gallons_plus_losses_survive_the_execute_and_the_unwind(
    api, facility_admin_headers
):
    """PRD 2.8: "Within a contract, the total across its lots of
    `volume_gallons` plus `loss_gallons` is unchanged by executing a blend and
    unchanged again by unwinding one."
    PRD 3.5: "The client's `bond_gallons_in_bond` is recomputed, and the
    contract-level conservation invariant of §2.8 holds across the whole
    operation."

    Design: Difficulty/compensating_invariant/blend_unwind_conserves_contract_gallons_plus_losses
    """
    scenario = _setup_approved_full_draw_trial()
    contract_id = scenario["contract"]["id"]

    before = contract_gallons_invariant(
        _list_contract_lots(api, contract_id, facility_admin_headers)
    )
    assert before == pytest.approx(2431.25, abs=0.01), (
        f"1565.00 + 866.25 gallons before the execute, got {before}"
    )

    execute_blend_trial(
        scenario["trial"]["id"], contract_id, scenario["rep_headers"]
    )
    during = contract_gallons_invariant(
        _list_contract_lots(api, contract_id, facility_admin_headers)
    )
    assert during == pytest.approx(2431.25, abs=0.01), (
        f"executing the blend moves wine without creating or destroying it, got {during}"
    )

    validate_success(
        api.blend_trial_transition(
            scenario["trial"]["id"], {"action": "UNWIND"}, facility_admin_headers
        )
    )
    after = contract_gallons_invariant(
        _list_contract_lots(api, contract_id, facility_admin_headers)
    )
    assert after == pytest.approx(2431.25, abs=0.01), (
        f"the compensation must leave zero drift, got {after}"
    )

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["bond_gallons_in_bond"] == pytest.approx(2431.25, abs=0.01)
