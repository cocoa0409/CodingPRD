"""HTTP client with one method per endpoint of the contract (PRD 4).

Every method returns the raw ``requests.Response`` so tests can assert the
status code themselves. The response envelope is unwrapped in exactly one
place — the shared ``validate_success`` / ``get_success_data`` validators —
and never a second time by callers of this client.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Payload = Optional[Dict[str, Any]]
Headers = Optional[Dict[str, str]]


class ApiClient(GenericApiClient):
    """One method per path in the endpoint table."""

    # ── Logical clock ─────────────────────────────────────────────────────────

    def set_clock(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Regulatory standards ──────────────────────────────────────────────────

    def create_regulatory_standard(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/regulatory-standards", payload, headers)

    def get_regulatory_standard(self, standard_id: str, headers: Headers = None):
        return self._request(
            "GET", "/regulatory-standards/%s" % standard_id, None, headers
        )

    def list_regulatory_standards(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/regulatory-standards", params, headers)

    # ── Distributors ──────────────────────────────────────────────────────────

    def create_distributor(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id: str, headers: Headers = None):
        return self._request("GET", "/distributors/%s" % distributor_id, None, headers)

    def list_distributors(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/distributors", params, headers)

    # ── Curing ovens ──────────────────────────────────────────────────────────

    def create_curing_oven(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/curing-ovens", payload, headers)

    def get_curing_oven(self, oven_id: str, headers: Headers = None):
        return self._request("GET", "/curing-ovens/%s" % oven_id, None, headers)

    def list_curing_ovens(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/curing-ovens", params, headers)

    # ── Test cells ────────────────────────────────────────────────────────────

    def create_test_cell(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/test-cells", payload, headers)

    def get_test_cell(self, cell_id: str, headers: Headers = None):
        return self._request("GET", "/test-cells/%s" % cell_id, None, headers)

    def list_test_cells(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/test-cells", params, headers)

    # ── Motor designs ─────────────────────────────────────────────────────────

    def create_motor_design(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/motor-designs", payload, headers)

    def get_motor_design(self, design_id: str, headers: Headers = None):
        return self._request("GET", "/motor-designs/%s" % design_id, None, headers)

    def list_motor_designs(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/motor-designs", params, headers)

    def submit_design_review(
        self, design_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", "/motor-designs/%s/submit-review" % design_id, payload, headers
        )

    def record_review_decision(
        self, design_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/motor-designs/%s/review-decision" % design_id, payload, headers
        )

    def open_design_revision(
        self, design_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/motor-designs/%s/open-revision" % design_id, payload, headers
        )

    # ── Customer orders ───────────────────────────────────────────────────────

    def create_customer_order(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/customer-orders", payload, headers)

    def get_customer_order(self, order_id: str, headers: Headers = None):
        return self._request("GET", "/customer-orders/%s" % order_id, None, headers)

    def list_customer_orders(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/customer-orders", params, headers)

    def confirm_customer_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", "/customer-orders/%s/confirm" % order_id, payload, headers
        )

    def cancel_customer_order(
        self, order_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/customer-orders/%s/cancel" % order_id, payload, headers
        )

    # ── Work orders ───────────────────────────────────────────────────────────

    def create_work_order(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id: str, headers: Headers = None):
        return self._request("GET", "/work-orders/%s" % work_order_id, None, headers)

    def list_work_orders(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/work-orders", params, headers)

    def get_work_order_cost_summary(self, work_order_id: str, headers: Headers = None):
        return self._request(
            "GET", "/work-orders/%s/cost-summary" % work_order_id, None, headers
        )

    def ship_work_order(
        self, work_order_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", "/work-orders/%s/ship" % work_order_id, payload, headers
        )

    # ── Stator builds ─────────────────────────────────────────────────────────

    def create_stator_build(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/stator-builds", payload, headers)

    def get_stator_build(self, stator_build_id: str, headers: Headers = None):
        return self._request(
            "GET", "/stator-builds/%s" % stator_build_id, None, headers
        )

    def list_stator_builds(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/stator-builds", params, headers)

    def impregnate_stator_build(
        self, stator_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/stator-builds/%s/impregnate" % stator_build_id, payload, headers
        )

    def surge_test_stator_build(
        self, stator_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/stator-builds/%s/surge-test" % stator_build_id, payload, headers
        )

    def disposition_stator_build(
        self, stator_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/stator-builds/%s/disposition" % stator_build_id, payload, headers
        )

    # ── Rotor builds ──────────────────────────────────────────────────────────

    def create_rotor_build(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/rotor-builds", payload, headers)

    def get_rotor_build(self, rotor_build_id: str, headers: Headers = None):
        return self._request("GET", "/rotor-builds/%s" % rotor_build_id, None, headers)

    def list_rotor_builds(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/rotor-builds", params, headers)

    def form_rotor_cage(
        self, rotor_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/rotor-builds/%s/form-cage" % rotor_build_id, payload, headers
        )

    def machine_rotor_build(
        self, rotor_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/rotor-builds/%s/machine" % rotor_build_id, payload, headers
        )

    def balance_disposition_rotor_build(
        self, rotor_build_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            "/rotor-builds/%s/balance-disposition" % rotor_build_id,
            payload,
            headers,
        )

    # ── Assembly records ──────────────────────────────────────────────────────

    def create_assembly_record(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/assembly-records", payload, headers)

    def get_assembly_record(self, assembly_record_id: str, headers: Headers = None):
        return self._request(
            "GET", "/assembly-records/%s" % assembly_record_id, None, headers
        )

    def list_assembly_records(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/assembly-records", params, headers)

    # ── Performance tests ─────────────────────────────────────────────────────

    def create_performance_test(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/performance-tests", payload, headers)

    def get_performance_test(self, performance_test_id: str, headers: Headers = None):
        return self._request(
            "GET", "/performance-tests/%s" % performance_test_id, None, headers
        )

    def list_performance_tests(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/performance-tests", params, headers)

    def record_performance_test(
        self, performance_test_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            "/performance-tests/%s/record" % performance_test_id,
            payload,
            headers,
        )

    # ── Nameplates ────────────────────────────────────────────────────────────

    def create_nameplate(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/nameplates", payload, headers)

    def get_nameplate(self, nameplate_id: str, headers: Headers = None):
        return self._request("GET", "/nameplates/%s" % nameplate_id, None, headers)

    def list_nameplates(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/nameplates", params, headers)

    def revoke_nameplate(
        self, nameplate_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/nameplates/%s/revoke" % nameplate_id, payload, headers
        )

    # ── Warranty claims ───────────────────────────────────────────────────────

    def create_warranty_claim(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id: str, headers: Headers = None):
        return self._request("GET", "/warranty-claims/%s" % claim_id, None, headers)

    def list_warranty_claims(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/warranty-claims", params, headers)

    def analyze_warranty_claim(
        self, claim_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/warranty-claims/%s/analyze" % claim_id, payload, headers
        )

    def dispute_warranty_claim(
        self, claim_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", "/warranty-claims/%s/dispute" % claim_id, payload, headers
        )

    def close_warranty_claim(
        self, claim_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", "/warranty-claims/%s/close" % claim_id, payload, headers
        )

    # ── Generic path access, for collection-agnostic checks ───────────────────

    def get_by_path(self, collection: str, row_id: str, headers: Headers = None):
        return self._request("GET", "/%s/%s" % (collection, row_id), None, headers)

    def list_by_path(
        self, collection: str, headers: Headers = None, params: Payload = None
    ):
        return self._request("GET", "/%s" % collection, params, headers)
