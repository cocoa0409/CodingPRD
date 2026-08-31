"""API client: one method per endpoint published by the API."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Customer --------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def set_takeback_agreement(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/takeback-agreement", payload, headers
        )

    # ---- ComponentLot ----------------------------------------------------
    def create_component_lot(self, payload, headers):
        return self._request("POST", "/component-lots", payload, headers)

    def get_component_lot(self, lot_id, headers):
        return self._request("GET", f"/component-lots/{lot_id}", headers=headers)

    def list_component_lots(self, headers, params=None):
        return self._request("GET", "/component-lots", headers=headers, params=params)

    def quarantine_component_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/component-lots/{lot_id}/quarantine", payload, headers
        )

    def list_component_lot_draws(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/component-lots/{lot_id}/draws", headers=headers, params=params
        )

    # ---- ProductSpec -----------------------------------------------------
    def create_product_spec(self, payload, headers):
        return self._request("POST", "/product-specs", payload, headers)

    def get_product_spec(self, spec_id, headers):
        return self._request("GET", f"/product-specs/{spec_id}", headers=headers)

    def list_product_specs(self, headers, params=None):
        return self._request("GET", "/product-specs", headers=headers, params=params)

    def activate_product_spec(self, spec_id, headers):
        return self._request("POST", f"/product-specs/{spec_id}/activate", {}, headers)

    def withdraw_product_spec(self, spec_id, payload, headers):
        return self._request(
            "POST", f"/product-specs/{spec_id}/withdraw", payload, headers
        )

    def create_spec_change_request(self, spec_id, payload, headers):
        return self._request(
            "POST", f"/product-specs/{spec_id}/change-requests", payload, headers
        )

    # ---- BlendRecipe -----------------------------------------------------
    def create_blend_recipe(self, payload, headers):
        return self._request("POST", "/blend-recipes", payload, headers)

    def get_blend_recipe(self, recipe_id, headers):
        return self._request("GET", f"/blend-recipes/{recipe_id}", headers=headers)

    def list_blend_recipes(self, headers, params=None):
        return self._request("GET", "/blend-recipes", headers=headers, params=params)

    def list_recipe_components(self, recipe_id, headers, params=None):
        return self._request(
            "GET", f"/blend-recipes/{recipe_id}/components", headers=headers, params=params
        )

    def activate_blend_recipe(self, recipe_id, headers):
        return self._request("POST", f"/blend-recipes/{recipe_id}/activate", {}, headers)

    # ---- BlendTank -------------------------------------------------------
    def create_blend_tank(self, payload, headers):
        return self._request("POST", "/blend-tanks", payload, headers)

    def get_blend_tank(self, tank_id, headers):
        return self._request("GET", f"/blend-tanks/{tank_id}", headers=headers)

    def list_blend_tanks(self, headers, params=None):
        return self._request("GET", "/blend-tanks", headers=headers, params=params)

    def flush_blend_tank(self, tank_id, headers):
        return self._request("POST", f"/blend-tanks/{tank_id}/flush", {}, headers)

    # ---- BlendBatch ------------------------------------------------------
    def create_blend_batch(self, payload, headers):
        return self._request("POST", "/blend-batches", payload, headers)

    def get_blend_batch(self, batch_id, headers):
        return self._request("GET", f"/blend-batches/{batch_id}", headers=headers)

    def list_blend_batches(self, headers, params=None):
        return self._request("GET", "/blend-batches", headers=headers, params=params)

    def charge_blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/charge", payload, headers)

    def cancel_charge_blend_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/blend-batches/{batch_id}/cancel-charge", payload, headers
        )

    def complete_blend(self, batch_id, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/complete-blend", {}, headers)

    def release_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/release", {}, headers)

    def quarantine_blend_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/blend-batches/{batch_id}/quarantine", payload, headers
        )

    def rework_blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/rework", payload, headers)

    def dispose_blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/dispose", payload, headers)

    def waive_qc(self, batch_id, payload, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/waive-qc", payload, headers)

    def list_batch_component_draws(self, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/blend-batches/{batch_id}/component-draws",
            headers=headers,
            params=params,
        )

    def create_qc_result(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/blend-batches/{batch_id}/qc-results", payload, headers
        )

    def list_qc_results(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/blend-batches/{batch_id}/qc-results", headers=headers, params=params
        )

    def create_retain_sample(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/blend-batches/{batch_id}/retain-samples", payload, headers
        )

    def list_retain_samples(self, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/blend-batches/{batch_id}/retain-samples",
            headers=headers,
            params=params,
        )

    def dispose_retain_sample(self, retain_id, payload, headers):
        return self._request(
            "POST", f"/retain-samples/{retain_id}/dispose", payload, headers
        )

    # ---- ApprovalClaim ---------------------------------------------------
    def create_approval_claim(self, payload, headers):
        return self._request("POST", "/approval-claims", payload, headers)

    def get_approval_claim(self, claim_id, headers):
        return self._request("GET", f"/approval-claims/{claim_id}", headers=headers)

    def list_approval_claims(self, headers, params=None):
        return self._request("GET", "/approval-claims", headers=headers, params=params)

    def submit_approval_claim(self, claim_id, headers):
        return self._request("POST", f"/approval-claims/{claim_id}/submit", {}, headers)

    def decide_approval_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/approval-claims/{claim_id}/decision", payload, headers
        )

    def approval_claim_lifecycle(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/approval-claims/{claim_id}/lifecycle", payload, headers
        )

    # ---- PackageConfiguration -------------------------------------------
    def create_package_configuration(self, payload, headers):
        return self._request("POST", "/package-configurations", payload, headers)

    def get_package_configuration(self, config_id, headers):
        return self._request(
            "GET", f"/package-configurations/{config_id}", headers=headers
        )

    def list_package_configurations(self, headers, params=None):
        return self._request(
            "GET", "/package-configurations", headers=headers, params=params
        )

    def activate_package_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/package-configurations/{config_id}/activate", {}, headers
        )

    def retire_package_configuration(self, config_id, payload, headers):
        return self._request(
            "POST", f"/package-configurations/{config_id}/retire", payload, headers
        )

    def list_configuration_order_lines(self, config_id, headers, params=None):
        return self._request(
            "GET",
            f"/package-configurations/{config_id}/order-lines",
            headers=headers,
            params=params,
        )

    # ---- PackagingLine / PackagingRun ------------------------------------
    def create_packaging_line(self, payload, headers):
        return self._request("POST", "/packaging-lines", payload, headers)

    def get_packaging_line(self, line_id, headers):
        return self._request("GET", f"/packaging-lines/{line_id}", headers=headers)

    def list_packaging_lines(self, headers, params=None):
        return self._request("GET", "/packaging-lines", headers=headers, params=params)

    def set_packaging_line_service_status(self, line_id, payload, headers):
        return self._request(
            "POST", f"/packaging-lines/{line_id}/service-status", payload, headers
        )

    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/packaging-runs", payload, headers)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/packaging-runs/{run_id}", headers=headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/packaging-runs", headers=headers, params=params)

    def start_packaging_run(self, run_id, headers):
        return self._request("POST", f"/packaging-runs/{run_id}/start", {}, headers)

    def complete_packaging_run(self, run_id, payload, headers):
        return self._request("POST", f"/packaging-runs/{run_id}/complete", payload, headers)

    def cancel_packaging_run(self, run_id, payload, headers):
        return self._request("POST", f"/packaging-runs/{run_id}/cancel", payload, headers)

    # ---- Order / OrderLine ------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", {}, headers)

    def hold_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/hold", payload, headers)

    def resume_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/resume", {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/invoice", {}, headers)

    def void_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/void", payload, headers)

    def apply_takeback_credit(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/apply-takeback-credit", payload, headers
        )

    # ---- TakebackCollection ----------------------------------------------
    def create_takeback_collection(self, payload, headers):
        return self._request("POST", "/takeback-collections", payload, headers)

    def get_takeback_collection(self, collection_id, headers):
        return self._request(
            "GET", f"/takeback-collections/{collection_id}", headers=headers
        )

    def list_takeback_collections(self, headers, params=None):
        return self._request(
            "GET", "/takeback-collections", headers=headers, params=params
        )

    def collect_takeback(self, collection_id, payload, headers):
        return self._request(
            "POST", f"/takeback-collections/{collection_id}/collect", payload, headers
        )

    def assay_takeback(self, collection_id, payload, headers):
        return self._request(
            "POST", f"/takeback-collections/{collection_id}/assay", payload, headers
        )

    def credit_takeback(self, collection_id, headers):
        return self._request(
            "POST", f"/takeback-collections/{collection_id}/credit", {}, headers
        )

    # ---- SpecChangeRequest -----------------------------------------------
    def get_spec_change_request(self, request_id, headers):
        return self._request(
            "GET", f"/spec-change-requests/{request_id}", headers=headers
        )

    def list_spec_change_requests(self, headers, params=None):
        return self._request(
            "GET", "/spec-change-requests", headers=headers, params=params
        )

    def submit_spec_change_request(self, request_id, headers):
        return self._request(
            "POST", f"/spec-change-requests/{request_id}/submit", {}, headers
        )

    def viscosity_review(self, request_id, payload, headers):
        return self._request(
            "POST", f"/spec-change-requests/{request_id}/viscosity-review", payload, headers
        )

    def approval_review(self, request_id, payload, headers):
        return self._request(
            "POST", f"/spec-change-requests/{request_id}/approval-review", payload, headers
        )

    def make_spec_change_effective(self, request_id, headers):
        return self._request(
            "POST", f"/spec-change-requests/{request_id}/make-effective", {}, headers
        )

    def withdraw_spec_change_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/spec-change-requests/{request_id}/withdraw", payload, headers
        )


api_client = ApiClient()
