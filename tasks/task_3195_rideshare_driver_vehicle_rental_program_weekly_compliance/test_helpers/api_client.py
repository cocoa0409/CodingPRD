"""API client: one method per operation in the endpoint catalogue (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Drivers ──────────────────────────────────────
    def register_driver(self, payload, headers):
        return self._request("POST", "/program/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/program/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/program/drivers", headers=headers, params=params)

    def record_activity_score(self, driver_id, payload, headers):
        return self._request("POST", f"/program/drivers/{driver_id}/activity", payload, headers)

    def record_driving_record(self, driver_id, payload, headers):
        return self._request("POST", f"/program/drivers/{driver_id}/driving-record", payload, headers)

    def list_driver_enrollments(self, driver_id, headers, params=None):
        return self._request("GET", f"/program/drivers/{driver_id}/enrollments", headers=headers, params=params)

    def get_driver_summary(self, driver_id, headers):
        return self._request("GET", f"/program/drivers/{driver_id}/summary", headers=headers)

    # ─── Enrollments ──────────────────────────────────
    def enroll_driver(self, payload, headers):
        return self._request("POST", "/program/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/program/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/program/enrollments", headers=headers, params=params)

    def verify_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/program/enrollments/{enrollment_id}/verify", payload, headers)

    def re_evaluate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/program/enrollments/{enrollment_id}/re-evaluate", payload, headers)

    def reinstate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/program/enrollments/{enrollment_id}/reinstate", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/program/enrollments/{enrollment_id}/withdraw", payload, headers)

    # ─── Vehicles ─────────────────────────────────────
    def admit_vehicle(self, payload, headers):
        return self._request("POST", "/program/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/program/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/program/vehicles", headers=headers, params=params)

    # ─── Agreements ───────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", "/program/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/program/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/program/agreements", headers=headers, params=params)

    def get_agreement_summary(self, agreement_id, headers):
        return self._request("GET", f"/program/agreements/{agreement_id}/summary", headers=headers)

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/program/agreements/{agreement_id}/activate", payload, headers)

    def swap_agreement_vehicle(self, agreement_id, payload, headers):
        return self._request("POST", f"/program/agreements/{agreement_id}/swap", payload, headers)

    def complete_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/program/agreements/{agreement_id}/complete", payload, headers)

    def escalate_recovery(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/program/agreements/{agreement_id}/escalate-recovery", payload, headers)

    def recover_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/program/agreements/{agreement_id}/recover", payload, headers)

    # ─── Weeks ────────────────────────────────────────
    def open_week(self, payload, headers):
        return self._request("POST", "/program/weeks", payload, headers)

    def get_week(self, week_id, headers):
        return self._request("GET", f"/program/weeks/{week_id}", headers=headers)

    def list_weeks(self, headers, params=None):
        return self._request("GET", "/program/weeks", headers=headers, params=params)

    def record_mileage(self, week_id, payload, headers):
        return self._request("POST", f"/program/weeks/{week_id}/mileage", payload, headers)

    def settle_week(self, week_id, headers, payload=None):
        return self._request("POST", f"/program/weeks/{week_id}/settle", payload, headers)

    def tender_payment(self, week_id, payload, headers):
        return self._request("POST", f"/program/weeks/{week_id}/payments", payload, headers)

    def retry_payment(self, week_id, payload, headers):
        return self._request("POST", f"/program/weeks/{week_id}/retry-payment", payload, headers)

    def grace_lapse(self, week_id, headers, payload=None):
        return self._request("POST", f"/program/weeks/{week_id}/grace-lapse", payload, headers)

    def waive_week(self, week_id, headers, payload=None):
        return self._request("POST", f"/program/weeks/{week_id}/waive", payload, headers)

    def reopen_week(self, week_id, headers, payload=None):
        return self._request("POST", f"/program/weeks/{week_id}/reopen", payload, headers)

    # ─── Maintenance events ───────────────────────────
    def report_maintenance_event(self, payload, headers):
        return self._request("POST", "/program/maintenance-events", payload, headers)

    def get_maintenance_event(self, event_id, headers):
        return self._request("GET", f"/program/maintenance-events/{event_id}", headers=headers)

    def list_maintenance_events(self, headers, params=None):
        return self._request("GET", "/program/maintenance-events", headers=headers, params=params)

    def start_maintenance_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/program/maintenance-events/{event_id}/start", payload, headers)

    def issue_loaner(self, event_id, headers, payload=None):
        return self._request("POST", f"/program/maintenance-events/{event_id}/issue-loaner", payload, headers)

    def complete_maintenance_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/program/maintenance-events/{event_id}/complete", payload, headers)

    # ─── Payments ─────────────────────────────────────
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/program/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/program/payments", headers=headers, params=params)

    # ─── Purchase options ─────────────────────────────
    def offer_purchase_option(self, payload, headers):
        return self._request("POST", "/program/purchase-options", payload, headers)

    def get_purchase_option(self, option_id, headers):
        return self._request("GET", f"/program/purchase-options/{option_id}", headers=headers)

    def list_purchase_options(self, headers, params=None):
        return self._request("GET", "/program/purchase-options", headers=headers, params=params)

    def elect_purchase_option(self, option_id, payload, headers):
        return self._request("POST", f"/program/purchase-options/{option_id}/elect", payload, headers)

    def fund_escrow(self, option_id, headers, payload=None):
        return self._request("POST", f"/program/purchase-options/{option_id}/fund-escrow", payload, headers)

    def withdraw_purchase_option(self, option_id, headers, payload=None):
        return self._request("POST", f"/program/purchase-options/{option_id}/withdraw", payload, headers)

    def complete_purchase_option(self, option_id, headers, payload=None):
        return self._request("POST", f"/program/purchase-options/{option_id}/complete", payload, headers)

    # ─── Platform qualification checks ────────────────
    def submit_platform_check(self, payload, headers):
        return self._request("POST", "/program/platform-checks", payload, headers)

    def rerun_platform_check(self, check_id, headers, payload=None):
        return self._request("POST", f"/program/platform-checks/{check_id}", payload, headers)

    def get_platform_check(self, check_id, headers):
        return self._request("GET", f"/program/platform-checks/{check_id}", headers=headers)

    def list_platform_checks(self, headers, params=None):
        return self._request("GET", "/program/platform-checks", headers=headers, params=params)

    # ─── Fleet facts ──────────────────────────────────
    def declare_fleet_fact(self, payload, headers):
        return self._request("POST", "/program/fleet-facts", payload, headers)

    def get_fleet_fact(self, fact_id, headers):
        return self._request("GET", f"/program/fleet-facts/{fact_id}", headers=headers)

    def recompute_fleet_fact(self, fact_id, headers, payload=None):
        return self._request("POST", f"/program/fleet-facts/{fact_id}/recompute", payload, headers)

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/program/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()