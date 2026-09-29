"""API client: one method per row of the PRD §4 endpoint table (44 rows).

Subclasses GenericApiClient from prd_bench_local_runner.testing; the base
_request() does the HTTP work and returns the raw requests.Response so tests can
assert status codes directly.

Payload dicts are passed through in insertion order, which matters: PRD §2.9
resolves body foreign keys "in the order in which the endpoint declares its
input fields", so the factories build every payload in the declared order and
this client must not reorder it.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Logical clock ----------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- Sellers ----------------
    def register_seller(self, payload: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/sellers", payload, headers)

    def list_sellers(self, headers: Optional[Dict[str, str]] = None,
                     params: Optional[Dict] = None):
        return self._request("GET", "/sellers", headers=headers, params=params)

    def get_seller(self, seller_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def credit_proceeds(self, seller_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/sellers/{seller_id}/proceeds-credits", payload, headers
        )

    def list_seller_snapshots(self, seller_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sellers/{seller_id}/metric-snapshots", headers=headers,
            params=params,
        )

    def list_seller_listings(self, seller_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sellers/{seller_id}/listings", headers=headers, params=params
        )

    def list_seller_notifications(self, seller_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sellers/{seller_id}/notifications", headers=headers, params=params
        )

    # ---------------- Metric snapshots and health evaluations ----------------
    def create_snapshot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/metric-snapshots", payload, headers)

    def create_health_evaluation(self, seller_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sellers/{seller_id}/health-evaluations", payload or {}, headers
        )

    def list_health_evaluations(self, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", "/health-evaluations", headers=headers, params=params)

    def get_health_evaluation(self, evaluation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/health-evaluations/{evaluation_id}", headers=headers)

    # ---------------- Policy catalogue ----------------
    def create_policy_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/policy-rules", payload, headers)

    def list_policy_rules(self, headers: Optional[Dict[str, str]] = None,
                          params: Optional[Dict] = None):
        return self._request("GET", "/policy-rules", headers=headers, params=params)

    # ---------------- Listings ----------------
    def create_listing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/listings", payload, headers)

    def relist_listing(self, listing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/relist", payload or {}, headers
        )

    # ---------------- Violations ----------------
    def create_violation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/violations", payload, headers)

    def list_violations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def get_violation(self, violation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def open_investigation(self, violation_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/violations/{violation_id}/open-investigation", payload or {}, headers
        )

    def adjudicate_violation(self, violation_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/violations/{violation_id}/adjudicate", payload, headers
        )

    # ---------------- Enforcement actions ----------------
    def create_enforcement_action(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enforcement-actions", payload, headers)

    def list_enforcement_actions(self, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", "/enforcement-actions", headers=headers, params=params)

    def get_enforcement_action(self, action_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enforcement-actions/{action_id}", headers=headers)

    def acknowledge_action(self, action_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enforcement-actions/{action_id}/acknowledge", payload or {}, headers
        )

    # ---------------- Plans of action ----------------
    def create_plan_of_action(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plans-of-action", payload, headers)

    def list_plans_of_action(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/plans-of-action", headers=headers, params=params)

    def get_plan_of_action(self, poa_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plans-of-action/{poa_id}", headers=headers)

    def review_plan_of_action(self, poa_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans-of-action/{poa_id}/review", payload, headers
        )

    # ---------------- Appeals ----------------
    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appeals", payload, headers)

    def list_appeals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def start_appeal_review(self, appeal_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/start-review", payload or {}, headers
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    def escalate_appeal(self, appeal_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/appeals/{appeal_id}/escalate", payload, headers)

    def decide_escalation(self, appeal_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/escalation-decision", payload, headers
        )

    # ---------------- Disbursement holds ----------------
    def create_hold(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/disbursement-holds", payload, headers)

    def list_holds(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/disbursement-holds", headers=headers, params=params)

    def get_hold(self, hold_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disbursement-holds/{hold_id}", headers=headers)

    def release_hold(self, hold_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursement-holds/{hold_id}/release", payload, headers
        )

    def forfeit_hold(self, hold_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/disbursement-holds/{hold_id}/forfeit", payload, headers
        )

    # ---------------- Related-account links ----------------
    def list_related_account_links(self, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", "/related-account-links", headers=headers, params=params)

    def get_related_account_link(self, link_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/related-account-links/{link_id}", headers=headers)

    def adjudicate_related_account_link(self, link_id: str, payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/related-account-links/{link_id}/adjudicate", payload, headers
        )


api_client = ApiClient()
