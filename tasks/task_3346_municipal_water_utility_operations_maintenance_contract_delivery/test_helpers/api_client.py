"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- municipalities ---
    def register_municipality(self, payload, headers):
        return self._request("POST", "/water-om/municipalities", payload, headers)

    def get_municipality(self, municipality_id, headers):
        return self._request("GET", f"/water-om/municipalities/{municipality_id}", headers=headers)

    def list_municipality_contracts(self, municipality_id, headers, params=None):
        return self._request("GET", f"/water-om/municipalities/{municipality_id}/contracts", headers=headers, params=params)

    def award_contract(self, municipality_id, payload, headers):
        return self._request("POST", f"/water-om/municipalities/{municipality_id}/contracts", payload, headers)

    def get_benchmark(self, municipality_id, headers):
        return self._request("GET", f"/water-om/municipalities/{municipality_id}/benchmark", headers=headers)

    # --- contract lifecycle ---
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/water-om/contracts/{contract_id}", headers=headers)

    def mobilize_contract(self, contract_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/mobilize", payload or {}, headers)

    def commence_operating(self, contract_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/commence-operating", payload or {}, headers)

    def freeze_baseline(self, contract_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/freeze-baseline", payload or {}, headers)

    def open_or_close_review(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/reviews", payload, headers)

    def enter_renewal(self, contract_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/renewals", payload or {}, headers)

    def begin_hand_back(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/hand-back", payload, headers)

    def complete_hand_back(self, contract_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/complete-hand-back", payload or {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/terminate", payload, headers)

    def get_settlement(self, contract_id, headers):
        return self._request("GET", f"/water-om/contracts/{contract_id}/settlement", headers=headers)

    # --- performance standards ---
    def list_contract_standards(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/performance-standards", headers=headers, params=params)

    def create_standard(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/performance-standards", payload, headers)

    def get_standard(self, standard_id, headers):
        return self._request("GET", f"/water-om/performance-standards/{standard_id}", headers=headers)

    def activate_standard(self, contract_id, standard_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/performance-standards/{standard_id}/activate", payload or {}, headers)

    def suspend_standard(self, standard_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-standards/{standard_id}/suspend", payload or {}, headers)

    def clear_breach(self, standard_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-standards/{standard_id}/clear-breach", payload or {}, headers)

    def reactivate_standard(self, standard_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-standards/{standard_id}/reactivate", payload or {}, headers)

    def retire_standard(self, standard_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-standards/{standard_id}/retire", payload or {}, headers)

    # --- measurements ---
    def list_standard_measurements(self, standard_id, headers, params=None):
        return self._request("GET", f"/water-om/performance-standards/{standard_id}/measurements", headers=headers, params=params)

    def record_measurement(self, standard_id, payload, headers):
        return self._request("POST", f"/water-om/performance-standards/{standard_id}/measurements", payload, headers)

    def get_measurement(self, measurement_id, headers):
        return self._request("GET", f"/water-om/performance-measurements/{measurement_id}", headers=headers)

    def assess_measurement(self, measurement_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-measurements/{measurement_id}/assess", payload or {}, headers)

    def dispute_measurement(self, measurement_id, payload, headers):
        return self._request("POST", f"/water-om/performance-measurements/{measurement_id}/dispute", payload, headers)

    def revise_measurement(self, measurement_id, payload, headers):
        return self._request("POST", f"/water-om/performance-measurements/{measurement_id}/revise", payload, headers)

    def confirm_measurement(self, measurement_id, headers, payload=None):
        return self._request("POST", f"/water-om/performance-measurements/{measurement_id}/confirm", payload or {}, headers)

    def waive_measurement(self, measurement_id, payload, headers):
        return self._request("POST", f"/water-om/performance-measurements/{measurement_id}/waive", payload, headers)

    # --- staffing commitments ---
    def list_contract_staffing(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/staffing-commitments", headers=headers, params=params)

    def create_staffing_commitment(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/staffing-commitments", payload, headers)

    def get_staffing_commitment(self, commitment_id, headers):
        return self._request("GET", f"/water-om/staffing-commitments/{commitment_id}", headers=headers)

    def bind_staffing_commitment(self, contract_id, commitment_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/staffing-commitments/{commitment_id}/bind", payload or {}, headers)

    def evaluate_staffing_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/water-om/staffing-commitments/{commitment_id}/evaluate", payload, headers)

    def open_remedy_plan(self, commitment_id, payload, headers):
        return self._request("POST", f"/water-om/staffing-commitments/{commitment_id}/remedy", payload, headers)

    def suspend_staffing_commitment(self, commitment_id, headers, payload=None):
        return self._request("POST", f"/water-om/staffing-commitments/{commitment_id}/suspend", payload or {}, headers)

    # --- employees ---
    def list_contract_employees(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/employees", headers=headers, params=params)

    def register_employee(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/water-om/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/water-om/employees/{employee_id}", headers=headers)

    def offer_transfer(self, contract_id, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/contracts/{contract_id}/employees/{employee_id}/offer", payload or {}, headers)

    def accept_transfer_offer(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/accept", payload or {}, headers)

    def decline_transfer_offer(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/decline", payload or {}, headers)

    def transfer_employee(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/transfer", payload or {}, headers)

    def begin_induction(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/begin-induction", payload or {}, headers)

    def complete_induction(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/complete-induction", payload or {}, headers)

    def withdraw_offer(self, employee_id, headers, payload=None):
        return self._request("POST", f"/water-om/employees/{employee_id}/withdraw-offer", payload or {}, headers)

    def separate_employee(self, employee_id, payload, headers):
        return self._request("POST", f"/water-om/employees/{employee_id}/separate", payload, headers)

    # --- assets ---
    def list_contract_assets(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/assets", headers=headers, params=params)

    def register_asset(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/water-om/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/water-om/assets/{asset_id}", headers=headers)

    def list_asset_assessments(self, asset_id, headers, params=None):
        return self._request("GET", f"/water-om/assets/{asset_id}/baseline-assessments", headers=headers, params=params)

    def record_asset_assessment(self, asset_id, payload, headers):
        return self._request("POST", f"/water-om/assets/{asset_id}/baseline-assessments", payload, headers)

    def flag_replacement(self, asset_id, headers, payload=None):
        return self._request("POST", f"/water-om/assets/{asset_id}/flag-replacement", payload or {}, headers)

    def clear_replacement_flag(self, asset_id, headers, payload=None):
        return self._request("POST", f"/water-om/assets/{asset_id}/clear-replacement-flag", payload or {}, headers)

    def complete_replacement(self, asset_id, payload, headers):
        return self._request("POST", f"/water-om/assets/{asset_id}/complete-replacement", payload, headers)

    def take_asset_out_of_service(self, asset_id, headers, payload=None):
        return self._request("POST", f"/water-om/assets/{asset_id}/take-out-of-service", payload or {}, headers)

    def return_asset_to_service(self, asset_id, headers, payload=None):
        return self._request("POST", f"/water-om/assets/{asset_id}/return-to-service", payload or {}, headers)

    def retire_asset(self, asset_id, headers, payload=None):
        return self._request("POST", f"/water-om/assets/{asset_id}/retire", payload or {}, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/water-om/asset-assessments/{assessment_id}", headers=headers)

    def dispute_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/water-om/asset-assessments/{assessment_id}/dispute", payload or {}, headers)

    def revise_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/water-om/asset-assessments/{assessment_id}/revise", payload, headers)

    def accept_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/water-om/asset-assessments/{assessment_id}/accept", payload or {}, headers)

    # --- PM schedules ---
    def list_asset_pm_schedules(self, asset_id, headers, params=None):
        return self._request("GET", f"/water-om/assets/{asset_id}/pm-schedules", headers=headers, params=params)

    def create_pm_schedule(self, asset_id, payload, headers):
        return self._request("POST", f"/water-om/assets/{asset_id}/pm-schedules", payload, headers)

    def list_contract_pm_schedules(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/pm-schedules", headers=headers, params=params)

    def get_pm_schedule(self, schedule_id, headers):
        return self._request("GET", f"/water-om/pm-schedules/{schedule_id}", headers=headers)

    def regenerate_pm_schedule(self, schedule_id, headers, payload=None):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/regenerate", payload or {}, headers)

    def suspend_pm_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/suspend", payload, headers)

    def reactivate_pm_schedule(self, schedule_id, headers, payload=None):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/reactivate", payload or {}, headers)

    def close_out_pm_schedule(self, schedule_id, headers, payload=None):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/close-out", payload or {}, headers)

    def retire_pm_schedule(self, schedule_id, headers, payload=None):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/retire", payload or {}, headers)

    def evaluate_pm_schedule(self, schedule_id, headers, payload=None):
        return self._request("POST", f"/water-om/pm-schedules/{schedule_id}/evaluate", payload or {}, headers)

    # --- work orders ---
    def list_contract_work_orders(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/work-orders", headers=headers, params=params)

    def ingest_work_order(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/work-orders", payload, headers)

    def list_asset_work_orders(self, asset_id, headers, params=None):
        return self._request("GET", f"/water-om/assets/{asset_id}/work-orders", headers=headers, params=params)

    def raise_work_order(self, asset_id, payload, headers):
        return self._request("POST", f"/water-om/assets/{asset_id}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/water-om/work-orders/{work_order_id}", headers=headers)

    def schedule_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/schedule", payload or {}, headers)

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/start", payload or {}, headers)

    def pause_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/pause", payload, headers)

    def resume_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/resume", payload or {}, headers)

    def await_parts(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/await-parts", payload or {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/complete", payload, headers)

    def verify_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/verify", payload, headers)

    def return_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/return", payload, headers)

    def close_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/close", payload or {}, headers)

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/water-om/work-orders/{work_order_id}/cancel", payload or {}, headers)

    # --- permits ---
    def list_contract_permits(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/permits", headers=headers, params=params)

    def create_permit(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/water-om/permits/{permit_id}", headers=headers)

    def list_permit_allocations(self, permit_id, headers, params=None):
        return self._request("GET", f"/water-om/permits/{permit_id}/penalty-allocations", headers=headers, params=params)

    def create_penalty_allocation(self, permit_id, payload, headers):
        return self._request("POST", f"/water-om/permits/{permit_id}/penalty-allocations", payload, headers)

    def submit_permit_application(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/submit-application", payload or {}, headers)

    def issue_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/issue", payload or {}, headers)

    def activate_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/activate", payload or {}, headers)

    def record_notice_of_violation(self, permit_id, payload, headers):
        return self._request("POST", f"/water-om/permits/{permit_id}/notices-of-violation", payload, headers)

    def clear_violation(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/clear-violation", payload or {}, headers)

    def file_permit_renewal(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/file-renewal", payload or {}, headers)

    def activate_permit_renewal(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/activate-renewal", payload or {}, headers)

    def suspend_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/suspend", payload or {}, headers)

    def reinstate_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/water-om/permits/{permit_id}/reinstate", payload or {}, headers)

    def list_contract_allocations(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/penalty-allocations", headers=headers, params=params)

    # --- penalty allocations ---
    def get_penalty_allocation(self, allocation_id, headers):
        return self._request("GET", f"/water-om/penalty-allocations/{allocation_id}", headers=headers)

    def contest_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/water-om/penalty-allocations/{allocation_id}/contest", payload, headers)

    def adjust_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/water-om/penalty-allocations/{allocation_id}/adjust", payload, headers)

    def void_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/water-om/penalty-allocations/{allocation_id}/void", payload, headers)

    def settle_allocation(self, allocation_id, headers, payload=None):
        return self._request("POST", f"/water-om/penalty-allocations/{allocation_id}/settle", payload or {}, headers)

    # --- emergency events ---
    def list_contract_emergencies(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/emergency-events", headers=headers, params=params)

    def report_emergency(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/emergency-events", payload, headers)

    def get_emergency(self, event_id, headers):
        return self._request("GET", f"/water-om/emergency-events/{event_id}", headers=headers)

    def list_asset_emergencies(self, asset_id, headers, params=None):
        return self._request("GET", f"/water-om/assets/{asset_id}/emergency-events", headers=headers, params=params)

    def dispatch_emergency(self, event_id, headers, payload=None):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/dispatch", payload or {}, headers)

    def contain_emergency(self, event_id, payload, headers):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/contain", payload, headers)

    def restore_emergency(self, event_id, payload, headers):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/restore", payload, headers)

    def notify_emergency(self, event_id, payload, headers):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/notify", payload, headers)

    def escalate_emergency(self, event_id, payload, headers):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/escalate", payload, headers)

    def investigate_emergency(self, event_id, headers, payload=None):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/investigate", payload or {}, headers)

    def close_emergency(self, event_id, headers, payload=None):
        return self._request("POST", f"/water-om/emergency-events/{event_id}/close", payload or {}, headers)

    # --- renewal proposals ---
    def list_contract_proposals(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/renewal-proposals", headers=headers, params=params)

    def submit_renewal_proposal(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/renewal-proposals", payload, headers)

    def get_renewal_proposal(self, proposal_id, headers):
        return self._request("GET", f"/water-om/renewal-proposals/{proposal_id}", headers=headers)

    def review_renewal_proposal(self, proposal_id, headers, payload=None):
        return self._request("POST", f"/water-om/renewal-proposals/{proposal_id}/review", payload or {}, headers)

    def counter_renewal_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/water-om/renewal-proposals/{proposal_id}/counter", payload, headers)

    def accept_renewal_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/water-om/renewal-proposals/{proposal_id}/accept", payload, headers)

    def reject_renewal_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/water-om/renewal-proposals/{proposal_id}/reject", payload, headers)

    def withdraw_renewal_proposal(self, proposal_id, headers, payload=None):
        return self._request("POST", f"/water-om/renewal-proposals/{proposal_id}/withdraw", payload or {}, headers)

    # --- transition obligations ---
    def list_contract_obligations(self, contract_id, headers, params=None):
        return self._request("GET", f"/water-om/contracts/{contract_id}/transition-obligations", headers=headers, params=params)

    def create_obligation(self, contract_id, payload, headers):
        return self._request("POST", f"/water-om/contracts/{contract_id}/transition-obligations", payload, headers)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/water-om/transition-obligations/{obligation_id}", headers=headers)

    def start_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/start", payload or {}, headers)

    def satisfy_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/satisfy", payload, headers)

    def dispute_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/dispute", payload, headers)

    def uphold_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/uphold", payload or {}, headers)

    def waive_obligation(self, obligation_id, payload, headers):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/waive", payload, headers)

    def evaluate_obligation(self, obligation_id, headers, payload=None):
        return self._request("POST", f"/water-om/transition-obligations/{obligation_id}/evaluate", payload or {}, headers)

    # --- logical clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/water-om/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()