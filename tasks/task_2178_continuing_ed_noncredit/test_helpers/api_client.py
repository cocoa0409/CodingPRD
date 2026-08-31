"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Catalog --------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def retire_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/retire", {}, headers)

    # ---- Offerings ------------------------------------------------------
    def create_offering(self, payload, headers):
        return self._request("POST", "/offerings", payload, headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def open_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/open", {}, headers)

    def census_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/census", {}, headers)

    def complete_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/complete", {}, headers)

    def create_registration(self, offering_id, payload, headers):
        return self._request(
            "POST", f"/offerings/{offering_id}/registrations", payload, headers
        )

    # ---- Learners & marketing ------------------------------------------
    def create_learner(self, payload, headers):
        return self._request("POST", "/learners", payload, headers)

    def get_learner(self, learner_id, headers):
        return self._request("GET", f"/learners/{learner_id}", headers=headers)

    def list_marketing_memberships(self, learner_id, headers, params=None):
        return self._request(
            "GET", f"/learners/{learner_id}/marketing-memberships",
            headers=headers, params=params,
        )

    def set_marketing_preference(self, learner_id, payload, headers):
        return self._request(
            "POST", f"/learners/{learner_id}/marketing-preference", payload, headers
        )

    # ---- Instructors ----------------------------------------------------
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ---- Corporate sponsorship -----------------------------------------
    def create_corporate_account(self, payload, headers):
        return self._request("POST", "/corporate-accounts", payload, headers)

    def get_corporate_account(self, account_id, headers):
        return self._request(
            "GET", f"/corporate-accounts/{account_id}", headers=headers
        )

    def suspend_corporate_account(self, account_id, headers):
        return self._request(
            "POST", f"/corporate-accounts/{account_id}/suspend", {}, headers
        )

    def reinstate_corporate_account(self, account_id, headers):
        return self._request(
            "POST", f"/corporate-accounts/{account_id}/reinstate", {}, headers
        )

    def create_deposit(self, account_id, payload, headers):
        return self._request(
            "POST", f"/corporate-accounts/{account_id}/deposits", payload, headers
        )

    def issue_voucher(self, account_id, payload, headers):
        return self._request(
            "POST", f"/corporate-accounts/{account_id}/vouchers", payload, headers
        )

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def assign_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/assign", payload, headers)

    def void_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/void", {}, headers)

    # ---- Registrations --------------------------------------------------
    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def pay_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/pay", payload, headers
        )

    def record_attendance(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/attendance", payload, headers
        )

    def award_completion(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/complete", {}, headers
        )

    # ---- Instructor contracting ----------------------------------------
    def create_instructor_contract(self, payload, headers):
        return self._request("POST", "/instructor-contracts", payload, headers)

    def list_instructor_contracts(self, headers, params=None):
        return self._request(
            "GET", "/instructor-contracts", headers=headers, params=params
        )

    def get_instructor_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/instructor-contracts/{contract_id}", headers=headers
        )

    def sign_instructor_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/instructor-contracts/{contract_id}/sign", payload, headers
        )

    def activate_instructor_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/instructor-contracts/{contract_id}/activate", {}, headers
        )

    def settle_instructor_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/instructor-contracts/{contract_id}/settle", {}, headers
        )

    # ---- Completion records ---------------------------------------------
    def list_completion_records(self, headers, params=None):
        return self._request(
            "GET", "/completion-records", headers=headers, params=params
        )

    def get_completion_record(self, record_id, headers):
        return self._request(
            "GET", f"/completion-records/{record_id}", headers=headers
        )

    def list_citations_for_record(self, record_id, headers, params=None):
        return self._request(
            "GET", f"/completion-records/{record_id}/citations",
            headers=headers, params=params,
        )

    def revoke_completion_record(self, record_id, headers):
        return self._request(
            "POST", f"/completion-records/{record_id}/revoke", {}, headers
        )

    # ---- Refund / transfer ----------------------------------------------
    def create_refund_transfer_request(self, payload, headers):
        return self._request("POST", "/refund-transfer-requests", payload, headers)

    def list_refund_transfer_requests(self, headers, params=None):
        return self._request(
            "GET", "/refund-transfer-requests", headers=headers, params=params
        )

    def get_refund_transfer_request(self, request_id, headers):
        return self._request(
            "GET", f"/refund-transfer-requests/{request_id}", headers=headers
        )

    def decide_refund_transfer_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/refund-transfer-requests/{request_id}/decide", payload, headers
        )

    def settle_refund_transfer_request(self, request_id, headers):
        return self._request(
            "POST", f"/refund-transfer-requests/{request_id}/settle", {}, headers
        )

    # ---- Credit for prior learning --------------------------------------
    def create_petition(self, payload, headers):
        return self._request("POST", "/cpl-petitions", payload, headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/cpl-petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/cpl-petitions/{petition_id}", headers=headers)

    def list_petition_citations(self, petition_id, headers, params=None):
        return self._request(
            "GET", f"/cpl-petitions/{petition_id}/citations",
            headers=headers, params=params,
        )

    def create_citation(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/cpl-petitions/{petition_id}/citations", payload, headers
        )

    def submit_petition(self, petition_id, headers):
        return self._request(
            "POST", f"/cpl-petitions/{petition_id}/submit", {}, headers
        )

    def review_petition(self, petition_id, headers):
        return self._request(
            "POST", f"/cpl-petitions/{petition_id}/review", {}, headers
        )

    def request_petition_revision(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/cpl-petitions/{petition_id}/request-revision", payload, headers
        )

    def decide_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/cpl-petitions/{petition_id}/decide", payload, headers
        )

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
