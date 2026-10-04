"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test controls ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def hedge_regression_sweep(self, payload, headers):
        return self._request("POST", "/fare/hedge-regression-sweeps", payload, headers)

    # ─── Routes ─────────────────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/fare/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/fare/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/fare/routes/{route_id}", headers=headers)

    def update_route(self, route_id, payload, headers):
        return self._request("PATCH", f"/fare/routes/{route_id}", payload, headers)

    def transition_route_posture(self, route_id, payload, headers):
        return self._request(
            "POST", f"/fare/routes/{route_id}/posture-transitions", payload, headers
        )

    def list_route_hedging_positions(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/fare/routes/{route_id}/hedging-positions", headers=headers, params=params
        )

    # ─── Itineraries ────────────────────────────────────────────────────────
    def create_itinerary(self, payload, headers):
        return self._request("POST", "/fare/itineraries", payload, headers)

    def list_itineraries(self, headers, params=None):
        return self._request("GET", "/fare/itineraries", headers=headers, params=params)

    def get_itinerary(self, itinerary_id, headers):
        return self._request("GET", f"/fare/itineraries/{itinerary_id}", headers=headers)

    def arm_watch(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/fare/itineraries/{itinerary_id}/watch-subscription", payload, headers
        )

    def book_itinerary(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/fare/itineraries/{itinerary_id}/bookings", payload, headers
        )

    def cancel_itinerary(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/fare/itineraries/{itinerary_id}/cancellations", payload, headers
        )

    # ─── Price observations ─────────────────────────────────────────────────
    def create_observation(self, payload, headers):
        return self._request("POST", "/fare/price-observations", payload, headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/fare/price-observations", headers=headers, params=params)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/fare/price-observations/{observation_id}", headers=headers)

    # ─── Demand curves ──────────────────────────────────────────────────────
    def publish_curve(self, payload, headers):
        return self._request("POST", "/fare/demand-curves", payload, headers)

    def list_curves(self, headers, params=None):
        return self._request("GET", "/fare/demand-curves", headers=headers, params=params)

    def get_curve(self, curve_id, headers):
        return self._request("GET", f"/fare/demand-curves/{curve_id}", headers=headers)

    # ─── Watches ────────────────────────────────────────────────────────────
    def list_watches(self, headers, params=None):
        return self._request("GET", "/fare/watch-subscriptions", headers=headers, params=params)

    def get_watch(self, watch_id, headers):
        return self._request("GET", f"/fare/watch-subscriptions/{watch_id}", headers=headers)

    def evaluate_watch(self, watch_id, payload, headers):
        return self._request(
            "POST", f"/fare/watch-subscriptions/{watch_id}/notifications", payload, headers
        )

    def confirm_watch(self, watch_id, payload, headers):
        return self._request(
            "POST", f"/fare/watch-subscriptions/{watch_id}/confirmations", payload, headers
        )

    # ─── Price freezes ──────────────────────────────────────────────────────
    def open_freeze(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/fare/itineraries/{itinerary_id}/price-freezes", payload, headers
        )

    def open_freeze_flat(self, payload, headers):
        return self._request("POST", "/fare/price-freezes", payload, headers)

    def list_freezes(self, headers, params=None):
        return self._request("GET", "/fare/price-freezes", headers=headers, params=params)

    def get_freeze(self, freeze_id, headers):
        return self._request("GET", f"/fare/price-freezes/{freeze_id}", headers=headers)

    def list_itinerary_freezes(self, itinerary_id, headers, params=None):
        return self._request(
            "GET", f"/fare/itineraries/{itinerary_id}/price-freezes", headers=headers, params=params
        )

    def activate_freeze(self, freeze_id, payload, headers):
        return self._request(
            "POST", f"/fare/price-freezes/{freeze_id}/activations", payload, headers
        )

    def expire_freeze(self, freeze_id, payload, headers):
        return self._request(
            "POST", f"/fare/price-freezes/{freeze_id}/expirations", payload, headers
        )

    def convert_freeze(self, freeze_id, payload, headers):
        return self._request(
            "POST", f"/fare/price-freezes/{freeze_id}/conversions", payload, headers
        )

    def cancel_freeze(self, freeze_id, payload, headers):
        return self._request(
            "POST", f"/fare/price-freezes/{freeze_id}/cancellations", payload, headers
        )

    def reinstate_freeze(self, freeze_id, payload, headers):
        return self._request(
            "POST", f"/fare/price-freezes/{freeze_id}/reinstatements", payload, headers
        )

    # ─── Protections ────────────────────────────────────────────────────────
    def quote_protection(self, payload, headers):
        return self._request("POST", "/fare/protections", payload, headers)

    def quote_protection_for_itinerary(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/fare/itineraries/{itinerary_id}/protections", payload, headers
        )

    def list_protections(self, headers, params=None):
        return self._request("GET", "/fare/protections", headers=headers, params=params)

    def get_protection(self, protection_id, headers):
        return self._request("GET", f"/fare/protections/{protection_id}", headers=headers)

    def requote_protection(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/quotes", payload, headers
        )

    def activate_protection(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/activations", payload, headers
        )

    def cancel_protected(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/cancellations", payload, headers
        )

    def reinstate_protection(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/reinstatements", payload, headers
        )

    def file_change_event_for_protection(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/change-events", payload, headers
        )

    def terminate_protection(self, protection_id, payload, headers):
        return self._request(
            "POST", f"/fare/protections/{protection_id}/terminations", payload, headers
        )

    # ─── Claims ─────────────────────────────────────────────────────────────
    def file_claim(self, payload, headers):
        return self._request("POST", "/fare/claims", payload, headers)

    def file_claim_for_freeze(self, freeze_id, payload, headers):
        return self._request("POST", f"/fare/price-freezes/{freeze_id}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/fare/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/fare/claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/reviews", payload, headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/approvals", payload, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/rejections", payload, headers)

    def withdraw_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/withdrawals", payload, headers)

    def reconsider_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/reconsiderations", payload, headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fare/claims/{claim_id}/settlements", payload, headers)

    # ─── Change events ──────────────────────────────────────────────────────
    def file_change_event(self, payload, headers):
        return self._request("POST", "/fare/change-events", payload, headers)

    def list_change_events(self, headers, params=None):
        return self._request("GET", "/fare/change-events", headers=headers, params=params)

    def get_change_event(self, change_event_id, headers):
        return self._request("GET", f"/fare/change-events/{change_event_id}", headers=headers)

    def select_option(self, change_event_id, payload, headers):
        return self._request(
            "POST", f"/fare/change-events/{change_event_id}/selections", payload, headers
        )

    def settle_change_event(self, change_event_id, payload, headers):
        return self._request(
            "POST", f"/fare/change-events/{change_event_id}/settlements", payload, headers
        )

    def cancel_change_event(self, change_event_id, payload, headers):
        return self._request(
            "POST", f"/fare/change-events/{change_event_id}/cancellations", payload, headers
        )

    # ─── Rebooking options ──────────────────────────────────────────────────
    def offer_option(self, payload, headers):
        return self._request("POST", "/fare/rebooking-options", payload, headers)

    def list_options(self, headers, params=None):
        return self._request("GET", "/fare/rebooking-options", headers=headers, params=params)

    def get_option(self, option_id, headers):
        return self._request("GET", f"/fare/rebooking-options/{option_id}", headers=headers)

    def list_change_event_options(self, change_event_id, headers, params=None):
        return self._request(
            "GET",
            f"/fare/change-events/{change_event_id}/rebooking-options",
            headers=headers,
            params=params,
        )

    def accept_option(self, option_id, payload, headers):
        return self._request(
            "POST", f"/fare/rebooking-options/{option_id}/acceptances", payload, headers
        )

    def revert_option_hold(self, option_id, payload, headers):
        return self._request(
            "POST", f"/fare/rebooking-options/{option_id}/hold-reversions", payload, headers
        )

    # ─── Destination options ────────────────────────────────────────────────
    def offer_destination_option(self, payload, headers):
        return self._request("POST", "/fare/destination-options", payload, headers)

    def list_destination_options(self, headers, params=None):
        return self._request("GET", "/fare/destination-options", headers=headers, params=params)

    def get_destination_option(self, destination_option_id, headers):
        return self._request(
            "GET", f"/fare/destination-options/{destination_option_id}", headers=headers
        )

    def bind_destination_option(self, destination_option_id, payload, headers):
        return self._request(
            "POST", f"/fare/destination-options/{destination_option_id}/selections", payload, headers
        )

    def release_destination_option(self, destination_option_id, payload, headers):
        return self._request(
            "POST", f"/fare/destination-options/{destination_option_id}/releases", payload, headers
        )

    # ─── Payments ───────────────────────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/fare/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/fare/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/fare/payments/{payment_id}", headers=headers)

    def list_freeze_payments(self, freeze_id, headers, params=None):
        return self._request(
            "GET", f"/fare/price-freezes/{freeze_id}/payments", headers=headers, params=params
        )

    def capture_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/fare/payments/{payment_id}/captures", payload, headers)

    def refund_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/fare/payments/{payment_id}/refunds", payload, headers)

    # ─── Hedging positions ──────────────────────────────────────────────────
    def open_hedging_position(self, payload, headers):
        return self._request("POST", "/fare/hedging-positions", payload, headers)

    def list_hedging_positions(self, headers, params=None):
        return self._request("GET", "/fare/hedging-positions", headers=headers, params=params)

    def get_hedging_position(self, position_id, headers):
        return self._request("GET", f"/fare/hedging-positions/{position_id}", headers=headers)

    def mark_hedging_position(self, position_id, payload, headers):
        return self._request(
            "POST", f"/fare/hedging-positions/{position_id}/marks", payload, headers
        )

    def settle_hedging_position(self, position_id, payload, headers):
        return self._request(
            "POST", f"/fare/hedging-positions/{position_id}/settlements", payload, headers
        )

    # ─── Risk pools ─────────────────────────────────────────────────────────
    def open_risk_pool(self, payload, headers):
        return self._request("POST", "/fare/risk-pools", payload, headers)

    def list_risk_pools(self, headers, params=None):
        return self._request("GET", "/fare/risk-pools", headers=headers, params=params)

    def get_risk_pool(self, pool_id, headers):
        return self._request("GET", f"/fare/risk-pools/{pool_id}", headers=headers)


api_client = ApiClient()