"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the `/pipeline` prefix except the logical-clock
control endpoint.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/pipeline"


class ApiClient(GenericApiClient):
    """Endpoint methods for the pipeline nomination & scheduling API."""

    # ---------------------------------------------------------------- clock
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------ terminals
    def create_terminal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/terminals", payload, headers)

    def create_inventory_adjustment(self, terminal_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/terminals/{terminal_id}/inventory-adjustments",
            payload,
            headers,
        )

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"{PREFIX}/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/terminals", headers=headers, params=params)

    # -------------------------------------------------------- product grades
    def create_product_grade(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-grades", payload, headers)

    def get_product_grade(self, grade_id, headers):
        return self._request(
            "GET", f"{PREFIX}/product-grades/{grade_id}", headers=headers
        )

    def list_product_grades(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/product-grades", headers=headers, params=params
        )

    # -------------------------------------------------------------- segments
    def create_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/segments", payload, headers)

    def change_proration_policy(self, segment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/segments/{segment_id}/proration-policy", payload, headers
        )

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"{PREFIX}/segments/{segment_id}", headers=headers)

    def list_segments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/segments", headers=headers, params=params)

    # -------------------------------------------------------------- shippers
    def create_shipper(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shippers", payload, headers)

    def suspend_shipper(self, shipper_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shippers/{shipper_id}/suspend", payload, headers
        )

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"{PREFIX}/shippers/{shipper_id}", headers=headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shippers", headers=headers, params=params)

    # ------------------------------------------------------ shipping history
    def create_shipping_history(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shipping-history", payload, headers)

    def get_shipping_history(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/shipping-history/{record_id}", headers=headers
        )

    def list_shipping_history(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shipping-history", headers=headers, params=params
        )

    # --------------------------------------------------------------- tariffs
    def create_tariff(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tariffs", payload, headers)

    def activate_tariff(self, tariff_id, headers):
        return self._request(
            "POST", f"{PREFIX}/tariffs/{tariff_id}/activate", {}, headers
        )

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"{PREFIX}/tariffs/{tariff_id}", headers=headers)

    def list_tariffs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tariffs", headers=headers, params=params)

    # ---------------------------------------------------------------- cycles
    def create_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles", payload, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/close", {}, headers)

    def prorate_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/prorate", {}, headers)

    def build_schedule(self, cycle_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/build-schedule", {}, headers
        )

    def publish_schedule(self, cycle_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/publish-schedule", {}, headers
        )

    def settle_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/settle", payload, headers
        )

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cycles", headers=headers, params=params)

    # ----------------------------------------------------------- nominations
    def create_nomination(self, payload, headers):
        return self._request("POST", f"{PREFIX}/nominations", payload, headers)

    def withdraw_nomination(self, nomination_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nominations/{nomination_id}/withdraw", {}, headers
        )

    def request_revision(self, nomination_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nominations/{nomination_id}/request-revision", {}, headers
        )

    def resubmit_nomination(self, nomination_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/nominations/{nomination_id}/resubmit", payload, headers
        )

    def get_nomination(self, nomination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/nominations/{nomination_id}", headers=headers
        )

    def list_nominations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/nominations", headers=headers, params=params
        )

    # --------------------------------------------------------- batch tickets
    def inject_batch(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/batch-tickets/{ticket_id}/inject", payload, headers
        )

    def deliver_batch(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/batch-tickets/{ticket_id}/deliver", payload, headers
        )

    def cancel_batch(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/batch-tickets/{ticket_id}/cancel", payload, headers
        )

    def reschedule_window(self, ticket_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/batch-tickets/{ticket_id}/reschedule-window",
            payload,
            headers,
        )

    def get_batch_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"{PREFIX}/batch-tickets/{ticket_id}", headers=headers
        )

    def list_batch_tickets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/batch-tickets", headers=headers, params=params
        )

    # ---------------------------------------------------- maintenance events
    def create_maintenance_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-events", payload, headers)

    def notify_maintenance_event(self, event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-events/{event_id}/notify", {}, headers
        )

    def start_maintenance_event(self, event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-events/{event_id}/start", {}, headers
        )

    def complete_maintenance_event(self, event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-events/{event_id}/complete", {}, headers
        )

    def get_maintenance_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/maintenance-events/{event_id}", headers=headers
        )

    def list_maintenance_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/maintenance-events", headers=headers, params=params
        )

    # ----------------------------------------------------------- settlements
    def certify_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/certify", {}, headers
        )

    def invoice_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/invoice", payload, headers
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlements", headers=headers, params=params
        )


api_client = ApiClient()
