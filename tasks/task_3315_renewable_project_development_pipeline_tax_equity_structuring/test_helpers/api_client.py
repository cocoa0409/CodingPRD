"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def transition_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/transitions", payload, headers)

    # --- site control instruments ---
    def create_site_control_instrument(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/site-control-instruments", payload, headers
        )

    def list_site_control_instruments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/site-control-instruments",
            headers=headers, params=params,
        )

    def get_site_control_instrument(self, instrument_id, headers):
        return self._request(
            "GET", f"/api/site-control-instruments/{instrument_id}", headers=headers
        )

    def transition_site_control_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/api/site-control-instruments/{instrument_id}/transitions",
            payload, headers,
        )

    # --- interconnection requests ---
    def create_interconnection_request(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/interconnection-requests", payload, headers
        )

    def list_interconnection_requests(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/interconnection-requests",
            headers=headers, params=params,
        )

    def get_interconnection_request(self, request_id, headers):
        return self._request(
            "GET", f"/api/interconnection-requests/{request_id}", headers=headers
        )

    def transition_interconnection_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/interconnection-requests/{request_id}/transitions",
            payload, headers,
        )

    def allocate_upgrade_costs(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/interconnection-requests/{request_id}/allocate-upgrade-costs",
            payload, headers,
        )

    # --- interconnection studies ---
    def create_study(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/interconnection-requests/{request_id}/studies", payload, headers
        )

    def list_studies(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/api/interconnection-requests/{request_id}/studies",
            headers=headers, params=params,
        )

    def get_study(self, study_id, headers):
        return self._request(
            "GET", f"/api/interconnection-studies/{study_id}", headers=headers
        )

    def transition_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/api/interconnection-studies/{study_id}/transitions", payload, headers
        )

    # --- offtake agreements ---
    def create_offtake_agreement(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/offtake-agreements", payload, headers
        )

    def list_offtake_agreements(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/offtake-agreements",
            headers=headers, params=params,
        )

    def get_offtake_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/offtake-agreements/{agreement_id}", headers=headers
        )

    def transition_offtake_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/offtake-agreements/{agreement_id}/transitions", payload, headers
        )

    # --- supply agreements ---
    def create_supply_agreement(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/supply-agreements", payload, headers
        )

    def list_supply_agreements(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/supply-agreements",
            headers=headers, params=params,
        )

    def get_supply_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/supply-agreements/{agreement_id}", headers=headers
        )

    def transition_supply_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/transitions", payload, headers
        )

    # --- procurement orders ---
    def create_procurement_order(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/procurement-orders",
            payload, headers,
        )

    def list_procurement_orders(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/api/supply-agreements/{agreement_id}/procurement-orders",
            headers=headers, params=params,
        )

    def get_procurement_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/procurement-orders/{order_id}", headers=headers
        )

    def transition_procurement_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/procurement-orders/{order_id}/transitions", payload, headers
        )

    # --- construction milestones ---
    def create_milestone(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/construction-milestones", payload, headers
        )

    def list_milestones(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/construction-milestones",
            headers=headers, params=params,
        )

    def get_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/api/construction-milestones/{milestone_id}", headers=headers
        )

    def submit_milestone_evidence(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/api/construction-milestones/{milestone_id}/submit-evidence",
            payload, headers,
        )

    def certify_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/api/construction-milestones/{milestone_id}/certify", payload, headers
        )

    # --- tax credit qualifications ---
    def list_tax_credit_qualifications(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/tax-credit-qualifications",
            headers=headers, params=params,
        )

    def get_tax_credit_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/api/tax-credit-qualifications/{qualification_id}", headers=headers
        )

    def transition_tax_credit_qualification(self, qualification_id, payload, headers):
        return self._request(
            "POST", f"/api/tax-credit-qualifications/{qualification_id}/transitions",
            payload, headers,
        )

    # --- tax equity partnerships ---
    def create_partnership(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/tax-equity-partnerships", payload, headers
        )

    def list_partnerships(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/tax-equity-partnerships",
            headers=headers, params=params,
        )

    def get_partnership(self, partnership_id, headers):
        return self._request(
            "GET", f"/api/tax-equity-partnerships/{partnership_id}", headers=headers
        )

    def transition_partnership(self, partnership_id, payload, headers):
        return self._request(
            "POST", f"/api/tax-equity-partnerships/{partnership_id}/transitions",
            payload, headers,
        )

    def post_contribution(self, partnership_id, payload, headers):
        return self._request(
            "POST", f"/api/tax-equity-partnerships/{partnership_id}/contributions",
            payload, headers,
        )

    def post_distribution(self, partnership_id, payload, headers):
        return self._request(
            "POST", f"/api/tax-equity-partnerships/{partnership_id}/distributions",
            payload, headers,
        )

    def list_ledger_entries(self, partnership_id, headers, params=None):
        return self._request(
            "GET", f"/api/tax-equity-partnerships/{partnership_id}/ledger-entries",
            headers=headers, params=params,
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/api/partnership-ledger-entries/{entry_id}", headers=headers
        )

    # --- debt facilities ---
    def create_debt_facility(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/debt-facilities", payload, headers
        )

    def list_debt_facilities(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/debt-facilities",
            headers=headers, params=params,
        )

    def get_debt_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/api/debt-facilities/{facility_id}", headers=headers
        )

    def transition_debt_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/api/debt-facilities/{facility_id}/transitions", payload, headers
        )


api_client = ApiClient()
