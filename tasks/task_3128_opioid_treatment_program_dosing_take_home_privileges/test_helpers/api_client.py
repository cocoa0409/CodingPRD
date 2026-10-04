"""API client: one method per endpoint defined in the PRD (PRD §4).

Every method returns the raw requests.Response so tests can assert status codes.
Subclasses the framework's GenericApiClient, which supplies _request().
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/otp/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Programs ────────────────────────────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/otp/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/otp/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/otp/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/otp/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/otp/programs/{program_id}/resume", {}, headers)

    def open_carry_quota(self, program_id, payload, headers):
        return self._request("POST", f"/otp/programs/{program_id}/carry-quota", payload, headers)

    def get_carry_quota(self, program_id, headers):
        return self._request("GET", f"/otp/programs/{program_id}/carry-quota", headers=headers)

    # ─── Users ───────────────────────────────────────────────────────────────
    def create_user(self, payload, headers):
        return self._request("POST", "/otp/users", payload, headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/otp/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/otp/users/{user_id}", headers=headers)

    # ─── Patients ────────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/otp/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/otp/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/otp/patients/{patient_id}", headers=headers)

    def confirm_diagnosis(self, patient_id, headers):
        return self._request("POST", f"/otp/patients/{patient_id}/confirm-diagnosis", {}, headers)

    def reinstate_patient(self, patient_id, headers):
        return self._request("POST", f"/otp/patients/{patient_id}/reinstate", {}, headers)

    def discharge_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/otp/patients/{patient_id}/discharge", payload, headers)

    def complete_withdrawal(self, patient_id, headers):
        return self._request("POST", f"/otp/patients/{patient_id}/complete-withdrawal", {}, headers)

    def patch_treatment_phase(self, patient_id, payload, headers):
        return self._request("PATCH", f"/otp/patients/{patient_id}/treatment-phase", payload, headers)

    def get_time_in_treatment_tracker(self, patient_id, headers):
        return self._request("GET", f"/otp/patients/{patient_id}/time-in-treatment-tracker",
                             headers=headers)

    # ─── Dose orders ─────────────────────────────────────────────────────────
    def create_dose_order(self, payload, headers):
        return self._request("POST", "/otp/dose-orders", payload, headers)

    def list_dose_orders(self, headers, params=None):
        return self._request("GET", "/otp/dose-orders", headers=headers, params=params)

    def get_dose_order(self, dose_order_id, headers):
        return self._request("GET", f"/otp/dose-orders/{dose_order_id}", headers=headers)

    def activate_dose_order(self, dose_order_id, headers):
        return self._request("POST", f"/otp/dose-orders/{dose_order_id}/activate", {}, headers)

    def suspend_dose_order(self, dose_order_id, headers):
        return self._request("POST", f"/otp/dose-orders/{dose_order_id}/suspend", {}, headers)

    def discontinue_dose_order(self, dose_order_id, headers):
        return self._request("POST", f"/otp/dose-orders/{dose_order_id}/discontinue", {}, headers)

    # ─── Dose dispenses ──────────────────────────────────────────────────────
    def create_dose_dispense(self, payload, headers):
        return self._request("POST", "/otp/dose-dispenses", payload, headers)

    def list_dose_dispenses(self, headers, params=None):
        return self._request("GET", "/otp/dose-dispenses", headers=headers, params=params)

    def get_dose_dispense(self, dose_id, headers):
        return self._request("GET", f"/otp/dose-dispenses/{dose_id}", headers=headers)

    def check_in(self, dose_id, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/check-in", {}, headers)

    def verify_dose(self, dose_id, payload, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/verify", payload, headers)

    def dispense_dose(self, dose_id, payload, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/dispense", payload, headers)

    def complete_dose(self, dose_id, payload, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/complete", payload, headers)

    def refuse_dose(self, dose_id, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/refuse", {}, headers)

    def cancel_dose(self, dose_id, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/cancel", {}, headers)

    def reschedule_dose(self, dose_id, payload, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/reschedule", payload, headers)

    def mark_missed(self, dose_id, headers):
        return self._request("POST", f"/otp/dose-dispenses/{dose_id}/mark-missed", {}, headers)

    def get_charge_preview(self, dose_id, headers):
        return self._request("GET", f"/otp/dose-dispenses/{dose_id}/charge-preview", headers=headers)

    # ─── Take-home privileges ────────────────────────────────────────────────
    def create_privilege(self, payload, headers):
        return self._request("POST", "/otp/take-home-privileges", payload, headers)

    def list_privileges(self, headers, params=None):
        return self._request("GET", "/otp/take-home-privileges", headers=headers, params=params)

    def get_privilege(self, privilege_id, headers):
        return self._request("GET", f"/otp/take-home-privileges/{privilege_id}", headers=headers)

    def evaluate_privilege(self, privilege_id, headers):
        return self._request("POST", f"/otp/take-home-privileges/{privilege_id}/evaluate", {}, headers)

    def revoke_privilege(self, privilege_id, headers):
        return self._request("POST", f"/otp/take-home-privileges/{privilege_id}/revoke", {}, headers)

    # ─── Take-home exceptions ────────────────────────────────────────────────
    def create_exception(self, payload, headers):
        return self._request("POST", "/otp/take-home-exceptions", payload, headers)

    def list_exceptions(self, headers, params=None):
        return self._request("GET", "/otp/take-home-exceptions", headers=headers, params=params)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/otp/take-home-exceptions/{exception_id}", headers=headers)

    def route_exception(self, exception_id, headers):
        return self._request("POST", f"/otp/take-home-exceptions/{exception_id}/route", {}, headers)

    def decide_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/otp/take-home-exceptions/{exception_id}/decision",
                             payload, headers)

    def revoke_exception(self, exception_id, headers):
        return self._request("POST", f"/otp/take-home-exceptions/{exception_id}/revoke", {}, headers)

    # ─── Carry ledgers ───────────────────────────────────────────────────────
    def list_carry_ledgers(self, headers, params=None):
        return self._request("GET", "/otp/take-home-carry-ledgers", headers=headers, params=params)

    def get_carry_ledger(self, ledger_id, headers):
        return self._request("GET", f"/otp/take-home-carry-ledgers/{ledger_id}", headers=headers)

    # ─── Inventory ───────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/otp/inventory-lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/otp/inventory-lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/otp/inventory-lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/otp/inventory-lots/{lot_id}/quarantine", {}, headers)

    def release_quarantine(self, lot_id, headers):
        return self._request("POST", f"/otp/inventory-lots/{lot_id}/release-quarantine", {}, headers)

    def destroy_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/otp/inventory-lots/{lot_id}/destroy", payload, headers)

    def create_transaction(self, payload, headers):
        return self._request("POST", "/otp/inventory-transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/otp/inventory-transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/otp/inventory-transactions/{transaction_id}", headers=headers)

    def close_reconciliation(self, period, payload, headers):
        return self._request("POST", f"/otp/inventory-reconciliations/{period}/close",
                             payload, headers)

    def get_reconciliation(self, headers, params=None):
        return self._request("GET", "/otp/inventory-reconciliations", headers=headers, params=params)

    # ─── Counseling and plan reviews ─────────────────────────────────────────
    def create_counseling_session(self, payload, headers):
        return self._request("POST", "/otp/counseling-sessions", payload, headers)

    def list_counseling_sessions(self, headers, params=None):
        return self._request("GET", "/otp/counseling-sessions", headers=headers, params=params)

    def get_counseling_session(self, session_id, headers):
        return self._request("GET", f"/otp/counseling-sessions/{session_id}", headers=headers)

    def complete_counseling_session(self, session_id, payload, headers):
        return self._request("POST", f"/otp/counseling-sessions/{session_id}/complete",
                             payload, headers)

    def no_show_counseling_session(self, session_id, headers):
        return self._request("POST", f"/otp/counseling-sessions/{session_id}/no-show", {}, headers)

    def create_plan_review(self, payload, headers):
        return self._request("POST", "/otp/treatment-plan-reviews", payload, headers)

    def list_plan_reviews(self, headers, params=None):
        return self._request("GET", "/otp/treatment-plan-reviews", headers=headers, params=params)

    def get_plan_review(self, review_id, headers):
        return self._request("GET", f"/otp/treatment-plan-reviews/{review_id}", headers=headers)

    # ─── Guest dosing ────────────────────────────────────────────────────────
    def create_arrangement(self, payload, headers):
        return self._request("POST", "/otp/guest-dosing-arrangements", payload, headers)

    def list_arrangements(self, headers, params=None):
        return self._request("GET", "/otp/guest-dosing-arrangements", headers=headers, params=params)

    def get_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/otp/guest-dosing-arrangements/{arrangement_id}",
                             headers=headers)

    def transmit_arrangement(self, arrangement_id, headers):
        return self._request("POST",
                             f"/otp/guest-dosing-arrangements/{arrangement_id}/transmit", {}, headers)

    def acknowledge_arrangement(self, arrangement_id, headers):
        return self._request("POST",
                             f"/otp/guest-dosing-arrangements/{arrangement_id}/acknowledge", {}, headers)

    def reject_arrangement(self, arrangement_id, headers):
        return self._request("POST",
                             f"/otp/guest-dosing-arrangements/{arrangement_id}/reject", {}, headers)

    def close_arrangement(self, arrangement_id, headers):
        return self._request("POST",
                             f"/otp/guest-dosing-arrangements/{arrangement_id}/close", {}, headers)

    def cancel_arrangement(self, arrangement_id, headers):
        return self._request("POST",
                             f"/otp/guest-dosing-arrangements/{arrangement_id}/cancel", {}, headers)

    # ─── Compliance and inspection readiness ─────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/otp/compliance-inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/otp/compliance-inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/otp/compliance-inspections/{inspection_id}", headers=headers)

    def get_readiness(self, inspection_id, headers):
        return self._request("GET", f"/otp/compliance-inspections/{inspection_id}/readiness",
                             headers=headers)

    def begin_inspection(self, inspection_id, headers):
        return self._request("POST", f"/otp/compliance-inspections/{inspection_id}/begin", {}, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/otp/compliance-inspections/{inspection_id}/complete", {}, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/otp/compliance-inspections/{inspection_id}/cancel", {}, headers)

    def create_finding(self, payload, headers):
        return self._request("POST", "/otp/compliance-findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/otp/compliance-findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/otp/compliance-findings/{finding_id}", headers=headers)

    def create_corrective_action(self, payload, headers):
        return self._request("POST", "/otp/corrective-actions", payload, headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/otp/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/otp/corrective-actions/{action_id}", headers=headers)

    def implement_corrective_action(self, action_id, headers):
        return self._request("POST", f"/otp/corrective-actions/{action_id}/implement", {}, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/otp/corrective-actions/{action_id}/verify", {}, headers)

    def cancel_corrective_action(self, action_id, headers):
        return self._request("POST", f"/otp/corrective-actions/{action_id}/cancel", {}, headers)

    # ─── Diversion control ───────────────────────────────────────────────────
    def create_diversion_case(self, payload, headers):
        return self._request("POST", "/otp/diversion-cases", payload, headers)

    def list_diversion_cases(self, headers, params=None):
        return self._request("GET", "/otp/diversion-cases", headers=headers, params=params)

    def get_diversion_case(self, case_id, headers):
        return self._request("GET", f"/otp/diversion-cases/{case_id}", headers=headers)

    def begin_review(self, case_id, headers):
        return self._request("POST", f"/otp/diversion-cases/{case_id}/begin-review", {}, headers)

    def confirm_diversion(self, case_id, payload, headers):
        return self._request("POST", f"/otp/diversion-cases/{case_id}/confirm", payload, headers)

    def unsubstantiate_diversion(self, case_id, payload, headers):
        return self._request("POST", f"/otp/diversion-cases/{case_id}/unsubstantiate",
                             payload, headers)

    def close_diversion_case(self, case_id, headers):
        return self._request("POST", f"/otp/diversion-cases/{case_id}/close", {}, headers)


api_client = ApiClient()