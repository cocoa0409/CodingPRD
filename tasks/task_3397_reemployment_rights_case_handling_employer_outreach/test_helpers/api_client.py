"""HTTP client for the Reemployment Rights Mediation API.

One method per endpoint the PRD declares. Every method returns the raw
response so a test can assert on the status code as well as the body. Query
filters and pagination are passed through the ``payload`` argument on GET
calls (the framework forwards it as query parameters); request bodies as
``payload`` on writes.

All paths are mounted under the ``/reemployment`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reemployment"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    Instants may legitimately arrive with three fractional digits, with fewer,
    or with none. Comparisons therefore run on the canonical form -
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` - so that ``2026-09-01T00:00:00Z`` and
    ``2026-09-01T00:00:00.000Z`` compare equal.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Service members ────────────────────────────────────────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}", None, headers)

    # ── Employers ──────────────────────────────────────────────────────────

    def create_employer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}", None, headers)

    def list_affiliated_ombudsmen(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}/affiliated-ombudsmen", None, headers)

    # ── Ombudsmen ──────────────────────────────────────────────────────────

    def create_ombudsman(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ombudsmen", payload, headers)

    def get_ombudsman(self, ombudsman_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ombudsmen/{ombudsman_id}", None, headers)

    def transition_ombudsman(self, ombudsman_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ombudsmen/{ombudsman_id}/state", payload, headers)

    # ── Service periods ────────────────────────────────────────────────────

    def create_service_period(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/service-periods", payload, headers)

    def list_member_service_periods(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}/service-periods", None, headers)

    def list_employer_service_periods(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}/service-periods", None, headers)

    # ── Cases ──────────────────────────────────────────────────────────────

    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}", None, headers)

    def list_cases(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases", params, headers)

    def assign_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cases/{case_id}/assign", payload, headers)

    def transition_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cases/{case_id}/state", payload, headers)

    # ── Eligibility analyses ───────────────────────────────────────────────

    def create_eligibility_analysis(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cases/{case_id}/eligibility-analysis", payload, headers)

    def list_eligibility_analyses(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}/eligibility-analyses", None, headers)

    # ── Mediation rounds ───────────────────────────────────────────────────

    def create_mediation_round(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/mediation-rounds", payload, headers)

    def respond_to_round(self, round_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/mediation-rounds/{round_id}/respond", payload, headers)

    def list_case_rounds(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}/rounds", None, headers)

    # ── Case notes ─────────────────────────────────────────────────────────

    def create_case_note(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/case-notes", payload, headers)

    def list_case_notes(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}/notes", None, headers)

    # ── Benefit assessments ────────────────────────────────────────────────

    def create_benefit_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/benefit-assessments", payload, headers)

    def list_benefit_assessments(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}/benefit-assessments", None, headers)

    # ── Referrals ──────────────────────────────────────────────────────────

    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def transition_referral(self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/state", payload, headers)

    def list_case_referrals(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cases/{case_id}/referrals", None, headers)

    # ── Statements of support ──────────────────────────────────────────────

    def create_statement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/statements-of-support", payload, headers)

    def transition_statement(self, statement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/statements-of-support/{statement_id}/state", payload, headers)

    def list_employer_statements(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}/statements-of-support", None, headers)

    # ── Recognition awards ─────────────────────────────────────────────────

    def create_award(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/recognition-awards", payload, headers)

    def transition_award(self, award_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/recognition-awards/{award_id}/state", payload, headers)

    def list_employer_awards(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}/recognition-awards", None, headers)

    # ── Outreach events ────────────────────────────────────────────────────

    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/outreach-events", payload, headers)

    def transition_event(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/outreach-events/{event_id}/state", payload, headers)

    # ── Training records ───────────────────────────────────────────────────

    def create_training_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/training-records", payload, headers)

    def list_training_records(self, ombudsman_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ombudsmen/{ombudsman_id}/training-records", None, headers)

    # ── Reports ────────────────────────────────────────────────────────────

    def get_sector_trends(self, params: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/reports/sector-trends", params, headers)


api_client = ApiClient()
