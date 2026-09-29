"""API client: one method per endpoint the PRD defines.

The base class supplies the HTTP plumbing; everything here is domain specific.
Two small utilities also live here because they are properties of the wire
format rather than of any single test:

* ``canonical_instant`` normalises an ISO 8601 UTC instant so that a value the
  API returns with three fractional digits compares equal to the same instant
  written without them.  The PRD allows an instant supplied to the API to carry
  zero or exactly three fractional digits, so tests must never assume a width.
* ``same_instant`` is the comparison built on top of it.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Return an ISO 8601 UTC instant with exactly three fractional digits.

    Sub-second precision is normalised, never assumed: '...T09:00:00Z',
    '...T09:00:00.0Z' and '...T09:00:00.000Z' all canonicalise identically.
    Values that are not instants (including None) are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    m = _INSTANT_RE.match(value)
    if not m:
        return value
    seconds, frac = m.group(1), m.group(2) or ""
    frac = (frac + "000")[:3]
    return f"{seconds}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when both values denote the same UTC instant, ignoring precision."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint, named in the language of the domain."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Pop-up venues ──────────────────────────────────────────────────────

    def create_venue(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def submit_permit_package(self, venue_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/venues/{venue_id}/permit-submissions", payload, headers
        )

    def decide_permit(self, venue_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/venues/{venue_id}/permit-decisions", payload, headers
        )

    def activate_lease(self, venue_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/activate-lease", {}, headers)

    def end_lease(self, venue_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/end-lease", {}, headers)

    def draw_buildout(self, venue_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/venues/{venue_id}/buildout-draws", payload, headers
        )

    # ── Licence agreements ─────────────────────────────────────────────────

    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/license-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/license-agreements/{agreement_id}",
                             headers=headers)

    def list_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/license-agreements", headers=headers,
                             params=params)

    def activate_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/activate", {}, headers
        )

    def expire_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/expire", {}, headers
        )

    # ── Creative submissions ───────────────────────────────────────────────

    def create_submission(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/creative-submissions", payload, headers)

    def get_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/creative-submissions/{submission_id}",
                             headers=headers)

    def list_submissions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/creative-submissions", headers=headers,
                             params=params)

    def start_submission_review(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/creative-submissions/{submission_id}/start-review", {}, headers
        )

    def decide_submission(self, submission_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/creative-submissions/{submission_id}/decisions", payload, headers
        )

    def resubmit_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/creative-submissions/{submission_id}/resubmit", {}, headers
        )

    # ── Experience runs ────────────────────────────────────────────────────

    def create_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/experience-runs", payload, headers)

    def get_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/experience-runs/{run_id}", headers=headers)

    def list_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/experience-runs", headers=headers, params=params)

    def open_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/experience-runs/{run_id}/open", {}, headers)

    def grant_extension(self, run_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/experience-runs/{run_id}/extensions", payload, headers
        )

    def decide_closure(self, run_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/experience-runs/{run_id}/closure-decisions", payload, headers
        )

    def lift_suspension(self, run_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/experience-runs/{run_id}/lift-suspension", payload, headers
        )

    def get_demand_index(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/experience-runs/{run_id}/demand-index",
                             headers=headers)

    # ── Themed rooms ───────────────────────────────────────────────────────

    def create_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/themed-rooms", payload, headers)

    def get_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/themed-rooms/{room_id}", headers=headers)

    def list_rooms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/themed-rooms", headers=headers, params=params)

    # ── Timed-entry slots ──────────────────────────────────────────────────

    def create_slot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/timed-entry-slots", payload, headers)

    def get_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/timed-entry-slots/{slot_id}", headers=headers)

    def list_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/timed-entry-slots", headers=headers, params=params)

    def release_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/timed-entry-slots/{slot_id}/release", {}, headers)

    def decide_slot_status(self, slot_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/timed-entry-slots/{slot_id}/status-decisions", payload, headers
        )

    def get_price_quote(self, slot_id: str, params: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/timed-entry-slots/{slot_id}/price-quote", headers=headers,
            params=params,
        )

    # ── Guest accounts ─────────────────────────────────────────────────────

    def create_guest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/guest-accounts", payload, headers)

    def get_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/guest-accounts/{guest_id}", headers=headers)

    def patch_guest(self, guest_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("PATCH", f"/guest-accounts/{guest_id}", payload, headers)

    def reinstate_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/guest-accounts/{guest_id}/reinstate", {}, headers)

    # ── Ticket orders ──────────────────────────────────────────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ticket-orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ticket-orders/{order_id}", headers=headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ticket-orders", headers=headers, params=params)

    def confirm_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/ticket-orders/{order_id}/confirm", {}, headers)

    def record_attendance(self, order_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/ticket-orders/{order_id}/attendance", payload, headers
        )

    def cancel_order(self, order_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/ticket-orders/{order_id}/cancel", payload, headers
        )

    def settle_refund(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ticket-orders/{order_id}/settle-refund", {}, headers
        )

    # ── Staff members ──────────────────────────────────────────────────────

    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def add_training_record(self, staff_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/staff-members/{staff_id}/training-records", payload, headers
        )

    def decide_staff_status(self, staff_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/staff-members/{staff_id}/status-decisions", payload, headers
        )

    # ── Staff shifts ───────────────────────────────────────────────────────

    def create_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/staff-shifts", payload, headers)

    def get_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/staff-shifts", headers=headers, params=params)

    def decide_shift_status(self, shift_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/staff-shifts/{shift_id}/status-decisions", payload, headers
        )

    # ── Safety inspections ─────────────────────────────────────────────────

    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/safety-inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/safety-inspections/{inspection_id}",
                             headers=headers)

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/safety-inspections", headers=headers,
                             params=params)

    def finalize_inspection(self, inspection_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/safety-inspections/{inspection_id}/finalize", payload, headers
        )

    def void_inspection(self, inspection_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/safety-inspections/{inspection_id}/void", payload, headers
        )

    # ── Build kits ─────────────────────────────────────────────────────────

    def create_kit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/build-kits", payload, headers)

    def get_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/build-kits/{kit_id}", headers=headers)

    def list_kits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/build-kits", headers=headers, params=params)

    def refurbish_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/build-kits/{kit_id}/refurbish", {}, headers)

    def localize_kit(self, kit_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/build-kits/{kit_id}/localize", payload, headers)

    # ── Royalty statements ─────────────────────────────────────────────────

    def create_statement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/royalty-statements", payload, headers)

    def get_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/royalty-statements/{statement_id}",
                             headers=headers)

    def list_statements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/royalty-statements", headers=headers,
                             params=params)

    def recompute_provisional(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty-statements/{statement_id}/recompute-provisional",
            {}, headers,
        )

    def finalize_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty-statements/{statement_id}/finalize", {}, headers
        )

    def settle_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty-statements/{statement_id}/settle", {}, headers
        )


api_client = ApiClient()
