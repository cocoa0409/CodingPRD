"""API client: one method per endpoint declared in PRD §4.

The API is mounted at the service root with no versioned path prefix (PRD §4),
so every path below is complete as written — including the TreasurySupervisor-only
logical-clock endpoint POST /_clock/set_current_utc, which sits outside the
business surface (PRD §2.4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4; TreasurySupervisor only) ---------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- CreditorAgency ---------------------------------------------------------
    def create_creditor_agency(self, payload, headers):
        return self._request("POST", "/creditor-agencies", payload, headers)

    def get_creditor_agency(self, creditor_agency_id, headers):
        return self._request(
            "GET", f"/creditor-agencies/{creditor_agency_id}", headers=headers
        )

    # --- Payee ------------------------------------------------------------------
    def create_payee(self, payload, headers):
        return self._request("POST", "/payees", payload, headers)

    # --- ExemptionPolicy --------------------------------------------------------
    def create_exemption_policy(self, payload, headers):
        return self._request("POST", "/exemption-policies", payload, headers)

    def activate_exemption_policy(self, exemption_policy_id, headers):
        return self._request(
            "POST",
            f"/exemption-policies/{exemption_policy_id}/activate",
            {},
            headers,
        )

    # --- Debt -------------------------------------------------------------------
    def create_debt(self, payload, headers):
        return self._request("POST", "/debts", payload, headers)

    def get_debt(self, debt_id, headers):
        return self._request("GET", f"/debts/{debt_id}", headers=headers)

    def list_debts(self, headers, params=None):
        return self._request("GET", "/debts", headers=headers, params=params)

    def notice_debt(self, debt_id, payload, headers):
        return self._request("POST", f"/debts/{debt_id}/notice", payload, headers)

    def activate_debt(self, debt_id, headers):
        return self._request("POST", f"/debts/{debt_id}/activate", {}, headers)

    # --- PaymentFile / Payment --------------------------------------------------
    def create_payment_file(self, payload, headers):
        return self._request("POST", "/payment-files", payload, headers)

    def get_payment_file(self, payment_file_id, headers):
        return self._request(
            "GET", f"/payment-files/{payment_file_id}", headers=headers
        )

    def create_payment(self, payment_file_id, payload, headers):
        return self._request(
            "POST", f"/payment-files/{payment_file_id}/payments", payload, headers
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def evaluate_offsets(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/payments/{payment_id}/evaluate-offsets", payload, headers
        )

    def execute_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/execute", {}, headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # --- Offset -----------------------------------------------------------------
    def get_offset(self, offset_id, headers):
        return self._request("GET", f"/offsets/{offset_id}", headers=headers)

    def list_offsets(self, headers, params=None):
        return self._request("GET", "/offsets", headers=headers, params=params)

    # --- RefundClaim ------------------------------------------------------------
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers)

    def get_refund_claim(self, refund_claim_id, headers):
        return self._request(
            "GET", f"/refund-claims/{refund_claim_id}", headers=headers
        )

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def review_refund_claim(self, refund_claim_id, headers):
        return self._request(
            "POST", f"/refund-claims/{refund_claim_id}/review", {}, headers
        )

    def decide_refund_claim(self, refund_claim_id, payload, headers):
        return self._request(
            "POST", f"/refund-claims/{refund_claim_id}/decide", payload, headers
        )

    def appeal_refund_claim(self, refund_claim_id, headers):
        return self._request(
            "POST", f"/refund-claims/{refund_claim_id}/appeal", {}, headers
        )

    # --- CollectionAgency / CollectionAction ------------------------------------
    def create_collection_agency(self, payload, headers):
        return self._request("POST", "/collection-agencies", payload, headers)

    def create_collection_action(self, debt_id, payload, headers):
        return self._request(
            "POST", f"/debts/{debt_id}/collection-actions", payload, headers
        )

    def get_collection_action(self, collection_action_id, headers):
        return self._request(
            "GET", f"/collection-actions/{collection_action_id}", headers=headers
        )

    def list_collection_actions(self, headers, params=None):
        return self._request(
            "GET", "/collection-actions", headers=headers, params=params
        )

    def activate_collection_action(self, collection_action_id, headers):
        return self._request(
            "POST",
            f"/collection-actions/{collection_action_id}/activate",
            {},
            headers,
        )

    def collect_collection_action(self, collection_action_id, payload, headers):
        return self._request(
            "POST",
            f"/collection-actions/{collection_action_id}/collect",
            payload,
            headers,
        )

    def terminate_collection_action(self, collection_action_id, headers):
        return self._request(
            "POST",
            f"/collection-actions/{collection_action_id}/terminate",
            {},
            headers,
        )

    # --- ReverseOffsetRequest ---------------------------------------------------
    def create_reverse_offset_request(self, payload, headers):
        return self._request("POST", "/reverse-offset-requests", payload, headers)

    def confirm_reverse_offset_request(self, reverse_offset_request_id, headers):
        return self._request(
            "POST",
            f"/reverse-offset-requests/{reverse_offset_request_id}/confirm",
            {},
            headers,
        )

    # --- ReciprocalAgreement ----------------------------------------------------
    def create_reciprocal_agreement(self, payload, headers):
        return self._request("POST", "/reciprocal-agreements", payload, headers)

    def activate_reciprocal_agreement(self, reciprocal_agreement_id, headers):
        return self._request(
            "POST",
            f"/reciprocal-agreements/{reciprocal_agreement_id}/activate",
            {},
            headers,
        )

    # --- DoNotPayRecord ---------------------------------------------------------
    def create_do_not_pay_record(self, payload, headers):
        return self._request("POST", "/do-not-pay-records", payload, headers)

    def remove_do_not_pay_record(self, do_not_pay_record_id, headers):
        return self._request(
            "POST",
            f"/do-not-pay-records/{do_not_pay_record_id}/remove",
            {},
            headers,
        )


api_client = ApiClient()
