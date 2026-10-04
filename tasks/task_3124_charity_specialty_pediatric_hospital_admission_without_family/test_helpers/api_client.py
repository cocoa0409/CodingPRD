"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/charity-care"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- SpecialtyHospital ---
    def create_hospital(self, payload, headers):
        return self._request("POST", f"{BASE}/hospitals", payload, headers)

    def list_hospitals(self, headers, params=None):
        return self._request("GET", f"{BASE}/hospitals", headers=headers, params=params)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"{BASE}/hospitals/{hospital_id}", headers=headers)

    def suspend_hospital(self, hospital_id, headers):
        return self._request("POST", f"{BASE}/hospitals/{hospital_id}/suspend", {}, headers)

    def reopen_hospital(self, hospital_id, headers):
        return self._request("POST", f"{BASE}/hospitals/{hospital_id}/reopen", {}, headers)

    def close_hospital(self, hospital_id, headers):
        return self._request("POST", f"{BASE}/hospitals/{hospital_id}/close", {}, headers)

    # --- SpecialtyProgram ---
    def create_program(self, hospital_id, payload, headers):
        return self._request("POST", f"{BASE}/hospitals/{hospital_id}/programs", payload, headers)

    def list_programs(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/hospitals/{hospital_id}/programs", headers=headers, params=params,
        )

    def get_program(self, program_id, headers):
        return self._request("GET", f"{BASE}/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"{BASE}/programs/{program_id}/suspend", {}, headers)

    def reactivate_program(self, program_id, headers):
        return self._request("POST", f"{BASE}/programs/{program_id}/reactivate", {}, headers)

    # --- ReferralSource ---
    def create_referral_source(self, payload, headers):
        return self._request("POST", f"{BASE}/referral-sources", payload, headers)

    def list_referral_sources(self, headers, params=None):
        return self._request("GET", f"{BASE}/referral-sources", headers=headers, params=params)

    def get_referral_source(self, source_id, headers):
        return self._request("GET", f"{BASE}/referral-sources/{source_id}", headers=headers)

    # --- PatientApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{BASE}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{BASE}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{BASE}/applications/{application_id}", headers=headers)

    def open_review(self, application_id, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/open-review", {}, headers)

    def request_info(self, application_id, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/request-info", {}, headers)

    def resubmit_info(self, application_id, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/resubmit-info", {}, headers)

    def cast_vote(self, application_id, payload, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/vote", payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/decide", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{BASE}/applications/{application_id}/withdraw", {}, headers)

    def list_reviews(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/reviews", headers=headers, params=params,
        )

    # --- InsurancePolicy ---
    def create_insurance_policy(self, application_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/insurance-policies", payload, headers,
        )

    def list_insurance_policies(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/insurance-policies",
            headers=headers, params=params,
        )

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"{BASE}/insurance-policies/{policy_id}", headers=headers)

    # --- BillingAccount / Claim ---
    def get_application_billing_account(self, application_id, headers):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/billing-account", headers=headers,
        )

    def list_billing_accounts(self, headers, params=None):
        return self._request("GET", f"{BASE}/billing-accounts", headers=headers, params=params)

    def get_billing_account(self, account_id, headers):
        return self._request("GET", f"{BASE}/billing-accounts/{account_id}", headers=headers)

    def create_claim(self, account_id, payload, headers):
        return self._request("POST", f"{BASE}/billing-accounts/{account_id}/claims", payload, headers)

    def list_claims(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/billing-accounts/{account_id}/claims", headers=headers, params=params,
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{BASE}/claims/{claim_id}", headers=headers)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/claims/{claim_id}/adjudicate", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/claims/{claim_id}/deny", {}, headers)

    def settle_billing_account(self, account_id, headers):
        return self._request("POST", f"{BASE}/billing-accounts/{account_id}/settle", {}, headers)

    # --- CarePlan / StagedProcedure ---
    def get_application_care_plan(self, application_id, headers):
        return self._request("GET", f"{BASE}/applications/{application_id}/care-plan", headers=headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"{BASE}/care-plans/{care_plan_id}", headers=headers)

    def discharge_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"{BASE}/care-plans/{care_plan_id}/discharge", {}, headers)

    def create_staged_procedure(self, care_plan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/care-plans/{care_plan_id}/staged-procedures", payload, headers,
        )

    def list_staged_procedures(self, care_plan_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/care-plans/{care_plan_id}/staged-procedures",
            headers=headers, params=params,
        )

    def get_staged_procedure(self, stage_id, headers):
        return self._request("GET", f"{BASE}/staged-procedures/{stage_id}", headers=headers)

    def schedule_stage(self, stage_id, headers):
        return self._request("POST", f"{BASE}/staged-procedures/{stage_id}/schedule", {}, headers)

    def complete_stage(self, stage_id, headers):
        return self._request("POST", f"{BASE}/staged-procedures/{stage_id}/complete", {}, headers)

    def defer_stage(self, stage_id, headers):
        return self._request("POST", f"{BASE}/staged-procedures/{stage_id}/defer", {}, headers)

    def replan_stage(self, stage_id, new_scheduled_date, headers):
        return self._request(
            "POST", f"{BASE}/staged-procedures/{stage_id}/replan",
            {"new_scheduled_date": new_scheduled_date}, headers,
        )

    def cancel_stage(self, stage_id, headers):
        return self._request("POST", f"{BASE}/staged-procedures/{stage_id}/cancel-stage", {}, headers)

    # --- TravelSupportGrant ---
    def create_travel_grant(self, application_id, grant_type, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/travel-support-grants",
            {"grant_type": grant_type}, headers,
        )

    def list_travel_grants(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/travel-support-grants",
            headers=headers, params=params,
        )

    def get_travel_grant(self, grant_id, headers):
        return self._request("GET", f"{BASE}/travel-support-grants/{grant_id}", headers=headers)

    # --- OutreachClinic / OutreachScreening ---
    def create_outreach_clinic(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/hospitals/{hospital_id}/outreach-clinics", payload, headers,
        )

    def list_outreach_clinics(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/hospitals/{hospital_id}/outreach-clinics", headers=headers, params=params,
        )

    def get_outreach_clinic(self, clinic_id, headers):
        return self._request("GET", f"{BASE}/outreach-clinics/{clinic_id}", headers=headers)

    def confirm_clinic(self, clinic_id, headers):
        return self._request("POST", f"{BASE}/outreach-clinics/{clinic_id}/confirm", {}, headers)

    def complete_clinic(self, clinic_id, headers):
        return self._request("POST", f"{BASE}/outreach-clinics/{clinic_id}/complete", {}, headers)

    def cancel_clinic(self, clinic_id, headers):
        return self._request("POST", f"{BASE}/outreach-clinics/{clinic_id}/cancel", {}, headers)

    def create_screening(self, clinic_id, payload, headers):
        return self._request("POST", f"{BASE}/outreach-clinics/{clinic_id}/screenings", payload, headers)

    def list_clinic_screenings(self, clinic_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/outreach-clinics/{clinic_id}/screenings", headers=headers, params=params,
        )

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{BASE}/outreach-screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{BASE}/outreach-screenings/{screening_id}", headers=headers)

    def record_screening_outcome(self, screening_id, headers):
        return self._request(
            "POST", f"{BASE}/outreach-screenings/{screening_id}/record-outcome", {}, headers,
        )

    def mark_screening_no_show(self, screening_id, headers):
        return self._request(
            "POST", f"{BASE}/outreach-screenings/{screening_id}/mark-no-show", {}, headers,
        )

    def rebook_screening(self, screening_id, new_screening_date, headers):
        return self._request(
            "POST", f"{BASE}/outreach-screenings/{screening_id}/rebook",
            {"new_screening_date": new_screening_date}, headers,
        )

    # --- PhilanthropicFund / FundAllocation ---
    def create_fund(self, payload, headers):
        return self._request("POST", f"{BASE}/philanthropic-funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", f"{BASE}/philanthropic-funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"{BASE}/philanthropic-funds/{fund_id}", headers=headers)

    def lock_fund(self, fund_id, headers):
        return self._request("POST", f"{BASE}/philanthropic-funds/{fund_id}/lock", {}, headers)

    def unlock_fund(self, fund_id, headers):
        return self._request("POST", f"{BASE}/philanthropic-funds/{fund_id}/unlock", {}, headers)

    def close_fund(self, fund_id, headers):
        return self._request("POST", f"{BASE}/philanthropic-funds/{fund_id}/close", {}, headers)

    def create_allocation(self, fund_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/philanthropic-funds/{fund_id}/allocations", payload, headers,
        )

    def list_fund_allocations(self, fund_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/philanthropic-funds/{fund_id}/allocations", headers=headers, params=params,
        )

    def list_allocations(self, headers, params=None):
        return self._request("GET", f"{BASE}/fund-allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"{BASE}/fund-allocations/{allocation_id}", headers=headers)

    def commit_allocation(self, allocation_id, expected_fund_version, headers):
        return self._request(
            "POST", f"{BASE}/fund-allocations/{allocation_id}/commit",
            {"expected_fund_version": expected_fund_version}, headers,
        )

    def withdraw_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"{BASE}/fund-allocations/{allocation_id}/withdraw", {}, headers,
        )

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"{BASE}/fund-allocations/{allocation_id}/release", {}, headers,
        )


api_client = ApiClient()
