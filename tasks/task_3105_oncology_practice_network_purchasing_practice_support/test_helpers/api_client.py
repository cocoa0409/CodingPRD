"""API client: one method per endpoint in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Clock (test-driving) ----------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Networks ----------------------------------------------------------
    def create_network(self, payload, headers):
        return self._request("POST", "/networks", payload, headers)

    def list_networks(self, headers, params=None):
        return self._request("GET", "/networks", params, headers=headers)

    def get_network(self, network_id, headers):
        return self._request("GET", f"/networks/{network_id}", headers=headers)

    def advance_epoch(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/advance-epoch", payload, headers)

    def freeze_commercial_terms(self, network_id, headers):
        return self._request("POST", f"/networks/{network_id}/freeze-commercial-terms", {}, headers)

    def unfreeze_commercial_terms(self, network_id, headers):
        return self._request("POST", f"/networks/{network_id}/unfreeze-commercial-terms", {}, headers)

    def get_rebate_share_report(self, network_id, headers, params=None):
        return self._request("GET", f"/networks/{network_id}/reporting/rebate-share", params, headers=headers)

    # --- Practices ---------------------------------------------------------
    def create_practice(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/practices", payload, headers)

    def list_practices(self, headers, params=None):
        return self._request("GET", "/networks/practices", params, headers=headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/networks/practices/{practice_id}", headers=headers)

    def affiliate_practice(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/affiliate", {}, headers)

    def suspend_practice(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/suspend", {}, headers)

    def reinstate_practice(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/reinstate", {}, headers)

    def departure_notice(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/departure-notice", {}, headers)

    def withdraw_departure(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/withdraw-departure", {}, headers)

    def withdraw_affiliation(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/withdraw-affiliation", {}, headers)

    def adopt_pathways(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/pathways/adopt", {}, headers)

    def suspend_pathways(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/pathways/suspend", {}, headers)

    def withdraw_pathways(self, practice_id, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/pathways/withdraw", {}, headers)

    def get_stock_report(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/stock-report", params, headers=headers)

    def list_practice_providers(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/providers", params, headers=headers)

    def list_practice_pricing_agreements(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/pricing-agreements", params, headers=headers)

    def list_practice_purchase_orders(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/purchase-orders", params, headers=headers)

    def list_practice_inventory_lots(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/inventory-lots", params, headers=headers)

    def list_practice_treatments(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/treatments", params, headers=headers)

    def list_practice_payer_claims(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/payer-claims", params, headers=headers)

    def list_practice_rebate_qualifications(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/rebate-qualifications", params, headers=headers)

    def list_practice_management_agreements(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/management-agreements", params, headers=headers)

    def list_practice_research_participations(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/research-participations", params, headers=headers)

    def list_practice_affiliation_contracts(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/affiliation-contracts", params, headers=headers)

    def list_practice_shortage_allocations(self, practice_id, headers, params=None):
        return self._request("GET", f"/networks/practices/{practice_id}/shortage-allocations", params, headers=headers)

    # --- Network-scoped flat collections -----------------------------------
    def list_drug_products(self, headers, params=None):
        return self._request("GET", "/networks/drug-products", params, headers=headers)

    def get_drug_product(self, product_id, headers):
        return self._request("GET", f"/networks/drug-products/{product_id}", headers=headers)

    def list_product_shortages(self, product_id, headers, params=None):
        return self._request("GET", f"/networks/drug-products/{product_id}/shortages", params, headers=headers)

    def list_product_treatments(self, product_id, headers, params=None):
        return self._request("GET", f"/networks/drug-products/{product_id}/treatments", params, headers=headers)

    def list_drug_purchase_orders(self, headers, params=None):
        return self._request("GET", "/networks/drug-purchase-orders", params, headers=headers)

    def get_drug_purchase_order(self, order_id, headers):
        return self._request("GET", f"/networks/drug-purchase-orders/{order_id}", headers=headers)

    def list_order_lots(self, order_id, headers):
        return self._request("GET", f"/networks/drug-purchase-orders/{order_id}/lots", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/networks/inventory-lots", params, headers=headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/networks/inventory-lots/{lot_id}", headers=headers)

    def list_lot_consumptions(self, lot_id, headers):
        return self._request("GET", f"/networks/inventory-lots/{lot_id}/consumptions", headers=headers)

    def list_lot_consumption_rows(self, headers, params=None):
        return self._request("GET", "/networks/lot-consumptions", params, headers=headers)

    def get_lot_consumption(self, consumption_id, headers):
        return self._request("GET", f"/networks/lot-consumptions/{consumption_id}", headers=headers)

    def list_patient_treatments(self, headers, params=None):
        return self._request("GET", "/networks/patient-treatments", params, headers=headers)

    def get_patient_treatment(self, treatment_id, headers):
        return self._request("GET", f"/networks/patient-treatments/{treatment_id}", headers=headers)

    def list_treatment_consumptions(self, treatment_id, headers):
        return self._request("GET", f"/networks/patient-treatments/{treatment_id}/consumptions", headers=headers)

    def list_treatment_claims(self, treatment_id, headers, params=None):
        return self._request("GET", f"/networks/patient-treatments/{treatment_id}/claims", params, headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/networks/providers", params, headers=headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/networks/providers/{provider_id}", headers=headers)

    def list_provider_treatments(self, provider_id, headers, params=None):
        return self._request("GET", f"/networks/providers/{provider_id}/treatments", params, headers=headers)

    def list_payer_claims(self, headers, params=None):
        return self._request("GET", "/networks/payer-claims", params, headers=headers)

    def get_payer_claim(self, claim_id, headers):
        return self._request("GET", f"/networks/payer-claims/{claim_id}", headers=headers)

    def list_rebate_programs(self, headers, params=None):
        return self._request("GET", "/networks/rebate-programs", params, headers=headers)

    def get_rebate_program(self, program_id, headers):
        return self._request("GET", f"/networks/rebate-programs/{program_id}", headers=headers)

    def list_program_qualifications(self, program_id, headers, params=None):
        return self._request("GET", f"/networks/rebate-programs/{program_id}/qualifications", params, headers=headers)

    def list_rebate_qualifications(self, headers, params=None):
        return self._request("GET", "/networks/rebate-qualifications", params, headers=headers)

    def get_rebate_qualification(self, qualification_id, headers):
        return self._request("GET", f"/networks/rebate-qualifications/{qualification_id}", headers=headers)

    def list_pathway_protocols(self, headers, params=None):
        return self._request("GET", "/networks/pathway-protocols", params, headers=headers)

    def get_pathway_protocol(self, protocol_id, headers):
        return self._request("GET", f"/networks/pathway-protocols/{protocol_id}", headers=headers)

    def list_management_agreements(self, headers, params=None):
        return self._request("GET", "/networks/practice-management-agreements", params, headers=headers)

    def get_management_agreement(self, agreement_id, headers):
        return self._request("GET", f"/networks/practice-management-agreements/{agreement_id}", headers=headers)

    def get_management_statement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/networks/practice-management-agreements/{agreement_id}/statement", params, headers=headers)

    def list_research_participations(self, headers, params=None):
        return self._request("GET", "/networks/research-participations", params, headers=headers)

    def get_research_participation(self, participation_id, headers):
        return self._request("GET", f"/networks/research-participations/{participation_id}", headers=headers)

    def list_drug_shortages(self, headers, params=None):
        return self._request("GET", "/networks/drug-shortages", params, headers=headers)

    def get_drug_shortage(self, shortage_id, headers):
        return self._request("GET", f"/networks/drug-shortages/{shortage_id}", headers=headers)

    def list_shortage_grants(self, shortage_id, headers, params=None):
        return self._request("GET", f"/networks/drug-shortages/{shortage_id}/allocations", params, headers=headers)

    def list_shortage_allocations(self, headers, params=None):
        return self._request("GET", "/networks/shortage-allocations", params, headers=headers)

    def get_shortage_allocation(self, allocation_id, headers):
        return self._request("GET", f"/networks/shortage-allocations/{allocation_id}", headers=headers)

    def list_allocation_orders(self, allocation_id, headers, params=None):
        return self._request("GET", f"/networks/shortage-allocations/{allocation_id}/orders", params, headers=headers)

    def list_affiliation_contracts(self, headers, params=None):
        return self._request("GET", "/networks/affiliation-contracts", params, headers=headers)

    def get_affiliation_contract(self, contract_id, headers):
        return self._request("GET", f"/networks/affiliation-contracts/{contract_id}", headers=headers)

    # --- Pathway protocols -------------------------------------------------
    def create_pathway_protocol(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/pathway-protocols", payload, headers)

    def update_pathway_protocol(self, protocol_id, payload, headers):
        return self._request("PUT", f"/networks/pathway-protocols/{protocol_id}", payload, headers)

    # --- Providers ---------------------------------------------------------
    def create_provider(self, practice_id, payload, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/providers", payload, headers)

    def deactivate_provider(self, provider_id, headers):
        return self._request("POST", f"/networks/providers/{provider_id}/deactivate", {}, headers)

    def reactivate_provider(self, provider_id, headers):
        return self._request("POST", f"/networks/providers/{provider_id}/reactivate", {}, headers)

    # --- Drug products -----------------------------------------------------
    def create_drug_product(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/drug-products", payload, headers)

    def recall_drug_product(self, product_id, headers):
        return self._request("POST", f"/networks/drug-products/{product_id}/recall", {}, headers)

    # --- Pricing agreements ------------------------------------------------
    def create_pricing_agreement(self, practice_id, payload, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/pricing-agreements", payload, headers)

    def list_pricing_agreements(self, headers, params=None):
        return self._request("GET", "/networks/pricing-agreements", params, headers=headers)

    def get_pricing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/networks/pricing-agreements/{agreement_id}", headers=headers)

    def submit_pricing_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/networks/pricing-agreements/{agreement_id}/submit", payload, headers)

    def approve_pricing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/pricing-agreements/{agreement_id}/approve", {}, headers)

    def return_agreement_to_draft(self, agreement_id, headers):
        return self._request("POST", f"/networks/pricing-agreements/{agreement_id}/return-to-draft", {}, headers)

    def reject_pricing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/pricing-agreements/{agreement_id}/reject", {}, headers)

    def reinstate_pricing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/pricing-agreements/{agreement_id}/reinstate", {}, headers)

    # --- Purchase orders ---------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/networks/drug-purchase-orders", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/networks/drug-purchase-orders/{order_id}/confirm", {}, headers)

    def backorder_order(self, order_id, headers):
        return self._request("POST", f"/networks/drug-purchase-orders/{order_id}/backorder", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/networks/drug-purchase-orders/{order_id}/ship", {}, headers)

    def receive_order(self, order_id, payload, headers):
        return self._request("POST", f"/networks/drug-purchase-orders/{order_id}/receive", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/networks/drug-purchase-orders/{order_id}/cancel", {}, headers)

    # --- Inventory lots ----------------------------------------------------
    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/networks/inventory-lots/{lot_id}/quarantine", {}, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/networks/inventory-lots/{lot_id}/release", {}, headers)

    def read_lot_expiry(self, lot_id, payload, headers):
        return self._request("POST", f"/networks/inventory-lots/{lot_id}/read-expiry", payload, headers)

    # --- Patient treatments ------------------------------------------------
    def create_treatment(self, payload, headers):
        return self._request("POST", "/networks/patient-treatments", payload, headers)

    def administer_treatment(self, treatment_id, payload, headers):
        return self._request("POST", f"/networks/patient-treatments/{treatment_id}/administer", payload, headers)

    def void_treatment(self, treatment_id, headers):
        return self._request("POST", f"/networks/patient-treatments/{treatment_id}/void", {}, headers)

    # --- Payer claims ------------------------------------------------------
    def submit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/networks/payer-claims/{claim_id}/submit", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/networks/payer-claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/networks/payer-claims/{claim_id}/deny", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/networks/payer-claims/{claim_id}/appeal", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/networks/payer-claims/{claim_id}/void", {}, headers)

    # --- Rebate programs and qualifications --------------------------------
    def create_rebate_program(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/rebate-programs", payload, headers)

    def activate_rebate_program(self, program_id, headers):
        return self._request("POST", f"/networks/rebate-programs/{program_id}/activate", {}, headers)

    def close_rebate_program(self, program_id, headers):
        return self._request("POST", f"/networks/rebate-programs/{program_id}/close", {}, headers)

    def create_rebate_qualification(self, payload, headers):
        return self._request("POST", "/networks/rebate-qualifications", payload, headers)

    def report_compliance(self, qualification_id, payload, headers):
        return self._request("POST", f"/networks/rebate-qualifications/{qualification_id}/report", payload, headers)

    def verify_compliance_report(self, qualification_id, headers):
        return self._request("POST", f"/networks/rebate-qualifications/{qualification_id}/verify-report", {}, headers)

    def evaluate_qualification(self, qualification_id, headers):
        return self._request("POST", f"/networks/rebate-qualifications/{qualification_id}/evaluate", {}, headers)

    def pay_qualification(self, qualification_id, headers):
        return self._request("POST", f"/networks/rebate-qualifications/{qualification_id}/pay", {}, headers)

    def reclaim_qualification(self, qualification_id, headers):
        return self._request("POST", f"/networks/rebate-qualifications/{qualification_id}/reclaim", {}, headers)

    # --- Practice management agreements ------------------------------------
    def create_management_agreement(self, payload, headers):
        return self._request("POST", "/networks/practice-management-agreements", payload, headers)

    def activate_management_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/practice-management-agreements/{agreement_id}/activate", {}, headers)

    def suspend_management_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/practice-management-agreements/{agreement_id}/suspend", {}, headers)

    def terminate_management_agreement(self, agreement_id, headers):
        return self._request("POST", f"/networks/practice-management-agreements/{agreement_id}/terminate", {}, headers)

    # --- Research participations -------------------------------------------
    def create_research_participation(self, practice_id, payload, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/research-participations", payload, headers)

    def begin_feasibility(self, participation_id, headers):
        return self._request("POST", f"/networks/research-participations/{participation_id}/begin-feasibility", {}, headers)

    def activate_research_site(self, participation_id, headers):
        return self._request("POST", f"/networks/research-participations/{participation_id}/activate", {}, headers)

    def suspend_research_site(self, participation_id, headers):
        return self._request("POST", f"/networks/research-participations/{participation_id}/suspend", {}, headers)

    def deactivate_research_site(self, participation_id, headers):
        return self._request("POST", f"/networks/research-participations/{participation_id}/deactivate", {}, headers)

    def enroll_participant(self, participation_id, payload, headers):
        return self._request("POST", f"/networks/research-participations/{participation_id}/enroll-participant", payload, headers)

    # --- Drug shortages ----------------------------------------------------
    def report_shortage(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/drug-shortages", payload, headers)

    def allocate_shortage(self, shortage_id, payload, headers):
        return self._request("POST", f"/networks/drug-shortages/{shortage_id}/allocate", payload, headers)

    def activate_shortage(self, shortage_id, headers):
        return self._request("POST", f"/networks/drug-shortages/{shortage_id}/activate", {}, headers)

    def resolve_shortage(self, shortage_id, headers):
        return self._request("POST", f"/networks/drug-shortages/{shortage_id}/resolve", {}, headers)

    # --- Affiliation contracts ---------------------------------------------
    def create_affiliation_contract(self, practice_id, payload, headers):
        return self._request("POST", f"/networks/practices/{practice_id}/affiliation-contracts", payload, headers)

    def activate_affiliation_contract(self, contract_id, headers):
        return self._request("POST", f"/networks/affiliation-contracts/{contract_id}/activate", {}, headers)

    def complete_contract_unwind(self, contract_id, headers):
        return self._request("POST", f"/networks/affiliation-contracts/{contract_id}/complete-unwind", {}, headers)

    def terminate_affiliation_contract(self, contract_id, headers):
        return self._request("POST", f"/networks/affiliation-contracts/{contract_id}/terminate", {}, headers)


api_client = ApiClient()