"""API client: one method per endpoint defined by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------------- species
    def create_species(self, payload, headers):
        return self._request("POST", "/species", payload, headers)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}", headers=headers)

    def create_critical_habitat_unit(self, species_id, payload, headers):
        return self._request(
            "POST", f"/species/{species_id}/critical-habitat-units", payload, headers
        )

    def list_critical_habitat_units(self, species_id, headers, params=None):
        return self._request(
            "GET",
            f"/species/{species_id}/critical-habitat-units",
            headers=headers,
            params=params,
        )

    def list_species_conservation_banks(self, species_id, headers, params=None):
        return self._request(
            "GET",
            f"/species/{species_id}/conservation-banks",
            headers=headers,
            params=params,
        )

    def change_species_listing(self, species_id, payload, headers):
        return self._request(
            "POST", f"/species/{species_id}/listing-change", payload, headers
        )

    # ------------------------------------------------------------ proponent
    def create_proponent(self, payload, headers):
        return self._request("POST", "/proponents", payload, headers)

    def get_proponent(self, proponent_id, headers):
        return self._request("GET", f"/proponents/{proponent_id}", headers=headers)

    # ------------------------------------------------------- project action
    def create_project_action(self, payload, headers):
        return self._request("POST", "/project-actions", payload, headers)

    def list_project_actions(self, headers, params=None):
        return self._request("GET", "/project-actions", headers=headers, params=params)

    def get_project_action(self, action_id, headers):
        return self._request("GET", f"/project-actions/{action_id}", headers=headers)

    def list_action_consultations(self, action_id, headers, params=None):
        return self._request(
            "GET",
            f"/project-actions/{action_id}/consultations",
            headers=headers,
            params=params,
        )

    def list_action_habitat_conservation_plans(self, action_id, headers, params=None):
        return self._request(
            "GET",
            f"/project-actions/{action_id}/habitat-conservation-plans",
            headers=headers,
            params=params,
        )

    def create_presence_determination(self, action_id, payload, headers):
        return self._request(
            "POST",
            f"/project-actions/{action_id}/presence-determinations",
            payload,
            headers,
        )

    def run_effect_determination(self, action_id, headers, payload=None):
        return self._request(
            "POST",
            f"/project-actions/{action_id}/effect-determination",
            payload if payload is not None else {},
            headers,
        )

    def create_habitat_conservation_plan(self, action_id, payload, headers):
        return self._request(
            "POST",
            f"/project-actions/{action_id}/habitat-conservation-plans",
            payload,
            headers,
        )

    # ------------------------------------------- presence determination reads
    def list_presence_determinations(self, headers, params=None):
        return self._request(
            "GET", "/presence-determinations", headers=headers, params=params
        )

    def get_presence_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/presence-determinations/{determination_id}", headers=headers
        )

    # --------------------------------------------------------- consultation
    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"/consultations/{consultation_id}", headers=headers)

    def list_biological_opinions(self, consultation_id, headers, params=None):
        return self._request(
            "GET",
            f"/consultations/{consultation_id}/biological-opinions",
            headers=headers,
            params=params,
        )

    def submit_biological_assessment(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/consultations/{consultation_id}/biological-assessment",
            payload,
            headers,
        )

    def request_information(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/consultations/{consultation_id}/information-request",
            payload,
            headers,
        )

    def record_concurrence(self, consultation_id, payload, headers):
        return self._request(
            "POST", f"/consultations/{consultation_id}/concurrence", payload, headers
        )

    def issue_biological_opinion(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/consultations/{consultation_id}/biological-opinion",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------- conservation bank
    def create_conservation_bank(self, payload, headers):
        return self._request("POST", "/conservation-banks", payload, headers)

    def get_conservation_bank(self, bank_id, headers):
        return self._request("GET", f"/conservation-banks/{bank_id}", headers=headers)

    def list_bank_mitigation_commitments(self, bank_id, headers, params=None):
        return self._request(
            "GET",
            f"/conservation-banks/{bank_id}/mitigation-commitments",
            headers=headers,
            params=params,
        )

    # ------------------------------------------ habitat conservation plan
    def get_habitat_conservation_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/habitat-conservation-plans/{plan_id}", headers=headers
        )

    def list_plan_mitigation_commitments(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/habitat-conservation-plans/{plan_id}/mitigation-commitments",
            headers=headers,
            params=params,
        )

    def list_plan_incidental_take_permits(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/habitat-conservation-plans/{plan_id}/incidental-take-permits",
            headers=headers,
            params=params,
        )

    def list_plan_changed_circumstance_events(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/habitat-conservation-plans/{plan_id}/changed-circumstance-events",
            headers=headers,
            params=params,
        )

    def create_mitigation_commitment(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/habitat-conservation-plans/{plan_id}/mitigation-commitments",
            payload,
            headers,
        )

    def create_funding_assurance(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/habitat-conservation-plans/{plan_id}/funding-assurances",
            payload,
            headers,
        )

    def submit_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/habitat-conservation-plans/{plan_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/habitat-conservation-plans/{plan_id}/decision", payload, headers
        )

    def issue_incidental_take_permit(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/habitat-conservation-plans/{plan_id}/incidental-take-permits",
            payload,
            headers,
        )

    def create_changed_circumstance_event(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/habitat-conservation-plans/{plan_id}/changed-circumstance-events",
            payload,
            headers,
        )

    # ------------------------------------------------ incidental take permit
    def get_incidental_take_permit(self, permit_id, headers):
        return self._request(
            "GET", f"/incidental-take-permits/{permit_id}", headers=headers
        )

    def list_permit_monitoring_reports(self, permit_id, headers, params=None):
        return self._request(
            "GET",
            f"/incidental-take-permits/{permit_id}/monitoring-reports",
            headers=headers,
            params=params,
        )

    def create_monitoring_report(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"/incidental-take-permits/{permit_id}/monitoring-reports",
            payload,
            headers,
        )

    def adjudicate_monitoring_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/monitoring-reports/{report_id}/adjudication", payload, headers
        )

    def respond_to_circumstance_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/changed-circumstance-events/{event_id}/response", payload, headers
        )


api_client = ApiClient()
