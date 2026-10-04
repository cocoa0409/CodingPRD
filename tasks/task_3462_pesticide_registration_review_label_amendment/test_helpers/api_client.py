"""API client: one method per endpoint defined in the PRD (§4 index).

The logical-clock endpoint lives OUTSIDE the /pesticide-registry prefix
(PRD §2.4): POST /_clock/set_current_utc. Every other path carries the
prefix. Methods return the raw requests.Response so tests can assert
status codes; fixtures validate via get_success_data().
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/pesticide-registry"
CLOCK_PATH = "/_clock/set_current_utc"  # platform endpoint — NO prefix


class ApiClient(GenericApiClient):
    # --- Platform: logical clock (unprefixed) ---
    def set_clock(self, payload: Dict, headers: Dict):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # --- Active ingredients ---
    def create_active_ingredient(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/active-ingredients", payload, headers)

    def list_active_ingredients(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/active-ingredients", headers=headers, params=params)

    # --- Products ---
    def create_product(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def list_products(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def get_product(self, product_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def reinstate_product(self, product_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/products/{product_id}/reinstate",
                             payload if payload is not None else {}, headers)

    def list_product_use_sites(self, product_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/products/{product_id}/use-sites",
                             headers=headers, params=params)

    def list_product_tolerances(self, product_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/products/{product_id}/tolerances",
                             headers=headers, params=params)

    def list_product_bulletins(self, product_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/products/{product_id}/endangered-species-bulletins",
                             headers=headers, params=params)

    def list_product_review_cases(self, product_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/products/{product_id}/registration-review-cases",
                             headers=headers, params=params)

    # --- Registration applications ---
    def create_application(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/registration-applications", payload, headers)

    def list_applications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/registration-applications", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/registration-applications/{application_id}",
                             headers=headers)

    def submit_application(self, application_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/registration-applications/{application_id}/submit",
                             payload if payload is not None else {}, headers)

    def withdraw_application(self, application_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/registration-applications/{application_id}/withdraw",
                             payload if payload is not None else {}, headers)

    def decide_application(self, application_id: str, payload: Dict, headers: Dict):
        return self._request("POST",
                             f"{PREFIX}/registration-applications/{application_id}/review-decisions",
                             payload, headers)

    def list_application_studies(self, application_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request("GET",
                             f"{PREFIX}/registration-applications/{application_id}/study-submissions",
                             headers=headers, params=params)

    def list_application_risk_assessments(self, application_id: str, headers: Dict):
        return self._request("GET",
                             f"{PREFIX}/registration-applications/{application_id}/risk-assessments",
                             headers=headers)

    # --- Study submissions ---
    def create_study(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/study-submissions", payload, headers)

    def list_studies(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/study-submissions", headers=headers, params=params)

    def get_study(self, study_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/study-submissions/{study_id}", headers=headers)

    def decide_study(self, study_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/study-submissions/{study_id}/review-decisions",
                             payload, headers)

    # --- Risk assessments ---
    def create_risk_assessment(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/risk-assessments", payload, headers)

    # --- Tolerances ---
    def create_tolerance(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/tolerances", payload, headers)

    # --- Label amendments ---
    def create_label_amendment(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/label-amendments", payload, headers)

    def list_label_amendments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/label-amendments", headers=headers, params=params)

    def get_label_amendment(self, amendment_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/label-amendments/{amendment_id}", headers=headers)

    def withdraw_label_amendment(self, amendment_id: str, headers: Dict,
                                 payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/label-amendments/{amendment_id}/withdraw",
                             payload if payload is not None else {}, headers)

    def decide_label_amendment(self, amendment_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/label-amendments/{amendment_id}/review-decisions",
                             payload, headers)

    # --- Applicator certifications ---
    def create_certification(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/applicator-certifications", payload, headers)

    def list_certifications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/applicator-certifications",
                             headers=headers, params=params)

    def renew_certification(self, certification_id: str, payload: Dict, headers: Dict):
        return self._request("POST",
                             f"{PREFIX}/applicator-certifications/{certification_id}/renew",
                             payload, headers)

    # --- Endangered-species bulletins ---
    def create_bulletin(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/endangered-species-bulletins", payload, headers)

    def lift_bulletin(self, bulletin_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/endangered-species-bulletins/{bulletin_id}/lift",
                             payload if payload is not None else {}, headers)

    # --- Registration review cases ---
    def create_review_case(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/registration-review-cases", payload, headers)

    def get_review_case(self, case_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/registration-review-cases/{case_id}", headers=headers)

    def complete_review_case(self, case_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/registration-review-cases/{case_id}/complete",
                             payload if payload is not None else {}, headers)

    def list_case_data_call_ins(self, case_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/registration-review-cases/{case_id}/data-call-ins",
                             headers=headers)

    # --- Data call-ins ---
    def create_data_call_in(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/data-call-ins", payload, headers)

    def get_data_call_in(self, dci_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/data-call-ins/{dci_id}", headers=headers)

    def respond_data_call_in(self, dci_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/data-call-ins/{dci_id}/respond", payload, headers)

    # --- Cancellation / suspension proceedings ---
    def create_proceeding(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/cancellation-proceedings", payload, headers)

    def list_proceedings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/cancellation-proceedings",
                             headers=headers, params=params)

    def get_proceeding(self, proceeding_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/cancellation-proceedings/{proceeding_id}",
                             headers=headers)

    def hear_proceeding(self, proceeding_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/cancellation-proceedings/{proceeding_id}/hear",
                             payload if payload is not None else {}, headers)

    def issue_order(self, proceeding_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request("POST",
                             f"{PREFIX}/cancellation-proceedings/{proceeding_id}/issue-order",
                             payload if payload is not None else {}, headers)

    def vacate_proceeding(self, proceeding_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/cancellation-proceedings/{proceeding_id}/vacate",
                             payload, headers)

    def record_disposal(self, proceeding_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{PREFIX}/cancellation-proceedings/{proceeding_id}/existing-stocks-disposals",
            payload, headers)

    # --- State registrations ---
    def create_state_registration(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/state-registrations", payload, headers)

    def list_state_registrations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/state-registrations", headers=headers, params=params)

    def get_state_registration(self, registration_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/state-registrations/{registration_id}",
                             headers=headers)

    def decide_state_registration(self, registration_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/state-registrations/{registration_id}/review-decisions",
            payload, headers)

    def revoke_state_registration(self, registration_id: str, headers: Dict,
                                  payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/state-registrations/{registration_id}/revoke",
                             payload if payload is not None else {}, headers)

    def renew_state_registration(self, registration_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/state-registrations/{registration_id}/renew",
                             payload, headers)


# Shared client instance. Import it as ``from test_helpers import api_client``
# (the package attribute is this instance; the submodule of the same name is
# intentionally shadowed at package level — do not ``import
# test_helpers.api_client as ac``).
api_client = ApiClient()
