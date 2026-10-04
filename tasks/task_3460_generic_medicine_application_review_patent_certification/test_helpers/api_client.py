"""API client: one method per endpoint defined in the PRD (section 4).

The clock endpoint lives outside the business prefix (PRD section 2.4), so its
path is used raw; all business paths carry the /generic-drug-review prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/generic-drug-review"


class ApiClient(GenericApiClient):
    # --- Logical clock (unprefixed, ProgramAdmin only) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Applicant companies ---
    def create_applicant_company(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicant-companies", payload, headers)

    def get_applicant_company(self, ac_id, headers):
        return self._request("GET", f"{PREFIX}/applicant-companies/{ac_id}", headers=headers)

    def list_applicant_facilities(self, ac_id, headers):
        return self._request("GET", f"{PREFIX}/applicant-companies/{ac_id}/manufacturing-facilities", headers=headers)

    # --- Manufacturing facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manufacturing-facilities", payload, headers)

    # --- Reference products / patents / protected indications ---
    def create_reference_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reference-products", payload, headers)

    def get_reference_product(self, rld_id, headers):
        return self._request("GET", f"{PREFIX}/reference-products/{rld_id}", headers=headers)

    def create_listed_patent(self, rld_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reference-products/{rld_id}/listed-patents", payload, headers)

    def list_listed_patents(self, rld_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reference-products/{rld_id}/listed-patents", headers=headers, params=params)

    def create_protected_indication(self, rld_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reference-products/{rld_id}/protected-indications", payload, headers)

    def list_protected_indications(self, rld_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reference-products/{rld_id}/protected-indications", headers=headers, params=params)

    # --- Generic applications ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{app_id}", headers=headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/submit", {}, headers)

    def approval_decision(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/approval-decision", payload, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/withdraw", {}, headers)

    def record_first_marketing(self, app_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/record-first-marketing", {}, headers)

    # --- Bioequivalence studies ---
    def create_be_study(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/bioequivalence-studies", payload, headers)

    def list_be_studies(self, app_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications/{app_id}/bioequivalence-studies", headers=headers, params=params)

    # --- Patent certifications ---
    def create_patent_certification(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/patent-certifications", payload, headers)

    def get_patent_certification(self, cert_id, headers):
        return self._request("GET", f"{PREFIX}/patent-certifications/{cert_id}", headers=headers)

    def list_patent_certifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patent-certifications", headers=headers, params=params)

    def amend_certification(self, cert_id, headers):
        return self._request("POST", f"{PREFIX}/patent-certifications/{cert_id}/amend", {}, headers)

    # --- Paragraph-IV notices and litigation ---
    def create_notice(self, cert_id, headers):
        return self._request("POST", f"{PREFIX}/patent-certifications/{cert_id}/notices", {}, headers)

    def list_notices(self, cert_id, headers):
        return self._request("GET", f"{PREFIX}/patent-certifications/{cert_id}/notices", headers=headers)

    def create_litigation_event(self, notice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/patent-notices/{notice_id}/litigation-events", payload, headers)

    # --- Review cycles / amendments ---
    def list_review_cycles(self, app_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{app_id}/review-cycles", headers=headers)

    def issue_deficiency(self, cycle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/review-cycles/{cycle_id}/issue-deficiency", payload, headers)

    def create_amendment(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/amendments", payload, headers)

    def list_amendments(self, app_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{app_id}/amendments", headers=headers)

    # --- Facility inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facility-inspections", payload, headers)

    def get_inspection(self, insp_id, headers):
        return self._request("GET", f"{PREFIX}/facility-inspections/{insp_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/facility-inspections", headers=headers, params=params)

    def record_inspection_outcome(self, insp_id, payload, headers):
        return self._request("POST", f"{PREFIX}/facility-inspections/{insp_id}/record-outcome", payload, headers)

    # --- Supplements ---
    def create_supplement(self, app_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{app_id}/supplements", payload, headers)

    def list_supplements(self, app_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications/{app_id}/supplements", headers=headers, params=params)

    def supplement_review_decision(self, supp_id, payload, headers):
        return self._request("POST", f"{PREFIX}/supplements/{supp_id}/review-decision", payload, headers)

    def withdraw_supplement(self, supp_id, headers):
        return self._request("POST", f"{PREFIX}/supplements/{supp_id}/withdraw", {}, headers)

    # --- Exclusivity awards ---
    def get_exclusivity_award(self, award_id, headers):
        return self._request("GET", f"{PREFIX}/exclusivity-awards/{award_id}", headers=headers)

    def list_exclusivity_awards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exclusivity-awards", headers=headers, params=params)


api_client = ApiClient()
