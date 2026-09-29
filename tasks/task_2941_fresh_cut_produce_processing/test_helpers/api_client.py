"""HTTP client for the Fresh-Cut Produce Processing API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as on the body. Request bodies are
passed as ``payload``; query filters and pagination as ``params``.

The contract mounts every path at the server root with no version prefix, so
paths are used exactly as the contract writes them.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form -
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` - rather than on the raw strings, so that
    ``2026-08-03T07:00:00Z`` and ``2026-08-03T07:00:00.000Z`` compare equal.
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

    # ── The plant logical clock ────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Products ───────────────────────────────────────────────────────────

    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/products", payload, headers)

    def list_products(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/products", params, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/products/{product_id}", None, headers)

    # ── Customer specification revisions ───────────────────────────────────

    def create_customer_spec(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/products/{product_id}/customer-specs", payload, headers)

    def list_customer_specs(
        self, product_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/products/{product_id}/customer-specs", params, headers)

    # ── Lines ──────────────────────────────────────────────────────────────

    def create_line(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/lines", payload, headers)

    def list_lines(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/lines", params, headers)

    def get_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/lines/{line_id}", None, headers)

    # ── Wash systems ───────────────────────────────────────────────────────

    def create_wash_system(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/wash-systems", payload, headers)

    def get_wash_system(self, wash_system_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/wash-systems/{wash_system_id}", None, headers)

    def changeout_wash_system(
        self,
        wash_system_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/wash-systems/{wash_system_id}/changeout", payload, headers
        )

    # ── Wash-water antimicrobial readings ──────────────────────────────────

    def create_antimicrobial_reading(
        self, wash_system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/wash-systems/{wash_system_id}/antimicrobial-readings", payload, headers
        )

    def list_antimicrobial_readings(
        self, wash_system_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/wash-systems/{wash_system_id}/antimicrobial-readings", params, headers
        )

    # ── Grower lots ────────────────────────────────────────────────────────

    def create_grower_lot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/grower-lots", payload, headers)

    def list_grower_lots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/grower-lots", params, headers)

    def get_grower_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/grower-lots/{lot_id}", None, headers)

    def approve_grower_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/grower-lots/{lot_id}/approve", payload, headers)

    def recall_grower_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/grower-lots/{lot_id}/recall", payload, headers)

    # ── Raw receipts ───────────────────────────────────────────────────────

    def create_raw_receipt(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/raw-receipts", payload, headers)

    def get_raw_receipt(self, receipt_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/raw-receipts/{receipt_id}", None, headers)

    def list_lot_raw_receipts(
        self, lot_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/grower-lots/{lot_id}/raw-receipts", params, headers)

    def disposition_raw_receipt(
        self, receipt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/raw-receipts/{receipt_id}/disposition", payload, headers
        )

    # ── Sanitation events ──────────────────────────────────────────────────

    def create_sanitation_event(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lines/{line_id}/sanitation-events", payload, headers)

    def list_sanitation_events(
        self, line_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/lines/{line_id}/sanitation-events", params, headers)

    def start_sanitation_event(
        self, event_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/sanitation-events/{event_id}/start", payload, headers)

    def submit_sanitation_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/sanitation-events/{event_id}/submit", payload, headers)

    def validate_sanitation_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/sanitation-events/{event_id}/validate", payload, headers)

    # ── Environmental swabs ────────────────────────────────────────────────

    def create_environmental_swab(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lines/{line_id}/environmental-swabs", payload, headers)

    def list_environmental_swabs(
        self, line_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/lines/{line_id}/environmental-swabs", params, headers)

    def record_swab_result(
        self, swab_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/environmental-swabs/{swab_id}/result", payload, headers)

    # ── Corrective actions ─────────────────────────────────────────────────

    def list_corrective_actions(
        self, line_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/lines/{line_id}/corrective-actions", params, headers)

    def start_corrective_action(
        self, action_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/corrective-actions/{action_id}/start", payload, headers)

    def submit_corrective_action_verification(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-actions/{action_id}/submit-verification", payload, headers
        )

    def verify_corrective_action(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/corrective-actions/{action_id}/verify", payload, headers)

    # ── Processing runs ────────────────────────────────────────────────────

    def create_process_run(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/process-runs", payload, headers)

    def list_process_runs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/process-runs", params, headers)

    def get_process_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/process-runs/{run_id}", None, headers)

    def start_process_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/process-runs/{run_id}/start", payload, headers)

    def close_process_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/process-runs/{run_id}/close", payload, headers)

    def get_traceability(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/process-runs/{run_id}/traceability", None, headers)

    # ── Lot consumptions ───────────────────────────────────────────────────

    def create_lot_consumption(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/process-runs/{run_id}/lot-consumptions", payload, headers)

    def list_run_lot_consumptions(
        self, run_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/process-runs/{run_id}/lot-consumptions", params, headers)

    def list_receipt_lot_consumptions(
        self, receipt_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/raw-receipts/{receipt_id}/lot-consumptions", params, headers)

    def void_lot_consumption(
        self, consumption_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lot-consumptions/{consumption_id}/void", payload, headers)

    # ── Finished cases ─────────────────────────────────────────────────────

    def list_finished_cases(
        self, run_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/process-runs/{run_id}/finished-cases", params, headers)

    def ship_finished_case(
        self, case_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/finished-cases/{case_id}/ship", payload, headers)

    # ── Hold records ───────────────────────────────────────────────────────

    def create_hold_record(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/process-runs/{run_id}/hold-records", payload, headers)

    def list_hold_records(
        self, run_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/process-runs/{run_id}/hold-records", params, headers)

    def submit_hold_sample(
        self, hold_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/hold-records/{hold_id}/submit-sample", payload, headers)

    def record_hold_result(
        self, hold_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/hold-records/{hold_id}/record-result", payload, headers)

    def release_hold(
        self, hold_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/hold-records/{hold_id}/release", payload, headers)

    def reject_hold(
        self, hold_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/hold-records/{hold_id}/reject", payload, headers)
