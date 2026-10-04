"""API client: one method per endpoint defined in the PRD.

All business endpoints live under the /refuge mount. The clock control is
UNPREFIXED — POST /_clock/set_current_utc sits outside the business surface
(PRD §4). Action endpoints with an empty input list send an empty JSON body.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Management units
    # ------------------------------------------------------------------
    def create_management_unit(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/refuge/management-units", payload, headers)

    def get_management_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/management-units/{unit_id}", headers=headers)

    def get_unit_posture(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/management-units/{unit_id}/posture", headers=headers)

    # ------------------------------------------------------------------
    # Compatibility determinations and public comments
    # ------------------------------------------------------------------
    def create_determination(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/refuge/determinations", payload, headers)

    def get_determination(self, determination_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/determinations/{determination_id}", headers=headers)

    def open_determination_comment(self, determination_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/determinations/{determination_id}/open-comment", {}, headers)

    def finalize_determination(self, determination_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/determinations/{determination_id}/finalize", payload, headers)

    def create_comment(self, determination_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/determinations/{determination_id}/comments", payload, headers)

    def list_comments(self, determination_id: str, headers: Dict[str, str],
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/determinations/{determination_id}/comments",
            headers=headers, params=params)

    def adjudicate_comment(self, comment_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/comments/{comment_id}/adjudicate", payload, headers)

    # ------------------------------------------------------------------
    # Permit applications
    # ------------------------------------------------------------------
    def create_permit(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/refuge/permits", payload, headers)

    def get_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/permits/{permit_id}", headers=headers)

    def list_permits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refuge/permits", headers=headers, params=params)

    def return_permit_for_revision(self, permit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/permits/{permit_id}/return-for-revision", payload, headers)

    def resubmit_permit(self, permit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/permits/{permit_id}/resubmit", payload, headers)

    def approve_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/permits/{permit_id}/approve", {}, headers)

    def pay_permit(self, permit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/permits/{permit_id}/pay", payload, headers)

    def revoke_permit(self, permit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/permits/{permit_id}/revoke", payload, headers)

    # ------------------------------------------------------------------
    # Habitat treatments
    # ------------------------------------------------------------------
    def create_treatment(self, unit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/management-units/{unit_id}/treatments", payload, headers)

    def list_treatments(self, unit_id: str, headers: Dict[str, str],
                        params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/management-units/{unit_id}/treatments",
            headers=headers, params=params)

    def start_treatment(self, treatment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/treatments/{treatment_id}/start", {}, headers)

    def complete_treatment(self, treatment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/treatments/{treatment_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Facility closures
    # ------------------------------------------------------------------
    def create_closure(self, unit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/management-units/{unit_id}/closures", payload, headers)

    def list_closures(self, unit_id: str, headers: Dict[str, str],
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/management-units/{unit_id}/closures",
            headers=headers, params=params)

    def activate_closure(self, closure_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/closures/{closure_id}/activate", {}, headers)

    def lift_closure(self, closure_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/closures/{closure_id}/lift", {}, headers)

    # ------------------------------------------------------------------
    # Interpretive programs, volunteers, assignments
    # ------------------------------------------------------------------
    def create_program(self, unit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/management-units/{unit_id}/programs", payload, headers)

    def list_programs(self, unit_id: str, headers: Dict[str, str],
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/management-units/{unit_id}/programs",
            headers=headers, params=params)

    def create_volunteer(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/refuge/volunteers", payload, headers)

    def clear_volunteer_background(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/volunteers/{volunteer_id}/clear-background", {}, headers)

    def create_assignment(self, program_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/programs/{program_id}/assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refuge/assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Grazing offerings, bids, award
    # ------------------------------------------------------------------
    def create_grazing_offering(self, unit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/management-units/{unit_id}/grazing-offerings", payload, headers)

    def list_grazing_offerings(self, unit_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/management-units/{unit_id}/grazing-offerings",
            headers=headers, params=params)

    def get_grazing_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/grazing-offerings/{offering_id}", headers=headers)

    def create_bid(self, offering_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/grazing-offerings/{offering_id}/bids", payload, headers)

    def list_bids(self, offering_id: str, headers: Dict[str, str],
                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/grazing-offerings/{offering_id}/bids",
            headers=headers, params=params)

    def close_and_select_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/grazing-offerings/{offering_id}/close-and-select", {}, headers)

    # ------------------------------------------------------------------
    # Cooperative agreements
    # ------------------------------------------------------------------
    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refuge/cooperative-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refuge/cooperative-agreements", headers=headers, params=params)

    def assess_agreement(self, agreement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/cooperative-agreements/{agreement_id}/assess", payload, headers)

    def create_ledger_entry(self, agreement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/cooperative-agreements/{agreement_id}/ledger-entries",
            payload, headers)

    def complete_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/cooperative-agreements/{agreement_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Citations
    # ------------------------------------------------------------------
    def create_citation(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/refuge/citations", payload, headers)

    def get_citation(self, citation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refuge/citations/{citation_id}", headers=headers)

    def list_citations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refuge/citations", headers=headers, params=params)

    def void_citation(self, citation_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/refuge/citations/{citation_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Population objectives
    # ------------------------------------------------------------------
    def create_population_objective(self, unit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/management-units/{unit_id}/population-objectives",
            payload, headers)

    def list_population_objectives(self, unit_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/refuge/management-units/{unit_id}/population-objectives",
            headers=headers, params=params)

    def record_survey(self, objective_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refuge/population-objectives/{objective_id}/surveys", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock (UNPREFIXED — outside the /refuge business surface)
    # ------------------------------------------------------------------
    def set_clock(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
