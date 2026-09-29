"""API client: one method per endpoint defined in PRD §4.

Every path is mounted under the ``/recommerce`` prefix. Methods return the raw
``requests.Response`` so tests can assert status codes through the framework
validators.

Timestamp canonicalisation lives here on purpose: the PRD fixes instants at
millisecond precision, but an implementation may serialise a whole second as
``...:00Z`` or ``...:00.000Z``. Tests compare instants through
``canonical_instant`` / ``instants_equal`` rather than raw string equality.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/recommerce"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant so precision width cannot fake a diff.

    ``2026-08-01T00:00:00Z``, ``2026-08-01T00:00:00.000Z`` and
    ``2026-08-01T00:00:00.000000Z`` all canonicalise to the same string.
    Non-instant values are returned unchanged.
    """
    if not isinstance(value, str) or "T" not in value:
        return value
    text = value.strip()
    if text.endswith("Z"):
        body, suffix = text[:-1], "Z"
    elif "+" in text[10:]:
        idx = text.index("+", 10)
        body, suffix = text[:idx], "Z"
    else:
        body, suffix = text, "Z"
    if "." in body:
        head, frac = body.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}{suffix}"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instants denote the same moment regardless of precision."""
    if left is None or right is None:
        return left is right or left == right
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint row."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers or {},
        )

    # ------------------------------------------------------------ customers
    def create_customer(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def patch_customer(self, customer_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{PREFIX}/customers/{customer_id}", payload, headers
        )

    def get_customer(self, customer_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/customers/{customer_id}", headers=headers
        )

    # -------------------------------------------------------- grade policies
    def create_grade_policy(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/grade-policies", payload, headers)

    def get_grade_policy(self, grade_policy_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/grade-policies/{grade_policy_id}", headers=headers
        )

    # ------------------------------------------------------- credit policies
    def create_credit_policy(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/credit-policies", payload, headers)

    def get_credit_policy(self, credit_policy_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-policies/{credit_policy_id}", headers=headers
        )

    # ------------------------------------------------------ store locations
    def create_store_location(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/store-locations", payload, headers)

    def patch_store_location(self, store_location_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{PREFIX}/store-locations/{store_location_id}", payload, headers
        )

    def get_store_location(self, store_location_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/store-locations/{store_location_id}", headers=headers
        )

    # ----------------------------------------------------------- refurb bays
    def create_refurb_bay(self, store_location_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/store-locations/{store_location_id}/refurb-bays",
            payload, headers,
        )

    def list_refurb_bays(self, store_location_id: str, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/store-locations/{store_location_id}/refurb-bays",
            headers=headers, params=params,
        )

    def patch_refurb_bay(self, refurb_bay_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{PREFIX}/refurb-bays/{refurb_bay_id}", payload, headers
        )

    # -------------------------------------------------------------- channels
    def create_channel(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/channels", payload, headers)

    def patch_channel(self, channel_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{PREFIX}/channels/{channel_id}", payload, headers
        )

    def get_channel(self, channel_id: str, headers):
        return self._request("GET", f"{PREFIX}/channels/{channel_id}", headers=headers)

    def list_channel_markdown_campaigns(self, channel_id: str, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/channels/{channel_id}/markdown-campaigns",
            headers=headers, params=params,
        )

    # -------------------------------------------------------------- trade-ins
    def create_trade_in(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id: str, headers):
        return self._request("GET", f"{PREFIX}/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trade-ins", headers=headers, params=params)

    def receive_trade_in(self, trade_in_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/trade-ins/{trade_in_id}/receive", payload or {}, headers
        )

    def authenticate_trade_in(self, trade_in_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/trade-ins/{trade_in_id}/authenticate", payload, headers
        )

    def appeal_trade_in(self, trade_in_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/trade-ins/{trade_in_id}/appeal", payload, headers
        )

    def disposition_trade_in(self, trade_in_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/trade-ins/{trade_in_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------ resale units
    def get_resale_unit(self, resale_unit_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/resale-units/{resale_unit_id}", headers=headers
        )

    def list_resale_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/resale-units", headers=headers, params=params
        )

    def list_resale_unit(self, resale_unit_id: str, payload: Dict[str, Any], headers):
        """POST /recommerce/resale-units/{id}/list — put a unit on sale."""
        return self._request(
            "POST", f"{PREFIX}/resale-units/{resale_unit_id}/list", payload, headers
        )

    # ----------------------------------------------------------- refurb orders
    def create_refurb_order(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/refurb-orders", payload, headers)

    def get_refurb_order(self, refurb_order_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/refurb-orders/{refurb_order_id}", headers=headers
        )

    def list_refurb_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/refurb-orders", headers=headers, params=params
        )

    def create_refurb_task(self, refurb_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/refurb-orders/{refurb_order_id}/tasks", payload, headers
        )

    def list_refurb_tasks(self, refurb_order_id: str, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/refurb-orders/{refurb_order_id}/tasks",
            headers=headers, params=params,
        )

    def start_refurb_order(self, refurb_order_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/refurb-orders/{refurb_order_id}/start",
            payload or {}, headers,
        )

    def submit_refurb_order_qc(self, refurb_order_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/refurb-orders/{refurb_order_id}/submit-qc",
            payload or {}, headers,
        )

    def decide_refurb_order_qc(self, refurb_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/refurb-orders/{refurb_order_id}/qc-decision",
            payload, headers,
        )

    # ------------------------------------------------------ markdown campaigns
    def create_markdown_campaign(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/markdown-campaigns", payload, headers)

    def get_markdown_campaign(self, markdown_campaign_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/markdown-campaigns/{markdown_campaign_id}", headers=headers
        )

    def run_markdown_cadence(self, markdown_campaign_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/markdown-campaigns/{markdown_campaign_id}/cadence-runs",
            payload or {}, headers,
        )

    # ----------------------------------------------------------- resale orders
    def create_resale_order(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/resale-orders", payload, headers)

    def get_resale_order(self, resale_order_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/resale-orders/{resale_order_id}", headers=headers
        )

    def list_resale_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/resale-orders", headers=headers, params=params
        )

    def list_resale_order_ledger_entries(self, resale_order_id: str, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/resale-orders/{resale_order_id}/ledger-entries",
            headers=headers, params=params,
        )

    def fulfill_resale_order(self, resale_order_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/resale-orders/{resale_order_id}/fulfill",
            payload or {}, headers,
        )

    def request_resale_order_return(self, resale_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/resale-orders/{resale_order_id}/return-request",
            payload, headers,
        )

    def settle_resale_order_return(self, resale_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/resale-orders/{resale_order_id}/settle-return",
            payload, headers,
        )

    # ----------------------------------------------------------- credit grants
    def get_credit_grant(self, credit_grant_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-grants/{credit_grant_id}", headers=headers
        )

    def list_credit_grants(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/credit-grants", headers=headers, params=params
        )

    def list_credit_grant_ledger_entries(self, credit_grant_id: str, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/credit-grants/{credit_grant_id}/ledger-entries",
            headers=headers, params=params,
        )

    def run_credit_grant_expiry(self, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/credit-grants/expiry-runs", payload or {}, headers
        )

    # ------------------------------------------------------- diversion reports
    def create_diversion_report(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/diversion-reports", payload, headers)

    def get_diversion_report(self, diversion_report_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/diversion-reports/{diversion_report_id}", headers=headers
        )

    def list_diversion_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/diversion-reports", headers=headers, params=params
        )

    def publish_diversion_report(self, diversion_report_id: str, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/diversion-reports/{diversion_report_id}/publish",
            payload or {}, headers,
        )


api_client = ApiClient()
