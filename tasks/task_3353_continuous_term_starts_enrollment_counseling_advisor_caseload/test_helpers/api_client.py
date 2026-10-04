"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- terms ---
    def create_term(self, payload, headers):
        return self._request("POST", "/api/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/api/terms/{term_id}", headers=headers)

    def advance_term(self, term_id, to_state, headers):
        return self._request(
            "POST", f"/api/terms/{term_id}/advance",
            {"to_state": to_state}, headers,
        )

    def list_sections_of_term(self, term_id, headers, params=None):
        return self._request(
            "GET", f"/api/terms/{term_id}/sections", headers=headers, params=params
        )

    def create_section(self, term_id, payload, headers):
        return self._request(
            "POST", f"/api/terms/{term_id}/sections", payload, headers
        )

    # --- programs & state authorizations ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def list_state_authorizations(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/api/programs/{program_id}/state-authorizations",
            headers=headers, params=params,
        )

    def create_state_authorization(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/programs/{program_id}/state-authorizations",
            payload, headers,
        )

    # --- staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/api/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/api/staff/{staff_id}", headers=headers)

    def list_staff_applicants(self, staff_id, headers, params=None):
        return self._request(
            "GET", f"/api/staff/{staff_id}/applicants",
            headers=headers, params=params,
        )

    # --- applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/api/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request(
            "GET", f"/api/applicants/{applicant_id}", headers=headers
        )

    def create_contact_attempt(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"/api/applicants/{applicant_id}/contact-attempts",
            payload, headers,
        )

    # --- applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/api/applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/api/applications/{application_id}", headers=headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/decision",
            payload, headers,
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/withdraw",
            {}, headers,
        )

    # --- transfer credit evaluations ---
    def list_tces(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/applications/{application_id}/transfer-credit-evaluations",
            headers=headers, params=params,
        )

    def create_tce(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/api/applications/{application_id}/transfer-credit-evaluations",
            payload, headers,
        )

    def advance_tce(self, tce_id, to_state, headers):
        return self._request(
            "POST", f"/api/transfer-credit-evaluations/{tce_id}/advance",
            {"to_state": to_state}, headers,
        )

    # --- enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/api/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/api/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/api/enrollments/{enrollment_id}", headers=headers
        )

    def withdraw_enrollment(self, enrollment_id, headers, withdrawal_date=None):
        payload = {}
        if withdrawal_date is not None:
            payload["withdrawal_date"] = withdrawal_date
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/withdraw",
            payload, headers,
        )

    def defer_enrollment(self, enrollment_id, to_state, headers):
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/defer",
            {"to_state": to_state}, headers,
        )

    # --- sections ---
    def advance_section(self, section_id, to_state, headers, adjunct_hires=None):
        payload = {"to_state": to_state}
        if adjunct_hires is not None:
            payload["adjunct_hires"] = adjunct_hires
        return self._request(
            "POST", f"/api/sections/{section_id}/advance", payload, headers
        )

    def add_to_roster(self, section_id, enrollment_id, headers):
        return self._request(
            "POST", f"/api/sections/{section_id}/roster",
            {"enrollment_id": enrollment_id}, headers,
        )

    # --- financial aid ---
    def create_aid_package(self, enrollment_id, efc_cents, headers):
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/financial-aid-packages",
            {"efc_cents": efc_cents}, headers,
        )

    def certify_aid_package(self, package_id, expected_enrollment_version, headers):
        return self._request(
            "POST", f"/api/financial-aid-packages/{package_id}/certify",
            {"expected_enrollment_version": expected_enrollment_version},
            headers,
        )

    def list_aid_packages(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/enrollments/{enrollment_id}/financial-aid-packages",
            headers=headers, params=params,
        )

    # --- early alerts ---
    def list_early_alerts(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/api/enrollments/{enrollment_id}/early-alerts",
            headers=headers, params=params,
        )

    def create_early_alert(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/early-alerts",
            payload, headers,
        )

    def advance_early_alert(self, alert_id, to_state, headers):
        return self._request(
            "POST", f"/api/early-alerts/{alert_id}/advance",
            {"to_state": to_state}, headers,
        )

    # --- retention outreach ---
    def create_retention_outreach(self, enrollment_id, target_term_id, headers):
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/retention-outreaches",
            {"target_term_id": target_term_id}, headers,
        )

    def list_retention_outreaches(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/api/enrollments/{enrollment_id}/retention-outreaches",
            headers=headers, params=params,
        )

    def advance_retention_outreach(self, outreach_id, to_state, headers):
        return self._request(
            "POST", f"/api/retention-outreaches/{outreach_id}/advance",
            {"to_state": to_state}, headers,
        )


api_client = ApiClient()
