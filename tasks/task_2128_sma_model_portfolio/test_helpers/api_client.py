"""API client: one method per endpoint defined in the PRD (mounted under /sma)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- Security
    def create_security(self, payload, headers):
        return self._request("POST", "/sma/securities", payload, headers)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/sma/securities/{security_id}", headers=headers)

    def reprice_security(self, security_id, payload, headers):
        return self._request(
            "POST", f"/sma/securities/{security_id}/price", payload, headers
        )

    # ---------------------------------------------------------------- Sponsor
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sma/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sma/sponsors/{sponsor_id}", headers=headers)

    # ------------------------------------------------------------------ Model
    def create_model(self, payload, headers):
        return self._request("POST", "/sma/models", payload, headers)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/sma/models/{model_id}", headers=headers)

    # ----------------------------------------------------------- ModelVersion
    def create_model_version(self, payload, headers):
        return self._request("POST", "/sma/model-versions", payload, headers)

    def get_model_version(self, model_version_id, headers):
        return self._request(
            "GET", f"/sma/model-versions/{model_version_id}", headers=headers
        )

    def list_model_versions(self, headers, params=None):
        return self._request("GET", "/sma/model-versions", headers=headers, params=params)

    def replace_sleeves(self, model_version_id, payload, headers):
        return self._request(
            "POST", f"/sma/model-versions/{model_version_id}/sleeves", payload, headers
        )

    def submit_model_version(self, model_version_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/model-versions/{model_version_id}/submit", payload or {}, headers
        )

    def approve_model_version(self, model_version_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/model-versions/{model_version_id}/approve", payload or {}, headers
        )

    def reject_model_version(self, model_version_id, payload, headers):
        return self._request(
            "POST", f"/sma/model-versions/{model_version_id}/reject", payload, headers
        )

    def publish_model_version(self, model_version_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/model-versions/{model_version_id}/publish", payload or {}, headers
        )

    def get_dispersion(self, model_version_id, headers, params=None):
        return self._request(
            "GET",
            f"/sma/model-versions/{model_version_id}/dispersion",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- SponsorDistribution
    def create_distribution(self, payload, headers):
        return self._request("POST", "/sma/sponsor-distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/sma/sponsor-distributions/{distribution_id}", headers=headers
        )

    def list_distributions(self, headers, params=None):
        return self._request(
            "GET", "/sma/sponsor-distributions", headers=headers, params=params
        )

    def activate_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sma/sponsor-distributions/{distribution_id}/activate",
            payload or {},
            headers,
        )

    # ---------------------------------------------------------------- Account
    def create_account(self, payload, headers):
        return self._request("POST", "/sma/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/sma/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/sma/accounts", headers=headers, params=params)

    def deposit_cash(self, account_id, payload, headers):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/deposits", payload, headers
        )

    def transfer_in(self, account_id, payload, headers):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/transfers-in", payload, headers
        )

    def suspend_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/suspend", payload or {}, headers
        )

    def reinstate_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/reinstate", payload or {}, headers
        )

    def run_implementation(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/implementations", payload or {}, headers
        )

    def evaluate_drift(self, account_id, payload, headers):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/drift-evaluations", payload, headers
        )

    def rebalance_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/accounts/{account_id}/rebalances", payload or {}, headers
        )

    def record_performance(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/sma/accounts/{account_id}/performance-observations",
            payload,
            headers,
        )

    # ------------------------------------------------------ AccountRestriction
    def create_restriction(self, payload, headers):
        return self._request("POST", "/sma/account-restrictions", payload, headers)

    def get_restriction(self, restriction_id, headers):
        return self._request(
            "GET", f"/sma/account-restrictions/{restriction_id}", headers=headers
        )

    def list_restrictions(self, headers, params=None):
        return self._request(
            "GET", "/sma/account-restrictions", headers=headers, params=params
        )

    def lift_restriction(self, restriction_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sma/account-restrictions/{restriction_id}/lift",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------- TradeOrder
    def get_trade_order(self, trade_order_id, headers):
        return self._request("GET", f"/sma/trade-orders/{trade_order_id}", headers=headers)

    def list_trade_orders(self, headers, params=None):
        return self._request("GET", "/sma/trade-orders", headers=headers, params=params)

    def cancel_trade_order(self, trade_order_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/trade-orders/{trade_order_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------ Block
    def create_block(self, payload, headers):
        return self._request("POST", "/sma/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/sma/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/sma/blocks", headers=headers, params=params)

    def execute_block(self, block_id, payload, headers):
        return self._request("POST", f"/sma/blocks/{block_id}/execute", payload, headers)

    def allocate_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/blocks/{block_id}/allocate", payload or {}, headers
        )

    def unwind_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/blocks/{block_id}/unwind", payload or {}, headers
        )

    # ----------------------------------------------------------------- TaxLot
    def get_tax_lot(self, tax_lot_id, headers):
        return self._request("GET", f"/sma/tax-lots/{tax_lot_id}", headers=headers)

    def list_tax_lots(self, headers, params=None):
        return self._request("GET", "/sma/tax-lots", headers=headers, params=params)

    # -------------------------------------------------------- HarvestProposal
    def create_harvest_proposal(self, payload, headers):
        return self._request("POST", "/sma/harvest-proposals", payload, headers)

    def get_harvest_proposal(self, harvest_proposal_id, headers):
        return self._request(
            "GET", f"/sma/harvest-proposals/{harvest_proposal_id}", headers=headers
        )

    def list_harvest_proposals(self, headers, params=None):
        return self._request(
            "GET", "/sma/harvest-proposals", headers=headers, params=params
        )

    def approve_harvest_proposal(self, harvest_proposal_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sma/harvest-proposals/{harvest_proposal_id}/approve",
            payload or {},
            headers,
        )

    def reject_harvest_proposal(self, harvest_proposal_id, payload, headers):
        return self._request(
            "POST",
            f"/sma/harvest-proposals/{harvest_proposal_id}/reject",
            payload,
            headers,
        )

    def execute_harvest_proposal(self, harvest_proposal_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sma/harvest-proposals/{harvest_proposal_id}/execute",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------- FeeInvoice
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/sma/fee-invoices", payload, headers)

    def get_fee_invoice(self, fee_invoice_id, headers):
        return self._request("GET", f"/sma/fee-invoices/{fee_invoice_id}", headers=headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/sma/fee-invoices", headers=headers, params=params)

    def issue_fee_invoice(self, fee_invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/fee-invoices/{fee_invoice_id}/issue", payload or {}, headers
        )

    def pay_fee_invoice(self, fee_invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/fee-invoices/{fee_invoice_id}/pay", payload or {}, headers
        )

    def void_fee_invoice(self, fee_invoice_id, payload, headers):
        return self._request(
            "POST", f"/sma/fee-invoices/{fee_invoice_id}/void", payload, headers
        )

    def mark_fee_invoice_delinquent(self, fee_invoice_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sma/fee-invoices/{fee_invoice_id}/mark-delinquent",
            payload or {},
            headers,
        )

    def write_off_fee_invoice(self, fee_invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/sma/fee-invoices/{fee_invoice_id}/write-off", payload or {}, headers
        )

    # ------------------------------------------------------------ raw helpers
    def raw_get(self, path, headers=None, params=None):
        """Escape hatch for tests that must address a path directly."""
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload=None, headers=None):
        """Escape hatch for tests that must address a path directly."""
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
