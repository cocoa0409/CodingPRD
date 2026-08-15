"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All endpoints live under the /fap mount. Methods return raw requests.Response
objects so tests can assert status codes via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fap"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- ClientAccount ---
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/activate", {}, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/suspend", {}, headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/terminate", {}, headers)

    def get_client_savings(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/savings", headers=headers)

    def run_daily_sweep(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/run_daily_sweep", {}, headers)

    # --- Carrier ---
    def create_carrier(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    def approve_carrier_onboard(self, carrier_id, headers):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/approve_onboard", {}, headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/suspend", {}, headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/reinstate", {}, headers)

    def offboard_carrier(self, carrier_id, headers):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/offboard", {}, headers)

    # --- RateContract ---
    def create_rate_contract(self, carrier_id, payload, headers):
        return self._request("POST", f"{PREFIX}/carriers/{carrier_id}/rate-contracts", payload, headers)

    def list_rate_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-contracts", headers=headers, params=params)

    def get_rate_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/rate-contracts/{contract_id}", headers=headers)

    def activate_rate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-contracts/{contract_id}/activate", payload, headers)

    def discard_rate_contract(self, contract_id, headers):
        return self._request("POST", f"{PREFIX}/rate-contracts/{contract_id}/discard", {}, headers)

    # --- ShipmentRecord ---
    def create_shipment(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def void_shipment(self, shipment_id, headers):
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/void", {}, headers)

    # --- CarrierInvoice + InvoiceLine ---
    def create_invoice(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def capture_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/capture", {}, headers)

    def rate_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/rate", payload, headers)

    def finalize_invoice_audit(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/finalize_audit", {}, headers)

    def rerate_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/rerate", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/void", {}, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/write_off", {}, headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/invoice-lines/{line_id}", headers=headers)

    def list_lines_of_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/lines", headers=headers)

    def assign_line_gl_code(self, line_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoice-lines/{line_id}/gl-code", payload, headers)

    def replace_line_allocations(self, line_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoice-lines/{line_id}/allocations", payload, headers)

    def list_line_allocations(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/invoice-lines/{line_id}/allocations", headers=headers)

    # --- AuditException ---
    def list_invoice_exceptions(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/exceptions", headers=headers)

    def list_client_exceptions(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/exceptions", headers=headers, params=params)

    def notify_exception_carrier(self, exception_id, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/notify_carrier", {}, headers)

    def respond_exception_carrier(self, exception_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/carrier_respond", payload, headers)

    def counter_exception(self, exception_id, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/counter", {}, headers)

    def resolve_exception(self, exception_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/resolve", payload, headers)

    def escalate_exception(self, exception_id, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/escalate", {}, headers)

    # --- GLAccount ---
    def create_gl_account(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/gl-accounts", payload, headers)

    def list_gl_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/gl-accounts", headers=headers, params=params)

    def get_gl_account(self, gl_account_id, headers):
        return self._request("GET", f"{PREFIX}/gl-accounts/{gl_account_id}", headers=headers)

    def list_gl_account_cost_allocations(self, gl_account_id, headers):
        return self._request("GET", f"{PREFIX}/gl-accounts/{gl_account_id}/cost-allocations", headers=headers)

    # --- FxRate ---
    def create_fx_rate(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/fx-rates", payload, headers)

    def list_fx_rates(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/fx-rates", headers=headers, params=params)

    # --- PaymentRun ---
    def create_payment_run(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/payment-runs", payload, headers)

    def list_payment_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payment-runs", headers=headers, params=params)

    def get_payment_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/payment-runs/{run_id}", headers=headers)

    def add_payment_run_item(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/items", payload, headers)

    def auto_fill_payment_run(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/auto_fill", payload, headers)

    def list_payment_run_items(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/payment-runs/{run_id}/items", headers=headers)

    def list_invoice_payment_run_items(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/payment-run-items", headers=headers)

    def lock_payment_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/lock", {}, headers)

    def unlock_payment_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/unlock", {}, headers)

    def release_payment_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/release", {}, headers)

    def settle_payment_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/settle", {}, headers)

    def cancel_payment_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/payment-runs/{run_id}/cancel", {}, headers)

    # --- RemittanceAdvice ---
    def list_run_remittance_advices(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/payment-runs/{run_id}/remittance-advices", headers=headers)

    def list_carrier_remittance_advices(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}/remittance-advices", headers=headers)

    def acknowledge_remittance_advice(self, advice_id, headers):
        return self._request("POST", f"{PREFIX}/remittance-advices/{advice_id}/acknowledge", {}, headers)

    # --- RecoveryClaim ---
    def create_recovery_claim(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/recovery-claims", payload, headers)

    def list_client_recovery_claims(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/recovery-claims", headers=headers, params=params)

    def list_invoice_recovery_claims(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/recovery-claims", headers=headers)

    def file_recovery_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/recovery-claims/{claim_id}/file", {}, headers)

    def respond_recovery_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/recovery-claims/{claim_id}/carrier_respond", payload, headers)

    def collect_recovery_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/recovery-claims/{claim_id}/collect", payload, headers)

    def abandon_recovery_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/recovery-claims/{claim_id}/abandon", {}, headers)

    # --- AnalyticsExport ---
    def create_analytics_export(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/analytics-exports", payload, headers)

    def list_analytics_exports(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/analytics-exports", headers=headers, params=params)


api_client = ApiClient()
