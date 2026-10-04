"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/private-student-loans"


class ApiClient(GenericApiClient):
    """Typed endpoint methods over the private-student-loan surface."""

    # --- reference data ----------------------------------------------------
    def create_borrower(self, payload, headers):
        return self._request("POST", f"{BASE}/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"{BASE}/borrowers/{borrower_id}", headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", f"{BASE}/borrowers", headers=headers, params=params)

    def create_cosigner(self, borrower_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/borrowers/{borrower_id}/cosigners", payload, headers
        )

    def reunderwrite_cosigner(self, cosigner_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/cosigners/{cosigner_id}/reunderwrite", payload, headers
        )

    def get_cosigner(self, cosigner_id, headers):
        return self._request("GET", f"{BASE}/cosigners/{cosigner_id}", headers=headers)

    def list_cosigners(self, headers, params=None):
        return self._request("GET", f"{BASE}/cosigners", headers=headers, params=params)

    def create_school(self, payload, headers):
        return self._request("POST", f"{BASE}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{BASE}/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", f"{BASE}/schools", headers=headers, params=params)

    def create_policy(self, payload, headers):
        return self._request("POST", f"{BASE}/loan-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{BASE}/loan-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{BASE}/loan-policies", headers=headers, params=params)

    # --- applications ------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{BASE}/loan-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{BASE}/loan-applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/loan-applications", headers=headers, params=params
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loan-applications/{application_id}/decision", payload, headers
        )

    def reconsider_application(self, application_id, headers):
        return self._request(
            "POST", f"{BASE}/loan-applications/{application_id}/reconsider", None, headers
        )

    def cancel_application(self, application_id, headers):
        return self._request(
            "POST", f"{BASE}/loan-applications/{application_id}/cancel", None, headers
        )

    def create_certification_request(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/loan-applications/{application_id}/school-certifications",
            payload,
            headers,
        )

    def list_application_certifications(self, application_id, headers):
        return self._request(
            "GET",
            f"{BASE}/loan-applications/{application_id}/school-certifications",
            headers=headers,
        )

    def list_application_loans(self, application_id, headers):
        return self._request(
            "GET", f"{BASE}/loan-applications/{application_id}/loans", headers=headers
        )

    def list_borrower_applications(self, borrower_id, headers):
        return self._request(
            "GET", f"{BASE}/borrowers/{borrower_id}/loan-applications", headers=headers
        )

    # --- school certifications ---------------------------------------------
    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{BASE}/school-certifications/{certification_id}", headers=headers
        )

    def list_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/school-certifications", headers=headers, params=params
        )

    def certify(self, certification_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/school-certifications/{certification_id}/certify", payload, headers
        )

    def reject_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/school-certifications/{certification_id}/reject", payload, headers
        )

    def refile_certification(self, certification_id, headers):
        return self._request(
            "POST", f"{BASE}/school-certifications/{certification_id}/refile", None, headers
        )

    # --- loans -------------------------------------------------------------
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{BASE}/loans", headers=headers, params=params)

    def list_borrower_loans(self, borrower_id, headers):
        return self._request("GET", f"{BASE}/borrowers/{borrower_id}/loans", headers=headers)

    def record_enrollment_status(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/enrollment-status", payload, headers
        )

    def enter_repayment(self, loan_id, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/enter-repayment", None, headers)

    def set_autodebit(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/autodebit", payload, headers)

    def deferment_projection(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/deferment-projection", payload, headers
        )

    def create_accrual_entry(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/accrual-entries", payload, headers
        )

    def list_accrual_entries(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/accrual-entries", headers=headers)

    def create_repayment_plan(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/repayment-plans", payload, headers)

    def list_repayment_plans(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/repayment-plans", headers=headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"{BASE}/repayment-plans/{plan_id}/approve", None, headers)

    def decline_plan(self, plan_id, headers):
        return self._request("POST", f"{BASE}/repayment-plans/{plan_id}/decline", None, headers)

    def create_payment_schedule(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/payment-schedule", payload, headers
        )

    def record_payment(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/payments", payload, headers)

    def list_payments(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/payments", headers=headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{BASE}/payments/{payment_id}", headers=headers)

    def reverse_payment(self, payment_id, payload, headers):
        return self._request("POST", f"{BASE}/payments/{payment_id}/reverse", payload, headers)

    def schedule_disbursement(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/disbursements", payload, headers)

    def list_disbursements(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/disbursements", headers=headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{BASE}/disbursements/{disbursement_id}", headers=headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{BASE}/disbursements/{disbursement_id}/release", None, headers
        )

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request("DELETE", f"{BASE}/disbursements/{disbursement_id}", headers=headers)

    def reschedule_disbursement(self, disbursement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disbursements/{disbursement_id}/reschedule", payload, headers
        )

    def school_refund(self, disbursement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disbursements/{disbursement_id}/school-refund", payload, headers
        )

    def request_forbearance(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/forbearances", payload, headers)

    def list_forbearances(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/forbearances", headers=headers)

    def cancel_forbearance(self, loan_id, forbearance_id, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/forbearances/{forbearance_id}/cancel", None, headers
        )

    def cure_loan(self, loan_id, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/cure", None, headers)

    def declare_default(self, loan_id, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/declare-default", None, headers)

    def rehabilitate(self, loan_id, payload, headers):
        return self._request("POST", f"{BASE}/loans/{loan_id}/rehabilitate", payload, headers)

    def loan_summary(self, loan_id, headers):
        return self._request("GET", f"{BASE}/loans/{loan_id}/summary", headers=headers)

    def create_release_application(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/cosigner-release-applications", payload, headers
        )

    def list_release_applications(self, loan_id, headers):
        return self._request(
            "GET", f"{BASE}/loans/{loan_id}/cosigner-release-applications", headers=headers
        )

    def get_release_application(self, release_id, headers):
        return self._request(
            "GET", f"{BASE}/cosigner-release-applications/{release_id}", headers=headers
        )

    def decide_release_application(self, release_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/cosigner-release-applications/{release_id}/decision", payload, headers
        )

    def reapply_release_application(self, release_id, headers):
        return self._request(
            "POST", f"{BASE}/cosigner-release-applications/{release_id}/reapply", None, headers
        )

    def withdraw_release_application(self, release_id, headers):
        return self._request(
            "POST", f"{BASE}/cosigner-release-applications/{release_id}/withdraw", None, headers
        )

    # --- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()