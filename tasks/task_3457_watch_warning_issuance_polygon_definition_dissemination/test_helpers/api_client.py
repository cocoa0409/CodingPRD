"""API client: one method per endpoint of the Watch Warning Issuance API (PRD §4).

Every business path lives under the ``/alerts`` prefix. The two platform
test-driving capabilities -- the logical clock and the dissemination settle --
are mounted OUTSIDE that prefix (PRD §2.4: "mounted outside the ``/alerts`` path
prefix under which the rest of the API lives"), so ``set_clock`` and
``settle_record`` deliberately do not use the prefix constant.

Methods return the raw ``requests.Response`` so tests can assert on the status
code as well as the body.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Filters, Headers, JsonObject, ResourceId

ALERTS = "/alerts"


class ApiClient(GenericApiClient):
    """Typed wrapper over the watch/warning service's HTTP surface."""

    # ---------------------------------------------------------- forecast offices
    def create_office(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/offices", payload, headers)

    def get_office(self, office_id: ResourceId, headers: Headers):
        return self._request("GET", ALERTS + "/offices/" + str(office_id), None, headers)

    def list_office_zones(self, office_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", ALERTS + "/offices/" + str(office_id) + "/zones", None, headers, params=filters
        )

    def list_office_forecasters(self, office_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", ALERTS + "/offices/" + str(office_id) + "/forecasters", None, headers, params=filters
        )

    def list_office_neighbor_agreements(self, office_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", ALERTS + "/offices/" + str(office_id) + "/neighbor-agreements", None, headers, params=filters
        )

    def list_office_storm_events(self, office_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", ALERTS + "/offices/" + str(office_id) + "/storm-events", None, headers, params=filters
        )

    def list_office_verification_statistics(self, office_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET",
            ALERTS + "/offices/" + str(office_id) + "/verification-statistics",
            None,
            headers,
            params=filters,
        )

    # --------------------------------------------------------------- county zones
    def create_zone(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/zones", payload, headers)

    # --------------------------------------------------------- neighbor agreements
    def create_neighbor_agreement(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/neighbor-agreements", payload, headers)

    # ------------------------------------------------------------ alert channels
    def create_alert_channel(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/alert-channels", payload, headers)

    # --------------------------------------------------------------- forecasters
    def create_forecaster(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/forecasters", payload, headers)

    # -------------------------------------------------------------- storm events
    def create_storm_event(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/storm-events", payload, headers)

    def get_storm_event(self, storm_event_id: ResourceId, headers: Headers):
        return self._request("GET", ALERTS + "/storm-events/" + str(storm_event_id), None, headers)

    def update_storm_event(self, storm_event_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PUT", ALERTS + "/storm-events/" + str(storm_event_id), payload, headers)

    def dissipate_storm_event(self, storm_event_id: ResourceId, headers: Headers):
        return self._request(
            "POST", ALERTS + "/storm-events/" + str(storm_event_id) + "/dissipate", {}, headers
        )

    # ------------------------------------------------------------------- products
    def create_product(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/products", payload, headers)

    def get_product(self, product_id: ResourceId, headers: Headers):
        return self._request("GET", ALERTS + "/products/" + str(product_id), None, headers)

    def list_products(self, headers: Headers, filters: Filters = None):
        return self._request("GET", ALERTS + "/products", None, headers, params=filters)

    def submit_coordination(self, product_id: ResourceId, headers: Headers):
        return self._request(
            "POST", ALERTS + "/products/" + str(product_id) + "/submit-coordination", {}, headers
        )

    def issue_product(self, product_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", ALERTS + "/products/" + str(product_id) + "/issue", payload, headers
        )

    def cancel_product(self, product_id: ResourceId, headers: Headers):
        return self._request(
            "POST", ALERTS + "/products/" + str(product_id) + "/cancel", {}, headers
        )

    def get_wea_preview(self, product_id: ResourceId, channel_id: ResourceId, headers: Headers):
        return self._request(
            "GET",
            ALERTS + "/products/" + str(product_id) + "/wea-preview",
            None,
            headers,
            params={"channel_id": str(channel_id)},
        )

    # ------------------------------------------------------- coordination requests
    def get_coordination_request(self, request_id: ResourceId, headers: Headers):
        return self._request(
            "GET", ALERTS + "/coordination-requests/" + str(request_id), None, headers
        )

    def list_coordination_requests(self, headers: Headers, filters: Filters = None):
        return self._request("GET", ALERTS + "/coordination-requests", None, headers, params=filters)

    def respond_coordination_request(self, request_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", ALERTS + "/coordination-requests/" + str(request_id) + "/respond", payload, headers
        )

    # -------------------------------------------------------- dissemination records
    def get_dissemination_record(self, record_id: ResourceId, headers: Headers):
        return self._request(
            "GET", ALERTS + "/dissemination-records/" + str(record_id), None, headers
        )

    def list_dissemination_records(self, headers: Headers, filters: Filters = None):
        return self._request("GET", ALERTS + "/dissemination-records", None, headers, params=filters)

    # --------------------------------------------------------- verification events
    def create_verification_event(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/verification-events", payload, headers)

    def get_verification_event(self, event_id: ResourceId, headers: Headers):
        return self._request(
            "GET", ALERTS + "/verification-events/" + str(event_id), None, headers
        )

    def list_verification_events(self, headers: Headers, filters: Filters = None):
        return self._request("GET", ALERTS + "/verification-events", None, headers, params=filters)

    def adjudicate_verification_event(self, event_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", ALERTS + "/verification-events/" + str(event_id) + "/adjudicate", payload, headers
        )

    # ------------------------------------------------------ verification statistics
    def create_verification_statistic(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/verification-statistics", payload, headers)

    # ------------------------------------------------------------ emergency actions
    def create_emergency_action(self, payload: JsonObject, headers: Headers):
        return self._request("POST", ALERTS + "/emergency-actions", payload, headers)

    def get_emergency_action(self, action_id: ResourceId, headers: Headers):
        return self._request(
            "GET", ALERTS + "/emergency-actions/" + str(action_id), None, headers
        )

    def list_emergency_actions(self, headers: Headers, filters: Filters = None):
        return self._request("GET", ALERTS + "/emergency-actions", None, headers, params=filters)

    def order_emergency_action(self, action_id: ResourceId, headers: Headers):
        return self._request(
            "POST", ALERTS + "/emergency-actions/" + str(action_id) + "/order", {}, headers
        )

    def lift_emergency_action(self, action_id: ResourceId, headers: Headers):
        return self._request(
            "POST", ALERTS + "/emergency-actions/" + str(action_id) + "/lift", {}, headers
        )

    # ------------------------- platform capabilities (UNPREFIXED, PRD §2.4) ------
    def set_clock(self, to_iso8601: str, headers: Headers):
        """Set the logical clock. Mounted outside the /alerts prefix."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def settle_dissemination_record(self, record_id: ResourceId, outcome: str, headers: Headers):
        """Settle a SENT dissemination record. Mounted outside the /alerts prefix."""
        return self._request(
            "POST",
            "/_dissemination/settle",
            {"record_id": str(record_id), "outcome": outcome},
            headers,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client", "ALERTS"]
