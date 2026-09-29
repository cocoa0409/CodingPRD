"""One method per endpoint declared by the PRD.

Every path is mounted under ``/mfg``. Creation endpoints answer 201 and every
other successful outcome answers 200, including the clock setter, so tests pass
the expected status to the validators rather than inferring it here.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import JsonDict


class MfgApiClient(GenericApiClient):
    """Typed wrapper over the manufacturing compliance API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/mfg/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Optional[JsonDict], headers: Dict[str, str]):
        return self._request("POST", "/mfg/_clock/set_current_utc", payload, headers)

    def read_clock(self, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", "/mfg/_clock", None, headers)

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/suppliers/{supplier_id}", None, headers)

    def list_suppliers(self, headers: Dict[str, str], params: Optional[JsonDict] = None):
        return self._request("GET", "/mfg/suppliers", params, headers)

    def qualify_supplier(
        self, supplier_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/suppliers/{supplier_id}/qualify", payload, headers
        )

    def disqualify_supplier(
        self, supplier_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/suppliers/{supplier_id}/disqualify", payload, headers
        )

    def requalify_supplier(
        self, supplier_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/suppliers/{supplier_id}/requalify", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Component lots
    # ------------------------------------------------------------------
    def create_component_lot(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/component-lots", payload, headers)

    def get_component_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/component-lots/{lot_id}", None, headers)

    def list_component_lots(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/component-lots", params, headers)

    def release_component_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/component-lots/{lot_id}/release", payload or {}, headers
        )

    def reject_component_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/component-lots/{lot_id}/reject", payload or {}, headers
        )

    def unblock_component_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/component-lots/{lot_id}/unblock", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Furnaces and glass-lining batches
    # ------------------------------------------------------------------
    def create_furnace(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/furnaces", payload, headers)

    def get_furnace(self, furnace_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/furnaces/{furnace_id}", None, headers)

    def list_furnaces(self, headers: Dict[str, str], params: Optional[JsonDict] = None):
        return self._request("GET", "/mfg/furnaces", params, headers)

    def create_lining_batch(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/glass-lining-batches", payload, headers)

    def get_lining_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/glass-lining-batches/{batch_id}", None, headers)

    def list_lining_batches(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/glass-lining-batches", params, headers)

    def fire_lining_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/glass-lining-batches/{batch_id}/fire", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Product models
    # ------------------------------------------------------------------
    def create_product_model(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/product-models", payload, headers)

    def get_product_model(self, model_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/product-models/{model_id}", None, headers)

    def list_product_models(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/product-models", params, headers)

    def release_model_to_channel(
        self, model_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST",
            f"/mfg/product-models/{model_id}/release-to-channel",
            payload or {},
            headers,
        )

    def lift_model_restriction(
        self, model_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST",
            f"/mfg/product-models/{model_id}/lift-restriction",
            payload or {},
            headers,
        )

    def withdraw_model(
        self, model_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/product-models/{model_id}/withdraw", payload or {}, headers
        )

    def suspend_model_certification(
        self, model_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mfg/product-models/{model_id}/suspend-certification",
            payload,
            headers,
        )

    def get_warranty_analysis(
        self, model_id: str, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"/mfg/product-models/{model_id}/warranty-analysis", params, headers
        )

    # ------------------------------------------------------------------
    # Test cells and efficiency tests
    # ------------------------------------------------------------------
    def create_test_cell(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/test-cells", payload, headers)

    def get_test_cell(self, cell_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/test-cells/{cell_id}", None, headers)

    def list_test_cells(self, headers: Dict[str, str], params: Optional[JsonDict] = None):
        return self._request("GET", "/mfg/test-cells", params, headers)

    def create_efficiency_test(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/efficiency-tests", payload, headers)

    def get_efficiency_test(self, test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/efficiency-tests/{test_id}", None, headers)

    def list_efficiency_tests(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/efficiency-tests", params, headers)

    def record_test_result(self, test_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/efficiency-tests/{test_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Rating certifications
    # ------------------------------------------------------------------
    def create_certification(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/rating-certifications", payload, headers)

    def get_certification(self, cert_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/rating-certifications/{cert_id}", None, headers)

    def list_certifications(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/rating-certifications", params, headers)

    def submit_certification(
        self, cert_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/rating-certifications/{cert_id}/submit", payload or {}, headers
        )

    def approve_certification(
        self, cert_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/rating-certifications/{cert_id}/approve", payload, headers
        )

    def reject_certification(
        self, cert_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/rating-certifications/{cert_id}/reject", payload, headers
        )

    def revoke_certification(
        self, cert_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/rating-certifications/{cert_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Tank lots
    # ------------------------------------------------------------------
    def create_tank_lot(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/tank-lots", payload, headers)

    def get_tank_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/tank-lots/{lot_id}", None, headers)

    def list_tank_lots(self, headers: Dict[str, str], params: Optional[JsonDict] = None):
        return self._request("GET", "/mfg/tank-lots", params, headers)

    def weld_tank_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/weld", payload or {}, headers
        )

    def apply_lining(self, lot_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/apply-lining", payload, headers
        )

    def authorize_reline(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/authorize-reline", payload or {}, headers
        )

    def rework_reversal(self, lot_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/rework-reversal", payload, headers
        )

    def scrap_tank_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/scrap", payload or {}, headers
        )

    def foam_tank_lot(self, lot_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", f"/mfg/tank-lots/{lot_id}/foam", payload, headers)

    def jacket_tank_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/jacket", payload or {}, headers
        )

    def release_tank_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/tank-lots/{lot_id}/release", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Lining inspections
    # ------------------------------------------------------------------
    def create_lining_inspection(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/lining-inspections", payload, headers)

    def get_lining_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mfg/lining-inspections/{inspection_id}", None, headers
        )

    def list_lot_lining_inspections(
        self, lot_id: str, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"/mfg/tank-lots/{lot_id}/lining-inspections", params, headers
        )

    # ------------------------------------------------------------------
    # Heater units
    # ------------------------------------------------------------------
    def create_heater_unit(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/heater-units", payload, headers)

    def get_heater_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/heater-units/{unit_id}", None, headers)

    def list_heater_units(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/heater-units", params, headers)

    def assemble_unit(
        self, unit_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/heater-units/{unit_id}/assemble", payload or {}, headers
        )

    def label_unit(
        self, unit_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/heater-units/{unit_id}/label", payload or {}, headers
        )

    def ship_unit(self, unit_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/heater-units/{unit_id}/ship", payload, headers
        )

    def release_unit_hold(
        self, unit_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/heater-units/{unit_id}/release-hold", payload or {}, headers
        )

    def disassemble_unit(self, unit_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/heater-units/{unit_id}/disassemble", payload, headers
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/warranty-claims/{claim_id}", None, headers)

    def list_warranty_claims(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/warranty-claims", params, headers)

    def validate_claim(
        self, claim_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/warranty-claims/{claim_id}/validate", payload or {}, headers
        )

    def deny_claim(self, claim_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/warranty-claims/{claim_id}/deny", payload, headers
        )

    def pay_claim(
        self, claim_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/warranty-claims/{claim_id}/pay", payload or {}, headers
        )

    def reverse_claim_payment(
        self, claim_id: str, payload: JsonDict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mfg/warranty-claims/{claim_id}/reverse-payment", payload, headers
        )

    # ------------------------------------------------------------------
    # Recall campaigns and notices
    # ------------------------------------------------------------------
    def create_recall_campaign(self, payload: JsonDict, headers: Dict[str, str]):
        return self._request("POST", "/mfg/recall-campaigns", payload, headers)

    def get_recall_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/recall-campaigns/{campaign_id}", None, headers)

    def list_recall_campaigns(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/recall-campaigns", params, headers)

    def scope_campaign(self, campaign_id: str, payload: JsonDict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mfg/recall-campaigns/{campaign_id}/scope", payload, headers
        )

    def announce_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST",
            f"/mfg/recall-campaigns/{campaign_id}/announce",
            payload or {},
            headers,
        )

    def close_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/recall-campaigns/{campaign_id}/close", payload or {}, headers
        )

    def cancel_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/recall-campaigns/{campaign_id}/cancel", payload or {}, headers
        )

    def get_campaign_completion(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mfg/recall-campaigns/{campaign_id}/completion", None, headers
        )

    def get_recall_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mfg/recall-notices/{notice_id}", None, headers)

    def list_recall_notices(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ):
        return self._request("GET", "/mfg/recall-notices", params, headers)

    def notify_notice(
        self, notice_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/recall-notices/{notice_id}/notify", payload or {}, headers
        )

    def remedy_notice(
        self, notice_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"/mfg/recall-notices/{notice_id}/remedy", payload or {}, headers
        )

    def mark_notice_unreachable(
        self, notice_id: str, headers: Dict[str, str], payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST",
            f"/mfg/recall-notices/{notice_id}/mark-unreachable",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Generic escape hatch for ladder tests that need a raw path/method
    # ------------------------------------------------------------------
    def call(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Any = None,
    ):
        return self._request(method, path, payload, headers)
