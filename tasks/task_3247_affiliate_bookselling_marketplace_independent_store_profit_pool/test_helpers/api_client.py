"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/bookshop/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ---- publishers / books ----------------------------------------------
    def create_publisher(self, payload, headers):
        return self._request("POST", "/bookshop/publishers", payload, headers)

    def get_publisher(self, publisher_id, headers):
        return self._request(
            "GET", f"/bookshop/publishers/{publisher_id}", headers=headers
        )

    def list_publisher_books(self, publisher_id, headers, params=None):
        return self._request(
            "GET",
            f"/bookshop/publishers/{publisher_id}/books",
            headers=headers,
            params=params,
        )

    def create_book(self, payload, headers):
        return self._request("POST", "/bookshop/books", payload, headers)

    # ---- stores ------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/bookshop/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/bookshop/stores/{store_id}", headers=headers)

    def list_store_lists(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/bookshop/stores/{store_id}/lists", headers=headers, params=params
        )

    def store_action(self, store_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/stores/{store_id}/actions", payload, headers
        )

    # ---- partners ----------------------------------------------------------
    def create_partner(self, payload, headers):
        return self._request("POST", "/bookshop/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request(
            "GET", f"/bookshop/partners/{partner_id}", headers=headers
        )

    def partner_action(self, partner_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/partners/{partner_id}/actions", payload, headers
        )

    # ---- lists ---------------------------------------------------------------
    def create_list(self, payload, headers):
        return self._request("POST", "/bookshop/lists", payload, headers)

    def list_action(self, list_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/lists/{list_id}/actions", payload, headers
        )

    # ---- orders ---------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/bookshop/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/bookshop/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/bookshop/orders", headers=headers, params=params)

    def order_action(self, order_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/orders/{order_id}/actions", payload, headers
        )

    def create_return(self, order_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/orders/{order_id}/returns", payload, headers
        )

    def list_order_returns(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/bookshop/orders/{order_id}/returns",
            headers=headers,
            params=params,
        )

    def list_order_tickets(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/bookshop/orders/{order_id}/tickets",
            headers=headers,
            params=params,
        )

    # ---- returns ---------------------------------------------------------------
    def return_action(self, return_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/returns/{return_id}/actions", payload, headers
        )

    # ---- ledger ------------------------------------------------------------------
    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/bookshop/ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/bookshop/ledger-entries", headers=headers, params=params
        )

    # ---- pool distributions ---------------------------------------------------------
    def create_pool_distribution(self, payload, headers):
        return self._request("POST", "/bookshop/pool-distributions", payload, headers)

    def pool_action(self, dist_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/pool-distributions/{dist_id}/actions", payload, headers
        )

    # ---- payouts ----------------------------------------------------------------------
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/bookshop/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/bookshop/payouts", headers=headers, params=params)

    def payout_action(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/payouts/{payout_id}/actions", payload, headers
        )

    # ---- tickets ------------------------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", "/bookshop/tickets", payload, headers)

    def ticket_action(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/bookshop/tickets/{ticket_id}/actions", payload, headers
        )

    # ---- promotions ------------------------------------------------------------------------
    def create_promotion(self, payload, headers):
        return self._request("POST", "/bookshop/promotions", payload, headers)


api_client = ApiClient()
