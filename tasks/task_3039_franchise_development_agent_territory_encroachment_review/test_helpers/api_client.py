"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform / test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Territory ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/territories", headers=headers, params=params)

    def assign_agent(self, territory_id, payload, headers):
        return self._request("POST", f"/territories/{territory_id}/assign-agent", payload, headers)

    def initiate_reassignment(self, territory_id, headers):
        return self._request("POST", f"/territories/{territory_id}/initiate-reassignment", {}, headers)

    def list_territory_stores(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}/stores", headers=headers)

    def list_territory_site_applications(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}/site-applications", headers=headers)

    def list_territory_fee_statements(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}/fee-statements", headers=headers)

    # --- DevelopmentAgent ---
    def create_development_agent(self, payload, headers):
        return self._request("POST", "/development-agents", payload, headers)

    def get_development_agent(self, agent_id, headers):
        return self._request("GET", f"/development-agents/{agent_id}", headers=headers)

    def flag_underperformance(self, agent_id, headers):
        return self._request("POST", f"/development-agents/{agent_id}/flag-underperformance", {}, headers)

    def clear_review(self, agent_id, headers):
        return self._request("POST", f"/development-agents/{agent_id}/clear-review", {}, headers)

    def terminate_agent(self, agent_id, headers):
        return self._request("POST", f"/development-agents/{agent_id}/terminate", {}, headers)

    def list_agent_territories(self, agent_id, headers):
        return self._request("GET", f"/development-agents/{agent_id}/territories", headers=headers)

    def list_agent_fee_statements(self, agent_id, headers):
        return self._request("GET", f"/development-agents/{agent_id}/fee-statements", headers=headers)

    # --- Franchisee ---
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/franchisees", payload, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}", headers=headers)

    def list_franchisee_stores(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}/stores", headers=headers)

    def list_franchisee_training_enrollments(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}/training-enrollments", headers=headers)

    def list_franchisee_transfer_requests(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}/transfer-requests", headers=headers)

    def list_franchisee_site_applications(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}/site-applications", headers=headers)

    def list_franchisee_promotion_votes(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}/promotion-votes", headers=headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def open_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/open", {}, headers)

    def terminate_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/terminate", {}, headers)

    def list_store_site_applications(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/site-applications", headers=headers)

    def list_store_protests(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/protests", headers=headers)

    def list_store_transfer_requests(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/transfer-requests", headers=headers)

    def list_store_remodel_mandates(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/remodel-mandates", headers=headers)

    def list_store_inspections(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/inspections", headers=headers)

    def list_store_promotion_votes(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/promotion-votes", headers=headers)

    def list_store_funding_disputes(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/funding-disputes", headers=headers)

    # --- SiteApplication / ImpactStudy ---
    def create_site_application(self, payload, headers):
        return self._request("POST", "/site-applications", payload, headers)

    def get_site_application(self, application_id, headers):
        return self._request("GET", f"/site-applications/{application_id}", headers=headers)

    def submit_site_application(self, application_id, headers):
        return self._request("POST", f"/site-applications/{application_id}/submit", {}, headers)

    def request_revision(self, application_id, payload, headers):
        return self._request("POST", f"/site-applications/{application_id}/request-revision", payload, headers)

    def approve_site_application(self, application_id, headers):
        return self._request("POST", f"/site-applications/{application_id}/approve", {}, headers)

    def reject_site_application(self, application_id, payload, headers):
        return self._request("POST", f"/site-applications/{application_id}/reject", payload, headers)

    def withdraw_site_application(self, application_id, headers):
        return self._request("POST", f"/site-applications/{application_id}/withdraw", {}, headers)

    def list_application_stores(self, application_id, headers):
        return self._request("GET", f"/site-applications/{application_id}/stores", headers=headers)

    def list_application_protests(self, application_id, headers):
        return self._request("GET", f"/site-applications/{application_id}/protests", headers=headers)

    def create_impact_study(self, application_id, payload, headers):
        return self._request("POST", f"/site-applications/{application_id}/impact-studies", payload, headers)

    def list_application_impact_studies(self, application_id, headers):
        return self._request("GET", f"/site-applications/{application_id}/impact-studies", headers=headers)

    def get_impact_study(self, study_id, headers):
        return self._request("GET", f"/impact-studies/{study_id}", headers=headers)

    def finalize_impact_study(self, study_id, headers):
        return self._request("POST", f"/impact-studies/{study_id}/finalize", {}, headers)

    # --- Protest ---
    def create_protest(self, payload, headers):
        return self._request("POST", "/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", "/protests", headers=headers, params=params)

    def begin_protest_review(self, protest_id, headers):
        return self._request("POST", f"/protests/{protest_id}/begin-review", {}, headers)

    def send_protest_to_mediation(self, protest_id, payload, headers):
        return self._request("POST", f"/protests/{protest_id}/send-to-mediation", payload, headers)

    def record_mediation_outcome(self, protest_id, payload, headers):
        return self._request("POST", f"/protests/{protest_id}/record-mediation-outcome", payload, headers)

    def resolve_protest(self, protest_id, payload, headers):
        return self._request("POST", f"/protests/{protest_id}/resolve", payload, headers)

    def escalate_protest(self, protest_id, headers):
        return self._request("POST", f"/protests/{protest_id}/escalate", {}, headers)

    # --- TransferRequest ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def advance_transfer_to_training(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/advance-to-training", {}, headers)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/approve", {}, headers)

    def reject_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/reject", payload, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/complete", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/cancel", {}, headers)

    # --- TrainingEnrollment ---
    def create_training_enrollment(self, payload, headers):
        return self._request("POST", "/training-enrollments", payload, headers)

    def get_training_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/training-enrollments/{enrollment_id}", headers=headers)

    def record_training_result(self, enrollment_id, payload, headers):
        return self._request("POST", f"/training-enrollments/{enrollment_id}/record-result", payload, headers)

    # --- RemodelMandate ---
    def create_remodel_mandate(self, payload, headers):
        return self._request("POST", "/remodel-mandates", payload, headers)

    def get_remodel_mandate(self, mandate_id, headers):
        return self._request("GET", f"/remodel-mandates/{mandate_id}", headers=headers)

    def schedule_remodel_mandate(self, mandate_id, payload, headers):
        return self._request("POST", f"/remodel-mandates/{mandate_id}/schedule", payload, headers)

    def begin_remodel_mandate(self, mandate_id, headers):
        return self._request("POST", f"/remodel-mandates/{mandate_id}/begin", {}, headers)

    def complete_remodel_mandate(self, mandate_id, headers):
        return self._request("POST", f"/remodel-mandates/{mandate_id}/complete", {}, headers)

    def waive_remodel_mandate(self, mandate_id, headers):
        return self._request("POST", f"/remodel-mandates/{mandate_id}/waive", {}, headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def record_inspection_findings(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/record-findings", payload, headers)

    def finalize_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/finalize", {}, headers)

    # --- Promotion / Vote ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def open_promotion_voting(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/open-voting", {}, headers)

    def close_promotion_voting(self, promotion_id, payload=None, headers=None):
        return self._request("POST", f"/promotions/{promotion_id}/close-voting", payload or {}, headers)

    def activate_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/activate", {}, headers)

    def close_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/close", {}, headers)

    def list_promotion_votes(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}/votes", headers=headers)

    def list_promotion_funding_disputes(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}/funding-disputes", headers=headers)

    def cast_vote(self, promotion_id, payload, headers):
        return self._request("POST", f"/promotions/{promotion_id}/votes", payload, headers)

    def get_promotion_vote(self, vote_id, headers):
        return self._request("GET", f"/promotion-votes/{vote_id}", headers=headers)

    def retract_vote(self, vote_id, headers):
        return self._request("POST", f"/promotion-votes/{vote_id}/retract", {}, headers)

    # --- FundingDispute ---
    def create_funding_dispute(self, payload, headers):
        return self._request("POST", "/funding-disputes", payload, headers)

    def get_funding_dispute(self, dispute_id, headers):
        return self._request("GET", f"/funding-disputes/{dispute_id}", headers=headers)

    def resolve_funding_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/funding-disputes/{dispute_id}/resolve", payload, headers)

    # --- FeeStatement ---
    def generate_fee_statement(self, payload, headers):
        return self._request("POST", "/fee-statements/generate", payload, headers)

    def get_fee_statement(self, statement_id, headers):
        return self._request("GET", f"/fee-statements/{statement_id}", headers=headers)

    def finalize_fee_statement(self, statement_id, headers):
        return self._request("POST", f"/fee-statements/{statement_id}/finalize", {}, headers)

    def settle_fee_statement(self, statement_id, headers):
        return self._request("POST", f"/fee-statements/{statement_id}/settle", {}, headers)


api_client = ApiClient()
