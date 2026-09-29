"""API client: one method per endpoint defined in the PRD's endpoint table."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Device Installment Upgrade Program API."""

    # ---- Customer --------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_carrier_account(self, customer_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/customers/{customer_id}/carrier-accounts",
                             payload, headers)

    def list_carrier_accounts(self, customer_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/customers/{customer_id}/carrier-accounts",
                             headers=headers, params=params)

    # ---- DeviceModel -----------------------------------------------------
    def create_device_model(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/device-models", payload, headers)

    def list_device_models(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/device-models", headers=headers, params=params)

    def get_device_model(self, model_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/device-models/{model_id}", headers=headers)

    # ---- CreditApplication -----------------------------------------------
    def create_credit_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/credit-applications", payload, headers)

    def list_credit_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/credit-applications", headers=headers, params=params)

    def get_credit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/credit-applications/{application_id}", headers=headers)

    def decide_credit_application(self, application_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"/credit-applications/{application_id}/decision",
                             payload, headers)

    # ---- InstallmentLoan -------------------------------------------------
    def create_loan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/loans", payload, headers)

    def list_loans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_installments(self, loan_id: str, headers: Dict[str, str],
                          params: Optional[Dict] = None):
        return self._request("GET", f"/loans/{loan_id}/installments",
                             headers=headers, params=params)

    def list_delinquency_events(self, loan_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/loans/{loan_id}/delinquency-events",
                             headers=headers, params=params)

    def list_loan_payoff_quotes(self, loan_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/loans/{loan_id}/payoff-quotes",
                             headers=headers, params=params)

    def create_payment(self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/loans/{loan_id}/payments", payload, headers)

    def create_payoff_quote(self, loan_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/loans/{loan_id}/payoff-quotes", payload, headers)

    def cancel_loan(self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/loans/{loan_id}/cancellation", payload, headers)

    # ---- PaymentPosting --------------------------------------------------
    def list_payment_postings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/payment-postings", headers=headers, params=params)

    def get_payment_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/payment-postings/{posting_id}", headers=headers)

    # ---- DeviceUnit ------------------------------------------------------
    def list_device_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/device-units", headers=headers, params=params)

    def get_device_unit(self, device_unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/device-units/{device_unit_id}", headers=headers)

    def activate_device_unit(self, device_unit_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/device-units/{device_unit_id}/activation",
                             payload, headers)

    def request_device_unlock(self, device_unit_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/device-units/{device_unit_id}/unlock-request",
                             payload if payload is not None else {}, headers)

    # ---- UpgradeRequest --------------------------------------------------
    def create_upgrade_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/upgrade-requests", payload, headers)

    def list_upgrade_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/upgrade-requests", headers=headers, params=params)

    def get_upgrade_request(self, upgrade_request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/upgrade-requests/{upgrade_request_id}", headers=headers)

    def declare_trade_in(self, upgrade_request_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/upgrade-requests/{upgrade_request_id}/trade-in-declaration",
            payload, headers)

    def complete_upgrade(self, upgrade_request_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/upgrade-requests/{upgrade_request_id}/completion",
                             payload, headers)

    # ---- TradeIn / DiagnosticReport --------------------------------------
    def list_trade_ins(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def receive_trade_in(self, trade_in_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/trade-ins/{trade_in_id}/receipt",
                             payload if payload is not None else {}, headers)

    def create_diagnostic_report(self, trade_in_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/trade-ins/{trade_in_id}/diagnostic-reports",
                             payload, headers)

    def list_diagnostic_reports(self, trade_in_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/trade-ins/{trade_in_id}/diagnostic-reports",
                             headers=headers, params=params)

    def dispute_trade_in(self, trade_in_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/trade-ins/{trade_in_id}/dispute", payload, headers)

    def regrade_trade_in(self, trade_in_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/trade-ins/{trade_in_id}/regrade", payload, headers)

    # ---- Servicing and the logical clock ---------------------------------
    def run_daily_servicing(self, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/servicing/daily-run",
                             payload if payload is not None else {}, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
