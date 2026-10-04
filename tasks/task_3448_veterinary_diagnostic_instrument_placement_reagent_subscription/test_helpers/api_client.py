"""API client: one method per endpoint defined in the PRD (PRD §4, 32 endpoints).

All endpoints — including the logical-clock endpoint — are mounted under the
``/api`` prefix (PRD §4: "All endpoints are mounted under the /api prefix").

The base URL is injected by the test harness via the ``API_BASE_URL``
environment variable (handled by the framework's GenericApiClient); no port
is hardcoded here.

IMPORT IDIOM (mandatory for test files): use
    ``from test_helpers import api_client``
to obtain the shared ``ApiClient`` instance. Do NOT write
``import test_helpers.api_client as ac`` expecting a module — the package
``__init__`` re-exports the ``api_client`` instance under the same name as
this submodule, so attribute access on the package resolves to the instance.
"""
from prd_bench_local_runner.testing import GenericApiClient

__all__ = ["ApiClient", "api_client"]


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods; ``_request`` is inherited."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4) — PlatformAdmin only
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        """POST /api/_clock/set_current_utc — advance the logical clock."""
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Group pricing agreements (PRD §3.2)
    # ------------------------------------------------------------------
    def create_group_pricing_agreement(self, payload, headers):
        """POST /api/group-pricing-agreements — returns 201."""
        return self._request("POST", "/api/group-pricing-agreements", payload, headers)

    def list_group_pricing_agreements(self, headers, params=None):
        """GET /api/group-pricing-agreements — filters: group_code, status."""
        return self._request("GET", "/api/group-pricing-agreements", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Clinics (PRD §3.1)
    # ------------------------------------------------------------------
    def create_clinic(self, payload, headers):
        """POST /api/clinics — returns 201."""
        return self._request("POST", "/api/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        """GET /api/clinics/{id}."""
        return self._request("GET", f"/api/clinics/{clinic_id}", headers=headers)

    def update_clinic(self, clinic_id, payload, headers):
        """PATCH /api/clinics/{id} — caseload_current_tests and/or status."""
        return self._request("PATCH", f"/api/clinics/{clinic_id}", payload, headers)

    # ------------------------------------------------------------------
    # Placement agreements (PRD §3.3, §3.5, §3.6)
    # ------------------------------------------------------------------
    def create_placement_agreement(self, payload, headers):
        """POST /api/placement-agreements — returns 201."""
        return self._request("POST", "/api/placement-agreements", payload, headers)

    def get_placement_agreement(self, agreement_id, headers):
        """GET /api/placement-agreements/{id}."""
        return self._request("GET", f"/api/placement-agreements/{agreement_id}", headers=headers)

    def list_placement_agreements(self, headers, params=None):
        """GET /api/placement-agreements — filters: clinic_id, status."""
        return self._request("GET", "/api/placement-agreements", headers=headers, params=params)

    def approve_placement_agreement(self, agreement_id, headers):
        """POST /api/placement-agreements/{id}/approve — FinanceReviewer."""
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/approve", {}, headers)

    def activate_placement_agreement(self, agreement_id, headers):
        """POST /api/placement-agreements/{id}/activate — PlatformAdmin."""
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/activate", {}, headers)

    def request_renegotiation(self, agreement_id, headers):
        """POST /api/placement-agreements/{id}/request-renegotiation."""
        return self._request(
            "POST", f"/api/placement-agreements/{agreement_id}/request-renegotiation", {}, headers,
        )

    def resolve_renegotiation(self, agreement_id, payload, headers):
        """POST /api/placement-agreements/{id}/resolve-renegotiation (OCC).

        Payload carries ``accept`` and ``expected_agreement_version``
        (required), plus optional ``new_minimum_cents`` / ``waive_period_ids``.
        """
        return self._request(
            "POST", f"/api/placement-agreements/{agreement_id}/resolve-renegotiation", payload, headers,
        )

    def close_commitment_period(self, agreement_id, payload, headers):
        """POST /api/placement-agreements/{id}/close-commitment-period (OCC).

        Payload carries ``period_month`` and ``expected_agreement_version``.
        """
        return self._request(
            "POST", f"/api/placement-agreements/{agreement_id}/close-commitment-period", payload, headers,
        )

    def list_commitment_periods(self, agreement_id, headers, params=None):
        """GET /api/placement-agreements/{id}/commitment-periods.

        Ordered by period_month ASC; filter: period_status.
        """
        return self._request(
            "GET", f"/api/placement-agreements/{agreement_id}/commitment-periods",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Commitment periods (PRD §3.5)
    # ------------------------------------------------------------------
    def record_payment(self, period_id, payload, headers):
        """POST /api/commitment-periods/{id}/record-payment — FinanceReviewer.

        Payload carries ``amount_cents`` (must equal billed_cents exactly).
        """
        return self._request(
            "POST", f"/api/commitment-periods/{period_id}/record-payment", payload, headers,
        )

    # ------------------------------------------------------------------
    # Analyzers (PRD §3.7)
    # ------------------------------------------------------------------
    def create_analyzer(self, payload, headers):
        """POST /api/analyzers — returns 201. FieldServiceEngineer."""
        return self._request("POST", "/api/analyzers", payload, headers)

    def get_analyzer(self, analyzer_id, headers):
        """GET /api/analyzers/{id}."""
        return self._request("GET", f"/api/analyzers/{analyzer_id}", headers=headers)

    def list_analyzers(self, headers, params=None):
        """GET /api/analyzers — filters: clinic_id, agreement_id, operational_status."""
        return self._request("GET", "/api/analyzers", headers=headers, params=params)

    def update_analyzer(self, analyzer_id, payload, headers):
        """PATCH /api/analyzers/{id} — operational_status and/or connectivity_status."""
        return self._request("PATCH", f"/api/analyzers/{analyzer_id}", payload, headers)

    # ------------------------------------------------------------------
    # Service cases (PRD §3.7)
    # ------------------------------------------------------------------
    def create_service_case(self, payload, headers):
        """POST /api/service-cases — returns 201. FieldServiceEngineer."""
        return self._request("POST", "/api/service-cases", payload, headers)

    def list_service_cases(self, analyzer_id, headers, params=None):
        """GET /api/analyzers/{id}/service-cases — serviced unit OR loaner."""
        return self._request(
            "GET", f"/api/analyzers/{analyzer_id}/service-cases", headers=headers, params=params,
        )

    def update_service_case(self, case_id, payload, headers):
        """PATCH /api/service-cases/{id} — action DISPATCH | RESOLVE | CANCEL."""
        return self._request("PATCH", f"/api/service-cases/{case_id}", payload, headers)

    # ------------------------------------------------------------------
    # Reagent orders (PRD §3.4)
    # ------------------------------------------------------------------
    def create_reagent_order(self, payload, headers):
        """POST /api/reagent-orders — returns 201 with locked pricing."""
        return self._request("POST", "/api/reagent-orders", payload, headers)

    def get_reagent_order(self, order_id, headers):
        """GET /api/reagent-orders/{id}."""
        return self._request("GET", f"/api/reagent-orders/{order_id}", headers=headers)

    def list_reagent_orders(self, headers, params=None):
        """GET /api/reagent-orders — filters: clinic_id, agreement_id, status."""
        return self._request("GET", "/api/reagent-orders", headers=headers, params=params)

    def update_reagent_order(self, order_id, payload, headers):
        """PATCH /api/reagent-orders/{id} — status FULFILLED | CANCELLED."""
        return self._request("PATCH", f"/api/reagent-orders/{order_id}", payload, headers)

    # ------------------------------------------------------------------
    # Lab test orders + unified results (PRD §3.8, §3.9)
    # ------------------------------------------------------------------
    def create_lab_test_order(self, payload, headers):
        """POST /api/lab-test-orders — returns 201. ClinicManager (own clinic)."""
        return self._request("POST", "/api/lab-test-orders", payload, headers)

    def get_lab_test_order(self, order_id, headers):
        """GET /api/lab-test-orders/{id}."""
        return self._request("GET", f"/api/lab-test-orders/{order_id}", headers=headers)

    def list_lab_test_orders(self, headers, params=None):
        """GET /api/lab-test-orders — filters: clinic_id, analyzer_id, status."""
        return self._request("GET", "/api/lab-test-orders", headers=headers, params=params)

    def update_lab_test_order(self, order_id, payload, headers):
        """PATCH /api/lab-test-orders/{id} — action RECEIVE | RECORD_RESULT | DELIVER | CANCEL."""
        return self._request("PATCH", f"/api/lab-test-orders/{order_id}", payload, headers)

    def list_lab_test_results(self, order_id, headers, params=None):
        """GET /api/lab-test-orders/{id}/results — array of length 0 or 1."""
        return self._request(
            "GET", f"/api/lab-test-orders/{order_id}/results", headers=headers, params=params,
        )


# Shared singleton. Test files import it via ``from test_helpers import api_client``
# (see module docstring for the import-idiom rule).
api_client = ApiClient()
