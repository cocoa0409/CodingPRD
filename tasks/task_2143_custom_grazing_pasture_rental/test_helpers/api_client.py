"""API client: one method per endpoint defined in the PRD.

All business paths sit under the /grazing prefix; /_clock is the single
test-driving namespace.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ registry
    def register_grazier(self, payload, headers):
        return self._request("POST", "/grazing/graziers", payload, headers)

    def register_cattle_owner(self, payload, headers):
        return self._request("POST", "/grazing/cattle-owners", payload, headers)

    def get_cattle_owner(self, owner_id, headers):
        return self._request("GET", f"/grazing/cattle-owners/{owner_id}", headers=headers)

    def register_range_consultant(self, payload, headers):
        return self._request("POST", "/grazing/range-consultants", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------- pasture
    def create_pasture(self, payload, headers):
        return self._request("POST", "/grazing/pastures", payload, headers)

    def get_pasture(self, pasture_id, headers):
        return self._request("GET", f"/grazing/pastures/{pasture_id}", headers=headers)

    def list_pastures(self, headers, params=None):
        return self._request("GET", "/grazing/pastures", headers=headers, params=params)

    def set_pasture_status(self, pasture_id, payload, headers):
        return self._request(
            "POST", f"/grazing/pastures/{pasture_id}/status", payload, headers
        )

    def create_capacity_assessment(self, pasture_id, payload, headers):
        return self._request(
            "POST", f"/grazing/pastures/{pasture_id}/capacity-assessments", payload, headers
        )

    def get_capacity_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/grazing/capacity-assessments/{assessment_id}", headers=headers
        )

    def list_capacity_assessments(self, headers, params=None):
        return self._request(
            "GET", "/grazing/capacity-assessments", headers=headers, params=params
        )

    def create_drought_reading(self, pasture_id, payload, headers):
        return self._request(
            "POST", f"/grazing/pastures/{pasture_id}/drought-readings", payload, headers
        )

    def list_drought_readings(self, pasture_id, headers, params=None):
        return self._request(
            "GET", f"/grazing/pastures/{pasture_id}/drought-readings",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------ contract
    def create_contract(self, payload, headers):
        return self._request("POST", "/grazing/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/grazing/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/grazing/contracts", headers=headers, params=params)

    def submit_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/grazing/contracts/{contract_id}/submit", {}, headers
        )

    def sign_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grazing/contracts/{contract_id}/sign", payload, headers
        )

    def early_removal(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grazing/contracts/{contract_id}/early-removal", payload, headers
        )

    # ----------------------------------------------------------------------- lot
    def create_lot(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grazing/contracts/{contract_id}/lots", payload, headers
        )

    def list_contract_lots(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/grazing/contracts/{contract_id}/lots", headers=headers, params=params
        )

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/grazing/lots/{lot_id}", headers=headers)

    def receive_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/grazing/lots/{lot_id}/receive", payload, headers)

    def create_weight_event(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/grazing/lots/{lot_id}/weight-events", payload, headers
        )

    def list_weight_events(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/grazing/lots/{lot_id}/weight-events", headers=headers, params=params
        )

    # -------------------------------------------------------------- health care
    def create_treatment(self, lot_id, payload, headers):
        return self._request("POST", f"/grazing/lots/{lot_id}/treatments", payload, headers)

    def list_treatments(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/grazing/lots/{lot_id}/treatments", headers=headers, params=params
        )

    def review_treatment(self, treatment_id, payload, headers):
        return self._request(
            "POST", f"/grazing/treatments/{treatment_id}/review", payload, headers
        )

    # ---------------------------------------------------------------- death loss
    def create_death_loss(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/grazing/lots/{lot_id}/death-losses", payload, headers
        )

    def list_death_losses(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/grazing/lots/{lot_id}/death-losses", headers=headers, params=params
        )

    def review_death_loss(self, death_loss_id, payload, headers):
        return self._request(
            "POST", f"/grazing/death-losses/{death_loss_id}/review", payload, headers
        )

    # ------------------------------------------------------------ infrastructure
    def create_infrastructure_ticket(self, payload, headers):
        return self._request("POST", "/grazing/infrastructure-tickets", payload, headers)

    def get_infrastructure_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/grazing/infrastructure-tickets/{ticket_id}", headers=headers
        )

    def list_infrastructure_tickets(self, headers, params=None):
        return self._request(
            "GET", "/grazing/infrastructure-tickets", headers=headers, params=params
        )

    def assign_infrastructure_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/grazing/infrastructure-tickets/{ticket_id}/assign", payload, headers
        )

    def complete_infrastructure_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/grazing/infrastructure-tickets/{ticket_id}/complete", payload, headers
        )

    # ---------------------------------------------------------------- settlement
    def create_settlement(self, payload, headers):
        return self._request("POST", "/grazing/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/grazing/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/grazing/settlements", headers=headers, params=params)

    def issue_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/issue", {}, headers
        )

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/dispute", payload, headers
        )

    def adjudicate_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/adjudicate", payload, headers
        )

    def reissue_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/reissue", {}, headers
        )

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/finalize", {}, headers
        )

    def void_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/grazing/settlements/{settlement_id}/void", payload, headers
        )


api_client = ApiClient()
