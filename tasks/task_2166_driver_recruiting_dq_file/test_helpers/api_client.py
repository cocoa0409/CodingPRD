"""API client: one method per endpoint defined in the PRD.

Every path below is absolute — the API exposes flat, top-level collections.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ─── Carrier ──────────────────────────────────────────────────────────────

    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def update_carrier(self, carrier_id, payload, headers):
        return self._request("PATCH", f"/carriers/{carrier_id}", payload, headers)

    # ─── DriverApplicant ──────────────────────────────────────────────────────

    def create_driver_applicant(self, payload, headers):
        return self._request("POST", "/driver-applicants", payload, headers)

    def get_driver_applicant(self, applicant_id, headers):
        return self._request(
            "GET", f"/driver-applicants/{applicant_id}", headers=headers
        )

    def list_driver_applicants(self, headers, params=None):
        return self._request("GET", "/driver-applicants", headers=headers, params=params)

    # ─── DriverApplication ────────────────────────────────────────────────────

    def create_driver_application(self, payload, headers):
        return self._request("POST", "/driver-applications", payload, headers)

    def get_driver_application(self, application_id, headers):
        return self._request(
            "GET", f"/driver-applications/{application_id}", headers=headers
        )

    def list_driver_applications(self, headers, params=None):
        return self._request(
            "GET", "/driver-applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/driver-applications/{application_id}/submit", {}, headers
        )

    def request_info(self, application_id, payload, headers):
        return self._request(
            "POST", f"/driver-applications/{application_id}/request-info", payload, headers
        )

    def resubmit_info(self, application_id, payload, headers):
        return self._request(
            "POST", f"/driver-applications/{application_id}/resubmit-info", payload, headers
        )

    def disqualify_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/driver-applications/{application_id}/disqualify", payload, headers
        )

    def reapply(self, application_id, payload, headers):
        return self._request(
            "POST", f"/driver-applications/{application_id}/reapply", payload, headers
        )

    def get_employment_coverage(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/driver-applications/{application_id}/employment-coverage",
            headers=headers,
            params=params,
        )

    # ─── EmploymentVerification ───────────────────────────────────────────────

    def create_employment_verification(self, payload, headers):
        return self._request("POST", "/employment-verifications", payload, headers)

    def get_employment_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/employment-verifications/{verification_id}", headers=headers
        )

    def list_employment_verifications(self, headers, params=None):
        return self._request(
            "GET", "/employment-verifications", headers=headers, params=params
        )

    def send_verification_request(self, verification_id, headers):
        return self._request(
            "POST", f"/employment-verifications/{verification_id}/send-request", {}, headers
        )

    def record_verification_response(self, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/employment-verifications/{verification_id}/record-response",
            payload,
            headers,
        )

    def mark_verification_no_response(self, verification_id, headers):
        return self._request(
            "POST",
            f"/employment-verifications/{verification_id}/mark-no-response",
            {},
            headers,
        )

    # ─── ScreeningCheck ───────────────────────────────────────────────────────

    def create_screening_check(self, payload, headers):
        return self._request("POST", "/screening-checks", payload, headers)

    def get_screening_check(self, screening_check_id, headers):
        return self._request(
            "GET", f"/screening-checks/{screening_check_id}", headers=headers
        )

    def list_screening_checks(self, headers, params=None):
        return self._request("GET", "/screening-checks", headers=headers, params=params)

    def record_screening_result(self, screening_check_id, payload, headers):
        return self._request(
            "POST", f"/screening-checks/{screening_check_id}/record-result", payload, headers
        )

    def adjudicate_screening_check(self, screening_check_id, payload, headers):
        return self._request(
            "POST", f"/screening-checks/{screening_check_id}/adjudicate", payload, headers
        )

    def dispute_screening_check(self, screening_check_id, payload, headers):
        return self._request(
            "POST", f"/screening-checks/{screening_check_id}/dispute", payload, headers
        )

    # ─── ClearinghouseQuery ───────────────────────────────────────────────────

    def create_clearinghouse_query(self, payload, headers):
        return self._request("POST", "/clearinghouse-queries", payload, headers)

    def get_clearinghouse_query(self, clearinghouse_query_id, headers):
        return self._request(
            "GET", f"/clearinghouse-queries/{clearinghouse_query_id}", headers=headers
        )

    def list_clearinghouse_queries(self, headers, params=None):
        return self._request(
            "GET", "/clearinghouse-queries", headers=headers, params=params
        )

    def consent_decision(self, clearinghouse_query_id, payload, headers):
        return self._request(
            "POST",
            f"/clearinghouse-queries/{clearinghouse_query_id}/consent-decision",
            payload,
            headers,
        )

    def record_clearinghouse_result(self, clearinghouse_query_id, payload, headers):
        return self._request(
            "POST",
            f"/clearinghouse-queries/{clearinghouse_query_id}/record-result",
            payload,
            headers,
        )

    # ─── DrugTestOrder ────────────────────────────────────────────────────────

    def create_drug_test_order(self, payload, headers):
        return self._request("POST", "/drug-test-orders", payload, headers)

    def get_drug_test_order(self, drug_test_order_id, headers):
        return self._request(
            "GET", f"/drug-test-orders/{drug_test_order_id}", headers=headers
        )

    def list_drug_test_orders(self, headers, params=None):
        return self._request("GET", "/drug-test-orders", headers=headers, params=params)

    def record_collection(self, drug_test_order_id, payload, headers):
        return self._request(
            "POST", f"/drug-test-orders/{drug_test_order_id}/record-collection", payload, headers
        )

    def record_lab_result(self, drug_test_order_id, payload, headers):
        return self._request(
            "POST", f"/drug-test-orders/{drug_test_order_id}/record-lab-result", payload, headers
        )

    def record_mro_verification(self, drug_test_order_id, payload, headers):
        return self._request(
            "POST",
            f"/drug-test-orders/{drug_test_order_id}/record-mro-verification",
            payload,
            headers,
        )

    # ─── RoadTest ─────────────────────────────────────────────────────────────

    def create_road_test(self, payload, headers):
        return self._request("POST", "/road-tests", payload, headers)

    def get_road_test(self, road_test_id, headers):
        return self._request("GET", f"/road-tests/{road_test_id}", headers=headers)

    def list_road_tests(self, headers, params=None):
        return self._request("GET", "/road-tests", headers=headers, params=params)

    def record_road_test_result(self, road_test_id, payload, headers):
        return self._request(
            "POST", f"/road-tests/{road_test_id}/record-result", payload, headers
        )

    def reschedule_road_test(self, road_test_id, payload, headers):
        return self._request(
            "POST", f"/road-tests/{road_test_id}/reschedule", payload, headers
        )

    # ─── OrientationSession / OrientationEnrollment ───────────────────────────

    def create_orientation_session(self, payload, headers):
        return self._request("POST", "/orientation-sessions", payload, headers)

    def get_orientation_session(self, session_id, headers):
        return self._request(
            "GET", f"/orientation-sessions/{session_id}", headers=headers
        )

    def list_orientation_sessions(self, headers, params=None):
        return self._request(
            "GET", "/orientation-sessions", headers=headers, params=params
        )

    def open_orientation_session(self, session_id, headers):
        return self._request(
            "POST", f"/orientation-sessions/{session_id}/open", {}, headers
        )

    def complete_orientation_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/orientation-sessions/{session_id}/complete", payload, headers
        )

    def create_orientation_enrollment(self, payload, headers):
        return self._request("POST", "/orientation-enrollments", payload, headers)

    def get_orientation_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/orientation-enrollments/{enrollment_id}", headers=headers
        )

    def list_orientation_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/orientation-enrollments", headers=headers, params=params
        )

    def cancel_orientation_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/orientation-enrollments/{enrollment_id}/cancel", payload, headers
        )

    # ─── DqFile / DqDocument ──────────────────────────────────────────────────

    def get_dq_file(self, dq_file_id, headers):
        return self._request("GET", f"/dq-files/{dq_file_id}", headers=headers)

    def list_dq_files(self, headers, params=None):
        return self._request("GET", "/dq-files", headers=headers, params=params)

    def get_dq_file_completeness(self, dq_file_id, headers, params=None):
        return self._request(
            "GET", f"/dq-files/{dq_file_id}/completeness", headers=headers, params=params
        )

    def annual_review(self, dq_file_id, payload, headers):
        return self._request(
            "POST", f"/dq-files/{dq_file_id}/annual-review", payload, headers
        )

    def revoke_certification(self, dq_file_id, payload, headers):
        return self._request(
            "POST", f"/dq-files/{dq_file_id}/revoke-certification", payload, headers
        )

    def get_dq_document(self, document_id, headers):
        return self._request("GET", f"/dq-documents/{document_id}", headers=headers)

    def list_dq_documents(self, headers, params=None):
        return self._request("GET", "/dq-documents", headers=headers, params=params)

    def update_dq_document(self, document_id, payload, headers):
        return self._request("PUT", f"/dq-documents/{document_id}", payload, headers)

    # ─── TuitionAgreement ─────────────────────────────────────────────────────

    def create_tuition_agreement(self, payload, headers):
        return self._request("POST", "/tuition-agreements", payload, headers)

    def get_tuition_agreement(self, tuition_agreement_id, headers):
        return self._request(
            "GET", f"/tuition-agreements/{tuition_agreement_id}", headers=headers
        )

    def list_tuition_agreements(self, headers, params=None):
        return self._request("GET", "/tuition-agreements", headers=headers, params=params)

    def activate_tuition_agreement(self, tuition_agreement_id, headers):
        return self._request(
            "POST", f"/tuition-agreements/{tuition_agreement_id}/activate", {}, headers
        )

    def accrue_month(self, tuition_agreement_id, payload, headers):
        return self._request(
            "POST", f"/tuition-agreements/{tuition_agreement_id}/accrue-month", payload, headers
        )

    def reverse_clawback(self, tuition_agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/tuition-agreements/{tuition_agreement_id}/reverse-clawback",
            payload,
            headers,
        )

    # ─── HireRecord ───────────────────────────────────────────────────────────

    def create_hire_record(self, payload, headers):
        return self._request("POST", "/hire-records", payload, headers)

    def get_hire_record(self, hire_record_id, headers):
        return self._request("GET", f"/hire-records/{hire_record_id}", headers=headers)

    def list_hire_records(self, headers, params=None):
        return self._request("GET", "/hire-records", headers=headers, params=params)

    def terminate_hire_record(self, hire_record_id, payload, headers):
        return self._request(
            "POST", f"/hire-records/{hire_record_id}/terminate", payload, headers
        )

    def rescind_hire_record(self, hire_record_id, payload, headers):
        return self._request(
            "POST", f"/hire-records/{hire_record_id}/rescind", payload, headers
        )


api_client = ApiClient()
