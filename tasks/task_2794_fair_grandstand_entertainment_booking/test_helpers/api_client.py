"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the ``/grandstand`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/grandstand"


class ApiClient(GenericApiClient):
    """One method per row of the PRD endpoint table."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # -------------------------------------------------------- fair editions
    def create_fair_edition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fair-editions", payload, headers)

    def get_fair_edition(self, fair_edition_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fair-editions/{fair_edition_id}", headers=headers
        )

    def list_fair_editions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fair-editions", headers=headers, params=params
        )

    def get_buying_strategy_report(self, fair_edition_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/fair-editions/{fair_edition_id}/buying-strategy-report",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------------- stages
    def create_stage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stages", payload, headers)

    def get_stage(self, stage_id, headers):
        return self._request("GET", f"{PREFIX}/stages/{stage_id}", headers=headers)

    def list_stages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stages", headers=headers, params=params)

    # -------------------------------------------------------- talent agents
    def create_talent_agent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/talent-agents", payload, headers)

    def get_talent_agent(self, agent_id, headers):
        return self._request(
            "GET", f"{PREFIX}/talent-agents/{agent_id}", headers=headers
        )

    # -------------------------------------------------------------- artists
    def create_artist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"{PREFIX}/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/artists", headers=headers, params=params)

    # --------------------------------------------------------------- offers
    def create_offer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/offers", headers=headers, params=params)

    def list_offer_rounds(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/offers/{offer_id}/rounds", headers=headers, params=params
        )

    def send_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/send", payload or {}, headers
        )

    def counter_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/counter", payload, headers
        )

    def revise_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/revise", payload, headers
        )

    def accept_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/accept", payload or {}, headers
        )

    def decline_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/decline", payload or {}, headers
        )

    def withdraw_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/withdraw", payload or {}, headers
        )

    # --------------------------------------------------------- show bookings
    def get_show_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{PREFIX}/show-bookings/{booking_id}", headers=headers
        )

    def list_show_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/show-bookings", headers=headers, params=params
        )

    def reschedule_show_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/show-bookings/{booking_id}/reschedule", payload, headers
        )

    def announce_show_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/show-bookings/{booking_id}/announce", payload, headers
        )

    def mark_show_booking_performed(self, booking_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/show-bookings/{booking_id}/mark-performed",
            payload or {},
            headers,
        )

    # ---------------------------------------------------------- ticket scales
    def create_ticket_scale(self, booking_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/show-bookings/{booking_id}/ticket-scales",
            payload,
            headers,
        )

    def list_ticket_scales(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/show-bookings/{booking_id}/ticket-scales",
            headers=headers,
            params=params,
        )

    def get_ticket_scale(self, ticket_scale_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ticket-scales/{ticket_scale_id}", headers=headers
        )

    def create_sales_batch(self, ticket_scale_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/ticket-scales/{ticket_scale_id}/sales-batches",
            payload,
            headers,
        )

    def list_sales_batches(self, ticket_scale_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/ticket-scales/{ticket_scale_id}/sales-batches",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------- contingency actions
    def create_contingency_action(self, booking_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/show-bookings/{booking_id}/contingency-actions",
            payload,
            headers,
        )

    def list_contingency_actions(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/show-bookings/{booking_id}/contingency-actions",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- production advances
    def get_production_advance(self, advance_id, headers):
        return self._request(
            "GET", f"{PREFIX}/production-advances/{advance_id}", headers=headers
        )

    def list_production_advances(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/production-advances", headers=headers, params=params
        )

    def create_rider_item(self, advance_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/production-advances/{advance_id}/rider-items",
            payload,
            headers,
        )

    def list_rider_items(self, advance_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/production-advances/{advance_id}/rider-items",
            headers=headers,
            params=params,
        )

    def complete_production_advance(self, advance_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/production-advances/{advance_id}/complete",
            payload or {},
            headers,
        )

    def get_rider_item(self, rider_item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rider-items/{rider_item_id}", headers=headers
        )

    def rule_rider_item(self, rider_item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rider-items/{rider_item_id}/rule", payload, headers
        )

    # ------------------------------------------------------------- sponsors
    def create_sponsor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"{PREFIX}/sponsors/{sponsor_id}", headers=headers)

    # ------------------------------------------------ sponsorship activations
    def create_sponsorship_activation(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sponsorship-activations", payload, headers
        )

    def get_sponsorship_activation(self, activation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sponsorship-activations/{activation_id}", headers=headers
        )

    def list_sponsorship_activations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sponsorship-activations", headers=headers, params=params
        )

    def confirm_sponsorship_activation(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/sponsorship-activations/{activation_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_sponsorship_activation(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/sponsorship-activations/{activation_id}/cancel",
            payload or {},
            headers,
        )

    # ---------------------------------------------------------- settlements
    def create_settlement(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/show-bookings/{booking_id}/settlements", payload, headers
        )

    def get_settlement_preview(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/show-bookings/{booking_id}/settlement-preview",
            headers=headers,
            params=params,
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlements", headers=headers, params=params
        )

    def submit_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/submit", payload or {}, headers
        )

    def approve_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/settlements/{settlement_id}/approve",
            payload or {},
            headers,
        )

    def reject_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/reject", payload, headers
        )


api_client = ApiClient()
