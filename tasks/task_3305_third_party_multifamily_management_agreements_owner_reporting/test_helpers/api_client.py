"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock / epoch ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/mgmt/_clock/set_current_utc", payload, headers)

    def advance_month(self, headers, payload=None):
        return self._request("POST", "/mgmt/advance_month", payload or {}, headers)

    # --- Owner ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/mgmt/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/mgmt/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/mgmt/owners", headers=headers, params=params)

    # --- Property ---
    def create_property(self, owner_id, payload, headers):
        return self._request("POST", f"/mgmt/owners/{owner_id}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/mgmt/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/mgmt/properties", headers=headers, params=params)

    def list_for_disposition(self, property_id, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/list_for_disposition", {}, headers)

    def complete_disposition(self, property_id, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/complete_disposition", {}, headers)

    # --- ManagementAgreement ---
    def create_agreement(self, owner_id, payload, headers):
        return self._request("POST", f"/mgmt/owners/{owner_id}/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/mgmt/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/mgmt/agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/mgmt/agreements/{agreement_id}/activate", payload, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mgmt/agreements/{agreement_id}/suspend", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mgmt/agreements/{agreement_id}/resume", {}, headers)

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/mgmt/agreements/{agreement_id}/terminate", payload, headers)

    def complete_termination(self, agreement_id, headers):
        return self._request("POST", f"/mgmt/agreements/{agreement_id}/complete_termination", {}, headers)

    # --- Onboarding ---
    def create_onboarding(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/onboardings", payload, headers)

    def get_onboarding(self, onboarding_id, headers):
        return self._request("GET", f"/mgmt/onboardings/{onboarding_id}", headers=headers)

    def list_property_onboardings(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/onboardings", headers=headers, params=params)

    def list_onboardings(self, headers, params=None):
        return self._request("GET", "/mgmt/onboardings", headers=headers, params=params)

    def verify_resident_data(self, onboarding_id, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/verify_resident_data", {}, headers)

    def import_ledger(self, onboarding_id, payload, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/import_ledger", payload, headers)

    def begin_vendor_review(self, onboarding_id, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/begin_vendor_review", {}, headers)

    def complete_vendor_review(self, onboarding_id, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/complete_vendor_review", {}, headers)

    def activate_onboarding(self, onboarding_id, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/activate", {}, headers)

    def abort_onboarding(self, onboarding_id, headers):
        return self._request("POST", f"/mgmt/onboardings/{onboarding_id}/abort", {}, headers)

    # --- Resident ---
    def create_resident(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/mgmt/residents/{resident_id}", headers=headers)

    def list_property_residents(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/residents", headers=headers, params=params)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/mgmt/residents", headers=headers, params=params)

    # --- VendorContract ---
    def create_vendor_contract(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/vendor-contracts", payload, headers)

    def get_vendor_contract(self, vendor_contract_id, headers):
        return self._request("GET", f"/mgmt/vendor-contracts/{vendor_contract_id}", headers=headers)

    def list_property_vendor_contracts(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/vendor-contracts", headers=headers, params=params)

    def list_vendor_contracts(self, headers, params=None):
        return self._request("GET", "/mgmt/vendor-contracts", headers=headers, params=params)

    def resolve_vendor_contract(self, vendor_contract_id, payload, headers):
        return self._request("POST", f"/mgmt/vendor-contracts/{vendor_contract_id}/resolve", payload, headers)

    # --- Budget ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/mgmt/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/mgmt/budgets/{budget_id}", headers=headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/mgmt/budgets", headers=headers, params=params)

    def submit_budget(self, budget_id, headers):
        return self._request("POST", f"/mgmt/budgets/{budget_id}/submit", {}, headers)

    def approve_budget(self, budget_id, headers):
        return self._request("POST", f"/mgmt/budgets/{budget_id}/approve", {}, headers)

    def reject_budget(self, budget_id, headers):
        return self._request("POST", f"/mgmt/budgets/{budget_id}/reject", {}, headers)

    # --- PricingRecommendation ---
    def create_pricing(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/pricing", payload, headers)

    def get_pricing(self, pricing_id, headers):
        return self._request("GET", f"/mgmt/pricing/{pricing_id}", headers=headers)

    def list_property_pricing(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/pricing", headers=headers, params=params)

    def list_pricing(self, headers, params=None):
        return self._request("GET", "/mgmt/pricing", headers=headers, params=params)

    def publish_pricing(self, pricing_id, headers):
        return self._request("POST", f"/mgmt/pricing/{pricing_id}/publish", {}, headers)

    def override_pricing(self, pricing_id, payload, headers):
        return self._request("POST", f"/mgmt/pricing/{pricing_id}/override", payload, headers)

    def withdraw_pricing(self, pricing_id, headers):
        return self._request("POST", f"/mgmt/pricing/{pricing_id}/withdraw", {}, headers)

    # --- StaffPosition ---
    def create_staff(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/staff", payload, headers)

    def get_staff(self, staff_position_id, headers):
        return self._request("GET", f"/mgmt/staff/{staff_position_id}", headers=headers)

    def list_property_staff(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/staff", headers=headers, params=params)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/mgmt/staff", headers=headers, params=params)

    # --- LedgerEntry ---
    def create_ledger_entry(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/ledger-entries", payload, headers)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/mgmt/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_property_ledger_entries(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/ledger-entries", headers=headers, params=params)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/mgmt/ledger-entries", headers=headers, params=params)

    # --- MonthlyStatement ---
    def create_statement(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/mgmt/statements/{statement_id}", headers=headers)

    def list_property_statements(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/statements", headers=headers, params=params)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/mgmt/statements", headers=headers, params=params)

    def close_statement(self, statement_id, headers):
        return self._request("POST", f"/mgmt/statements/{statement_id}/close", {}, headers)

    def restate_statement(self, statement_id, headers):
        return self._request("POST", f"/mgmt/statements/{statement_id}/restate", {}, headers)

    # --- OwnerReportPackage ---
    def create_report(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/mgmt/reports/{report_id}", headers=headers)

    def list_property_reports(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/reports", headers=headers, params=params)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/mgmt/reports", headers=headers, params=params)

    def generate_report(self, report_id, headers):
        return self._request("POST", f"/mgmt/reports/{report_id}/generate", {}, headers)

    def deliver_report(self, report_id, headers):
        return self._request("POST", f"/mgmt/reports/{report_id}/deliver", {}, headers)

    # --- Claim ---
    def create_claim(self, property_id, payload, headers):
        return self._request("POST", f"/mgmt/properties/{property_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/mgmt/claims/{claim_id}", headers=headers)

    def list_property_claims(self, property_id, headers, params=None):
        return self._request("GET", f"/mgmt/properties/{property_id}/claims", headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/mgmt/claims", headers=headers, params=params)

    def begin_claim_review(self, claim_id, headers):
        return self._request("POST", f"/mgmt/claims/{claim_id}/begin_review", {}, headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/mgmt/claims/{claim_id}/settle", payload, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/mgmt/claims/{claim_id}/close", {}, headers)

    def list_claim_settlements(self, claim_id, headers, params=None):
        return self._request("GET", f"/mgmt/claims/{claim_id}/settlements", headers=headers, params=params)

    # --- ClaimSettlement ---
    def get_claim_settlement(self, claim_settlement_id, headers):
        return self._request("GET", f"/mgmt/claim-settlements/{claim_settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/mgmt/claim-settlements", headers=headers, params=params)


api_client = ApiClient()
