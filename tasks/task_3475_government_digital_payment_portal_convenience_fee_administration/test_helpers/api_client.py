"""API client: one method per endpoint defined in the PRD.

All business resources are mounted under the ``/portal`` prefix. The logical
clock control ``POST /_clock/set_current_utc`` lives outside that prefix,
exactly as the PRD specifies.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/portal"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, current_utc, headers):
        # Mounted OUTSIDE the /portal prefix per the PRD logical-clock section.
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --------------------------------------------------------------- agencies
    def create_agency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"{PREFIX}/agencies/{agency_id}", headers=headers)

    def activate_agency(self, agency_id, headers):
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/activate", {}, headers
        )

    def suspend_agency(self, agency_id, headers):
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/suspend", {}, headers
        )

    def offboard_agency(self, agency_id, headers):
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/offboard", {}, headers
        )

    # ----------------------------------------------------- settlement accounts
    def create_settlement_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-accounts", payload, headers)

    def list_settlement_accounts(self, agency_id, headers):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/settlement-accounts",
            headers=headers,
        )

    def verify_settlement_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-accounts/{account_id}/verify",
            payload, headers,
        )

    # ------------------------------------------------------------ pricing tiers
    def create_pricing_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pricing-tiers", payload, headers)

    def list_pricing_tiers(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/pricing-tiers",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------ attestations
    def create_attestation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/attestations", payload, headers)

    def list_attestations(self, agency_id, headers):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/attestations", headers=headers
        )

    # ---------------------------------------------------------------- services
    def create_service(self, payload, headers):
        return self._request("POST", f"{PREFIX}/services", payload, headers)

    def get_service(self, service_id, headers):
        return self._request("GET", f"{PREFIX}/services/{service_id}", headers=headers)

    def list_services(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/services",
            headers=headers, params=params,
        )

    def update_service(self, service_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/services/{service_id}", payload, headers
        )

    def activate_service(self, service_id, headers):
        return self._request(
            "POST", f"{PREFIX}/services/{service_id}/activate", {}, headers
        )

    def deactivate_service(self, service_id, headers):
        return self._request(
            "POST", f"{PREFIX}/services/{service_id}/deactivate", {}, headers
        )

    # -------------------------------------------------- statutory authorizations
    def create_statutory_authorization(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/statutory-authorizations", payload, headers
        )

    def approve_statutory_authorization(self, authorization_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/statutory-authorizations/{authorization_id}/approve",
            {}, headers,
        )

    def list_statutory_authorizations(self, service_id, headers):
        return self._request(
            "GET", f"{PREFIX}/services/{service_id}/authorizations", headers=headers
        )

    # ----------------------------------------------------------------- payers
    def create_payer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"{PREFIX}/payers/{payer_id}", headers=headers)

    # -------------------------------------------------------------- instruments
    def create_instrument(self, payer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payers/{payer_id}/instruments", payload, headers
        )

    def list_instruments(self, payer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/payers/{payer_id}/instruments", headers=headers
        )

    def verify_ach_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/instruments/{instrument_id}/verify-ach",
            payload, headers,
        )

    # --------------------------------------------------------------- fee quotes
    def create_fee_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fee-quotes", payload, headers)

    def get_fee_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/fee-quotes/{quote_id}", headers=headers)

    def list_fee_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fee-quotes", headers=headers, params=params)

    # ------------------------------------------------------- payment transactions
    def authorize_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/payment-transactions/{transaction_id}", headers=headers
        )

    def list_transactions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/payment-transactions", headers=headers, params=params
        )

    def capture_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-transactions/{transaction_id}/capture",
            {}, headers,
        )

    def void_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-transactions/{transaction_id}/void",
            {}, headers,
        )

    def ach_return_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-transactions/{transaction_id}/ach-return",
            {}, headers,
        )

    def re_present_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-transactions/{transaction_id}/re-present",
            {}, headers,
        )

    def list_transaction_refunds(self, transaction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/payment-transactions/{transaction_id}/refunds",
            headers=headers,
        )

    def list_transaction_chargebacks(self, transaction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/payment-transactions/{transaction_id}/chargebacks",
            headers=headers,
        )

    # --------------------------------------------------------- settlement batches
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-batches/{batch_id}", headers=headers
        )

    def list_settlement_batches(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/settlement-batches",
            headers=headers, params=params,
        )

    def close_settlement_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/close", {}, headers
        )

    def submit_settlement_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/submit", {}, headers
        )

    def confirm_batch_deposit(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/confirm-deposit",
            payload, headers,
        )

    def reconcile_settlement_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/reconcile", {}, headers
        )

    def list_batch_exceptions(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-batches/{batch_id}/exceptions",
            headers=headers,
        )

    # -------------------------------------------------- reconciliation exceptions
    def resolve_reconciliation_exception(self, exception_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reconciliation-exceptions/{exception_id}/resolve",
            payload, headers,
        )

    # ------------------------------------------------------------------ refunds
    def create_refund(self, payload, headers):
        return self._request("POST", f"{PREFIX}/refunds", payload, headers)

    def decide_refund(self, refund_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refunds/{refund_id}/decide", payload, headers
        )

    # --------------------------------------------------------------- chargebacks
    def create_chargeback(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chargebacks", payload, headers)

    def contest_chargeback(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{case_id}/contest", payload, headers
        )

    def accept_chargeback(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{case_id}/accept", {}, headers
        )

    def record_chargeback_outcome(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{case_id}/record-outcome",
            payload, headers,
        )

    # ------------------------------------------------------------- self-funding
    def close_period(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/self-funding/close-period", payload, headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/self-funding-ledger", headers=headers, params=params
        )


api_client = ApiClient()
