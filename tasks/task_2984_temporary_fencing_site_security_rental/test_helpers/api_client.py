"""HTTP client for the Temporary Fencing & Site Security Rental API.

One method per endpoint of PRD §4.  Every method returns the raw
``requests.Response`` so that tests can assert status codes themselves.

Instant canonicalisation
------------------------
PRD §2.6 requires every instant to be an ISO 8601 UTC timestamp ending in ``Z``
but does not fix the number of fractional-second digits an entity field must
carry.  ``canonical_instant`` therefore reduces any conforming spelling of the
same moment to a single comparable form, so that tests never assert raw string
equality on a timestamp.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from . import constants as C


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``.

    Trailing zero fractional digits are dropped so that ``...T10:00:00Z``,
    ``...T10:00:00.000Z`` and ``...T10:00:00.000000+00:00`` all compare equal.
    """
    if value is None:
        return None
    dt = parse_instant(value)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-naive UTC ``datetime``."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def shift_instant(value: str, **delta: Any) -> str:
    """Return ``value`` moved by a :class:`datetime.timedelta` keyword delta."""
    return (parse_instant(value) + timedelta(**delta)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    ) + "Z"


class FenceRentalsClient(GenericApiClient):
    """Endpoint methods for every path in PRD §4."""

    # -- logical clock (PRD §2.6) -------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", C.CLOCK_PATH, {"current_utc": current_utc}, headers or {}
        )

    def set_clock_raw(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", C.CLOCK_PATH, payload, headers or {})

    # -- municipalities -----------------------------------------------------

    def create_municipality(self, payload: Any, headers: Dict):
        return self._request("POST", C.MUNICIPALITIES, payload, headers)

    def get_municipality(self, municipality_id: str, headers: Dict):
        return self._request(
            "GET", f"{C.MUNICIPALITIES}/{municipality_id}", None, headers
        )

    def list_municipalities(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.MUNICIPALITIES, None, headers, params=params)

    # -- accounts -----------------------------------------------------------

    def create_account(self, payload: Any, headers: Dict):
        return self._request("POST", C.ACCOUNTS, payload, headers)

    def get_account(self, account_id: str, headers: Dict):
        return self._request("GET", f"{C.ACCOUNTS}/{account_id}", None, headers)

    def list_accounts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.ACCOUNTS, None, headers, params=params)

    def create_payment(self, account_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.ACCOUNTS}/{account_id}/payments", payload, headers
        )

    # -- products -----------------------------------------------------------

    def create_product(self, payload: Any, headers: Dict):
        return self._request("POST", C.PRODUCTS, payload, headers)

    def get_product(self, product_id: str, headers: Dict):
        return self._request("GET", f"{C.PRODUCTS}/{product_id}", None, headers)

    def list_products(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.PRODUCTS, None, headers, params=params)

    # -- crews --------------------------------------------------------------

    def create_crew(self, payload: Any, headers: Dict):
        return self._request("POST", C.CREWS, payload, headers)

    def get_crew(self, crew_id: str, headers: Dict):
        return self._request("GET", f"{C.CREWS}/{crew_id}", None, headers)

    def list_crews(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.CREWS, None, headers, params=params)

    # -- jobsites -----------------------------------------------------------

    def create_jobsite(self, payload: Any, headers: Dict):
        return self._request("POST", C.JOBSITES, payload, headers)

    def get_jobsite(self, jobsite_id: str, headers: Dict):
        return self._request("GET", f"{C.JOBSITES}/{jobsite_id}", None, headers)

    def list_jobsites(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.JOBSITES, None, headers, params=params)

    # -- quotes -------------------------------------------------------------

    def create_quote(self, jobsite_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.JOBSITES}/{jobsite_id}/quotes", payload, headers
        )

    def get_quote(self, quote_id: str, headers: Dict):
        return self._request("GET", f"{C.QUOTES}/{quote_id}", None, headers)

    def list_quotes(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.QUOTES, None, headers, params=params)

    def issue_quote(self, quote_id: str, headers: Dict, payload: Any = None):
        return self._request(
            "POST", f"{C.QUOTES}/{quote_id}/issue", {} if payload is None else payload,
            headers,
        )

    def accept_quote(self, quote_id: str, payload: Any, headers: Dict):
        return self._request("POST", f"{C.QUOTES}/{quote_id}/accept", payload, headers)

    # -- permits ------------------------------------------------------------

    def create_permit(self, payload: Any, headers: Dict):
        return self._request("POST", C.PERMITS, payload, headers)

    def get_permit(self, permit_id: str, headers: Dict):
        return self._request("GET", f"{C.PERMITS}/{permit_id}", None, headers)

    def list_permits(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.PERMITS, None, headers, params=params)

    def submit_permit(self, permit_id: str, headers: Dict, payload: Any = None):
        return self._request(
            "POST",
            f"{C.PERMITS}/{permit_id}/submit",
            {} if payload is None else payload,
            headers,
        )

    def decide_permit(self, permit_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.PERMITS}/{permit_id}/municipal-decision", payload, headers
        )

    # -- contracts ----------------------------------------------------------

    def create_contract(self, payload: Any, headers: Dict):
        return self._request("POST", C.CONTRACTS, payload, headers)

    def get_contract(self, contract_id: str, headers: Dict):
        return self._request("GET", f"{C.CONTRACTS}/{contract_id}", None, headers)

    def list_contracts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.CONTRACTS, None, headers, params=params)

    def create_work_order(self, contract_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.CONTRACTS}/{contract_id}/work-orders", payload, headers
        )

    def create_reset_order(self, contract_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.CONTRACTS}/{contract_id}/reset-orders", payload, headers
        )

    def cancel_contract(self, contract_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.CONTRACTS}/{contract_id}/cancel", payload, headers
        )

    def create_billing_run(self, contract_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.CONTRACTS}/{contract_id}/billing-runs", payload, headers
        )

    # -- work orders --------------------------------------------------------

    def get_work_order(self, work_order_id: str, headers: Dict):
        return self._request("GET", f"{C.WORK_ORDERS}/{work_order_id}", None, headers)

    def list_work_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.WORK_ORDERS, None, headers, params=params)

    def dispatch_work_order(self, work_order_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.WORK_ORDERS}/{work_order_id}/dispatch", payload, headers
        )

    def complete_work_order(self, work_order_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.WORK_ORDERS}/{work_order_id}/complete", payload, headers
        )

    def abort_work_order(self, work_order_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.WORK_ORDERS}/{work_order_id}/abort", payload, headers
        )

    def cancel_work_order(self, work_order_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.WORK_ORDERS}/{work_order_id}/cancel", payload, headers
        )

    # -- invoices -----------------------------------------------------------

    def get_invoice(self, invoice_id: str, headers: Dict):
        return self._request("GET", f"{C.INVOICES}/{invoice_id}", None, headers)

    def list_invoices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.INVOICES, None, headers, params=params)

    def void_invoice(self, invoice_id: str, payload: Any, headers: Dict):
        return self._request(
            "POST", f"{C.INVOICES}/{invoice_id}/void", payload, headers
        )

    # -- reconciliations ----------------------------------------------------

    def get_reconciliation(self, reconciliation_id: str, headers: Dict):
        return self._request(
            "GET", f"{C.RECONCILIATIONS}/{reconciliation_id}", None, headers
        )

    def list_reconciliations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", C.RECONCILIATIONS, None, headers, params=params)

    def finalize_reconciliation(
        self, reconciliation_id: str, payload: Any, headers: Dict
    ):
        return self._request(
            "POST",
            f"{C.RECONCILIATIONS}/{reconciliation_id}/finalize",
            payload,
            headers,
        )
