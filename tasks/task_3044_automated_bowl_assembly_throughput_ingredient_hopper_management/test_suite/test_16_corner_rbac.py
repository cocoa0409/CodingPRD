"""Corner — RBAC: role gates on mark-ready, calibration approval, and the
throughput report."""

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    make_line_operator_headers,
    validate_error,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    submit_verification_payload,
    create_prep_batch_payload,
    calibration_adjustment_payload,
)


class TestCustomerCannotMarkBatchReady:
    def test_customer_mark_ready_rejected(self, api):
        """PRD §4: "| POST | `/api/prep-batches/{id}/mark-ready` | Mark an
        IN_PREP batch READY; triggers the allocation waterfall | PrepCook |"
        PRD §2.1: "Once authenticated, the acting role must be permitted for the
        target endpoint; a role attempting an operation reserved for another
        role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_customer_cannot_mark_batch_ready
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        response = api.mark_prep_batch_ready(batch["id"], CUSTOMER_HEADERS)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        assert after["status"] == "IN_PREP"


class TestLineOperatorCannotApproveCalibration:
    def test_line_operator_calibration_approval_rejected(self, api):
        """PRD §4: "| POST | `/api/hoppers/{id}/calibration-adjustments` |
        Approve a calibration adjustment on a QUARANTINED hopper | QualityLead |"
        PRD §2.1: "a role attempting an operation reserved for another role is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_line_operator_cannot_approve_calibration
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM", line_type="MANUAL"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=5000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(2000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        verifier = make_line_operator_headers("op_verifier_1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "QUARANTINED"

        response = api.create_calibration_adjustment(
            hopper["id"], calibration_adjustment_payload(0.95), LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert after["status"] == "QUARANTINED"


class TestThroughputRoleGate:
    def test_customer_cannot_read_throughput(self, api):
        """PRD §4: "| GET | `/api/restaurants/{id}/throughput` | Throughput and
        queue-time metrics per line over a half-open window | OpsAdmin,
        ShiftManager |"
        PRD §2.1: "a role attempting an operation reserved for another role is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_shift_manager_can_read_throughput_customer_cannot
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        response = api.get_throughput(
            rest["id"], CUSTOMER_HEADERS,
            params={"from_iso8601": "2026-09-01T00:00:00Z",
                    "to_iso8601": "2026-09-01T01:00:00Z"})
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
