"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- PlasmaCenter ---
    def create_center(self, payload, headers):
        return self._request("POST", "/plasma-centers", payload, headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/plasma-centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request(
            "GET", f"/plasma-centers/{center_id}", headers=headers
        )

    def place_inspection_hold(self, center_id, payload, headers):
        return self._request(
            "POST", f"/plasma-centers/{center_id}/inspection-holds", payload, headers
        )

    def clear_inspection_hold(self, center_id, payload, headers):
        return self._request(
            "POST",
            f"/plasma-centers/{center_id}/inspection-holds/clear",
            payload,
            headers,
        )

    def decommission_center(self, center_id, payload, headers):
        return self._request(
            "POST", f"/plasma-centers/{center_id}/decommission", payload, headers
        )

    def list_capacity_snapshots(self, center_id, headers, params=None):
        return self._request(
            "GET",
            f"/plasma-centers/{center_id}/capacity-snapshots",
            headers=headers,
            params=params,
        )

    # --- CompensationSchedule ---
    def create_schedule(self, center_id, payload, headers):
        return self._request(
            "POST",
            f"/plasma-centers/{center_id}/compensation-schedules",
            payload,
            headers,
        )

    def list_schedules(self, center_id, headers, params=None):
        return self._request(
            "GET",
            f"/plasma-centers/{center_id}/compensation-schedules",
            headers=headers,
            params=params,
        )

    def get_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/compensation-schedules/{schedule_id}", headers=headers
        )

    def retire_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST",
            f"/compensation-schedules/{schedule_id}/retire",
            payload,
            headers,
        )

    # --- Donor ---
    def register_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    def file_deferral(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/donors/{donor_id}/deferrals", payload, headers
        )

    def list_deferrals(self, donor_id, headers, params=None):
        return self._request(
            "GET", f"/donors/{donor_id}/deferrals", headers=headers, params=params
        )

    def override_deferral(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"/deferral-registry-entries/{entry_id}/override",
            payload,
            headers,
        )

    # --- ScreeningVisit ---
    def schedule_screening(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/donors/{donor_id}/screening-visits", payload, headers
        )

    def list_screenings(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"/donors/{donor_id}/screening-visits",
            headers=headers,
            params=params,
        )

    def get_screening(self, visit_id, headers):
        return self._request(
            "GET", f"/screening-visits/{visit_id}", headers=headers
        )

    def record_sub_record(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/screening-visits/{visit_id}/sub-records", payload, headers
        )

    def list_sub_records(self, visit_id, headers, params=None):
        return self._request(
            "GET",
            f"/screening-visits/{visit_id}/sub-records",
            headers=headers,
            params=params,
        )

    def clear_screening(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/screening-visits/{visit_id}/clear", payload or {}, headers
        )

    # --- DonationVisit ---
    def schedule_donation(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/donors/{donor_id}/donation-visits", payload, headers
        )

    def list_donations(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"/donors/{donor_id}/donation-visits",
            headers=headers,
            params=params,
        )

    def get_donation(self, visit_id, headers):
        return self._request("GET", f"/donation-visits/{visit_id}", headers=headers)

    def check_in(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/donation-visits/{visit_id}/check-in", payload or {}, headers
        )

    def complete_collection(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"/donation-visits/{visit_id}/complete-collection",
            payload,
            headers,
        )

    def discharge(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/donation-visits/{visit_id}/discharge", payload or {}, headers
        )

    def record_adverse_reaction(self, visit_id, payload, headers):
        return self._request(
            "POST",
            f"/donation-visits/{visit_id}/adverse-reactions",
            payload,
            headers,
        )

    def list_adverse_reactions(self, visit_id, headers, params=None):
        return self._request(
            "GET",
            f"/donation-visits/{visit_id}/adverse-reactions",
            headers=headers,
            params=params,
        )

    # --- DonationUnit ---
    def list_units(self, headers, params=None):
        return self._request(
            "GET", "/donation-units", headers=headers, params=params
        )

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/donation-units/{unit_id}", headers=headers)

    def release_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"/donation-units/{unit_id}/release", payload or {}, headers
        )

    # --- LookBackCase ---
    def list_lookback_cases(self, headers, params=None):
        return self._request("GET", "/lookback-cases", headers=headers, params=params)

    def get_lookback_case(self, case_id, headers):
        return self._request("GET", f"/lookback-cases/{case_id}", headers=headers)

    def resolve_lookback_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/lookback-cases/{case_id}/resolve", payload, headers
        )

    # --- CompensationPayment (read-only) ---
    def get_payment_for_visit(self, visit_id, headers):
        return self._request(
            "GET",
            f"/donation-visits/{visit_id}/compensation-payment",
            headers=headers,
        )

    def list_payments_for_donor(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"/donors/{donor_id}/compensation-payments",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
