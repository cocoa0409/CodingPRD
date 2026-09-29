"""HTTP client for the Airport Checkpoint Staffing API.

One method per endpoint of PRD §4, plus the instant-canonicalisation helpers
that let tests compare server-returned ISO 8601 timestamps safely.
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict, QueryParams

# ── ISO 8601 canonicalisation ─────────────────────────────────────────────────
# PRD §2.4 renders stored timestamps with exactly three fractional digits while
# the instants clients send carry none. Comparisons must therefore run on a
# canonical form rather than on the raw strings.


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Return an ISO 8601 UTC instant with any zero fractional part removed."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        body = text[:-1]
    elif text.endswith("+00:00"):
        body = text[: -len("+00:00")]
    else:
        body = text
    if "." in body:
        whole, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        body = whole if frac == "" else f"{whole}.{frac}"
    return f"{body}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 instants denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint. Every method returns the raw response."""

    # ── Logical clock (PRD §2.4) ──────────────────────────────────────────────
    def set_clock(self, payload: JsonDict, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Show-up curves (PRD §3.1) ─────────────────────────────────────────────
    def create_show_up_curve(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/show-up-curves", payload, headers)

    def get_show_up_curve(self, curve_id: str, headers: Headers):
        return self._request("GET", f"/show-up-curves/{curve_id}", None, headers)

    def update_show_up_curve(self, curve_id: str, payload: JsonDict, headers: Headers):
        """PRD §3.1 declares a curve immutable; used to prove no update exists."""
        return self._request("PATCH", f"/show-up-curves/{curve_id}", payload, headers)

    # ── Checkpoints (PRD §3.1) ────────────────────────────────────────────────
    def create_checkpoint(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/checkpoints", payload, headers)

    def get_checkpoint(self, checkpoint_id: str, headers: Headers):
        return self._request("GET", f"/checkpoints/{checkpoint_id}", None, headers)

    def update_checkpoint(self, checkpoint_id: str, payload: JsonDict, headers: Headers):
        return self._request("PATCH", f"/checkpoints/{checkpoint_id}", payload, headers)

    # ── Lanes (PRD §3.1, §3.6) ────────────────────────────────────────────────
    def create_lane(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/lanes", payload, headers)

    def get_lane(self, lane_id: str, headers: Headers):
        return self._request("GET", f"/lanes/{lane_id}", None, headers)

    def list_lanes(self, headers: Headers, params: Optional[QueryParams] = None):
        return self._request("GET", "/lanes", params, headers)

    def open_lane(self, lane_id: str, headers: Headers, payload: Optional[JsonDict] = None):
        return self._request("POST", f"/lanes/{lane_id}/open", payload or {}, headers)

    def stand_down_lane(self, lane_id: str, payload: JsonDict, headers: Headers):
        return self._request("POST", f"/lanes/{lane_id}/stand-down", payload, headers)

    # ── Equipment units (PRD §3.1, §3.6) ──────────────────────────────────────
    def create_equipment_unit(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id: str, headers: Headers):
        return self._request("GET", f"/equipment-units/{unit_id}", None, headers)

    def list_equipment_units(self, headers: Headers, params: Optional[QueryParams] = None):
        return self._request("GET", "/equipment-units", params, headers)

    def report_equipment_state(self, unit_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/equipment-units/{unit_id}/report-state", payload, headers
        )

    # ── Officers (PRD §3.1, §3.7) ─────────────────────────────────────────────
    def create_officer(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/officers", payload, headers)

    def get_officer(self, officer_id: str, headers: Headers):
        return self._request("GET", f"/officers/{officer_id}", None, headers)

    def set_officer_duty_status(self, officer_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/officers/{officer_id}/duty-status", payload, headers
        )

    def get_officer_duty_ledger(
        self, officer_id: str, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request(
            "GET", f"/officers/{officer_id}/duty-ledger", params, headers
        )

    # ── Flight schedule entries (PRD §3.2) ────────────────────────────────────
    def create_flight_schedule_entry(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/flight-schedule-entries", payload, headers)

    def get_flight_schedule_entry(self, entry_id: str, headers: Headers):
        return self._request(
            "GET", f"/flight-schedule-entries/{entry_id}", None, headers
        )

    def list_flight_schedule_entries(
        self, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request("GET", "/flight-schedule-entries", params, headers)

    def cancel_flight_schedule_entry(
        self, entry_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/flight-schedule-entries/{entry_id}/cancel", payload or {}, headers
        )

    # ── Time bands (PRD §3.2) ─────────────────────────────────────────────────
    def create_time_band(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/time-bands", payload, headers)

    def get_time_band(self, band_id: str, headers: Headers):
        return self._request("GET", f"/time-bands/{band_id}", None, headers)

    def list_time_bands(self, headers: Headers, params: Optional[QueryParams] = None):
        return self._request("GET", "/time-bands", params, headers)

    def forecast_time_band(self, band_id: str, payload: JsonDict, headers: Headers):
        return self._request("POST", f"/time-bands/{band_id}/forecast", payload, headers)

    # ── Staffing plans (PRD §3.3, §3.4) ───────────────────────────────────────
    def create_staffing_plan(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/staffing-plans", payload, headers)

    def get_staffing_plan(self, plan_id: str, headers: Headers):
        return self._request("GET", f"/staffing-plans/{plan_id}", None, headers)

    def list_staffing_plans(self, headers: Headers, params: Optional[QueryParams] = None):
        return self._request("GET", "/staffing-plans", params, headers)

    def submit_staffing_plan(
        self, plan_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/staffing-plans/{plan_id}/submit", payload or {}, headers
        )

    def decide_staffing_plan(self, plan_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/staffing-plans/{plan_id}/decision", payload, headers
        )

    def revise_staffing_plan(
        self, plan_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/staffing-plans/{plan_id}/revise", payload or {}, headers
        )

    def staffing_plan_lifecycle(self, plan_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/staffing-plans/{plan_id}/lifecycle", payload, headers
        )

    def get_plan_cost_summary(self, plan_id: str, headers: Headers):
        return self._request(
            "GET", f"/staffing-plans/{plan_id}/cost-summary", None, headers
        )

    # ── Lane assignments (PRD §3.3, §3.7) ─────────────────────────────────────
    def create_lane_assignment(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/lane-assignments", payload, headers)

    def get_lane_assignment(self, assignment_id: str, headers: Headers):
        return self._request("GET", f"/lane-assignments/{assignment_id}", None, headers)

    def list_lane_assignments(
        self, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request("GET", "/lane-assignments", params, headers)

    def assignment_duty(self, assignment_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/lane-assignments/{assignment_id}/duty", payload, headers
        )

    def assignment_break(self, assignment_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/lane-assignments/{assignment_id}/break", payload, headers
        )

    # ── Wait observations and publication (PRD §3.8) ──────────────────────────
    def create_wait_observation(
        self, checkpoint_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/checkpoints/{checkpoint_id}/wait-observations", payload, headers
        )

    def get_wait_observation(self, observation_id: str, headers: Headers):
        return self._request("GET", f"/wait-observations/{observation_id}", None, headers)

    def list_wait_observations(
        self, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request("GET", "/wait-observations", params, headers)

    def get_published_wait_time(
        self, checkpoint_id: str, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request(
            "GET", f"/checkpoints/{checkpoint_id}/wait-time", params, headers
        )

    # ── Escalation tickets (PRD §3.8) ─────────────────────────────────────────
    def get_escalation_ticket(self, ticket_id: str, headers: Headers):
        return self._request("GET", f"/escalation-tickets/{ticket_id}", None, headers)

    def list_escalation_tickets(
        self, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request("GET", "/escalation-tickets", params, headers)

    def acknowledge_escalation_ticket(
        self, ticket_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/escalation-tickets/{ticket_id}/acknowledge", payload or {}, headers
        )

    def resolve_escalation_ticket(
        self, ticket_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/escalation-tickets/{ticket_id}/resolve", payload, headers
        )

    # ── Screening referrals (PRD §3.9) ────────────────────────────────────────
    def create_screening_referral(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/screening-referrals", payload, headers)

    def get_screening_referral(self, referral_id: str, headers: Headers):
        return self._request("GET", f"/screening-referrals/{referral_id}", None, headers)

    def list_screening_referrals(
        self, headers: Headers, params: Optional[QueryParams] = None
    ):
        return self._request("GET", "/screening-referrals", params, headers)

    def begin_screening_referral(
        self, referral_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/screening-referrals/{referral_id}/begin", payload, headers
        )

    def resolve_screening_referral(
        self, referral_id: str, payload: JsonDict, headers: Headers
    ):
        return self._request(
            "POST", f"/screening-referrals/{referral_id}/resolve", payload, headers
        )

    # ── Surge details (PRD §3.5) ──────────────────────────────────────────────
    def create_surge_detail(self, payload: JsonDict, headers: Headers):
        return self._request("POST", "/surge-details", payload, headers)

    def get_surge_detail(self, detail_id: str, headers: Headers):
        return self._request("GET", f"/surge-details/{detail_id}", None, headers)

    def list_surge_details(self, headers: Headers, params: Optional[QueryParams] = None):
        return self._request("GET", "/surge-details", params, headers)

    def decide_surge_detail(self, detail_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"/surge-details/{detail_id}/decision", payload, headers
        )

    def cancel_surge_detail(
        self, detail_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/surge-details/{detail_id}/cancel", payload or {}, headers
        )

    # ── Analytics (PRD §3.9) ──────────────────────────────────────────────────
    def get_throughput_analysis(self, checkpoint_id: str, headers: Headers):
        return self._request(
            "GET", f"/checkpoints/{checkpoint_id}/throughput-analysis", None, headers
        )
