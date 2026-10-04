"""API client: one method per endpoint defined in the PRD (mounted under /rail)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/rail/_clock/set_current_utc", payload, headers)

    # --- yards ---
    def create_yard(self, payload, headers):
        return self._request("POST", "/rail/yards", payload, headers)

    def list_yards(self, headers, params=None):
        return self._request("GET", "/rail/yards", headers=headers, params=params)

    def get_yard(self, yard_id, headers):
        return self._request("GET", f"/rail/yards/{yard_id}", headers=headers)

    def list_yard_car_events(self, yard_id, headers, params=None):
        return self._request("GET", f"/rail/yards/{yard_id}/car-events", headers=headers, params=params)

    # --- train plans ---
    def create_train_plan(self, payload, headers):
        return self._request("POST", "/rail/train-plans", payload, headers)

    def list_train_plans(self, headers, params=None):
        return self._request("GET", "/rail/train-plans", headers=headers, params=params)

    def get_train_plan(self, plan_id, headers):
        return self._request("GET", f"/rail/train-plans/{plan_id}", headers=headers)

    def activate_train_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rail/train-plans/{plan_id}/activate", payload, headers)

    def retire_train_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rail/train-plans/{plan_id}/retire", payload, headers)

    # --- crew pools ---
    def create_crew_pool(self, payload, headers):
        return self._request("POST", "/rail/crew-pools", payload, headers)

    def list_crew_pools(self, headers, params=None):
        return self._request("GET", "/rail/crew-pools", headers=headers, params=params)

    def get_crew_pool(self, pool_id, headers):
        return self._request("GET", f"/rail/crew-pools/{pool_id}", headers=headers)

    def replenish_crew_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/rail/crew-pools/{pool_id}/replenish", payload, headers)

    def close_crew_pool(self, pool_id, headers):
        return self._request("POST", f"/rail/crew-pools/{pool_id}/close", {}, headers)

    # --- locomotives ---
    def create_locomotive(self, payload, headers):
        return self._request("POST", "/rail/locomotives", payload, headers)

    def list_locomotives(self, headers, params=None):
        return self._request("GET", "/rail/locomotives", headers=headers, params=params)

    def get_locomotive(self, loco_id, headers):
        return self._request("GET", f"/rail/locomotives/{loco_id}", headers=headers)

    def bad_order_locomotive(self, loco_id, headers):
        return self._request("POST", f"/rail/locomotives/{loco_id}/bad-order", {}, headers)

    def release_repair_locomotive(self, loco_id, headers):
        return self._request("POST", f"/rail/locomotives/{loco_id}/release-repair", {}, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/rail/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/rail/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/rail/customers/{customer_id}", headers=headers)

    def adjust_service_credits(self, customer_id, payload, headers):
        return self._request("POST", f"/rail/customers/{customer_id}/service-credits", payload, headers)

    # --- shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/rail/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/rail/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/rail/shipments/{shipment_id}", headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/rail/shipments/{shipment_id}/cancel", {}, headers)

    def list_shipment_car_events(self, shipment_id, headers, params=None):
        return self._request("GET", f"/rail/shipments/{shipment_id}/car-events", headers=headers, params=params)

    def list_shipment_exceptions(self, shipment_id, headers, params=None):
        return self._request("GET", f"/rail/shipments/{shipment_id}/service-exceptions", headers=headers, params=params)

    # --- trip legs ---
    def assign_trip_legs(self, shipment_id, payload, headers):
        return self._request("POST", f"/rail/shipments/{shipment_id}/trip-legs", payload, headers)

    def list_shipment_trip_legs(self, shipment_id, headers, params=None):
        return self._request("GET", f"/rail/shipments/{shipment_id}/trip-legs", headers=headers, params=params)

    def list_trip_legs(self, headers, params=None):
        return self._request("GET", "/rail/trip-legs", headers=headers, params=params)

    def get_trip_leg(self, leg_id, headers):
        return self._request("GET", f"/rail/trip-legs/{leg_id}", headers=headers)

    # --- train departures ---
    def create_train_departure(self, payload, headers):
        return self._request("POST", "/rail/train-departures", payload, headers)

    def list_train_departures(self, headers, params=None):
        return self._request("GET", "/rail/train-departures", headers=headers, params=params)

    def get_train_departure(self, departure_id, headers):
        return self._request("GET", f"/rail/train-departures/{departure_id}", headers=headers)

    def finalize_train_departure(self, departure_id, headers):
        return self._request("POST", f"/rail/train-departures/{departure_id}/finalize", {}, headers)

    def cancel_train_departure(self, departure_id, headers):
        return self._request("POST", f"/rail/train-departures/{departure_id}/cancel", {}, headers)

    # --- car events ---
    def create_car_event(self, payload, headers):
        return self._request("POST", "/rail/car-events", payload, headers)

    def list_car_events(self, headers, params=None):
        return self._request("GET", "/rail/car-events", headers=headers, params=params)

    # --- service exceptions ---
    def list_service_exceptions(self, headers, params=None):
        return self._request("GET", "/rail/service-exceptions", headers=headers, params=params)

    def get_service_exception(self, exception_id, headers):
        return self._request("GET", f"/rail/service-exceptions/{exception_id}", headers=headers)

    def triage_service_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/rail/service-exceptions/{exception_id}/triage", payload, headers)

    def resolve_service_exception(self, exception_id, headers):
        return self._request("POST", f"/rail/service-exceptions/{exception_id}/resolve", {}, headers)


api_client = ApiClient()
