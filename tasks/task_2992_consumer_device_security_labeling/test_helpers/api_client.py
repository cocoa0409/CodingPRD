"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/labeling"


class ApiClient(GenericApiClient):
    # ---- logical clock (PRD §2.4) ---------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- program tiers ---------------------------------------------------
    def create_program_tier(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/program-tiers", payload, headers)

    def get_program_tier(self, tier_id: str, headers):
        return self._request("GET", f"{PREFIX}/program-tiers/{tier_id}", headers=headers)

    def list_tier_device_categories(self, tier_id: str, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/program-tiers/{tier_id}/device-categories",
            headers=headers,
            params=params,
        )

    # ---- device categories ----------------------------------------------
    def create_device_category(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/device-categories", payload, headers)

    def get_device_category(self, category_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/device-categories/{category_id}", headers=headers
        )

    # ---- security criteria ----------------------------------------------
    def create_security_criteria(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/security-criteria", payload, headers)

    def get_security_criterion(self, criterion_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/security-criteria/{criterion_id}", headers=headers
        )

    def list_security_criteria(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/security-criteria", headers=headers, params=params
        )

    # ---- manufacturers ---------------------------------------------------
    def create_manufacturer(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/manufacturers/{manufacturer_id}", headers=headers
        )

    # ---- test labs -------------------------------------------------------
    def create_test_lab(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/test-labs", payload, headers)

    def get_test_lab(self, lab_id: str, headers):
        return self._request("GET", f"{PREFIX}/test-labs/{lab_id}", headers=headers)

    # ---- retailers -------------------------------------------------------
    def create_retailer(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/retailers", payload, headers)

    def get_retailer(self, retailer_id: str, headers):
        return self._request("GET", f"{PREFIX}/retailers/{retailer_id}", headers=headers)

    def acknowledge_education(self, retailer_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/retailers/{retailer_id}/education-ack", payload, headers
        )

    # ---- products --------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id: str, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def create_spec_change(self, product_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/products/{product_id}/spec-changes", payload, headers
        )

    # ---- conformance assessments ----------------------------------------
    def create_assessment(self, product_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/products/{product_id}/assessments", payload, headers
        )

    def get_assessment(self, assessment_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assessments", headers=headers, params=params
        )

    def create_criterion_responses(
        self, assessment_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/responses", payload, headers
        )

    def get_criterion_response(self, response_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/criterion-responses/{response_id}", headers=headers
        )

    def list_criterion_responses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/criterion-responses", headers=headers, params=params
        )

    def submit_assessment(self, assessment_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{PREFIX}/assessments/{assessment_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_assessment(self, assessment_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/decide", payload, headers
        )

    def resubmit_assessment(self, assessment_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/resubmit", payload, headers
        )

    # ---- test engagements ------------------------------------------------
    def create_test_engagement(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/test-engagements", payload, headers)

    def get_test_engagement(self, engagement_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/test-engagements/{engagement_id}", headers=headers
        )

    def list_test_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/test-engagements", headers=headers, params=params
        )

    def report_test_engagement(self, engagement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/test-engagements/{engagement_id}/report", payload, headers
        )

    def cancel_test_engagement(self, engagement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/test-engagements/{engagement_id}/cancel", payload, headers
        )

    # ---- label grants, registry entries and renewal ----------------------
    def create_label_grant(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/label-grants", payload, headers)

    def get_label_grant(self, grant_id: str, headers):
        return self._request("GET", f"{PREFIX}/label-grants/{grant_id}", headers=headers)

    def list_label_grants(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/label-grants", headers=headers, params=params
        )

    def create_registry_entry(self, grant_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/label-grants/{grant_id}/registry-entry", payload, headers
        )

    def get_registry_entry(self, grant_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/label-grants/{grant_id}/registry-entry", headers=headers
        )

    def decide_registry_publication(self, grant_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{PREFIX}/label-grants/{grant_id}/registry-publication",
            payload,
            headers,
        )

    def create_renewal(self, grant_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/label-grants/{grant_id}/renewals", payload, headers
        )

    def scan_registry(self, scannable_code: str, headers):
        return self._request(
            "GET", f"{PREFIX}/registry/{scannable_code}", headers=headers
        )

    # ---- retailer display authorizations ---------------------------------
    def create_display_authorization(self, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/display-authorizations", payload, headers
        )

    def get_display_authorization(self, authorization_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/display-authorizations/{authorization_id}", headers=headers
        )

    def list_display_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/display-authorizations", headers=headers, params=params
        )

    def withdraw_display_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{PREFIX}/display-authorizations/{authorization_id}/withdraw",
            payload,
            headers,
        )

    # ---- misuse enforcement ----------------------------------------------
    def create_enforcement_case(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/enforcement-cases", payload, headers)

    def get_enforcement_case(self, case_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/enforcement-cases/{case_id}", headers=headers
        )

    def list_enforcement_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/enforcement-cases", headers=headers, params=params
        )

    def issue_case_notice(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/notice", payload, headers
        )

    def refer_case_to_lab(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/lab-referral", payload, headers
        )

    def adjudicate_case(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/adjudicate", payload, headers
        )

    def vacate_case(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/vacate", payload, headers
        )

    def pay_penalty(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{PREFIX}/enforcement-cases/{case_id}/penalty-payments",
            payload,
            headers,
        )

    # ---- recognition surveys and program evaluation ----------------------
    def create_recognition_survey(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/recognition-surveys", payload, headers)

    def get_recognition_survey(self, survey_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/recognition-surveys/{survey_id}", headers=headers
        )

    def list_recognition_surveys(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/recognition-surveys", headers=headers, params=params
        )

    def get_program_evaluation(self, headers):
        return self._request("GET", f"{PREFIX}/program-evaluation", headers=headers)

    # ---- operational sweep ----------------------------------------------
    def run_expiry_sweep(self, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{PREFIX}/program/expiry-sweep",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
