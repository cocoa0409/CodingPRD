"""One method per endpoint of the Hot-N-Ready production and pickup portal API.

Methods return the raw ``requests.Response`` so tests can assert on both the
status code and the decoded body.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Filters, Headers, JsonObject, ResourceId


class HotReadyApiClient(GenericApiClient):
    """Typed wrapper over the portal's HTTP surface."""

    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601: str, headers: Headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- store days
    def create_store_day(self, payload: JsonObject, headers: Headers):
        return self._request("POST", "/store-days", payload, headers)

    def list_store_days(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/store-days", None, headers, params=params)

    def get_store_day(self, day_id: ResourceId, headers: Headers):
        return self._request("GET", "/store-days/" + str(day_id), None, headers)

    def update_store_day(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PUT", "/store-days/" + str(day_id), payload, headers)

    def open_store_day(self, day_id: ResourceId, headers: Headers):
        return self._request("POST", "/store-days/" + str(day_id) + "/open", {}, headers)

    def close_store_day(self, day_id: ResourceId, headers: Headers):
        return self._request("POST", "/store-days/" + str(day_id) + "/close", {}, headers)

    def reconcile_store_day(self, day_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/reconcile", {}, headers
        )

    def get_waste_report(self, day_id: ResourceId, headers: Headers):
        return self._request(
            "GET", "/store-days/" + str(day_id) + "/waste-report", None, headers
        )

    # ---------------------------------------------------------------- dayparts
    def create_daypart(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/dayparts", payload, headers
        )

    def list_dayparts_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET", "/store-days/" + str(day_id) + "/dayparts", None, headers, params=params
        )

    def get_daypart(self, daypart_id: ResourceId, headers: Headers):
        return self._request("GET", "/dayparts/" + str(daypart_id), None, headers)

    def update_daypart(self, daypart_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PUT", "/dayparts/" + str(daypart_id), payload, headers)

    def close_daypart(self, daypart_id: ResourceId, headers: Headers):
        return self._request("POST", "/dayparts/" + str(daypart_id) + "/close", {}, headers)

    def list_dayparts(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/dayparts", None, headers, params=params)

    # ------------------------------------------------------------ demand events
    def create_demand_event(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/demand-events", payload, headers
        )

    def list_demand_events_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/demand-events",
            None,
            headers,
            params=params,
        )

    def get_demand_event(self, event_id: ResourceId, headers: Headers):
        return self._request("GET", "/demand-events/" + str(event_id), None, headers)

    def cancel_demand_event(self, event_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/demand-events/" + str(event_id) + "/cancel", {}, headers
        )

    def list_demand_events(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/demand-events", None, headers, params=params)

    # -------------------------------------------------------------- dough batches
    def create_dough_batch(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/dough-batches", payload, headers
        )

    def get_dough_batch(self, batch_id: ResourceId, headers: Headers):
        return self._request("GET", "/dough-batches/" + str(batch_id), None, headers)

    def list_dough_batches_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/dough-batches",
            None,
            headers,
            params=params,
        )

    def advance_dough_batch(self, batch_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/dough-batches/" + str(batch_id) + "/advance", {}, headers
        )

    def list_dough_batches(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/dough-batches", None, headers, params=params)

    # ------------------------------------------------------------- cheese batches
    def create_cheese_batch(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/cheese-batches", payload, headers
        )

    def get_cheese_batch(self, batch_id: ResourceId, headers: Headers):
        return self._request("GET", "/cheese-batches/" + str(batch_id), None, headers)

    def list_cheese_batches_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/cheese-batches",
            None,
            headers,
            params=params,
        )

    def advance_cheese_batch(self, batch_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/cheese-batches/" + str(batch_id) + "/advance", {}, headers
        )

    def list_cheese_batches(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/cheese-batches", None, headers, params=params)

    # ----------------------------------------------------------------- products
    def create_product(self, payload: JsonObject, headers: Headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/products", None, headers, params=params)

    def get_product(self, product_id: ResourceId, headers: Headers):
        return self._request("GET", "/products/" + str(product_id), None, headers)

    def update_product(self, product_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PUT", "/products/" + str(product_id), payload, headers)

    # ------------------------------------------------------------ production runs
    def create_production_run(self, daypart_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST",
            "/dayparts/" + str(daypart_id) + "/production-runs",
            payload,
            headers,
        )

    def list_production_runs_of(self, daypart_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/dayparts/" + str(daypart_id) + "/production-runs",
            None,
            headers,
            params=params,
        )

    def get_production_run(self, run_id: ResourceId, headers: Headers):
        return self._request("GET", "/production-runs/" + str(run_id), None, headers)

    def start_baking(self, run_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/production-runs/" + str(run_id) + "/start-baking", {}, headers
        )

    def rack_run(self, run_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/production-runs/" + str(run_id) + "/rack", {}, headers
        )

    def list_production_runs(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/production-runs", None, headers, params=params)

    # --------------------------------------------------------------- hold units
    def list_hold_units(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/hold-units", None, headers, params=params)

    def get_hold_unit(self, unit_id: ResourceId, headers: Headers):
        return self._request("GET", "/hold-units/" + str(unit_id), None, headers)

    def discard_hold_unit(self, unit_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/hold-units/" + str(unit_id) + "/discard", payload, headers
        )

    # ------------------------------------------------------------------- orders
    def create_order(self, payload: JsonObject, headers: Headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/orders", None, headers, params=params)

    def get_order(self, order_id: ResourceId, headers: Headers):
        return self._request("GET", "/orders/" + str(order_id), None, headers)

    def pay_order(self, order_id: ResourceId, headers: Headers):
        return self._request("POST", "/orders/" + str(order_id) + "/pay", {}, headers)

    def start_preparation(self, order_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/orders/" + str(order_id) + "/start-preparation", {}, headers
        )

    def mark_ready(self, order_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/orders/" + str(order_id) + "/mark-ready", {}, headers
        )

    def claim_order(self, order_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/orders/" + str(order_id) + "/claim", payload, headers
        )

    def cancel_order(self, order_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/orders/" + str(order_id) + "/cancel", {}, headers
        )

    # -------------------------------------------------------------- locker slots
    def create_locker_slot(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/locker-slots", payload, headers
        )

    def list_locker_slots_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/locker-slots",
            None,
            headers,
            params=params,
        )

    def get_locker_slot(self, slot_id: ResourceId, headers: Headers):
        return self._request("GET", "/locker-slots/" + str(slot_id), None, headers)

    def list_locker_slots(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/locker-slots", None, headers, params=params)

    # ---------------------------------------------------------------- waste logs
    def list_waste_logs_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/waste-logs",
            None,
            headers,
            params=params,
        )

    def list_waste_logs(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/waste-logs", None, headers, params=params)

    def get_waste_log(self, waste_log_id: ResourceId, headers: Headers):
        return self._request("GET", "/waste-logs/" + str(waste_log_id), None, headers)

    # --------------------------------------------------------------- crew shifts
    def create_crew_shift(self, day_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", "/store-days/" + str(day_id) + "/crew-shifts", payload, headers
        )

    def list_crew_shifts_of(self, day_id: ResourceId, headers: Headers, params: Filters = None):
        return self._request(
            "GET",
            "/store-days/" + str(day_id) + "/crew-shifts",
            None,
            headers,
            params=params,
        )

    def get_crew_shift(self, shift_id: ResourceId, headers: Headers):
        return self._request("GET", "/crew-shifts/" + str(shift_id), None, headers)

    def end_crew_shift(self, shift_id: ResourceId, headers: Headers):
        return self._request(
            "POST", "/crew-shifts/" + str(shift_id) + "/end", {}, headers
        )

    def list_crew_shifts(self, headers: Headers, params: Filters = None):
        return self._request("GET", "/crew-shifts", None, headers, params=params)


__all__ = ["HotReadyApiClient"]
