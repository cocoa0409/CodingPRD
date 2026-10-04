"""API client: one method per endpoint declared in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving endpoints ──────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def recompute_compliance_posture(self, agency_id, headers):
        return self._request("POST", "/_maintenance/recompute-compliance-posture",
                             {"agency_id": agency_id}, headers)

    # ─── Agencies ────────────────────────────────────────────
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def update_agency(self, agency_id, payload, headers):
        return self._request("PUT", f"/agencies/{agency_id}", payload, headers)

    def posture_reset(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/posture-reset",
                             payload, headers)

    def book_of_business(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/book-of-business",
                             headers=headers, params=params)

    def list_agency_agents(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/agents",
                             headers=headers, params=params)

    def list_agency_members(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/members",
                             headers=headers, params=params)

    # ─── Carriers ────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def update_carrier(self, carrier_id, payload, headers):
        return self._request("PUT", f"/carriers/{carrier_id}", payload, headers)

    def list_carrier_plans(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/plans",
                             headers=headers, params=params)

    def list_carrier_appointments(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/appointments",
                             headers=headers, params=params)

    def list_carrier_certifications(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/certifications",
                             headers=headers, params=params)

    def list_carrier_reconciliations(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/carrier-reconciliations",
                             headers=headers, params=params)

    # ─── Agents ──────────────────────────────────────────────
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def add_license(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/licenses", payload, headers)

    def list_licenses(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/licenses",
                             headers=headers, params=params)

    def add_certification(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/certifications",
                             payload, headers)

    def list_certifications(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/certifications",
                             headers=headers, params=params)

    def add_appointment(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/appointments",
                             payload, headers)

    def list_appointments(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/appointments",
                             headers=headers, params=params)

    def reinstate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/reinstate", {}, headers)

    def terminate_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/terminate", payload, headers)

    def rehire_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/rehire", payload, headers)

    def list_agent_members(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/members",
                             headers=headers, params=params)

    def list_agent_complaints(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/complaints",
                             headers=headers, params=params)

    def list_agent_coaching_assignments(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/coaching-assignments",
                             headers=headers, params=params)

    def list_agent_call_sessions(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/call-sessions",
                             headers=headers, params=params)

    def list_agent_enrollments(self, agent_id, headers, params=None):
        return self._request("GET", f"/agents/{agent_id}/enrollments",
                             headers=headers, params=params)

    # ─── Members ─────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PUT", f"/members/{member_id}", payload, headers)

    def list_member_scopes(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/scope-of-appointments",
                             headers=headers, params=params)

    def list_member_enrollments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/enrollments",
                             headers=headers, params=params)

    # ─── Scope of appointment ────────────────────────────────
    def create_scope(self, payload, headers):
        return self._request("POST", "/scope-of-appointments", payload, headers)

    def list_scopes(self, headers, params=None):
        return self._request("GET", "/scope-of-appointments",
                             headers=headers, params=params)

    def get_scope(self, scope_id, headers):
        return self._request("GET", f"/scope-of-appointments/{scope_id}",
                             headers=headers)

    def void_scope(self, scope_id, payload, headers):
        return self._request("POST", f"/scope-of-appointments/{scope_id}/void",
                             payload, headers)

    # ─── Call sessions ───────────────────────────────────────
    def create_call_session(self, payload, headers):
        return self._request("POST", "/call-sessions", payload, headers)

    def list_call_sessions(self, headers, params=None):
        return self._request("GET", "/call-sessions", headers=headers, params=params)

    def get_call_session(self, call_id, headers):
        return self._request("GET", f"/call-sessions/{call_id}", headers=headers)

    def connect_call(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/connect",
                             payload, headers)

    def complete_call(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/complete",
                             payload, headers)

    def drop_call(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/drop",
                             payload, headers)

    def amend_call(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/amend",
                             payload, headers)

    def finalize_amendment(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/finalize-amendment",
                             payload, headers)

    def attach_recording(self, call_id, payload, headers):
        return self._request("POST", f"/call-sessions/{call_id}/recordings",
                             payload, headers)

    # ─── Plans ───────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def add_formulary_drug(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/formulary-drugs",
                             payload, headers)

    def list_formulary_drugs(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/formulary-drugs",
                             headers=headers, params=params)

    def add_pharmacy_network_entry(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/pharmacy-network-entries",
                             payload, headers)

    def list_pharmacy_network_entries(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/pharmacy-network-entries",
                             headers=headers, params=params)

    def add_provider_directory_entry(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/provider-directory-entries",
                             payload, headers)

    def list_provider_directory_entries(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/provider-directory-entries",
                             headers=headers, params=params)

    def list_plan_enrollments(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/enrollments",
                             headers=headers, params=params)

    # ─── Plan comparison ─────────────────────────────────────
    def create_plan_comparison(self, payload, headers):
        return self._request("POST", "/plan-comparisons", payload, headers)

    # ─── Enrollments ─────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def acknowledge_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/acknowledge",
                             payload, headers)

    def effectuate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/effectuate",
                             {}, headers)

    def reject_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reject",
                             payload, headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw",
                             payload, headers)

    def disenroll_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/disenroll",
                             payload, headers)

    def commission_adjustment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/commission-adjustment",
                             payload, headers)

    # ─── Commission ledger ───────────────────────────────────
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/commission-ledger-entries", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/commission-ledger-entries",
                             headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/commission-ledger-entries/{entry_id}",
                             headers=headers)

    def finalize_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/commission-ledger-entries/{entry_id}/finalize",
                             {}, headers)

    def reverse_ledger_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/commission-ledger-entries/{entry_id}/reverse",
                             payload, headers)

    def reinstate_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/commission-ledger-entries/{entry_id}/reinstate",
                             {}, headers)

    def reinstate_finalized_entry(self, entry_id, headers):
        return self._request("POST",
                             f"/commission-ledger-entries/{entry_id}/reinstate-finalized",
                             {}, headers)

    # ─── Corrections ─────────────────────────────────────────
    def create_correction(self, payload, headers):
        return self._request("POST", "/corrections", payload, headers)

    def list_corrections(self, headers, params=None):
        return self._request("GET", "/corrections", headers=headers, params=params)

    # ─── Carrier reconciliation ──────────────────────────────
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/carrier-reconciliations", payload, headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/carrier-reconciliations",
                             headers=headers, params=params)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/carrier-reconciliations/{recon_id}",
                             headers=headers)

    def reconcile(self, recon_id, headers):
        return self._request("POST", f"/carrier-reconciliations/{recon_id}/reconcile",
                             {}, headers)

    def dispute_reconciliation(self, recon_id, payload, headers):
        return self._request("POST", f"/carrier-reconciliations/{recon_id}/dispute",
                             payload, headers)

    def reopen_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/carrier-reconciliations/{recon_id}/reopen",
                             {}, headers)

    def level_recognize(self, recon_id, headers):
        return self._request("POST",
                             f"/carrier-reconciliations/{recon_id}/level-recognize",
                             {}, headers)

    # ─── Complaints ──────────────────────────────────────────
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def begin_review(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/begin-review",
                             {}, headers)

    def substantiate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/substantiate",
                             {}, headers)

    def dismiss_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/dismiss",
                             {}, headers)

    def appeal_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/appeal",
                             payload, headers)

    def remand_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/remand",
                             {}, headers)

    def close_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close",
                             {}, headers)

    # ─── Coaching ────────────────────────────────────────────
    def create_coaching_assignment(self, payload, headers):
        return self._request("POST", "/coaching-assignments", payload, headers)

    def list_coaching_assignments(self, headers, params=None):
        return self._request("GET", "/coaching-assignments",
                             headers=headers, params=params)

    def get_coaching_assignment(self, coaching_id, headers):
        return self._request("GET", f"/coaching-assignments/{coaching_id}",
                             headers=headers)

    def start_coaching(self, coaching_id, headers):
        return self._request("POST", f"/coaching-assignments/{coaching_id}/start",
                             {}, headers)

    def complete_coaching(self, coaching_id, payload, headers):
        return self._request("POST", f"/coaching-assignments/{coaching_id}/complete",
                             payload, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]