"""Endpoint methods for the Neighborhood Swim Club API (PRD §4).

Every path is mounted under ``/swim-club``. Each method returns the raw
``requests.Response`` so tests can assert on status codes themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an ISO-8601 UTC instant to second precision with a trailing ``Z``.

    PRD §2.4 pins server-minted timestamps at "exactly three fractional
    digits", but the instants a test *pins* (a ``voided_at``, a
    ``closure_started_at``, an ``offer_expires_at``) are only meaningful to the
    second. Comparing canonical forms keeps a legitimate ``.000`` suffix from
    reading as a mismatch.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    if "." in text:
        text = text.split(".", 1)[0]
    return text + "Z"


class ApiClient(GenericApiClient):
    """One method per row of the PRD §4 endpoint table."""

    # ── Seasons ───────────────────────────────────────
    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/seasons", payload, headers)

    def open_season(self, season_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/seasons/{season_id}/open", payload or {}, headers
        )

    def close_season(self, season_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/seasons/{season_id}/close", payload or {}, headers
        )

    def run_billing_run(self, season_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/seasons/{season_id}/billing-runs",
            payload or {}, headers,
        )

    def create_reserve_contribution(self, season_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/seasons/{season_id}/reserve-contributions",
            payload, headers,
        )

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/seasons/{season_id}", None, headers)

    def list_seasons(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/seasons", params, headers)

    def get_staffing_window(self, season_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/seasons/{season_id}/staffing-window",
            params, headers,
        )

    # ── Membership categories ─────────────────────────
    def create_membership_category(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/membership-categories", payload, headers
        )

    def get_membership_category(self, category_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/membership-categories/{category_id}", None, headers
        )

    def list_membership_categories(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/membership-categories", params, headers
        )

    # ── Households ────────────────────────────────────
    def create_household(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/households", payload, headers)

    def create_standing_transition(self, household_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/households/{household_id}/standing-transitions",
            payload, headers,
        )

    def create_household_payment(self, household_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/households/{household_id}/payments",
            payload, headers,
        )

    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/households/{household_id}", None, headers
        )

    def list_households(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/households", params, headers)

    # ── Waitlist entries ──────────────────────────────
    def create_waitlist_entry(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/waitlist-entries", payload, headers
        )

    def next_waitlist_offer(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/waitlist-entries/next-offer", payload, headers
        )

    def respond_waitlist_entry(self, entry_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/waitlist-entries/{entry_id}/respond",
            payload, headers,
        )

    def get_waitlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/waitlist-entries/{entry_id}", None, headers
        )

    def list_waitlist_entries(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/waitlist-entries", params, headers
        )

    # ── Memberships ───────────────────────────────────
    def create_membership(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/memberships", payload, headers)

    def invoice_membership(self, membership_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/memberships/{membership_id}/invoice",
            payload or {}, headers,
        )

    def create_membership_payment(self, membership_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/memberships/{membership_id}/payments",
            payload, headers,
        )

    def write_off_membership(self, membership_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/memberships/{membership_id}/write-off",
            payload, headers,
        )

    def get_membership(self, membership_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/memberships/{membership_id}", None, headers
        )

    def list_memberships(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/memberships", params, headers)

    # ── Guest visits ──────────────────────────────────
    def create_guest_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/guest-visits", payload, headers)

    def void_guest_visit(self, visit_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/guest-visits/{visit_id}/void", payload, headers
        )

    def get_guest_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/guest-visits/{visit_id}", None, headers
        )

    def list_guest_visits(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/guest-visits", params, headers)

    # ── Lifeguards ────────────────────────────────────
    def create_lifeguard(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/lifeguards", payload, headers)

    def get_lifeguard(self, lifeguard_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/lifeguards/{lifeguard_id}", None, headers
        )

    def list_lifeguards(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/lifeguards", params, headers)

    # ── Certifications ────────────────────────────────
    def create_certification(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/certifications", payload, headers
        )

    def revoke_certification(self, certification_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/certifications/{certification_id}/revoke",
            payload, headers,
        )

    def get_certification(self, certification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/certifications/{certification_id}", None, headers
        )

    def list_certifications(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/certifications", params, headers)

    # ── Guard shifts ──────────────────────────────────
    def create_guard_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/guard-shifts", payload, headers)

    def transition_guard_shift(self, shift_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/guard-shifts/{shift_id}/transitions",
            payload, headers,
        )

    def get_guard_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/guard-shifts/{shift_id}", None, headers
        )

    def list_guard_shifts(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/guard-shifts", params, headers)

    # ── Swim-team registrations ───────────────────────
    def create_registration(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/swim-team-registrations", payload, headers
        )

    def transition_registration(self, registration_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/swim-team-registrations/{registration_id}/transitions",
            payload, headers,
        )

    def get_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/swim-team-registrations/{registration_id}",
            None, headers,
        )

    def list_registrations(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/swim-team-registrations", params, headers
        )

    # ── Meets ─────────────────────────────────────────
    def create_meet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/meets", payload, headers)

    def close_meet_roster(self, meet_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/meets/{meet_id}/close-roster",
            payload or {}, headers,
        )

    def transition_meet(self, meet_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/meets/{meet_id}/transitions", payload, headers
        )

    def get_meet(self, meet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/meets/{meet_id}", None, headers)

    def list_meets(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/meets", params, headers)

    # ── Volunteer assignments ─────────────────────────
    def create_volunteer_assignment(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/volunteer-assignments", payload, headers
        )

    def transition_volunteer_assignment(self, assignment_id: str,
                                        payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/volunteer-assignments/{assignment_id}/transitions",
            payload, headers,
        )

    def get_volunteer_assignment(self, assignment_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/volunteer-assignments/{assignment_id}",
            None, headers,
        )

    def list_volunteer_assignments(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/volunteer-assignments", params, headers
        )

    # ── Party reservations ────────────────────────────
    def create_party_reservation(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/party-reservations", payload, headers
        )

    def transition_party_reservation(self, reservation_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/party-reservations/{reservation_id}/transitions",
            payload, headers,
        )

    def get_party_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/party-reservations/{reservation_id}", None, headers
        )

    def list_party_reservations(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/party-reservations", params, headers
        )

    # ── Inspection findings ───────────────────────────
    def create_inspection_finding(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-findings", payload, headers
        )

    def transition_inspection_finding(self, finding_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-findings/{finding_id}/transitions",
            payload, headers,
        )

    def get_inspection_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/inspection-findings/{finding_id}", None, headers
        )

    def list_inspection_findings(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/inspection-findings", params, headers
        )

    # ── Conduct cases ─────────────────────────────────
    def create_conduct_case(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/conduct-cases", payload, headers
        )

    def transition_conduct_case(self, case_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/conduct-cases/{case_id}/transitions",
            payload, headers,
        )

    def get_conduct_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/conduct-cases/{case_id}", None, headers
        )

    def list_conduct_cases(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/conduct-cases", params, headers)

    # ── Capital projects ──────────────────────────────
    def create_capital_project(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/capital-projects", payload, headers
        )

    def transition_capital_project(self, project_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/capital-projects/{project_id}/transitions",
            payload, headers,
        )

    def fund_capital_project(self, project_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/capital-projects/{project_id}/fund",
            payload, headers,
        )

    def get_capital_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/capital-projects/{project_id}", None, headers
        )

    def list_capital_projects(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/capital-projects", params, headers
        )

    # ── Logical clock ─────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


# A single shared instance; the runner injects API_BASE_URL into the environment.
api_client = ApiClient()
