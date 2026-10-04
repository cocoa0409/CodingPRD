"""API client: one method per endpoint defined in the PRD (Section 4).

URL convention: every business resource lives under the ``/disaster-relief``
prefix and its method builds the path with ``self._p(...)``. The logical-clock
endpoint is a platform-level operation at the SERVER ROOT — PRD 2.4 states it
"sits outside that prefix" — so ``set_clock`` posts to the literal path
``/_clock/set_current_utc`` WITHOUT the prefix. ``_p`` refuses paths that
start with ``/_`` so a platform path can never be prefixed by accident.
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods; ``_request`` is inherited."""

    @staticmethod
    def _p(path: str) -> str:
        """Prefix a business-resource path with /disaster-relief."""
        if path.startswith("/_"):
            raise ValueError(
                f"platform path {path!r} must be requested unprefixed "
                f"(server root), not under {API_PREFIX}"
            )
        return f"{API_PREFIX}{path}"

    # ---- logical clock (UNPREFIXED — server root, PRD 2.4) -----------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", CLOCK_PATH,
                             {"current_utc": current_utc}, headers)

    # ---- disaster declarations ----------------------------------------------
    def create_declaration(self, payload, headers):
        return self._request("POST", self._p("/disaster-declarations"),
                             payload, headers)

    # ---- applicants -----------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", self._p("/applicants"), payload, headers)

    # ---- loan applications ----------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", self._p("/loan-applications"),
                             payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", self._p("/loan-applications"),
                             headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", self._p(f"/loan-applications/{application_id}"),
            headers=headers)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", self._p(f"/loan-applications/{application_id}/submit"),
            {}, headers)

    def request_reconsideration(self, application_id, headers):
        return self._request(
            "POST",
            self._p(f"/loan-applications/{application_id}/request-reconsideration"),
            {}, headers)

    def create_credit_review(self, application_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/loan-applications/{application_id}/credit-reviews"),
            payload, headers)

    def list_credit_reviews(self, application_id, headers, params=None):
        return self._request(
            "GET",
            self._p(f"/loan-applications/{application_id}/credit-reviews"),
            headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", self._p(f"/loan-applications/{application_id}/decision"),
            payload, headers)

    # ---- damage verifications ---------------------------------------------------
    def create_damage_verification(self, application_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/loan-applications/{application_id}/damage-verifications"),
            payload, headers)

    def list_damage_verifications(self, application_id, headers, params=None):
        return self._request(
            "GET",
            self._p(f"/loan-applications/{application_id}/damage-verifications"),
            headers=headers, params=params)

    def complete_damage_verification(self, verification_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/damage-verifications/{verification_id}/complete"),
            payload, headers)

    def dispute_damage_verification(self, verification_id, headers):
        return self._request(
            "POST",
            self._p(f"/damage-verifications/{verification_id}/dispute"),
            {}, headers)

    # ---- grant awards -------------------------------------------------------------
    def create_grant_award(self, application_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/loan-applications/{application_id}/grant-awards"),
            payload, headers)

    def list_grant_awards(self, application_id, headers, params=None):
        return self._request(
            "GET",
            self._p(f"/loan-applications/{application_id}/grant-awards"),
            headers=headers, params=params)

    # ---- loans ----------------------------------------------------------------------
    def list_loans(self, headers, params=None):
        return self._request("GET", self._p("/loans"),
                             headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", self._p(f"/loans/{loan_id}"),
                             headers=headers)

    def accept_loan(self, loan_id, headers):
        return self._request("POST", self._p(f"/loans/{loan_id}/accept"),
                             {}, headers)

    # ---- disbursement tranches -------------------------------------------------------
    def list_tranches(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/disbursement-tranches"),
            headers=headers, params=params)

    def release_tranche(self, tranche_id, headers):
        return self._request(
            "POST", self._p(f"/disbursement-tranches/{tranche_id}/release"),
            {}, headers)

    # ---- repair milestones --------------------------------------------------------------
    def create_milestone(self, loan_id, payload, headers):
        return self._request(
            "POST", self._p(f"/loans/{loan_id}/repair-milestones"),
            payload, headers)

    def list_milestones(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/repair-milestones"),
            headers=headers, params=params)

    def decide_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", self._p(f"/repair-milestones/{milestone_id}/decision"),
            payload, headers)

    # ---- modification requests -------------------------------------------------------------
    def create_modification_request(self, loan_id, payload, headers):
        return self._request(
            "POST", self._p(f"/loans/{loan_id}/modification-requests"),
            payload, headers)

    def list_modification_requests(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/modification-requests"),
            headers=headers, params=params)

    def decide_modification_request(self, modification_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/modification-requests/{modification_id}/decision"),
            payload, headers)

    # ---- insurance settlements ----------------------------------------------------------------
    def create_insurance_settlement(self, loan_id, payload, headers):
        return self._request(
            "POST", self._p(f"/loans/{loan_id}/insurance-settlements"),
            payload, headers)

    def list_insurance_settlements(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/insurance-settlements"),
            headers=headers, params=params)

    def apply_insurance_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/insurance-settlements/{settlement_id}/apply"),
            payload, headers)

    def void_insurance_settlement(self, settlement_id, headers):
        return self._request(
            "POST", self._p(f"/insurance-settlements/{settlement_id}/void"),
            {}, headers)

    # ---- excess funds receivables ---------------------------------------------------------------
    def list_excess_funds_receivables(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/excess-funds-receivables"),
            headers=headers, params=params)

    def pay_excess_funds_receivable(self, receivable_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/excess-funds-receivables/{receivable_id}/payments"),
            payload, headers)

    # ---- servicing actions -------------------------------------------------------------------------
    def create_servicing_action(self, loan_id, payload, headers):
        return self._request(
            "POST", self._p(f"/loans/{loan_id}/servicing-actions"),
            payload, headers)

    def list_servicing_actions(self, loan_id, headers, params=None):
        return self._request(
            "GET", self._p(f"/loans/{loan_id}/servicing-actions"),
            headers=headers, params=params)

    def decide_servicing_action(self, action_id, payload, headers):
        return self._request(
            "POST", self._p(f"/servicing-actions/{action_id}/decision"),
            payload, headers)

    # ---- payments --------------------------------------------------------------------------------------
    def create_payment(self, loan_id, payload, headers):
        return self._request("POST", self._p(f"/loans/{loan_id}/payments"),
                             payload, headers)

    def list_payments(self, loan_id, headers, params=None):
        return self._request("GET", self._p(f"/loans/{loan_id}/payments"),
                             headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request(
            "POST", self._p(f"/payments/{payment_id}/reverse"), {}, headers)


api_client = ApiClient()
