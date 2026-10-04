"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Plan tiers ---
    def create_plan_tier(self, payload, headers):
        return self._request("POST", "/plan-tiers", payload, headers)

    def list_plan_tiers(self, headers, params=None):
        return self._request("GET", "/plan-tiers", headers=headers, params=params)

    def get_plan_tier(self, tier_id, headers):
        return self._request("GET", f"/plan-tiers/{tier_id}", headers=headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    # --- Coverage zones ---
    def create_coverage_zone(self, payload, headers):
        return self._request("POST", "/coverage-zones", payload, headers)

    def list_coverage_zones(self, headers, params=None):
        return self._request("GET", "/coverage-zones", headers=headers, params=params)

    def get_coverage_zone(self, zone_id, headers):
        return self._request("GET", f"/coverage-zones/{zone_id}", headers=headers)

    # --- Vehicles ---
    def create_vehicle(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/vehicles", payload, headers)

    def list_account_vehicles(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/vehicles", headers=headers, params=params)

    def get_vehicle_aliased(self, vehicle_id, headers):
        return self._request("GET", f"/accounts/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/accounts/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def update_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/vehicles/{vehicle_id}", payload, headers)

    # --- Subscriptions ---
    def create_subscription(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/subscriptions", payload, headers)

    def list_account_subscriptions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/subscriptions", headers=headers, params=params)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/accounts/subscriptions", headers=headers, params=params)

    def get_subscription_aliased(self, subscription_id, headers):
        return self._request("GET", f"/accounts/subscriptions/{subscription_id}", headers=headers)

    def get_subscription(self, account_id, subscription_id, headers):
        return self._request(
            "GET", f"/accounts/{account_id}/subscriptions/{subscription_id}", headers=headers
        )

    def convert_subscription(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/convert",
            payload, headers,
        )

    def record_billing_event(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/billing-events",
            payload, headers,
        )

    def retain_emergency(self, account_id, subscription_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/retain-emergency",
            {}, headers,
        )

    def reactivate_subscription(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/reactivate",
            payload, headers,
        )

    def cancel_subscription(self, account_id, subscription_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/cancel",
            {}, headers,
        )

    # --- Crash events ---
    def create_crash_event(self, vehicle_id, payload, headers=None):
        return self._request("POST", f"/vehicles/{vehicle_id}/crash-events", payload, headers)

    def list_crash_events(self, headers, params=None):
        return self._request("GET", "/accounts/crash-events", headers=headers, params=params)

    def list_vehicle_crash_events(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/crash-events", headers=headers, params=params
        )

    def get_crash_event_aliased(self, event_id, headers):
        return self._request("GET", f"/accounts/crash-events/{event_id}", headers=headers)

    def get_crash_event(self, vehicle_id, event_id, headers):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/crash-events/{event_id}", headers=headers
        )

    def connect_advisor(self, vehicle_id, event_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/crash-events/{event_id}/connect-advisor",
            {}, headers,
        )

    def create_dispatch_request(self, vehicle_id, event_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/crash-events/{event_id}/dispatch-requests",
            payload, headers,
        )

    def close_crash_event(self, vehicle_id, event_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/crash-events/{event_id}/close", {}, headers,
        )

    # --- Dispatch requests ---
    def list_dispatch_requests(self, headers, params=None):
        return self._request("GET", "/accounts/dispatch-requests", headers=headers, params=params)

    def get_dispatch_request_aliased(self, dispatch_id, headers):
        return self._request("GET", f"/accounts/dispatch-requests/{dispatch_id}", headers=headers)

    def get_dispatch_request(self, dispatch_id, headers):
        return self._request("GET", f"/dispatch-requests/{dispatch_id}", headers=headers)

    def list_vehicle_dispatch_requests(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/dispatch-requests", headers=headers, params=params
        )

    def acknowledge_dispatch(self, dispatch_id, headers):
        return self._request(
            "POST", f"/dispatch-requests/{dispatch_id}/acknowledge", {}, headers,
        )

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatch-requests/{dispatch_id}/cancel", {}, headers)

    def list_psap_dispatch_requests(self, psap_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/psaps/{psap_id}/dispatch-requests", headers=headers, params=params
        )

    # --- PSAPs ---
    def create_psap(self, payload, headers):
        return self._request("POST", "/psaps", payload, headers)

    def get_psap_aliased(self, psap_id, headers):
        return self._request("GET", f"/accounts/psaps/{psap_id}", headers=headers)

    def list_psaps(self, headers, params=None):
        return self._request("GET", "/psaps", headers=headers, params=params)

    def get_psap(self, psap_id, headers):
        return self._request("GET", f"/psaps/{psap_id}", headers=headers)

    # --- Stolen vehicle cases ---
    def create_stolen_case(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/stolen-cases", payload, headers)

    def list_stolen_cases(self, headers, params=None):
        return self._request("GET", "/accounts/stolen-cases", headers=headers, params=params)

    def list_vehicle_stolen_cases(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/stolen-cases", headers=headers, params=params
        )

    def get_stolen_case_aliased(self, case_id, headers):
        return self._request("GET", f"/accounts/stolen-cases/{case_id}", headers=headers)

    def get_stolen_case(self, vehicle_id, case_id, headers):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}", headers=headers
        )

    def verify_stolen_case(self, vehicle_id, case_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}/verify", {}, headers,
        )

    def arm_slowdown(self, vehicle_id, case_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}/arm-slowdown", {}, headers,
        )

    def execute_slowdown(self, vehicle_id, case_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}/execute-slowdown",
            {}, headers,
        )

    def close_case_recovered(self, vehicle_id, case_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}/close-recovered",
            {}, headers,
        )

    def close_case_unverified(self, vehicle_id, case_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/stolen-cases/{case_id}/close-unverified",
            {}, headers,
        )

    # --- Remote commands ---
    def create_remote_command(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/remote-commands", payload, headers)

    def list_remote_commands(self, headers, params=None):
        return self._request("GET", "/accounts/remote-commands", headers=headers, params=params)

    def list_vehicle_remote_commands(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/remote-commands", headers=headers, params=params
        )

    def get_remote_command_aliased(self, command_id, headers):
        return self._request("GET", f"/accounts/remote-commands/{command_id}", headers=headers)

    def get_remote_command(self, command_id, headers):
        return self._request("GET", f"/remote-commands/{command_id}", headers=headers)

    def acknowledge_remote_command(self, command_id, headers=None):
        return self._request(
            "POST", f"/remote-commands/{command_id}/acknowledge", {}, headers,
        )

    def fail_remote_command(self, command_id, headers=None):
        return self._request("POST", f"/remote-commands/{command_id}/fail", {}, headers)

    # --- Diagnostic reports ---
    def create_diagnostic_report(self, vehicle_id, payload, headers=None):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/diagnostic-reports", payload, headers,
        )

    def list_diagnostic_reports(self, headers, params=None):
        return self._request("GET", "/accounts/diagnostic-reports", headers=headers, params=params)

    def list_vehicle_diagnostic_reports(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/diagnostic-reports", headers=headers, params=params
        )

    def get_diagnostic_report_aliased(self, report_id, headers):
        return self._request("GET", f"/accounts/diagnostic-reports/{report_id}", headers=headers)

    def get_diagnostic_report(self, vehicle_id, report_id, headers):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/diagnostic-reports/{report_id}", headers=headers,
        )

    # --- Dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def get_dealer_aliased(self, dealer_id, headers):
        return self._request("GET", f"/accounts/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    # --- Service appointments ---
    def create_appointment(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealers/{dealer_id}/appointments", payload, headers)

    def list_service_appointments(self, headers, params=None):
        return self._request(
            "GET", "/accounts/service-appointments", headers=headers, params=params
        )

    def list_dealer_appointments(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/dealers/{dealer_id}/appointments", headers=headers, params=params
        )

    def confirm_appointment(self, dealer_id, appointment_id, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/appointments/{appointment_id}/confirm", {}, headers,
        )

    def complete_appointment(self, dealer_id, appointment_id, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/appointments/{appointment_id}/complete", {}, headers,
        )

    def cancel_appointment(self, dealer_id, appointment_id, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/appointments/{appointment_id}/cancel", {}, headers,
        )

    def get_service_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/accounts/service-appointments/{appointment_id}", headers=headers,
        )

    # --- Data consents ---
    def get_consent_aliased(self, consent_id, headers):
        return self._request("GET", f"/accounts/consents/{consent_id}", headers=headers)

    def create_consent(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/accounts/consents", headers=headers, params=params)

    def list_account_consents(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/consents", headers=headers, params=params
        )

    def revoke_consent(self, account_id, consent_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/consents/{consent_id}/revoke", {}, headers,
        )

    def grant_consent(self, account_id, consent_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/consents/{consent_id}/grant", {}, headers,
        )


api_client = ApiClient()
