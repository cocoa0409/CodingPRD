"""
HTTP client for the Hospital Sitter & Continuous Observation Staffing API.

**Envelope contract for this suite (decided once, here).** Every method on
``ObservationApiClient`` returns the raw ``requests.Response`` — never a parsed
body and never an unwrapped ``data`` payload. Unwrapping happens in exactly one
place: the generic validators (``validate_success`` / ``validate_paginated`` /
``get_success_data``) which return the envelope's ``data`` member. Every
assertion helper in ``assertions.py`` therefore takes an already-unwrapped
resource dict and must never index ``["data"]`` again.

**Timestamp canonicalisation (single point).** PRD section 2.4 renders every
logical-clock instant "as an ISO 8601 UTC instant with exactly three fractional
digits (for example ``2026-08-01T00:00:00.000Z``)". ``canonical_instant`` below
is the only place that formatting lives: request payloads are normalised on the
way out by ``_normalise_payload``, and ``assertions.assert_instant`` normalises
both sides before comparing, so a change in declared precision is a one-line fix.
"""

import re
from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

# ─── Instant canonicalisation ─────────────────────────

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00|)$"
)

# Payload keys that carry an ISO 8601 UTC instant and are normalised on the wire.
INSTANT_FIELDS = frozenset(
    {
        "current_utc",
        "close_through_utc",
        "deescalation_cert_expires_on",
        "shift_start_at",
        "shift_end_at",
        "monitor_start_at",
        "monitor_end_at",
    }
)


def canonical_instant(value: str) -> str:
    """
    Render an ISO 8601 UTC instant in the PRD's canonical form: exactly three
    fractional digits and a trailing ``Z`` (for example ``2026-08-01T00:00:00.000Z``).

    Inputs already in that form are returned unchanged. Inputs that are not
    instants at all (a sentinel, a deliberately malformed literal a negative test
    wants to send verbatim) are returned untouched so the server still sees them.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    day, clock, frac = match.group(1), match.group(2), match.group(3) or ""
    millis = (frac + "000")[:3]
    return f"{day}T{clock}.{millis}Z"


def instant(value: str, *, hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    """
    Canonical instant literal, optionally offset by whole hours/minutes/seconds.

    Used so a test can write the PRD's own arithmetic ("that instant advanced by
    ``reassessment_interval_hours`` hours") instead of a hand-computed literal.
    """
    import datetime as _dt

    match = _INSTANT_RE.match(value.strip())
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    frac = (match.group(3) or "") + "000"
    base = _dt.datetime(
        int(match.group(1)[0:4]),
        int(match.group(1)[5:7]),
        int(match.group(1)[8:10]),
        int(match.group(2)[0:2]),
        int(match.group(2)[3:5]),
        int(match.group(2)[6:8]),
        int(frac[:3]) * 1000,
        tzinfo=_dt.timezone.utc,
    )
    moved = base + _dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return (
        f"{moved.year:04d}-{moved.month:02d}-{moved.day:02d}"
        f"T{moved.hour:02d}:{moved.minute:02d}:{moved.second:02d}"
        f".{moved.microsecond // 1000:03d}Z"
    )


def minutes_between(start: str, end: str) -> int:
    """Whole minutes elapsed between two instants, discarding any partial minute."""
    import datetime as _dt

    def _parse(v: str) -> "_dt.datetime":
        m = _INSTANT_RE.match(v.strip())
        assert m, f"Not an ISO 8601 UTC instant: {v!r}"
        frac = (m.group(3) or "") + "000"
        return _dt.datetime(
            int(m.group(1)[0:4]),
            int(m.group(1)[5:7]),
            int(m.group(1)[8:10]),
            int(m.group(2)[0:2]),
            int(m.group(2)[3:5]),
            int(m.group(2)[6:8]),
            int(frac[:3]) * 1000,
            tzinfo=_dt.timezone.utc,
        )

    return int((_parse(end) - _parse(start)).total_seconds() // 60)


def _normalise_payload(payload: Any) -> Any:
    """Canonicalise every instant-bearing key on the way out to the server."""
    if isinstance(payload, dict):
        return {
            key: (
                canonical_instant(value)
                if key in INSTANT_FIELDS and isinstance(value, str)
                else _normalise_payload(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_normalise_payload(item) for item in payload]
    return payload


class ObservationApiClient(GenericApiClient):
    """
    One method per endpoint of PRD section 4. Every method returns the raw
    ``requests.Response`` so a test can assert on the HTTP status itself.
    """

    # ─── internals ────────────────────────────────────

    def _post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> requests.Response:
        body = {} if payload is None else _normalise_payload(payload)
        return self._request("POST", f"{API_PREFIX}{path}", body, headers)

    def _get(
        self,
        path: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}{path}", params, headers)

    # ─── units (PRD 3.1 / 3.9) ────────────────────────

    def create_unit(self, payload, headers) -> requests.Response:
        return self._post("/units", payload, headers)

    def list_units(self, headers, params=None) -> requests.Response:
        return self._get("/units", headers, params)

    def get_unit(self, unit_id, headers) -> requests.Response:
        return self._get(f"/units/{unit_id}", headers)

    def list_unit_patients(self, unit_id, headers, params=None) -> requests.Response:
        return self._get(f"/units/{unit_id}/patients", headers, params)

    def list_unit_staff(self, unit_id, headers, params=None) -> requests.Response:
        return self._get(f"/units/{unit_id}/staff", headers, params)

    def list_unit_cost_entries(self, unit_id, headers, params=None) -> requests.Response:
        return self._get(f"/units/{unit_id}/cost-entries", headers, params)

    def cost_close(self, unit_id, payload, headers) -> requests.Response:
        return self._post(f"/units/{unit_id}/cost-close", payload, headers)

    # ─── patients (PRD 3.1 / 3.9) ─────────────────────

    def create_patient(self, payload, headers) -> requests.Response:
        return self._post("/patients", payload, headers)

    def get_patient(self, patient_id, headers) -> requests.Response:
        return self._get(f"/patients/{patient_id}", headers)

    def list_patient_orders(self, patient_id, headers, params=None) -> requests.Response:
        return self._get(f"/patients/{patient_id}/orders", headers, params)

    def discharge_patient(self, patient_id, headers) -> requests.Response:
        return self._post(f"/patients/{patient_id}/discharge", None, headers)

    # ─── staff (PRD 3.1) ──────────────────────────────

    def create_staff(self, payload, headers) -> requests.Response:
        return self._post("/staff", payload, headers)

    def list_staff(self, headers, params=None) -> requests.Response:
        return self._get("/staff", headers, params)

    def get_staff(self, staff_id, headers) -> requests.Response:
        return self._get(f"/staff/{staff_id}", headers)

    def list_staff_assignments(self, staff_id, headers, params=None) -> requests.Response:
        return self._get(f"/staff/{staff_id}/sitter-assignments", headers, params)

    def list_staff_stations(self, staff_id, headers, params=None) -> requests.Response:
        return self._get(f"/staff/{staff_id}/monitoring-stations", headers, params)

    def record_certification(self, staff_id, payload, headers) -> requests.Response:
        return self._post(f"/staff/{staff_id}/certifications", payload, headers)

    # ─── observation orders (PRD 3.2 / 3.3 / 3.9) ─────

    def create_order(self, payload, headers) -> requests.Response:
        return self._post("/orders", payload, headers)

    def list_orders(self, headers, params=None) -> requests.Response:
        return self._get("/orders", headers, params)

    def get_order(self, order_id, headers) -> requests.Response:
        return self._get(f"/orders/{order_id}", headers)

    def list_order_assignments(self, order_id, headers, params=None) -> requests.Response:
        return self._get(f"/orders/{order_id}/sitter-assignments", headers, params)

    def list_order_reassessments(self, order_id, headers, params=None) -> requests.Response:
        return self._get(f"/orders/{order_id}/reassessments", headers, params)

    def list_order_feeds(self, order_id, headers, params=None) -> requests.Response:
        return self._get(f"/orders/{order_id}/video-feeds", headers, params)

    def list_order_safety_events(self, order_id, headers, params=None) -> requests.Response:
        return self._get(f"/orders/{order_id}/safety-events", headers, params)

    def create_reassessment(self, order_id, payload, headers) -> requests.Response:
        return self._post(f"/orders/{order_id}/reassessments", payload, headers)

    def open_discontinuation_review(self, order_id, payload, headers) -> requests.Response:
        return self._post(f"/orders/{order_id}/discontinuation-review", payload, headers)

    def decide_discontinuation(self, order_id, payload, headers) -> requests.Response:
        return self._post(f"/orders/{order_id}/discontinuation-decision", payload, headers)

    def get_reassessment(self, reassessment_id, headers) -> requests.Response:
        return self._get(f"/reassessments/{reassessment_id}", headers)

    # ─── sitter assignments (PRD 3.4 / 3.5) ───────────

    def create_assignment(self, payload, headers) -> requests.Response:
        return self._post("/sitter-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers) -> requests.Response:
        return self._get(f"/sitter-assignments/{assignment_id}", headers)

    def list_assignment_handoffs(self, assignment_id, headers, params=None) -> requests.Response:
        return self._get(f"/sitter-assignments/{assignment_id}/handoffs", headers, params)

    def list_assignment_cost_entries(self, assignment_id, headers, params=None) -> requests.Response:
        return self._get(f"/sitter-assignments/{assignment_id}/cost-entries", headers, params)

    def list_assignment_safety_events(self, assignment_id, headers, params=None) -> requests.Response:
        return self._get(f"/sitter-assignments/{assignment_id}/safety-events", headers, params)

    def start_watch(self, assignment_id, headers) -> requests.Response:
        return self._post(f"/sitter-assignments/{assignment_id}/start-watch", None, headers)

    def break_start(self, assignment_id, headers) -> requests.Response:
        return self._post(f"/sitter-assignments/{assignment_id}/break-start", None, headers)

    def break_end(self, assignment_id, headers) -> requests.Response:
        return self._post(f"/sitter-assignments/{assignment_id}/break-end", None, headers)

    def complete_watch(self, assignment_id, payload, headers) -> requests.Response:
        return self._post(f"/sitter-assignments/{assignment_id}/complete", payload, headers)

    def void_assignment(self, assignment_id, headers) -> requests.Response:
        return self._post(f"/sitter-assignments/{assignment_id}/void", None, headers)

    # ─── handoffs (PRD 3.6) ───────────────────────────

    def create_handoff(self, payload, headers) -> requests.Response:
        return self._post("/handoffs", payload, headers)

    def get_handoff(self, handoff_id, headers) -> requests.Response:
        return self._get(f"/handoffs/{handoff_id}", headers)

    def countersign_handoff(self, handoff_id, headers) -> requests.Response:
        return self._post(f"/handoffs/{handoff_id}/countersign", None, headers)

    # ─── consoles and feeds (PRD 3.7) ─────────────────

    def create_station(self, payload, headers) -> requests.Response:
        return self._post("/monitoring-stations", payload, headers)

    def get_station(self, station_id, headers) -> requests.Response:
        return self._get(f"/monitoring-stations/{station_id}", headers)

    def list_station_feeds(self, station_id, headers, params=None) -> requests.Response:
        return self._get(f"/monitoring-stations/{station_id}/video-feeds", headers, params)

    def offline_station(self, station_id, headers) -> requests.Response:
        return self._post(f"/monitoring-stations/{station_id}/offline", None, headers)

    def create_feed(self, payload, headers) -> requests.Response:
        return self._post("/video-feeds", payload, headers)

    def get_feed(self, feed_id, headers) -> requests.Response:
        return self._get(f"/video-feeds/{feed_id}", headers)

    def release_feed(self, feed_id, headers) -> requests.Response:
        return self._post(f"/video-feeds/{feed_id}/release", None, headers)

    # ─── safety events (PRD 3.8) ──────────────────────

    def create_safety_event(self, payload, headers) -> requests.Response:
        return self._post("/safety-events", payload, headers)

    def get_safety_event(self, event_id, headers) -> requests.Response:
        return self._get(f"/safety-events/{event_id}", headers)

    def escalate_response(self, event_id, payload, headers) -> requests.Response:
        return self._post(f"/safety-events/{event_id}/escalate-response", payload, headers)

    def open_incident_review(self, event_id, headers) -> requests.Response:
        return self._post(f"/safety-events/{event_id}/open-incident-review", None, headers)

    def close_safety_event(self, event_id, payload, headers) -> requests.Response:
        return self._post(f"/safety-events/{event_id}/close", payload, headers)

    # ─── cost ledger (PRD 2.10) ───────────────────────

    def get_cost_entry(self, cost_entry_id, headers) -> requests.Response:
        return self._get(f"/cost-entries/{cost_entry_id}", headers)

    # ─── logical clock (PRD 2.4 / 3.3) ────────────────

    def set_clock(self, payload, headers) -> requests.Response:
        return self._post("/_clock/set_current_utc", payload, headers)
