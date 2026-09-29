"""API client: one method per endpoint declared in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant so sub-second precision width never
    causes a spurious mismatch.

    ``2026-10-12T15:00:00Z``, ``2026-10-12T15:00:00.000Z`` and
    ``2026-10-12T15:00:00+00:00`` all canonicalise to ``2026-10-12T15:00:00Z``.
    Returns the input unchanged when it is not a parsable instant.
    """
    if not isinstance(value, str) or not value:
        return value
    text = value.strip()
    tail = ""
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
        tail = "Z"
    elif len(text) >= 6 and text[-6] in "+-" and text[-3] == ":":
        offset = text[-6:]
        if offset in ("+00:00", "-00:00"):
            text = text[:-6]
            tail = "Z"
        else:
            return value
    else:
        return value
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit()).rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return f"{text}{tail}"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two ISO-8601 instants ignoring sub-second precision width."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Endpoint methods for the guest ranch / all-inclusive resort API."""

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # seasons
    # ------------------------------------------------------------------
    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def advance_season(self, season_id: str, target_status: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/seasons/{season_id}/advance",
            {"target_status": target_status},
            headers,
        )

    # ------------------------------------------------------------------
    # cabins
    # ------------------------------------------------------------------
    def create_cabin(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cabins", payload, headers)

    def get_cabin(self, cabin_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cabins/{cabin_id}", headers=headers)

    def list_cabins(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cabins", headers=headers, params=params)

    def cabin_maintenance_hold(self, cabin_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabins/{cabin_id}/maintenance-hold", payload, headers
        )

    def cabin_return_to_ready(self, cabin_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabins/{cabin_id}/return-to-ready", payload, headers
        )

    def cabin_turnover_complete(self, cabin_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabins/{cabin_id}/turnover-complete", {}, headers
        )

    # ------------------------------------------------------------------
    # guests
    # ------------------------------------------------------------------
    def create_guest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def list_guests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def sign_waiver(self, guest_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/guests/{guest_id}/waiver-signature", payload, headers
        )

    def revoke_waiver(self, guest_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/guests/{guest_id}/waiver-revocation", {"reason": reason}, headers
        )

    def suspend_guest(self, guest_id: str, target_standing: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/guests/{guest_id}/suspension",
            {"target_standing": target_standing, "reason": reason},
            headers,
        )

    def reinstate_guest(self, guest_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/guests/{guest_id}/reinstatement", {"reason": reason}, headers
        )

    # ------------------------------------------------------------------
    # rider assessments
    # ------------------------------------------------------------------
    def create_rider_assessment(self, guest_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/guests/{guest_id}/rider-assessments", payload, headers
        )

    def get_rider_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rider-assessments/{assessment_id}", headers=headers)

    def list_rider_assessments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rider-assessments", headers=headers, params=params)

    def evaluate_rider_assessment(self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/rider-assessments/{assessment_id}/evaluate", payload, headers
        )

    def flag_re_evaluation(self, assessment_id: str, re_evaluation_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/rider-assessments/{assessment_id}/flag-re-evaluation",
            {"re_evaluation_reason": re_evaluation_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # bookings
    # ------------------------------------------------------------------
    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def post_payment(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/payments", payload, headers)

    def confirm_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/bookings/{booking_id}/cancel", {"reason": reason}, headers
        )

    def check_in_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/check-in", payload, headers)

    def check_out_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/check-out", payload, headers)

    def post_folio_adjustment(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/bookings/{booking_id}/folio-adjustments", payload, headers
        )

    # ------------------------------------------------------------------
    # horses
    # ------------------------------------------------------------------
    def create_horse(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/horses", payload, headers)

    def get_horse(self, horse_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/horses/{horse_id}", headers=headers)

    def list_horses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/horses", headers=headers, params=params)

    def create_health_event(self, horse_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/horses/{horse_id}/health-events", payload, headers)

    def get_health_event(self, health_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/horse-health-events/{health_event_id}", headers=headers
        )

    def list_health_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/horse-health-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # activity slots
    # ------------------------------------------------------------------
    def create_activity_slot(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/seasons/{season_id}/activity-slots", payload, headers
        )

    def get_activity_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/activity-slots/{slot_id}", headers=headers)

    def list_activity_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/activity-slots", headers=headers, params=params)

    def open_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/activity-slots/{slot_id}/open", {}, headers)

    def run_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/activity-slots/{slot_id}/run", {}, headers)

    def complete_slot(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/activity-slots/{slot_id}/complete", payload, headers
        )

    def cancel_slot(self, slot_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/activity-slots/{slot_id}/cancel", {"reason": reason}, headers
        )

    # ------------------------------------------------------------------
    # guide assignments
    # ------------------------------------------------------------------
    def create_guide_assignment(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/activity-slots/{slot_id}/guide-assignments", payload, headers
        )

    def get_guide_assignment(self, guide_assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/guide-assignments/{guide_assignment_id}", headers=headers
        )

    def list_guide_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/guide-assignments", headers=headers, params=params)

    def release_guide_assignment(self, guide_assignment_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/guide-assignments/{guide_assignment_id}/release",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # activity reservations (seats)
    # ------------------------------------------------------------------
    def create_reservation(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/activity-slots/{slot_id}/reservations", payload, headers
        )

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/activity-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/activity-reservations", headers=headers, params=params
        )

    def assign_mount(self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/activity-reservations/{reservation_id}/mount-assignments",
            payload,
            headers,
        )

    def auto_assign_mount(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/activity-reservations/{reservation_id}/mount-auto-assign",
            {},
            headers,
        )

    def release_mount(self, reservation_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/activity-reservations/{reservation_id}/mount-release",
            {"reason": reason},
            headers,
        )

    def check_in_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/activity-reservations/{reservation_id}/check-in", {}, headers
        )

    def cancel_reservation(self, reservation_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/activity-reservations/{reservation_id}/cancel",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # staff members
    # ------------------------------------------------------------------
    def create_staff_member(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/seasons/{season_id}/staff-members", payload, headers
        )

    def get_staff_member(self, staff_member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def list_staff_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def onboard_staff_member(self, staff_member_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/onboard", payload, headers
        )

    def separate_staff_member(self, staff_member_id: str, reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/staff-members/{staff_member_id}/separate",
            {"reason": reason},
            headers,
        )

    def complete_season_for_staff_member(self, staff_member_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/complete-season", {}, headers
        )

    # ------------------------------------------------------------------
    # incident reports
    # ------------------------------------------------------------------
    def create_incident_report(self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/activity-reservations/{reservation_id}/incident-reports",
            payload,
            headers,
        )

    def get_incident_report(self, incident_report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/incident-reports/{incident_report_id}", headers=headers
        )

    def list_incident_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def dispose_incident_report(self, incident_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/incident-reports/{incident_report_id}/dispose", payload, headers
        )

    def close_incident_report(self, incident_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/incident-reports/{incident_report_id}/close", payload, headers
        )


api_client = ApiClient()
