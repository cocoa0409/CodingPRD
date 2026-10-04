"""API client: one method per endpoint in the PRD's endpoint table.

All endpoints are mounted under /marketplace.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/marketplace/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Nurse ---
    def create_nurse(self, payload, headers):
        return self._request("POST", "/marketplace/nurses", payload, headers)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"/marketplace/nurses/{nurse_id}", headers=headers)

    def list_nurses(self, headers, params=None):
        return self._request("GET", "/marketplace/nurses", headers=headers, params=params)

    def submit_nurse(self, nurse_id, headers):
        return self._request("POST", f"/marketplace/nurses/{nurse_id}/submit", {}, headers)

    def deactivate_nurse(self, nurse_id, headers):
        return self._request("POST", f"/marketplace/nurses/{nurse_id}/deactivate", {}, headers)

    def reactivate_nurse(self, nurse_id, headers):
        return self._request("POST", f"/marketplace/nurses/{nurse_id}/reactivate", {}, headers)

    def withdraw_nurse(self, nurse_id, headers):
        return self._request("POST", f"/marketplace/nurses/{nurse_id}/withdraw", {}, headers)

    def list_nurse_license_verifications(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/nurses/{nurse_id}/license-verifications",
            headers=headers, params=params,
        )

    def list_nurse_certifications(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/nurses/{nurse_id}/certifications",
            headers=headers, params=params,
        )

    def list_nurse_applications(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/nurses/{nurse_id}/applications",
            headers=headers, params=params,
        )

    def list_nurse_matches(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/nurses/{nurse_id}/matches",
            headers=headers, params=params,
        )

    # --- LicenseVerification ---
    def create_license_verification(self, payload, headers):
        return self._request("POST", "/marketplace/license-verifications", payload, headers)

    def get_license_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/marketplace/license-verifications/{verification_id}", headers=headers,
        )

    def verify_license(self, verification_id, headers):
        return self._request(
            "POST", f"/marketplace/license-verifications/{verification_id}/verify", {}, headers,
        )

    def reject_license(self, verification_id, payload, headers):
        return self._request(
            "POST", f"/marketplace/license-verifications/{verification_id}/reject",
            payload, headers,
        )

    # --- Certification ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/marketplace/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/marketplace/certifications/{certification_id}", headers=headers,
        )

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/marketplace/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/marketplace/employers/{employer_id}", headers=headers)

    def list_employer_requisitions(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/employers/{employer_id}/requisitions",
            headers=headers, params=params,
        )

    def list_employer_invoices(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/employers/{employer_id}/invoices",
            headers=headers, params=params,
        )

    def suspend_employer(self, employer_id, headers):
        return self._request("POST", f"/marketplace/employers/{employer_id}/suspend", {}, headers)

    def reinstate_employer(self, employer_id, headers):
        return self._request("POST", f"/marketplace/employers/{employer_id}/reinstate", {}, headers)

    # --- Requisition ---
    def create_requisition(self, payload, headers):
        return self._request("POST", "/marketplace/requisitions", payload, headers)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/marketplace/requisitions/{requisition_id}", headers=headers)

    def pause_requisition(self, requisition_id, headers):
        return self._request("POST", f"/marketplace/requisitions/{requisition_id}/pause", {}, headers)

    def resume_requisition(self, requisition_id, headers):
        return self._request("POST", f"/marketplace/requisitions/{requisition_id}/resume", {}, headers)

    def close_requisition(self, requisition_id, headers):
        return self._request("POST", f"/marketplace/requisitions/{requisition_id}/close", {}, headers)

    def generate_matches(self, requisition_id, headers):
        return self._request(
            "POST", f"/marketplace/requisitions/{requisition_id}/generate-matches", {}, headers,
        )

    def list_requisition_matches(self, requisition_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/requisitions/{requisition_id}/matches",
            headers=headers, params=params,
        )

    def get_sla_report(self, requisition_id, headers):
        return self._request(
            "GET", f"/marketplace/requisitions/{requisition_id}/sla-report", headers=headers,
        )

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/marketplace/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/marketplace/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/marketplace/applications", headers=headers, params=params)

    def review_application(self, application_id, headers):
        return self._request("POST", f"/marketplace/applications/{application_id}/review", {}, headers)

    def counter_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/marketplace/applications/{application_id}/counter", payload, headers,
        )

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/marketplace/applications/{application_id}/decline", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/marketplace/applications/{application_id}/withdraw", {}, headers)

    def list_application_interviews(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/applications/{application_id}/interviews",
            headers=headers, params=params,
        )

    def list_application_offers(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/applications/{application_id}/offers",
            headers=headers, params=params,
        )

    def list_application_screenings(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/applications/{application_id}/screenings",
            headers=headers, params=params,
        )

    def list_application_documents(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/marketplace/applications/{application_id}/onboarding-documents",
            headers=headers, params=params,
        )

    # --- Interview ---
    def schedule_interview(self, application_id, payload, headers):
        return self._request(
            "POST", f"/marketplace/applications/{application_id}/interviews", payload, headers,
        )

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/marketplace/interviews/{interview_id}", headers=headers)

    def complete_interview(self, interview_id, headers):
        return self._request("POST", f"/marketplace/interviews/{interview_id}/complete", {}, headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/marketplace/interviews/{interview_id}/cancel", {}, headers)

    def no_show_interview(self, interview_id, headers):
        return self._request("POST", f"/marketplace/interviews/{interview_id}/no-show", {}, headers)

    # --- Offer ---
    def issue_offer(self, application_id, payload, headers):
        return self._request(
            "POST", f"/marketplace/applications/{application_id}/offers", payload, headers,
        )

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/marketplace/offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/marketplace/offers/{offer_id}/accept", {}, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/marketplace/offers/{offer_id}/decline", {}, headers)

    def rescind_offer(self, offer_id, headers):
        return self._request("POST", f"/marketplace/offers/{offer_id}/rescind", {}, headers)

    # --- Screening ---
    def create_screening(self, payload, headers):
        return self._request("POST", "/marketplace/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/marketplace/screenings/{screening_id}", headers=headers)

    def verify_credentials(self, screening_id, headers):
        return self._request(
            "POST", f"/marketplace/screenings/{screening_id}/verify-credentials", {}, headers,
        )

    def fail_credentials(self, screening_id, headers):
        return self._request(
            "POST", f"/marketplace/screenings/{screening_id}/fail-credentials", {}, headers,
        )

    def clear_background(self, screening_id, headers):
        return self._request(
            "POST", f"/marketplace/screenings/{screening_id}/clear-background", {}, headers,
        )

    def flag_background(self, screening_id, headers):
        return self._request(
            "POST", f"/marketplace/screenings/{screening_id}/flag-background", {}, headers,
        )

    # --- OnboardingDocument ---
    def create_document(self, payload, headers):
        return self._request("POST", "/marketplace/onboarding-documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request(
            "GET", f"/marketplace/onboarding-documents/{document_id}", headers=headers,
        )

    def approve_document(self, document_id, headers):
        return self._request(
            "POST", f"/marketplace/onboarding-documents/{document_id}/approve", {}, headers,
        )

    def reject_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"/marketplace/onboarding-documents/{document_id}/reject", payload, headers,
        )

    # --- Placement ---
    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/marketplace/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/marketplace/placements", headers=headers, params=params)

    def terminate_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/marketplace/placements/{placement_id}/terminate", {}, headers,
        )

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/marketplace/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/marketplace/invoices", headers=headers, params=params)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/marketplace/invoices/{invoice_id}/settle", {}, headers)


api_client = ApiClient()
