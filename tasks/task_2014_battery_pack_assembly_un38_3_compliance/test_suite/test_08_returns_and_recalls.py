"""Return authorizations with safe discharge, and recall campaign cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_recall,
    approve_rma,
    begin_discharge,
    close_rma,
    complete_discharge,
    create_recall,
    create_return_authorization_payload,
    create_storage_location,
    get_battery_pack,
    get_program,
    get_recall,
    get_rma,
    get_storage_location,
    make_safety_officer_headers,
    receive_rma,
    setup_delivered_pack,
    setup_ready_to_store_pack,
    stage_pack,
    store_placement,
    validate_error,
    validate_success,
)


class TestReturnAuthorization:
    def test_approve_rejects_target_above_safe_ceiling(self, api):
        """PRD §3.9: "the `target_soc_percent` must not exceed the safe-discharge ceiling
        of 30.0 percent (`ERR_TARGET_SOC_TOO_HIGH`)".

        Design: Corner/validations/rma_target_soc_too_high
        """
        bundle = setup_delivered_pack()
        program_id = bundle["program"]["id"]
        assert bundle["pack"]["logistics_status"] == "DELIVERED"
        resp = api.create_return_authorization(
            program_id,
            create_return_authorization_payload(bundle["pack"]["id"], "DEFECT", 50.0),
            TEST_USERS["customer_service_headers"],
        )
        rma = validate_success(resp, 201)
        resp = api.approve_return_authorization(
            program_id, rma["id"], make_safety_officer_headers("so-rma-1")
        )
        validate_error(resp, ApiErrorId.ERR_TARGET_SOC_TOO_HIGH)
        assert get_rma(program_id, rma["id"])["status"] == "REQUESTED"

    def test_full_return_flow_ends_closed_with_pack_scrapped(self, api):
        """PRD §3.9: "it moves the RMA to `RECEIVED`, cascades the pack's logistics axis
        `DELIVERED` → `RETURNED`, and sets the pack's `disposition` to `SCRAPPED`.
        Closing the RMA requires `RECEIVED` (`ERR_RMA_NOT_RECEIVED`) and moves it to
        terminal `CLOSED`."

        Design: Difficulty/compensating_invariant/pack_disposition_invariant_delivered_then_returned_leaves_pack_scrapped
        """
        bundle = setup_delivered_pack()
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        assert bundle["pack"]["disposition"] == "IN_SERVICE"

        rma = validate_success(
            api.create_return_authorization(
                program_id,
                create_return_authorization_payload(pack_id, "DEFECT", 25.0),
                TEST_USERS["customer_service_headers"],
            ),
            201,
        )
        approve_rma(program_id, rma["id"])
        begin_discharge(program_id, rma["id"])
        complete_discharge(program_id, rma["id"], 25.0)
        receive_rma(program_id, rma["id"])
        closed = close_rma(program_id, rma["id"])

        assert closed["status"] == "CLOSED"
        pack = get_battery_pack(program_id, pack_id)
        assert pack["logistics_status"] == "RETURNED"
        assert pack["disposition"] == "SCRAPPED"
        assert pack["is_safe_discharged"] is True

    def test_complete_discharge_drives_soc_band_low_under_plain_variant(self, api):
        """PRD §3.9: "Completion writes `actual_soc_after_discharge` from the measured
        value, drives the pack's `soc_percent` to the same figure, recomputes the pack's
        `soc_band` under the hysteresis variant when the flashed firmware supports it
        (§3.7), sets `is_safe_discharged` to true, moves the pack's `disposition` to
        `DISCHARGED`, and moves the RMA to `DISCHARGED`."
        PRD §3.7: "The plain variant of this assignment applies at pack creation and
        whenever the pack's flashed firmware does not support hysteresis." With a
        non-hysteresis firmware, discharge to 25.0 puts the pack in `SOC_LOW`.

        Design: Difficulty/compensating_invariant/pack_disposition_invariant_delivered_then_returned_leaves_pack_scrapped
        """
        bundle = setup_delivered_pack()
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        rma = validate_success(
            api.create_return_authorization(
                program_id,
                create_return_authorization_payload(pack_id, "WARRANTY", 25.0),
                TEST_USERS["customer_service_headers"],
            ),
            201,
        )
        approve_rma(program_id, rma["id"])
        begin_discharge(program_id, rma["id"])
        discharged = complete_discharge(program_id, rma["id"], 25.0)
        assert discharged["status"] == "DISCHARGED"
        assert discharged["actual_soc_after_discharge"] == pytest.approx(25.0)
        pack = get_battery_pack(program_id, pack_id)
        assert pack["soc_percent"] == pytest.approx(25.0)
        assert pack["soc_band"] == "SOC_LOW"
        assert pack["is_safe_discharged"] is True
        assert pack["disposition"] == "DISCHARGED"


class TestRecallCascade:
    def _stored_pack_with_recall(self, api):
        """READY_TO_STORE pack placed and STORED, plus a DRAFT CLASS_II recall scoped to
        its cell lot."""
        bundle = setup_ready_to_store_pack(storage_capacity_wh=10000)
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        location = create_storage_location(
            program_id, capacity_wh=5000, accepts_soc_band=["SOC_MID"]
        )
        placement = stage_pack(program_id, location["id"], pack_id)
        store_placement(program_id, placement["id"])
        assert get_storage_location(program_id, location["id"])["wh_occupied"] == pytest.approx(43.20)
        assert get_program(program_id)["wh_committed"] == pytest.approx(43.20)
        recall = create_recall(
            program_id, severity="CLASS_II", scope_lot_id=bundle["lot"]["id"]
        )
        return bundle, location, placement, recall

    def test_activation_captures_pack_and_marks_contained(self, api):
        """PRD §3.9: "Every captured pack has its `active_recall_id` set to the campaign
        and its `disposition` driven to `RECALLED_HOLD`; each captured pack currently at
        `READY_TO_STORE` fires its assembly transition to `RECALLED`, and
        `packs_contained` counts those whose assembly axis has reached `RECALLED`."

        Design: Difficulty/transitive_cascade/recall_activation_cascades_pack_placement_slot_program
        """
        bundle, location, placement, recall = self._stored_pack_with_recall(api)
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]

        activated = activate_recall(program_id, recall["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["packs_in_scope"] == 1
        assert activated["packs_contained"] == 1

        pack = get_battery_pack(program_id, pack_id)
        assert pack["assembly_status"] == "RECALLED"
        assert pack["active_recall_id"] == recall["id"]
        assert pack["disposition"] == "RECALLED_HOLD"
        assert pack["storage_location_id"] is None

    def test_activation_force_releases_placement_and_restores_ledgers(self, api):
        """PRD §3.9: "Captured packs currently `STAGED` or `STORED` are force-released —
        their placement moves to `RELEASED` and the slot's `wh_occupied` and the program's
        `wh_committed` are decremented accordingly — so recalled inventory never sits in
        rated storage. The program's `recall_count` increments by 1, and its
        `compliance_risk_index` drops by the severity weight (15, 8, or 3 per §2.7)
        multiplied by the capture count."
        CLASS_II weight 8 x 1 captured pack: 100 - 8 = 92.

        Design: Difficulty/transitive_cascade/recall_activation_cascades_pack_placement_slot_program
        """
        bundle, location, placement, recall = self._stored_pack_with_recall(api)
        program_id = bundle["program"]["id"]

        activate_recall(program_id, recall["id"])

        placement_after = validate_success(
            api.get_storage_placement(program_id, placement["id"], TEST_USERS["any_headers"])
        )
        assert placement_after["status"] == "RELEASED"
        assert get_storage_location(program_id, location["id"])["wh_occupied"] == pytest.approx(0)
        program = get_program(program_id)
        assert program["wh_committed"] == pytest.approx(0)
        assert program["recall_count"] == 1
        assert program["compliance_risk_index"] == 92
        assert get_recall(program_id, recall["id"])["status"] == "ACTIVE"
