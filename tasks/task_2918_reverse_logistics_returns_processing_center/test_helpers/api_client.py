"""One method per API endpoint (PRD §4).

Every method returns the raw `requests.Response` so tests can assert on status
codes as well as bodies. Paths are complete as written in the specification —
no mount prefix, no version segment, no tenant segment.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the 64 documented endpoints."""

    # ── Clients ────────────────────────────────────────────────────────

    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clients/{client_id}", None, headers)

    def list_clients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/clients", params, headers)

    def suspend_client(
        self,
        client_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/clients/{client_id}/suspend", payload or {}, headers
        )

    def reinstate_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/clients/{client_id}/reinstate", {}, headers)

    def get_disposition_audit(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}/disposition-audit", None, headers
        )

    # ── Catalog items ──────────────────────────────────────────────────

    def create_catalog_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/catalog-items", payload, headers)

    def get_catalog_item(self, catalog_item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/catalog-items/{catalog_item_id}", None, headers)

    def list_catalog_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/catalog-items", params, headers)

    def recall_catalog_item(
        self, catalog_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/catalog-items/{catalog_item_id}/recall", payload, headers
        )

    # ── Processing bays ────────────────────────────────────────────────

    def create_processing_bay(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/processing-bays", payload, headers)

    def get_processing_bay(self, bay_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/processing-bays/{bay_id}", None, headers)

    def list_processing_bays(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/processing-bays", params, headers)

    # ── Secondary market channels ──────────────────────────────────────

    def create_channel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/secondary-market-channels", payload, headers)

    def get_channel(self, channel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/secondary-market-channels/{channel_id}", None, headers
        )

    def list_channels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/secondary-market-channels", params, headers)

    def pause_channel(
        self,
        channel_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/secondary-market-channels/{channel_id}/pause",
            payload or {},
            headers,
        )

    def resume_channel(self, channel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/secondary-market-channels/{channel_id}/resume", {}, headers
        )

    # ── Return authorizations ──────────────────────────────────────────

    def create_rma(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/return-authorizations", payload, headers)

    def get_rma(self, rma_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/return-authorizations/{rma_id}", None, headers)

    def list_rmas(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/return-authorizations", params, headers)

    def create_rma_line(
        self, rma_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-authorizations/{rma_id}/lines", payload, headers
        )

    def get_rma_line(self, rma_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/return-authorization-lines/{rma_line_id}", None, headers
        )

    def list_rma_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/return-authorization-lines", params, headers)

    def issue_rma(self, rma_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/return-authorizations/{rma_id}/issue", {}, headers
        )

    def void_rma(
        self,
        rma_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/return-authorizations/{rma_id}/void", payload or {}, headers
        )

    def reissue_rma(
        self, rma_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-authorizations/{rma_id}/reissue", payload, headers
        )

    # ── Receipts and scanned unit lines ────────────────────────────────

    def create_receipt(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/receipts", payload, headers)

    def get_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/receipts/{receipt_id}", None, headers)

    def list_receipts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/receipts", params, headers)

    def create_receipt_line(
        self, receipt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/receipts/{receipt_id}/lines", payload, headers
        )

    # ── Return lines ───────────────────────────────────────────────────

    def get_return_line(self, return_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/return-lines/{return_line_id}", None, headers)

    def list_return_lines(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/return-lines", params, headers)

    def list_line_fraud_checks(
        self,
        return_line_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/return-lines/{return_line_id}/fraud-checks", params, headers
        )

    def get_fraud_check(self, fraud_check_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fraud-checks/{fraud_check_id}", None, headers)

    def list_fraud_checks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/fraud-checks", params, headers)

    def quarantine_line(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-lines/{return_line_id}/quarantine", payload, headers
        )

    def grade_line(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-lines/{return_line_id}/grade", payload, headers
        )

    def override_disposition(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/return-lines/{return_line_id}/override-disposition",
            payload,
            headers,
        )

    def clear_fraud_hold(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/return-lines/{return_line_id}/clear-fraud-hold",
            payload,
            headers,
        )

    def release_refund(self, return_line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/return-lines/{return_line_id}/release-refund", {}, headers
        )

    def deny_refund(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-lines/{return_line_id}/deny-refund", payload, headers
        )

    def reverse_refund(
        self, return_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/return-lines/{return_line_id}/reverse-refund", payload, headers
        )

    # ── Refund releases ────────────────────────────────────────────────

    def get_refund_release(self, refund_release_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refund-releases/{refund_release_id}", None, headers
        )

    def list_refund_releases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/refund-releases", params, headers)

    # ── Refurbishment work orders ──────────────────────────────────────

    def create_work_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/refurb-work-orders", payload, headers)

    def get_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refurb-work-orders/{work_order_id}", None, headers
        )

    def list_work_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/refurb-work-orders", params, headers)

    def start_test(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/refurb-work-orders/{work_order_id}/start-test", payload, headers
        )

    def record_test_result(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/refurb-work-orders/{work_order_id}/record-test-result",
            payload,
            headers,
        )

    def repackage_work_order(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/refurb-work-orders/{work_order_id}/repackage", payload, headers
        )

    def abandon_work_order(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/refurb-work-orders/{work_order_id}/abandon", payload, headers
        )

    # ── Disposition orders ─────────────────────────────────────────────

    def create_disposition_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/disposition-orders", payload, headers)

    def get_disposition_order(
        self, disposition_order_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/disposition-orders/{disposition_order_id}", None, headers
        )

    def list_disposition_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/disposition-orders", params, headers)

    def approve_disposition_order(
        self, disposition_order_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/approve",
            {},
            headers,
        )

    def execute_disposition_order(
        self,
        disposition_order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/execute",
            payload or {},
            headers,
        )

    def cancel_disposition_order(
        self,
        disposition_order_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/disposition-orders/{disposition_order_id}/cancel",
            payload,
            headers,
        )

    # ── Pricing feedback ───────────────────────────────────────────────

    def create_pricing_feedback(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/pricing-feedback", payload, headers)

    def get_pricing_feedback(
        self, pricing_feedback_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/pricing-feedback/{pricing_feedback_id}", None, headers
        )

    def list_pricing_feedback(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/pricing-feedback", params, headers)

    # ── Shrink ledger ──────────────────────────────────────────────────

    def get_shrink_ledger_entry(
        self, shrink_ledger_entry_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/shrink-ledger-entries/{shrink_ledger_entry_id}", None, headers
        )

    def list_shrink_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/shrink-ledger-entries", params, headers)

    # ── Logical clock ──────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
