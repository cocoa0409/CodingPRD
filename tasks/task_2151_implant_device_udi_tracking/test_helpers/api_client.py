"""API client: one method per endpoint defined in the PRD.

Every business resource is mounted beneath the `/udi` prefix; the logical-clock
endpoint sits at `/_clock/set_current_utc`.
"""

from prd_bench_local_runner.testing import GenericApiClient

UDI = "/udi"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Vendors ──────────────────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{UDI}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{UDI}/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", f"{UDI}/vendors", payload=params, headers=headers)

    # ─── Consignment agreements ───────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{UDI}/consignment-agreements", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{UDI}/consignment-agreements/{agreement_id}/activate", {}, headers
        )

    def record_price_list_revision(self, agreement_id, headers):
        return self._request(
            "POST",
            f"{UDI}/consignment-agreements/{agreement_id}/price-list-revisions",
            {},
            headers,
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{UDI}/consignment-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/consignment-agreements", payload=params, headers=headers
        )

    # ─── Catalog items ────────────────────────────────────────────────
    def create_catalog_item(self, payload, headers):
        return self._request("POST", f"{UDI}/catalog-items", payload, headers)

    def get_catalog_item(self, catalog_item_id, headers):
        return self._request(
            "GET", f"{UDI}/catalog-items/{catalog_item_id}", headers=headers
        )

    def list_catalog_items(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/catalog-items", payload=params, headers=headers
        )

    # ─── Lots ─────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", f"{UDI}/lots", payload, headers)

    def add_device_unit(self, lot_id, payload, headers):
        return self._request("POST", f"{UDI}/lots/{lot_id}/device-units", payload, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"{UDI}/lots/{lot_id}/release", {}, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{UDI}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{UDI}/lots", payload=params, headers=headers)

    # ─── Device units ─────────────────────────────────────────────────
    def get_device_unit(self, device_unit_id, headers):
        return self._request(
            "GET", f"{UDI}/device-units/{device_unit_id}", headers=headers
        )

    def list_device_units(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/device-units", payload=params, headers=headers
        )

    def release_reservation(self, device_unit_id, headers):
        return self._request(
            "POST", f"{UDI}/device-units/{device_unit_id}/release-reservation", {}, headers
        )

    def waste_device_unit(self, device_unit_id, headers):
        return self._request(
            "POST", f"{UDI}/device-units/{device_unit_id}/waste", {}, headers
        )

    # ─── Patients ─────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", f"{UDI}/patients", payload, headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"{UDI}/patients/{patient_id}", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{UDI}/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{UDI}/patients", payload=params, headers=headers)

    # ─── Surgical cases ───────────────────────────────────────────────
    def create_surgical_case(self, payload, headers):
        return self._request("POST", f"{UDI}/surgical-cases", payload, headers)

    def get_surgical_case(self, case_id, headers):
        return self._request("GET", f"{UDI}/surgical-cases/{case_id}", headers=headers)

    def list_surgical_cases(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/surgical-cases", payload=params, headers=headers
        )

    def get_case_readiness(self, case_id, headers):
        return self._request(
            "GET", f"{UDI}/surgical-cases/{case_id}/readiness", headers=headers
        )

    def create_reservation(self, case_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/surgical-cases/{case_id}/reservations", payload, headers
        )

    def start_case(self, case_id, headers):
        return self._request("POST", f"{UDI}/surgical-cases/{case_id}/start", {}, headers)

    def create_implant_record(self, case_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/surgical-cases/{case_id}/implant-records", payload, headers
        )

    def close_case(self, case_id, headers):
        return self._request("POST", f"{UDI}/surgical-cases/{case_id}/close", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"{UDI}/surgical-cases/{case_id}/cancel", {}, headers)

    # ─── Implant records ──────────────────────────────────────────────
    def get_implant_record(self, implant_record_id, headers):
        return self._request(
            "GET", f"{UDI}/implant-records/{implant_record_id}", headers=headers
        )

    def list_implant_records(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/implant-records", payload=params, headers=headers
        )

    def verify_implant_record(self, implant_record_id, headers):
        return self._request(
            "POST", f"{UDI}/implant-records/{implant_record_id}/verify", {}, headers
        )

    def amend_implant_record(self, implant_record_id, headers):
        return self._request(
            "POST", f"{UDI}/implant-records/{implant_record_id}/amend", {}, headers
        )

    def create_explant(self, implant_record_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/implant-records/{implant_record_id}/explants", payload, headers
        )

    # ─── Charge captures ──────────────────────────────────────────────
    def create_charge(self, implant_record_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/implant-records/{implant_record_id}/charges", payload, headers
        )

    def get_charge(self, charge_id, headers):
        return self._request(
            "GET", f"{UDI}/charge-captures/{charge_id}", headers=headers
        )

    def list_charges(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/charge-captures", payload=params, headers=headers
        )

    def post_charge(self, charge_id, headers):
        return self._request(
            "POST", f"{UDI}/charge-captures/{charge_id}/post", {}, headers
        )

    def finalize_charge(self, charge_id, headers):
        return self._request(
            "POST", f"{UDI}/charge-captures/{charge_id}/finalize", {}, headers
        )

    def correct_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/charge-captures/{charge_id}/correct", payload, headers
        )

    def void_charge(self, charge_id, headers):
        return self._request(
            "POST", f"{UDI}/charge-captures/{charge_id}/void", {}, headers
        )

    # ─── Registry submissions ─────────────────────────────────────────
    def get_registry_submission(self, submission_id, headers):
        return self._request(
            "GET", f"{UDI}/registry-submissions/{submission_id}", headers=headers
        )

    def list_registry_submissions(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/registry-submissions", payload=params, headers=headers
        )

    def submit_registry_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/registry-submissions/{submission_id}/submit", payload, headers
        )

    def adjudicate_registry_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"{UDI}/registry-submissions/{submission_id}/adjudicate",
            payload,
            headers,
        )

    # ─── Field actions ────────────────────────────────────────────────
    def create_field_action(self, payload, headers):
        return self._request("POST", f"{UDI}/field-actions", payload, headers)

    def publish_field_action(self, field_action_id, headers):
        return self._request(
            "POST", f"{UDI}/field-actions/{field_action_id}/publish", {}, headers
        )

    def close_field_action(self, field_action_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/field-actions/{field_action_id}/close", payload, headers
        )

    def get_field_action(self, field_action_id, headers):
        return self._request(
            "GET", f"{UDI}/field-actions/{field_action_id}", headers=headers
        )

    def list_field_actions(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/field-actions", payload=params, headers=headers
        )

    def get_field_action_exposure(self, field_action_id, headers):
        return self._request(
            "GET", f"{UDI}/field-actions/{field_action_id}/exposure", headers=headers
        )

    # ─── Recall notifications ─────────────────────────────────────────
    def get_recall_notification(self, notification_id, headers):
        return self._request(
            "GET", f"{UDI}/recall-notifications/{notification_id}", headers=headers
        )

    def list_recall_notifications(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/recall-notifications", payload=params, headers=headers
        )

    def resolve_recall_notification(self, notification_id, payload, headers):
        return self._request(
            "POST",
            f"{UDI}/recall-notifications/{notification_id}/resolve",
            payload,
            headers,
        )

    # ─── Vendor invoices ──────────────────────────────────────────────
    def create_vendor_invoice(self, payload, headers):
        return self._request("POST", f"{UDI}/vendor-invoices", payload, headers)

    def match_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{UDI}/vendor-invoices/{invoice_id}/match", {}, headers
        )

    def approve_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/vendor-invoices/{invoice_id}/approve", payload, headers
        )

    def dispute_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{UDI}/vendor-invoices/{invoice_id}/dispute", {}, headers
        )

    def resubmit_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/vendor-invoices/{invoice_id}/resubmit", payload, headers
        )

    def get_vendor_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{UDI}/vendor-invoices/{invoice_id}", headers=headers
        )

    def list_vendor_invoices(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/vendor-invoices", payload=params, headers=headers
        )

    # ─── Explant records ──────────────────────────────────────────────
    def get_explant_record(self, explant_record_id, headers):
        return self._request(
            "GET", f"{UDI}/explant-records/{explant_record_id}", headers=headers
        )

    def list_explant_records(self, headers, params=None):
        return self._request(
            "GET", f"{UDI}/explant-records", payload=params, headers=headers
        )

    def disposition_explant(self, explant_record_id, payload, headers):
        return self._request(
            "POST",
            f"{UDI}/explant-records/{explant_record_id}/disposition",
            payload,
            headers,
        )

    def ship_explant(self, explant_record_id, headers):
        return self._request(
            "POST", f"{UDI}/explant-records/{explant_record_id}/ship", {}, headers
        )

    def credit_explant(self, explant_record_id, payload, headers):
        return self._request(
            "POST", f"{UDI}/explant-records/{explant_record_id}/credit", payload, headers
        )

    # ─── Operational checkpoint ───────────────────────────────────────
    def create_ops_run(self, headers):
        return self._request("POST", f"{UDI}/ops-runs", {}, headers)


api_client = ApiClient()
