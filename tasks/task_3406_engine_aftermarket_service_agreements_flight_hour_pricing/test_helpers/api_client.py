"""API client: one method per endpoint defined in PRD §4.

The base URL is read from the API_BASE_URL environment variable by the
framework's GenericApiClient; the server lifecycle is owned by the runner.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Operators / Engines / master data
    # ------------------------------------------------------------------
    def create_operator(self, payload, headers):
        return self._request("POST", "/api/operators", payload, headers)

    def create_engine(self, payload, headers):
        return self._request("POST", "/api/engines", payload, headers)

    def create_spare_engine(self, payload, headers):
        return self._request("POST", "/api/spare-engines", payload, headers)

    def create_directive(self, payload, headers):
        return self._request("POST", "/api/directives", payload, headers)

    # ------------------------------------------------------------------
    # Flight-hour reports
    # ------------------------------------------------------------------
    def submit_flight_hour_report(self, engine_id, payload, headers):
        return self._request(
            "POST", f"/api/engines/{engine_id}/flight-hour-reports", payload, headers
        )

    def verify_flight_hour_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/flight-hour-reports/{report_id}/verify", headers=headers
        )

    # ------------------------------------------------------------------
    # Shop visits
    # ------------------------------------------------------------------
    def create_shop_visit(self, engine_id, payload, headers):
        return self._request(
            "POST", f"/api/engines/{engine_id}/shop-visits", payload, headers
        )

    def induct_shop_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/api/shop-visits/{visit_id}/induct", headers=headers
        )

    def complete_shop_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/api/shop-visits/{visit_id}/complete", headers=headers
        )

    # ------------------------------------------------------------------
    # Service agreements
    # ------------------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/agreements", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/activate", headers=headers
        )

    def open_renegotiation(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/open-renegotiation", headers=headers
        )

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/amend", payload, headers
        )

    def enroll_engine(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/enroll", payload, headers
        )

    # ------------------------------------------------------------------
    # Billing statements
    # ------------------------------------------------------------------
    def issue_billing_statement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/billing-statements", payload, headers
        )

    def settle_billing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/settle", headers=headers
        )

    # ------------------------------------------------------------------
    # Recognition snapshots
    # ------------------------------------------------------------------
    def create_recognition_snapshot(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/recognition-snapshots", headers=headers
        )

    # ------------------------------------------------------------------
    # Workscopes
    # ------------------------------------------------------------------
    def create_workscope(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/shop-visits/{visit_id}/workscopes", payload, headers
        )

    def approve_workscope(self, workscope_id, headers):
        return self._request(
            "POST", f"/api/workscopes/{workscope_id}/approve", headers=headers
        )

    def reject_workscope(self, workscope_id, headers):
        return self._request(
            "POST", f"/api/workscopes/{workscope_id}/reject", headers=headers
        )

    # ------------------------------------------------------------------
    # Part requisitions
    # ------------------------------------------------------------------
    def create_part_requisition(self, workscope_id, payload, headers):
        return self._request(
            "POST", f"/api/workscopes/{workscope_id}/part-requisitions", payload, headers
        )

    def source_part_requisition(self, requisition_id, headers, payload=None):
        return self._request(
            "POST", f"/api/part-requisitions/{requisition_id}/source", payload, headers
        )

    # ------------------------------------------------------------------
    # Spare engine leases
    # ------------------------------------------------------------------
    def create_spare_engine_lease(self, payload, headers):
        return self._request("POST", "/api/spare-engine-leases", payload, headers)

    def activate_spare_engine_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/api/spare-engine-leases/{lease_id}/activate", headers=headers
        )

    def return_spare_engine_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/api/spare-engine-leases/{lease_id}/return", headers=headers
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_engine(self, engine_id, headers):
        return self._request("GET", f"/api/engines/{engine_id}", headers=headers)

    def list_engines(self, headers, params=None):
        return self._request("GET", "/api/engines", headers=headers, params=params)

    def list_engine_shop_visits(self, engine_id, headers, params=None):
        return self._request(
            "GET", f"/api/engines/{engine_id}/shop-visits", headers=headers, params=params
        )

    def list_engine_flight_hour_reports(self, engine_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/engines/{engine_id}/flight-hour-reports",
            headers=headers,
            params=params,
        )

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/agreements/{agreement_id}", headers=headers)

    def list_agreement_billing_statements(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/agreements/{agreement_id}/billing-statements",
            headers=headers,
            params=params,
        )

    def list_agreement_recognition_snapshots(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/agreements/{agreement_id}/recognition-snapshots",
            headers=headers,
            params=params,
        )

    def get_shop_visit(self, visit_id, headers):
        return self._request("GET", f"/api/shop-visits/{visit_id}", headers=headers)

    def list_shop_visit_workscopes(self, visit_id, headers, params=None):
        return self._request(
            "GET", f"/api/shop-visits/{visit_id}/workscopes", headers=headers, params=params
        )

    def list_shop_visit_leases(self, visit_id, headers, params=None):
        return self._request(
            "GET", f"/api/shop-visits/{visit_id}/leases", headers=headers, params=params
        )

    def get_workscope(self, workscope_id, headers):
        return self._request("GET", f"/api/workscopes/{workscope_id}", headers=headers)

    def list_workscope_part_requisitions(self, workscope_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/workscopes/{workscope_id}/part-requisitions",
            headers=headers,
            params=params,
        )

    def get_spare_engine(self, spare_engine_id, headers):
        return self._request("GET", f"/api/spare-engines/{spare_engine_id}", headers=headers)

    def list_spare_engine_leases(self, spare_engine_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/spare-engines/{spare_engine_id}/leases",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
