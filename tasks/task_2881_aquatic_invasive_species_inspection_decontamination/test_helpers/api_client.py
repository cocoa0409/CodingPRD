"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- WaterBody -------------------------------------------------------
    def create_water_body(self, payload, headers):
        return self._request("POST", "/water-bodies", payload, headers)

    def get_water_body(self, water_body_id, headers):
        return self._request("GET", f"/water-bodies/{water_body_id}", headers=headers)

    def list_water_bodies(self, headers, params=None):
        return self._request("GET", "/water-bodies", headers=headers, params=params)

    def patch_water_body(self, water_body_id, payload, headers):
        return self._request("PATCH", f"/water-bodies/{water_body_id}", payload, headers)

    # --- InspectionStation ----------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/inspection-stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/inspection-stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/inspection-stations", headers=headers, params=params)

    def set_station_status(self, station_id, payload, headers):
        return self._request(
            "POST", f"/inspection-stations/{station_id}/status", payload, headers
        )

    def create_station_hours(self, station_id, payload, headers):
        return self._request(
            "POST", f"/inspection-stations/{station_id}/hours", payload, headers
        )

    def list_station_hours(self, station_id, headers, params=None):
        return self._request(
            "GET", f"/inspection-stations/{station_id}/hours", headers=headers, params=params
        )

    # --- Inspector -------------------------------------------------------
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def set_inspector_status(self, inspector_id, payload, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/status", payload, headers)

    def create_training_record(self, inspector_id, payload, headers):
        return self._request(
            "POST", f"/inspectors/{inspector_id}/training-records", payload, headers
        )

    def list_training_records(self, inspector_id, headers, params=None):
        return self._request(
            "GET", f"/inspectors/{inspector_id}/training-records",
            headers=headers, params=params,
        )

    # --- Watercraft ------------------------------------------------------
    def create_watercraft(self, payload, headers):
        return self._request("POST", "/watercraft", payload, headers)

    def get_watercraft(self, watercraft_id, headers):
        return self._request("GET", f"/watercraft/{watercraft_id}", headers=headers)

    def list_watercraft(self, headers, params=None):
        return self._request("GET", "/watercraft", headers=headers, params=params)

    # --- ReciprocityAgreement -------------------------------------------
    def create_reciprocity_agreement(self, payload, headers):
        return self._request("POST", "/reciprocity-agreements", payload, headers)

    def get_reciprocity_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/reciprocity-agreements/{agreement_id}", headers=headers
        )

    def list_reciprocity_agreements(self, headers, params=None):
        return self._request(
            "GET", "/reciprocity-agreements", headers=headers, params=params
        )

    def set_reciprocity_agreement_status(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/reciprocity-agreements/{agreement_id}/status", payload, headers
        )

    # --- InspectionRecord ------------------------------------------------
    def create_inspection_record(self, payload, headers):
        return self._request("POST", "/inspection-records", payload, headers)

    def get_inspection_record(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}", headers=headers)

    def list_inspection_records(self, headers, params=None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    def screen_inspection_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/inspection-records/{record_id}/screening", payload, headers
        )

    def dispose_inspection_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/inspection-records/{record_id}/disposition", payload, headers
        )

    def enforce_inspection_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/inspection-records/{record_id}/enforcement", payload, headers
        )

    # --- DeconOrder ------------------------------------------------------
    def create_decon_order(self, payload, headers):
        return self._request("POST", "/decon-orders", payload, headers)

    def get_decon_order(self, order_id, headers):
        return self._request("GET", f"/decon-orders/{order_id}", headers=headers)

    def list_decon_orders(self, headers, params=None):
        return self._request("GET", "/decon-orders", headers=headers, params=params)

    def treat_decon_order(self, order_id, payload, headers):
        return self._request("POST", f"/decon-orders/{order_id}/treatment", payload, headers)

    def verify_decon_dry_time(self, order_id, payload, headers):
        return self._request(
            "POST", f"/decon-orders/{order_id}/dry-verification", payload, headers
        )

    # --- QuarantineOrder -------------------------------------------------
    def create_quarantine_order(self, payload, headers):
        return self._request("POST", "/quarantine-orders", payload, headers)

    def get_quarantine_order(self, order_id, headers):
        return self._request("GET", f"/quarantine-orders/{order_id}", headers=headers)

    def list_quarantine_orders(self, headers, params=None):
        return self._request("GET", "/quarantine-orders", headers=headers, params=params)

    def request_quarantine_release(self, order_id, payload, headers):
        return self._request(
            "POST", f"/quarantine-orders/{order_id}/release-request", payload, headers
        )

    def decide_quarantine_release(self, order_id, payload, headers):
        return self._request(
            "POST", f"/quarantine-orders/{order_id}/release", payload, headers
        )

    def report_quarantine_breach(self, order_id, payload, headers):
        return self._request(
            "POST", f"/quarantine-orders/{order_id}/breach-report", payload, headers
        )

    # --- DetectionReport -------------------------------------------------
    def create_detection_report(self, payload, headers):
        return self._request("POST", "/detection-reports", payload, headers)

    def get_detection_report(self, report_id, headers):
        return self._request("GET", f"/detection-reports/{report_id}", headers=headers)

    def list_detection_reports(self, headers, params=None):
        return self._request("GET", "/detection-reports", headers=headers, params=params)

    def submit_detection_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/detection-reports/{report_id}/submission", payload, headers
        )

    def acknowledge_detection_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/detection-reports/{report_id}/state-acknowledgement", payload, headers
        )

    # --- EducationCampaign -----------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/education-campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/education-campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/education-campaigns", headers=headers, params=params)

    def set_campaign_status(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/education-campaigns/{campaign_id}/status", payload, headers
        )

    def evaluate_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/education-campaigns/{campaign_id}/evaluation", payload, headers
        )

    # --- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
