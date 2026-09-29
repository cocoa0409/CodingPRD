"""Endpoint-per-method HTTP client for the television series development API.

One method per path in the contract's endpoint table. Every method returns the raw
response so the caller decides whether to validate a success envelope or an error.

Timestamp handling is canonicalised here: the contract renders instants as
ISO-8601 UTC with exactly three fractional digits, but a server that emits a
different sub-second width is still naming the same instant, so
``canonical_instant`` normalises both sides before any comparison.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Leaves non-instant values untouched so it is safe to apply defensively.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, _zone = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


class ApiClient(GenericApiClient):
    """Domain client: one method per endpoint in the contract."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Agencies ─────────────────────────────────────
    def create_agency(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Headers):
        return self._request("GET", f"/agencies/{agency_id}", None, headers)

    # ─── Slates ───────────────────────────────────────
    def create_slate(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/slates", payload, headers)

    def get_slate(self, slate_id: str, headers: Headers):
        return self._request("GET", f"/slates/{slate_id}", None, headers)

    # ─── Writers ──────────────────────────────────────
    def create_writer(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/writers", payload, headers)

    def get_writer(self, writer_id: str, headers: Headers):
        return self._request("GET", f"/writers/{writer_id}", None, headers)

    def list_writers(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/writers", params, headers)

    # ─── Holding deals ────────────────────────────────
    def create_holding_deal(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/holding-deals", payload, headers)

    def get_holding_deal(self, holding_deal_id: str, headers: Headers):
        return self._request("GET", f"/holding-deals/{holding_deal_id}", None, headers)

    def list_holding_deals(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/holding-deals", params, headers)

    def terminate_holding_deal(
        self, holding_deal_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/holding-deals/{holding_deal_id}/terminate", payload, headers
        )

    # ─── Pitches ──────────────────────────────────────
    def create_pitch(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/pitches", payload, headers)

    def get_pitch(self, pitch_id: str, headers: Headers):
        return self._request("GET", f"/pitches/{pitch_id}", None, headers)

    def list_pitches(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/pitches", params, headers)

    def record_coverage(self, pitch_id: str, payload: JsonDict, headers: Headers):
        return self._request("POST", f"/pitches/{pitch_id}/coverage", payload, headers)

    def file_rights_check(self, pitch_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/pitches/{pitch_id}/rights-checks", payload, headers
        )

    def list_rights_checks(self, pitch_id: str, headers: Headers):
        return self._request("GET", f"/pitches/{pitch_id}/rights-checks", None, headers)

    def advance_pitch(self, pitch_id: str, headers: Headers, payload: Optional[JsonDict] = None):
        return self._request(
            "POST", f"/pitches/{pitch_id}/advance", payload if payload is not None else {}, headers
        )

    # ─── Development projects ─────────────────────────
    def get_project(self, project_id: str, headers: Headers):
        return self._request("GET", f"/development-projects/{project_id}", None, headers)

    def list_projects(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/development-projects", params, headers)

    def get_feasibility(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/development-projects/{project_id}/feasibility", params, headers
        )

    def list_project_pilot_orders(self, project_id: str, headers: Headers):
        return self._request(
            "GET", f"/development-projects/{project_id}/pilot-orders", None, headers
        )

    def list_project_negotiations(self, project_id: str, headers: Headers):
        return self._request(
            "GET", f"/development-projects/{project_id}/negotiations", None, headers
        )

    def abandon_project(self, project_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/development-projects/{project_id}/abandon", payload, headers
        )

    def offer_turnaround(
        self, project_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST",
            f"/development-projects/{project_id}/turnaround",
            payload if payload is not None else {},
            headers,
        )

    def exercise_turnaround(self, project_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST",
            f"/development-projects/{project_id}/turnaround-exercise",
            payload,
            headers,
        )

    # ─── Script deals and steps ───────────────────────
    def create_script_deal(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/script-deals", payload, headers)

    def get_script_deal(self, deal_id: str, headers: Headers):
        return self._request("GET", f"/script-deals/{deal_id}", None, headers)

    def list_script_deals(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/script-deals", params, headers)

    def list_deal_steps(self, deal_id: str, headers: Headers):
        return self._request("GET", f"/script-deals/{deal_id}/steps", None, headers)

    def exercise_step(self, deal_id: str, step_id: str, headers: Headers):
        return self._request(
            "POST", f"/script-deals/{deal_id}/steps/{step_id}/exercise", {}, headers
        )

    def deliver_step(self, deal_id: str, step_id: str, headers: Headers):
        return self._request(
            "POST", f"/script-deals/{deal_id}/steps/{step_id}/deliver", {}, headers
        )

    def review_step(
        self, deal_id: str, step_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/script-deals/{deal_id}/steps/{step_id}/review", payload, headers
        )

    def cutoff_deal(self, deal_id: str, payload: JsonDict, headers: Headers):
        return self._request("POST", f"/script-deals/{deal_id}/cutoff", payload, headers)

    # ─── Pilot orders ─────────────────────────────────
    def create_pilot_order(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/pilot-orders", payload, headers)

    def get_pilot_order(self, pilot_order_id: str, headers: Headers):
        return self._request("GET", f"/pilot-orders/{pilot_order_id}", None, headers)

    def clear_contingency(
        self, pilot_order_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST",
            f"/pilot-orders/{pilot_order_id}/contingency-clearances",
            payload,
            headers,
        )

    def wrap_pilot(self, pilot_order_id: str, headers: Headers):
        return self._request("POST", f"/pilot-orders/{pilot_order_id}/wrap", {}, headers)

    def field_screening(
        self, pilot_order_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/pilot-orders/{pilot_order_id}/test-screenings", payload, headers
        )

    def list_screenings(
        self, pilot_order_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/pilot-orders/{pilot_order_id}/test-screenings", params, headers
        )

    def certify_screening(self, screening_id: str, headers: Headers):
        return self._request(
            "POST", f"/test-screenings/{screening_id}/certify", {}, headers
        )

    # ─── Negotiations ─────────────────────────────────
    def create_negotiation(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/negotiations", payload, headers)

    def table_round(self, negotiation_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/negotiations/{negotiation_id}/rounds", payload, headers
        )

    def accept_negotiation(self, negotiation_id: str, headers: Headers):
        return self._request(
            "POST", f"/negotiations/{negotiation_id}/accept", {}, headers
        )

    # ─── Greenlight requests ──────────────────────────
    def create_greenlight_request(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/greenlight-requests", payload, headers)

    def get_greenlight_request(self, greenlight_id: str, headers: Headers):
        return self._request(
            "GET", f"/greenlight-requests/{greenlight_id}", None, headers
        )

    def list_greenlight_requests(self, headers: Headers, params: Optional[Dict] = None):
        return self._request("GET", "/greenlight-requests", params, headers)

    def record_decision(
        self, greenlight_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/greenlight-requests/{greenlight_id}/decisions", payload, headers
        )
