"""API client: one method per endpoint published by the licensing platform.

Every path is mounted under the ``/erm`` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/erm"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant so sub-second width never breaks equality.

    ``2027-01-02T00:00:00Z``, ``2027-01-02T00:00:00.000Z`` and
    ``2027-01-02T00:00:00.000000Z`` all canonicalise to the same string.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit()).rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text + "Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Electronic Resource Licensing API."""

    # ─── Members ─────────────────────────────────────────────────────────────
    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    # ─── Vendors ─────────────────────────────────────────────────────────────
    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/vendors/{vendor_id}", headers=headers)

    # ─── Products ────────────────────────────────────────────────────────────
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/products/{product_id}", headers=headers)

    def list_products(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/products", headers=headers, params=params)

    # ─── Trials ──────────────────────────────────────────────────────────────
    def create_trial(self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/products/{product_id}/trials", payload, headers)

    def get_trial(self, trial_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/trials/{trial_id}", headers=headers)

    def list_trials(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/trials", headers=headers, params=params)

    def open_trial(self, trial_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/trials/{trial_id}/open", payload or {}, headers)

    def close_trial(self, trial_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/trials/{trial_id}/close", payload or {}, headers)

    def evaluate_trial(self, trial_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/trials/{trial_id}/evaluate", payload or {}, headers)

    def submit_feedback(self, trial_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/trials/{trial_id}/feedback", payload, headers)

    def list_trial_feedback(self, trial_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/trials/{trial_id}/feedback", headers=headers, params=params)

    # ─── Negotiations ────────────────────────────────────────────────────────
    def create_negotiation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/negotiations", payload, headers)

    def get_negotiation(self, negotiation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/negotiations/{negotiation_id}", headers=headers)

    def list_negotiations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/negotiations", headers=headers, params=params)

    def submit_negotiation(self, negotiation_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/negotiations/{negotiation_id}/submit",
                             payload or {}, headers)

    def vendor_response(self, negotiation_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/negotiations/{negotiation_id}/vendor-response",
                             payload, headers)

    def revise_negotiation(self, negotiation_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/negotiations/{negotiation_id}/revise",
                             payload, headers)

    def sign_negotiation(self, negotiation_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/negotiations/{negotiation_id}/sign",
                             payload, headers)

    # ─── Commitments ─────────────────────────────────────────────────────────
    def create_commitment(self, product_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/products/{product_id}/commitments",
                             payload, headers)

    def get_commitment(self, commitment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/commitments/{commitment_id}", headers=headers)

    def list_commitments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/commitments", headers=headers, params=params)

    def withdraw_commitment(self, commitment_id: str, headers: Dict[str, str],
                            payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/commitments/{commitment_id}/withdraw",
                             payload or {}, headers)

    # ─── Subscriptions ───────────────────────────────────────────────────────
    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions", headers=headers, params=params)

    def get_cost_per_use(self, subscription_id: str, headers: Dict[str, str],
                         params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}/cost-per-use",
                             headers=headers, params=params)

    def get_invoice_allocation(self, subscription_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}/invoice-allocation",
                             headers=headers, params=params)

    # ─── Authentication configuration ────────────────────────────────────────
    def create_auth_config(self, subscription_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/subscriptions/{subscription_id}/auth-configs",
                             payload, headers)

    def list_auth_configs(self, subscription_id: str, headers: Dict[str, str],
                          params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}/auth-configs",
                             headers=headers, params=params)

    def verify_auth_config(self, auth_config_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/auth-configs/{auth_config_id}/verify",
                             payload, headers)

    # ─── Access incidents ────────────────────────────────────────────────────
    def create_access_incident(self, subscription_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/subscriptions/{subscription_id}/access-incidents",
                             payload, headers)

    def get_access_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/access-incidents/{incident_id}", headers=headers)

    def list_access_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/access-incidents", headers=headers, params=params)

    def diagnose_incident(self, incident_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/access-incidents/{incident_id}/diagnose",
                             payload, headers)

    def resolve_incident(self, incident_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/access-incidents/{incident_id}/resolve",
                             payload, headers)

    def reopen_incident(self, incident_id: str, headers: Dict[str, str],
                        payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/access-incidents/{incident_id}/reopen",
                             payload or {}, headers)

    # ─── Usage reports ───────────────────────────────────────────────────────
    def create_usage_report(self, subscription_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/subscriptions/{subscription_id}/usage-reports",
                             payload, headers)

    def get_usage_report(self, usage_report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/usage-reports/{usage_report_id}", headers=headers)

    def list_usage_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/usage-reports", headers=headers, params=params)

    # ─── Renewal decisions ───────────────────────────────────────────────────
    def create_renewal_decision(self, subscription_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/subscriptions/{subscription_id}/renewal-decisions",
                             payload, headers)

    def list_renewal_decisions(self, subscription_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}/renewal-decisions",
                             headers=headers, params=params)

    def open_vote(self, decision_id: str, headers: Dict[str, str],
                  payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/renewal-decisions/{decision_id}/open-vote",
                             payload or {}, headers)

    def cast_vote(self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/renewal-decisions/{decision_id}/vote",
                             payload, headers)

    def decide_renewal(self, decision_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/renewal-decisions/{decision_id}/decide",
                             payload, headers)

    def execute_renewal(self, decision_id: str, headers: Dict[str, str],
                        payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/renewal-decisions/{decision_id}/execute",
                             payload or {}, headers)

    def revert_restructure(self, decision_id: str, headers: Dict[str, str],
                           payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/renewal-decisions/{decision_id}/revert-restructure",
                             payload or {}, headers)

    # ─── Archival deposit checks ─────────────────────────────────────────────
    def create_archival_check(self, subscription_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/subscriptions/{subscription_id}/archival-checks",
                             payload, headers)

    def list_archival_checks(self, subscription_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/subscriptions/{subscription_id}/archival-checks",
                             headers=headers, params=params)

    def attest_archival_check(self, check_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/archival-checks/{check_id}/attest",
                             payload, headers)

    def verify_archival_check(self, check_id: str, headers: Dict[str, str],
                              payload: Optional[Dict] = None):
        return self._request("POST", f"{BASE}/archival-checks/{check_id}/verify",
                             payload or {}, headers)

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def advance_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self.set_clock({"to_iso8601": to_iso8601}, headers)

    # ─── Raw escape hatch (used to probe for absent write surfaces) ──────────
    def raw(self, method: str, path: str, payload: Any = None,
            headers: Optional[Dict[str, str]] = None):
        return self._request(method, path, payload, headers)


api_client = ApiClient()
