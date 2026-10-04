"""API client: one method per operation defined in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock / system ------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def tick(self, headers, payload=None):
        return self._request("POST", "/_system/tick", payload or {}, headers)

    # --- Employer accounts -----------------------------------------------------
    def create_employer_account(self, payload, headers):
        return self._request("POST", "/employer-accounts", payload, headers)

    def get_employer_account(self, account_id, headers):
        return self._request("GET", f"/employer-accounts/{account_id}", headers=headers)

    def list_employer_accounts(self, headers, params=None):
        return self._request("GET", "/employer-accounts", headers=headers, params=params)

    def suspend_employer_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/employer-accounts/{account_id}/suspend", payload or {}, headers
        )

    def reactivate_employer_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/employer-accounts/{account_id}/reactivate", payload or {}, headers
        )

    # --- Bundle entitlements ---------------------------------------------------
    def create_bundle_entitlement(self, payload, headers):
        return self._request("POST", "/bundle-entitlements", payload, headers)

    def get_bundle_entitlement(self, bundle_id, headers):
        return self._request("GET", f"/bundle-entitlements/{bundle_id}", headers=headers)

    def list_bundle_entitlements(self, headers, params=None):
        return self._request("GET", "/bundle-entitlements", headers=headers, params=params)

    def activate_bundle_entitlement(self, bundle_id, headers, payload=None):
        return self._request(
            "POST", f"/bundle-entitlements/{bundle_id}/activate", payload or {}, headers
        )

    def reinstate_bundle_entitlement(self, bundle_id, headers, payload=None):
        return self._request(
            "POST", f"/bundle-entitlements/{bundle_id}/reinstate", payload or {}, headers
        )

    # --- Care advocates --------------------------------------------------------
    def create_care_advocate(self, payload, headers):
        return self._request("POST", "/care-advocates", payload, headers)

    def get_care_advocate(self, advocate_id, headers):
        return self._request("GET", f"/care-advocates/{advocate_id}", headers=headers)

    def list_care_advocates(self, headers, params=None):
        return self._request("GET", "/care-advocates", headers=headers, params=params)

    # --- Members ---------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def assign_advocate(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/members/{member_id}/assign-advocate", payload or {}, headers
        )

    def complete_intake(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/members/{member_id}/complete-intake", payload or {}, headers
        )

    def complete_care(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/members/{member_id}/complete-care", payload or {}, headers
        )

    def select_member_clinic(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/select-clinic", payload, headers)

    # --- Surrender routes ------------------------------------------------------
    def create_surrender_route(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/surrender-routes", payload, headers)

    def list_member_surrender_routes(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/surrender-routes", headers=headers, params=params
        )

    def list_surrender_routes(self, headers, params=None):
        return self._request("GET", "/surrender-routes", headers=headers, params=params)

    def get_surrender_route(self, route_id, headers):
        return self._request("GET", f"/surrender-routes/{route_id}", headers=headers)

    def withdraw_surrender_route(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/surrender-routes/withdraw", payload, headers
        )

    def retire_surrender_route(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/surrender-routes/retire", payload, headers
        )

    # --- Clinics ---------------------------------------------------------------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    def create_clinic_contract(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/contracts", payload, headers)

    def suspend_clinic(self, clinic_id, headers, payload=None):
        return self._request("POST", f"/clinics/{clinic_id}/suspend", payload or {}, headers)

    def terminate_clinic(self, clinic_id, headers, payload=None):
        return self._request("POST", f"/clinics/{clinic_id}/terminate", payload or {}, headers)

    def recompute_clinic_quality(self, clinic_id, headers, payload=None):
        return self._request(
            "POST", f"/clinics/{clinic_id}/quality-recompute", payload or {}, headers
        )

    def report_outcome(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/report-outcome", payload, headers)

    # --- Clinic contracts ------------------------------------------------------
    def get_clinic_contract(self, contract_id, headers):
        return self._request("GET", f"/clinic-contracts/{contract_id}", headers=headers)

    def list_clinic_contracts(self, headers, params=None):
        return self._request("GET", "/clinic-contracts", headers=headers, params=params)

    def activate_clinic_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/clinic-contracts/{contract_id}/activate", payload, headers)

    def terminate_clinic_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic-contracts/{contract_id}/terminate", payload or {}, headers
        )

    # --- Treatment plans -------------------------------------------------------
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def select_plan_clinic(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/select-clinic", payload, headers)

    def create_preauthorization(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/preauthorizations", payload, headers)

    def resubmit_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/resubmit-plan", payload, headers)

    def abandon_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/treatment-plans/{plan_id}/abandon", payload or {}, headers)

    # --- Preauthorizations -----------------------------------------------------
    def get_preauthorization(self, preauth_id, headers):
        return self._request("GET", f"/preauthorizations/{preauth_id}", headers=headers)

    def list_preauthorizations(self, headers, params=None):
        return self._request("GET", "/preauthorizations", headers=headers, params=params)

    def begin_clinical_review(self, preauth_id, headers, payload=None):
        return self._request(
            "POST", f"/preauthorizations/{preauth_id}/begin-clinical-review", payload or {}, headers
        )

    def decide_preauthorization(self, preauth_id, payload, headers):
        return self._request("POST", f"/preauthorizations/{preauth_id}/decide", payload, headers)

    def revise_preauthorization(self, preauth_id, payload, headers):
        return self._request(
            "POST", f"/preauthorizations/{preauth_id}/revise-request", payload, headers
        )

    # --- Treatment cycles ------------------------------------------------------
    def create_treatment_cycle(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/treatment-cycles", payload, headers)

    def get_treatment_cycle(self, cycle_id, headers):
        return self._request("GET", f"/treatment-cycles/{cycle_id}", headers=headers)

    def list_treatment_cycles(self, headers, params=None):
        return self._request("GET", "/treatment-cycles", headers=headers, params=params)

    def start_stimulation(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/treatment-cycles/{cycle_id}/start-stimulation", payload or {}, headers
        )

    def record_retrieval(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/treatment-cycles/{cycle_id}/record-retrieval", payload or {}, headers
        )

    def record_fertilization(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/treatment-cycles/{cycle_id}/record-fertilization", payload or {}, headers
        )

    def record_transfer(self, cycle_id, payload, headers):
        return self._request("POST", f"/treatment-cycles/{cycle_id}/record-transfer", payload, headers)

    def record_cycle_outcome(self, cycle_id, payload, headers):
        return self._request("POST", f"/treatment-cycles/{cycle_id}/record-outcome", payload, headers)

    def cancel_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/treatment-cycles/{cycle_id}/cancel", payload or {}, headers)

    # --- Medication orders -----------------------------------------------------
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/medication-orders", payload, headers)

    def get_medication_order(self, order_id, headers):
        return self._request("GET", f"/medication-orders/{order_id}", headers=headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/medication-orders", headers=headers, params=params)

    def dispense_medication_order(self, order_id, payload, headers):
        return self._request("POST", f"/medication-orders/{order_id}/dispense", payload, headers)

    def ship_medication_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/medication-orders/{order_id}/ship", payload or {}, headers
        )

    def deliver_medication_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/medication-orders/{order_id}/deliver", payload or {}, headers
        )

    def cancel_medication_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/medication-orders/{order_id}/cancel", payload or {}, headers
        )

    # --- Pathway requests ------------------------------------------------------
    def create_pathway_request(self, payload, headers):
        return self._request("POST", "/pathway-requests", payload, headers)

    def get_pathway_request(self, request_id, headers):
        return self._request("GET", f"/pathway-requests/{request_id}", headers=headers)

    def list_pathway_requests(self, headers, params=None):
        return self._request("GET", "/pathway-requests", headers=headers, params=params)

    def begin_pathway_review(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/pathway-requests/{request_id}/begin-clinical-review", payload or {}, headers
        )

    def decide_pathway_request(self, request_id, payload, headers):
        return self._request("POST", f"/pathway-requests/{request_id}/decide", payload, headers)

    def activate_pathway_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/pathway-requests/{request_id}/activate", payload or {}, headers
        )

    def complete_pathway_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/pathway-requests/{request_id}/complete", payload or {}, headers
        )

    def withdraw_pathway_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/pathway-requests/{request_id}/withdraw", payload or {}, headers
        )

    # --- Claims ----------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload or {}, headers)

    def deny_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/deny", payload or {}, headers)

    def pay_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", payload, headers)

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/appeal", payload or {}, headers)

    def decide_appeal(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/appeal-decide", payload or {}, headers)

    def reverse_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/reverse", payload or {}, headers)

    # --- Outcome records -------------------------------------------------------
    def get_outcome_record(self, record_id, headers):
        return self._request("GET", f"/outcome-records/{record_id}", headers=headers)

    def list_outcome_records(self, headers, params=None):
        return self._request("GET", "/outcome-records", headers=headers, params=params)

    def amend_outcome_record(self, record_id, payload, headers):
        return self._request("POST", f"/outcome-records/{record_id}/amend", payload, headers)

    def void_outcome_record(self, record_id, payload, headers):
        return self._request("POST", f"/outcome-records/{record_id}/void", payload, headers)


api_client = ApiClient()