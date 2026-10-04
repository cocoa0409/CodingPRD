"""HTTP client for the Cabinet Program Rollout API.

One method per endpoint the PRD declares (PRD §4). Every method returns the
raw ``requests.Response`` so a test can assert on the status code as well as
the body. Query filters and pagination go through ``params``; request bodies
through ``payload``.

All cabinet-domain resources live under the ``/cabinet`` prefix; the logical
clock endpoint ``POST /_clock/set_current_utc`` is the sole exception and is
deliberately called UNPREFIXED here (PRD §2.4).
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_ENDPOINT

_P = API_PREFIX  # "/cabinet"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so that ``2026-09-01T00:00:00Z`` and
    ``2026-09-01T00:00:00.000Z`` compare equal.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock (UNPREFIXED — PRD §2.4) ───────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_ENDPOINT, payload, headers)

    # ── Accounts ────────────────────────────────────────────────────────────

    def create_account(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/accounts/{account_id}", headers=headers)

    def set_account_status(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/accounts/{account_id}/status", payload, headers)

    # ── Programs and lines ──────────────────────────────────────────────────

    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/programs/{program_id}", headers=headers)

    def list_programs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/programs", headers=headers, params=params)

    def activate_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/programs/{program_id}/activate", {}, headers)

    def create_program_line(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/programs/{program_id}/lines", payload, headers)

    def get_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/lines/{line_id}", headers=headers)

    def list_lines(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/lines", headers=headers, params=params)

    def append_disposition_action(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/lines/{line_id}/disposition-actions", payload, headers)

    # ── Finish batches ──────────────────────────────────────────────────────

    def create_finish_batch(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/finish-batches", payload, headers)

    def retire_finish_batch(self, batch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/finish-batches/{batch_id}/retire", {}, headers)

    # ── Capacity ────────────────────────────────────────────────────────────

    def create_production_slot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/production-slots", payload, headers)

    def list_production_slots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/production-slots", headers=headers, params=params)

    # ── Design service ──────────────────────────────────────────────────────

    def create_design_job(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/design-jobs", payload, headers)

    def get_design_job(self, job_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/design-jobs/{job_id}", headers=headers)

    def list_design_jobs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/design-jobs", headers=headers, params=params)

    def transition_design_job(
        self, job_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/design-jobs/{job_id}/transition", payload, headers)

    def convert_design_job(
        self, job_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/design-jobs/{job_id}/convert", payload, headers)

    # ── Orders ──────────────────────────────────────────────────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/orders/{order_id}", headers=headers)

    def list_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/orders", headers=headers, params=params)

    def transition_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/orders/{order_id}/transition", payload, headers)

    def transition_order_financial(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/orders/{order_id}/financial", payload, headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/orders/{order_id}/cancel", {}, headers)

    # ── Shipments ───────────────────────────────────────────────────────────

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/shipments/{shipment_id}", headers=headers)

    def list_shipments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/shipments", headers=headers, params=params)

    def transition_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/shipments/{shipment_id}/transition", payload, headers)

    # ── Damage claims and replacement logistics ─────────────────────────────

    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{_P}/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/claims/{claim_id}", headers=headers)

    def list_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/claims", headers=headers, params=params)

    def transition_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/claims/{claim_id}/transition", payload, headers)

    def get_replacement_order(
        self, replacement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{_P}/replacement-orders/{replacement_id}", headers=headers)

    def list_replacement_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/replacement-orders", headers=headers, params=params)

    def transition_replacement_order(
        self, replacement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{_P}/replacement-orders/{replacement_id}/transition", payload, headers
        )

    # ── Display resets ──────────────────────────────────────────────────────

    def get_display_reset(self, reset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{_P}/display-resets/{reset_id}", headers=headers)

    def list_display_resets(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{_P}/display-resets", headers=headers, params=params)

    def transition_display_reset(
        self, reset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{_P}/display-resets/{reset_id}/transition", payload, headers)


api_client = ApiClient()
