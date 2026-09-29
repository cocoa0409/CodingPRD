"""One method per declared endpoint, plus instant canonicalisation.

Timestamps come back with a three-digit fractional part, so every comparison a
test makes goes through `canonical_instant` rather than through raw string
equality: `2026-08-01T00:00:00Z` and `2026-08-01T00:00:00.000Z` name the same
instant and must compare equal.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 instant to a three-digit fractional part in Z form."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    else:
        # Truncate a numeric UTC offset; the contract only ever emits UTC.
        for sign in ("+", "-"):
            marker = text.rfind(sign)
            if marker > 10:
                text = text[:marker]
                break
    if "." in text:
        head, _, frac = text.partition(".")
    else:
        head, frac = text, ""
    frac = (frac + "000")[:3]
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper: one method per row of the endpoint table."""

    # -- Standing registries -------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customers/{customer_id}", None, headers)

    def create_insurer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurers", payload, headers)

    def get_insurer(self, insurer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurers/{insurer_id}", None, headers)

    def create_parts_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/parts-vendors", payload, headers)

    def get_parts_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parts-vendors/{vendor_id}", None, headers)

    def create_stall(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stalls", payload, headers)

    def get_stall(self, stall_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stalls/{stall_id}", None, headers)

    def create_calibration_bay(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/calibration-bays", payload, headers)

    def get_calibration_bay(self, bay_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/calibration-bays/{bay_id}", None, headers)

    # -- The logical clock ---------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Intake, teardown, blueprint ----------------------------------------
    def create_repair_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/repair-orders/{order_id}", None, headers)

    def list_repair_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/repair-orders", params, headers)

    def create_teardown_finding(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/teardown-findings", payload, headers
        )

    def list_damage_lines(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/repair-orders/{order_id}/damage-lines", params, headers
        )

    def publish_blueprint(
        self, order_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/blueprint", payload, headers
        )

    # -- The estimate --------------------------------------------------------
    def create_estimate_line(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/estimate-lines", payload, headers
        )

    def get_estimate_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/estimate-lines/{line_id}", None, headers)

    def list_estimate_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/estimate-lines", params, headers)

    def lock_estimate(
        self, order_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/estimate/lock", payload, headers
        )

    def declare_total_loss(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/total-loss", payload, headers
        )

    # -- Supplements and consent --------------------------------------------
    def create_supplement(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/supplements", payload, headers
        )

    def list_supplements(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/repair-orders/{order_id}/supplements", params, headers
        )

    def get_supplement(self, supplement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/supplements/{supplement_id}", None, headers)

    def decide_supplement(
        self, supplement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/supplements/{supplement_id}/decision", payload, headers
        )

    def resubmit_supplement(
        self, supplement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/supplements/{supplement_id}/resubmit", payload, headers
        )

    def create_consent_decision(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/consent-decisions", payload, headers
        )

    # -- Parts ---------------------------------------------------------------
    def create_parts_line(
        self, estimate_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/estimate-lines/{estimate_line_id}/parts-lines", payload, headers
        )

    def get_parts_line(self, parts_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parts-lines/{parts_line_id}", None, headers)

    def list_parts_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/parts-lines", params, headers)

    def quote_parts_line(
        self, parts_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/quote", payload, headers
        )

    def counter_offer_parts_line(
        self, parts_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/counter-offer", payload, headers
        )

    def accept_parts_price(
        self,
        parts_line_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/accept-price", payload, headers
        )

    def order_parts_line(
        self, parts_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/order", payload, headers
        )

    def receive_parts_line(
        self, parts_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/receive", payload, headers
        )

    def return_parts_line(
        self, parts_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/return", payload, headers
        )

    def install_parts_line(
        self,
        parts_line_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/parts-lines/{parts_line_id}/install", payload, headers
        )

    def run_parts_delay_sweep(
        self, order_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/parts-delay-sweep", payload, headers
        )

    def list_order_parts_delay_events(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/repair-orders/{order_id}/parts-delay-events", params, headers
        )

    def list_parts_line_delay_events(
        self,
        parts_line_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/parts-lines/{parts_line_id}/parts-delay-events", params, headers
        )

    # -- Procedure research and calibration ---------------------------------
    def create_procedure_record(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/procedure-records", payload, headers
        )

    def get_procedure_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/procedure-records/{record_id}", None, headers)

    def list_procedure_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/procedure-records", params, headers)

    def document_adherence(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/procedure-records/{record_id}", payload, headers
        )

    def schedule_calibration(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/procedure-records/{record_id}/calibration-schedule",
            payload,
            headers,
        )

    def record_calibration_result(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/procedure-records/{record_id}/calibration-result",
            payload,
            headers,
        )

    # -- Bookings and stage advancement -------------------------------------
    def create_stage_assignment(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/stage-assignments", payload, headers
        )

    def get_stage_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stage-assignments/{assignment_id}", None, headers)

    def list_stage_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/stage-assignments", params, headers)

    def cancel_stage_assignment(
        self,
        assignment_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/stage-assignments/{assignment_id}/cancel", payload, headers
        )

    def advance_stage(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/stage-advance", payload, headers
        )

    # -- Quality control, delivery, cycle time ------------------------------
    def create_qc_inspection(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/qc-inspections", payload, headers
        )

    def list_qc_inspections(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/repair-orders/{order_id}/qc-inspections", params, headers
        )

    def get_cycle_time(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/repair-orders/{order_id}/cycle-time", params, headers
        )

    def deliver_repair_order(
        self, order_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/repair-orders/{order_id}/deliver", payload, headers
        )

    # -- Raw escape hatch ----------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)
