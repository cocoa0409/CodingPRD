"""API client: one method per endpoint declared in PRD section 4."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ── Restaurants ──────────────────────────────────────────────────────────
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/api/restaurants", payload, headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/api/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/api/restaurants/{restaurant_id}", headers=headers)

    def list_restaurant_orders(self, restaurant_id, headers, params=None):
        return self._request(
            "GET", f"/api/restaurants/{restaurant_id}/orders", headers=headers, params=params
        )

    def get_throughput(self, restaurant_id, headers, params=None):
        return self._request(
            "GET", f"/api/restaurants/{restaurant_id}/throughput", headers=headers, params=params
        )

    # ── Assembly lines ───────────────────────────────────────────────────────
    def create_assembly_line(self, payload, headers):
        return self._request("POST", "/api/assembly-lines", payload, headers)

    def list_assembly_lines(self, headers, params=None):
        return self._request("GET", "/api/assembly-lines", headers=headers, params=params)

    def get_assembly_line(self, line_id, headers):
        return self._request("GET", f"/api/assembly-lines/{line_id}", headers=headers)

    def pause_line(self, line_id, headers):
        return self._request("POST", f"/api/assembly-lines/{line_id}/pause", {}, headers)

    def resume_line(self, line_id, headers):
        return self._request("POST", f"/api/assembly-lines/{line_id}/resume", {}, headers)

    def list_line_hoppers(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/api/assembly-lines/{line_id}/hoppers", headers=headers, params=params
        )

    def list_line_sanitation_cycles(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/api/assembly-lines/{line_id}/sanitation-cycles", headers=headers, params=params
        )

    # ── Ingredients ──────────────────────────────────────────────────────────
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/api/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/api/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/api/ingredients/{ingredient_id}", headers=headers)

    def eighty_six_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/eighty-six", {}, headers)

    def restore_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/restore", {}, headers)

    # ── Recipes ──────────────────────────────────────────────────────────────
    def create_recipe(self, payload, headers):
        return self._request("POST", "/api/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/api/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/api/recipes/{recipe_id}", headers=headers)

    def list_recipe_orders(self, recipe_id, headers, params=None):
        return self._request(
            "GET", f"/api/recipes/{recipe_id}/orders", headers=headers, params=params
        )

    # ── Hoppers ──────────────────────────────────────────────────────────────
    def create_hopper(self, payload, headers):
        return self._request("POST", "/api/hoppers", payload, headers)

    def list_hoppers(self, headers, params=None):
        return self._request("GET", "/api/hoppers", headers=headers, params=params)

    def get_hopper(self, hopper_id, headers):
        return self._request("GET", f"/api/hoppers/{hopper_id}", headers=headers)

    def load_hopper(self, hopper_id, payload, headers):
        return self._request("POST", f"/api/hoppers/{hopper_id}/load", payload, headers)

    def report_sensor_reading(self, hopper_id, payload, headers):
        return self._request(
            "POST", f"/api/hoppers/{hopper_id}/sensor-reading", payload, headers
        )

    def create_calibration_adjustment(self, hopper_id, payload, headers):
        return self._request(
            "POST", f"/api/hoppers/{hopper_id}/calibration-adjustments", payload, headers
        )

    def list_calibration_adjustments(self, hopper_id, headers, params=None):
        return self._request(
            "GET", f"/api/hoppers/{hopper_id}/calibration-adjustments", headers=headers, params=params
        )

    def list_hopper_portion_verifications(self, hopper_id, headers, params=None):
        return self._request(
            "GET", f"/api/hoppers/{hopper_id}/portion-verifications", headers=headers, params=params
        )

    def list_hopper_refill_tasks(self, hopper_id, headers, params=None):
        return self._request(
            "GET", f"/api/hoppers/{hopper_id}/refill-tasks", headers=headers, params=params
        )

    # ── Refill tasks ─────────────────────────────────────────────────────────
    def create_refill_task(self, payload, headers):
        return self._request("POST", "/api/refill-tasks", payload, headers)

    def list_refill_tasks(self, headers, params=None):
        return self._request("GET", "/api/refill-tasks", headers=headers, params=params)

    def get_refill_task(self, task_id, headers):
        return self._request("GET", f"/api/refill-tasks/{task_id}", headers=headers)

    def start_refill_task(self, task_id, headers):
        return self._request("POST", f"/api/refill-tasks/{task_id}/start", {}, headers)

    def complete_refill_task(self, task_id, headers):
        return self._request("POST", f"/api/refill-tasks/{task_id}/complete", {}, headers)

    def cancel_refill_task(self, task_id, headers):
        return self._request("POST", f"/api/refill-tasks/{task_id}/cancel", {}, headers)

    # ── Prep batches ─────────────────────────────────────────────────────────
    def create_prep_batch(self, payload, headers):
        return self._request("POST", "/api/prep-batches", payload, headers)

    def list_prep_batches(self, headers, params=None):
        return self._request("GET", "/api/prep-batches", headers=headers, params=params)

    def get_prep_batch(self, batch_id, headers):
        return self._request("GET", f"/api/prep-batches/{batch_id}", headers=headers)

    def mark_prep_batch_ready(self, batch_id, headers):
        return self._request("POST", f"/api/prep-batches/{batch_id}/mark-ready", {}, headers)

    def expire_sweep_prep_batches(self, headers):
        return self._request("POST", "/api/prep-batches/expire-sweep", {}, headers)

    # ── Orders ───────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def start_order_assembly(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/start-assembly", {}, headers)

    def submit_order_verification(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/submit-verification", payload, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    def reroute_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/reroute", payload, headers)

    def list_order_portion_verifications(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/portion-verifications", headers=headers, params=params
        )

    # ── Substitution rules ───────────────────────────────────────────────────
    def create_substitution_rule(self, payload, headers):
        return self._request("POST", "/api/substitution-rules", payload, headers)

    def list_substitution_rules(self, headers, params=None):
        return self._request("GET", "/api/substitution-rules", headers=headers, params=params)

    def get_substitution_rule(self, rule_id, headers):
        return self._request("GET", f"/api/substitution-rules/{rule_id}", headers=headers)

    def activate_substitution_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/api/substitution-rules/{rule_id}/activate", {}, headers
        )

    def reject_substitution_rule(self, rule_id, headers):
        return self._request("POST", f"/api/substitution-rules/{rule_id}/reject", {}, headers)

    def retire_substitution_rule(self, rule_id, headers):
        return self._request("POST", f"/api/substitution-rules/{rule_id}/retire", {}, headers)

    # ── Sanitation cycles ────────────────────────────────────────────────────
    def create_sanitation_cycle(self, payload, headers):
        return self._request("POST", "/api/sanitation-cycles", payload, headers)

    def list_sanitation_cycles(self, headers, params=None):
        return self._request("GET", "/api/sanitation-cycles", headers=headers, params=params)

    def get_sanitation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/sanitation-cycles/{cycle_id}", headers=headers)

    def start_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/sanitation-cycles/{cycle_id}/start", {}, headers)

    def complete_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/sanitation-cycles/{cycle_id}/complete", {}, headers)

    def abort_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/sanitation-cycles/{cycle_id}/abort", {}, headers)

    # ── Labor assignments ────────────────────────────────────────────────────
    def create_labor_assignment(self, payload, headers):
        return self._request("POST", "/api/labor-assignments", payload, headers)

    def list_labor_assignments(self, headers, params=None):
        return self._request("GET", "/api/labor-assignments", headers=headers, params=params)

    def get_labor_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/labor-assignments/{assignment_id}", headers=headers)

    # ── Portion verifications (analytics view) ───────────────────────────────
    def list_portion_verifications(self, headers, params=None):
        return self._request(
            "GET", "/api/portion-verifications", headers=headers, params=params
        )

    def get_portion_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/api/portion-verifications/{verification_id}", headers=headers
        )


api_client = ApiClient()
