"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock / sweeps (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_sweeps(self, headers, payload=None):
        return self._request("POST", "/api/_sweeps/age-and-retention", payload or {}, headers)

    # --- Circle ---
    def create_circle(self, payload, headers):
        return self._request("POST", "/api/circles", payload, headers)

    def get_circle(self, circle_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}", headers=headers)

    def list_circles(self, headers, params=None):
        return self._request("GET", "/api/circles", headers=headers, params=params)

    # --- Member ---
    def get_member_toplevel(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def list_members_toplevel(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def invite_member(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/members", payload, headers)

    def list_members(self, circle_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/members", headers=headers, params=params)

    def get_member(self, circle_id, member_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}", headers=headers)

    def promote_member(self, circle_id, member_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/promote", payload or {}, headers)

    def demote_member(self, circle_id, member_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/demote", payload or {}, headers)

    def transfer_ownership(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/transfer-ownership", payload, headers)

    # --- Consent ---
    def grant_consent(self, circle_id, member_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/consent/grant", payload, headers)

    def revoke_consent(self, circle_id, member_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/consent/revoke", payload or {}, headers)

    def list_consent_records(self, circle_id, member_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/consent-records", headers=headers, params=params)

    def get_consent_record(self, record_id, headers):
        return self._request("GET", f"/api/consent-records/{record_id}", headers=headers)

    def list_consent_records_toplevel(self, headers, params=None):
        return self._request("GET", "/api/consent-records", headers=headers, params=params)

    # --- Privacy ---
    def patch_privacy(self, circle_id, member_id, payload, headers):
        return self._request("PATCH", f"/api/circles/{circle_id}/members/{member_id}/privacy", payload, headers)

    # --- Place ---
    def get_place_toplevel(self, place_id, headers):
        return self._request("GET", f"/api/places/{place_id}", headers=headers)

    def create_place(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/places", payload, headers)

    def list_places(self, circle_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/places", headers=headers, params=params)

    def get_place(self, circle_id, place_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}/places/{place_id}", headers=headers)

    def patch_place(self, circle_id, place_id, payload, headers):
        return self._request("PATCH", f"/api/circles/{circle_id}/places/{place_id}", payload, headers)

    def archive_place(self, circle_id, place_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/places/{place_id}/archive", payload or {}, headers)

    # --- LocationFix ---
    def get_fix_toplevel(self, fix_id, headers):
        return self._request("GET", f"/api/location-fixes/{fix_id}", headers=headers)

    def list_fixes_toplevel(self, headers, params=None):
        return self._request("GET", "/api/location-fixes", headers=headers, params=params)

    def post_fix(self, circle_id, member_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/fixes", payload, headers)

    def list_fixes(self, circle_id, member_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/fixes", headers=headers, params=params)

    def get_fix(self, circle_id, member_id, fix_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/fixes/{fix_id}", headers=headers)

    # --- PlaceAlert ---
    def get_alert_toplevel(self, alert_id, headers):
        return self._request("GET", f"/api/place-alerts/{alert_id}", headers=headers)

    def list_alerts_toplevel(self, headers, params=None):
        return self._request("GET", "/api/place-alerts", headers=headers, params=params)

    def list_place_alerts(self, circle_id, place_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/places/{place_id}/alerts", headers=headers, params=params)

    # --- TripReport ---
    def get_trip_toplevel(self, trip_id, headers):
        return self._request("GET", f"/api/trip-reports/{trip_id}", headers=headers)

    def list_trips_toplevel(self, headers, params=None):
        return self._request("GET", "/api/trip-reports", headers=headers, params=params)

    def list_trips(self, circle_id, member_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/trips", headers=headers, params=params)

    def get_trip(self, circle_id, member_id, trip_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/trips/{trip_id}", headers=headers)

    # --- CrashEvent ---
    def report_crash(self, circle_id, member_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/members/{member_id}/crash-events", payload, headers)

    def list_crashes(self, circle_id, member_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/members/{member_id}/crash-events", headers=headers, params=params)

    def get_crash(self, crash_id, headers):
        return self._request("GET", f"/api/crash-events/{crash_id}", headers=headers)

    def list_crashes_toplevel(self, headers, params=None):
        return self._request("GET", "/api/crash-events", headers=headers, params=params)

    def acknowledge_wellness(self, crash_id, check_id, headers, payload=None):
        return self._request("POST", f"/api/crash-events/{crash_id}/wellness-checks/{check_id}/acknowledge", payload or {}, headers)

    def mark_false_alarm(self, crash_id, payload, headers):
        return self._request("POST", f"/api/crash-events/{crash_id}/mark-false-alarm", payload, headers)

    # --- WellnessCheck ---
    def get_wellness_check(self, check_id, headers):
        return self._request("GET", f"/api/wellness-checks/{check_id}", headers=headers)

    def list_wellness_checks_toplevel(self, headers, params=None):
        return self._request("GET", "/api/wellness-checks", headers=headers, params=params)

    # --- EmergencyDispatch ---
    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/api/emergency-dispatches/{dispatch_id}", headers=headers)

    def list_dispatches_toplevel(self, headers, params=None):
        return self._request("GET", "/api/emergency-dispatches", headers=headers, params=params)

    def verify_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/api/emergency-dispatches/{dispatch_id}/verify", payload, headers)

    def complete_dispatch(self, dispatch_id, headers, payload=None):
        return self._request("POST", f"/api/emergency-dispatches/{dispatch_id}/complete", payload or {}, headers)

    def cancel_dispatch(self, dispatch_id, headers, payload=None):
        return self._request("POST", f"/api/emergency-dispatches/{dispatch_id}/cancel", payload or {}, headers)

    # --- Subscription & fiscal ---
    def change_tier(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/subscription/change-tier", payload, headers)

    def reactivate_subscription(self, circle_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/subscription/reactivate", payload or {}, headers)

    def simulate_payment_failed(self, circle_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/subscription/simulate-payment-failed", payload or {}, headers)

    def simulate_suspend(self, circle_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/subscription/simulate-suspend", payload or {}, headers)

    def get_subscription_event(self, event_id, headers):
        return self._request("GET", f"/api/subscription-events/{event_id}", headers=headers)

    def list_subscription_events_toplevel(self, headers, params=None):
        return self._request("GET", "/api/subscription-events", headers=headers, params=params)

    def list_subscription_events(self, circle_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/subscription-events", headers=headers, params=params)

    def consume_roadside_assistance(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/roadside-assistance", payload, headers)

    def consume_identity_protection(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/identity-protection/consume", payload, headers)

    # --- ComplianceHold ---
    def get_compliance_hold(self, hold_id, headers):
        return self._request("GET", f"/api/compliance-holds/{hold_id}", headers=headers)

    def list_compliance_holds_toplevel(self, headers, params=None):
        return self._request("GET", "/api/compliance-holds", headers=headers, params=params)

    def open_compliance_hold(self, circle_id, payload, headers):
        return self._request("POST", f"/api/circles/{circle_id}/compliance-holds", payload, headers)

    def list_compliance_holds(self, circle_id, headers, params=None):
        return self._request("GET", f"/api/circles/{circle_id}/compliance-holds", headers=headers, params=params)

    def resolve_compliance_hold(self, circle_id, hold_id, headers, payload=None):
        return self._request("POST", f"/api/circles/{circle_id}/compliance-holds/{hold_id}/resolve", payload or {}, headers)


api_client = ApiClient()
