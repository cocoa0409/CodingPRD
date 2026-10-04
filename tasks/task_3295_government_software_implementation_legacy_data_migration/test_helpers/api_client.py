"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- agencies / calendar / staff ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/programs/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/programs/agencies/{agency_id}", headers=headers)

    def create_calendar_window(self, agency_id, payload, headers):
        return self._request("POST", f"/programs/agencies/{agency_id}/calendar-windows", payload, headers)

    def list_calendar_windows(self, agency_id, headers, params=None):
        return self._request("GET", f"/programs/agencies/{agency_id}/calendar-windows", headers=headers, params=params)

    def create_staff(self, agency_id, payload, headers):
        return self._request("POST", f"/programs/agencies/{agency_id}/staff", payload, headers)

    def list_staff(self, agency_id, headers, params=None):
        return self._request("GET", f"/programs/agencies/{agency_id}/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/programs/staff/{staff_id}", headers=headers)

    def create_unavailability_window(self, staff_id, payload, headers):
        return self._request("POST", f"/programs/staff/{staff_id}/unavailability-windows", payload, headers)

    def list_unavailability_windows(self, staff_id, headers, params=None):
        return self._request("GET", f"/programs/staff/{staff_id}/unavailability-windows", headers=headers, params=params)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/programs/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/programs/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/programs/contracts", headers=headers, params=params)

    def transition_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/transition", payload, headers)

    def award_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/award", payload, headers)

    def start_implementation(self, contract_id, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/start-implementation", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/close", {}, headers)

    def cancel_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/cancel", payload, headers)

    # --- phases / milestones / criteria ---
    def create_phase(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/phases", payload, headers)

    def list_phases(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/phases", headers=headers, params=params)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/programs/phases/{phase_id}", headers=headers)

    def create_milestone(self, phase_id, payload, headers):
        return self._request("POST", f"/programs/phases/{phase_id}/milestones", payload, headers)

    def list_phase_milestones(self, phase_id, headers, params=None):
        return self._request("GET", f"/programs/phases/{phase_id}/milestones", headers=headers, params=params)

    def list_contract_milestones(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/programs/milestones/{milestone_id}", headers=headers)

    def create_criterion(self, milestone_id, payload, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/criteria", payload, headers)

    def list_criteria(self, milestone_id, headers, params=None):
        return self._request("GET", f"/programs/milestones/{milestone_id}/criteria", headers=headers, params=params)

    def record_criterion_result(self, criterion_id, payload, headers):
        return self._request("POST", f"/programs/criteria/{criterion_id}/result", payload, headers)

    def submit_milestone(self, milestone_id, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/submit", {}, headers)

    def accept_milestone(self, milestone_id, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/accept", {}, headers)

    def reject_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/reject", payload, headers)

    def resubmit_milestone(self, milestone_id, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/resubmit", {}, headers)

    def invoice_milestone(self, milestone_id, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/invoice", {}, headers)

    def mark_milestone_paid(self, milestone_id, headers):
        return self._request("POST", f"/programs/milestones/{milestone_id}/mark-paid", {}, headers)

    # --- workflow processes / decisions ---
    def create_workflow_process(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/workflow-processes", payload, headers)

    def list_workflow_processes(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/workflow-processes", headers=headers, params=params)

    def get_workflow_process(self, process_id, headers):
        return self._request("GET", f"/programs/workflow-processes/{process_id}", headers=headers)

    def map_process(self, process_id, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/map", {}, headers)

    def submit_process_review(self, process_id, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/submit-review", {}, headers)

    def approve_process(self, process_id, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/approve", {}, headers)

    def send_process_rework(self, process_id, payload, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/send-rework", payload, headers)

    def remap_process(self, process_id, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/remap", {}, headers)

    def retire_process(self, process_id, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/retire", {}, headers)

    def create_decision(self, process_id, payload, headers):
        return self._request("POST", f"/programs/workflow-processes/{process_id}/decisions", payload, headers)

    def list_process_decisions(self, process_id, headers, params=None):
        return self._request("GET", f"/programs/workflow-processes/{process_id}/decisions", headers=headers, params=params)

    def list_contract_decisions(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/programs/decisions/{decision_id}", headers=headers)

    def list_supersessions(self, decision_id, headers, params=None):
        return self._request("GET", f"/programs/decisions/{decision_id}/supersessions", headers=headers, params=params)

    def ratify_decision(self, decision_id, headers):
        return self._request("POST", f"/programs/decisions/{decision_id}/ratify", {}, headers)

    def reject_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/programs/decisions/{decision_id}/reject", payload, headers)

    # --- migration ---
    def create_migration_batch(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/migration-batches", payload, headers)

    def list_migration_batches(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/migration-batches", headers=headers, params=params)

    def get_migration_batch(self, batch_id, headers):
        return self._request("GET", f"/programs/migration-batches/{batch_id}", headers=headers)

    def ingest_records(self, batch_id, payload, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/records", payload, headers)

    def list_records(self, batch_id, headers, params=None):
        return self._request("GET", f"/programs/migration-batches/{batch_id}/records", headers=headers, params=params)

    def extract_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/extract", {}, headers)

    def cleanse_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/cleanse", payload, headers)

    def load_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/load", {}, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/reconcile", {}, headers)

    def list_reconciliation_reports(self, batch_id, headers, params=None):
        return self._request("GET", f"/programs/migration-batches/{batch_id}/reconciliation-reports", headers=headers, params=params)

    def recleanse_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/recleanse", {}, headers)

    def accept_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/migration-batches/{batch_id}/accept", {}, headers)

    # --- interfaces / certifications ---
    def create_interface(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/interfaces", payload, headers)

    def list_interfaces(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/interfaces", headers=headers, params=params)

    def get_interface(self, interface_id, headers):
        return self._request("GET", f"/programs/interfaces/{interface_id}", headers=headers)

    def start_interface_development(self, interface_id, headers):
        return self._request("POST", f"/programs/interfaces/{interface_id}/start-development", {}, headers)

    def start_interface_testing(self, interface_id, headers):
        return self._request("POST", f"/programs/interfaces/{interface_id}/start-testing", {}, headers)

    def create_certification(self, interface_id, payload, headers):
        return self._request("POST", f"/programs/interfaces/{interface_id}/certifications", payload, headers)

    def list_certifications(self, interface_id, headers, params=None):
        return self._request("GET", f"/programs/interfaces/{interface_id}/certifications", headers=headers, params=params)

    def list_contract_certifications(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/interface-certifications", headers=headers, params=params)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/programs/interface-certifications/{cert_id}", headers=headers)

    def begin_certification(self, cert_id, headers):
        return self._request("POST", f"/programs/interface-certifications/{cert_id}/begin", {}, headers)

    def pass_certification(self, cert_id, headers):
        return self._request("POST", f"/programs/interface-certifications/{cert_id}/pass", {}, headers)

    def fail_certification(self, cert_id, payload, headers):
        return self._request("POST", f"/programs/interface-certifications/{cert_id}/fail", payload, headers)

    def retry_certification(self, cert_id, payload, headers):
        return self._request("POST", f"/programs/interface-certifications/{cert_id}/retry", payload, headers)

    def cancel_certification(self, cert_id, headers):
        return self._request("POST", f"/programs/interface-certifications/{cert_id}/cancel", {}, headers)

    # --- UAT ---
    def create_uat_cycle(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/uat-cycles", payload, headers)

    def list_uat_cycles(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/uat-cycles", headers=headers, params=params)

    def get_uat_cycle(self, cycle_id, headers):
        return self._request("GET", f"/programs/uat-cycles/{cycle_id}", headers=headers)

    def create_uat_session(self, cycle_id, payload, headers):
        return self._request("POST", f"/programs/uat-cycles/{cycle_id}/sessions", payload, headers)

    def list_uat_sessions(self, cycle_id, headers, params=None):
        return self._request("GET", f"/programs/uat-cycles/{cycle_id}/sessions", headers=headers, params=params)

    def record_uat_session_result(self, session_id, payload, headers):
        return self._request("POST", f"/programs/uat-sessions/{session_id}/record-result", payload, headers)

    def start_uat_cycle(self, cycle_id, headers):
        return self._request("POST", f"/programs/uat-cycles/{cycle_id}/start", {}, headers)

    def block_uat_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/programs/uat-cycles/{cycle_id}/block", payload, headers)

    def complete_uat_cycle(self, cycle_id, headers):
        return self._request("POST", f"/programs/uat-cycles/{cycle_id}/complete", {}, headers)

    def list_staff_uat_sessions(self, staff_id, headers, params=None):
        return self._request("GET", f"/programs/staff/{staff_id}/uat-sessions", headers=headers, params=params)

    # --- training ---
    def create_training_session(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/training-sessions", payload, headers)

    def list_training_sessions(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/training-sessions", headers=headers, params=params)

    def get_training_session(self, session_id, headers):
        return self._request("GET", f"/programs/training-sessions/{session_id}", headers=headers)

    def create_enrollment(self, session_id, payload, headers):
        return self._request("POST", f"/programs/training-sessions/{session_id}/enrollments", payload, headers)

    def list_enrollments(self, session_id, headers, params=None):
        return self._request("GET", f"/programs/training-sessions/{session_id}/enrollments", headers=headers, params=params)

    def record_enrollment_outcome(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/training-enrollments/{enrollment_id}/record-outcome", payload, headers)

    def mark_training_delivered(self, session_id, headers):
        return self._request("POST", f"/programs/training-sessions/{session_id}/mark-delivered", {}, headers)

    def cancel_training_session(self, session_id, headers):
        return self._request("POST", f"/programs/training-sessions/{session_id}/cancel", {}, headers)

    def list_staff_enrollments(self, staff_id, headers, params=None):
        return self._request("GET", f"/programs/staff/{staff_id}/training-enrollments", headers=headers, params=params)

    # --- go-live ---
    def create_go_live_event(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/go-live-events", payload, headers)

    def list_go_live_events(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/go-live-events", headers=headers, params=params)

    def get_go_live_event(self, event_id, headers):
        return self._request("GET", f"/programs/go-live-events/{event_id}", headers=headers)

    def readiness_check(self, event_id, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/readiness-check", {}, headers)

    def approve_go_live(self, event_id, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/approve", {}, headers)

    def revise_go_live(self, event_id, payload, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/revise", payload, headers)

    def execute_go_live(self, event_id, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/execute", {}, headers)

    def rollback_go_live(self, event_id, payload, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/rollback", payload, headers)

    def replan_go_live(self, event_id, payload, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/replan", payload, headers)

    def cancel_go_live(self, event_id, headers):
        return self._request("POST", f"/programs/go-live-events/{event_id}/cancel", {}, headers)

    # --- support ---
    def list_support_transitions(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/support-transitions", headers=headers, params=params)

    def get_support_transition(self, transition_id, headers):
        return self._request("GET", f"/programs/support-transitions/{transition_id}", headers=headers)

    def advance_support_transition(self, transition_id, headers):
        return self._request("POST", f"/programs/support-transitions/{transition_id}/advance", {}, headers)

    def sunset_support_transition(self, transition_id, headers):
        return self._request("POST", f"/programs/support-transitions/{transition_id}/sunset", {}, headers)

    def create_ticket(self, transition_id, payload, headers):
        return self._request("POST", f"/programs/support-transitions/{transition_id}/tickets", payload, headers)

    def list_tickets(self, transition_id, headers, params=None):
        return self._request("GET", f"/programs/support-transitions/{transition_id}/tickets", headers=headers, params=params)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/programs/support-tickets/{ticket_id}/resolve", payload, headers)

    # --- maintenance ---
    def create_maintenance_agreement(self, contract_id, payload, headers):
        return self._request("POST", f"/programs/contracts/{contract_id}/maintenance-agreements", payload, headers)

    def list_maintenance_agreements(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/maintenance-agreements", headers=headers, params=params)

    def get_maintenance_agreement(self, agreement_id, headers):
        return self._request("GET", f"/programs/maintenance-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/programs/maintenance-agreements/{agreement_id}/activate", {}, headers)

    def renew_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/programs/maintenance-agreements/{agreement_id}/renew", payload, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/programs/maintenance-agreements/{agreement_id}/suspend", {}, headers)

    # --- audit ---
    def list_audit_log(self, contract_id, headers, params=None):
        return self._request("GET", f"/programs/contracts/{contract_id}/audit-log", headers=headers, params=params)


api_client = ApiClient()
