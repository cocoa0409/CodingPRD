"""API client: one method per operation in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/v1/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/v1/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/v1/accounts/{account_id}", headers=headers)

    def get_account_billing_summary(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/v1/accounts/{account_id}/billing-summary", headers=headers,
            params=params,
        )

    def list_account_ledger_entries(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/v1/accounts/{account_id}/ledger-entries", headers=headers,
            params=params,
        )

    # --- warehouses ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/v1/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/v1/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/v1/warehouses/{warehouse_id}", headers=headers)

    def patch_warehouse(self, warehouse_id, payload, headers):
        return self._request("PATCH", f"/v1/warehouses/{warehouse_id}", payload, headers)

    def resume_warehouse(self, warehouse_id, payload, headers):
        return self._request(
            "POST", f"/v1/warehouses/{warehouse_id}/resume", payload, headers
        )

    def suspend_warehouse(self, warehouse_id, headers):
        return self._request(
            "POST", f"/v1/warehouses/{warehouse_id}/suspend", {}, headers
        )

    def scale_warehouse(self, warehouse_id, payload, headers):
        return self._request(
            "POST", f"/v1/warehouses/{warehouse_id}/cluster-scaling", payload, headers
        )

    # --- warehouse sessions ---
    def create_session(self, payload, headers):
        return self._request("POST", "/v1/warehouse-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request(
            "GET", "/v1/warehouse-sessions", headers=headers, params=params
        )

    def get_session(self, session_id, headers):
        return self._request(
            "GET", f"/v1/warehouse-sessions/{session_id}", headers=headers
        )

    def close_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/v1/warehouse-sessions/{session_id}/close", payload, headers
        )

    # --- capacity contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/v1/capacity-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request(
            "GET", "/v1/capacity-contracts", headers=headers, params=params
        )

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/v1/capacity-contracts/{contract_id}", headers=headers
        )

    def activate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/v1/capacity-contracts/{contract_id}/activate", payload, headers
        )

    def renew_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/v1/capacity-contracts/{contract_id}/renew", payload, headers
        )

    def close_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/v1/capacity-contracts/{contract_id}/close", payload, headers
        )

    # --- credit drawdowns ---
    def create_drawdown(self, payload, headers):
        return self._request("POST", "/v1/credit-drawdowns", payload, headers)

    def list_drawdowns(self, headers, params=None):
        return self._request(
            "GET", "/v1/credit-drawdowns", headers=headers, params=params
        )

    def get_drawdown(self, drawdown_id, headers):
        return self._request(
            "GET", f"/v1/credit-drawdowns/{drawdown_id}", headers=headers
        )

    def reverse_drawdown(self, drawdown_id, payload, headers):
        return self._request(
            "POST", f"/v1/credit-drawdowns/{drawdown_id}/reverse", payload, headers
        )

    # --- storage ---
    def create_storage_record(self, payload, headers):
        return self._request("POST", "/v1/storage-usage-records", payload, headers)

    def list_storage_records(self, headers, params=None):
        return self._request(
            "GET", "/v1/storage-usage-records", headers=headers, params=params
        )

    def get_storage_record(self, record_id, headers):
        return self._request(
            "GET", f"/v1/storage-usage-records/{record_id}", headers=headers
        )

    def get_storage_billing_summary(self, record_id, headers):
        return self._request(
            "GET", f"/v1/storage-usage-records/{record_id}/billing-summary",
            headers=headers,
        )

    def revise_storage_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/v1/storage-usage-records/{record_id}/revise", payload, headers
        )

    def finalize_storage_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/v1/storage-usage-records/{record_id}/finalize", payload, headers
        )

    # --- data shares ---
    def create_share(self, payload, headers):
        return self._request("POST", "/v1/data-shares", payload, headers)

    def list_shares(self, headers, params=None):
        return self._request("GET", "/v1/data-shares", headers=headers, params=params)

    def get_share(self, share_id, headers):
        return self._request("GET", f"/v1/data-shares/{share_id}", headers=headers)

    def patch_share(self, share_id, payload, headers):
        return self._request("PATCH", f"/v1/data-shares/{share_id}", payload, headers)

    def publish_share(self, share_id, headers):
        return self._request("POST", f"/v1/data-shares/{share_id}/publish", {}, headers)

    def suspend_share(self, share_id, headers):
        return self._request("POST", f"/v1/data-shares/{share_id}/suspend", {}, headers)

    def revoke_share(self, share_id, payload, headers):
        return self._request(
            "POST", f"/v1/data-shares/{share_id}/revoke", payload, headers
        )

    # --- share usage events ---
    def create_usage_event(self, share_id, payload, headers):
        return self._request(
            "POST", f"/v1/shares/{share_id}/usage-events", payload, headers
        )

    def list_share_usage_events(self, share_id, headers, params=None):
        return self._request(
            "GET", f"/v1/shares/{share_id}/usage-events", headers=headers, params=params
        )

    def list_usage_events(self, headers, params=None):
        return self._request(
            "GET", "/v1/share-usage-events", headers=headers, params=params
        )

    def get_usage_event(self, event_id, headers):
        return self._request(
            "GET", f"/v1/share-usage-events/{event_id}", headers=headers
        )

    # --- listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/v1/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/v1/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/v1/listings/{listing_id}", headers=headers)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/publish", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/withdraw", {}, headers)

    def get_provider_payout(self, listing_id, headers):
        return self._request(
            "GET", f"/v1/listings/{listing_id}/provider-payout", headers=headers
        )

    # --- paid share usage ---
    def create_paid_usage(self, payload, headers):
        return self._request("POST", "/v1/paid-share-usage", payload, headers)

    def list_paid_usage(self, headers, params=None):
        return self._request(
            "GET", "/v1/paid-share-usage", headers=headers, params=params
        )

    def get_paid_usage(self, paid_usage_id, headers):
        return self._request(
            "GET", f"/v1/paid-share-usage/{paid_usage_id}", headers=headers
        )

    def settle_paid_usage(self, paid_usage_id, headers):
        return self._request(
            "POST", f"/v1/paid-share-usage/{paid_usage_id}/settle", {}, headers
        )

    def settle_paid_usage_with_body(self, paid_usage_id, payload, headers):
        return self._request(
            "POST", f"/v1/paid-share-usage/{paid_usage_id}/settle", payload, headers
        )

    def dispute_paid_usage(self, paid_usage_id, payload, headers):
        return self._request(
            "POST", f"/v1/paid-share-usage/{paid_usage_id}/dispute", payload, headers
        )

    def resolve_paid_usage(self, paid_usage_id, headers):
        return self._request(
            "POST", f"/v1/paid-share-usage/{paid_usage_id}/resolve", {}, headers
        )

    # --- resource monitors ---
    def create_monitor(self, payload, headers):
        return self._request("POST", "/v1/resource-monitors", payload, headers)

    def list_monitors(self, headers, params=None):
        return self._request(
            "GET", "/v1/resource-monitors", headers=headers, params=params
        )

    def get_monitor(self, monitor_id, headers):
        return self._request(
            "GET", f"/v1/resource-monitors/{monitor_id}", headers=headers
        )

    def reset_monitor(self, monitor_id, headers):
        return self._request(
            "POST", f"/v1/resource-monitors/{monitor_id}/reset", {}, headers
        )

    # --- replication ---
    def create_replication(self, payload, headers):
        return self._request("POST", "/v1/replication-configurations", payload, headers)

    def list_replication(self, headers, params=None):
        return self._request(
            "GET", "/v1/replication-configurations", headers=headers, params=params
        )

    def get_replication(self, replication_id, headers):
        return self._request(
            "GET", f"/v1/replication-configurations/{replication_id}", headers=headers
        )

    def refresh_replication(self, replication_id, headers):
        return self._request(
            "POST", f"/v1/replication-configurations/{replication_id}/refresh",
            {}, headers,
        )


api_client = ApiClient()