"""Recall case edges: empty frozen scope and suspect-shape validation."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_supplier, create_received_lot, recall_case_payload,
)


class TestRecallCaseEdges:
    def test_recall_initiate_empty_scope_allowed(self, api):
        """PRD §3.7: "an empty scope is legitimate — a case may initiate with
        an empty `affected_batch_ids`". PRD §3.7: "`affected_quantity_kg` is
        their summed `quantity_kg` in exact decimal arithmetic."

        The suspect lot never entered any batch: scope freezes to [] and 0 kg
        and the case still reaches INITIATED.

        Design: Corner/calculations/recall_initiate_empty_scope_allowed
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="CINNAMON",
                                  origin_region="Galle", quantity_kg=25,
                                  flavor_intensity_units=65.0,
                                  cost_per_kg_cents=400)
        resp = api_client.create_recall_case(
            recall_case_payload(trigger_type="REGULATORY",
                                scope_policy="PROVISIONAL",
                                suspect_lot_id=lot["id"]),
            TEST_USERS["recall_coordinator_headers"])
        case = validate_success(resp, 201)
        initiated = validate_success(api_client.initiate_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        assert initiated["status"] == "INITIATED"
        assert initiated["affected_batch_ids"] == []
        assert initiated["affected_quantity_kg"] == 0

    def test_recall_create_scope_shape_invalid(self, api):
        """PRD §3.7: "a `scope_policy` of `PROVISIONAL` or `FINAL`, and
        exactly one suspect reference — `suspect_lot_id` or
        `suspect_batch_id`; supplying both or neither, for any trigger type,
        is rejected with `ERR_RECALL_SCOPE_INVALID` (HTTP 422)."

        Design: Corner/validations/recall_create_scope_shape_invalid
        """
        resp = api_client.create_recall_case(
            recall_case_payload(trigger_type="LOT_SUSPECT",
                                scope_policy="FINAL"),
            TEST_USERS["recall_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_RECALL_SCOPE_INVALID)
