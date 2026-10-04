"""HTTP client for the Sports Bar Game-Day API.

One method per endpoint the contract declares, plus the admin-only logical
clock control. Every method returns the raw response so tests can assert on
status codes as well as bodies. All paths are prefixed with the API mount
point declared in the contract.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _query(**filters: Any) -> Dict[str, Any]:
    """Drop unset filters so an omitted parameter is genuinely absent."""
    return {key: value for key, value in filters.items() if value is not None}


class ApiClient(GenericApiClient):
    """Endpoint-level client for the game-day operations service."""

    # ── Logical clock (PRD §2.4) ─────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ── Venues ───────────────────────────────────────────────────────────────

    def create_venue(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues/{venue_id}", None, headers)

    def update_wing_cost(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/venues/{venue_id}/wing-cost", payload, headers
        )

    def get_wing_prep_forecast(self, venue_id, headers, date=None, mode=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/forecasts/wing-prep",
            None,
            headers,
            params=_query(date=date, mode=mode),
        )

    def quote_wing_price(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/wing-pricing/quote", payload, headers
        )

    # ── Events ───────────────────────────────────────────────────────────────

    def create_event(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/events", payload, headers)

    def list_events(
        self,
        headers,
        league=None,
        kind=None,
        status=None,
        date_from=None,
        date_to=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/events",
            None,
            headers,
            params=_query(
                league=league,
                kind=kind,
                status=status,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
            ),
        )

    def get_event(self, event_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/events/{event_id}", None, headers)

    def cancel_event(self, event_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/events/{event_id}/cancel", {}, headers
        )

    def list_event_zones(self, event_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/events/{event_id}/zones", None, headers
        )

    def list_event_screen_assignments(self, event_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/events/{event_id}/screen-assignments", None, headers
        )

    def list_event_checks(self, event_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/events/{event_id}/checks", None, headers
        )

    def list_event_ppv_events(self, event_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/events/{event_id}/ppv-events", None, headers
        )

    # ── Broadcast licenses ───────────────────────────────────────────────────

    def create_license(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/licenses", payload, headers
        )

    def list_venue_licenses(self, venue_id, headers, league=None, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/licenses",
            None,
            headers,
            params=_query(league=league, status=status),
        )

    def get_license(self, license_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", None, headers)

    def list_licenses(self, headers, venue_id=None, league=None, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/licenses",
            None,
            headers,
            params=_query(venue_id=venue_id, league=league, status=status),
        )

    def activate_license(self, license_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/activate", {}, headers
        )

    def suspend_license(self, license_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/suspend", {}, headers
        )

    def terminate_license(self, license_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/terminate", {}, headers
        )

    # ── Zones and screen assignments ─────────────────────────────────────────

    def create_zone(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/zones", payload, headers
        )

    def list_venue_zones(self, venue_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/venues/{venue_id}/zones", None, headers
        )

    def list_zones(self, headers, venue_id=None, primary_event_id=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/zones",
            None,
            headers,
            params=_query(venue_id=venue_id, primary_event_id=primary_event_id),
        )

    def get_zone(self, zone_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/zones/{zone_id}", None, headers)

    def create_screen_assignment(self, zone_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/zones/{zone_id}/screen-assignments", payload, headers
        )

    def release_screen_assignment(self, zone_id, assignment_id, headers) -> requests.Response:
        return self._request(
            "DELETE",
            f"{API_PREFIX}/zones/{zone_id}/screen-assignments/{assignment_id}",
            None,
            headers,
        )

    def list_zone_screen_assignments(self, zone_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/zones/{zone_id}/screen-assignments", None, headers
        )

    def get_screen_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/screen-assignments/{assignment_id}", None, headers
        )

    # ── Guests ───────────────────────────────────────────────────────────────

    def create_guest(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/guests", payload, headers)

    def get_guest(self, guest_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/guests/{guest_id}", None, headers)

    def list_venue_guests(self, venue_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/venues/{venue_id}/guests", None, headers
        )

    def list_guest_waitlist_entries(self, guest_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/guests/{guest_id}/waitlist-entries", None, headers
        )

    def list_guest_checks(self, guest_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/guests/{guest_id}/checks", None, headers
        )

    def list_guest_trivia_entries(self, guest_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/guests/{guest_id}/trivia-entries", None, headers
        )

    def list_guest_fantasy_entries(self, guest_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/guests/{guest_id}/fantasy-entries", None, headers
        )

    # ── Waitlist ─────────────────────────────────────────────────────────────

    def join_waitlist(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/waitlist", payload, headers)

    def list_venue_waitlist_entries(self, venue_id, headers, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/waitlist-entries",
            None,
            headers,
            params=_query(status=status),
        )

    def get_waitlist_entry(self, entry_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/waitlist-entries/{entry_id}", None, headers
        )

    def call_waitlist_entry(self, entry_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/waitlist/{entry_id}/call", {}, headers
        )

    def seat_waitlist_entry(self, entry_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/waitlist/{entry_id}/seat", payload, headers
        )

    def cancel_waitlist_entry(self, entry_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/waitlist/{entry_id}/cancel", {}, headers
        )

    # ── Checks and order lines ───────────────────────────────────────────────

    def create_check(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/checks", payload, headers)

    def get_check(self, check_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/checks/{check_id}", None, headers)

    def list_venue_checks(self, venue_id, headers, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/checks",
            None,
            headers,
            params=_query(status=status),
        )

    def list_checks(self, headers, venue_id=None, guest_id=None, event_id=None, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/checks",
            None,
            headers,
            params=_query(
                venue_id=venue_id, guest_id=guest_id, event_id=event_id, status=status
            ),
        )

    def list_check_order_lines(self, check_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/checks/{check_id}/order-lines", None, headers
        )

    def add_order_line(self, check_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/checks/{check_id}/order-lines", payload, headers
        )

    def void_order_line(self, line_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/order-lines/{line_id}/void", {}, headers
        )

    def get_order_line(self, line_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/order-lines/{line_id}", None, headers)

    def settle_check(self, check_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/checks/{check_id}/settle", {}, headers
        )

    def void_check(self, check_id, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/checks/{check_id}/void", {}, headers)

    # ── PPV registrations ────────────────────────────────────────────────────

    def create_ppv_event(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/ppv-events", payload, headers
        )

    def get_ppv_event(self, ppv_event_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/ppv-events/{ppv_event_id}", None, headers
        )

    def list_venue_ppv_events(self, venue_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/venues/{venue_id}/ppv-events", None, headers
        )

    def list_ppv_events(self, headers, venue_id=None, event_id=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/ppv-events",
            None,
            headers,
            params=_query(venue_id=venue_id, event_id=event_id),
        )

    # ── Staffing plans and shifts ────────────────────────────────────────────

    def create_staffing_plan(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/staffing-plans", payload, headers
        )

    def get_staffing_plan(self, plan_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/staffing-plans/{plan_id}", None, headers
        )

    def list_venue_staffing_plans(self, venue_id, headers, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/staffing-plans",
            None,
            headers,
            params=_query(status=status),
        )

    def add_shift(self, plan_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/shifts", payload, headers
        )

    def list_plan_shifts(self, plan_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/staffing-plans/{plan_id}/shifts", None, headers
        )

    def get_shift(self, shift_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shifts/{shift_id}", None, headers)

    def publish_staffing_plan(self, plan_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/publish", {}, headers
        )

    def revert_staffing_plan(self, plan_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/revert", {}, headers
        )

    def lock_staffing_plan(self, plan_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/staffing-plans/{plan_id}/lock", {}, headers
        )

    # ── Promo rules ──────────────────────────────────────────────────────────

    def create_promo_rule(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/promo-rules", payload, headers)

    def get_promo_rule(self, promo_rule_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/promo-rules/{promo_rule_id}", None, headers
        )

    def list_promo_rules(self, headers, day_of_week=None, wing_kind=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/promo-rules",
            None,
            headers,
            params=_query(day_of_week=day_of_week, wing_kind=wing_kind),
        )

    # ── Trivia ───────────────────────────────────────────────────────────────

    def create_trivia_session(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/venues/{venue_id}/trivia-sessions", payload, headers
        )

    def get_trivia_session(self, session_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/trivia-sessions/{session_id}", None, headers
        )

    def list_venue_trivia_sessions(self, venue_id, headers, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/trivia-sessions",
            None,
            headers,
            params=_query(status=status),
        )

    def create_trivia_entry(self, session_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/trivia-sessions/{session_id}/entries",
            payload,
            headers,
        )

    def list_session_trivia_entries(self, session_id, headers) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/trivia-sessions/{session_id}/trivia-entries",
            None,
            headers,
        )

    def get_trivia_entry(self, entry_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/trivia-entries/{entry_id}", None, headers
        )

    def submit_trivia_answer(self, entry_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/trivia-entries/{entry_id}/answers", payload, headers
        )

    def close_trivia_session(self, session_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/trivia-sessions/{session_id}/close", {}, headers
        )

    def settle_trivia_session(self, session_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/trivia-sessions/{session_id}/settle", {}, headers
        )

    # ── Fantasy contests ─────────────────────────────────────────────────────

    def create_fantasy_contest(self, venue_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/venues/{venue_id}/fantasy-contests",
            payload,
            headers,
        )

    def get_fantasy_contest(self, contest_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/fantasy-contests/{contest_id}", None, headers
        )

    def list_venue_fantasy_contests(self, venue_id, headers, status=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/venues/{venue_id}/fantasy-contests",
            None,
            headers,
            params=_query(status=status),
        )

    def open_fantasy_contest(self, contest_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fantasy-contests/{contest_id}/open", {}, headers
        )

    def create_fantasy_entry(self, contest_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/fantasy-contests/{contest_id}/entries",
            payload,
            headers,
        )

    def list_contest_fantasy_entries(self, contest_id, headers) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/fantasy-contests/{contest_id}/fantasy-entries",
            None,
            headers,
        )

    def get_fantasy_entry(self, entry_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/fantasy-entries/{entry_id}", None, headers
        )

    def lock_fantasy_contest(self, contest_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fantasy-contests/{contest_id}/lock", {}, headers
        )

    def settle_fantasy_contest(self, contest_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fantasy-contests/{contest_id}/settle", payload, headers
        )

    def cancel_fantasy_contest(self, contest_id, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fantasy-contests/{contest_id}/cancel", {}, headers
        )


api_client = ApiClient()
