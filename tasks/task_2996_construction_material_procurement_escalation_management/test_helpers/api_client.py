"""API client: one method per endpoint defined in the PRD (§4).

Every endpoint lives under the `/procurement` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/procurement"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Construction Material Procurement API."""

    # ─── Project ──────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    # ─── MaterialPackage ──────────────────────────────────────────────────
    def create_material_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/material-packages", payload, headers)

    def get_material_package(self, package_id, headers):
        return self._request(
            "GET", f"{PREFIX}/material-packages/{package_id}", headers=headers
        )

    def list_material_packages(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/material-packages", headers=headers, params=params
        )

    def update_material_package(self, package_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/material-packages/{package_id}", payload, headers
        )

    # ─── Supplier / DisruptionEvent ───────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{PREFIX}/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/suppliers", headers=headers, params=params)

    def suspend_supplier(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/suppliers/{supplier_id}/suspend", payload, headers
        )

    def create_disruption_event(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/suppliers/{supplier_id}/disruption-events", payload, headers
        )

    def list_disruption_events(self, supplier_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/suppliers/{supplier_id}/disruption-events",
            headers=headers,
            params=params,
        )

    # ─── Quote ────────────────────────────────────────────────────────────
    def create_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes", headers=headers, params=params)

    def revise_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/quotes/{quote_id}/revise", payload, headers
        )

    # ─── EscalationAgreement ──────────────────────────────────────────────
    def create_escalation_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/escalation-agreements", payload, headers)

    def get_escalation_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/escalation-agreements/{agreement_id}", headers=headers
        )

    def list_escalation_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/escalation-agreements", headers=headers, params=params
        )

    def propose_escalation_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/escalation-agreements/{agreement_id}/propose",
            payload,
            headers,
        )

    def counter_escalation_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/escalation-agreements/{agreement_id}/counter",
            payload,
            headers,
        )

    def execute_escalation_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/escalation-agreements/{agreement_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    # ─── IndexReading ─────────────────────────────────────────────────────
    def create_index_reading(self, payload, headers):
        return self._request("POST", f"{PREFIX}/index-readings", payload, headers)

    def list_index_readings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/index-readings", headers=headers, params=params
        )

    # ─── PurchaseCommitment ───────────────────────────────────────────────
    def create_purchase_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/purchase-commitments", payload, headers)

    def get_purchase_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/purchase-commitments/{commitment_id}", headers=headers
        )

    def list_purchase_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/purchase-commitments", headers=headers, params=params
        )

    def commit_purchase_commitment(self, commitment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-commitments/{commitment_id}/commit",
            payload if payload is not None else {},
            headers,
        )

    def set_delivery_posture(self, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-commitments/{commitment_id}/delivery-posture",
            payload,
            headers,
        )

    def cancel_purchase_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/purchase-commitments/{commitment_id}/cancel",
            payload,
            headers,
        )

    # ─── OffsiteStorageArrangement / StorageDocument ──────────────────────
    def create_storage_arrangement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-arrangements", payload, headers)

    def get_storage_arrangement(self, arrangement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/storage-arrangements/{arrangement_id}", headers=headers
        )

    def list_storage_arrangements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/storage-arrangements", headers=headers, params=params
        )

    def create_storage_document(self, arrangement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/storage-arrangements/{arrangement_id}/documents",
            payload,
            headers,
        )

    def list_storage_documents(self, arrangement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/storage-arrangements/{arrangement_id}/documents",
            headers=headers,
            params=params,
        )

    def revoke_storage_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-documents/{document_id}/revoke", payload, headers
        )

    # ─── SubstitutionRequest ──────────────────────────────────────────────
    def create_substitution_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/substitution-requests", payload, headers)

    def get_substitution_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/substitution-requests/{request_id}", headers=headers
        )

    def list_substitution_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/substitution-requests", headers=headers, params=params
        )

    def disposition_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/substitution-requests/{request_id}/disposition",
            payload,
            headers,
        )

    def resubmit_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/substitution-requests/{request_id}/resubmit",
            payload,
            headers,
        )

    def rescind_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/substitution-requests/{request_id}/rescind",
            payload,
            headers,
        )

    # ─── ChangeOrderRequest ───────────────────────────────────────────────
    def create_change_order_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/change-order-requests", payload, headers)

    def get_change_order_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/change-order-requests/{request_id}", headers=headers
        )

    def list_change_order_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/change-order-requests", headers=headers, params=params
        )

    def submit_change_order_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/change-order-requests/{request_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def disposition_change_order_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/change-order-requests/{request_id}/disposition",
            payload,
            headers,
        )

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
