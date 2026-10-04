"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- stores --------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ---- season campaigns ----------------------------------------------------
    def create_season_campaign(self, payload, headers):
        return self._request("POST", "/season-campaigns", payload, headers)

    def list_season_campaigns(self, headers, params=None):
        return self._request("GET", "/season-campaigns", headers=headers, params=params)

    def get_season_campaign(self, campaign_id, headers):
        return self._request("GET", f"/season-campaigns/{campaign_id}", headers=headers)

    def begin_teardown(self, campaign_id, headers):
        return self._request(
            "POST", f"/season-campaigns/{campaign_id}/begin-teardown", {}, headers
        )

    def complete_reset(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/season-campaigns/{campaign_id}/complete-reset", payload, headers
        )

    def verify_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/season-campaigns/{campaign_id}/verify", payload, headers
        )

    def activate_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/season-campaigns/{campaign_id}/activate", payload, headers
        )

    def cancel_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/season-campaigns/{campaign_id}/cancel", {}, headers
        )

    # ---- staging bays ---------------------------------------------------------
    def create_staging_bay(self, payload, headers):
        return self._request("POST", "/staging-bays", payload, headers)

    def list_staging_bays(self, headers, params=None):
        return self._request("GET", "/staging-bays", headers=headers, params=params)

    def get_staging_bay(self, bay_id, headers):
        return self._request("GET", f"/staging-bays/{bay_id}", headers=headers)

    def set_staging_bay_status(self, bay_id, payload, headers):
        return self._request(
            "POST", f"/staging-bays/{bay_id}/set-status", payload, headers
        )

    # ---- hatchery schedules ---------------------------------------------------
    def create_hatchery_schedule(self, payload, headers):
        return self._request("POST", "/hatchery-schedules", payload, headers)

    def list_hatchery_schedules(self, headers, params=None):
        return self._request("GET", "/hatchery-schedules", headers=headers, params=params)

    def get_hatchery_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/hatchery-schedules/{schedule_id}", headers=headers
        )

    def publish_hatchery_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/hatchery-schedules/{schedule_id}/publish", {}, headers
        )

    def close_hatchery_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/hatchery-schedules/{schedule_id}/close", payload, headers
        )

    # ---- livestock lots -------------------------------------------------------
    def create_livestock_lot(self, payload, headers):
        return self._request("POST", "/livestock-lots", payload, headers)

    def list_livestock_lots(self, headers, params=None):
        return self._request("GET", "/livestock-lots", headers=headers, params=params)

    def get_livestock_lot(self, lot_id, headers):
        return self._request("GET", f"/livestock-lots/{lot_id}", headers=headers)

    def open_lot_sale(self, lot_id, headers):
        return self._request("POST", f"/livestock-lots/{lot_id}/open-sale", {}, headers)

    def close_lot_sale(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/livestock-lots/{lot_id}/close-sale", payload, headers
        )

    def create_care_log(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/livestock-lots/{lot_id}/care-logs", payload, headers
        )

    def list_care_logs(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/livestock-lots/{lot_id}/care-logs", headers=headers, params=params
        )

    # ---- chick orders ---------------------------------------------------------
    def create_chick_order(self, payload, headers):
        return self._request("POST", "/chick-orders", payload, headers)

    def list_chick_orders(self, headers, params=None):
        return self._request("GET", "/chick-orders", headers=headers, params=params)

    def get_chick_order(self, order_id, headers):
        return self._request("GET", f"/chick-orders/{order_id}", headers=headers)

    def verify_brooder(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chick-orders/{order_id}/verify-brooder", payload, headers
        )

    def fulfill_chick_order(self, order_id, headers):
        return self._request("POST", f"/chick-orders/{order_id}/fulfill", {}, headers)

    def cancel_chick_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chick-orders/{order_id}/cancel", payload, headers
        )

    def create_mortality_claim(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chick-orders/{order_id}/mortality-claims", payload, headers
        )

    def review_mortality_claim(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chick-orders/{order_id}/review-mortality-claim", payload, headers
        )

    # ---- weighted sales -------------------------------------------------------
    def create_weighted_sale(self, payload, headers):
        return self._request("POST", "/weighted-sales", payload, headers)

    def list_weighted_sales(self, headers, params=None):
        return self._request("GET", "/weighted-sales", headers=headers, params=params)

    def get_weighted_sale(self, sale_id, headers):
        return self._request("GET", f"/weighted-sales/{sale_id}", headers=headers)

    def finalize_weighted_sale(self, sale_id, payload, headers):
        return self._request(
            "POST", f"/weighted-sales/{sale_id}/finalize", payload, headers
        )

    def void_weighted_sale(self, sale_id, headers):
        return self._request("POST", f"/weighted-sales/{sale_id}/void", {}, headers)

    # ---- loyalty accounts -----------------------------------------------------
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers)

    def list_loyalty_accounts(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", headers=headers, params=params)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    def lookup_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts/lookup", payload, headers)

    def set_loyalty_account_status(self, account_id, payload, headers):
        return self._request(
            "POST", f"/loyalty-accounts/{account_id}/set-status", payload, headers
        )

    def create_ledger_entry(self, account_id, payload, headers):
        return self._request(
            "POST", f"/loyalty-accounts/{account_id}/ledger-entries", payload, headers
        )

    def list_account_ledger_entries(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/loyalty-accounts/{account_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def get_loyalty_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/loyalty-ledger-entries/{entry_id}", headers=headers
        )

    def list_loyalty_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/loyalty-ledger-entries", headers=headers, params=params
        )

    def get_loyalty_offers(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/loyalty-accounts/{account_id}/offers", headers=headers, params=params
        )

    # ---- pickup orders --------------------------------------------------------
    def create_pickup_order(self, payload, headers):
        return self._request("POST", "/pickup-orders", payload, headers)

    def list_pickup_orders(self, headers, params=None):
        return self._request("GET", "/pickup-orders", headers=headers, params=params)

    def get_pickup_order(self, pickup_id, headers):
        return self._request("GET", f"/pickup-orders/{pickup_id}", headers=headers)

    def stage_pickup_order(self, pickup_id, headers):
        return self._request("POST", f"/pickup-orders/{pickup_id}/stage", {}, headers)

    def mark_pickup_ready(self, pickup_id, headers):
        return self._request(
            "POST", f"/pickup-orders/{pickup_id}/mark-ready", {}, headers
        )

    def request_loadout(self, pickup_id, headers):
        return self._request(
            "POST", f"/pickup-orders/{pickup_id}/request-loadout", {}, headers
        )

    def complete_loadout(self, pickup_id, headers):
        return self._request(
            "POST", f"/pickup-orders/{pickup_id}/complete-loadout", {}, headers
        )

    def complete_pickup_order(self, pickup_id, headers):
        return self._request("POST", f"/pickup-orders/{pickup_id}/complete", {}, headers)

    def cancel_pickup_order(self, pickup_id, headers):
        return self._request("POST", f"/pickup-orders/{pickup_id}/cancel", {}, headers)

    # ---- service events -------------------------------------------------------
    def create_service_event(self, payload, headers):
        return self._request("POST", "/service-events", payload, headers)

    def list_service_events(self, headers, params=None):
        return self._request("GET", "/service-events", headers=headers, params=params)

    def get_service_event(self, event_id, headers):
        return self._request("GET", f"/service-events/{event_id}", headers=headers)

    def publish_service_event(self, event_id, headers):
        return self._request(
            "POST", f"/service-events/{event_id}/publish", {}, headers
        )

    def cancel_service_event(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/cancel", {}, headers)

    # ---- event bookings -------------------------------------------------------
    def create_event_booking(self, payload, headers):
        return self._request("POST", "/event-bookings", payload, headers)

    def list_event_bookings(self, headers, params=None):
        return self._request("GET", "/event-bookings", headers=headers, params=params)

    def get_event_booking(self, booking_id, headers):
        return self._request("GET", f"/event-bookings/{booking_id}", headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/check-in", {}, headers
        )

    def complete_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/complete", {}, headers
        )

    def mark_booking_no_show(self, booking_id, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/mark-no-show", {}, headers
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/event-bookings/{booking_id}/cancel", {}, headers)

    # Generic verbs: the framework's GenericApiClient exposes get/post/put/
    # delete but not patch; add it so negative-append-only probes can exercise
    # PATCH as well (PRD §2.4 declares CareLogEntry / LoyaltyLedgerEntry
    # append-only — no update path exists for them).
    def patch(self, path, json=None, headers=None, **kwargs):
        return self._request("PATCH", path, payload=json, headers=headers)


api_client = ApiClient()
