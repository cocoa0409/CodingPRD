"""Typed HTTP surface for the rulemaking / disclosure / dealer-compliance API.

One method per operation of PRD section 4, so no test body ever spells a URL.
Every method returns the raw ``requests.Response``; validating the envelope is
the caller's job via the framework validators.

Routing note (PRD section 4): every business endpoint lives under the ``/msrb``
prefix EXCEPT the logical-clock operation, which is deliberately mounted
outside that prefix. ``set_clock`` therefore spells its path in full.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

PREFIX = API_PREFIX


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the API under test."""

    # ------------------------------------------------------------------
    # Logical clock (PRD section 2.4) - mounted OUTSIDE the /msrb prefix.
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Organizations (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_organization(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/organizations", payload, headers)

    def get_organization(self, org_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/organizations/{org_id}", headers=headers)

    def suspend_organization(self, org_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/organizations/{org_id}/suspend", payload, headers)

    def list_solicitation_records(
        self, org_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/organizations/{org_id}/solicitation-records", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Rule proposals and comment letters (PRD sections 3.1-3.3)
    # ------------------------------------------------------------------
    def create_rule_proposal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rule-proposals", payload, headers)

    def list_rule_proposals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rule-proposals", headers=headers, params=params)

    def get_rule_proposal(self, proposal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rule-proposals/{proposal_id}", headers=headers)

    def patch_rule_proposal(self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/rule-proposals/{proposal_id}", payload, headers)

    def open_comment_period(self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/rule-proposals/{proposal_id}/open-comment-period", payload, headers
        )

    def submit_for_approval(self, proposal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/rule-proposals/{proposal_id}/submit-for-approval", {}, headers
        )

    def decide_proposal(self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rule-proposals/{proposal_id}/decide", payload, headers)

    def create_comment_letter(self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/rule-proposals/{proposal_id}/comment-letters", payload, headers
        )

    def list_comment_letters(
        self, proposal_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/rule-proposals/{proposal_id}/comment-letters", headers=headers, params=params
        )

    def moderate_comment_letter(self, letter_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/comment-letters/{letter_id}/moderate", payload, headers)

    # ------------------------------------------------------------------
    # Disclosure submissions (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_disclosure_submission(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/disclosure-submissions", payload, headers)

    def list_disclosure_submissions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/disclosure-submissions", headers=headers, params=params)

    def get_disclosure_submission(self, submission_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/disclosure-submissions/{submission_id}", headers=headers)

    def review_submission(self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/disclosure-submissions/{submission_id}/review-outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # Professionals, exams, continuing education (PRD section 3.6)
    # ------------------------------------------------------------------
    def create_professional(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/professionals", payload, headers)

    def list_professionals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/professionals", headers=headers, params=params)

    def get_professional(self, professional_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/professionals/{professional_id}", headers=headers)

    def set_professional_standing(self, professional_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/professionals/{professional_id}/standing", payload, headers
        )

    def record_ce_credits(self, professional_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/professionals/{professional_id}/ce-credits", payload, headers
        )

    def create_exam_attempt(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/exam-attempts", payload, headers)

    def list_exam_attempts(
        self, professional_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/professionals/{professional_id}/exam-attempts", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Trade reports (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_trade_report(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/trade-reports", payload, headers)

    def list_trade_reports(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/trade-reports", headers=headers, params=params)

    def get_trade_report(self, trade_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/trade-reports/{trade_id}", headers=headers)

    def cancel_trade_report(self, trade_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/trade-reports/{trade_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Data subscriptions and licensed feeds (PRD section 3.7)
    # ------------------------------------------------------------------
    def create_data_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/data-subscriptions", payload, headers)

    def list_data_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/data-subscriptions", headers=headers, params=params)

    def get_data_subscription(self, subscription_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/data-subscriptions/{subscription_id}", headers=headers)

    def transition_data_subscription(self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/data-subscriptions/{subscription_id}/transition", payload, headers
        )

    def get_data_feed(self, product_code: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/data-feeds/{product_code}", headers=headers)

    # ------------------------------------------------------------------
    # Enforcement referrals (PRD section 3.8)
    # ------------------------------------------------------------------
    def create_enforcement_referral(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/enforcement-referrals", payload, headers)

    def list_enforcement_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/enforcement-referrals", headers=headers, params=params)

    def get_enforcement_referral(self, referral_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/enforcement-referrals/{referral_id}", headers=headers)

    def advance_enforcement_referral(self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/enforcement-referrals/{referral_id}/advance", payload, headers
        )

    # ------------------------------------------------------------------
    # Solicitation records (PRD section 3.8)
    # ------------------------------------------------------------------
    def create_solicitation_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/solicitation-records", payload, headers)

    # ------------------------------------------------------------------
    # Raw escape hatch for negative-path probes (e.g. unauthenticated calls
    # that must omit the credential headers entirely).
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)


# Shared client instance; tests may also construct their own ApiClient().
api_client = ApiClient()
