"""API client: one method per endpoint the service floor exposes.

Every path is mounted under the /service-floor prefix except the logical clock.
GET requests pass their payload as query parameters; POST requests pass theirs as
a JSON body (the base class handles the split).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/service-floor"


class ApiClient(GenericApiClient):

    # --- Logical clock --------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Venue ----------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/venues", params=params, headers=headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", headers=headers)

    def run_ops(self, venue_id, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/run_ops", {}, headers)

    def get_cost_report(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}/cost-report",
                             headers=headers)

    def get_protein_cost_report(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}/protein-cost-report",
                             headers=headers)

    def retire_tier(self, venue_id, tier_id, headers):
        return self._request("POST",
                             f"{PREFIX}/venues/{venue_id}/tiers/{tier_id}/retire",
                             {}, headers)

    def maintenance_release(self, venue_id, table_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/venues/{venue_id}/tables/{table_id}/maintenance-release",
                             payload, headers)

    # --- Party ----------------------------------------------------------------
    def create_party(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parties", payload, headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parties", params=params, headers=headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"{PREFIX}/parties/{party_id}", headers=headers)

    # --- TableTier ------------------------------------------------------------
    def create_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tiers", params=params, headers=headers)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"{PREFIX}/tiers/{tier_id}", headers=headers)

    # --- GrillTable -----------------------------------------------------------
    def create_table(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tables", payload, headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tables", params=params, headers=headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"{PREFIX}/tables/{table_id}", headers=headers)

    def post_table_event(self, table_id, payload, headers):
        return self._request("POST", f"{PREFIX}/tables/{table_id}/events", payload, headers)

    # --- Reservation ----------------------------------------------------------
    def create_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations", params=params, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}",
                             headers=headers)

    def grant_hold(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/holds",
                             payload, headers)

    def seat_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/seat",
                             {}, headers)

    def post_reservation_event(self, reservation_id, event_type, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/events",
                             {"event_type": event_type}, headers)

    def change_party_size(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/party-size",
                             payload, headers)

    def close_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/close",
                             payload, headers)

    def reopen_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/reopen",
                             payload, headers)

    # --- TableSeating ---------------------------------------------------------
    def list_seatings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seatings", params=params, headers=headers)

    def get_seating(self, seating_id, headers):
        return self._request("GET", f"{PREFIX}/seatings/{seating_id}", headers=headers)

    def extend_seating(self, seating_id, extension_minutes, headers):
        return self._request("POST", f"{PREFIX}/seatings/{seating_id}/extend",
                             {"extension_minutes": extension_minutes}, headers)

    # --- ChefAssignment -------------------------------------------------------
    def create_chef(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chefs", payload, headers)

    def list_chefs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chefs", params=params, headers=headers)

    def get_chef(self, chef_id, headers):
        return self._request("GET", f"{PREFIX}/chefs/{chef_id}", headers=headers)

    def post_chef_event(self, chef_id, payload, headers):
        return self._request("POST", f"{PREFIX}/chefs/{chef_id}/events", payload, headers)

    # --- ShowPerformance ------------------------------------------------------
    def list_shows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shows", params=params, headers=headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"{PREFIX}/shows/{show_id}", headers=headers)

    def post_show_event(self, show_id, event_type, headers):
        return self._request("POST", f"{PREFIX}/shows/{show_id}/events",
                             {"event_type": event_type}, headers)

    # --- MaintenanceWindow ----------------------------------------------------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/maintenance-windows",
                             params=params, headers=headers)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/maintenance-windows/{window_id}",
                             headers=headers)

    def accept_maintenance_window(self, window_id, headers):
        return self._request("POST",
                             f"{PREFIX}/maintenance-windows/{window_id}/accept",
                             {}, headers)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST",
                             f"{PREFIX}/maintenance-windows/{window_id}/cancel",
                             {}, headers)

    def reopen_maintenance_window(self, window_id, headers):
        return self._request("POST",
                             f"{PREFIX}/maintenance-windows/{window_id}/reopen",
                             {}, headers)

    # --- SushiTicket ----------------------------------------------------------
    def create_sushi_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sushi-tickets", payload, headers)

    def list_sushi_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sushi-tickets", params=params,
                             headers=headers)

    def get_sushi_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/sushi-tickets/{ticket_id}",
                             headers=headers)

    def post_sushi_event(self, ticket_id, event_type, headers):
        return self._request("POST", f"{PREFIX}/sushi-tickets/{ticket_id}/events",
                             {"event_type": event_type}, headers)

    # --- VenueLedgerEntry -----------------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ledger-entries", params=params,
                             headers=headers)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/ledger-entries/{entry_id}",
                             headers=headers)

    def void_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/ledger-entries/{entry_id}/void",
                             {}, headers)

    # --- ProteinTicket --------------------------------------------------------
    def list_protein_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/protein-tickets", params=params,
                             headers=headers)

    def get_protein_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/protein-tickets/{ticket_id}",
                             headers=headers)

    def adjust_protein_variance(self, ticket_id, delta_grams, headers):
        return self._request("POST", f"{PREFIX}/protein-tickets/{ticket_id}/variance",
                             {"delta_grams": delta_grams}, headers)

    def post_protein_event(self, ticket_id, event_type, headers):
        return self._request("POST", f"{PREFIX}/protein-tickets/{ticket_id}/events",
                             {"event_type": event_type}, headers)


api_client = ApiClient()