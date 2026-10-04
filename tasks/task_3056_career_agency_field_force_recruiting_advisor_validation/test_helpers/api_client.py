"""API client: one method per endpoint of the Career Agency Field Force API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- DistrictOffice ----------------------------------------------------
    def create_district_office(self, payload, headers):
        return self._request("POST", "/agency/district-offices", payload, headers)

    def list_district_offices(self, headers, params=None):
        return self._request("GET", "/agency/district-offices", headers=headers, params=params)

    def get_district_office(self, office_id, headers):
        return self._request("GET", f"/agency/district-offices/{office_id}", headers=headers)

    def suspend_district_office(self, office_id, headers):
        return self._request("POST", f"/agency/district-offices/{office_id}/suspend", {}, headers)

    def reactivate_district_office(self, office_id, headers):
        return self._request("POST", f"/agency/district-offices/{office_id}/reactivate", {}, headers)

    def close_district_office(self, office_id, headers):
        return self._request("POST", f"/agency/district-offices/{office_id}/close", {}, headers)

    def list_office_advisors(self, office_id, headers, params=None):
        return self._request("GET", f"/agency/district-offices/{office_id}/advisors",
                             headers=headers, params=params)

    def list_office_candidates(self, office_id, headers, params=None):
        return self._request("GET", f"/agency/district-offices/{office_id}/recruiting-candidates",
                             headers=headers, params=params)

    # --- Advisor -----------------------------------------------------------
    def create_advisor(self, payload, headers):
        return self._request("POST", "/agency/advisors", payload, headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/agency/advisors", headers=headers, params=params)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/agency/advisors/{advisor_id}", headers=headers)

    def terminate_advisor(self, advisor_id, headers):
        return self._request("POST", f"/agency/advisors/{advisor_id}/terminate", {}, headers)

    def remediate_advisor(self, advisor_id, headers):
        return self._request("POST", f"/agency/advisors/{advisor_id}/remediate", {}, headers)

    def lock_licensing_remediation(self, advisor_id, headers):
        return self._request("POST", f"/agency/advisors/{advisor_id}/licensing/lock-remediation",
                             {}, headers)

    def unlock_licensing_remediation(self, advisor_id, headers):
        return self._request("POST", f"/agency/advisors/{advisor_id}/licensing/unlock-remediation",
                             {}, headers)

    def list_downline(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/downline",
                             headers=headers, params=params)

    def list_advisor_product_licenses(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/product-licenses",
                             headers=headers, params=params)

    def list_advisor_securities_registrations(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/securities-registrations",
                             headers=headers, params=params)

    def list_advisor_carrier_appointments(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/carrier-appointments",
                             headers=headers, params=params)

    def list_advisor_employment_contracts(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/employment-contracts",
                             headers=headers, params=params)

    def list_advisor_validation_periods(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/validation-periods",
                             headers=headers, params=params)

    def list_advisor_persistency_records(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/persistency-records",
                             headers=headers, params=params)

    def list_advisor_commission_credits(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/commission-credits",
                             headers=headers, params=params)

    def list_advisor_joint_work_cases(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/joint-work-cases",
                             headers=headers, params=params)

    def list_advisor_orphan_assignments(self, advisor_id, headers, params=None):
        return self._request("GET", f"/agency/advisors/{advisor_id}/orphan-policy-assignments",
                             headers=headers, params=params)

    # --- RecruitingCandidate ----------------------------------------------
    def create_candidate(self, payload, headers):
        return self._request("POST", "/agency/recruiting-candidates", payload, headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/agency/recruiting-candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/agency/recruiting-candidates/{candidate_id}", headers=headers)

    def screen_candidate(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/screen",
                             {}, headers)

    def schedule_assessment(self, candidate_id, payload, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/schedule-assessment",
                             payload, headers)

    def advance_to_interview(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/advance-to-interview",
                             {}, headers)

    def extend_offer(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/extend-offer",
                             {}, headers)

    def accept_offer(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/accept-offer",
                             {}, headers)

    def decline_offer(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/decline-offer",
                             {}, headers)

    def reengage_candidate(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/reengage",
                             {}, headers)

    def reject_candidate(self, candidate_id, headers):
        return self._request("POST", f"/agency/recruiting-candidates/{candidate_id}/reject",
                             {}, headers)

    def list_candidate_assessments(self, candidate_id, headers, params=None):
        return self._request("GET", f"/agency/recruiting-candidates/{candidate_id}/selection-assessments",
                             headers=headers, params=params)

    def list_candidate_reengagements(self, candidate_id, headers, params=None):
        return self._request("GET", f"/agency/recruiting-candidates/{candidate_id}/reengagements",
                             headers=headers, params=params)

    def list_candidate_employment_contracts(self, candidate_id, headers, params=None):
        return self._request("GET", f"/agency/recruiting-candidates/{candidate_id}/employment-contracts",
                             headers=headers, params=params)

    # --- SelectionAssessment ----------------------------------------------
    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/agency/selection-assessments/{assessment_id}", headers=headers)

    def score_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/agency/selection-assessments/{assessment_id}/score",
                             payload, headers)

    def supersede_assessment(self, assessment_id, headers):
        return self._request("POST", f"/agency/selection-assessments/{assessment_id}/supersede",
                             {}, headers)

    def invalidate_assessment(self, assessment_id, headers):
        return self._request("POST", f"/agency/selection-assessments/{assessment_id}/invalidate",
                             {}, headers)

    # --- EmploymentContract ------------------------------------------------
    def create_employment_contract(self, payload, headers):
        return self._request("POST", "/agency/employment-contracts", payload, headers)

    def list_employment_contracts(self, headers, params=None):
        return self._request("GET", "/agency/employment-contracts", headers=headers, params=params)

    def get_employment_contract(self, contract_id, headers):
        return self._request("GET", f"/agency/employment-contracts/{contract_id}", headers=headers)

    def list_contract_validation_periods(self, contract_id, headers, params=None):
        return self._request("GET", f"/agency/employment-contracts/{contract_id}/validation-periods",
                             headers=headers, params=params)

    def draw_training_allowance(self, contract_id, headers):
        return self._request("POST", "/agency/training-allowance-draws",
                             {"contract_id": contract_id}, headers)

    # --- ValidationPeriod --------------------------------------------------
    def open_validation_period(self, payload, headers):
        return self._request("POST", "/agency/validation-periods", payload, headers)

    def get_validation_period(self, period_id, headers):
        return self._request("GET", f"/agency/validation-periods/{period_id}", headers=headers)

    def evaluate_validation_period(self, period_id, headers):
        return self._request("POST", f"/agency/validation-periods/{period_id}/evaluate", {}, headers)

    def extend_validation_period(self, period_id, new_end_date, headers):
        return self._request("POST", f"/agency/validation-periods/{period_id}/extend",
                             {"new_end_date": new_end_date}, headers)

    # --- ProductLicense ----------------------------------------------------
    def create_product_license(self, payload, headers):
        return self._request("POST", "/agency/product-licenses", payload, headers)

    def get_product_license(self, license_id, headers):
        return self._request("GET", f"/agency/product-licenses/{license_id}", headers=headers)

    def activate_product_license(self, license_id, headers):
        return self._request("POST", f"/agency/product-licenses/{license_id}/activate", {}, headers)

    def renew_product_license(self, license_id, expires_at, headers):
        return self._request("POST", f"/agency/product-licenses/{license_id}/renew",
                             {"expires_at": expires_at}, headers)

    def list_license_carrier_appointments(self, license_id, headers, params=None):
        return self._request("GET", f"/agency/product-licenses/{license_id}/carrier-appointments",
                             headers=headers, params=params)

    # --- SecuritiesRegistration -------------------------------------------
    def create_securities_registration(self, payload, headers):
        return self._request("POST", "/agency/securities-registrations", payload, headers)

    def list_securities_registrations(self, headers, params=None):
        return self._request("GET", "/agency/securities-registrations", headers=headers, params=params)

    def get_securities_registration(self, registration_id, headers):
        return self._request("GET", f"/agency/securities-registrations/{registration_id}",
                             headers=headers)

    def activate_securities_registration(self, registration_id, headers):
        return self._request("POST", f"/agency/securities-registrations/{registration_id}/activate",
                             {}, headers)

    def list_registration_dependents(self, registration_id, headers, params=None):
        return self._request("GET", f"/agency/securities-registrations/{registration_id}/dependents",
                             headers=headers, params=params)

    # --- CarrierAppointment ------------------------------------------------
    def create_carrier_appointment(self, payload, headers):
        return self._request("POST", "/agency/carrier-appointments", payload, headers)

    def get_carrier_appointment(self, appointment_id, headers):
        return self._request("GET", f"/agency/carrier-appointments/{appointment_id}", headers=headers)

    def approve_carrier_appointment(self, appointment_id, headers):
        return self._request("POST", f"/agency/carrier-appointments/{appointment_id}/approve",
                             {}, headers)

    def reject_carrier_appointment(self, appointment_id, headers):
        return self._request("POST", f"/agency/carrier-appointments/{appointment_id}/reject",
                             {}, headers)

    # --- Policy ------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/agency/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/agency/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/agency/policies/{policy_id}", headers=headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/activate", {}, headers)

    def lapse_policy(self, policy_id, lapse_date, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/lapse",
                             {"lapse_date": lapse_date}, headers)

    def reinstate_policy(self, policy_id, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/reinstate", {}, headers)

    def surrender_policy(self, policy_id, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/surrender", {}, headers)

    def terminate_policy(self, policy_id, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/terminate", {}, headers)

    def list_policy_joint_work_cases(self, policy_id, headers, params=None):
        return self._request("GET", f"/agency/policies/{policy_id}/joint-work-cases",
                             headers=headers, params=params)

    def list_policy_commission_credits(self, policy_id, headers, params=None):
        return self._request("GET", f"/agency/policies/{policy_id}/commission-credits",
                             headers=headers, params=params)

    def list_policy_orphan_assignments(self, policy_id, headers, params=None):
        return self._request("GET", f"/agency/policies/{policy_id}/orphan-policy-assignments",
                             headers=headers, params=params)

    # --- JointWorkCase -----------------------------------------------------
    def create_joint_work_case(self, payload, headers):
        return self._request("POST", "/agency/joint-work-cases", payload, headers)

    def get_joint_work_case(self, case_id, headers):
        return self._request("GET", f"/agency/joint-work-cases/{case_id}", headers=headers)

    def submit_joint_work_case(self, case_id, headers):
        return self._request("POST", f"/agency/joint-work-cases/{case_id}/submit", {}, headers)

    def close_joint_work_case(self, case_id, headers):
        return self._request("POST", f"/agency/joint-work-cases/{case_id}/close", {}, headers)

    def void_joint_work_case(self, case_id, headers):
        return self._request("POST", f"/agency/joint-work-cases/{case_id}/void", {}, headers)

    def reopen_joint_work_case(self, case_id, headers):
        return self._request("POST", f"/agency/joint-work-cases/{case_id}/reopen", {}, headers)

    # --- CommissionCredit --------------------------------------------------
    def get_commission_credit(self, credit_id, headers):
        return self._request("GET", f"/agency/commission-credits/{credit_id}", headers=headers)

    def pay_commission_credit(self, credit_id, headers):
        return self._request("POST", f"/agency/commission-credits/{credit_id}/pay", {}, headers)

    def void_commission_credit(self, credit_id, headers):
        return self._request("POST", f"/agency/commission-credits/{credit_id}/void", {}, headers)

    def recover_commission_credit(self, credit_id, amount_cents, headers):
        return self._request("POST", f"/agency/commission-credits/{credit_id}/recover",
                             {"amount_cents": amount_cents}, headers)

    # --- PersistencyRecord -------------------------------------------------
    def create_persistency_record(self, payload, headers):
        return self._request("POST", "/agency/persistency-records", payload, headers)

    def get_persistency_record(self, record_id, headers):
        return self._request("GET", f"/agency/persistency-records/{record_id}", headers=headers)

    def dispute_persistency_record(self, record_id, headers):
        return self._request("POST", f"/agency/persistency-records/{record_id}/dispute", {}, headers)

    def resolve_persistency_dispute(self, record_id, headers):
        return self._request("POST", f"/agency/persistency-records/{record_id}/resolve-dispute",
                             {}, headers)

    def finalize_persistency_record(self, record_id, headers):
        return self._request("POST", f"/agency/persistency-records/{record_id}/finalize", {}, headers)

    # --- OrphanPolicyAssignment -------------------------------------------
    def get_orphan_assignment(self, assignment_id, headers):
        return self._request("GET", f"/agency/orphan-policy-assignments/{assignment_id}",
                             headers=headers)

    def assign_orphan_policy(self, assignment_id, headers):
        return self._request("POST", f"/agency/orphan-policy-assignments/{assignment_id}/assign",
                             {}, headers)

    def reopen_orphan_assignment(self, assignment_id, headers):
        return self._request("POST", f"/agency/orphan-policy-assignments/{assignment_id}/reopen",
                             {}, headers)


api_client = ApiClient()