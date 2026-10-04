"""HTTP client: one method per endpoint the contract declares.

Every path in this API is mounted beneath ``/stores``; the breed handling rules
collection and the logical clock controls sit at the top level. List endpoints
take ``params`` for pagination/filtering; write endpoints take ``payload``.

Every method returns the raw response so tests can assert on status codes and
envelope shape.
"""

from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/stores"


class ApiClient(GenericApiClient):
    """Client for the pet care centre API.

    The evaluator restarts the server before every test, which closes every
    keep-alive socket the previous test left open. A pooled connection that the
    server has already dropped surfaces as a transport error rather than a
    response, so the URLLib3 retry adapter re-establishes the connection and
    replays the request instead of failing the test on a stale socket. POST is
    included in the retried methods, because every write on this surface is a
    POST.
    """

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        retries = Retry(total=3, connect=3, read=3, allowed_methods=None, backoff_factor=0.2)
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ── Centres and hospital posture ───────────────────────────────────────

    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", PREFIX, payload, headers)

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", PREFIX, params, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}", None, headers)

    def restrict_store(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/restrict", payload, headers)

    def lift_posture_restriction(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/lift-posture-restriction", payload, headers)

    def freeze_hospital(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/freeze-hospital", payload, headers)

    def reopen_hospital(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/reopen-hospital", payload, headers)

    def bump_occupancy(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/_bump-occupancy-v1", payload, headers)

    # ── Members ────────────────────────────────────────────────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members", params, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}", None, headers)

    def activate_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members/{member_id}/activate", {}, headers)

    def suspend_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members/{member_id}/suspend", {}, headers)

    def archive_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members/{member_id}/archive", {}, headers)

    def list_member_pets(self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}/pets", params, headers)

    # ── Pets ───────────────────────────────────────────────────────────────

    def create_pet(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pets", payload, headers)

    def list_pets(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets", params, headers)

    def get_pet(self, pet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets/{pet_id}", None, headers)

    def archive_pet(self, pet_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pets/{pet_id}/archive", payload, headers)

    def list_pet_incident_records(self, pet_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets/{pet_id}/incident-records", params, headers)

    def list_pet_rabies_certificates(self, pet_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets/{pet_id}/rabies-certificates", params, headers)

    def list_pet_encounters(self, pet_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets/{pet_id}/veterinary-encounters", params, headers)

    def list_pet_prescriptions(self, pet_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pets/{pet_id}/prescription-authorizations", params, headers)

    # ── Breed handling rules ───────────────────────────────────────────────

    def create_breed_rule(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/breed-handling-rules", payload, headers)

    def list_breed_rules(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/breed-handling-rules", params, headers)

    def get_breed_rule(self, rule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/breed-handling-rules/{rule_id}", None, headers)

    # ── Service bays ───────────────────────────────────────────────────────

    def create_service_bay(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bays", payload, headers)

    def get_store_service_bay(self, store_id: str, bay_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/service-bays/{bay_id}", None, headers)

    def disable_service_bay(self, store_id: str, bay_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bays/{bay_id}/disable", payload, headers)

    def list_service_bays(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-bays", params, headers)

    def get_service_bay(self, bay_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-bays/{bay_id}", None, headers)

    # ── Service bookings and screenings ────────────────────────────────────

    def create_booking(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-bookings/{booking_id}", None, headers)

    def screen_booking(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/screen", payload, headers)

    def confirm_bay(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/confirm-bay", payload, headers)

    def start_service(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/start-service", payload, headers)

    def complete_service(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/complete-service", payload, headers)

    def mark_no_show(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/mark-no-show", payload, headers)

    def cancel_booking(self, store_id: str, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/cancel", payload, headers)

    def list_booking_risk_screenings(self, store_id: str, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/risk-screenings", params, headers)

    def list_booking_incident_records(self, store_id: str, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/service-bookings/{booking_id}/incident-records", params, headers)

    def list_service_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-bookings", params, headers)

    def list_risk_screenings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/risk-screenings", params, headers)

    def get_risk_screening(self, screening_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/risk-screenings/{screening_id}", None, headers)

    # ── Veterinary encounters ──────────────────────────────────────────────

    def create_encounter(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/veterinary-encounters", payload, headers)

    def get_encounter(self, encounter_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/veterinary-encounters/{encounter_id}", None, headers)

    def get_retail_encounter(self, encounter_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/retail/veterinary-encounters/{encounter_id}", None, headers)

    def check_in_encounter(self, store_id: str, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/check-in", payload, headers)

    def start_exam(self, store_id: str, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/start-exam", payload, headers)

    def complete_exam(self, store_id: str, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/complete-exam", payload, headers)

    def cancel_encounter(self, store_id: str, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/cancel", payload, headers)

    def get_charge_summary(self, store_id: str, encounter_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/charge-summary", None, headers)

    def list_encounter_prescriptions(self, store_id: str, encounter_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/veterinary-encounters/{encounter_id}/prescription-authorizations", params, headers)

    def list_encounters(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/veterinary-encounters", params, headers)

    # ── Vaccination clinics and visits ─────────────────────────────────────

    def create_clinic(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-clinics", payload, headers)

    def get_clinic(self, clinic_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vaccination-clinics/{clinic_id}", None, headers)

    def open_walk_ins(self, store_id: str, clinic_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-clinics/{clinic_id}/open-walk-ins", payload, headers)

    def close_walk_ins(self, store_id: str, clinic_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-clinics/{clinic_id}/close-walk-ins", payload, headers)

    def list_clinic_visits(self, store_id: str, clinic_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/vaccination-clinics/{clinic_id}/vaccination-visits", params, headers)

    def get_clinic_state_report(self, store_id: str, clinic_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/vaccination-clinics/{clinic_id}/state-report", params, headers)

    def list_clinics(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vaccination-clinics", params, headers)

    def create_visit(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-visits", payload, headers)

    def list_visits(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vaccination-visits", params, headers)

    def get_visit(self, visit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vaccination-visits/{visit_id}", None, headers)

    def issue_certificate(self, store_id: str, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-visits/{visit_id}/issue-certificate", payload, headers)

    def submit_state_report(self, store_id: str, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/vaccination-visits/{visit_id}/submit-state-report", payload, headers)

    def get_visit_rabies_certificate(self, visit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vaccination-visits/{visit_id}/rabies-certificate", None, headers)

    def list_rabies_certificates(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rabies-certificates", params, headers)

    def get_rabies_certificate(self, certificate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rabies-certificates/{certificate_id}", None, headers)

    # ── Prescriptions ──────────────────────────────────────────────────────

    def create_prescription(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/prescription-authorizations", payload, headers)

    def get_prescription(self, authorization_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/prescription-authorizations/{authorization_id}", None, headers)

    def revoke_prescription(self, store_id: str, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/prescription-authorizations/{authorization_id}/revoke", payload, headers)

    def list_prescriptions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/prescription-authorizations", params, headers)

    # ── Pharmacy orders ────────────────────────────────────────────────────

    def create_pharmacy_order(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/pharmacy-orders", payload, headers)

    def get_pharmacy_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pharmacy-orders/{order_id}", None, headers)

    def dispense_pharmacy_order(self, store_id: str, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/pharmacy-orders/{order_id}/dispense", payload, headers)

    def reject_pharmacy_order(self, store_id: str, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/pharmacy-orders/{order_id}/reject", payload, headers)

    def list_pharmacy_orders(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pharmacy-orders", params, headers)

    def list_prescription_pharmacy_orders(self, authorization_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/prescription-authorizations/{authorization_id}/pharmacy-orders", params, headers)

    # ── Retail cross-sells ─────────────────────────────────────────────────

    def create_cross_sell(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/retail-cross-sells", payload, headers)

    def get_cross_sell(self, cross_sell_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/retail-cross-sells/{cross_sell_id}", None, headers)

    def redeem_cross_sell(self, store_id: str, cross_sell_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/retail-cross-sells/{cross_sell_id}/redeem", payload, headers)

    def list_cross_sells(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/retail-cross-sells", params, headers)

    def list_prescription_cross_sells(self, authorization_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/prescription-authorizations/{authorization_id}/retail-cross-sells", params, headers)

    # ── Incident records and claims ────────────────────────────────────────

    def create_incident(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/incident-records", payload, headers)

    def get_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/incident-records/{incident_id}", None, headers)

    def begin_review(self, store_id: str, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/incident-records/{incident_id}/begin-review", payload, headers)

    def approve_claim(self, store_id: str, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/incident-records/{incident_id}/approve-claim", payload, headers)

    def deny_claim(self, store_id: str, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/incident-records/{incident_id}/deny-claim", payload, headers)

    def return_to_queue(self, store_id: str, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/incident-records/{incident_id}/return-to-queue", payload, headers)

    def get_claim_summary(self, store_id: str, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/incident-records/{incident_id}/claim-summary", None, headers)

    def list_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/incident-records", params, headers)

    # ── Service packages and billing cycles ────────────────────────────────

    def create_package(self, store_id: str, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/members/{member_id}/service-packages", payload, headers)

    def get_package(self, package_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-packages/{package_id}", None, headers)

    def list_packages(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-packages", params, headers)

    def list_member_packages(self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}/service-packages", params, headers)

    def advance_billing_cycle(self, store_id: str, member_id: str, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/{store_id}/members/{member_id}/service-packages/{package_id}/billing-cycles", payload, headers
        )

    def list_package_billing_cycles(self, package_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-packages/{package_id}/billing-cycles", params, headers)

    def list_billing_cycles(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/billing-cycles", params, headers)

    def get_billing_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/billing-cycles/{cycle_id}", None, headers)

    def pause_package(self, store_id: str, member_id: str, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/{store_id}/members/{member_id}/service-packages/{package_id}/pause", payload, headers
        )

    def resume_package(self, store_id: str, member_id: str, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/{store_id}/members/{member_id}/service-packages/{package_id}/resume", payload, headers
        )

    def cancel_package(self, store_id: str, member_id: str, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/{store_id}/members/{member_id}/service-packages/{package_id}/cancel", payload, headers
        )

    # ── Training enrolments ────────────────────────────────────────────────

    def create_enrollment(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/training-enrollments", payload, headers)

    def get_store_enrollment(self, store_id: str, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/{store_id}/training-enrollments/{enrollment_id}", None, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/training-enrollments/{enrollment_id}", None, headers)

    def begin_course(self, store_id: str, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/training-enrollments/{enrollment_id}/begin-course", payload, headers)

    def return_to_ack(self, store_id: str, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/training-enrollments/{enrollment_id}/return-to-ack", payload, headers)

    def start_course(self, store_id: str, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/training-enrollments/{enrollment_id}/start-course", payload, headers)

    def revert_course(self, store_id: str, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/{store_id}/training-enrollments/{enrollment_id}/revert-course", payload, headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/training-enrollments", params, headers)

    def list_package_enrollments(self, package_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-packages/{package_id}/training-enrollments", params, headers)


api_client = ApiClient()