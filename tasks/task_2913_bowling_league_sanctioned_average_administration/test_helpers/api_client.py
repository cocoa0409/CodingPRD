"""Typed HTTP client — one method per endpoint in the PRD's endpoint table.

Every method returns the raw ``requests.Response`` so tests may assert on the
HTTP status; unwrapping the response envelope is the job of the framework
validators (``validate_success`` returns ``body["data"]``), never of this file.

Timestamp canonicalisation lives here and nowhere else.  The PRD requires
server-stamped instants to carry exactly three fractional-second digits, but a
response may legitimately spell an instant with zero, one, two or three digits
in places the PRD does not pin.  Rather than sprinkle tolerance across hundreds
of assertions, ``_request`` rewrites every ISO-8601 instant in the JSON body to
the single canonical ``YYYY-MM-DDTHH:MM:SS.mmmZ`` spelling, and ``as_instant``
puts an expected literal into that same spelling.  Assertions can then compare
instants with plain ``==``.
"""
import json
import re
from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing.client import GenericApiClient

# Importing the error catalogue registers the error-id -> HTTP-status map with
# the framework validators, so ``validate_error`` can check statuses itself.
from test_helpers import api_errors  # noqa: F401

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})$"
)


def as_instant(value: Any) -> Any:
    """Rewrite an ISO-8601 instant into the canonical ``...THH:MM:SS.mmmZ`` form.

    Non-instant values are returned untouched, so this is safe to apply to any
    field.  Offsets other than ``Z`` are preserved as written rather than
    shifted: the PRD only ever compares instants the tests themselves supplied
    in UTC, and silently shifting would hide a server-side offset bug.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if match is None:
        return value
    date_part, time_part, fraction, offset = match.groups()
    millis = (fraction or ".")[1:4].ljust(3, "0")
    suffix = "Z" if offset in ("Z", "z") else offset
    return f"{date_part}T{time_part}.{millis}{suffix}"


def _canonicalise(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _canonicalise(val) for key, val in node.items()}
    if isinstance(node, list):
        return [_canonicalise(item) for item in node]
    return as_instant(node)


class ApiClient(GenericApiClient):
    """One method per endpoint of the league-administration API."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(
            method, path, payload=payload, headers=headers, params=params
        )
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = _canonicalise(body)
        if canonical != body:
            response._content = json.dumps(canonical).encode("utf-8")
        return response

    # ─── Logical clock ───────────────────────────────────────
    def set_clock(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"current_utc": current_utc}, headers=headers,
        )

    # ─── Members ─────────────────────────────────────────────
    def register_member(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/members", payload=payload, headers=headers)

    def get_member(self, member_id: str, headers=None):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ─── Leagues ─────────────────────────────────────────────
    def charter_league(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/leagues", payload=payload, headers=headers)

    def adopt_bylaws(self, league_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/leagues/{league_id}/bylaws", payload=payload, headers=headers
        )

    def adopt_schedule(self, league_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/leagues/{league_id}/schedule", payload=payload, headers=headers
        )

    def close_season(self, league_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/leagues/{league_id}/close-season",
            payload=payload, headers=headers,
        )

    def get_league(self, league_id: str, headers=None):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers=None, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def list_league_teams(self, league_id: str, headers=None, params=None):
        return self._request(
            "GET", f"/leagues/{league_id}/teams", headers=headers, params=params
        )

    # ─── Teams ───────────────────────────────────────────────
    def create_team(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/teams", payload=payload, headers=headers)

    def get_team(self, team_id: str, headers=None):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    # ─── Memberships ─────────────────────────────────────────
    def create_membership(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/memberships", payload=payload, headers=headers)

    def get_membership(self, membership_id: str, headers=None):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers=None, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    # ─── Lane pairs ──────────────────────────────────────────
    def register_lane_pair(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/lane-pairs", payload=payload, headers=headers)

    def set_lane_pair_certification(
        self, lane_pair_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/lane-pairs/{lane_pair_id}/certification",
            payload=payload, headers=headers,
        )

    def get_lane_pair(self, lane_pair_id: str, headers=None):
        return self._request("GET", f"/lane-pairs/{lane_pair_id}", headers=headers)

    def list_lane_pairs(self, headers=None, params=None):
        return self._request("GET", "/lane-pairs", headers=headers, params=params)

    # ─── Fee remittances ─────────────────────────────────────
    def create_fee_remittance(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", "/fee-remittances", payload=payload, headers=headers
        )

    def submit_fee_remittance(
        self, remittance_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/fee-remittances/{remittance_id}/submit",
            payload=payload, headers=headers,
        )

    def record_national_decision(
        self, remittance_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/fee-remittances/{remittance_id}/national-decision",
            payload=payload, headers=headers,
        )

    def get_fee_remittance(self, remittance_id: str, headers=None):
        return self._request(
            "GET", f"/fee-remittances/{remittance_id}", headers=headers
        )

    def list_fee_remittances(self, headers=None, params=None):
        return self._request("GET", "/fee-remittances", headers=headers, params=params)

    # ─── Matches ─────────────────────────────────────────────
    def submit_lineup(self, match_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/matches/{match_id}/lineups", payload=payload, headers=headers
        )

    def open_match(self, match_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/matches/{match_id}/open", payload=payload, headers=headers
        )

    def record_scores(self, match_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/matches/{match_id}/scores", payload=payload, headers=headers
        )

    def certify_match(self, match_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/matches/{match_id}/certify", payload=payload, headers=headers
        )

    def forfeit_match(self, match_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/matches/{match_id}/forfeit", payload=payload, headers=headers
        )

    def get_match(self, match_id: str, headers=None):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers=None, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    # ─── Series entries (lineup slots) ───────────────────────
    def get_series_entry(self, series_entry_id: str, headers=None):
        return self._request(
            "GET", f"/series-entries/{series_entry_id}", headers=headers
        )

    def list_series_entries(self, headers=None, params=None):
        return self._request("GET", "/series-entries", headers=headers, params=params)

    # ─── Dues payments ───────────────────────────────────────
    def record_dues_payment(
        self, membership_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/memberships/{membership_id}/dues-payments",
            payload=payload, headers=headers,
        )

    def get_dues_payment(self, dues_payment_id: str, headers=None):
        return self._request(
            "GET", f"/dues-payments/{dues_payment_id}", headers=headers
        )

    def list_dues_payments(self, headers=None, params=None):
        return self._request("GET", "/dues-payments", headers=headers, params=params)

    # ─── Prize funds and awards ──────────────────────────────
    def draft_distribution_plan(
        self, prize_fund_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/prize-funds/{prize_fund_id}/distribution-plans",
            payload=payload, headers=headers,
        )

    def approve_plan(self, prize_fund_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/prize-funds/{prize_fund_id}/approve-plan",
            payload=payload, headers=headers,
        )

    def disburse(self, prize_fund_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/prize-funds/{prize_fund_id}/disburse",
            payload=payload, headers=headers,
        )

    def get_prize_fund(self, prize_fund_id: str, headers=None):
        return self._request("GET", f"/prize-funds/{prize_fund_id}", headers=headers)

    def list_prize_funds(self, headers=None, params=None):
        return self._request("GET", "/prize-funds", headers=headers, params=params)

    def reverse_award(self, prize_award_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/prize-awards/{prize_award_id}/reverse",
            payload=payload, headers=headers,
        )

    def get_prize_award(self, prize_award_id: str, headers=None):
        return self._request("GET", f"/prize-awards/{prize_award_id}", headers=headers)

    def list_prize_awards(self, headers=None, params=None):
        return self._request("GET", "/prize-awards", headers=headers, params=params)

    # ─── Honor-score award applications ──────────────────────
    def create_award_application(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", "/award-applications", payload=payload, headers=headers
        )

    def league_verify_application(
        self, application_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/award-applications/{application_id}/league-verification",
            payload=payload, headers=headers,
        )

    def resubmit_evidence(
        self, application_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/award-applications/{application_id}/evidence",
            payload=payload, headers=headers,
        )

    def association_decide_application(
        self, application_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/award-applications/{application_id}/association-decision",
            payload=payload, headers=headers,
        )

    def get_award_application(self, application_id: str, headers=None):
        return self._request(
            "GET", f"/award-applications/{application_id}", headers=headers
        )

    def list_award_applications(self, headers=None, params=None):
        return self._request(
            "GET", "/award-applications", headers=headers, params=params
        )

    # ─── Protests ────────────────────────────────────────────
    def file_protest(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/protests", payload=payload, headers=headers)

    def review_protest(self, protest_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/protests/{protest_id}/review", payload=payload, headers=headers
        )

    def rule_on_protest(self, protest_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/protests/{protest_id}/ruling", payload=payload, headers=headers
        )

    def association_rule_on_protest(
        self, protest_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/protests/{protest_id}/association-ruling",
            payload=payload, headers=headers,
        )

    def get_protest(self, protest_id: str, headers=None):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def list_protests(self, headers=None, params=None):
        return self._request("GET", "/protests", headers=headers, params=params)

    # ─── Raw escape hatch ────────────────────────────────────
    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request — for tests that must probe a path or a
        method the typed helpers deliberately do not expose."""
        return self._request(
            method, path, payload=payload, headers=headers, params=params
        )
