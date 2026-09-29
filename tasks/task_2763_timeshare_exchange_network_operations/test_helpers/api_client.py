"""API client — one method per endpoint of the Timeshare Exchange Network API.

Every path is mounted under ``/exchange-network`` (PRD §4).
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/exchange-network"


class ApiClient(GenericApiClient):
    """Endpoint methods for the exchange-network surface."""

    # ---------------------------------------------------------------- tiers
    def create_membership_tier(self, payload, headers):
        return self._request("POST", f"{BASE}/membership-tiers", payload, headers)

    def get_membership_tier(self, tier_id, headers):
        return self._request(
            "GET", f"{BASE}/membership-tiers/{tier_id}", headers=headers
        )

    def list_membership_tiers(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/membership-tiers", headers=headers, params=params
        )

    # -------------------------------------------------------------- resorts
    def create_resort(self, payload, headers):
        return self._request("POST", f"{BASE}/resorts", payload, headers)

    def get_resort(self, resort_id, headers):
        return self._request("GET", f"{BASE}/resorts/{resort_id}", headers=headers)

    def list_resorts(self, headers, params=None):
        return self._request("GET", f"{BASE}/resorts", headers=headers, params=params)

    def update_resort(self, resort_id, payload, headers):
        return self._request("PATCH", f"{BASE}/resorts/{resort_id}", payload, headers)

    def grant_resort_affiliation(self, resort_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/resorts/{resort_id}/affiliation", payload or {}, headers
        )

    def change_resort_status(self, resort_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/resorts/{resort_id}/status-changes", payload, headers
        )

    def get_resort_compliance(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/resorts/{resort_id}/compliance", headers=headers,
            params=params,
        )

    # --------------------------------------------------------- season bands
    def create_season_band(self, payload, headers):
        return self._request("POST", f"{BASE}/season-bands", payload, headers)

    def get_season_band(self, band_id, headers):
        return self._request("GET", f"{BASE}/season-bands/{band_id}", headers=headers)

    def list_season_bands(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/season-bands", headers=headers, params=params
        )

    # ------------------------------------------------------ quality reviews
    def create_quality_review(self, resort_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/resorts/{resort_id}/quality-reviews", payload, headers
        )

    def get_quality_review(self, review_id, headers):
        return self._request(
            "GET", f"{BASE}/resort-quality-reviews/{review_id}", headers=headers
        )

    def list_quality_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/resort-quality-reviews", headers=headers, params=params
        )

    # -------------------------------------------------------------- members
    def create_member(self, payload, headers):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{BASE}/members", headers=headers, params=params)

    def create_dues_payment(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/dues-payments", payload, headers
        )

    def change_member_status(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/status-changes", payload, headers
        )

    def change_member_tier(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/tier-changes", payload, headers
        )

    # -------------------------------------------------------------- ledger
    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{BASE}/ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/ledger-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------- deposits
    def create_deposit(self, payload, headers):
        return self._request("POST", f"{BASE}/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"{BASE}/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", f"{BASE}/deposits", headers=headers, params=params)

    def create_deposit_extension(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/deposits/{deposit_id}/extensions", payload, headers
        )

    def withdraw_deposit(self, deposit_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/deposits/{deposit_id}/withdrawal", payload or {}, headers
        )

    def get_deposit_valuation(self, deposit_id, headers):
        return self._request(
            "GET", f"{BASE}/deposits/{deposit_id}/valuation", headers=headers
        )

    # ---------------------------------------------------- exchange requests
    def create_exchange_request(self, payload, headers):
        return self._request("POST", f"{BASE}/exchange-requests", payload, headers)

    def get_exchange_request(self, request_id, headers):
        return self._request(
            "GET", f"{BASE}/exchange-requests/{request_id}", headers=headers
        )

    def list_exchange_requests(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/exchange-requests", headers=headers, params=params
        )

    def attach_request_funding(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/exchange-requests/{request_id}/funding", payload, headers
        )

    def decline_match(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/exchange-requests/{request_id}/decline",
            payload or {}, headers,
        )

    def cancel_exchange_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/exchange-requests/{request_id}/cancellation",
            payload or {}, headers,
        )

    # -------------------------------------------------------- confirmations
    def create_confirmation(self, payload, headers):
        return self._request("POST", f"{BASE}/confirmations", payload, headers)

    def get_confirmation(self, confirmation_id, headers):
        return self._request(
            "GET", f"{BASE}/confirmations/{confirmation_id}", headers=headers
        )

    def list_confirmations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/confirmations", headers=headers, params=params
        )

    def cancel_confirmation(self, confirmation_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/confirmations/{confirmation_id}/cancellation",
            payload or {}, headers,
        )

    def reinstate_confirmation(self, confirmation_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/confirmations/{confirmation_id}/reinstatement",
            payload or {}, headers,
        )

    # -------------------------------------------------------- matching runs
    def create_matching_run(self, payload, headers):
        return self._request("POST", f"{BASE}/matching-runs", payload, headers)

    def get_matching_run(self, run_id, headers):
        return self._request("GET", f"{BASE}/matching-runs/{run_id}", headers=headers)

    def list_matching_runs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/matching-runs", headers=headers, params=params
        )

    # ------------------------------------------------------- getaway offers
    def get_getaway_offer(self, offer_id, headers):
        return self._request(
            "GET", f"{BASE}/getaway-offers/{offer_id}", headers=headers
        )

    def list_getaway_offers(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/getaway-offers", headers=headers, params=params
        )

    def book_getaway_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/getaway-offers/{offer_id}/bookings", payload, headers
        )

    def withdraw_getaway_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/getaway-offers/{offer_id}/withdrawal",
            payload or {}, headers,
        )

    # ------------------------------------------------------------- disputes
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{BASE}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{BASE}/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{BASE}/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/disputes/{dispute_id}/review", payload or {}, headers
        )

    def request_dispute_info(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disputes/{dispute_id}/info-requests", payload, headers
        )

    def respond_to_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disputes/{dispute_id}/responses", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disputes/{dispute_id}/resolution", payload, headers
        )

    def withdraw_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/disputes/{dispute_id}/withdrawal", payload or {}, headers
        )

    # ---------------------------------------------------------- logical clock
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
