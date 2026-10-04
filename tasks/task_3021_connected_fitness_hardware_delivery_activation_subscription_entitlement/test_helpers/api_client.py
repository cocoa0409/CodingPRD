"""API client: one method per endpoint of the connected-fitness API."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fitness"


class ApiClient(GenericApiClient):
    # ─── Membership ────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"{PREFIX}/memberships/{membership_id}", headers=headers)

    def activate_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/activate", payload, headers
        )

    def pause_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/pause", payload, headers
        )

    def resume_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/resume", payload, headers
        )

    def cancel_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/cancel", payload, headers
        )

    def reactivate_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/reactivate", payload, headers
        )

    def get_membership_summary(self, membership_id, headers):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}/summary", headers=headers
        )

    # ─── HouseholdUser ─────────────────────────────────
    def list_household_users(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/household-users", headers=headers, params=params)

    def create_household_user(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/household-users", payload, headers
        )

    def list_membership_household_users(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}/household-users",
            headers=headers, params=params,
        )

    def get_household_user(self, user_id, headers):
        return self._request("GET", f"{PREFIX}/household-users/{user_id}", headers=headers)

    def verify_household_user(self, user_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/household-users/{user_id}/verify", payload, headers
        )

    def start_stream(self, user_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/household-users/{user_id}/start-stream", payload, headers
        )

    def suspend_household_user(self, user_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/household-users/{user_id}/suspend", payload, headers
        )

    def unsuspend_household_user(self, user_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/household-users/{user_id}/unsuspend", payload, headers
        )

    # ─── Device ────────────────────────────────────────
    def create_device(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/devices", payload, headers
        )

    def list_membership_devices(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}/devices",
            headers=headers, params=params,
        )

    def get_device(self, device_id, headers):
        return self._request("GET", f"{PREFIX}/devices/{device_id}", headers=headers)

    def link_device(self, device_id, payload, headers):
        return self._request("POST", f"{PREFIX}/devices/{device_id}/link", payload, headers)

    def warranty_reset(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/warranty-reset", payload, headers
        )

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    # ─── HardwareOrder ─────────────────────────────────
    def create_hardware_order(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/memberships/{membership_id}/hardware-orders", payload, headers
        )

    def list_membership_hardware_orders(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}/hardware-orders",
            headers=headers, params=params,
        )

    def get_hardware_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/hardware-orders/{order_id}", headers=headers)

    def list_hardware_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hardware-orders", headers=headers, params=params)

    def file_refund_dispute(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardware-orders/{order_id}/refund-dispute", payload, headers
        )

    def redeem_refund(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardware-orders/{order_id}/redeem-refund", payload, headers
        )

    def list_device_hardware_orders(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/hardware-orders",
            headers=headers, params=params,
        )

    def list_order_delivery_appointments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hardware-orders/{order_id}/delivery-appointments",
            headers=headers, params=params,
        )

    def list_order_service_orders(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hardware-orders/{order_id}/service-orders",
            headers=headers, params=params,
        )

    def cancel_hardware_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardware-orders/{order_id}/cancel", payload, headers
        )

    # ─── DeliveryAppointment ───────────────────────────
    def create_delivery_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/delivery-appointments", payload, headers)

    def list_delivery_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/delivery-appointments", headers=headers, params=params
        )

    def get_delivery_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/delivery-appointments/{appointment_id}", headers=headers
        )

    def list_device_delivery_appointments(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/delivery-appointments",
            headers=headers, params=params,
        )

    def schedule_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/schedule",
            payload, headers,
        )

    def start_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/start", payload, headers
        )

    def complete_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/complete",
            payload, headers,
        )

    def fail_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/fail", payload, headers
        )

    def reschedule_delivery_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/reschedule",
            payload, headers,
        )

    def get_delivery_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/delivery-quotes", payload, headers)

    # ─── FinancingPlan ─────────────────────────────────
    def list_financing_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/financing-plans", headers=headers, params=params
        )

    def create_financing_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/financing-plans", payload, headers)

    def list_membership_financing_plans(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/memberships/{membership_id}/financing-plans",
            headers=headers, params=params,
        )

    def list_order_financing_plans(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hardware-orders/{order_id}/financing-plans",
            headers=headers, params=params,
        )

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/financing-plans/{plan_id}", headers=headers)

    def pay_installment(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/financing-plans/{plan_id}/installments/pay", payload, headers
        )

    def fail_installment(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/financing-plans/{plan_id}/installments/fail", payload, headers
        )

    def rolling_correction(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/financing-plans/{plan_id}/installments/rolling-correction",
            payload, headers,
        )

    # ─── ServiceOrder ──────────────────────────────────
    def list_service_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-orders", headers=headers, params=params
        )

    def create_service_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-orders", payload, headers)

    def get_service_order(self, service_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-orders/{service_order_id}", headers=headers
        )

    def list_device_service_orders(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/service-orders",
            headers=headers, params=params,
        )

    def reserve_part(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/reserve-part",
            payload, headers,
        )

    def release_reservation(self, part_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-inventory/{part_id}/reservation-release",
            payload, headers,
        )

    def schedule_service_order(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/schedule",
            payload, headers,
        )

    def start_repair(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/start-repair",
            payload, headers,
        )

    def resolve_service_order(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/resolve",
            payload, headers,
        )

    def fail_repair(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/fail-repair",
            payload, headers,
        )

    def list_service_order_parts(self, service_order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-orders/{service_order_id}/parts",
            headers=headers, params=params,
        )

    # ─── PartsInventory ────────────────────────────────
    def list_parts_inventory(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-inventory", headers=headers, params=params
        )

    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-inventory", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/parts-inventory/{part_id}", headers=headers)

    def restock_part(self, part_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-inventory/{part_id}/restock", payload, headers
        )

    def list_part_service_orders(self, part_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-inventory/{part_id}/service-orders",
            headers=headers, params=params,
        )

    # ─── ClassSession ──────────────────────────────────
    def create_class_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/class-sessions", payload, headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/class-sessions/{session_id}", headers=headers)

    def list_class_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/class-sessions", headers=headers, params=params
        )

    def publish_class_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/class-sessions/{session_id}/publish", payload, headers
        )

    def cancel_class_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/class-sessions/{session_id}/cancel", payload, headers
        )

    def get_leaderboard(self, session_id, headers):
        return self._request(
            "GET", f"{PREFIX}/class-sessions/{session_id}/leaderboard", headers=headers
        )

    # ─── ClassEnrollment ───────────────────────────────
    def list_class_enrollments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/class-enrollments", headers=headers, params=params
        )

    def create_class_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/class-enrollments", payload, headers)

    def list_session_enrollments(self, session_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/class-sessions/{session_id}/class-enrollments",
            headers=headers, params=params,
        )

    def list_device_enrollments(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/class-enrollments",
            headers=headers, params=params,
        )

    def list_user_enrollments(self, user_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/household-users/{user_id}/class-enrollments",
            headers=headers, params=params,
        )

    def complete_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/class-enrollments/{enrollment_id}/complete",
            payload, headers,
        )

    def drop_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/class-enrollments/{enrollment_id}/drop", payload, headers
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/class-enrollments/{enrollment_id}", headers=headers
        )

    # ─── RefurbBatch ───────────────────────────────────
    def create_refurb_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/refurb-batches", payload, headers)

    def list_device_refurb_batches(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/refurb-batches",
            headers=headers, params=params,
        )

    def list_device_refurb_batches_sold(self, device_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/devices/{device_id}/refurb-batches-sold",
            headers=headers, params=params,
        )

    def list_refurb_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/refurb-batches", headers=headers, params=params
        )

    def get_refurb_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/refurb-batches/{batch_id}", headers=headers)

    def certify_refurb_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refurb-batches/{batch_id}/certify", payload, headers
        )

    def list_refurb_batch_for_resale(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refurb-batches/{batch_id}/list", payload, headers
        )

    def sell_refurb_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refurb-batches/{batch_id}/sell", payload, headers
        )

    # ─── Operational endpoints ─────────────────────────
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def run_ops(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_run_ops", payload, headers)


api_client = ApiClient()