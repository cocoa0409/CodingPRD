"""API client: one method per endpoint defined in the PRD (section 4).

All endpoints live under the /eeoc prefix — including the logical-clock
endpoint POST /eeoc/_clock/set_current_utc, which is routed through the
prefix exactly like every other call.

Methods return raw requests.Response objects; validate with the framework
validators (validate_success/validate_error/validate_paginated) or with
test_helpers.assertions.validate_created / validate_ok.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/eeoc"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD section 2.4; PlatformAdmin only) -----------------
    def set_clock(self, payload: Dict, headers: Optional[Dict] = None):
        """POST /eeoc/_clock/set_current_utc — payload: {to_iso8601}."""
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload=payload, headers=headers
        )

    # --- Reference data ------------------------------------------------------
    def create_deferral_agency(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/deferral-agencies", payload=payload, headers=headers
        )

    def create_employer(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/employers", payload=payload, headers=headers
        )

    def update_employer(self, employer_id: str, payload: Dict,
                        headers: Optional[Dict] = None):
        return self._request(
            "PATCH", f"{PREFIX}/employers/{employer_id}", payload=payload, headers=headers
        )

    def create_complainant(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/complainants", payload=payload, headers=headers
        )

    # --- Charges -------------------------------------------------------------
    def create_charge(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges", payload=payload, headers=headers
        )

    def get_charge(self, charge_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/charges/{charge_id}", headers=headers)

    def list_charges(self, headers: Optional[Dict] = None,
                     params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/charges", headers=headers, params=params)

    def amend_charge(self, charge_id: str, payload: Dict,
                     headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/amend", payload=payload, headers=headers
        )

    def withdraw_charge(self, charge_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/withdraw", headers=headers
        )

    # --- Mediation -----------------------------------------------------------
    def offer_mediation(self, charge_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/mediation-cases", headers=headers
        )

    def list_mediation_cases(self, charge_id: str, headers: Optional[Dict] = None,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/charges/{charge_id}/mediation-cases",
            headers=headers, params=params,
        )

    def get_mediation_case(self, mediation_case_id: str,
                           headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/mediation-cases/{mediation_case_id}", headers=headers
        )

    def respond_mediation(self, mediation_case_id: str, payload: Dict,
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/mediation-cases/{mediation_case_id}/respond",
            payload=payload, headers=headers,
        )

    def create_mediation_session(self, mediation_case_id: str, payload: Dict,
                                 headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/mediation-cases/{mediation_case_id}/sessions",
            payload=payload, headers=headers,
        )

    def list_mediation_sessions(self, mediation_case_id: str,
                                headers: Optional[Dict] = None,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/mediation-cases/{mediation_case_id}/sessions",
            headers=headers, params=params,
        )

    def conclude_mediation(self, mediation_case_id: str, payload: Dict,
                           headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/mediation-cases/{mediation_case_id}/conclude",
            payload=payload, headers=headers,
        )

    # --- Investigation -------------------------------------------------------
    def get_investigation_case(self, case_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/investigation-cases/{case_id}", headers=headers
        )

    def list_investigation_cases(self, headers: Optional[Dict] = None,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/investigation-cases", headers=headers, params=params
        )

    def assign_investigator(self, case_id: str, payload: Dict,
                            headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/investigation-cases/{case_id}/assign",
            payload=payload, headers=headers,
        )

    def create_evidence_request(self, case_id: str, payload: Dict,
                                headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/investigation-cases/{case_id}/evidence-requests",
            payload=payload, headers=headers,
        )

    def list_evidence_requests(self, case_id: str, headers: Optional[Dict] = None,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/investigation-cases/{case_id}/evidence-requests",
            headers=headers, params=params,
        )

    def respond_evidence_request(self, request_id: str, payload: Dict,
                                 headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/evidence-requests/{request_id}/respond",
            payload=payload, headers=headers,
        )

    def create_witness_interview(self, case_id: str, payload: Dict,
                                 headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/investigation-cases/{case_id}/interviews",
            payload=payload, headers=headers,
        )

    def list_witness_interviews(self, case_id: str, headers: Optional[Dict] = None,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/investigation-cases/{case_id}/interviews",
            headers=headers, params=params,
        )

    # --- Determinations ------------------------------------------------------
    def create_determination(self, case_id: str, payload: Dict,
                             headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/investigation-cases/{case_id}/determinations",
            payload=payload, headers=headers,
        )

    def list_determinations(self, case_id: str, headers: Optional[Dict] = None,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/investigation-cases/{case_id}/determinations",
            headers=headers, params=params,
        )

    def submit_determination(self, determination_id: str,
                             headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/determinations/{determination_id}/submit",
            headers=headers,
        )

    def review_determination(self, determination_id: str, payload: Dict,
                             headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/determinations/{determination_id}/review",
            payload=payload, headers=headers,
        )

    # --- Conciliation --------------------------------------------------------
    def list_conciliation_processes(self, charge_id: str,
                                    headers: Optional[Dict] = None,
                                    params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/charges/{charge_id}/conciliation-processes",
            headers=headers, params=params,
        )

    def get_conciliation_process(self, process_id: str,
                                 headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/conciliation-processes/{process_id}", headers=headers
        )

    def table_offer(self, process_id: str, payload: Dict,
                    headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/conciliation-processes/{process_id}/offers",
            payload=payload, headers=headers,
        )

    def accept_conciliation(self, process_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/conciliation-processes/{process_id}/accept",
            headers=headers,
        )

    def fail_conciliation(self, process_id: str, payload: Dict,
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/conciliation-processes/{process_id}/fail",
            payload=payload, headers=headers,
        )

    def list_remedy_packages(self, process_id: str, headers: Optional[Dict] = None,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/conciliation-processes/{process_id}/remedy-packages",
            headers=headers, params=params,
        )

    # --- Right-to-sue --------------------------------------------------------
    def issue_right_to_sue(self, charge_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/right-to-sue-notices",
            headers=headers,
        )

    def list_right_to_sue_notices(self, charge_id: str,
                                  headers: Optional[Dict] = None,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/charges/{charge_id}/right-to-sue-notices",
            headers=headers, params=params,
        )

    # --- Systemic cases ------------------------------------------------------
    def create_systemic_case(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/systemic-cases", payload=payload, headers=headers
        )

    def link_charge(self, systemic_case_id: str, payload: Dict,
                    headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/systemic-cases/{systemic_case_id}/links",
            payload=payload, headers=headers,
        )

    # --- Disclosures ---------------------------------------------------------
    def create_disclosure(self, charge_id: str, payload: Dict,
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/disclosures",
            payload=payload, headers=headers,
        )

    def list_disclosures(self, charge_id: str, headers: Optional[Dict] = None,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/charges/{charge_id}/disclosures",
            headers=headers, params=params,
        )

    # --- Settlement vacatur --------------------------------------------------
    def vacate_settlement(self, charge_id: str, payload: Dict,
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/vacate-settlement",
            payload=payload, headers=headers,
        )


api_client = ApiClient()
