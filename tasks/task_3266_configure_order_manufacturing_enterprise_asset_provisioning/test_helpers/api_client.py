"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    # --- programs ---
    def create_program(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/programs", headers=headers, params=params)

    def lock_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/lock", {}, headers)

    def list_account_programs(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}/programs", headers=headers)

    # --- templates ---
    def create_template(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/templates", payload, headers)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/api/templates/{template_id}/publish", {}, headers)

    def list_program_templates(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}/templates", headers=headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/api/templates/{template_id}", headers=headers)

    def list_templates(self, headers, params=None):
        return self._request("GET", "/api/templates", headers=headers, params=params)

    # --- chassis models ---
    def create_chassis_model(self, payload, headers):
        return self._request("POST", "/api/chassis-models", payload, headers)

    def discontinue_chassis_model(self, chassis_id, headers):
        return self._request("POST", f"/api/chassis-models/{chassis_id}/discontinue", {}, headers)

    def get_chassis_model(self, chassis_id, headers):
        return self._request("GET", f"/api/chassis-models/{chassis_id}", headers=headers)

    # --- components ---
    def create_component(self, payload, headers):
        return self._request("POST", "/api/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/api/components/{component_id}", headers=headers)

    def restock_component(self, component_id, payload, headers):
        return self._request("POST", f"/api/components/{component_id}/restock", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/api/components", headers=headers, params=params)

    def discontinue_component(self, component_id, headers):
        return self._request("POST", f"/api/components/{component_id}/discontinue", {}, headers)

    # --- compatibility rules ---
    def create_compatibility_rule(self, payload, headers):
        return self._request("POST", "/api/compatibility-rules", payload, headers)

    def list_chassis_rules(self, chassis_id, headers):
        return self._request("GET", f"/api/chassis-models/{chassis_id}/compatibility-rules", headers=headers)

    def list_compatibility_rules(self, headers, params=None):
        return self._request("GET", "/api/compatibility-rules", headers=headers, params=params)

    def list_component_rules(self, component_id, headers):
        return self._request("GET", f"/api/components/{component_id}/compatibility-rules", headers=headers)

    # --- configurations ---
    def create_configuration(self, payload, headers):
        return self._request("POST", "/api/configurations", payload, headers)

    def get_configuration(self, config_id, headers):
        return self._request("GET", f"/api/configurations/{config_id}", headers=headers)

    def list_configurations(self, headers, params=None):
        return self._request("GET", "/api/configurations", headers=headers, params=params)

    def validate_configuration(self, config_id, headers):
        return self._request("POST", f"/api/configurations/{config_id}/validate", {}, headers)

    def lock_configuration(self, config_id, headers):
        return self._request("POST", f"/api/configurations/{config_id}/lock", {}, headers)

    def unlock_configuration(self, config_id, headers):
        return self._request("POST", f"/api/configurations/{config_id}/unlock", {}, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_account_orders(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}/orders", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/lines", headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def list_order_lines_all(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    # --- build jobs ---
    def get_build_job(self, job_id, headers):
        return self._request("GET", f"/api/build-jobs/{job_id}", headers=headers)

    def list_order_build_jobs(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/build-jobs", headers=headers)

    def list_build_jobs(self, headers, params=None):
        return self._request("GET", "/api/build-jobs", headers=headers, params=params)

    def allocate_build_job(self, job_id, headers):
        return self._request("POST", f"/api/build-jobs/{job_id}/allocate", {}, headers)

    def start_build_job(self, job_id, headers):
        return self._request("POST", f"/api/build-jobs/{job_id}/start", {}, headers)

    def complete_build_job(self, job_id, headers):
        return self._request("POST", f"/api/build-jobs/{job_id}/complete", {}, headers)

    # --- substitution requests ---
    def list_job_substitution_requests(self, job_id, headers):
        return self._request("GET", f"/api/build-jobs/{job_id}/substitution-requests", headers=headers)

    def get_substitution_request(self, sr_id, headers):
        return self._request("GET", f"/api/substitution-requests/{sr_id}", headers=headers)

    def list_substitution_requests(self, headers, params=None):
        return self._request("GET", "/api/substitution-requests", headers=headers, params=params)

    def approve_substitution(self, sr_id, headers):
        return self._request("POST", f"/api/substitution-requests/{sr_id}/approve", {}, headers)

    def reject_substitution(self, sr_id, headers):
        return self._request("POST", f"/api/substitution-requests/{sr_id}/reject", {}, headers)

    def repropose_substitution(self, sr_id, payload, headers):
        return self._request("POST", f"/api/substitution-requests/{sr_id}/repropose", payload, headers)

    # --- deployment waves ---
    def create_deployment_wave(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/deployment-waves", payload, headers)

    def list_order_waves(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/deployment-waves", headers=headers)

    def release_wave(self, wave_id, headers):
        return self._request("POST", f"/api/deployment-waves/{wave_id}/release", {}, headers)

    def ship_wave(self, wave_id, headers):
        return self._request("POST", f"/api/deployment-waves/{wave_id}/ship", {}, headers)

    def receive_wave(self, wave_id, headers):
        return self._request("POST", f"/api/deployment-waves/{wave_id}/receive", {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/api/deployment-waves/{wave_id}/cancel", {}, headers)

    # --- assets ---
    def list_line_assets(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}/assets", headers=headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/api/assets", headers=headers, params=params)

    def get_asset_report(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/asset-report", headers=headers)

    # --- support entitlements ---
    def create_support_entitlement(self, line_id, payload, headers):
        return self._request("POST", f"/api/order-lines/{line_id}/support-entitlements", payload, headers)

    def list_line_entitlements(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}/support-entitlements", headers=headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/api/support-entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/api/support-entitlements/{entitlement_id}", headers=headers)

    def cancel_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/api/support-entitlements/{entitlement_id}/cancel", {}, headers)

    # --- asset recovery requests ---
    def create_recovery_request(self, payload, headers):
        return self._request("POST", "/api/asset-recovery-requests", payload, headers)

    def list_account_recovery_requests(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}/asset-recovery-requests", headers=headers)

    def get_recovery_request(self, rr_id, headers):
        return self._request("GET", f"/api/asset-recovery-requests/{rr_id}", headers=headers)

    def list_recovery_requests(self, headers, params=None):
        return self._request("GET", "/api/asset-recovery-requests", headers=headers, params=params)

    def issue_recovery_label(self, rr_id, headers):
        return self._request("POST", f"/api/asset-recovery-requests/{rr_id}/issue-label", {}, headers)

    def receive_recovery(self, rr_id, payload, headers):
        return self._request("POST", f"/api/asset-recovery-requests/{rr_id}/receive", payload, headers)

    def credit_recovery(self, rr_id, headers):
        return self._request("POST", f"/api/asset-recovery-requests/{rr_id}/credit", {}, headers)

    def recycle_recovery(self, rr_id, headers):
        return self._request("POST", f"/api/asset-recovery-requests/{rr_id}/recycle", {}, headers)

    def cancel_recovery(self, rr_id, headers):
        return self._request("POST", f"/api/asset-recovery-requests/{rr_id}/cancel", {}, headers)

    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
