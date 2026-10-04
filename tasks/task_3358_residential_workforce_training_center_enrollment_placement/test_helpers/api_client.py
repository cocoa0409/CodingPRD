"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (PRD section 2.4) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Applicants / applications (PRD section 3.1) ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/jc/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/jc/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/jc/applicants/{applicant_id}", headers=headers)

    def create_application(self, payload, headers):
        return self._request("POST", "/jc/applications", payload, headers)

    def list_applications(self, applicant_id, headers):
        return self._request(
            "GET", f"/jc/applicants/{applicant_id}/applications", headers=headers
        )

    def transition_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/jc/applications/{application_id}/transition", payload, headers
        )

    def assign_center(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"/jc/applicants/{applicant_id}/center-assignment", payload, headers
        )

    # ---- Centers / trade programs (PRD section 3.2) ----
    def create_center(self, payload, headers):
        return self._request("POST", "/jc/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/jc/centers/{center_id}", headers=headers)

    def list_center_operator_contracts(self, center_id, headers):
        return self._request(
            "GET", f"/jc/centers/{center_id}/operator-contracts", headers=headers
        )

    def create_trade_program(self, payload, headers):
        return self._request("POST", "/jc/trade-programs", payload, headers)

    def list_center_trade_programs(self, center_id, headers):
        return self._request(
            "GET", f"/jc/centers/{center_id}/trade-programs", headers=headers
        )

    def patch_trade_program(self, program_id, payload, headers):
        return self._request(
            "PATCH", f"/jc/trade-programs/{program_id}", payload, headers
        )

    # ---- Enrollments (PRD section 3.3) ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/jc/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/jc/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/jc/enrollments/{enrollment_id}", headers=headers)

    def transition_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/jc/enrollments/{enrollment_id}/transition", payload, headers
        )

    # ---- Dormitory assignments (PRD section 3.4) ----
    def create_dormitory_assignment(self, payload, headers):
        return self._request("POST", "/jc/dormitory-assignments", payload, headers)

    def list_dormitory_assignments(self, enrollment_id, headers):
        return self._request(
            "GET", f"/jc/enrollments/{enrollment_id}/dormitory-assignments",
            headers=headers,
        )

    def checkout_dormitory_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/jc/dormitory-assignments/{assignment_id}/checkout",
            payload, headers,
        )

    # ---- Conduct incidents (PRD section 3.4) ----
    def create_conduct_incident(self, payload, headers):
        return self._request("POST", "/jc/conduct-incidents", payload, headers)

    def list_conduct_incidents(self, enrollment_id, headers):
        return self._request(
            "GET", f"/jc/enrollments/{enrollment_id}/conduct-incidents", headers=headers
        )

    def transition_conduct_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/jc/conduct-incidents/{incident_id}/transition", payload, headers
        )

    # ---- Credentials (PRD section 3.5) ----
    def create_credential(self, payload, headers):
        return self._request("POST", "/jc/credentials", payload, headers)

    def list_credentials(self, enrollment_id, headers):
        return self._request(
            "GET", f"/jc/enrollments/{enrollment_id}/credentials", headers=headers
        )

    def transition_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/jc/credentials/{credential_id}/transition", payload, headers
        )

    # ---- Employer agreements (PRD section 3.6) ----
    def create_employer_agreement(self, payload, headers):
        return self._request("POST", "/jc/employer-agreements", payload, headers)

    def get_employer_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/jc/employer-agreements/{agreement_id}", headers=headers
        )

    def list_agreement_wbl_placements(self, agreement_id, headers):
        return self._request(
            "GET", f"/jc/employer-agreements/{agreement_id}/wbl-placements",
            headers=headers,
        )

    # ---- WBL placements (PRD section 3.6) ----
    def create_wbl_placement(self, payload, headers):
        return self._request("POST", "/jc/wbl-placements", payload, headers)

    def list_enrollment_wbl_placements(self, enrollment_id, headers):
        return self._request(
            "GET", f"/jc/enrollments/{enrollment_id}/wbl-placements", headers=headers
        )

    def transition_wbl_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/jc/wbl-placements/{placement_id}/transition", payload, headers
        )

    # ---- Transition plans (PRD section 3.7) ----
    def get_transition_plan(self, enrollment_id, headers):
        return self._request(
            "GET", f"/jc/enrollments/{enrollment_id}/transition-plan", headers=headers
        )

    def record_transition_service(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/jc/transition-plans/{plan_id}/services", payload, headers
        )

    # ---- Operator contracts / performance (PRD section 3.8) ----
    def create_operator_contract(self, payload, headers):
        return self._request("POST", "/jc/operator-contracts", payload, headers)

    def get_operator_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/jc/operator-contracts/{contract_id}", headers=headers
        )

    def transition_operator_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/jc/operator-contracts/{contract_id}/transition",
            payload, headers,
        )

    def get_performance_preview(self, contract_id, headers):
        return self._request(
            "GET", f"/jc/operator-contracts/{contract_id}/performance-preview",
            headers=headers,
        )

    def close_period(self, contract_id, headers):
        return self._request(
            "POST", f"/jc/operator-contracts/{contract_id}/close-period", None, headers
        )

    def list_performance_snapshots(self, contract_id, headers):
        return self._request(
            "GET", f"/jc/operator-contracts/{contract_id}/performance-snapshots",
            headers=headers,
        )


api_client = ApiClient()
