"""Endpoint mixin: clock, communities, evaluation cycles, sheets, classes.

Paths under the service are written exactly as the endpoint catalogue prints
them, including the ``/ppc`` mount. The logical-clock administration call
lives OUTSIDE that mount (``/_clock/set_current_utc``) and is deliberately
not prefixed here.

Every method returns the raw ``requests.Response``; validators decide what
the body should look like.
"""
from typing import Any, Dict, Optional

import requests


class EvaluationEndpoints:
    # ── Logical clock (outside the /ppc mount) ───────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Communities ──────────────────────────────────────────────────────
    def create_community(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/communities", payload, headers)

    def list_communities(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/communities", headers=headers, params=params)

    def get_community(self, community_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/communities/{community_id}", headers=headers)

    def attest_comms(self, community_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/communities/{community_id}/attest-comms", payload, headers)

    # ── Evaluation cycles ────────────────────────────────────────────────
    def create_evaluation_cycle(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/evaluation-cycles", payload, headers)

    def list_evaluation_cycles(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/evaluation-cycles", headers=headers, params=params)

    def get_evaluation_cycle(self, cycle_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/evaluation-cycles/{cycle_id}", headers=headers)

    def transition_evaluation_cycle(self, cycle_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/evaluation-cycles/{cycle_id}/transition", payload, headers)

    def create_score_sheet(self, cycle_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/evaluation-cycles/{cycle_id}/score-sheets", payload, headers)

    def publish_classification(self, cycle_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/evaluation-cycles/{cycle_id}/publish-classification", payload, headers)

    # ── Score sheets ─────────────────────────────────────────────────────
    def list_score_sheets(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/score-sheets", headers=headers, params=params)

    def get_score_sheet(self, sheet_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/score-sheets/{sheet_id}", headers=headers)

    def finalize_score_sheet(self, sheet_id: str, headers: Optional[Dict[str, str]], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/ppc/score-sheets/{sheet_id}/finalize", payload if payload is not None else {}, headers)

    # ── Classifications ──────────────────────────────────────────────────
    def list_classifications(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/classifications", headers=headers, params=params)

    def get_classification(self, classification_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/classifications/{classification_id}", headers=headers)

    def activate_classification(self, classification_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/classifications/{classification_id}/activate", payload, headers)
