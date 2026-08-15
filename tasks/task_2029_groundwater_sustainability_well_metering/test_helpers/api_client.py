"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- WaterUserAccount ---
    def create_account(self, payload, headers):
        return self._request("POST", "/water-user-accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/water-user-accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/water-user-accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/water-user-accounts/{account_id}", payload, headers)

    # --- Well ---
    def create_well(self, payload, headers):
        return self._request("POST", "/wells", payload, headers)

    def list_wells(self, headers, params=None):
        return self._request("GET", "/wells", headers=headers, params=params)

    def get_well(self, well_id, headers):
        return self._request("GET", f"/wells/{well_id}", headers=headers)

    def install_meter(self, well_id, payload, headers):
        return self._request("POST", f"/wells/{well_id}/install-meter", payload, headers)

    def activate_well(self, well_id, headers):
        return self._request("POST", f"/wells/{well_id}/activate", headers=headers)

    def decommission_well(self, well_id, headers):
        return self._request("POST", f"/wells/{well_id}/decommission", headers=headers)

    # --- ExtractionReport ---
    def create_extraction_report(self, payload, headers):
        return self._request("POST", "/extraction-reports", payload, headers)

    def list_extraction_reports(self, headers, params=None):
        return self._request("GET", "/extraction-reports", headers=headers, params=params)

    def get_extraction_report(self, report_id, headers):
        return self._request("GET", f"/extraction-reports/{report_id}", headers=headers)

    def verify_report(self, report_id, headers):
        return self._request("POST", f"/extraction-reports/{report_id}/verify", headers=headers)

    def dispute_report(self, report_id, headers):
        return self._request("POST", f"/extraction-reports/{report_id}/dispute", headers=headers)

    def resubmit_report(self, report_id, payload, headers):
        return self._request("POST", f"/extraction-reports/{report_id}/resubmit", payload, headers)

    # --- TransferOrder ---
    def create_transfer_order(self, payload, headers):
        return self._request("POST", "/transfer-orders", payload, headers)

    def list_transfer_orders(self, headers, params=None):
        return self._request("GET", "/transfer-orders", headers=headers, params=params)

    def get_transfer_order(self, transfer_id, headers):
        return self._request("GET", f"/transfer-orders/{transfer_id}", headers=headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_id}/accept", headers=headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_id}/cancel", headers=headers)

    def settle_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_id}/settle", headers=headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-orders/{transfer_id}/reject", headers=headers)

    # --- MonitoringReading ---
    def create_monitoring_reading(self, payload, headers):
        return self._request("POST", "/monitoring-readings", payload, headers)

    def list_well_monitoring_readings(self, well_id, headers, params=None):
        return self._request("GET", f"/wells/{well_id}/monitoring-readings", headers=headers, params=params)

    # --- BasinConditionSnapshot ---
    def create_basin_snapshot(self, headers):
        return self._request("POST", "/basin-condition-snapshots", headers=headers)

    def list_basin_snapshots(self, headers, params=None):
        return self._request("GET", "/basin-condition-snapshots", headers=headers, params=params)

    def publish_basin_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/basin-condition-snapshots/{snapshot_id}/publish", headers=headers)

    # --- PenaltyAssessment ---
    def create_penalty_assessment(self, payload, headers):
        return self._request("POST", "/penalty-assessments", payload, headers)

    def list_penalty_assessments(self, headers, params=None):
        return self._request("GET", "/penalty-assessments", headers=headers, params=params)

    def get_penalty_assessment(self, assessment_id, headers):
        return self._request("GET", f"/penalty-assessments/{assessment_id}", headers=headers)

    def pay_assessment(self, assessment_id, headers):
        return self._request("POST", f"/penalty-assessments/{assessment_id}/pay", headers=headers)

    def appeal_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/penalty-assessments/{assessment_id}/appeal", payload, headers)

    def decide_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/penalty-assessments/{assessment_id}/decide", payload, headers)

    # --- AnnualStateReport ---
    def create_annual_state_report(self, payload, headers):
        return self._request("POST", "/annual-state-reports", payload, headers)

    def list_annual_state_reports(self, headers, params=None):
        return self._request("GET", "/annual-state-reports", headers=headers, params=params)

    def submit_annual_state_report(self, report_id, headers):
        return self._request("POST", f"/annual-state-reports/{report_id}/submit", headers=headers)

    def acknowledge_annual_state_report(self, report_id, headers):
        return self._request("POST", f"/annual-state-reports/{report_id}/acknowledge", headers=headers)

    # --- Admin / test-driving ---
    def close_water_year(self, payload, headers):
        return self._request("POST", "/admin/close-water-year", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
