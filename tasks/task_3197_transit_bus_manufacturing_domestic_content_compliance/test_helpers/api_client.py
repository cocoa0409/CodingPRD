"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ---- agencies -------------------------------------------------------
    def create_agency(self, payload, headers):
        return self._request("POST", "/api/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/api/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/api/agencies/{agency_id}", headers=headers)

    def update_agency(self, agency_id, payload, headers):
        return self._request("PATCH", f"/api/agencies/{agency_id}", payload, headers)

    def list_agency_contracts(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/api/agencies/{agency_id}/contracts", headers=headers, params=params
        )

    def list_agency_training_sessions(self, agency_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/agencies/{agency_id}/training-sessions",
            headers=headers,
            params=params,
        )

    def list_agency_parts_stocks(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/api/agencies/{agency_id}/parts-stocks", headers=headers, params=params
        )

    # ---- contracts ------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def award_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/award", {}, headers
        )

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/activate", {}, headers
        )

    def complete_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/complete", {}, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/terminate", {}, headers
        )

    def list_contract_option_orders(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/contracts/{contract_id}/option-orders",
            headers=headers,
            params=params,
        )

    def list_contract_configurations(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/contracts/{contract_id}/bus-configurations",
            headers=headers,
            params=params,
        )

    def list_contract_bus_units(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/api/contracts/{contract_id}/bus-units", headers=headers, params=params
        )

    def list_contract_audit_records(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/contracts/{contract_id}/audit-records",
            headers=headers,
            params=params,
        )

    # ---- option orders --------------------------------------------------
    def exercise_option_order(self, option_order_id, payload, headers):
        return self._request(
            "POST", f"/api/option-orders/{option_order_id}/exercise", payload, headers
        )

    def get_option_order(self, option_order_id, headers):
        return self._request(
            "GET", f"/api/option-orders/{option_order_id}", headers=headers
        )

    # ---- bus configurations ---------------------------------------------
    def create_bus_configuration(self, payload, headers):
        return self._request("POST", "/api/bus-configurations", payload, headers)

    def get_bus_configuration(self, config_id, headers):
        return self._request(
            "GET", f"/api/bus-configurations/{config_id}", headers=headers
        )

    def submit_review_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/api/bus-configurations/{config_id}/submit-review", {}, headers
        )

    def freeze_configuration(self, config_id, payload, headers):
        return self._request(
            "POST", f"/api/bus-configurations/{config_id}/freeze", payload, headers
        )

    def return_to_draft_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/api/bus-configurations/{config_id}/return-to-draft", {}, headers
        )

    def obsolete_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/api/bus-configurations/{config_id}/obsolete", {}, headers
        )

    def list_configuration_bus_units(self, config_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/bus-configurations/{config_id}/bus-units",
            headers=headers,
            params=params,
        )

    # ---- components -----------------------------------------------------
    def create_component(self, payload, headers):
        return self._request("POST", "/api/components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/api/components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/api/components/{component_id}", headers=headers)

    def submit_supplier_docs(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/supplier-docs", {}, headers
        )

    def verify_docs(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/verify-docs", {}, headers
        )

    def reject_docs(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/reject-docs", {}, headers
        )

    # ---- bus units ------------------------------------------------------
    def create_bus_unit(self, payload, headers):
        return self._request("POST", "/api/bus-units", payload, headers)

    def list_bus_units(self, headers, params=None):
        return self._request("GET", "/api/bus-units", headers=headers, params=params)

    def get_bus_unit(self, bus_unit_id, headers):
        return self._request("GET", f"/api/bus-units/{bus_unit_id}", headers=headers)

    def engineer_bus(self, bus_unit_id, headers):
        return self._request(
            "POST", f"/api/bus-units/{bus_unit_id}/engineer", {}, headers
        )

    def submit_plant_inspection(self, bus_unit_id, headers):
        return self._request(
            "POST", f"/api/bus-units/{bus_unit_id}/submit-plant-inspection", {}, headers
        )

    def deliver_bus(self, bus_unit_id, headers):
        return self._request(
            "POST", f"/api/bus-units/{bus_unit_id}/deliver", {}, headers
        )

    def accept_bus(self, bus_unit_id, headers):
        return self._request("POST", f"/api/bus-units/{bus_unit_id}/accept", {}, headers)

    def record_payment(self, bus_unit_id, headers):
        return self._request(
            "POST", f"/api/bus-units/{bus_unit_id}/record-payment", {}, headers
        )

    def issue_certificate(self, bus_unit_id, payload, headers):
        return self._request(
            "POST",
            f"/api/bus-units/{bus_unit_id}/compliance-certificates",
            payload,
            headers,
        )

    def list_bus_certificates(self, bus_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/bus-units/{bus_unit_id}/compliance-certificates",
            headers=headers,
            params=params,
        )

    def list_bus_parts_kits(self, bus_unit_id, headers, params=None):
        return self._request(
            "GET", f"/api/bus-units/{bus_unit_id}/parts-kits", headers=headers, params=params
        )

    def list_bus_inspection_records(self, bus_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/bus-units/{bus_unit_id}/inspection-records",
            headers=headers,
            params=params,
        )

    def list_bus_warranty_claims(self, bus_unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/bus-units/{bus_unit_id}/warranty-claims",
            headers=headers,
            params=params,
        )

    # ---- compliance certificates ----------------------------------------
    def revoke_certificate(self, certificate_id, headers):
        return self._request(
            "POST",
            f"/api/compliance-certificates/{certificate_id}/revoke",
            {},
            headers,
        )

    # ---- audit records --------------------------------------------------
    def create_audit_record(self, payload, headers):
        return self._request("POST", "/api/audit-records", payload, headers)

    def get_audit_record(self, audit_record_id, headers):
        return self._request(
            "GET", f"/api/audit-records/{audit_record_id}", headers=headers
        )

    def record_audit_finding(self, audit_record_id, payload, headers):
        return self._request(
            "POST", f"/api/audit-records/{audit_record_id}/findings", payload, headers
        )

    def complete_audit(self, audit_record_id, headers):
        return self._request(
            "POST", f"/api/audit-records/{audit_record_id}/complete", {}, headers
        )

    # ---- production slots ------------------------------------------------
    def create_production_slot(self, payload, headers):
        return self._request("POST", "/api/production-slots", payload, headers)

    def list_production_slots(self, headers, params=None):
        return self._request(
            "GET", "/api/production-slots", headers=headers, params=params
        )

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/api/production-slots/{slot_id}", headers=headers)

    def assign_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/api/production-slots/{slot_id}/assign", payload, headers
        )

    def start_production(self, slot_id, headers):
        return self._request(
            "POST", f"/api/production-slots/{slot_id}/start-production", {}, headers
        )

    def complete_production(self, slot_id, headers):
        return self._request(
            "POST", f"/api/production-slots/{slot_id}/complete-production", {}, headers
        )

    def cancel_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/api/production-slots/{slot_id}/cancel", {}, headers
        )

    # ---- parts kits ------------------------------------------------------
    def create_parts_kit(self, payload, headers):
        return self._request("POST", "/api/parts-kits", payload, headers)

    def get_parts_kit(self, kit_id, headers):
        return self._request("GET", f"/api/parts-kits/{kit_id}", headers=headers)

    # ---- inspection records ----------------------------------------------
    def create_inspection_record(self, payload, headers):
        return self._request("POST", "/api/inspection-records", payload, headers)

    def get_inspection_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/inspection-records/{record_id}", headers=headers
        )

    # ---- warranty claims -------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/api/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/api/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/api/warranty-claims/{claim_id}", headers=headers)

    def start_review_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/start-review", {}, headers
        )

    def approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/approve", {}, headers
        )

    def deny_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/deny", {}, headers
        )

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/pay", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/warranty-claims/{claim_id}/close", {}, headers
        )

    # ---- training sessions -----------------------------------------------
    def create_training_session(self, payload, headers):
        return self._request("POST", "/api/training-sessions", payload, headers)

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/api/training-sessions", headers=headers, params=params
        )

    def get_training_session(self, session_id, headers):
        return self._request(
            "GET", f"/api/training-sessions/{session_id}", headers=headers
        )

    def complete_training_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/training-sessions/{session_id}/complete", {}, headers
        )

    def cancel_training_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/training-sessions/{session_id}/cancel", {}, headers
        )

    # ---- parts stocks -----------------------------------------------------
    def create_parts_stock(self, payload, headers):
        return self._request("POST", "/api/parts-stocks", payload, headers)

    def list_parts_stocks(self, headers, params=None):
        return self._request("GET", "/api/parts-stocks", headers=headers, params=params)

    def get_parts_stock(self, stock_id, headers):
        return self._request("GET", f"/api/parts-stocks/{stock_id}", headers=headers)

    def restock_parts_stock(self, stock_id, payload, headers):
        return self._request(
            "PATCH", f"/api/parts-stocks/{stock_id}", payload, headers
        )


api_client = ApiClient()
