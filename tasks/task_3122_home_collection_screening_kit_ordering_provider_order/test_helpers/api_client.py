"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/screening/_clock/set_current_utc", payload, headers)

    # --- HealthPlanProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/screening/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/screening/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/screening/programs/{program_id}", headers=headers)

    # --- MemberCohort ---
    def list_program_cohorts(self, program_id, headers, params=None):
        return self._request("GET", f"/screening/programs/{program_id}/cohorts", headers=headers, params=params)

    def enroll_cohort(self, program_id, payload, headers):
        return self._request("POST", f"/screening/programs/{program_id}/cohorts", payload, headers)

    def get_program_cohort(self, program_id, cohort_id, headers):
        return self._request("GET", f"/screening/programs/{program_id}/cohorts/{cohort_id}", headers=headers)

    def dispatch_outreach(self, program_id, cohort_id, payload, headers):
        return self._request("POST", f"/screening/programs/{program_id}/cohorts/{cohort_id}/outreach", payload, headers)

    def exclude_cohort(self, program_id, cohort_id, headers):
        return self._request("POST", f"/screening/programs/{program_id}/cohorts/{cohort_id}/exclude", {}, headers)

    def list_cohort_outreach_events(self, program_id, cohort_id, headers):
        return self._request("GET", f"/screening/programs/{program_id}/cohorts/{cohort_id}/outreach-events", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/screening/cohorts", headers=headers, params=params)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/screening/cohorts/{cohort_id}", headers=headers)

    # --- OutreachEvent ---
    def list_outreach_events(self, headers, params=None):
        return self._request("GET", "/screening/outreach-events", headers=headers, params=params)

    def get_outreach_event(self, event_id, headers):
        return self._request("GET", f"/screening/outreach-events/{event_id}", headers=headers)

    # --- Reminder ---
    def list_reminders(self, headers, params=None):
        return self._request("GET", "/screening/reminders", headers=headers, params=params)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/screening/reminders/{reminder_id}", headers=headers)

    def list_order_reminders(self, order_id, headers):
        return self._request("GET", f"/screening/orders/{order_id}/reminders", headers=headers)

    def dispatch_reminders(self, order_id, headers):
        return self._request("POST", f"/screening/orders/{order_id}/reminders/dispatch", {}, headers)

    # --- QualityMeasureReport ---
    def create_quality_measure_report(self, program_id, headers):
        return self._request("POST", f"/screening/programs/{program_id}/quality-measure-report", {}, headers)

    def list_program_quality_measure_reports(self, program_id, headers):
        return self._request("GET", f"/screening/programs/{program_id}/quality-measure-reports", headers=headers)

    def list_quality_measure_reports(self, headers, params=None):
        return self._request("GET", "/screening/quality-measure-reports", headers=headers, params=params)

    def get_quality_measure_report(self, report_id, headers):
        return self._request("GET", f"/screening/quality-measure-reports/{report_id}", headers=headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/screening/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/screening/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/screening/patients/{patient_id}", headers=headers)

    def opt_out_patient(self, patient_id, headers):
        return self._request("POST", f"/screening/patients/{patient_id}/opt-out", {}, headers)

    def get_patient_risk_score(self, patient_id, headers):
        return self._request("GET", f"/screening/patients/{patient_id}/risk-score", headers=headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/screening/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/screening/providers/{provider_id}", headers=headers)

    # --- ScreeningOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/screening/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/screening/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/screening/orders/{order_id}", headers=headers)

    def confirm_eligibility(self, order_id, headers):
        return self._request("POST", f"/screening/orders/{order_id}/eligibility/confirm", {}, headers)

    def reject_eligibility(self, order_id, headers):
        return self._request("POST", f"/screening/orders/{order_id}/eligibility/reject", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/screening/orders/{order_id}/cancel", {}, headers)

    def create_kit(self, order_id, payload, headers):
        return self._request("POST", f"/screening/orders/{order_id}/kit", payload, headers)

    def list_order_kits(self, order_id, headers):
        return self._request("GET", f"/screening/orders/{order_id}/kits", headers=headers)

    def get_order_sla(self, order_id, headers):
        return self._request("GET", f"/screening/orders/{order_id}/sla", headers=headers)

    def list_order_results(self, order_id, headers):
        return self._request("GET", f"/screening/orders/{order_id}/results", headers=headers)

    # --- ScreeningKit ---
    def list_kits(self, headers, params=None):
        return self._request("GET", "/screening/kits", headers=headers, params=params)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/screening/kits/{kit_id}", headers=headers)

    def ship_kit(self, kit_id, headers):
        return self._request("POST", f"/screening/kits/{kit_id}/ship", {}, headers)

    def return_kit(self, kit_id, headers):
        return self._request("POST", f"/screening/kits/{kit_id}/return", {}, headers)

    # --- LabSpecimen ---
    def accession_specimen(self, order_id, headers):
        return self._request("POST", f"/screening/orders/{order_id}/specimens", {}, headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/screening/specimens", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/screening/specimens/{specimen_id}", headers=headers)

    def list_kit_specimens(self, kit_id, headers):
        return self._request("GET", f"/screening/kits/{kit_id}/specimens", headers=headers)

    def process_specimen(self, specimen_id, headers):
        return self._request("POST", f"/screening/specimens/{specimen_id}/process", {}, headers)

    def record_adequacy(self, specimen_id, payload, headers):
        return self._request("POST", f"/screening/specimens/{specimen_id}/adequacy", payload, headers)

    def result_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/screening/specimens/{specimen_id}/result", payload, headers)

    # --- ScreeningResult / navigation ---
    def list_results(self, headers, params=None):
        return self._request("GET", "/screening/results", headers=headers, params=params)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/screening/results/{result_id}", headers=headers)

    def schedule_navigation(self, result_id, headers):
        return self._request("POST", f"/screening/results/{result_id}/navigation/schedule", {}, headers)

    def complete_navigation(self, result_id, headers):
        return self._request("POST", f"/screening/results/{result_id}/navigation/complete", {}, headers)


api_client = ApiClient()
