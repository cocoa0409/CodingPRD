"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------------- funds
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    # ------------------------------------------------------------- share classes
    def create_share_class(self, payload, headers):
        return self._request("POST", "/share-classes", payload, headers)

    def get_share_class(self, share_class_id, headers):
        return self._request("GET", f"/share-classes/{share_class_id}", headers=headers)

    def list_share_classes(self, headers, params=None):
        return self._request("GET", "/share-classes", headers=headers, params=params)

    def list_share_class_nav_records(self, share_class_id, headers, params=None):
        return self._request(
            "GET", f"/share-classes/{share_class_id}/nav-records",
            headers=headers, params=params,
        )

    def list_share_class_blue_sky_registrations(self, share_class_id, headers, params=None):
        return self._request(
            "GET", f"/share-classes/{share_class_id}/blue-sky-registrations",
            headers=headers, params=params,
        )

    def list_share_class_distributions(self, share_class_id, headers, params=None):
        return self._request(
            "GET", f"/share-classes/{share_class_id}/distributions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------- shareholder accounts
    def create_shareholder_account(self, payload, headers):
        return self._request("POST", "/shareholder-accounts", payload, headers)

    def get_shareholder_account(self, account_id, headers):
        return self._request("GET", f"/shareholder-accounts/{account_id}", headers=headers)

    def list_shareholder_accounts(self, headers, params=None):
        return self._request("GET", "/shareholder-accounts", headers=headers, params=params)

    def update_shareholder_account(self, account_id, payload, headers):
        return self._request(
            "PATCH", f"/shareholder-accounts/{account_id}", payload, headers
        )

    def activate_shareholder_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/shareholder-accounts/{account_id}/activate", payload, headers
        )

    def restrict_shareholder_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/shareholder-accounts/{account_id}/restrict", payload, headers
        )

    def reinstate_shareholder_account(self, account_id, headers):
        return self._request(
            "POST", f"/shareholder-accounts/{account_id}/reinstate", {}, headers
        )

    def close_shareholder_account(self, account_id, headers):
        return self._request(
            "POST", f"/shareholder-accounts/{account_id}/close", {}, headers
        )

    def list_account_positions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/shareholder-accounts/{account_id}/positions",
            headers=headers, params=params,
        )

    # ---------------------------------------------------- positions & the ledger
    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def get_share_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/share-ledger-entries/{entry_id}", headers=headers)

    def list_share_ledger_entries(self, headers, params=None):
        return self._request("GET", "/share-ledger-entries", headers=headers, params=params)

    # ------------------------------------------------------- state registrations
    def create_blue_sky_registration(self, payload, headers):
        return self._request("POST", "/blue-sky-registrations", payload, headers)

    def get_blue_sky_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/blue-sky-registrations/{registration_id}", headers=headers
        )

    # -------------------------------------------------------------- NAV records
    def create_nav_record(self, payload, headers):
        return self._request("POST", "/nav-records", payload, headers)

    def get_nav_record(self, nav_record_id, headers):
        return self._request("GET", f"/nav-records/{nav_record_id}", headers=headers)

    def finalize_nav_record(self, nav_record_id, headers):
        return self._request("POST", f"/nav-records/{nav_record_id}/finalize", {}, headers)

    def repost_nav_record(self, nav_record_id, payload, headers):
        return self._request(
            "POST", f"/nav-records/{nav_record_id}/repost", payload, headers
        )

    # ------------------------------------------------------------------- trades
    def create_trade(self, payload, headers):
        return self._request("POST", "/trades", payload, headers)

    def get_trade(self, trade_id, headers):
        return self._request("GET", f"/trades/{trade_id}", headers=headers)

    def list_trades(self, headers, params=None):
        return self._request("GET", "/trades", headers=headers, params=params)

    def approve_as_of_trade(self, trade_id, headers):
        return self._request("POST", f"/trades/{trade_id}/approve-as-of", {}, headers)

    def price_trade(self, trade_id, headers):
        return self._request("POST", f"/trades/{trade_id}/price", {}, headers)

    def settle_trade(self, trade_id, headers):
        return self._request("POST", f"/trades/{trade_id}/settle", {}, headers)

    def cancel_trade(self, trade_id, payload, headers):
        return self._request("POST", f"/trades/{trade_id}/cancel", payload, headers)

    def reverse_trade(self, trade_id, payload, headers):
        return self._request("POST", f"/trades/{trade_id}/reverse", payload, headers)

    # ------------------------------------------------------------ distributions
    def create_distribution(self, payload, headers):
        return self._request("POST", "/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def record_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/distributions/{distribution_id}/record", {}, headers
        )

    def pay_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/pay", {}, headers)

    def reverse_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/distributions/{distribution_id}/reverse", payload, headers
        )

    def get_distribution_payment(self, payment_id, headers):
        return self._request(
            "GET", f"/distribution-payments/{payment_id}", headers=headers
        )

    def list_distribution_payments(self, headers, params=None):
        return self._request(
            "GET", "/distribution-payments", headers=headers, params=params
        )

    # --------------------------------------------------------- systematic plans
    def create_systematic_plan(self, payload, headers):
        return self._request("POST", "/systematic-plans", payload, headers)

    def get_systematic_plan(self, plan_id, headers):
        return self._request("GET", f"/systematic-plans/{plan_id}", headers=headers)

    def list_systematic_plans(self, headers, params=None):
        return self._request("GET", "/systematic-plans", headers=headers, params=params)

    def update_systematic_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/systematic-plans/{plan_id}", payload, headers)

    def execute_systematic_plan(self, plan_id, headers):
        return self._request("POST", f"/systematic-plans/{plan_id}/execute", {}, headers)

    # ------------------------------------------------------ pricing error cases
    def create_pricing_error_case(self, payload, headers):
        return self._request("POST", "/pricing-error-cases", payload, headers)

    def get_pricing_error_case(self, case_id, headers):
        return self._request("GET", f"/pricing-error-cases/{case_id}", headers=headers)

    def list_pricing_error_cases(self, headers, params=None):
        return self._request("GET", "/pricing-error-cases", headers=headers, params=params)

    def assess_pricing_error_case(self, case_id, headers):
        return self._request("POST", f"/pricing-error-cases/{case_id}/assess", {}, headers)

    def close_immaterial_pricing_error_case(self, case_id, headers):
        return self._request(
            "POST", f"/pricing-error-cases/{case_id}/close-immaterial", {}, headers
        )

    def approve_correction_pricing_error_case(self, case_id, headers):
        return self._request(
            "POST", f"/pricing-error-cases/{case_id}/approve-correction", {}, headers
        )

    def reprocess_pricing_error_case(self, case_id, headers):
        return self._request(
            "POST", f"/pricing-error-cases/{case_id}/reprocess", {}, headers
        )

    # --------------------------------------------------- omnibus reconciliations
    def create_omnibus_reconciliation(self, payload, headers):
        return self._request("POST", "/omnibus-reconciliations", payload, headers)

    def get_omnibus_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"/omnibus-reconciliations/{reconciliation_id}", headers=headers
        )

    def list_omnibus_reconciliations(self, headers, params=None):
        return self._request(
            "GET", "/omnibus-reconciliations", headers=headers, params=params
        )

    def adjust_omnibus_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST", f"/omnibus-reconciliations/{reconciliation_id}/adjust", payload, headers
        )

    def dispute_omnibus_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST", f"/omnibus-reconciliations/{reconciliation_id}/dispute", payload, headers
        )


api_client = ApiClient()
