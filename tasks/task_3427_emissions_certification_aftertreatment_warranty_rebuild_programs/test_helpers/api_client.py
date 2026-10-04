"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions).

Base URL comes from the API_BASE_URL environment variable, which
prd-bench-local-runner sets before launching pytest; nothing is hardcoded here.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------- regulation standards
    def create_regulation_standard(self, payload, headers):
        return self._request("POST", "/emissions/regulation-standards", payload, headers)

    def get_regulation_standard(self, standard_id, headers):
        return self._request("GET", f"/emissions/regulation-standards/{standard_id}", headers=headers)

    def list_regulation_standards(self, headers, params=None):
        return self._request("GET", "/emissions/regulation-standards", headers=headers, params=params)

    def publish_regulation_standard(self, standard_id, headers):
        return self._request("POST", f"/emissions/regulation-standards/{standard_id}/publish", None, headers)

    def supersede_regulation_standard(self, standard_id, payload, headers):
        return self._request("POST", f"/emissions/regulation-standards/{standard_id}/supersede", payload, headers)

    # ------------------------------------------------------- engine families
    def create_engine_family(self, payload, headers):
        return self._request("POST", "/emissions/engine-families", payload, headers)

    def get_engine_family(self, family_id, headers):
        return self._request("GET", f"/emissions/engine-families/{family_id}", headers=headers)

    def list_engine_families(self, headers, params=None):
        return self._request("GET", "/emissions/engine-families", headers=headers, params=params)

    def begin_testing(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/begin-testing", None, headers)

    def submit_review(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/submit-review", None, headers)

    def return_to_testing(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/return-to-testing", None, headers)

    def certify_family(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/certify", None, headers)

    def enter_production(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/enter-production", None, headers)

    def phase_out_family(self, family_id, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/phase-out", None, headers)

    def list_family_specs(self, family_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-families/{family_id}/aftertreatment-specs", headers=headers, params=params)

    def list_family_test_runs(self, family_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-families/{family_id}/test-runs", headers=headers, params=params)

    def list_family_engine_units(self, family_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-families/{family_id}/engine-units", headers=headers, params=params)

    def list_family_campaigns(self, family_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-families/{family_id}/field-campaigns", headers=headers, params=params)

    def list_family_in_use_results(self, family_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-families/{family_id}/in-use-results", headers=headers, params=params)

    # -------------------------------------------------- aftertreatment specs
    def create_aftertreatment_spec(self, family_id, payload, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/aftertreatment-specs", payload, headers)

    def get_aftertreatment_spec(self, spec_id, headers):
        return self._request("GET", f"/emissions/aftertreatment-specs/{spec_id}", headers=headers)

    def calibrate_spec(self, spec_id, payload, headers):
        return self._request("POST", f"/emissions/aftertreatment-specs/{spec_id}/calibrate", payload, headers)

    def activate_spec(self, spec_id, headers):
        return self._request("POST", f"/emissions/aftertreatment-specs/{spec_id}/activate", None, headers)

    # ------------------------------------------------------------ test runs
    def create_test_run(self, family_id, payload, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/test-runs", payload, headers)

    def get_test_run(self, run_id, headers):
        return self._request("GET", f"/emissions/test-runs/{run_id}", headers=headers)

    def record_test_results(self, run_id, payload, headers):
        return self._request("POST", f"/emissions/test-runs/{run_id}/record-results", payload, headers)

    def review_test_run(self, run_id, payload, headers):
        return self._request("POST", f"/emissions/test-runs/{run_id}/review", payload, headers)

    def invalidate_test_run(self, run_id, payload, headers):
        return self._request("POST", f"/emissions/test-runs/{run_id}/invalidate", payload, headers)

    # ---------------------------------------------------------------- fleets
    def create_fleet(self, payload, headers):
        return self._request("POST", "/emissions/fleets", payload, headers)

    def get_fleet(self, fleet_id, headers):
        return self._request("GET", f"/emissions/fleets/{fleet_id}", headers=headers)

    def reinstate_fleet(self, fleet_id, headers):
        return self._request("POST", f"/emissions/fleets/{fleet_id}/reinstate", None, headers)

    def list_fleet_engine_units(self, fleet_id, headers, params=None):
        return self._request("GET", f"/emissions/fleets/{fleet_id}/engine-units", headers=headers, params=params)

    # ----------------------------------------------------------- engine units
    def create_engine_unit(self, payload, headers):
        return self._request("POST", "/emissions/engine-units", payload, headers)

    def get_engine_unit(self, unit_id, headers):
        return self._request("GET", f"/emissions/engine-units/{unit_id}", headers=headers)

    def list_engine_units(self, headers, params=None):
        return self._request("GET", "/emissions/engine-units", headers=headers, params=params)

    def decommission_unit(self, unit_id, headers):
        return self._request("POST", f"/emissions/engine-units/{unit_id}/decommission", None, headers)

    def get_unit_coverage(self, unit_id, headers):
        return self._request("GET", f"/emissions/engine-units/{unit_id}/coverage", headers=headers)

    def create_maintenance_record(self, unit_id, payload, headers):
        return self._request("POST", f"/emissions/engine-units/{unit_id}/maintenance-records", payload, headers)

    def list_maintenance_records(self, unit_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-units/{unit_id}/maintenance-records", headers=headers, params=params)

    # ------------------------------------------------------------- telematics
    def create_telematics_snapshot(self, unit_id, payload, headers):
        return self._request("POST", f"/emissions/engine-units/{unit_id}/telematics-snapshots", payload, headers)

    def list_telematics_snapshots(self, unit_id, headers, params=None):
        return self._request("GET", f"/emissions/engine-units/{unit_id}/telematics-snapshots", headers=headers, params=params)

    # -------------------------------------------------------- service centers
    def create_service_center(self, payload, headers):
        return self._request("POST", "/emissions/service-centers", payload, headers)

    def get_service_center(self, center_id, headers):
        return self._request("GET", f"/emissions/service-centers/{center_id}", headers=headers)

    def audit_service_center(self, center_id, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/audit", None, headers)

    def authorize_service_center(self, center_id, payload, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/authorize", payload, headers)

    def suspend_service_center(self, center_id, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/suspend", None, headers)

    def reinstate_service_center(self, center_id, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/reinstate", None, headers)

    def revoke_service_center(self, center_id, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/revoke", None, headers)

    def create_technician(self, center_id, payload, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/technicians", payload, headers)

    def list_technicians(self, center_id, headers, params=None):
        return self._request("GET", f"/emissions/service-centers/{center_id}/technicians", headers=headers, params=params)

    def recertify_technician(self, tech_id, payload, headers):
        return self._request("POST", f"/emissions/technicians/{tech_id}/recertify", payload, headers)

    def create_diagnostic_tool(self, center_id, payload, headers):
        return self._request("POST", f"/emissions/service-centers/{center_id}/diagnostic-tools", payload, headers)

    def list_diagnostic_tools(self, center_id, headers, params=None):
        return self._request("GET", f"/emissions/service-centers/{center_id}/diagnostic-tools", headers=headers, params=params)

    def recalibrate_tool(self, tool_id, headers):
        return self._request("POST", f"/emissions/diagnostic-tools/{tool_id}/recalibrate", None, headers)

    # -------------------------------------------------------- warranty claims
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/emissions/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/emissions/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/emissions/warranty-claims", headers=headers, params=params)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/emissions/warranty-claims/{claim_id}/start-review", None, headers)

    def request_claim_info(self, claim_id, headers):
        return self._request("POST", f"/emissions/warranty-claims/{claim_id}/request-info", None, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/emissions/warranty-claims/{claim_id}/resubmit", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/emissions/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/emissions/warranty-claims/{claim_id}/pay", None, headers)

    # --------------------------------------------------------- field campaigns
    def create_field_campaign(self, payload, headers):
        return self._request("POST", "/emissions/field-campaigns", payload, headers)

    def get_field_campaign(self, campaign_id, headers):
        return self._request("GET", f"/emissions/field-campaigns/{campaign_id}", headers=headers)

    def announce_campaign(self, campaign_id, headers):
        return self._request("POST", f"/emissions/field-campaigns/{campaign_id}/announce", None, headers)

    def begin_campaign_execution(self, campaign_id, headers):
        return self._request("POST", f"/emissions/field-campaigns/{campaign_id}/begin-execution", None, headers)

    def campaign_completion_review(self, campaign_id, headers):
        return self._request("POST", f"/emissions/field-campaigns/{campaign_id}/completion-review", None, headers)

    def resume_campaign_execution(self, campaign_id, headers):
        return self._request("POST", f"/emissions/field-campaigns/{campaign_id}/resume-execution", None, headers)

    # ----------------------------------------------------- campaign work orders
    def create_campaign_work_order(self, campaign_id, payload, headers):
        return self._request("POST", f"/emissions/field-campaigns/{campaign_id}/work-orders", payload, headers)

    def get_campaign_work_order(self, work_order_id, headers):
        return self._request("GET", f"/emissions/campaign-work-orders/{work_order_id}", headers=headers)

    def list_campaign_work_orders(self, headers, params=None):
        return self._request("GET", "/emissions/campaign-work-orders", headers=headers, params=params)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/emissions/campaign-work-orders/{work_order_id}/start", None, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/emissions/campaign-work-orders/{work_order_id}/complete", None, headers)

    def verify_work_order(self, work_order_id, headers):
        return self._request("POST", f"/emissions/campaign-work-orders/{work_order_id}/verify", None, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/emissions/campaign-work-orders/{work_order_id}/cancel", None, headers)

    # ------------------------------------------------------------ reman orders
    def create_reman_order(self, payload, headers):
        return self._request("POST", "/emissions/reman-orders", payload, headers)

    def get_reman_order(self, order_id, headers):
        return self._request("GET", f"/emissions/reman-orders/{order_id}", headers=headers)

    def list_reman_orders(self, headers, params=None):
        return self._request("GET", "/emissions/reman-orders", headers=headers, params=params)

    def confirm_reman_order(self, order_id, headers):
        return self._request("POST", f"/emissions/reman-orders/{order_id}/confirm", None, headers)

    def receive_core(self, order_id, headers):
        return self._request("POST", f"/emissions/reman-orders/{order_id}/receive-core", None, headers)

    def grade_core(self, order_id, payload, headers):
        return self._request("POST", f"/emissions/reman-orders/{order_id}/grade-core", payload, headers)

    def forfeit_core(self, order_id, headers):
        return self._request("POST", f"/emissions/reman-orders/{order_id}/forfeit-core", None, headers)

    def close_reman_order(self, order_id, headers):
        return self._request("POST", f"/emissions/reman-orders/{order_id}/close", None, headers)

    # -------------------------------------------------------- in-use compliance
    def create_in_use_result(self, family_id, payload, headers):
        return self._request("POST", f"/emissions/engine-families/{family_id}/in-use-results", payload, headers)


api_client = ApiClient()
