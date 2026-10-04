"""Cyclic RawLot states and FinishedBatch parallel status dimensions."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_supplier, create_received_lot, post_test,
    disposition_lot, setup_produced_batch, recall_case_payload, get_batch,
)


def _walk_quarantine_cycle(lot_id):
    """RECEIVED -> IN_TEST -> QUARANTINED -> IN_TEST -> ACCEPTED."""
    t1 = post_test(lot_id, "MICRO", 40000)
    after_first = validate_success(
        api_client.get_lot(lot_id, TEST_USERS["quality_manager_headers"]), 200)
    q = disposition_lot(lot_id, "QUARANTINE", reason="odor anomaly")
    t2 = post_test(lot_id, "MOISTURE", 9.0)
    after_retest = validate_success(
        api_client.get_lot(lot_id, TEST_USERS["quality_manager_headers"]), 200)
    t3 = post_test(lot_id, "ADULTERANT_SCREEN", 0.5)
    accepted = disposition_lot(lot_id, "ACCEPT")
    return {"t1": t1, "after_first": after_first, "quarantined": q,
            "t2": t2, "after_retest": after_retest, "t3": t3,
            "accepted": accepted}


class TestRawLotQuarantineRetestCycle:
    def test_quarantine_retest_cycle_state_walk(self, api):
        """PRD §3.2: "The very first test recorded on a `RECEIVED` lot moves it
        to `IN_TEST`." PRD §3.2: "`QUARANTINE` moves an `IN_TEST` lot to
        `QUARANTINED`." PRD §3.2: "A test posted while the lot is `QUARANTINED`
        — a retest — moves it back to `IN_TEST`."

        The lot re-enters IN_TEST from QUARANTINED rather than terminating;
        the final ACCEPT lands it in ACCEPTED.

        Design: Difficulty/non_linear_state_machine/raw_lot_quarantine_retest_cycle
        """
        supplier = create_supplier(name="Aegean Herbs", origin_country="GR")
        lot = create_received_lot(supplier["id"], spice_code="OREGANO",
                                  origin_region="Lesvos", quantity_kg=50,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150,
                                  allergen_profile="MUSTARD")
        assert lot["status"] == "RECEIVED"
        w = _walk_quarantine_cycle(lot["id"])
        assert w["after_first"]["status"] == "IN_TEST"
        assert w["quarantined"]["status"] == "QUARANTINED"
        assert w["after_retest"]["status"] == "IN_TEST"
        assert w["accepted"]["status"] == "ACCEPTED"

    def test_accept_gate_uses_suite_accumulated_across_visits(self, api):
        """PRD §3.2: "the lot must carry at least one recorded `PASS` for each
        member of the required suite — `MICRO`, `ADULTERANT_SCREEN`, and
        `MOISTURE` — else `ERR_TEST_SUITE_INCOMPLETE` (HTTP 409)." PRD §3.2:
        "A lot's lifecycle is cyclic by design: quarantine and retest may
        iterate any number of times before the terminal `REJECTED` state".

        All three tests posted across two separate IN_TEST visits are PASS, so
        the final ACCEPT succeeds.

        Design: Difficulty/non_linear_state_machine/raw_lot_quarantine_retest_cycle
        """
        supplier = create_supplier(name="Aegean Herbs", origin_country="GR")
        lot = create_received_lot(supplier["id"], spice_code="OREGANO",
                                  origin_region="Lesvos", quantity_kg=50,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150,
                                  allergen_profile="MUSTARD")
        w = _walk_quarantine_cycle(lot["id"])
        assert w["t1"]["result"] == "PASS"
        assert w["t2"]["result"] == "PASS"
        assert w["t3"]["result"] == "PASS"
        assert w["accepted"]["status"] == "ACCEPTED"
        resp = api_client.list_tests(lot["id"],
                                     TEST_USERS["quality_manager_headers"])
        tests = get_success_data(resp)
        assert len(tests) == 3


class TestFinishedBatchParallelDimensions:
    def test_manual_hold_blocks_ship_commercial_untouched(self, api):
        """PRD §3.6: "a `QualityManager` may place a `CLEAR` batch on manual
        hold, optionally attaching a `note`: the batch's `quality_status`
        becomes `QUALITY_HOLD` with `quality_hold_cause` set to `MANUAL` and
        `quality_hold_lot_id` set to null." PRD §3.6: "its `quality_status`
        must be `CLEAR` and no `INITIATED` recall case may list the batch
        among its `affected_batch_ids` (else `ERR_BATCH_NOT_SHIPPABLE`, HTTP
        409)".

        The quality dimension moves while commercial_status stays CREATED, and
        the failed ship does not move the commercial dimension.

        Design: Difficulty/non_linear_state_machine/finished_batch_parallel_dimensions
        """
        s = setup_produced_batch(product_code="STEAK-7")
        batch = s["batch"]
        assert batch["commercial_status"] == "CREATED"
        assert batch["quality_status"] == "CLEAR"
        resp = api_client.hold_batch(batch["id"],
                                     TEST_USERS["quality_manager_headers"],
                                     note="retail complaint")
        held = validate_success(resp, 200)
        assert held["quality_status"] == "QUALITY_HOLD"
        assert held["quality_hold_cause"] == "MANUAL"
        assert held["quality_hold_lot_id"] is None
        assert held["commercial_status"] == "CREATED"
        resp = api_client.ship_batch(batch["id"],
                                     TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SHIPPABLE)
        after = get_batch(batch["id"])
        assert after["commercial_status"] == "CREATED"

    def test_recall_close_terminates_quality_dimension_only(self, api):
        """PRD §3.7: "each affected batch sitting in `QUALITY_HOLD` moves to
        `RECALLED` when its `brand_type` is `BRANDED`, or to `WITHDRAWN` when
        it is `PRIVATE_LABEL`". PRD §3.6: "A finished batch lives on two
        parallel and independent status dimensions."

        A BRANDED batch held manually, then covered by an initiated and closed
        recall, ends RECALLED while commercial_status remains CREATED.

        Design: Difficulty/non_linear_state_machine/finished_batch_parallel_dimensions
        """
        s = setup_produced_batch(product_code="STEAK-7")
        batch, la = s["batch"], s["lots"][0]
        resp = api_client.hold_batch(batch["id"],
                                     TEST_USERS["quality_manager_headers"],
                                     note="retail complaint")
        validate_success(resp, 200)
        resp = api_client.create_recall_case(
            recall_case_payload(trigger_type="LOT_SUSPECT", scope_policy="FINAL",
                                suspect_lot_id=la["id"]),
            TEST_USERS["recall_coordinator_headers"])
        case = validate_success(resp, 201)
        validate_success(api_client.initiate_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        validate_success(api_client.close_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        after = get_batch(batch["id"])
        assert after["quality_status"] == "RECALLED"
        assert after["commercial_status"] == "CREATED"
