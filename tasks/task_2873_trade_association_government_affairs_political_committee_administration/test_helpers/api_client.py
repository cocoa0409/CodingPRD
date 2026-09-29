"""API client: one method per endpoint defined in the PRD."""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/advocacy"

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:[Zz]|([+-])(\d{2}):?(\d{2}))?$"
)


def canonicalize_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    The PRD pins the wire format at three fractional-second digits, e.g.
    2026-08-01T00:00:00.000Z. Comparisons in tests go through this helper so
    that a server writing 2026-08-01T00:00:00Z or +00:00 is compared on the
    instant it denotes rather than on incidental sub-second width.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, sign, off_h, off_m = match.groups()
    if sign is not None and (int(off_h) != 0 or int(off_m) != 0):
        return value
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two instants denote the same UTC moment."""
    return canonicalize_instant(actual) == canonicalize_instant(expected)


class ApiClient(GenericApiClient):
    """Endpoint methods for the Government Affairs API."""

    # --- test-only logical clock (outside the business path prefix) ---

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- members ---

    def create_member(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def get_deductibility_notice(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/deductibility-notice", headers=headers
        )

    def list_member_committee_seats(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/committee-seats",
            headers=headers, params=params,
        )

    def list_member_position_votes(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/position-votes",
            headers=headers, params=params,
        )

    def list_member_prior_approvals(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/prior-approvals",
            headers=headers, params=params,
        )

    # --- policy committees and seats ---

    def create_committee(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/committees", payload, headers)

    def get_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/committees/{committee_id}", headers=headers)

    def create_committee_seat(
        self, committee_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/committees/{committee_id}/seats", payload, headers
        )

    def list_committee_seats(
        self, committee_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/committees/{committee_id}/seats",
            headers=headers, params=params,
        )

    def list_committee_policy_positions(
        self, committee_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/committees/{committee_id}/policy-positions",
            headers=headers, params=params,
        )

    # --- policy positions, ballots and adoption ---

    def create_policy_position(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/policy-positions", payload, headers)

    def get_policy_position(self, position_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/policy-positions/{position_id}", headers=headers
        )

    def open_ballot(
        self, position_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{PREFIX}/policy-positions/{position_id}/open-ballot",
            payload if payload is not None else {}, headers,
        )

    def cast_vote(self, position_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/policy-positions/{position_id}/votes", payload, headers
        )

    def list_position_votes(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/policy-positions/{position_id}/votes",
            headers=headers, params=params,
        )

    def withdraw_dissent(self, position_id: str, vote_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/policy-positions/{position_id}/votes/{vote_id}/withdraw-dissent",
            {}, headers,
        )

    def tally_position(self, position_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/policy-positions/{position_id}/tally", {}, headers
        )

    def adopt_position(self, position_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/policy-positions/{position_id}/adopt", {}, headers
        )

    def list_position_lobbying_activities(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/policy-positions/{position_id}/lobbying-activities",
            headers=headers, params=params,
        )

    def list_position_grassroots_campaigns(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/policy-positions/{position_id}/grassroots-campaigns",
            headers=headers, params=params,
        )

    # --- lobbying registrations ---

    def create_lobbying_registration(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lobbying-registrations", payload, headers)

    def get_lobbying_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/lobbying-registrations/{registration_id}", headers=headers
        )

    def file_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/lobbying-registrations/{registration_id}/file", {}, headers
        )

    def amend_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/lobbying-registrations/{registration_id}/amend", {}, headers
        )

    def certify_registration_amendment(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/lobbying-registrations/{registration_id}/certify-amendment",
            {}, headers,
        )

    def terminate_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/lobbying-registrations/{registration_id}/terminate",
            {}, headers,
        )

    def list_registration_activities(
        self, registration_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/lobbying-registrations/{registration_id}/activities",
            headers=headers, params=params,
        )

    def list_registration_expenditure_reports(
        self, registration_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/lobbying-registrations/{registration_id}/expenditure-reports",
            headers=headers, params=params,
        )

    # --- lobbying activities ---

    def create_lobbying_activity(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lobbying-activities", payload, headers)

    def void_lobbying_activity(
        self, activity_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/lobbying-activities/{activity_id}/void", payload, headers
        )

    # --- expenditure reports ---

    def create_expenditure_report(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/expenditure-reports", payload, headers)

    def certify_expenditure_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/expenditure-reports/{report_id}/certify", {}, headers
        )

    # --- grassroots campaigns and action alerts ---

    def create_grassroots_campaign(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/grassroots-campaigns", payload, headers)

    def get_grassroots_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/grassroots-campaigns/{campaign_id}", headers=headers
        )

    def dispatch_alert(self, campaign_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/grassroots-campaigns/{campaign_id}/alerts", payload, headers
        )

    def list_campaign_alerts(
        self, campaign_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/grassroots-campaigns/{campaign_id}/alerts",
            headers=headers, params=params,
        )

    def close_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/grassroots-campaigns/{campaign_id}/close", {}, headers
        )

    # --- PAC prior approvals ---

    def create_prior_approval(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/prior-approvals", payload, headers)

    def grant_prior_approval(
        self, approval_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/prior-approvals/{approval_id}/grant", payload, headers
        )

    def revoke_prior_approval(self, approval_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/prior-approvals/{approval_id}/revoke", {}, headers
        )

    # --- candidates ---

    def create_candidate(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/candidates/{candidate_id}", headers=headers)

    def list_candidate_pac_contributions(
        self, candidate_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/candidates/{candidate_id}/pac-contributions",
            headers=headers, params=params,
        )

    # --- separate segregated fund ---

    def create_segregated_fund(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/segregated-funds", payload, headers)

    def get_segregated_fund(self, fund_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/segregated-funds/{fund_id}", headers=headers
        )

    def list_fund_pac_contributions(
        self, fund_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/segregated-funds/{fund_id}/pac-contributions",
            headers=headers, params=params,
        )

    def create_fund_receipt(self, fund_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/segregated-funds/{fund_id}/receipts", payload, headers
        )

    def run_filing_cycle(self, fund_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/segregated-funds/{fund_id}/filing-cycle", payload, headers
        )

    # --- PAC contributions ---

    def create_pac_contribution(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/pac-contributions", payload, headers)

    def get_pac_contribution(self, contribution_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/pac-contributions/{contribution_id}", headers=headers
        )

    def board_approve_contribution(self, contribution_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pac-contributions/{contribution_id}/board-approve",
            {}, headers,
        )

    def disburse_contribution(self, contribution_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pac-contributions/{contribution_id}/disburse", {}, headers
        )

    def void_pac_contribution(
        self, contribution_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pac-contributions/{contribution_id}/void", payload, headers
        )


api_client = ApiClient()
