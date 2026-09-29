"""Typed HTTP client with one method per endpoint of PRD section 4.

Every method returns the raw ``requests.Response`` so that tests assert the
status code themselves. Query parameters are dropped when None so that a
list call can distinguish "filter omitted" from "filter supplied".
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/group-sales"


def _params(**kwargs: Any) -> Dict[str, Any]:
    """Drop keys whose value is None so omitted filters stay omitted.

    Booleans are rendered as the JSON spellings ``true`` / ``false`` because a
    query string carries text, and ``is_master`` is declared as a boolean
    filter in PRD 2.11.
    """
    out: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        out[key] = "true" if value is True else "false" if value is False else value
    return out


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant so two spellings compare equal.

    PRD 2.4 states that "instants the server mints are rendered with three
    fractional digits", while a client may legitimately send an instant with
    none. Comparisons between a value a test supplied and a value the server
    minted therefore go through this canonical form, which keeps the instant
    but removes the fractional-width difference.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text + "Z"


class ApiClient(GenericApiClient):
    """One method per endpoint declared in PRD section 4."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4)
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Client organizations (PRD 3.1)
    # ------------------------------------------------------------------

    def create_account(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/accounts", payload=payload, headers=headers)

    def get_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/accounts/{account_id}", headers=headers)

    def list_account_leads(
        self,
        account_id: str,
        headers: Dict[str, str],
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/accounts/{account_id}/leads",
            payload=_params(status=status, limit=limit, offset=offset),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Concession packages (PRD 3.1)
    # ------------------------------------------------------------------

    def create_package(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/concession-packages", payload=payload, headers=headers
        )

    def get_package(self, package_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/concession-packages/{package_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # House inventory calendar (PRD 2.9, 3.1)
    # ------------------------------------------------------------------

    def create_inventory_day(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/inventory-days", payload=payload, headers=headers
        )

    def list_inventory_days(
        self,
        headers: Dict[str, str],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/inventory-days",
            payload=_params(
                from_date=from_date, to_date=to_date, limit=limit, offset=offset
            ),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Leads (PRD 3.2)
    # ------------------------------------------------------------------

    def create_lead(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/leads", payload=payload, headers=headers)

    def get_lead(self, lead_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/leads/{lead_id}", headers=headers)

    def qualify_lead(self, lead_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/leads/{lead_id}/qualify", payload={}, headers=headers
        )

    def list_lead_displacement_analyses(
        self,
        lead_id: str,
        headers: Dict[str, str],
        analysis_variant: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/leads/{lead_id}/displacement-analyses",
            payload=_params(
                analysis_variant=analysis_variant, status=status,
                limit=limit, offset=offset,
            ),
            headers=headers,
        )

    def list_lead_function_space_holds(
        self,
        lead_id: str,
        headers: Dict[str, str],
        space_code: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/leads/{lead_id}/function-space-holds",
            payload=_params(
                space_code=space_code, status=status, limit=limit, offset=offset
            ),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Function space (PRD 3.2)
    # ------------------------------------------------------------------

    def create_function_space_hold(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/function-space-holds", payload=payload, headers=headers
        )

    def get_function_space_hold(
        self, hold_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/function-space-holds/{hold_id}", headers=headers
        )

    def release_function_space_hold(
        self, hold_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/function-space-holds/{hold_id}/release",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Displacement studies (PRD 3.3)
    # ------------------------------------------------------------------

    def create_displacement_analysis(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/displacement-analyses", payload=payload, headers=headers
        )

    def get_displacement_analysis(
        self, analysis_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/displacement-analyses/{analysis_id}", headers=headers
        )

    def decide_displacement_analysis(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/displacement-analyses/{analysis_id}/decide",
            payload=payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Rate quotes (PRD 3.4)
    # ------------------------------------------------------------------

    def create_rate_quote(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/rate-quotes", payload=payload, headers=headers
        )

    def get_rate_quote(self, quote_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/rate-quotes/{quote_id}", headers=headers)

    def list_rate_quotes(
        self,
        headers: Dict[str, str],
        lead_id: Optional[str] = None,
        concession_package_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/rate-quotes",
            payload=_params(
                lead_id=lead_id, concession_package_id=concession_package_id,
                status=status, limit=limit, offset=offset,
            ),
            headers=headers,
        )

    def propose_rate_quote(
        self, quote_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/rate-quotes/{quote_id}/propose", payload={}, headers=headers
        )

    def counter_rate_quote(
        self, quote_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/rate-quotes/{quote_id}/counter",
            payload=payload, headers=headers,
        )

    def revise_rate_quote(
        self, quote_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/rate-quotes/{quote_id}/revise",
            payload=payload, headers=headers,
        )

    def accept_rate_quote(
        self, quote_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/rate-quotes/{quote_id}/accept", payload={}, headers=headers
        )

    # ------------------------------------------------------------------
    # Contracts (PRD 3.5, 3.9)
    # ------------------------------------------------------------------

    def create_contract(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts", payload=payload, headers=headers
        )

    def get_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/contracts/{contract_id}", headers=headers)

    def list_contracts(
        self,
        headers: Dict[str, str],
        quote_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/contracts",
            payload=_params(
                quote_id=quote_id, status=status, limit=limit, offset=offset
            ),
            headers=headers,
        )

    def send_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/send", payload={}, headers=headers
        )

    def sign_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/sign",
            payload=payload, headers=headers,
        )

    def cancel_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/cancel",
            payload=payload, headers=headers,
        )

    def list_contract_reconciliations(
        self,
        contract_id: str,
        headers: Dict[str, str],
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/contracts/{contract_id}/reconciliations",
            payload=_params(status=status, limit=limit, offset=offset),
            headers=headers,
        )

    def list_contract_ancillary_charges(
        self,
        contract_id: str,
        headers: Dict[str, str],
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/contracts/{contract_id}/ancillary-charges",
            payload=_params(
                category=category, status=status, limit=limit, offset=offset
            ),
            headers=headers,
        )

    def create_reconciliation(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/reconciliations",
            payload=payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Room blocks and their nights (PRD 3.6, 3.7)
    # ------------------------------------------------------------------

    def create_room_block(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/room-blocks", payload=payload, headers=headers
        )

    def get_room_block(self, block_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/room-blocks/{block_id}", headers=headers)

    def list_room_blocks(
        self,
        headers: Dict[str, str],
        contract_id: Optional[str] = None,
        parent_block_id: Optional[str] = None,
        is_master: Optional[bool] = None,
        inventory_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/room-blocks",
            payload=_params(
                contract_id=contract_id, parent_block_id=parent_block_id,
                is_master=is_master, inventory_status=inventory_status,
                limit=limit, offset=offset,
            ),
            headers=headers,
        )

    def list_block_nights(
        self,
        block_id: str,
        headers: Dict[str, str],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/room-blocks/{block_id}/nights",
            payload=_params(
                from_date=from_date, to_date=to_date, limit=limit, offset=offset
            ),
            headers=headers,
        )

    def list_block_reservations(
        self,
        block_id: str,
        headers: Dict[str, str],
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/room-blocks/{block_id}/reservations",
            payload=_params(status=status, limit=limit, offset=offset),
            headers=headers,
        )

    def get_pickup_summary(
        self, block_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/room-blocks/{block_id}/pickup-summary", headers=headers
        )

    def open_room_block(
        self, block_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/room-blocks/{block_id}/open", payload={}, headers=headers
        )

    def cutoff_room_block(
        self, block_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/room-blocks/{block_id}/cutoff", payload={}, headers=headers
        )

    def waive_attrition(
        self, block_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/room-blocks/{block_id}/waive-attrition",
            payload=payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Reservations (PRD 3.6)
    # ------------------------------------------------------------------

    def create_reservation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reservations", payload=payload, headers=headers
        )

    def get_reservation(
        self, reservation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/reservations/{reservation_id}", headers=headers
        )

    def advance_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reservations/{reservation_id}/advance",
            payload=payload, headers=headers,
        )

    def cancel_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reservations/{reservation_id}/cancel",
            payload=payload, headers=headers,
        )

    # ------------------------------------------------------------------
    # Ancillary revenue (PRD 3.8)
    # ------------------------------------------------------------------

    def create_ancillary_charge(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/ancillary-charges", payload=payload, headers=headers
        )

    def get_ancillary_charge(
        self, charge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/ancillary-charges/{charge_id}", headers=headers
        )

    def post_ancillary_charge(
        self, charge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/ancillary-charges/{charge_id}/post",
            payload={}, headers=headers,
        )

    def void_ancillary_charge(
        self, charge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/ancillary-charges/{charge_id}/void",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Settlement (PRD 3.9)
    # ------------------------------------------------------------------

    def get_reconciliation(
        self, reconciliation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/reconciliations/{reconciliation_id}", headers=headers
        )

    def finalize_reconciliation(
        self, reconciliation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reconciliations/{reconciliation_id}/finalize",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for probes that must bypass the typed helpers.
    # ------------------------------------------------------------------

    def raw_get(
        self, path: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", path, payload=params, headers=headers)

    def raw_post(
        self, path: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", path, payload=payload, headers=headers)
