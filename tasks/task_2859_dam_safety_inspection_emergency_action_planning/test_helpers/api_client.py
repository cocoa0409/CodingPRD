"""HTTP client with one method per endpoint declared by the PRD.

Also provides ISO-8601 canonicalisation helpers: the PRD renders instants with
three fractional digits, so comparisons against literal expectations normalise
sub-second precision before comparing.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 instant so sub-second precision never breaks equality.

    ``2026-08-01T00:00:00Z``, ``2026-08-01T00:00:00.000Z`` and
    ``2026-08-01T00:00:00.000000Z`` all canonicalise to the same string.
    Non-instant values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, _offset = match.groups()
    frac = (frac or "").rstrip("0")
    if frac:
        return f"{date_part}T{time_part}.{frac}Z"
    return f"{date_part}T{time_part}Z"


def instants_equal(actual: Any, expected: Any) -> bool:
    """True when two instants denote the same moment, ignoring trailing zeros."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD's endpoint catalogue."""

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------
    def create_owner(self, payload: dict, headers: dict):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: dict):
        return self._request("GET", f"/owners/{owner_id}", None, headers)

    def list_owners(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/owners", params, headers)

    def create_fee_adjustment(self, owner_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/owners/{owner_id}/fee-adjustments", payload, headers
        )

    def list_fee_ledger_entries(
        self, owner_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/owners/{owner_id}/fee-ledger-entries", params, headers
        )

    # ------------------------------------------------------------------
    # Engineers
    # ------------------------------------------------------------------
    def create_engineer(self, payload: dict, headers: dict):
        return self._request("POST", "/engineers", payload, headers)

    def get_engineer(self, engineer_id: str, headers: dict):
        return self._request("GET", f"/engineers/{engineer_id}", None, headers)

    def list_engineers(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/engineers", params, headers)

    # ------------------------------------------------------------------
    # River reaches
    # ------------------------------------------------------------------
    def create_river_reach(self, payload: dict, headers: dict):
        return self._request("POST", "/river-reaches", payload, headers)

    def get_river_reach(self, reach_id: str, headers: dict):
        return self._request("GET", f"/river-reaches/{reach_id}", None, headers)

    def list_river_reaches(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/river-reaches", params, headers)

    # ------------------------------------------------------------------
    # Dams
    # ------------------------------------------------------------------
    def create_dam(self, payload: dict, headers: dict):
        return self._request("POST", "/dams", payload, headers)

    def get_dam(self, dam_id: str, headers: dict):
        return self._request("GET", f"/dams/{dam_id}", None, headers)

    def list_dams(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/dams", params, headers)

    def get_compliance_summary(self, dam_id: str, headers: dict):
        return self._request(
            "GET", f"/dams/{dam_id}/compliance-summary", None, headers
        )

    def state_intervention(self, dam_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/dams/{dam_id}/state-intervention", payload, headers
        )

    # ------------------------------------------------------------------
    # Consequence assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload: dict, headers: dict):
        return self._request("POST", "/consequence-assessments", payload, headers)

    def get_assessment(self, assessment_id: str, headers: dict):
        return self._request(
            "GET", f"/consequence-assessments/{assessment_id}", None, headers
        )

    def list_assessments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/consequence-assessments", params, headers)

    def certify_assessment(
        self, assessment_id: str, payload: Optional[dict], headers: dict
    ):
        return self._request(
            "POST",
            f"/consequence-assessments/{assessment_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload: dict, headers: dict):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: dict):
        return self._request("GET", f"/inspections/{inspection_id}", None, headers)

    def list_inspections(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/inspections", params, headers)

    def submit_inspection(self, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/inspections/{inspection_id}/submit", payload, headers
        )

    def accept_inspection(
        self, inspection_id: str, payload: Optional[dict], headers: dict
    ):
        return self._request(
            "POST",
            f"/inspections/{inspection_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def return_inspection(self, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/inspections/{inspection_id}/return", payload, headers
        )

    # ------------------------------------------------------------------
    # Deficiencies
    # ------------------------------------------------------------------
    def get_deficiency(self, deficiency_id: str, headers: dict):
        return self._request("GET", f"/deficiencies/{deficiency_id}", None, headers)

    def list_deficiencies(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/deficiencies", params, headers)

    def create_remediation_order(self, deficiency_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/deficiencies/{deficiency_id}/remediation-orders", payload, headers
        )

    # ------------------------------------------------------------------
    # Remediation orders
    # ------------------------------------------------------------------
    def get_remediation_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/remediation-orders/{order_id}", None, headers)

    def list_remediation_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/remediation-orders", params, headers)

    def get_penalty_preview(self, order_id: str, headers: dict):
        return self._request(
            "GET", f"/remediation-orders/{order_id}/penalty-preview", None, headers
        )

    def file_order_response(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/remediation-orders/{order_id}/response", payload, headers
        )

    def verify_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/remediation-orders/{order_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Emergency action plans
    # ------------------------------------------------------------------
    def create_eap(self, payload: dict, headers: dict):
        return self._request("POST", "/emergency-action-plans", payload, headers)

    def get_eap(self, eap_id: str, headers: dict):
        return self._request(
            "GET", f"/emergency-action-plans/{eap_id}", None, headers
        )

    def list_eaps(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/emergency-action-plans", params, headers)

    def submit_eap(self, eap_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST",
            f"/emergency-action-plans/{eap_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_eap(self, eap_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/emergency-action-plans/{eap_id}/review", payload, headers
        )

    def create_exercise(self, eap_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/emergency-action-plans/{eap_id}/exercises", payload, headers
        )

    def list_exercises(self, eap_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/emergency-action-plans/{eap_id}/exercises", params, headers
        )

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, payload: dict, headers: dict):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id: str, headers: dict):
        return self._request("GET", f"/permits/{permit_id}", None, headers)

    def list_permits(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/permits", params, headers)

    def assign_permit_review(self, permit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/permits/{permit_id}/assign-review", payload, headers
        )

    def decide_permit(self, permit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/permits/{permit_id}/decision", payload, headers
        )

    def resubmit_permit(self, permit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/permits/{permit_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # High-water events
    # ------------------------------------------------------------------
    def create_event(self, payload: dict, headers: dict):
        return self._request("POST", "/high-water-events", payload, headers)

    def get_event(self, event_id: str, headers: dict):
        return self._request("GET", f"/high-water-events/{event_id}", None, headers)

    def list_events(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/high-water-events", params, headers)

    def create_reading(self, event_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/high-water-events/{event_id}/readings", payload, headers
        )

    def list_readings(self, event_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/high-water-events/{event_id}/readings", params, headers
        )

    def stand_down_event(self, event_id: str, payload: Optional[dict], headers: dict):
        return self._request(
            "POST",
            f"/high-water-events/{event_id}/stand-down",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Drawdown orders
    # ------------------------------------------------------------------
    def create_drawdown_order(self, payload: dict, headers: dict):
        return self._request("POST", "/drawdown-orders", payload, headers)

    def get_drawdown_order(self, drawdown_id: str, headers: dict):
        return self._request("GET", f"/drawdown-orders/{drawdown_id}", None, headers)

    def list_drawdown_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/drawdown-orders", params, headers)

    def coordinate_drawdown(self, drawdown_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/drawdown-orders/{drawdown_id}/coordinate", payload, headers
        )

    def activate_drawdown(
        self, drawdown_id: str, payload: Optional[dict], headers: dict
    ):
        return self._request(
            "POST",
            f"/drawdown-orders/{drawdown_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def complete_drawdown(self, drawdown_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/drawdown-orders/{drawdown_id}/complete", payload, headers
        )

    def cancel_drawdown(self, drawdown_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/drawdown-orders/{drawdown_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Program
    # ------------------------------------------------------------------
    def compliance_sweep(self, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            "/program/compliance-sweep",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw helper for path-shape probes
    # ------------------------------------------------------------------
    def raw_get(self, path: str, headers: Optional[dict] = None,
                params: Optional[dict] = None) -> requests.Response:
        return self._request("GET", path, params, headers)


api_client = ApiClient()
