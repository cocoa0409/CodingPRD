"""API client: one method per endpoint in the PRD §4 endpoint table.

All business endpoints are mounted under /leasing; the logical-clock endpoint
is mounted at the root, outside the prefix (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock (root-mounted, outside /leasing) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/leasing/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/leasing/agencies/{agency_id}", headers=headers)

    # --- Building ---
    def create_building(self, payload, headers):
        return self._request("POST", "/leasing/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/leasing/buildings/{building_id}", headers=headers)

    # --- SpaceRequirement ---
    def create_space_requirement(self, payload, headers):
        return self._request("POST", "/leasing/space-requirements", payload, headers)

    def get_space_requirement(self, requirement_id, headers):
        return self._request("GET", f"/leasing/space-requirements/{requirement_id}",
                             headers=headers)

    def list_space_requirements(self, headers, params=None):
        return self._request("GET", "/leasing/space-requirements",
                             headers=headers, params=params)

    def submit_requirement(self, requirement_id, headers):
        return self._request("POST", f"/leasing/space-requirements/{requirement_id}/submit",
                             headers=headers)

    def return_requirement(self, requirement_id, headers):
        return self._request("POST", f"/leasing/space-requirements/{requirement_id}/return",
                             headers=headers)

    def resubmit_requirement(self, requirement_id, headers):
        return self._request("POST", f"/leasing/space-requirements/{requirement_id}/resubmit",
                             headers=headers)

    def validate_requirement(self, requirement_id, headers):
        return self._request("POST", f"/leasing/space-requirements/{requirement_id}/validate",
                             headers=headers)

    def complete_market_survey(self, requirement_id, payload, headers):
        return self._request("POST",
                             f"/leasing/space-requirements/{requirement_id}/complete-market-survey",
                             payload, headers)

    # --- LeaseOffer ---
    def create_offer(self, requirement_id, payload, headers):
        return self._request("POST", f"/leasing/space-requirements/{requirement_id}/offers",
                             payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/leasing/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/leasing/offers", headers=headers, params=params)

    def evaluate_offer(self, offer_id, headers):
        return self._request("POST", f"/leasing/offers/{offer_id}/evaluate", headers=headers)

    def select_offer(self, offer_id, headers):
        return self._request("POST", f"/leasing/offers/{offer_id}/select", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/leasing/offers/{offer_id}/withdraw", headers=headers)

    # --- Lease ---
    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leasing/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leasing/leases", headers=headers, params=params)

    def commence_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/commence",
                             payload, headers)

    def create_tax_statement(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/tax-statements",
                             payload, headers)

    # --- ExpirationPlan ---
    def create_expiration_plan(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/expiration-plans",
                             headers=headers)

    def list_expiration_plans(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/expiration-plans",
                             headers=headers, params=params)

    def select_plan_option(self, plan_id, payload, headers):
        return self._request("POST", f"/leasing/expiration-plans/{plan_id}/select-option",
                             payload, headers)

    def execute_plan(self, plan_id, headers):
        return self._request("POST", f"/leasing/expiration-plans/{plan_id}/execute",
                             headers=headers)

    # --- OccupancyAgreement ---
    def create_oa(self, payload, headers):
        return self._request("POST", "/leasing/occupancy-agreements", payload, headers)

    def get_oa(self, oa_id, headers):
        return self._request("GET", f"/leasing/occupancy-agreements/{oa_id}",
                             headers=headers)

    def list_oas(self, headers, params=None):
        return self._request("GET", "/leasing/occupancy-agreements",
                             headers=headers, params=params)

    def activate_oa(self, oa_id, headers):
        return self._request("POST", f"/leasing/occupancy-agreements/{oa_id}/activate",
                             headers=headers)

    def terminate_oa(self, oa_id, headers):
        return self._request("POST", f"/leasing/occupancy-agreements/{oa_id}/terminate",
                             headers=headers)

    def amend_oa(self, oa_id, payload, headers):
        return self._request("POST", f"/leasing/occupancy-agreements/{oa_id}/amend",
                             payload, headers)

    def generate_bill(self, oa_id, payload, headers):
        return self._request("POST", f"/leasing/occupancy-agreements/{oa_id}/bills",
                             payload, headers)

    def list_bills(self, oa_id, headers, params=None):
        return self._request("GET", f"/leasing/occupancy-agreements/{oa_id}/bills",
                             headers=headers, params=params)

    # --- RentBill ---
    def pay_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/leasing/rent-bills/{bill_id}/pay",
                             payload, headers)

    # --- AlterationRequest ---
    def create_alteration(self, oa_id, payload, headers):
        return self._request("POST",
                             f"/leasing/occupancy-agreements/{oa_id}/alteration-requests",
                             payload, headers)

    def list_alterations(self, oa_id, headers, params=None):
        return self._request("GET",
                             f"/leasing/occupancy-agreements/{oa_id}/alteration-requests",
                             headers=headers, params=params)

    def estimate_alteration(self, alteration_id, payload, headers):
        return self._request("POST", f"/leasing/alteration-requests/{alteration_id}/estimate",
                             payload, headers)

    def approve_alteration(self, alteration_id, payload, headers):
        return self._request("POST", f"/leasing/alteration-requests/{alteration_id}/approve",
                             payload, headers)

    def revise_alteration(self, alteration_id, payload, headers):
        return self._request("POST", f"/leasing/alteration-requests/{alteration_id}/revise",
                             payload, headers)

    def complete_alteration(self, alteration_id, payload, headers):
        return self._request("POST", f"/leasing/alteration-requests/{alteration_id}/complete",
                             payload, headers)

    def cancel_alteration(self, alteration_id, headers):
        return self._request("POST", f"/leasing/alteration-requests/{alteration_id}/cancel",
                             headers=headers)

    # --- ServiceTicket ---
    def create_service_ticket(self, building_id, payload, headers):
        return self._request("POST", f"/leasing/buildings/{building_id}/service-tickets",
                             payload, headers)

    def list_service_tickets(self, building_id, headers, params=None):
        return self._request("GET", f"/leasing/buildings/{building_id}/service-tickets",
                             headers=headers, params=params)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/leasing/service-tickets/{ticket_id}/resolve",
                             headers=headers)

    def verify_ticket(self, ticket_id, headers):
        return self._request("POST", f"/leasing/service-tickets/{ticket_id}/verify",
                             headers=headers)

    # --- UtilizationSurvey ---
    def create_survey(self, oa_id, payload, headers):
        return self._request("POST",
                             f"/leasing/occupancy-agreements/{oa_id}/utilization-surveys",
                             payload, headers)

    def list_surveys(self, oa_id, headers, params=None):
        return self._request("GET",
                             f"/leasing/occupancy-agreements/{oa_id}/utilization-surveys",
                             headers=headers, params=params)

    def finalize_survey(self, survey_id, headers):
        return self._request("POST", f"/leasing/utilization-surveys/{survey_id}/finalize",
                             headers=headers)

    # --- SpaceReductionAction ---
    def list_reduction_actions(self, oa_id, headers, params=None):
        return self._request("GET",
                             f"/leasing/occupancy-agreements/{oa_id}/space-reduction-actions",
                             headers=headers, params=params)

    def approve_reduction(self, action_id, headers):
        return self._request("POST", f"/leasing/space-reduction-actions/{action_id}/approve",
                             headers=headers)

    def execute_reduction(self, action_id, headers):
        return self._request("POST", f"/leasing/space-reduction-actions/{action_id}/execute",
                             headers=headers)


api_client = ApiClient()
