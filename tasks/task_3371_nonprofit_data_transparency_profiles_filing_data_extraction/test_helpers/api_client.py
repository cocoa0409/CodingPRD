"""API client: one method per endpoint in the PRD's §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Organization -------------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", "/nonprofits/organizations", payload, headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/nonprofits/organizations", headers=headers, params=params)

    def get_organization(self, organization_id, headers):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}", headers=headers)

    def patch_organization(self, organization_id, payload, headers):
        return self._request("PATCH", f"/nonprofits/organizations/{organization_id}", payload, headers)

    def verify_organization(self, organization_id, payload, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/verify", payload, headers)

    # --- Program / leadership / demographics --------------------------------
    def create_program(self, organization_id, payload, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/programs", payload, headers)

    def list_programs(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/programs",
                             headers=headers, params=params)

    def create_leadership_member(self, organization_id, payload, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/leadership-members",
                             payload, headers)

    def list_leadership_members(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/leadership-members",
                             headers=headers, params=params)

    def list_demographic_records(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/demographic-records",
                             headers=headers, params=params)

    # --- Transparency seals -------------------------------------------------
    def award_seal(self, organization_id, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/seals", {}, headers)

    def list_seals(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/seals",
                             headers=headers, params=params)

    def renew_seal(self, seal_id, headers):
        return self._request("POST", f"/nonprofits/seals/{seal_id}/renew", {}, headers)

    # --- Grant --------------------------------------------------------------
    def create_grant(self, organization_id, payload, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/grants", payload, headers)

    def list_grants(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/grants",
                             headers=headers, params=params)

    def match_grant_recipient(self, grant_id, payload, headers):
        return self._request("POST", f"/nonprofits/grants/{grant_id}/match-recipient", payload, headers)

    # --- DataLicense --------------------------------------------------------
    def create_license(self, organization_id, payload, headers):
        return self._request("POST", f"/nonprofits/organizations/{organization_id}/licenses", payload, headers)

    def list_licenses(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/licenses",
                             headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/nonprofits/licenses/{license_id}", headers=headers)

    def activate_license(self, license_id, headers):
        return self._request("POST", f"/nonprofits/licenses/{license_id}/activate", {}, headers)

    def post_usage_event(self, license_id, payload, headers):
        return self._request("POST", f"/nonprofits/licenses/{license_id}/usage-events", payload, headers)

    def void_usage_event(self, license_id, event_id, headers):
        return self._request("POST", f"/nonprofits/licenses/{license_id}/usage-events/{event_id}/void",
                             {}, headers)

    def list_usage_events(self, license_id, headers, params=None):
        return self._request("GET", f"/nonprofits/licenses/{license_id}/usage-events",
                             headers=headers, params=params)

    # --- Filings ------------------------------------------------------------
    def create_filing(self, payload, headers):
        return self._request("POST", "/nonprofits/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/nonprofits/filings/{filing_id}", headers=headers)

    def extract_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/nonprofits/filings/{filing_id}/extract", payload, headers)

    def normalize_filing(self, filing_id, headers):
        return self._request("POST", f"/nonprofits/filings/{filing_id}/normalize", {}, headers)

    def void_filing(self, filing_id, headers):
        return self._request("POST", f"/nonprofits/filings/{filing_id}/void", {}, headers)

    def list_organization_filings(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/filings",
                             headers=headers, params=params)

    def list_extracted_fields(self, filing_id, headers, params=None):
        return self._request("GET", f"/nonprofits/filings/{filing_id}/extracted-fields",
                             headers=headers, params=params)

    def get_extracted_field(self, field_id, headers):
        return self._request("GET", f"/nonprofits/extracted-fields/{field_id}", headers=headers)

    # --- Correction requests ------------------------------------------------
    def create_correction_request(self, field_id, payload, headers):
        return self._request("POST", f"/nonprofits/extracted-fields/{field_id}/correction-requests",
                             payload, headers)

    def list_field_correction_requests(self, field_id, headers, params=None):
        return self._request("GET", f"/nonprofits/extracted-fields/{field_id}/correction-requests",
                             headers=headers, params=params)

    def list_organization_correction_requests(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/correction-requests",
                             headers=headers, params=params)

    def decide_correction_request(self, request_id, payload, headers):
        return self._request("POST", f"/nonprofits/correction-requests/{request_id}/decide",
                             payload, headers)

    # --- Identity resolution ------------------------------------------------
    def create_identity_case(self, payload, headers):
        return self._request("POST", "/nonprofits/identity-cases", payload, headers)

    def finalize_identity_case(self, case_id, payload, headers):
        return self._request("POST", f"/nonprofits/identity-cases/{case_id}/finalize", payload, headers)

    def list_identity_cases(self, organization_id, headers, params=None):
        return self._request("GET", f"/nonprofits/organizations/{organization_id}/identity-cases",
                             headers=headers, params=params)

    # --- Funder research ----------------------------------------------------
    def get_prospects(self, headers, params=None):
        return self._request("GET", "/nonprofits/funder-research/prospects", headers=headers, params=params)

    # --- Test-driving clock -------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)


api_client = ApiClient()
