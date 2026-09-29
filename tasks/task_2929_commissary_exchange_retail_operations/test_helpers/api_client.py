"""HTTP client: one method per endpoint of the API under test (PRD 4).

Every method returns the raw ``requests.Response`` so tests can assert both the
status code and the envelope. Action endpoints that take no payload still send
an empty JSON object rather than a null body.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings compare equal.

    PRD 2.4 fixes the wire format at three fractional digits with a trailing
    ``Z``, but the sub-second width of a literal a test sends in is not
    interesting to any assertion. Comparisons therefore run through this
    canonicaliser instead of matching raw strings.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000000")[:6].rstrip("0")
    else:
        head, frac = text, ""
    if len(head) == 10:  # a bare date, widened to midnight
        head = head + "T00:00:00"
    return f"{head}.{frac}Z" if frac else f"{head}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instant spellings denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Typed wrapper over the flat endpoint surface described in PRD 4."""

    # -- helpers ---------------------------------------------------------
    def _action(
        self,
        path: str,
        payload: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
    ) -> requests.Response:
        return self._request("POST", path, payload if payload is not None else {}, headers)

    # -- logical clock (PRD 2.5) -----------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- stores (PRD 3.1) ------------------------------------------------
    def create_store(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/stores", params, headers)

    def get_store(self, store_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}", None, headers)

    def close_period(self, store_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/stores/{store_id}/close-period", payload, headers)

    def list_fund_ledger(self, store_id: str, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/fund-ledger", params, headers)

    def list_store_mwr_programs(self, store_id: str, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/mwr-programs", params, headers)

    # -- patrons (PRD 3.2, 3.7) -----------------------------------------
    def create_patron(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/patrons", payload, headers)

    def list_patrons(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/patrons", params, headers)

    def get_patron(self, patron_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/patrons/{patron_id}", None, headers)

    def set_card_status(self, patron_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/patrons/{patron_id}/card-status", payload, headers)

    def compliance_review(self, patron_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/patrons/{patron_id}/compliance-review", payload, headers)

    # -- shopper delegations (PRD 3.3) ----------------------------------
    def create_delegation(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/shopper-delegations", payload, headers)

    def list_delegations(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/shopper-delegations", params, headers)

    def get_delegation(self, delegation_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/shopper-delegations/{delegation_id}", None, headers)

    def revoke_delegation(self, delegation_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/shopper-delegations/{delegation_id}/revoke", payload, headers)

    # -- products (PRD 3.4) ---------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/products", payload, headers)

    def list_products(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/products", params, headers)

    def get_product(self, product_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/products/{product_id}", None, headers)

    # -- assortments (PRD 3.4) ------------------------------------------
    def create_assortment(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/assortments", payload, headers)

    def list_assortments(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/assortments", params, headers)

    def get_assortment(self, assortment_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/assortments/{assortment_id}", None, headers)

    def retire_assortment(self, assortment_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/assortments/{assortment_id}/retire", payload, headers)

    # -- sales (PRD 3.5, 3.6) -------------------------------------------
    def open_sale(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/sales", payload, headers)

    def add_sale_line(self, sale_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/sales/{sale_id}/lines", payload, headers)

    def tender_sale(self, sale_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/sales/{sale_id}/tender", payload, headers)

    def void_sale(self, sale_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/sales/{sale_id}/void", payload, headers)

    def list_sales(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/sales", params, headers)

    def get_sale(self, sale_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/sales/{sale_id}", None, headers)

    def list_sale_lines(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/sale-lines", params, headers)

    def get_sale_line(self, sale_line_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/sale-lines/{sale_line_id}", None, headers)

    # -- MWR programmes (PRD 3.9) ---------------------------------------
    def create_mwr_program(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/mwr-programs", payload, headers)

    def get_mwr_program(self, program_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/mwr-programs/{program_id}", None, headers)

    # -- capital projects (PRD 3.9) -------------------------------------
    def create_capital_project(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/capital-projects", payload, headers)

    def list_capital_projects(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/capital-projects", params, headers)

    def get_capital_project(self, project_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/capital-projects/{project_id}", None, headers)

    def submit_capital_project(self, project_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/capital-projects/{project_id}/submit", payload, headers)

    def decide_capital_project(self, project_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/capital-projects/{project_id}/decision", payload, headers)

    def close_capital_project(self, project_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/capital-projects/{project_id}/close", payload, headers)

    # -- special orders (PRD 3.8) ---------------------------------------
    def create_special_order(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", "/special-orders", params, headers)

    def get_special_order(self, order_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"/special-orders/{order_id}", None, headers)

    def route_special_order(self, order_id: str, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"/special-orders/{order_id}/route", payload, headers)

    def cancel_special_order(self, order_id: str, payload: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._action(f"/special-orders/{order_id}/cancel", payload, headers)


# Module-level singleton used by conftest and the fixtures.
api_client = ApiClient()
