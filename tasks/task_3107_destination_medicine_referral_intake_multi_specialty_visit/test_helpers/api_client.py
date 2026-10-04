"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # per-test-server isolation restarts the server before every test;
        # forcing Connection: close prevents the session-scoped client from
        # reusing a stale keep-alive connection to the previous server process.
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        return super()._request(method, path, payload, hdrs, params)

    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Specialty services ---
    def create_specialty_service(self, payload, headers):
        return self._request("POST", "/specialty-services", payload, headers)

    def list_specialty_services(self, headers, params=None):
        return self._request("GET", "/specialty-services", headers=headers, params=params)

    def get_specialty_service(self, service_id, headers):
        return self._request("GET", f"/specialty-services/{service_id}", headers=headers)

    # --- Slots ---
    def create_slot(self, service_id, payload, headers):
        return self._request(
            "POST", f"/specialty-services/{service_id}/slots", payload, headers
        )

    def list_service_slots(self, service_id, headers, params=None):
        return self._request(
            "GET", f"/specialty-services/{service_id}/slots", headers=headers, params=params
        )

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/slots/{slot_id}", headers=headers)

    def confirm_slot(self, slot_id, headers):
        return self._request("POST", f"/slots/{slot_id}/confirm", {}, headers)

    def release_slot(self, slot_id, headers):
        return self._request("POST", f"/slots/{slot_id}/release", {}, headers)

    # --- Referrals / patients / records ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def get_referral_patient(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}/patient", headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def create_medical_record(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/medical-records", payload, headers
        )

    def list_medical_records(self, referral_id, headers, params=None):
        return self._request(
            "GET", f"/referrals/{referral_id}/medical-records", headers=headers, params=params
        )

    def get_medical_record(self, record_id, headers):
        return self._request("GET", f"/medical-records/{record_id}", headers=headers)

    def verify_medical_record(self, referral_id, record_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/medical-records/{record_id}/verify",
            {}, headers,
        )

    def reject_medical_record(self, referral_id, record_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/medical-records/{record_id}/reject",
            {}, headers,
        )

    def submit_review(self, referral_id, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/submit-review", {}, headers
        )

    # --- Visit cases ---
    def create_visit_case(self, payload, headers):
        return self._request("POST", "/visit-cases", payload, headers)

    def list_visit_cases(self, headers, params=None):
        return self._request("GET", "/visit-cases", headers=headers, params=params)

    def get_visit_case(self, case_id, headers):
        return self._request("GET", f"/visit-cases/{case_id}", headers=headers)

    def create_case_review(self, case_id, payload, headers):
        return self._request("POST", f"/visit-cases/{case_id}/reviews", payload, headers)

    def list_case_reviews(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/visit-cases/{case_id}/reviews", headers=headers, params=params
        )

    def get_case_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/visit-cases/{case_id}/withdraw", {}, headers)

    def authorize_travel(self, case_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/authorize-travel", {}, headers
        )

    # --- Financial clearance ---
    def get_case_financial_clearance(self, case_id, headers):
        return self._request(
            "GET", f"/visit-cases/{case_id}/financial-clearance", headers=headers
        )

    def waive_clearance(self, case_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/financial-clearance/waive", {}, headers
        )

    def reopen_clearance(self, case_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/financial-clearance/reopen", {}, headers
        )

    def forfeit_clearance(self, case_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/financial-clearance/forfeit", {}, headers
        )

    def get_financial_clearance(self, clearance_id, headers):
        return self._request(
            "GET", f"/financial-clearances/{clearance_id}", headers=headers
        )

    # --- Estimate letters ---
    def create_estimate_letter(self, case_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/estimate-letters", {}, headers
        )

    def list_estimate_letters(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/visit-cases/{case_id}/estimate-letters", headers=headers, params=params
        )

    def get_estimate_letter(self, letter_id, headers):
        return self._request("GET", f"/estimate-letters/{letter_id}", headers=headers)

    # --- Billing transactions ---
    def create_billing_transaction(self, case_id, payload, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/billing-transactions", payload, headers
        )

    def list_billing_transactions(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/visit-cases/{case_id}/billing-transactions",
            headers=headers, params=params,
        )

    def get_billing_transaction(self, txn_id, headers):
        return self._request("GET", f"/billing-transactions/{txn_id}", headers=headers)

    def list_all_billing_transactions(self, headers, params=None):
        return self._request(
            "GET", "/billing-transactions", headers=headers, params=params
        )

    # --- Itinerary / holds / visits ---
    def get_case_itinerary(self, case_id, headers):
        return self._request("GET", f"/visit-cases/{case_id}/itinerary", headers=headers)

    def get_itinerary(self, itinerary_id, headers):
        return self._request("GET", f"/itineraries/{itinerary_id}", headers=headers)

    def create_slot_hold(self, case_id, payload, headers):
        return self._request("POST", f"/visit-cases/{case_id}/slot-holds", payload, headers)

    def confirm_itinerary(self, itinerary_id, headers):
        return self._request("POST", f"/itineraries/{itinerary_id}/confirm", {}, headers)

    def lock_itinerary(self, itinerary_id, headers):
        return self._request("POST", f"/itineraries/{itinerary_id}/lock", {}, headers)

    def list_itinerary_visits(self, itinerary_id, headers, params=None):
        return self._request(
            "GET", f"/itineraries/{itinerary_id}/visits", headers=headers, params=params
        )

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def mark_visit_no_show(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/mark-no-show", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    # --- Logistics ---
    def create_logistics(self, case_id, payload, headers):
        return self._request("POST", f"/visit-cases/{case_id}/logistics", payload, headers)

    def list_logistics(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/visit-cases/{case_id}/logistics", headers=headers, params=params
        )

    def get_logistics(self, arrangement_id, headers):
        return self._request(
            "GET", f"/logistics-arrangements/{arrangement_id}", headers=headers
        )

    def confirm_logistics(self, case_id, arrangement_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/logistics/{arrangement_id}/confirm",
            {}, headers,
        )

    def cancel_logistics(self, case_id, arrangement_id, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/logistics/{arrangement_id}/cancel",
            {}, headers,
        )

    # --- Communications ---
    def create_communication(self, case_id, payload, headers):
        return self._request(
            "POST", f"/visit-cases/{case_id}/communications", payload, headers
        )

    def list_communications(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/visit-cases/{case_id}/communications", headers=headers, params=params
        )

    def get_communication(self, comm_id, headers):
        return self._request("GET", f"/communications/{comm_id}", headers=headers)


api_client = ApiClient()
