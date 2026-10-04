"""API client: one method per endpoint the PRD declares (all under /v1).

Every method returns the raw ``requests.Response`` so tests assert on the
status code and the envelope. Query filters and pagination go through
``params``; request bodies through ``payload``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the segment-leaderboards API."""

    # ── Logical clock (PlatformAdmin only) ────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ── Athletes ──────────────────────────────────────────────────────────

    def create_athlete(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/athletes", payload, headers)

    def get_athlete(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}", headers=headers)

    def export_athlete(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/export", headers=headers)

    def delete_athlete(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("DELETE", f"/v1/athletes/{athlete_id}", headers=headers)

    # ── Subscriptions ─────────────────────────────────────────────────────

    def create_subscription(self, athlete_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/subscriptions", payload, headers)

    def list_subscriptions(self, athlete_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/subscriptions/{subscription_id}", headers=headers)

    def cancel_subscription(self, subscription_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/subscriptions/{subscription_id}/cancel", payload or {}, headers)

    # ── Privacy zones ─────────────────────────────────────────────────────

    def create_privacy_zone(self, athlete_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/privacy_zones", payload, headers)

    def list_privacy_zones(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/privacy_zones", headers=headers)

    def get_privacy_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/privacy-zones/{zone_id}", headers=headers)

    def update_privacy_zone(self, zone_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PUT", f"/v1/privacy-zones/{zone_id}", payload, headers)

    def disable_privacy_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/privacy-zones/{zone_id}/disable", {}, headers)

    def enable_privacy_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/privacy-zones/{zone_id}/enable", {}, headers)

    # ── Activities ────────────────────────────────────────────────────────

    def upload_activity(self, athlete_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/activities", payload, headers)

    def list_athlete_activities(self, athlete_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/activities", headers=headers, params=params)

    def list_activities(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/activities", headers=headers, params=params)

    def get_activity(self, activity_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/activities/{activity_id}", headers=headers)

    def correct_activity_category(self, activity_id: str, corrected_sport_type: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/activities/{activity_id}/correct_category", {"corrected_sport_type": corrected_sport_type}, headers)

    # ── Segments, efforts, leaderboards ───────────────────────────────────

    def create_segment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/segments", payload, headers)

    def get_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/segments/{segment_id}", headers=headers)

    def list_segments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/segments", headers=headers, params=params)

    def activate_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/segments/{segment_id}/activate", {}, headers)

    def retire_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/segments/{segment_id}/retire", {}, headers)

    def list_segment_efforts(self, segment_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/segments/{segment_id}/efforts", headers=headers, params=params)

    def get_leaderboard(self, segment_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/segments/{segment_id}/leaderboard", headers=headers, params=params)

    def list_athlete_efforts(self, athlete_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/efforts", headers=headers, params=params)

    def list_efforts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/efforts", headers=headers, params=params)

    def get_effort(self, effort_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/efforts/{effort_id}", headers=headers)

    # ── Flags ─────────────────────────────────────────────────────────────

    def create_flag(self, effort_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/efforts/{effort_id}/flags", payload, headers)

    def list_effort_flags(self, effort_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/efforts/{effort_id}/flags", headers=headers, params=params)

    def list_flags(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/flags", headers=headers, params=params)

    def get_flag(self, flag_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/flags/{flag_id}", headers=headers)

    def uphold_flag(self, flag_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/flags/{flag_id}/uphold", {}, headers)

    def reject_flag(self, flag_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/flags/{flag_id}/reject", {}, headers)

    # ── Clubs and memberships ─────────────────────────────────────────────

    def create_club(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/clubs", payload, headers)

    def get_club(self, club_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/clubs/{club_id}", headers=headers)

    def list_clubs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/clubs", headers=headers, params=params)

    def archive_club(self, club_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/archive", {}, headers)

    def join_club(self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/memberships", payload, headers)

    def list_club_memberships(self, club_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/clubs/{club_id}/memberships", headers=headers, params=params)

    def list_memberships(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/memberships", headers=headers, params=params)

    def get_membership(self, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/memberships/{membership_id}", headers=headers)

    def approve_membership(self, club_id: str, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/memberships/{membership_id}/approve", {}, headers)

    def remove_membership(self, club_id: str, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/memberships/{membership_id}/remove", {}, headers)

    def leave_membership(self, club_id: str, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/memberships/{membership_id}/leave", {}, headers)

    # ── Challenges and participations ─────────────────────────────────────

    def create_challenge(self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/challenges", payload, headers)

    def list_club_challenges(self, club_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/clubs/{club_id}/challenges", headers=headers, params=params)

    def list_challenges(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/challenges", headers=headers, params=params)

    def get_challenge(self, challenge_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/challenges/{challenge_id}", headers=headers)

    def start_challenge(self, club_id: str, challenge_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/challenges/{challenge_id}/start", {}, headers)

    def cancel_challenge(self, club_id: str, challenge_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/challenges/{challenge_id}/cancel", {}, headers)

    def join_challenge(self, challenge_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/challenges/{challenge_id}/participations", payload, headers)

    def list_challenge_participations(self, challenge_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/challenges/{challenge_id}/participations", headers=headers, params=params)

    def list_participations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/participations", headers=headers, params=params)

    def get_participation(self, participation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/participations/{participation_id}", headers=headers)

    def withdraw_participation(self, challenge_id: str, participation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/challenges/{challenge_id}/participations/{participation_id}/withdraw", {}, headers)

    # ── Virtual events and RSVPs ──────────────────────────────────────────

    def create_event(self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/events", payload, headers)

    def list_club_events(self, club_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/clubs/{club_id}/events", headers=headers, params=params)

    def list_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/events", headers=headers, params=params)

    def get_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/events/{event_id}", headers=headers)

    def cancel_event(self, club_id: str, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/clubs/{club_id}/events/{event_id}/cancel", {}, headers)

    def create_rsvp(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/events/{event_id}/rsvps", payload, headers)

    def list_event_rsvps(self, event_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/events/{event_id}/rsvps", headers=headers, params=params)

    def list_rsvps(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/rsvps", headers=headers, params=params)

    def get_rsvp(self, rsvp_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/rsvps/{rsvp_id}", headers=headers)

    def decline_rsvp(self, event_id: str, rsvp_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/events/{event_id}/rsvps/{rsvp_id}/decline", {}, headers)

    def rejoin_rsvp(self, event_id: str, rsvp_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/events/{event_id}/rsvps/{rsvp_id}/rejoin", {}, headers)

    # ── Safety contacts, beacon sessions, heat map ────────────────────────

    def create_safety_contact(self, athlete_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/safety_contacts", payload, headers)

    def list_safety_contacts(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/safety_contacts", headers=headers)

    def get_safety_contact(self, contact_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/safety_contacts/{contact_id}", headers=headers)

    def create_beacon_session(self, athlete_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/beacon_sessions", {}, headers)

    def list_beacon_sessions(self, athlete_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/beacon_sessions", headers=headers, params=params)

    def get_beacon_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/beacon_sessions/{session_id}", headers=headers)

    def ping_beacon_session(self, athlete_id: str, session_id: str, lat: float, lng: float, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/beacon_sessions/{session_id}/ping", {"lat": lat, "lng": lng}, headers)

    def stop_beacon_session(self, athlete_id: str, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/beacon_sessions/{session_id}/stop", {}, headers)

    def get_heatmap(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/heatmap", headers=headers, params=params)

    # ── Route plans ───────────────────────────────────────────────────────

    def create_route_plan(self, athlete_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/athletes/{athlete_id}/route_plans", payload, headers)

    def list_route_plans(self, athlete_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/athletes/{athlete_id}/route_plans", headers=headers, params=params)

    def get_route_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/route_plans/{plan_id}", headers=headers)


api_client = ApiClient()
