"""
Endpoint client for the Building Trades Hiring Hall Dispatch API.

One method per row of the §4 endpoint table. Every method returns the raw
`requests.Response` so tests can assert on status codes as well as bodies.

This module also owns the wire format of instants. §2.4 and §2.5 require every
instant to be an ISO 8601 UTC value rendered with exactly three fractional
digits, so `canonical_instant()` lives here and is the single place where
sub-second width is normalised — tests compare canonical forms rather than
re-implementing the rendering rule.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE, CLOCK_PATH

# ─── Instant handling (§2.4, §2.5) ────────────────────────────────────────────

_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant the API may render, with or without ms."""
    assert isinstance(value, str), f"Not an instant string: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render_instant(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime(_INSTANT_FORMAT)[:-4] + "Z"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an instant to the three-fractional-digit UTC rendering §2.4 fixes.

    Comparisons in the tests run over canonical forms so that a server which
    renders `...:00Z` and one which renders `...:00.000Z` are judged on the
    instant they mean rather than on incidental sub-second width.
    """
    if value is None:
        return None
    return render_instant(parse_instant(value))


def plus_hours(value: str, hours: float) -> str:
    """Instant arithmetic in hours; §2.5 fixes all comparisons to the millisecond."""
    return render_instant(parse_instant(value) + timedelta(hours=hours))


def plus_days(value: str, days: float) -> str:
    """Instant arithmetic in exact 24-hour days, as §2.5 requires."""
    return render_instant(parse_instant(value) + timedelta(days=days))


def plus_millis(value: str, millis: int) -> str:
    """One-millisecond steps, the resolution §2.5 makes boundaries exact to."""
    return render_instant(parse_instant(value) + timedelta(milliseconds=millis))


class HiringHallApiClient(GenericApiClient):
    """One method per §4 endpoint."""

    # ─── Logical clock (§2.5) ─────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Housekeeping sweep (§3.4) ────────────────────────────────────────────

    def run_dispatch_run(self, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"{BASE}/dispatch-runs", payload or {}, headers)

    # ─── Locals (§3.1) ────────────────────────────────────────────────────────

    def create_local(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/locals", payload, headers)

    def get_local(self, local_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/locals/{local_id}", None, headers)

    def list_locals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/locals", params, headers)

    # ─── Out-of-work list groups (§3.2) ───────────────────────────────────────

    def create_out_of_work_list(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/out-of-work-lists", payload, headers)

    def get_out_of_work_list(self, list_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/out-of-work-lists/{list_id}", None, headers)

    def list_out_of_work_lists(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{BASE}/out-of-work-lists", params, headers)

    # ─── Members and endorsements (§3.1) ──────────────────────────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/members/{member_id}", None, headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/members", params, headers)

    def patch_member_standing(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{BASE}/members/{member_id}/standing", payload, headers
        )

    def create_skill_endorsement(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/skill-endorsements", payload, headers
        )

    def list_member_skill_endorsements(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/members/{member_id}/skill-endorsements", params, headers
        )

    def get_skill_endorsement(self, endorsement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/skill-endorsements/{endorsement_id}", None, headers
        )

    # ─── Ratio policies (§3.6) ────────────────────────────────────────────────

    def create_ratio_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/ratio-policies", payload, headers)

    def get_ratio_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/ratio-policies/{policy_id}", None, headers)

    def list_ratio_policies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{BASE}/ratio-policies", params, headers)

    # ─── Registrations (§3.3, §3.4) ───────────────────────────────────────────

    def create_registration(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/registrations", payload, headers)

    def get_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/registrations/{registration_id}", None, headers
        )

    def list_registrations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{BASE}/registrations", params, headers)

    def renew_registration(
        self, registration_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE}/registrations/{registration_id}/renew", payload or {}, headers
        )

    def remove_registration(
        self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/registrations/{registration_id}/remove", payload, headers
        )

    # ─── Contractors (§3.5) ───────────────────────────────────────────────────

    def create_contractor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/contractors/{contractor_id}", None, headers)

    def list_contractors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/contractors", params, headers)

    def patch_contractor_signatory_status(
        self, contractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH",
            f"{BASE}/contractors/{contractor_id}/signatory-status",
            payload,
            headers,
        )

    # ─── Job requests (§3.5, §3.6) ────────────────────────────────────────────

    def create_job_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/job-requests", payload, headers)

    def get_job_request(self, job_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/job-requests/{job_request_id}", None, headers
        )

    def list_job_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/job-requests", params, headers)

    def cancel_job_request(
        self, job_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/job-requests/{job_request_id}/cancel", payload, headers
        )

    def get_dispatch_order(
        self, job_request_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/job-requests/{job_request_id}/dispatch-order", params, headers
        )

    def create_referral(
        self, job_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/job-requests/{job_request_id}/referrals", payload, headers
        )

    # ─── Referrals (§3.6, §3.7) ───────────────────────────────────────────────

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/referrals/{referral_id}", None, headers)

    def list_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/referrals", params, headers)

    def accept_referral(
        self, referral_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE}/referrals/{referral_id}/accept", payload or {}, headers
        )

    def refuse_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/referrals/{referral_id}/refuse", payload, headers
        )

    def withdraw_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/referrals/{referral_id}/withdraw", payload, headers
        )

    # ─── Dispatches (§3.8) ────────────────────────────────────────────────────

    def get_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/dispatches/{dispatch_id}", None, headers)

    def list_dispatches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/dispatches", params, headers)

    def layoff_dispatch(
        self, dispatch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/dispatches/{dispatch_id}/layoff", payload, headers
        )

    def recall_dispatch(
        self, dispatch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/dispatches/{dispatch_id}/recall", payload, headers
        )

    # ─── Grievances (§3.9) ────────────────────────────────────────────────────

    def create_grievance(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/grievances", payload, headers)

    def get_grievance(self, grievance_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/grievances/{grievance_id}", None, headers)

    def list_grievances(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/grievances", params, headers)

    def review_grievance(
        self, grievance_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{BASE}/grievances/{grievance_id}/review", payload or {}, headers
        )

    def adjudicate_grievance(
        self, grievance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/grievances/{grievance_id}/adjudicate", payload, headers
        )

    # ─── Retention ledger (§2.10) ─────────────────────────────────────────────

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/ledger-entries/{entry_id}", None, headers)

    def list_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{BASE}/ledger-entries", params, headers)
