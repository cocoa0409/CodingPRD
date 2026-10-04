"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the /private-wireless prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/private-wireless/_clock/set_current_utc", payload, headers)

    # ---- Enterprise ----
    def create_enterprise(self, payload, headers):
        return self._request("POST", "/private-wireless/enterprises", payload, headers)

    def list_enterprises(self, headers, params=None):
        return self._request("GET", "/private-wireless/enterprises", headers=headers, params=params)

    def get_enterprise(self, enterprise_id, headers):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}", headers=headers)

    def activate_enterprise(self, enterprise_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/activate", {}, headers)

    def suspend_enterprise(self, enterprise_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/suspend", {}, headers)

    def resume_enterprise(self, enterprise_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/resume", {}, headers)

    def offboard_enterprise(self, enterprise_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/offboard", {}, headers)

    # ---- Site ----
    def create_site(self, enterprise_id, payload, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/sites", payload, headers)

    def list_enterprise_sites(self, enterprise_id, headers, params=None):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}", headers=headers)

    def activate_site(self, site_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/activate", {}, headers)

    def decommission_site(self, site_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/decommission", {}, headers)

    def get_site_summary(self, site_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/summary", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/private-wireless/sites", headers=headers, params=params)

    # ---- SiteSurvey ----
    def create_survey(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/surveys", payload, headers)

    def list_site_surveys(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/private-wireless/surveys/{survey_id}", headers=headers)

    def get_survey_under_site(self, site_id, survey_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/surveys/{survey_id}", headers=headers)

    def submit_survey(self, site_id, survey_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/surveys/{survey_id}/submit", {}, headers)

    def approve_survey(self, site_id, survey_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/surveys/{survey_id}/approve", {}, headers)

    def reject_survey(self, site_id, survey_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/surveys/{survey_id}/reject", {}, headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/private-wireless/surveys", headers=headers, params=params)

    # ---- CoverageDesign ----
    def create_design(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/designs", payload, headers)

    def list_site_designs(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/designs", headers=headers, params=params)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/private-wireless/designs/{design_id}", headers=headers)

    def get_design_under_site(self, site_id, design_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/designs/{design_id}", headers=headers)

    def submit_design(self, site_id, design_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/designs/{design_id}/submit", {}, headers)

    def approve_design(self, site_id, design_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/designs/{design_id}/approve", {}, headers)

    def reject_design(self, site_id, design_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/designs/{design_id}/reject", {}, headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", "/private-wireless/designs", headers=headers, params=params)

    # ---- CellSector ----
    def create_cell(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/cells", payload, headers)

    def list_site_cells(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/cells", headers=headers, params=params)

    def get_cell(self, cell_id, headers):
        return self._request("GET", f"/private-wireless/cells/{cell_id}", headers=headers)

    def configure_cell(self, site_id, cell_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/cells/{cell_id}/configure", {}, headers)

    def on_air_cell(self, site_id, cell_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/cells/{cell_id}/on-air", {}, headers)

    def off_air_cell(self, site_id, cell_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/cells/{cell_id}/off-air", {}, headers)

    def decommission_cell(self, site_id, cell_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/cells/{cell_id}/decommission", {}, headers)

    def list_cells(self, headers, params=None):
        return self._request("GET", "/private-wireless/cells", headers=headers, params=params)

    # ---- SpectrumLease ----
    def create_lease(self, enterprise_id, payload, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/spectrum-leases", payload, headers)

    def list_enterprise_leases(self, enterprise_id, headers, params=None):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}/spectrum-leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/private-wireless/spectrum-leases/{lease_id}", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/private-wireless/spectrum-leases/{lease_id}/activate", {}, headers)

    def cancel_lease(self, lease_id, headers):
        return self._request("POST", f"/private-wireless/spectrum-leases/{lease_id}/cancel", {}, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/private-wireless/spectrum-leases", headers=headers, params=params)

    # ---- SpectrumCoordinationRequest ----
    def create_coordination_request(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests", payload, headers)

    def list_site_coordination_requests(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/coordination-requests", headers=headers, params=params)

    def get_coordination_request(self, request_id, headers):
        return self._request("GET", f"/private-wireless/coordination-requests/{request_id}", headers=headers)

    def get_coordination_request_under_site(self, site_id, request_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}", headers=headers)

    def submit_coordination_request(self, site_id, request_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/submit", {}, headers)

    def begin_coordination(self, site_id, request_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/begin-coordination", {}, headers)

    def approve_coordination_request(self, site_id, request_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/approve", payload, headers)

    def reject_coordination_request(self, site_id, request_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/reject", {}, headers)

    def register_coordination_request(self, site_id, request_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/register", {}, headers)

    def withdraw_coordination_request(self, site_id, request_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/coordination-requests/{request_id}/withdraw", {}, headers)

    def list_coordination_requests(self, headers, params=None):
        return self._request("GET", "/private-wireless/coordination-requests", headers=headers, params=params)

    # ---- SpectrumAssignment ----
    def create_assignment(self, cell_id, payload, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/spectrum-assignments", payload, headers)

    def list_cell_assignments(self, cell_id, headers, params=None):
        return self._request("GET", f"/private-wireless/cells/{cell_id}/spectrum-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/private-wireless/spectrum-assignments/{assignment_id}", headers=headers)

    def release_assignment(self, cell_id, assignment_id, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/spectrum-assignments/{assignment_id}/release", {}, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/private-wireless/spectrum-assignments", headers=headers, params=params)

    # ---- SIMProfile ----
    def create_sim_profile(self, enterprise_id, payload, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/sim-profiles", payload, headers)

    def list_enterprise_sim_profiles(self, enterprise_id, headers, params=None):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}/sim-profiles", headers=headers, params=params)

    def get_sim_profile(self, sim_id, headers):
        return self._request("GET", f"/private-wireless/sim-profiles/{sim_id}", headers=headers)

    def list_sim_profiles(self, headers, params=None):
        return self._request("GET", "/private-wireless/sim-profiles", headers=headers, params=params)

    # ---- Device ----
    def create_device(self, cell_id, payload, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices", payload, headers)

    def list_cell_devices(self, cell_id, headers, params=None):
        return self._request("GET", f"/private-wireless/cells/{cell_id}/devices", headers=headers, params=params)

    def list_site_devices(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/devices", headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/private-wireless/devices/{device_id}", headers=headers)

    def bind_sim(self, cell_id, device_id, payload, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices/{device_id}/bind-sim", payload, headers)

    def activate_device(self, cell_id, device_id, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices/{device_id}/activate", {}, headers)

    def suspend_device(self, cell_id, device_id, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices/{device_id}/suspend", {}, headers)

    def resume_device(self, cell_id, device_id, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices/{device_id}/resume", {}, headers)

    def decommission_device(self, cell_id, device_id, headers):
        return self._request("POST", f"/private-wireless/cells/{cell_id}/devices/{device_id}/decommission", {}, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/private-wireless/devices", headers=headers, params=params)

    # ---- NetworkSlice / SliceBinding ----
    def create_slice(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices", payload, headers)

    def list_site_slices(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/slices", headers=headers, params=params)

    def get_slice(self, slice_id, headers):
        return self._request("GET", f"/private-wireless/slices/{slice_id}", headers=headers)

    def get_slice_under_site(self, site_id, slice_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/slices/{slice_id}", headers=headers)

    def activate_slice(self, site_id, slice_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices/{slice_id}/activate", {}, headers)

    def suspend_slice(self, site_id, slice_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices/{slice_id}/suspend", {}, headers)

    def retire_slice(self, site_id, slice_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices/{slice_id}/retire", {}, headers)

    def bind_device(self, site_id, slice_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices/{slice_id}/bind-device", payload, headers)

    def unbind_device(self, site_id, slice_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/slices/{slice_id}/unbind-device", payload, headers)

    def list_slice_bindings(self, site_id, slice_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/slices/{slice_id}/bindings", headers=headers, params=params)

    def get_slice_binding(self, binding_id, headers):
        return self._request("GET", f"/private-wireless/slice-bindings/{binding_id}", headers=headers)

    def list_bindings(self, headers, params=None):
        return self._request("GET", "/private-wireless/slice-bindings", headers=headers, params=params)

    def list_slices(self, headers, params=None):
        return self._request("GET", "/private-wireless/slices", headers=headers, params=params)

    # ---- ServiceContract ----
    def create_contract(self, enterprise_id, payload, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/contracts", payload, headers)

    def list_enterprise_contracts(self, enterprise_id, headers, params=None):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/private-wireless/contracts/{contract_id}", headers=headers)

    def get_contract_under_enterprise(self, enterprise_id, contract_id, headers):
        return self._request("GET", f"/private-wireless/enterprises/{enterprise_id}/contracts/{contract_id}", headers=headers)

    def activate_contract(self, enterprise_id, contract_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/contracts/{contract_id}/activate", {}, headers)

    def renew_contract(self, enterprise_id, contract_id, payload, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/contracts/{contract_id}/renew", payload, headers)

    def terminate_contract(self, enterprise_id, contract_id, headers):
        return self._request("POST", f"/private-wireless/enterprises/{enterprise_id}/contracts/{contract_id}/terminate", {}, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/private-wireless/contracts", headers=headers, params=params)

    # ---- MonitoringAlert ----
    def create_alert(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/alerts", payload, headers)

    def list_site_alerts(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/private-wireless/alerts/{alert_id}", headers=headers)

    def get_alert_under_site(self, site_id, alert_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, site_id, alert_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/alerts/{alert_id}/acknowledge", {}, headers)

    def mitigate_alert(self, site_id, alert_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/alerts/{alert_id}/mitigate", {}, headers)

    def resolve_alert(self, site_id, alert_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/alerts/{alert_id}/resolve", {}, headers)

    def mark_false_alarm(self, site_id, alert_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/alerts/{alert_id}/mark-false-alarm", {}, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/private-wireless/alerts", headers=headers, params=params)

    # ---- CoverageRemediation ----
    def create_remediation(self, site_id, payload, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations", payload, headers)

    def list_site_remediations(self, site_id, headers, params=None):
        return self._request("GET", f"/private-wireless/sites/{site_id}/remediations", headers=headers, params=params)

    def get_remediation(self, remediation_id, headers):
        return self._request("GET", f"/private-wireless/remediations/{remediation_id}", headers=headers)

    def get_remediation_under_site(self, site_id, remediation_id, headers):
        return self._request("GET", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}", headers=headers)

    def approve_remediation(self, site_id, remediation_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}/approve", {}, headers)

    def start_remediation(self, site_id, remediation_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}/start", {}, headers)

    def verify_remediation(self, site_id, remediation_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}/verify", {}, headers)

    def complete_remediation(self, site_id, remediation_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}/complete", {}, headers)

    def reopen_remediation(self, site_id, remediation_id, headers):
        return self._request("POST", f"/private-wireless/sites/{site_id}/remediations/{remediation_id}/reopen", {}, headers)

    def list_remediations(self, headers, params=None):
        return self._request("GET", "/private-wireless/remediations", headers=headers, params=params)


api_client = ApiClient()
