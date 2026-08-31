"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Engagement -----
    def create_engagement(self, payload, headers):
        return self._request("POST", "/soc/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/soc/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/soc/engagements", headers=headers, params=params)

    def transition_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/soc/engagements/{engagement_id}/transitions", payload, headers
        )

    def get_readiness_summary(self, engagement_id, headers):
        return self._request(
            "GET", f"/soc/engagements/{engagement_id}/readiness-summary", headers=headers
        )

    def run_readiness_assessment(self, engagement_id, headers):
        return self._request(
            "POST", f"/soc/engagements/{engagement_id}/readiness-assessment", {}, headers
        )

    def run_calendar(self, engagement_id, headers):
        return self._request(
            "POST", f"/soc/engagements/{engagement_id}/calendar-run", {}, headers
        )

    # ----- SystemDescription -----
    def create_system_description(self, payload, headers):
        return self._request("POST", "/soc/system-descriptions", payload, headers)

    def get_system_description(self, system_description_id, headers):
        return self._request(
            "GET", f"/soc/system-descriptions/{system_description_id}", headers=headers
        )

    def list_system_descriptions(self, headers, params=None):
        return self._request("GET", "/soc/system-descriptions", headers=headers, params=params)

    def transition_system_description(self, system_description_id, payload, headers):
        return self._request(
            "POST",
            f"/soc/system-descriptions/{system_description_id}/transitions",
            payload,
            headers,
        )

    def lock_boundary(self, system_description_id, headers):
        return self._request(
            "POST",
            f"/soc/system-descriptions/{system_description_id}/lock-boundary",
            {},
            headers,
        )

    # ----- BoundaryComponent -----
    def create_boundary_component(self, payload, headers):
        return self._request("POST", "/soc/boundary-components", payload, headers)

    def get_boundary_component(self, boundary_component_id, headers):
        return self._request(
            "GET", f"/soc/boundary-components/{boundary_component_id}", headers=headers
        )

    def list_boundary_components(self, headers, params=None):
        return self._request("GET", "/soc/boundary-components", headers=headers, params=params)

    def set_boundary_component_scope(self, boundary_component_id, payload, headers):
        return self._request(
            "POST",
            f"/soc/boundary-components/{boundary_component_id}/set-scope",
            payload,
            headers,
        )

    # ----- TrustCriterion -----
    def create_trust_criterion(self, payload, headers):
        return self._request("POST", "/soc/trust-criteria", payload, headers)

    def get_trust_criterion(self, trust_criterion_id, headers):
        return self._request("GET", f"/soc/trust-criteria/{trust_criterion_id}", headers=headers)

    def list_trust_criteria(self, headers, params=None):
        return self._request("GET", "/soc/trust-criteria", headers=headers, params=params)

    # ----- Control -----
    def create_control(self, payload, headers):
        return self._request("POST", "/soc/controls", payload, headers)

    def get_control(self, control_id, headers):
        return self._request("GET", f"/soc/controls/{control_id}", headers=headers)

    def list_controls(self, headers, params=None):
        return self._request("GET", "/soc/controls", headers=headers, params=params)

    def assign_control_owner(self, control_id, payload, headers):
        return self._request(
            "POST", f"/soc/controls/{control_id}/assign-owner", payload, headers
        )

    def transition_control(self, control_id, payload, headers):
        return self._request(
            "POST", f"/soc/controls/{control_id}/transitions", payload, headers
        )

    def generate_evidence_calendar(self, control_id, headers):
        return self._request(
            "POST", f"/soc/controls/{control_id}/evidence-calendar", {}, headers
        )

    # ----- CriteriaMapping -----
    def create_criteria_mapping(self, payload, headers):
        return self._request("POST", "/soc/criteria-mappings", payload, headers)

    def get_criteria_mapping(self, criteria_mapping_id, headers):
        return self._request(
            "GET", f"/soc/criteria-mappings/{criteria_mapping_id}", headers=headers
        )

    def list_criteria_mappings(self, headers, params=None):
        return self._request("GET", "/soc/criteria-mappings", headers=headers, params=params)

    def retire_criteria_mapping(self, criteria_mapping_id, headers):
        return self._request(
            "DELETE", f"/soc/criteria-mappings/{criteria_mapping_id}", headers=headers
        )

    # ----- EvidenceRequest -----
    def create_evidence_request(self, payload, headers):
        return self._request("POST", "/soc/evidence-requests", payload, headers)

    def get_evidence_request(self, evidence_request_id, headers):
        return self._request(
            "GET", f"/soc/evidence-requests/{evidence_request_id}", headers=headers
        )

    def list_evidence_requests(self, headers, params=None):
        return self._request("GET", "/soc/evidence-requests", headers=headers, params=params)

    def submit_evidence(self, evidence_request_id, payload, headers):
        return self._request(
            "POST", f"/soc/evidence-requests/{evidence_request_id}/submit", payload, headers
        )

    def review_evidence(self, evidence_request_id, payload, headers):
        return self._request(
            "POST", f"/soc/evidence-requests/{evidence_request_id}/review", payload, headers
        )

    # ----- Gap -----
    def create_gap(self, payload, headers):
        return self._request("POST", "/soc/gaps", payload, headers)

    def get_gap(self, gap_id, headers):
        return self._request("GET", f"/soc/gaps/{gap_id}", headers=headers)

    def list_gaps(self, headers, params=None):
        return self._request("GET", "/soc/gaps", headers=headers, params=params)

    def transition_gap(self, gap_id, payload, headers):
        return self._request("POST", f"/soc/gaps/{gap_id}/transitions", payload, headers)

    # ----- AuditSample -----
    def draw_audit_sample(self, payload, headers):
        return self._request("POST", "/soc/audit-samples", payload, headers)

    def get_audit_sample(self, audit_sample_id, headers):
        return self._request("GET", f"/soc/audit-samples/{audit_sample_id}", headers=headers)

    def list_audit_samples(self, headers, params=None):
        return self._request("GET", "/soc/audit-samples", headers=headers, params=params)

    def record_sample_item(self, audit_sample_id, payload, headers):
        return self._request(
            "POST", f"/soc/audit-samples/{audit_sample_id}/items", payload, headers
        )

    def conclude_audit_sample(self, audit_sample_id, headers):
        return self._request(
            "POST", f"/soc/audit-samples/{audit_sample_id}/conclude", {}, headers
        )

    def void_audit_sample(self, audit_sample_id, payload, headers):
        return self._request(
            "POST", f"/soc/audit-samples/{audit_sample_id}/void", payload, headers
        )

    # ----- AuditException -----
    def get_audit_exception(self, audit_exception_id, headers):
        return self._request(
            "GET", f"/soc/audit-exceptions/{audit_exception_id}", headers=headers
        )

    def list_audit_exceptions(self, headers, params=None):
        return self._request("GET", "/soc/audit-exceptions", headers=headers, params=params)

    def evaluate_audit_exception(self, audit_exception_id, payload, headers):
        return self._request(
            "POST", f"/soc/audit-exceptions/{audit_exception_id}/evaluate", payload, headers
        )

    # ----- SubserviceOrganization -----
    def create_subservice_organization(self, payload, headers):
        return self._request("POST", "/soc/subservice-organizations", payload, headers)

    def get_subservice_organization(self, subservice_organization_id, headers):
        return self._request(
            "GET",
            f"/soc/subservice-organizations/{subservice_organization_id}",
            headers=headers,
        )

    def list_subservice_organizations(self, headers, params=None):
        return self._request(
            "GET", "/soc/subservice-organizations", headers=headers, params=params
        )

    def set_subservice_method(self, subservice_organization_id, payload, headers):
        return self._request(
            "POST",
            f"/soc/subservice-organizations/{subservice_organization_id}/set-method",
            payload,
            headers,
        )

    # ----- CUEC -----
    def create_cuec(self, payload, headers):
        return self._request("POST", "/soc/cuecs", payload, headers)

    def get_cuec(self, cuec_id, headers):
        return self._request("GET", f"/soc/cuecs/{cuec_id}", headers=headers)

    def list_cuecs(self, headers, params=None):
        return self._request("GET", "/soc/cuecs", headers=headers, params=params)

    def articulate_cuec(self, cuec_id, payload, headers):
        return self._request("POST", f"/soc/cuecs/{cuec_id}/articulate", payload, headers)

    # ----- ReportDistribution -----
    def create_report_distribution(self, payload, headers):
        return self._request("POST", "/soc/report-distributions", payload, headers)

    def get_report_distribution(self, report_distribution_id, headers):
        return self._request(
            "GET", f"/soc/report-distributions/{report_distribution_id}", headers=headers
        )

    def list_report_distributions(self, headers, params=None):
        return self._request("GET", "/soc/report-distributions", headers=headers, params=params)

    def transition_report_distribution(self, report_distribution_id, payload, headers):
        return self._request(
            "POST",
            f"/soc/report-distributions/{report_distribution_id}/transitions",
            payload,
            headers,
        )

    # ----- BridgeLetter -----
    def create_bridge_letter(self, payload, headers):
        return self._request("POST", "/soc/bridge-letters", payload, headers)

    def get_bridge_letter(self, bridge_letter_id, headers):
        return self._request("GET", f"/soc/bridge-letters/{bridge_letter_id}", headers=headers)

    def list_bridge_letters(self, headers, params=None):
        return self._request("GET", "/soc/bridge-letters", headers=headers, params=params)

    def issue_bridge_letter(self, bridge_letter_id, headers):
        return self._request(
            "POST", f"/soc/bridge-letters/{bridge_letter_id}/issue", {}, headers
        )

    # ----- CustomerQuestionnaire -----
    def create_customer_questionnaire(self, payload, headers):
        return self._request("POST", "/soc/customer-questionnaires", payload, headers)

    def get_customer_questionnaire(self, customer_questionnaire_id, headers):
        return self._request(
            "GET", f"/soc/customer-questionnaires/{customer_questionnaire_id}", headers=headers
        )

    def list_customer_questionnaires(self, headers, params=None):
        return self._request(
            "GET", "/soc/customer-questionnaires", headers=headers, params=params
        )

    def deflect_customer_questionnaire(self, customer_questionnaire_id, payload, headers):
        return self._request(
            "POST",
            f"/soc/customer-questionnaires/{customer_questionnaire_id}/deflect",
            payload,
            headers,
        )

    # ----- Logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
