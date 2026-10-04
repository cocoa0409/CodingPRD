"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- manufacturer clients ---------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def reinstate_client(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/clients/{client_id}/reinstate", payload or {}, headers
        )

    def list_client_report_products(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/report-products", headers=headers, params=params
        )

    def list_client_audit_events(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/audit-events", headers=headers, params=params
        )

    def request_audit(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/audit-requests", payload, headers
        )

    # ---- data suppliers ---------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, headers, payload=None):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/suspend", payload or {}, headers
        )

    def resume_supplier(self, supplier_id, headers, payload=None):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/resume", payload or {}, headers
        )

    def create_agreement(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/agreements", payload, headers
        )

    def list_supplier_agreements(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"/suppliers/{supplier_id}/agreements", headers=headers, params=params
        )

    # ---- data acquisition agreements --------------------------------------
    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/data-acquisition-agreements/{agreement_id}", headers=headers
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/data-acquisition-agreements/{agreement_id}/activate",
            payload or {}, headers,
        )

    def suspend_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/data-acquisition-agreements/{agreement_id}/suspend",
            payload or {}, headers,
        )

    def resume_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/data-acquisition-agreements/{agreement_id}/resume",
            payload or {}, headers,
        )

    def terminate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/data-acquisition-agreements/{agreement_id}/terminate",
            payload or {}, headers,
        )

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/data-acquisition-agreements/{agreement_id}/amendments",
            payload, headers,
        )

    # ---- de-identification profiles ---------------------------------------
    def create_deid_profile(self, payload, headers):
        return self._request("POST", "/deidentification-profiles", payload, headers)

    def get_deid_profile(self, profile_id, headers):
        return self._request(
            "GET", f"/deidentification-profiles/{profile_id}", headers=headers
        )

    def list_deid_profile_batches(self, profile_id, headers, params=None):
        return self._request(
            "GET", f"/deidentification-profiles/{profile_id}/batches",
            headers=headers, params=params,
        )

    # ---- data feed batches --------------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/data-feed-batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/data-feed-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/data-feed-batches/{batch_id}", headers=headers)

    def validate_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/data-feed-batches/{batch_id}/validate", payload or {}, headers
        )

    def deidentify_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/data-feed-batches/{batch_id}/deidentify", payload, headers
        )

    def accept_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/data-feed-batches/{batch_id}/accept", payload, headers
        )

    def reject_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/data-feed-batches/{batch_id}/reject", payload or {}, headers
        )

    def reprocess_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/data-feed-batches/{batch_id}/reprocess", payload or {}, headers
        )

    # ---- prescribers --------------------------------------------------------
    def create_prescriber(self, payload, headers):
        return self._request("POST", "/prescribers", payload, headers)

    def list_prescribers(self, headers, params=None):
        return self._request("GET", "/prescribers", headers=headers, params=params)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/prescribers/{prescriber_id}", headers=headers)

    def deactivate_prescriber(self, prescriber_id, headers, payload=None):
        return self._request(
            "POST", f"/prescribers/{prescriber_id}/deactivate", payload or {}, headers
        )

    def reactivate_prescriber(self, prescriber_id, headers, payload=None):
        return self._request(
            "POST", f"/prescribers/{prescriber_id}/reactivate", payload or {}, headers
        )

    def create_opt_out(self, prescriber_id, payload, headers):
        return self._request(
            "POST", f"/prescribers/{prescriber_id}/opt-outs", payload, headers
        )

    def list_prescriber_opt_outs(self, prescriber_id, headers, params=None):
        return self._request(
            "GET", f"/prescribers/{prescriber_id}/opt-outs", headers=headers,
            params=params,
        )

    # ---- prescriber opt-outs ------------------------------------------------
    def get_opt_out(self, opt_out_id, headers):
        return self._request("GET", f"/prescriber-opt-outs/{opt_out_id}", headers=headers)

    def verify_opt_out(self, opt_out_id, headers, payload=None):
        return self._request(
            "POST", f"/prescriber-opt-outs/{opt_out_id}/verify", payload or {}, headers
        )

    def activate_opt_out(self, opt_out_id, headers, payload=None):
        return self._request(
            "POST", f"/prescriber-opt-outs/{opt_out_id}/activate", payload or {}, headers
        )

    def reject_opt_out(self, opt_out_id, headers, payload=None):
        return self._request(
            "POST", f"/prescriber-opt-outs/{opt_out_id}/reject", payload or {}, headers
        )

    def lift_opt_out(self, opt_out_id, headers, payload=None):
        return self._request(
            "POST", f"/prescriber-opt-outs/{opt_out_id}/lift", payload or {}, headers
        )

    # ---- jurisdiction rules -------------------------------------------------
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/jurisdiction-rules", payload, headers)

    def list_jurisdiction_rules(self, headers, params=None):
        return self._request("GET", "/jurisdiction-rules", headers=headers, params=params)

    # ---- projection methodologies -------------------------------------------
    def create_methodology(self, payload, headers):
        return self._request("POST", "/projection-methodologies", payload, headers)

    def get_methodology(self, methodology_id, headers):
        return self._request(
            "GET", f"/projection-methodologies/{methodology_id}", headers=headers
        )

    def restate_methodology(self, methodology_id, payload, headers):
        return self._request(
            "POST", f"/projection-methodologies/{methodology_id}/restate",
            payload, headers,
        )

    # ---- projection cells ---------------------------------------------------
    def create_cell(self, payload, headers):
        return self._request("POST", "/projection-cells", payload, headers)

    def list_cells(self, headers, params=None):
        return self._request("GET", "/projection-cells", headers=headers, params=params)

    def get_cell(self, cell_id, headers):
        return self._request("GET", f"/projection-cells/{cell_id}", headers=headers)

    def recompute_cell(self, cell_id, payload, headers):
        return self._request(
            "POST", f"/projection-cells/{cell_id}/recompute", payload, headers
        )

    # ---- report products ----------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/report-products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/report-products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/report-products/{product_id}", headers=headers)

    def sync_product_methodology(self, product_id, headers, payload=None):
        return self._request(
            "POST", f"/report-products/{product_id}/sync-methodology",
            payload or {}, headers,
        )

    def invoice_preview(self, product_id, payload, headers):
        return self._request(
            "POST", f"/report-products/{product_id}/invoice-preview", payload, headers
        )

    def create_delivery_period(self, product_id, payload, headers):
        return self._request(
            "POST", f"/report-products/{product_id}/delivery-periods", payload, headers
        )

    def list_product_delivery_periods(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/report-products/{product_id}/delivery-periods",
            headers=headers, params=params,
        )

    # ---- report delivery periods --------------------------------------------
    def get_delivery_period(self, period_id, headers):
        return self._request(
            "GET", f"/report-delivery-periods/{period_id}", headers=headers
        )

    def close_delivery_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/report-delivery-periods/{period_id}/close", payload, headers
        )

    def schedule_delivery(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/report-delivery-periods/{period_id}/deliveries",
            payload or {}, headers,
        )

    def list_period_deliveries(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/report-delivery-periods/{period_id}/deliveries",
            headers=headers, params=params,
        )

    # ---- report deliveries --------------------------------------------------
    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/report-deliveries/{delivery_id}", headers=headers)

    def compile_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/report-deliveries/{delivery_id}/compile", payload or {}, headers
        )

    def release_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/report-deliveries/{delivery_id}/release", payload or {}, headers
        )

    def recall_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/report-deliveries/{delivery_id}/recall", payload or {}, headers
        )

    def reissue_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/report-deliveries/{delivery_id}/reissue", payload or {}, headers
        )

    # ---- client audit events ------------------------------------------------
    def get_audit_event(self, audit_id, headers):
        return self._request("GET", f"/audit-events/{audit_id}", headers=headers)

    def schedule_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"/audit-events/{audit_id}/schedule", payload or {}, headers
        )

    def complete_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audit-events/{audit_id}/complete", payload, headers
        )

    def cancel_audit(self, audit_id, headers, payload=None):
        return self._request(
            "POST", f"/audit-events/{audit_id}/cancel", payload or {}, headers
        )


api_client = ApiClient()
