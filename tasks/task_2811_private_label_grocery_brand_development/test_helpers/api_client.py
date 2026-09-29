"""Endpoint-per-method client for the Private-Label Brand Development API.

Also hosts the value-canonicalisation helpers.  Timestamps are compared after
normalising the fractional-second width, so a body that renders an instant as
``2026-08-01T00:00:00.000Z`` and one that renders it as ``2026-08-01T00:00:00Z``
are treated as the same instant.  Money is always sent and read as an integer
number of cents, never as a string.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/private-label"


def canonicalize_iso(value):
    """Normalise an ISO 8601 UTC instant so string equality is precision-safe.

    Returns ``YYYY-MM-DDTHH:MM:SS.mmmZ`` for any recognised UTC spelling:
    a trailing ``Z`` or ``+00:00`` offset, and zero to nine fractional digits.
    Non-string input is returned unchanged so ``None`` flows through.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    if not text.endswith("Z"):
        return value
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def canonicalize_money(value):
    """Coerce a money reading to ``int`` cents, rejecting fractional cents."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        assert value == int(value), f"money must be whole cents, got {value!r}"
        return int(value)
    raise AssertionError(f"money must be a JSON number of cents, got {value!r}")


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the API contract."""

    # --- Logical clock -------------------------------------------------------
    def set_clock(self, current_utc: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Brand programs -----------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{BASE}/programs/{program_id}", None, headers)

    def list_programs(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/programs", params, headers)

    def program_lifecycle(self, program_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/lifecycle", payload, headers
        )

    def get_budget_ledger(self, program_id, headers):
        return self._request(
            "GET", f"{BASE}/programs/{program_id}/budget-ledger", None, headers
        )

    # --- Category gaps ------------------------------------------------------
    def create_gap(self, payload, headers):
        return self._request("POST", f"{BASE}/category-gaps", payload, headers)

    def get_gap(self, gap_id, headers):
        return self._request("GET", f"{BASE}/category-gaps/{gap_id}", None, headers)

    def list_gaps(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/category-gaps", params, headers)

    def analyze_gap(self, gap_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/category-gaps/{gap_id}/analyze", payload, headers
        )

    def decide_gap_tier(self, gap_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/category-gaps/{gap_id}/tier-decision", payload, headers
        )

    # --- Suppliers ----------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{BASE}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{BASE}/suppliers/{supplier_id}", None, headers)

    def list_suppliers(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/suppliers", params, headers)

    def decide_qualification(self, supplier_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/suppliers/{supplier_id}/qualification-decision",
            payload,
            headers,
        )

    def get_scorecard(self, supplier_id, headers):
        return self._request(
            "GET", f"{BASE}/suppliers/{supplier_id}/scorecard", None, headers
        )

    # --- Plant lines --------------------------------------------------------
    def create_plant_line(self, payload, headers):
        return self._request("POST", f"{BASE}/plant-lines", payload, headers)

    def get_plant_line(self, plant_line_id, headers):
        return self._request(
            "GET", f"{BASE}/plant-lines/{plant_line_id}", None, headers
        )

    def list_plant_lines(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/plant-lines", params, headers)

    # --- Plant audits -------------------------------------------------------
    def create_plant_audit(self, payload, headers):
        return self._request("POST", f"{BASE}/plant-audits", payload, headers)

    def get_plant_audit(self, plant_audit_id, headers):
        return self._request(
            "GET", f"{BASE}/plant-audits/{plant_audit_id}", None, headers
        )

    def list_plant_audits(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/plant-audits", params, headers)

    def finalize_plant_audit(self, plant_audit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/plant-audits/{plant_audit_id}/finalize", payload, headers
        )

    # --- Product items ------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", f"{BASE}/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"{BASE}/items/{item_id}", None, headers)

    def list_items(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/items", params, headers)

    def post_shipment_feed(self, item_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/items/{item_id}/shipment-feed", payload, headers
        )

    def launch_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/items/{item_id}/launch", payload or {}, headers
        )

    def rationalize_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/items/{item_id}/rationalize", payload, headers
        )

    # --- Cost models --------------------------------------------------------
    def create_cost_model(self, payload, headers):
        return self._request("POST", f"{BASE}/cost-models", payload, headers)

    def get_cost_model(self, cost_model_id, headers):
        return self._request(
            "GET", f"{BASE}/cost-models/{cost_model_id}", None, headers
        )

    def list_cost_models(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/cost-models", params, headers)

    def decide_cost_model(self, cost_model_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/cost-models/{cost_model_id}/decision", payload, headers
        )

    # --- Comparison studies -------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", f"{BASE}/comparison-studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request(
            "GET", f"{BASE}/comparison-studies/{study_id}", None, headers
        )

    def list_studies(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/comparison-studies", params, headers)

    def finalize_study(self, study_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/comparison-studies/{study_id}/finalize",
            payload or {},
            headers,
        )

    # --- Artwork rounds -----------------------------------------------------
    def create_artwork_round(self, payload, headers):
        return self._request("POST", f"{BASE}/artwork-rounds", payload, headers)

    def get_artwork_round(self, artwork_round_id, headers):
        return self._request(
            "GET", f"{BASE}/artwork-rounds/{artwork_round_id}", None, headers
        )

    def list_artwork_rounds(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/artwork-rounds", params, headers)

    def generate_nutrition_panel(self, artwork_round_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/artwork-rounds/{artwork_round_id}/nutrition-panel",
            payload or {},
            headers,
        )

    def submit_artwork_round(self, artwork_round_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/artwork-rounds/{artwork_round_id}/submit",
            payload or {},
            headers,
        )

    def review_artwork_round(self, artwork_round_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/artwork-rounds/{artwork_round_id}/review", payload, headers
        )

    # --- Label claims -------------------------------------------------------
    def create_label_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/label-claims", payload, headers)

    def get_label_claim(self, label_claim_id, headers):
        return self._request(
            "GET", f"{BASE}/label-claims/{label_claim_id}", None, headers
        )

    def list_label_claims(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/label-claims", params, headers)

    def review_label_claim(self, label_claim_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/label-claims/{label_claim_id}/review", payload, headers
        )

    # --- Specifications -----------------------------------------------------
    def create_specification(self, payload, headers):
        return self._request("POST", f"{BASE}/specifications", payload, headers)

    def get_specification(self, specification_id, headers):
        return self._request(
            "GET", f"{BASE}/specifications/{specification_id}", None, headers
        )

    def list_specifications(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/specifications", params, headers)

    def lock_specification(self, specification_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/specifications/{specification_id}/lock",
            payload or {},
            headers,
        )

    # --- Production runs ----------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", f"{BASE}/production-runs", payload, headers)

    def get_production_run(self, production_run_id, headers):
        return self._request(
            "GET", f"{BASE}/production-runs/{production_run_id}", None, headers
        )

    def list_production_runs(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/production-runs", params, headers)

    def approve_production_run(self, production_run_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/approve",
            payload or {},
            headers,
        )

    def complete_production_run(self, production_run_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/complete",
            payload,
            headers,
        )

    def release_hold_production_run(self, production_run_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/release-hold",
            payload or {},
            headers,
        )

    def cancel_production_run(self, production_run_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/cancel",
            payload or {},
            headers,
        )

    # --- Complaints ---------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{BASE}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{BASE}/complaints/{complaint_id}", None, headers)

    def list_complaints(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/complaints", params, headers)

    # --- Cost change requests -----------------------------------------------
    def create_change_request(self, payload, headers):
        return self._request("POST", f"{BASE}/cost-change-requests", payload, headers)

    def get_change_request(self, cost_change_request_id, headers):
        return self._request(
            "GET", f"{BASE}/cost-change-requests/{cost_change_request_id}", None, headers
        )

    def list_change_requests(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/cost-change-requests", params, headers)

    def counter_change_request(self, cost_change_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/cost-change-requests/{cost_change_request_id}/counter",
            payload,
            headers,
        )

    def revise_change_request(self, cost_change_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/cost-change-requests/{cost_change_request_id}/revise",
            payload,
            headers,
        )

    def decide_change_request(self, cost_change_request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/cost-change-requests/{cost_change_request_id}/decision",
            payload,
            headers,
        )

    def withdraw_change_request(self, cost_change_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/cost-change-requests/{cost_change_request_id}/withdraw",
            payload or {},
            headers,
        )


api_client = ApiClient()
