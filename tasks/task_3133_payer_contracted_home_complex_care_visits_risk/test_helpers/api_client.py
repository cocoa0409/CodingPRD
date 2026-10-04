"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Care Programs ---
    def create_care_program(self, payload, headers):
        return self._request("POST", "/care-programs", payload, headers)

    def list_care_programs(self, headers, params=None):
        return self._request("GET", "/care-programs", headers=headers, params=params)

    def get_care_program(self, program_id, headers):
        return self._request("GET", f"/care-programs/{program_id}", headers=headers)

    def advance_program_clock(self, program_id, payload, headers):
        return self._request("POST", f"/care-programs/{program_id}/clock/advance", payload, headers)

    # --- Payer Contracts ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/payer-contracts", payload, headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/payer-contracts", headers=headers, params=params)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/payer-contracts/{contract_id}", headers=headers)

    # --- Medical Costs ---
    def create_medical_cost(self, payload, headers):
        return self._request("POST", "/medical-costs", payload, headers)

    def list_medical_costs(self, headers, params=None):
        return self._request("GET", "/medical-costs", headers=headers, params=params)

    # --- PCP Providers ---
    def create_pcp_provider(self, payload, headers):
        return self._request("POST", "/pcp-providers", payload, headers)

    def list_pcp_providers(self, headers, params=None):
        return self._request("GET", "/pcp-providers", headers=headers, params=params)

    def get_pcp_provider(self, pcp_id, headers):
        return self._request("GET", f"/pcp-providers/{pcp_id}", headers=headers)

    # --- Clinicians ---
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/clinicians", headers=headers, params=params)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # --- Member Enrollments ---
    def create_enrollment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/enrollments", payload, headers)

    def list_member_enrollments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/enrollments", headers=headers, params=params)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def begin_outreach(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/begin-outreach", {}, headers)

    def record_attempt(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/record-attempt", {}, headers)

    def record_consent(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/record-consent", payload, headers)

    def record_decline(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/record-decline", {}, headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def disenroll(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/disenroll", payload, headers)

    # --- Care Teams ---
    def get_care_team(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}/care-team", headers=headers)

    def update_care_team(self, enrollment_id, payload, headers):
        return self._request("PUT", f"/enrollments/{enrollment_id}/care-team", payload, headers)

    def activate_care_team(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/care-team/activate", {}, headers)

    def suspend_care_team(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/care-team/suspend", {}, headers)

    def reinstate_care_team(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/care-team/reinstate", {}, headers)

    # --- Visits ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def depart_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/depart", {}, headers)

    def arrive_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/arrive", {}, headers)

    def upsert_assessment(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/assessment", payload, headers)

    def get_assessment(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}/assessment", headers=headers)

    def submit_assessment(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/assessment/submit", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def cancel_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", payload, headers)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/reschedule", payload, headers)

    def mark_no_show(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/mark-no-show", {}, headers)

    # --- Urgent Episodes ---
    def create_urgent_episode(self, payload, headers):
        return self._request("POST", "/urgent-episodes", payload, headers)

    def list_urgent_episodes(self, headers, params=None):
        return self._request("GET", "/urgent-episodes", headers=headers, params=params)

    def get_urgent_episode(self, episode_id, headers):
        return self._request("GET", f"/urgent-episodes/{episode_id}", headers=headers)

    def dispatch_episode(self, episode_id, headers):
        return self._request("POST", f"/urgent-episodes/{episode_id}/dispatch", {}, headers)

    def arrive_episode(self, episode_id, headers):
        return self._request("POST", f"/urgent-episodes/{episode_id}/arrive", {}, headers)

    def resolve_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/urgent-episodes/{episode_id}/resolve", payload, headers)

    # --- Performance Measurements ---
    def list_performance_measurements(self, headers, params=None):
        return self._request("GET", "/performance-measurements", headers=headers, params=params)

    def get_performance_measurement(self, measurement_id, headers):
        return self._request("GET", f"/performance-measurements/{measurement_id}", headers=headers)

    # --- Settlements ---
    def create_settlement(self, contract_id, headers):
        return self._request("POST", f"/payer-contracts/{contract_id}/settlements", {}, headers)

    def list_settlements(self, contract_id, headers, params=None):
        return self._request("GET", f"/payer-contracts/{contract_id}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def finalize_settlement(self, contract_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/payer-contracts/{contract_id}/settlements/{settlement_id}/finalize",
            {},
            headers,
        )

    def mark_settlement_paid(self, contract_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/payer-contracts/{contract_id}/settlements/{settlement_id}/mark-paid",
            {},
            headers,
        )

    def void_settlement(self, contract_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/payer-contracts/{contract_id}/settlements/{settlement_id}/void",
            {},
            headers,
        )

    # --- Logical clock (test-driving endpoints) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock_hours(self, payload, headers):
        return self._request("POST", "/_clock/advance_hours", payload, headers)


api_client = ApiClient()
