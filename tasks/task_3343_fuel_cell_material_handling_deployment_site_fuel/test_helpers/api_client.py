"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def close_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/close", {}, headers)

    def record_productivity(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/record-productivity", payload, headers)

    # --- assessments ---
    def create_assessment(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/assessments", payload, headers)

    def list_assessments(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def update_assessment(self, assessment_id, payload, headers):
        return self._request("PUT", f"/api/assessments/{assessment_id}", payload, headers)

    def submit_assessment(self, site_id, assessment_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/assessments/{assessment_id}/submit", {}, headers)

    def approve_assessment(self, site_id, assessment_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/assessments/{assessment_id}/approve", {}, headers)

    def reject_assessment(self, site_id, assessment_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/assessments/{assessment_id}/reject", {}, headers)

    def revise_assessment(self, site_id, assessment_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/assessments/{assessment_id}/revise", {}, headers)

    # --- supply contracts ---
    def create_supply_contract(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/supply-contracts", payload, headers)

    def list_supply_contracts(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/supply-contracts", headers=headers, params=params)

    def get_supply_contract(self, contract_id, headers):
        return self._request("GET", f"/api/supply-contracts/{contract_id}", headers=headers)

    def list_contract_fueling_events(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/supply-contracts/{contract_id}/fueling-events", headers=headers, params=params)

    def list_contract_invoices(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/supply-contracts/{contract_id}/invoices", headers=headers, params=params)

    def activate_supply_contract(self, site_id, contract_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/supply-contracts/{contract_id}/activate", {}, headers)

    def terminate_supply_contract(self, site_id, contract_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/supply-contracts/{contract_id}/terminate", {}, headers)

    # --- stations & permits ---
    def create_station(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/stations", payload, headers)

    def list_stations(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/api/stations/{station_id}", headers=headers)

    def update_station(self, station_id, payload, headers):
        return self._request("PUT", f"/api/stations/{station_id}", payload, headers)

    def start_construction(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/start-construction", {}, headers)

    def commission_station(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/commission", {}, headers)

    def create_permit(self, station_id, payload, headers):
        return self._request("POST", f"/api/stations/{station_id}/permits", payload, headers)

    def list_permits(self, station_id, headers, params=None):
        return self._request("GET", f"/api/stations/{station_id}/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def issue_permit(self, station_id, permit_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/permits/{permit_id}/issue", {}, headers)

    def reject_permit(self, station_id, permit_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/permits/{permit_id}/reject", {}, headers)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/api/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def list_technician_events(self, technician_id, headers, params=None):
        return self._request("GET", f"/api/technicians/{technician_id}/conversion-events", headers=headers, params=params)

    # --- conversion plans & events ---
    def create_conversion_plan(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/conversion-plans", payload, headers)

    def list_conversion_plans(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/conversion-plans", headers=headers, params=params)

    def get_conversion_plan(self, plan_id, headers):
        return self._request("GET", f"/api/conversion-plans/{plan_id}", headers=headers)

    def schedule_plan(self, site_id, plan_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/conversion-plans/{plan_id}/schedule", payload, headers)

    def revert_plan(self, site_id, plan_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/conversion-plans/{plan_id}/revert", {}, headers)

    def cancel_plan(self, site_id, plan_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/conversion-plans/{plan_id}/cancel", {}, headers)

    def create_conversion_event(self, plan_id, payload, headers):
        return self._request("POST", f"/api/conversion-plans/{plan_id}/conversion-events", payload, headers)

    def list_plan_events(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/conversion-plans/{plan_id}/conversion-events", headers=headers, params=params)

    def get_conversion_event(self, event_id, headers):
        return self._request("GET", f"/api/conversion-events/{event_id}", headers=headers)

    def list_conversion_events(self, headers, params=None):
        return self._request("GET", "/api/conversion-events", headers=headers, params=params)

    def start_event(self, plan_id, event_id, headers):
        return self._request("POST", f"/api/conversion-plans/{plan_id}/conversion-events/{event_id}/start", {}, headers)

    def complete_event(self, plan_id, event_id, headers):
        return self._request("POST", f"/api/conversion-plans/{plan_id}/conversion-events/{event_id}/complete", {}, headers)

    def cancel_event(self, plan_id, event_id, headers):
        return self._request("POST", f"/api/conversion-plans/{plan_id}/conversion-events/{event_id}/cancel", {}, headers)

    def unstart_event(self, plan_id, event_id, headers):
        return self._request("POST", f"/api/conversion-plans/{plan_id}/conversion-events/{event_id}/unstart", {}, headers)

    # --- service agreements & downtime ---
    def create_service_agreement(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/service-agreements", payload, headers)

    def list_service_agreements(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/service-agreements", headers=headers, params=params)

    def get_service_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/service-agreements/{agreement_id}", headers=headers)

    def activate_service_agreement(self, site_id, agreement_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/service-agreements/{agreement_id}/activate", {}, headers)

    def terminate_service_agreement(self, site_id, agreement_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/service-agreements/{agreement_id}/terminate", {}, headers)

    def create_downtime_report(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/downtime-reports", payload, headers)

    def list_downtime_reports(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/downtime-reports", headers=headers, params=params)

    # --- fueling events ---
    def create_fueling_event(self, station_id, payload, headers):
        return self._request("POST", f"/api/stations/{station_id}/fueling-events", payload, headers)

    def list_station_fueling_events(self, station_id, headers, params=None):
        return self._request("GET", f"/api/stations/{station_id}/fueling-events", headers=headers, params=params)

    def get_fueling_event(self, event_id, headers):
        return self._request("GET", f"/api/fueling-events/{event_id}", headers=headers)

    def list_event_line_items(self, event_id, headers, params=None):
        return self._request("GET", f"/api/fueling-events/{event_id}/line-items", headers=headers, params=params)

    # --- invoices & line items ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_site_invoices(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/invoices", headers=headers, params=params)

    def add_line_item(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/line-items", payload, headers)

    def list_line_items(self, invoice_id, headers, params=None):
        return self._request("GET", f"/api/invoices/{invoice_id}/line-items", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/pay", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/resolve", {}, headers)

    # --- availability report ---
    def get_availability_report(self, site_id, month, headers):
        return self._request("GET", f"/api/sites/{site_id}/availability-report", headers=headers, params={"month": month})

    # --- incentive claims ---
    def create_incentive_claim(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/incentive-claims", payload, headers)

    def list_incentive_claims(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/incentive-claims", headers=headers, params=params)

    def get_incentive_claim(self, claim_id, headers):
        return self._request("GET", f"/api/incentive-claims/{claim_id}", headers=headers)

    def submit_claim(self, site_id, claim_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/incentive-claims/{claim_id}/submit", {}, headers)

    def approve_claim(self, site_id, claim_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/incentive-claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, site_id, claim_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/incentive-claims/{claim_id}/reject", {}, headers)

    # --- training records ---
    def create_training_record(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/training-records", payload, headers)

    def list_training_records(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/api/training-records/{record_id}", headers=headers)


api_client = ApiClient()
