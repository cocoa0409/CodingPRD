"""Typed client for the Wholesale Auction Arbitration API (PRD section 4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ArbitrationApiClient(GenericApiClient):
    """One method per endpoint in the PRD endpoint table.

    Every method takes an explicit `headers` mapping so that each test states
    which role and identity it is acting as.
    """

    # --- Registry: sellers -----------------------------------------------------

    def create_seller(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitration/sellers", payload, headers)

    def get_seller(self, seller_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitration/sellers/{seller_id}", None, headers)

    def reinstate_seller(
        self, seller_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/sellers/{seller_id}/reinstate", payload, headers
        )

    def list_seller_policy_actions(self, seller_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/sellers/{seller_id}/policy-actions", None, headers
        )

    def get_seller_scorecard(self, seller_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/sellers/{seller_id}/scorecard", None, headers
        )

    # --- Registry: buyers ------------------------------------------------------

    def create_buyer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitration/buyers", payload, headers)

    def get_buyer(self, buyer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitration/buyers/{buyer_id}", None, headers)

    def pay_buyer_fee(
        self, buyer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/buyers/{buyer_id}/fee-payments", payload, headers
        )

    def list_buyer_frivolous_fees(self, buyer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/buyers/{buyer_id}/frivolous-fees", None, headers
        )

    # --- Registry: policies ----------------------------------------------------

    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitration/policies", payload, headers)

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitration/policies/{policy_id}", None, headers)

    # --- The block: sales ------------------------------------------------------

    def create_sale(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitration/sales", payload, headers)

    def get_sale(self, sale_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitration/sales/{sale_id}", None, headers)

    def list_sales(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", "/arbitration/sales", None, headers, params)

    def create_announcement(
        self, sale_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/sales/{sale_id}/announcements", payload, headers
        )

    def list_announcements(self, sale_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/sales/{sale_id}/announcements", None, headers
        )

    def settle_sale(
        self, sale_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/sales/{sale_id}/settle", payload, headers
        )

    def list_sale_ledger_entries(self, sale_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/sales/{sale_id}/ledger-entries", None, headers
        )

    def list_sale_inspections(self, sale_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/sales/{sale_id}/post-sale-inspections", None, headers
        )

    # --- Post-sale inspections -------------------------------------------------

    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/arbitration/post-sale-inspections", payload, headers
        )

    def complete_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/arbitration/post-sale-inspections/{inspection_id}/complete",
            payload,
            headers,
        )

    # --- Arbitration cases -----------------------------------------------------

    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitration/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitration/cases/{case_id}", None, headers)

    def list_cases(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", "/arbitration/cases", None, headers, params)

    def create_evidence(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/evidence", payload, headers
        )

    def list_evidence(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/evidence", None, headers
        )

    def open_review(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/open-review", payload, headers
        )

    def seller_response(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/seller-response", payload, headers
        )

    def list_negotiation_rounds(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/negotiation-rounds", None, headers
        )

    def counter_round(
        self,
        case_id: str,
        round_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/arbitration/cases/{case_id}/negotiation-rounds/{round_id}/counter",
            payload,
            headers,
        )

    def accept_round(
        self,
        case_id: str,
        round_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/arbitration/cases/{case_id}/negotiation-rounds/{round_id}/accept",
            payload,
            headers,
        )

    def create_transport_leg(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/transport-legs", payload, headers
        )

    def list_transport_legs(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/transport-legs", None, headers
        )

    def escalate_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/escalate", payload, headers
        )

    def create_decision(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/decision", payload, headers
        )

    def list_decision(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/decision", None, headers
        )

    def list_case_ledger_entries(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/ledger-entries", None, headers
        )

    def withdraw_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/arbitration/cases/{case_id}/withdraw", payload, headers
        )

    def list_case_frivolous_fees(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/frivolous-fees", None, headers
        )

    def list_case_policy_actions(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/arbitration/cases/{case_id}/policy-actions", None, headers
        )

    # --- Internal test-driving capabilities ------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_sweep(self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_ops/run-arbitration-sweep", payload if payload is not None else {}, headers
        )
