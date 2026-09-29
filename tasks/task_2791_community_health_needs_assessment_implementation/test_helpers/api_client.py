"""Typed HTTP client for the community health needs assessment API.

Every method is a thin wrapper over one row of the endpoint table.  All monetary
amounts are passed through as JSON numbers (integer cents); no helper here ever
stringifies money.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .test_users import OFFICER

_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)

# --------------------------------------------------------------------------
# Exact-precision JSON bodies
#
# PRD §2.9 requires a cost-to-charge ratio to carry *exactly four* decimal
# places on the wire: "a value with more or fewer than four decimal places is an
# ``ERR_VALIDATION`` failure".  A Python float cannot preserve the trailing
# zeros of ``0.3200`` — ``json.dumps(0.32)`` emits ``0.32``, three places short
# of what the PRD demands — so ratio constants are held as ``Decimal`` and this
# encoder writes them out as bare JSON numbers with their exact text.
# --------------------------------------------------------------------------
_RAW_SENTINEL = "@@RAWNUM@@"
_RAW_RE = re.compile(r'"%s(-?[0-9][0-9.eE+-]*)%s"' % (_RAW_SENTINEL, _RAW_SENTINEL))


def _raw_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return f"{_RAW_SENTINEL}{format(obj, 'f')}{_RAW_SENTINEL}"
    raise TypeError(f"{type(obj).__name__} is not JSON serializable")


def encode_body(payload: Any) -> str:
    """Serialise a request body, rendering ``Decimal`` with its exact digits."""
    return _RAW_RE.sub(r"\1", json.dumps(payload, default=_raw_default))


def canonical_iso(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    The PRD declares stamped instants as UTC timestamps with three fractional
    second digits.  Comparing two instants that differ only in the *width* of
    the fractional part — ``...:00Z`` against ``...:00.000Z`` — is a formatting
    difference and not a behavioural one, so every comparison in this suite runs
    through this canonicaliser first.
    """
    if not isinstance(value, str):
        return value
    match = _ISO_RE.match(value.strip())
    if not match:
        return value
    base, frac, _tz = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{base}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants denote the same moment."""
    return canonical_iso(left) == canonical_iso(right)


class ApiClient(GenericApiClient):
    """One method per endpoint, with the acting headers always explicit."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send the request, serialising bodies through :func:`encode_body`.

        Only the write path is customised: a ``Decimal`` in the payload has to
        reach the wire with its exact decimal text, which ``requests``' own
        ``json=`` kwarg cannot do.
        """
        if method.upper() in ("GET", "DELETE") or payload is None:
            return super()._request(method, path, payload=payload, headers=headers, params=params)

        sent_headers = dict(headers or {})
        sent_headers.setdefault("Content-Type", "application/json")
        kwargs: Dict[str, Any] = {"headers": sent_headers, "data": encode_body(payload)}
        if params:
            kwargs["params"] = params
        return self.session.request(method, f"{self.base_url}{path}", **kwargs)

    # ------------------------------------------------------------------
    # Raw escape hatch — used only where a test must send malformed or
    # absent identity headers.
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload=payload, headers=headers, params=params)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload={"to_iso8601": to_iso8601}, headers=headers
        )

    # ------------------------------------------------------------------
    # Assessment cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("POST", "/assessment-cycles", payload=payload, headers=headers)

    def list_cycles(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/assessment-cycles", headers=headers, params=params or None)

    def get_cycle(self, cycle_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/assessment-cycles/{cycle_id}", headers=headers)

    def advance_cycle(
        self, cycle_id: str, to_status: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/assessment-cycles/{cycle_id}/advance",
            payload={"to_status": to_status},
            headers=headers,
        )

    def board_action(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessment-cycles/{cycle_id}/board-action", payload=payload, headers=headers
        )

    def publish_cycle(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessment-cycles/{cycle_id}/publish", payload=payload, headers=headers
        )

    def file_return(
        self, cycle_id: str, return_form_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/assessment-cycles/{cycle_id}/file-return",
            payload={"return_form_id": return_form_id},
            headers=headers,
        )

    def list_cycle_evaluations(
        self, cycle_id: str, headers: Dict[str, str] = OFFICER, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/assessment-cycles/{cycle_id}/progress-evaluations",
            headers=headers,
            params=params or None,
        )

    # ------------------------------------------------------------------
    # Health indicators and observations
    # ------------------------------------------------------------------
    def create_indicator(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/health-indicators", payload=payload, headers=headers)

    def list_indicators(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/health-indicators", headers=headers, params=params or None)

    def get_indicator(self, indicator_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/health-indicators/{indicator_id}", headers=headers)

    def create_data_point(
        self, indicator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/health-indicators/{indicator_id}/data-points", payload=payload, headers=headers
        )

    def list_indicator_data_points(
        self, indicator_id: str, headers: Dict[str, str] = OFFICER, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/health-indicators/{indicator_id}/data-points",
            headers=headers,
            params=params or None,
        )

    def list_data_points(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/indicator-data-points", headers=headers, params=params or None)

    def get_data_point(self, data_point_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/indicator-data-points/{data_point_id}", headers=headers)

    def void_data_point(
        self, data_point_id: str, reason: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/indicator-data-points/{data_point_id}/void",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Responsible parties
    # ------------------------------------------------------------------
    def create_party(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/responsible-parties", payload=payload, headers=headers)

    def list_parties(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/responsible-parties", headers=headers, params=params or None)

    def get_party(self, party_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/responsible-parties/{party_id}", headers=headers)

    # ------------------------------------------------------------------
    # Stakeholder interviews
    # ------------------------------------------------------------------
    def create_interview(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/stakeholder-interviews", payload=payload, headers=headers)

    def list_interviews(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/stakeholder-interviews", headers=headers, params=params or None)

    def get_interview(self, interview_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/stakeholder-interviews/{interview_id}", headers=headers)

    def complete_interview(
        self, interview_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/stakeholder-interviews/{interview_id}/complete",
            payload=payload,
            headers=headers,
        )

    def cancel_interview(
        self, interview_id: str, reason: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/stakeholder-interviews/{interview_id}/cancel",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Priority candidates
    # ------------------------------------------------------------------
    def create_candidate(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/priority-candidates", payload=payload, headers=headers)

    def list_candidates(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/priority-candidates", headers=headers, params=params or None)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/priority-candidates/{candidate_id}", headers=headers)

    def score_candidate(
        self, candidate_id: str, scoring_variant: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/priority-candidates/{candidate_id}/score",
            payload={"scoring_variant": scoring_variant},
            headers=headers,
        )

    def select_candidate(
        self, candidate_id: str, selection_rationale: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/priority-candidates/{candidate_id}/select",
            payload={"selection_rationale": selection_rationale},
            headers=headers,
        )

    def defer_candidate(
        self, candidate_id: str, reason: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/priority-candidates/{candidate_id}/defer",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Implementation strategies and objectives
    # ------------------------------------------------------------------
    def create_strategy(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/implementation-strategies", payload=payload, headers=headers)

    def list_strategies(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request(
            "GET", "/implementation-strategies", headers=headers, params=params or None
        )

    def get_strategy(self, strategy_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/implementation-strategies/{strategy_id}", headers=headers)

    def submit_strategy(self, strategy_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request(
            "POST", f"/implementation-strategies/{strategy_id}/submit", payload={}, headers=headers
        )

    def create_objective(
        self, strategy_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/implementation-strategies/{strategy_id}/objectives",
            payload=payload,
            headers=headers,
        )

    def list_strategy_objectives(
        self, strategy_id: str, headers: Dict[str, str] = OFFICER, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/implementation-strategies/{strategy_id}/objectives",
            headers=headers,
            params=params or None,
        )

    def list_objectives(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/strategy-objectives", headers=headers, params=params or None)

    def get_objective(self, objective_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/strategy-objectives/{objective_id}", headers=headers)

    def report_progress(
        self, objective_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/strategy-objectives/{objective_id}/report-progress",
            payload=payload,
            headers=headers,
        )

    def set_execution_status(
        self, strategy_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/implementation-strategies/{strategy_id}/execution-status",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Partnership agreements
    # ------------------------------------------------------------------
    def create_agreement(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/partnership-agreements", payload=payload, headers=headers)

    def list_agreements(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/partnership-agreements", headers=headers, params=params or None)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/partnership-agreements/{agreement_id}", headers=headers)

    def sign_agreement(
        self, agreement_id: str, signatory_side: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/partnership-agreements/{agreement_id}/sign",
            payload={"signatory_side": signatory_side},
            headers=headers,
        )

    def terminate_agreement(
        self, agreement_id: str, reason: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/partnership-agreements/{agreement_id}/terminate",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Resource commitments
    # ------------------------------------------------------------------
    def create_commitment(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/resource-commitments", payload=payload, headers=headers)

    def list_commitments(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/resource-commitments", headers=headers, params=params or None)

    def get_commitment(self, commitment_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/resource-commitments/{commitment_id}", headers=headers)

    def release_commitment(
        self, commitment_id: str, reason: str, headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/resource-commitments/{commitment_id}/release",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Community benefit reports and expense postings
    # ------------------------------------------------------------------
    def create_report(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/community-benefit-reports", payload=payload, headers=headers)

    def list_reports(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request(
            "GET", "/community-benefit-reports", headers=headers, params=params or None
        )

    def get_report(self, report_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/community-benefit-reports/{report_id}", headers=headers)

    def finalize_report(
        self, report_id: str, audited_cost_to_charge_ratio: float, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/community-benefit-reports/{report_id}/finalize",
            payload={"audited_cost_to_charge_ratio": audited_cost_to_charge_ratio},
            headers=headers,
        )

    def create_posting(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/expense-postings", payload=payload, headers=headers)

    def list_postings(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/expense-postings", headers=headers, params=params or None)

    def get_posting(self, posting_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/expense-postings/{posting_id}", headers=headers)

    def void_posting(
        self, posting_id: str, reason: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/expense-postings/{posting_id}/void",
            payload={"reason": reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Progress evaluations
    # ------------------------------------------------------------------
    def create_evaluation(
        self, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request("POST", "/progress-evaluations", payload=payload, headers=headers)

    def list_evaluations(self, headers: Dict[str, str] = OFFICER, **params: Any) -> requests.Response:
        return self._request("GET", "/progress-evaluations", headers=headers, params=params or None)

    def get_evaluation(self, evaluation_id: str, headers: Dict[str, str] = OFFICER) -> requests.Response:
        return self._request("GET", f"/progress-evaluations/{evaluation_id}", headers=headers)

    def publish_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str] = OFFICER
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/progress-evaluations/{evaluation_id}/publish",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Small read conveniences used pervasively by fixtures and tests
    # ------------------------------------------------------------------
    def report_version(self, report_id: str, headers: Dict[str, str] = OFFICER) -> int:
        """Current ``version`` of a report, re-read before every posting.

        Each posting increments the owning report's version, so the
        optimistic-concurrency token a posting must carry has to be refreshed
        between consecutive postings.
        """
        body = self.get_report(report_id, headers=headers).json()
        return body["data"]["version"]

    def candidate_version(self, candidate_id: str, headers: Dict[str, str] = OFFICER) -> int:
        """Current ``version`` of a candidate, the token a strategy create carries."""
        body = self.get_candidate(candidate_id, headers=headers).json()
        return body["data"]["version"]


#: Module-level singleton; the base URL comes from the environment.
api_client = ApiClient()
