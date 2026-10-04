"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Franchise areas ---
    def create_franchise_area(self, payload, headers):
        return self._request("POST", "/franchise-areas", payload, headers)

    def get_franchise_area(self, fa_id, headers):
        return self._request("GET", f"/franchise-areas/{fa_id}", headers=headers)

    def list_franchise_areas(self, headers, params=None):
        return self._request("GET", "/franchise-areas", headers=headers, params=params)

    # --- Optical nodes ---
    def create_optical_node(self, fa_id, payload, headers):
        return self._request("POST", f"/franchise-areas/{fa_id}/optical-nodes", payload, headers)

    def get_optical_node(self, on_id, headers):
        return self._request("GET", f"/optical-nodes/{on_id}", headers=headers)

    def list_optical_nodes(self, fa_id, headers, params=None):
        return self._request("GET", f"/franchise-areas/{fa_id}/optical-nodes", headers=headers, params=params)

    # --- Spectrum blocks ---
    def create_spectrum_block(self, on_id, payload, headers):
        return self._request("POST", f"/optical-nodes/{on_id}/spectrum-blocks", payload, headers)

    def get_spectrum_block(self, sb_id, headers):
        return self._request("GET", f"/spectrum-blocks/{sb_id}", headers=headers)

    def list_spectrum_blocks(self, on_id, headers, params=None):
        return self._request("GET", f"/optical-nodes/{on_id}/spectrum-blocks", headers=headers, params=params)

    # --- Service groups ---
    def create_service_group(self, on_id, payload, headers):
        return self._request("POST", f"/optical-nodes/{on_id}/service-groups", payload, headers)

    def get_service_group(self, sg_id, headers):
        return self._request("GET", f"/service-groups/{sg_id}", headers=headers)

    def list_service_groups(self, on_id, headers, params=None):
        return self._request("GET", f"/optical-nodes/{on_id}/service-groups", headers=headers, params=params)

    # --- Utilization samples ---
    def create_utilization_sample(self, sg_id, payload, headers):
        return self._request("POST", f"/service-groups/{sg_id}/utilization-samples", payload, headers)

    def list_utilization_samples(self, sg_id, headers, params=None):
        return self._request("GET", f"/service-groups/{sg_id}/utilization-samples", headers=headers, params=params)

    # --- Capacity actions ---
    def create_capacity_action(self, sg_id, payload, headers):
        return self._request("POST", f"/service-groups/{sg_id}/capacity-actions", payload, headers)

    def get_capacity_action(self, ca_id, headers):
        return self._request("GET", f"/capacity-actions/{ca_id}", headers=headers)

    def list_capacity_actions(self, sg_id, headers, params=None):
        return self._request("GET", f"/service-groups/{sg_id}/capacity-actions", headers=headers, params=params)

    def approve_capacity_action(self, ca_id, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/approve", None, headers)

    def revise_capacity_action(self, ca_id, payload, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/revise", payload, headers)

    def begin_capacity_action(self, ca_id, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/begin", None, headers)

    def complete_capacity_action(self, ca_id, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/complete", None, headers)

    def cancel_capacity_action(self, ca_id, payload, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/cancel", payload, headers)

    # --- Node split projects ---
    def create_node_split_project(self, ca_id, payload, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/node-split-projects", payload, headers)

    def get_node_split_project(self, nsp_id, headers):
        return self._request("GET", f"/node-split-projects/{nsp_id}", headers=headers)

    def list_node_split_projects(self, ca_id, headers, params=None):
        return self._request("GET", f"/capacity-actions/{ca_id}/node-split-projects", headers=headers, params=params)

    def adjudicate_permit(self, nsp_id, payload, headers):
        return self._request("POST", f"/node-split-projects/{nsp_id}/adjudicate-permit", payload, headers)

    def refile_permit(self, nsp_id, headers):
        return self._request("POST", f"/node-split-projects/{nsp_id}/refile-permit", None, headers)

    def schedule_node_split_project(self, nsp_id, payload, headers):
        return self._request("POST", f"/node-split-projects/{nsp_id}/schedule", payload, headers)

    def begin_construction(self, nsp_id, headers):
        return self._request("POST", f"/node-split-projects/{nsp_id}/begin-construction", None, headers)

    def cutover_node_split_project(self, nsp_id, headers):
        return self._request("POST", f"/node-split-projects/{nsp_id}/cutover", None, headers)

    # --- Migration waves ---
    def create_migration_wave(self, ca_id, payload, headers):
        return self._request("POST", f"/capacity-actions/{ca_id}/migration-waves", payload, headers)

    def get_migration_wave(self, mw_id, headers):
        return self._request("GET", f"/migration-waves/{mw_id}", headers=headers)

    def list_migration_waves(self, ca_id, headers, params=None):
        return self._request("GET", f"/capacity-actions/{ca_id}/migration-waves", headers=headers, params=params)

    def execute_migration_wave(self, mw_id, headers):
        return self._request("POST", f"/migration-waves/{mw_id}/execute", None, headers)

    def cancel_migration_wave(self, mw_id, headers):
        return self._request("POST", f"/migration-waves/{mw_id}/cancel", None, headers)

    # --- Customer premises ---
    def create_customer_premise(self, sg_id, payload, headers):
        return self._request("POST", f"/service-groups/{sg_id}/customer-premises", payload, headers)

    def get_customer_premise(self, cp_id, headers):
        return self._request("GET", f"/customer-premises/{cp_id}", headers=headers)

    def list_customer_premises(self, sg_id, headers, params=None):
        return self._request("GET", f"/service-groups/{sg_id}/customer-premises", headers=headers, params=params)

    def filter_customer_premises(self, headers, params=None):
        return self._request("GET", "/customer-premises", headers=headers, params=params)

    # --- Customer equipment ---
    def create_equipment(self, cp_id, payload, headers):
        return self._request("POST", f"/customer-premises/{cp_id}/equipment", payload, headers)

    def get_equipment(self, eq_id, headers):
        return self._request("GET", f"/equipment/{eq_id}", headers=headers)

    def list_equipment(self, cp_id, headers, params=None):
        return self._request("GET", f"/customer-premises/{cp_id}/equipment", headers=headers, params=params)

    def swap_equipment(self, eq_id, payload, headers):
        return self._request("POST", f"/equipment/{eq_id}/swap", payload, headers)

    # --- Speed tiers ---
    def create_speed_tier(self, payload, headers):
        return self._request("POST", "/speed-tiers", payload, headers)

    def get_speed_tier(self, st_id, headers):
        return self._request("GET", f"/speed-tiers/{st_id}", headers=headers)

    def retire_speed_tier(self, st_id, headers):
        return self._request("POST", f"/speed-tiers/{st_id}/retire", None, headers)

    # --- Provisioning requests ---
    def create_provisioning_request(self, cp_id, payload, headers):
        return self._request("POST", f"/customer-premises/{cp_id}/provisioning-requests", payload, headers)

    def get_provisioning_request(self, pr_id, headers):
        return self._request("GET", f"/provisioning-requests/{pr_id}", headers=headers)

    def list_provisioning_requests(self, headers, params=None):
        return self._request("GET", "/provisioning-requests", headers=headers, params=params)

    def validate_provisioning_request(self, pr_id, headers):
        return self._request("POST", f"/provisioning-requests/{pr_id}/validate", None, headers)

    def activate_provisioning_request(self, pr_id, headers):
        return self._request("POST", f"/provisioning-requests/{pr_id}/activate", None, headers)

    def retry_provisioning_request(self, pr_id, headers):
        return self._request("POST", f"/provisioning-requests/{pr_id}/retry", None, headers)

    def cancel_provisioning_request(self, pr_id, headers):
        return self._request("POST", f"/provisioning-requests/{pr_id}/cancel", None, headers)

    # --- Refresh campaigns ---
    def create_refresh_campaign(self, fa_id, payload, headers):
        return self._request("POST", f"/franchise-areas/{fa_id}/refresh-campaigns", payload, headers)

    def get_refresh_campaign(self, rc_id, headers):
        return self._request("GET", f"/refresh-campaigns/{rc_id}", headers=headers)

    def list_refresh_campaigns(self, fa_id, headers, params=None):
        return self._request("GET", f"/franchise-areas/{fa_id}/refresh-campaigns", headers=headers, params=params)

    def launch_refresh_campaign(self, rc_id, headers):
        return self._request("POST", f"/refresh-campaigns/{rc_id}/launch", None, headers)

    def close_refresh_campaign(self, rc_id, headers):
        return self._request("POST", f"/refresh-campaigns/{rc_id}/close", None, headers)

    # --- Congestion complaints ---
    def create_congestion_complaint(self, cp_id, payload, headers):
        return self._request("POST", f"/customer-premises/{cp_id}/congestion-complaints", payload, headers)

    def get_congestion_complaint(self, cc_id, headers):
        return self._request("GET", f"/congestion-complaints/{cc_id}", headers=headers)

    def list_congestion_complaints(self, headers, params=None):
        return self._request("GET", "/congestion-complaints", headers=headers, params=params)

    def classify_congestion_complaint(self, cc_id, payload, headers):
        return self._request("POST", f"/congestion-complaints/{cc_id}/classify", payload, headers)

    def resolve_congestion_complaint(self, cc_id, payload, headers):
        return self._request("POST", f"/congestion-complaints/{cc_id}/resolve", payload, headers)

    def reopen_congestion_complaint(self, cc_id, headers):
        return self._request("POST", f"/congestion-complaints/{cc_id}/reopen", None, headers)

    def close_congestion_complaint(self, cc_id, headers):
        return self._request("POST", f"/congestion-complaints/{cc_id}/close", None, headers)


api_client = ApiClient()
