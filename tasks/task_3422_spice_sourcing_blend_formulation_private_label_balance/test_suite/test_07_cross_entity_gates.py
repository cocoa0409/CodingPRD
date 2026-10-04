"""Cross-entity state gates: committed blend for scheduling, recall for ship."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_active_formula, create_blend_run,
    commit_blend_run, create_line, schedule_run, get_line_version,
    production_run_payload, setup_produced_batch, recall_case_payload,
    get_batch,
)


def _setup_draft_blend_gate():
    supplier, lots = setup_accepted_lots(costs=(100, 200, 300))
    formula = create_active_formula("GATE-1")
    br = create_blend_run(formula["id"], "COST_MIN", 100)  # left DRAFT
    line = create_line(name="Line-G")
    return {"formula": formula, "br": br, "line": line}


class TestProductionRunRequiresCommittedBlendRun:
    def test_draft_rejected_identical_payload_succeeds_after_commit(self, api):
        """PRD §3.5: "the `blend_run_id` (which must be `COMMITTED`, else
        `ERR_BLEND_RUN_NOT_COMMITTED`".

        While the blend run is DRAFT the schedule is rejected; once the same
        run commits, the identical payload succeeds (201).

        Design: Difficulty/cross_entity_state_dependency/production_run_requires_committed_blend_run
        """
        s = _setup_draft_blend_gate()
        version = get_line_version(s["line"]["id"])
        payload = production_run_payload(
            s["line"]["id"], s["formula"]["id"], s["br"]["id"], 100,
            "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", version)
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_BLEND_RUN_NOT_COMMITTED)
        commit_blend_run(s["br"]["id"])
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        run = validate_success(resp, 201)
        assert run["status"] == "SCHEDULED"

    def test_rejected_schedule_leaves_line_version_and_computes_none(self, api):
        """PRD §2.7: "A successful scheduling increments the line's `version`
        by 1, so every scheduling invalidates previously observed versions."
        PRD §3.5: "When there is no predecessor, the class is `NONE`."

        The rejected (DRAFT blend) attempt is not a successful scheduling, so
        the line version is unmoved; the accepted first run has a null
        predecessor and changeover class NONE.

        Design: Difficulty/cross_entity_state_dependency/production_run_requires_committed_blend_run
        """
        s = _setup_draft_blend_gate()
        version = get_line_version(s["line"]["id"])
        payload = production_run_payload(
            s["line"]["id"], s["formula"]["id"], s["br"]["id"], 100,
            "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", version)
        api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        assert get_line_version(s["line"]["id"]) == version
        commit_blend_run(s["br"]["id"])
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        run = validate_success(resp, 201)
        assert run["predecessor_run_id"] is None
        assert run["changeover_class_required"] == "NONE"


class TestBatchShipBlockedByInitiatedRecall:
    def _setup_covered_batch(self):
        s = setup_produced_batch(product_code="SHIP-1")
        resp = api_client.create_recall_case(
            recall_case_payload(trigger_type="LOT_SUSPECT", scope_policy="FINAL",
                                suspect_lot_id=s["lots"][0]["id"]),
            TEST_USERS["recall_coordinator_headers"])
        case = validate_success(resp, 201)
        initiated = validate_success(api_client.initiate_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        return s, case, initiated

    def test_ship_rejected_while_covering_recall_initiated(self, api):
        """PRD §3.6: "its `quality_status` must be `CLEAR` and no `INITIATED`
        recall case may list the batch among its `affected_batch_ids` (else
        `ERR_BATCH_NOT_SHIPPABLE`, HTTP 409)". PRD §3.7: "Scope is computed
        once, at initiation, and then frozen on the case."

        Initiation freezes scope to exactly the one batch carrying the suspect
        lot (100 kg) and holds it; the ship gate then rejects.

        Design: Difficulty/cross_entity_state_dependency/batch_ship_blocked_by_initiated_recall
        """
        s, case, initiated = self._setup_covered_batch()
        assert initiated["affected_batch_ids"] == [s["batch"]["id"]]
        assert initiated["affected_quantity_kg"] == pytest.approx(100.0)
        resp = api_client.ship_batch(s["batch"]["id"],
                                     TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SHIPPABLE)

    def test_ship_still_rejected_after_recall_close(self, api):
        """PRD §3.7: "each affected batch sitting in `QUALITY_HOLD` moves to
        `RECALLED` when its `brand_type` is `BRANDED`". PRD §3.6: "its
        `quality_status` must be `CLEAR` ... (else `ERR_BATCH_NOT_SHIPPABLE`,
        HTTP 409)".

        Closing the case moves the BRANDED batch to RECALLED (terminal for
        quality), so the ship gate keeps rejecting even after the case closes.

        Design: Difficulty/cross_entity_state_dependency/batch_ship_blocked_by_initiated_recall
        """
        s, case, _ = self._setup_covered_batch()
        validate_success(api_client.close_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        after = get_batch(s["batch"]["id"])
        assert after["quality_status"] == "RECALLED"
        assert after["commercial_status"] == "CREATED"
        resp = api_client.ship_batch(s["batch"]["id"],
                                     TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SHIPPABLE)
