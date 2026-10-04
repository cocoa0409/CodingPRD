"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/platform/_clock/set_current_utc", payload, headers)

    # --- ModelVersion ---
    def create_model_version(self, payload, headers):
        return self._request("POST", "/platform/model-versions", payload, headers)

    def get_model_version(self, model_id, headers):
        return self._request("GET", f"/platform/model-versions/{model_id}", headers=headers)

    def list_model_versions(self, headers, params=None):
        return self._request("GET", "/platform/model-versions", headers=headers, params=params)

    def patch_model_version(self, model_id, payload, headers):
        return self._request("PATCH", f"/platform/model-versions/{model_id}", payload, headers)

    def validate_model_version(self, model_id, headers, payload=None):
        return self._request("POST", f"/platform/model-versions/{model_id}/validate", payload or {}, headers)

    def activate_model_version(self, model_id, headers, payload=None):
        return self._request("POST", f"/platform/model-versions/{model_id}/activate", payload or {}, headers)

    def retire_model_version(self, model_id, headers, payload=None):
        return self._request("POST", f"/platform/model-versions/{model_id}/retire", payload or {}, headers)

    # --- FairnessReview ---
    def create_fairness_review(self, payload, headers):
        return self._request("POST", "/platform/fairness-reviews", payload, headers)

    def list_fairness_reviews(self, headers, params=None):
        return self._request("GET", "/platform/fairness-reviews", headers=headers, params=params)

    def get_fairness_review(self, review_id, headers):
        return self._request("GET", f"/platform/fairness-reviews/{review_id}", headers=headers)

    def decide_fairness_review(self, review_id, payload, headers):
        return self._request("POST", f"/platform/fairness-reviews/{review_id}/decide", payload, headers)

    # --- Attestation ---
    def create_attestation(self, model_id, payload, headers):
        return self._request("POST", f"/platform/model-versions/{model_id}/attestations", payload, headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", "/platform/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/platform/attestations/{attestation_id}", headers=headers)

    # --- Partner ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/platform/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/platform/partners/{partner_id}", headers=headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", "/platform/partners", headers=headers, params=params)

    def activate_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"/platform/partners/{partner_id}/activate", payload or {}, headers)

    def suspend_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"/platform/partners/{partner_id}/suspend", payload or {}, headers)

    def offboard_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"/platform/partners/{partner_id}/offboard", payload or {}, headers)

    # --- CreditBox ---
    def create_credit_box(self, partner_id, payload, headers):
        return self._request("POST", f"/platform/partners/{partner_id}/credit-boxes", payload, headers)

    def list_credit_boxes(self, partner_id, headers, params=None):
        return self._request("GET", f"/platform/partners/{partner_id}/credit-boxes", headers=headers, params=params)

    def get_credit_box(self, box_id, headers):
        return self._request("GET", f"/platform/credit-boxes/{box_id}", headers=headers)

    def activate_credit_box(self, partner_id, box_id, payload, headers):
        return self._request(
            "POST", f"/platform/partners/{partner_id}/credit-boxes/{box_id}/activate", payload, headers
        )

    def retire_credit_box(self, partner_id, box_id, headers, payload=None):
        return self._request(
            "POST", f"/platform/partners/{partner_id}/credit-boxes/{box_id}/retire", payload or {}, headers
        )

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/platform/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/platform/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/platform/applicants", headers=headers, params=params)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/platform/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/platform/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/platform/applications", headers=headers, params=params)

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/platform/applications/{application_id}/withdraw", payload or {}, headers)

    def allocate_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/platform/applications/{application_id}/allocate", payload or {}, headers)

    # --- Verification ---
    def list_verifications(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/platform/applications/{application_id}/verifications", headers=headers, params=params
        )

    def instant_check_verification(self, application_id, verification_id, headers, payload=None):
        return self._request(
            "POST",
            f"/platform/applications/{application_id}/verifications/{verification_id}/instant-check",
            payload or {},
            headers,
        )

    def manual_decide_verification(self, application_id, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/platform/applications/{application_id}/verifications/{verification_id}/manual-decision",
            payload,
            headers,
        )

    # --- Loan ---
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/platform/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/platform/loans", headers=headers, params=params)

    def post_payment(self, loan_id, payload, headers):
        return self._request("POST", f"/platform/loans/{loan_id}/payments", payload, headers)

    def advance_servicing(self, loan_id, headers, payload=None):
        return self._request("POST", f"/platform/loans/{loan_id}/advance-servicing", payload or {}, headers)

    def charge_off_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"/platform/loans/{loan_id}/charge-off", payload or {}, headers)

    # --- ServicingEvent ---
    def list_servicing_events(self, loan_id, headers, params=None):
        return self._request("GET", f"/platform/loans/{loan_id}/servicing-events", headers=headers, params=params)

    # --- SecuritizationPool ---
    def create_securitization_pool(self, payload, headers):
        return self._request("POST", "/platform/securitization-pools", payload, headers)

    def get_securitization_pool(self, pool_id, headers):
        return self._request("GET", f"/platform/securitization-pools/{pool_id}", headers=headers)

    def list_securitization_pools(self, headers, params=None):
        return self._request("GET", "/platform/securitization-pools", headers=headers, params=params)

    def close_securitization_pool(self, pool_id, headers, payload=None):
        return self._request("POST", f"/platform/securitization-pools/{pool_id}/close", payload or {}, headers)

    # --- AllocationDecision ---
    def list_allocation_decisions(self, headers, params=None):
        return self._request("GET", "/platform/allocation-decisions", headers=headers, params=params)

    def get_allocation_decision(self, decision_id, headers):
        return self._request("GET", f"/platform/allocation-decisions/{decision_id}", headers=headers)


api_client = ApiClient()
