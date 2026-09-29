"""API client: one method per endpoint defined in the PRD.

Every business resource lives at its own top-level collection beneath the
``/sop`` prefix; relationships travel as identifier fields in request bodies
and as filters on list reads.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Product families ----------------
    def create_product_family(self, payload, headers):
        return self._request("POST", "/sop/product-families", payload, headers)

    def get_product_family(self, family_id, headers):
        return self._request(
            "GET", f"/sop/product-families/{family_id}", headers=headers
        )

    def list_product_families(self, headers, params=None):
        return self._request(
            "GET", "/sop/product-families", headers=headers, params=params
        )

    # ---------------- Items ----------------
    def create_item(self, payload, headers):
        return self._request("POST", "/sop/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/sop/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/sop/items", headers=headers, params=params)

    def reset_inventory_policy(self, item_id, payload, headers):
        return self._request(
            "POST", f"/sop/items/{item_id}/inventory-policy", payload, headers
        )

    def transition_item_lifecycle(self, item_id, payload, headers):
        return self._request(
            "POST", f"/sop/items/{item_id}/lifecycle-transitions", payload, headers
        )

    # ---------------- Customers ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/sop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/sop/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/sop/customers", headers=headers, params=params)

    # ---------------- Capacity blocks ----------------
    def create_capacity_block(self, payload, headers):
        return self._request("POST", "/sop/capacity-blocks", payload, headers)

    def get_capacity_block(self, block_id, headers):
        return self._request(
            "GET", f"/sop/capacity-blocks/{block_id}", headers=headers
        )

    def list_capacity_blocks(self, headers, params=None):
        return self._request(
            "GET", "/sop/capacity-blocks", headers=headers, params=params
        )

    # ---------------- Promotions ----------------
    def create_promotion(self, payload, headers):
        return self._request("POST", "/sop/promotions", payload, headers)

    def approve_promotion(self, promotion_id, headers, payload=None):
        return self._request(
            "POST", f"/sop/promotions/{promotion_id}/approve", payload or {}, headers
        )

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/sop/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/sop/promotions", headers=headers, params=params)

    # ---------------- Planning cycles ----------------
    def create_planning_cycle(self, payload, headers):
        return self._request("POST", "/sop/planning-cycles", payload, headers)

    def transition_planning_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/sop/planning-cycles/{cycle_id}/transitions", payload, headers
        )

    def get_planning_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/sop/planning-cycles/{cycle_id}", headers=headers
        )

    def list_planning_cycles(self, headers, params=None):
        return self._request(
            "GET", "/sop/planning-cycles", headers=headers, params=params
        )

    def get_cycle_accuracy_summary(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/sop/planning-cycles/{cycle_id}/accuracy-summary",
            headers=headers,
            params=params,
        )

    # ---------------- Demand forecasts ----------------
    def create_demand_forecast(self, payload, headers):
        return self._request("POST", "/sop/demand-forecasts", payload, headers)

    def transition_demand_forecast(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/sop/demand-forecasts/{forecast_id}/transitions", payload, headers
        )

    def get_demand_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/sop/demand-forecasts/{forecast_id}", headers=headers
        )

    def list_demand_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/sop/demand-forecasts", headers=headers, params=params
        )

    # ---------------- Consensus adjustments ----------------
    def create_consensus_adjustment(self, payload, headers):
        return self._request("POST", "/sop/consensus-adjustments", payload, headers)

    def review_consensus_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST",
            f"/sop/consensus-adjustments/{adjustment_id}/reviews",
            payload,
            headers,
        )

    def resubmit_consensus_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST",
            f"/sop/consensus-adjustments/{adjustment_id}/resubmit",
            payload,
            headers,
        )

    def get_consensus_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/sop/consensus-adjustments/{adjustment_id}", headers=headers
        )

    def list_consensus_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/sop/consensus-adjustments", headers=headers, params=params
        )

    # ---------------- Supply plans ----------------
    def create_supply_plan(self, payload, headers):
        return self._request("POST", "/sop/supply-plans", payload, headers)

    def ration_supply_plan(self, supply_plan_id, headers, payload=None):
        return self._request(
            "POST", f"/sop/supply-plans/{supply_plan_id}/ration", payload or {}, headers
        )

    def get_supply_plan(self, supply_plan_id, headers):
        return self._request(
            "GET", f"/sop/supply-plans/{supply_plan_id}", headers=headers
        )

    def list_supply_plans(self, headers, params=None):
        return self._request("GET", "/sop/supply-plans", headers=headers, params=params)

    # ---------------- Allocations ----------------
    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/sop/allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/sop/allocations", headers=headers, params=params)

    # ---------------- Scenarios ----------------
    def create_scenario(self, payload, headers):
        return self._request("POST", "/sop/scenarios", payload, headers)

    def evaluate_scenario(self, scenario_id, headers, payload=None):
        return self._request(
            "POST", f"/sop/scenarios/{scenario_id}/evaluate", payload or {}, headers
        )

    def select_scenario(self, scenario_id, payload, headers):
        return self._request(
            "POST", f"/sop/scenarios/{scenario_id}/select", payload, headers
        )

    def get_scenario(self, scenario_id, headers):
        return self._request("GET", f"/sop/scenarios/{scenario_id}", headers=headers)

    def list_scenarios(self, headers, params=None):
        return self._request("GET", "/sop/scenarios", headers=headers, params=params)

    # ---------------- Accuracy records ----------------
    def create_accuracy_record(self, payload, headers):
        return self._request("POST", "/sop/accuracy-records", payload, headers)

    def get_accuracy_record(self, record_id, headers):
        return self._request(
            "GET", f"/sop/accuracy-records/{record_id}", headers=headers
        )

    def list_accuracy_records(self, headers, params=None):
        return self._request(
            "GET", "/sop/accuracy-records", headers=headers, params=params
        )

    # ---------------- Logical clock ----------------
    def set_current_utc(self, payload, headers=None):
        """The logical-clock capability is exempt from the header authentication
        and the role check, so headers are optional."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
