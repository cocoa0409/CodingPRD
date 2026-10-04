"""API client: one method per endpoint defined in the PRD (all under /repair)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/repair/_clock/set_current_utc", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/repair/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/repair/customers/{customer_id}", headers=headers)

    def lock_customer(self, customer_id, headers):
        return self._request("POST", f"/repair/customers/{customer_id}/lock", {}, headers)

    def unlock_customer(self, customer_id, headers):
        return self._request("POST", f"/repair/customers/{customer_id}/unlock", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/repair/customers/{customer_id}/close", {}, headers)

    # --- devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/repair/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/repair/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/repair/devices", headers=headers, params=params)

    def list_customer_devices(self, customer_id, headers):
        return self._request("GET", f"/repair/customers/{customer_id}/devices", headers=headers)

    # --- coverage plans ---
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", "/repair/coverage-plans", payload, headers)

    def get_coverage_plan(self, plan_id, headers):
        return self._request("GET", f"/repair/coverage-plans/{plan_id}", headers=headers)

    def list_device_coverage_plans(self, device_id, headers):
        return self._request("GET", f"/repair/devices/{device_id}/coverage-plans", headers=headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", "/repair/coverage-plans", headers=headers, params=params)

    def cancel_coverage_plan(self, plan_id, headers):
        return self._request("POST", f"/repair/coverage-plans/{plan_id}/cancel", {}, headers)

    # --- service locations ---
    def create_service_location(self, payload, headers):
        return self._request("POST", "/repair/service-locations", payload, headers)

    def get_service_location(self, location_id, headers):
        return self._request("GET", f"/repair/service-locations/{location_id}", headers=headers)

    def list_service_locations(self, headers, params=None):
        return self._request("GET", "/repair/service-locations", headers=headers, params=params)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/repair/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/repair/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/repair/technicians", headers=headers, params=params)

    # --- parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/repair/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/repair/parts/{part_id}", headers=headers)

    # --- part inventories ---
    def create_part_inventory(self, payload, headers):
        return self._request("POST", "/repair/part-inventories", payload, headers)

    def get_part_inventory(self, inventory_id, headers):
        return self._request("GET", f"/repair/part-inventories/{inventory_id}", headers=headers)

    def list_part_inventories(self, headers, params=None):
        return self._request("GET", "/repair/part-inventories", headers=headers, params=params)

    def list_location_part_inventories(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/repair/locations/{location_id}/part-inventories",
            headers=headers, params=params,
        )

    # --- appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/repair/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/repair/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/repair/appointments", headers=headers, params=params)

    def list_customer_appointments(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/repair/customers/{customer_id}/appointments",
            headers=headers, params=params,
        )

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/repair/appointments/{appointment_id}/check-in", {}, headers)

    def start_diagnosis(self, appointment_id, headers):
        return self._request("POST", f"/repair/appointments/{appointment_id}/start-diagnosis", {}, headers)

    def complete_diagnosis(self, appointment_id, headers):
        return self._request("POST", f"/repair/appointments/{appointment_id}/complete-diagnosis", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/repair/appointments/{appointment_id}/cancel", {}, headers)

    # --- repair orders ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair/repair-orders", headers=headers, params=params)

    def list_customer_repair_orders(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/repair/customers/{customer_id}/repair-orders",
            headers=headers, params=params,
        )

    def allocate_parts(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/allocate-parts", {}, headers)

    def start_repair(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/start-repair", {}, headers)

    def complete_repair(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/complete-repair", {}, headers)

    def pass_quality_check(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/pass-quality-check", {}, headers)

    def ship_to_depot(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/ship-to-depot", {}, headers)

    def receive_at_depot(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/receive-at-depot", {}, headers)

    def receive_back_from_depot(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/receive-back-from-depot", {}, headers)

    def complete_pickup(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/complete-pickup", {}, headers)

    def cancel_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/cancel", {}, headers)

    def escalate_repeat(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/escalate-repeat", {}, headers)

    def re_triage(self, repair_order_id, headers):
        return self._request("POST", f"/repair/repair-orders/{repair_order_id}/re-triage", {}, headers)

    # --- part allocations ---
    def get_part_allocation(self, allocation_id, headers):
        return self._request("GET", f"/repair/part-allocations/{allocation_id}", headers=headers)

    def list_part_allocations(self, headers, params=None):
        return self._request("GET", "/repair/part-allocations", headers=headers, params=params)

    # --- coverage entitlements ---
    def create_coverage_entitlement(self, payload, headers):
        return self._request("POST", "/repair/coverage-entitlements", payload, headers)

    def get_coverage_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/repair/coverage-entitlements/{entitlement_id}", headers=headers)

    def list_repair_order_entitlements(self, repair_order_id, headers):
        return self._request(
            "GET", f"/repair/repair-orders/{repair_order_id}/coverage-entitlements",
            headers=headers,
        )

    def list_coverage_entitlements(self, headers, params=None):
        return self._request("GET", "/repair/coverage-entitlements", headers=headers, params=params)

    def resolve_entitlement(self, entitlement_id, payload, headers):
        return self._request("POST", f"/repair/coverage-entitlements/{entitlement_id}/resolve", payload, headers)

    def resolve_entitlement_partial(self, entitlement_id, payload, headers):
        return self._request("POST", f"/repair/coverage-entitlements/{entitlement_id}/resolve-partial", payload, headers)

    def waive_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/repair/coverage-entitlements/{entitlement_id}/waive", {}, headers)

    # --- security verifications ---
    def create_security_verification(self, payload, headers):
        return self._request("POST", "/repair/security-verifications", payload, headers)

    def get_security_verification(self, verification_id, headers):
        return self._request("GET", f"/repair/security-verifications/{verification_id}", headers=headers)

    def list_repair_order_verifications(self, repair_order_id, headers):
        return self._request(
            "GET", f"/repair/repair-orders/{repair_order_id}/security-verifications",
            headers=headers,
        )

    def list_security_verifications(self, headers, params=None):
        return self._request("GET", "/repair/security-verifications", headers=headers, params=params)

    def verify_security_verification(self, verification_id, headers):
        return self._request("POST", f"/repair/security-verifications/{verification_id}/verify", {}, headers)

    def fail_security_verification(self, verification_id, headers):
        return self._request("POST", f"/repair/security-verifications/{verification_id}/fail", {}, headers)

    # --- repair shipments ---
    def create_repair_shipment(self, payload, headers):
        return self._request("POST", "/repair/repair-shipments", payload, headers)

    def get_repair_shipment(self, shipment_id, headers):
        return self._request("GET", f"/repair/repair-shipments/{shipment_id}", headers=headers)

    def list_repair_shipments(self, headers, params=None):
        return self._request("GET", "/repair/repair-shipments", headers=headers, params=params)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/repair/repair-shipments/{shipment_id}/ship", {}, headers)

    def receive_shipment(self, shipment_id, headers):
        return self._request("POST", f"/repair/repair-shipments/{shipment_id}/receive", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/repair/repair-shipments/{shipment_id}/deliver", {}, headers)

    def mark_shipment_lost(self, shipment_id, headers):
        return self._request("POST", f"/repair/repair-shipments/{shipment_id}/mark-lost", {}, headers)

    # --- quality follow-ups ---
    def create_quality_follow_up(self, payload, headers):
        return self._request("POST", "/repair/quality-follow-ups", payload, headers)

    def get_quality_follow_up(self, follow_up_id, headers):
        return self._request("GET", f"/repair/quality-follow-ups/{follow_up_id}", headers=headers)

    def list_repair_order_follow_ups(self, repair_order_id, headers):
        return self._request(
            "GET", f"/repair/repair-orders/{repair_order_id}/quality-follow-ups",
            headers=headers,
        )

    def list_quality_follow_ups(self, headers, params=None):
        return self._request("GET", "/repair/quality-follow-ups", headers=headers, params=params)

    def resolve_follow_up_satisfied(self, follow_up_id, headers):
        return self._request("POST", f"/repair/quality-follow-ups/{follow_up_id}/resolve-satisfied", {}, headers)

    def resolve_follow_up_repeat(self, follow_up_id, headers):
        return self._request("POST", f"/repair/quality-follow-ups/{follow_up_id}/resolve-repeat", {}, headers)

    def escalate_follow_up(self, follow_up_id, headers):
        return self._request("POST", f"/repair/quality-follow-ups/{follow_up_id}/escalate", {}, headers)


api_client = ApiClient()
