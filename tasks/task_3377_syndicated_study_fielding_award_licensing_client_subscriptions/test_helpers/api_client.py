"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/research/_clock/set_current_utc", payload, headers)

    # --- Studies ---
    def create_study(self, payload, headers):
        return self._request("POST", "/research/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/research/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/research/studies/{study_id}", headers=headers)

    def study_state(self, study_id, payload, headers):
        return self._request("POST", f"/research/studies/{study_id}/state", payload, headers)

    # --- Methodology versions / factors ---
    def create_methodology_version(self, payload, headers):
        return self._request("POST", "/research/methodology-versions", payload, headers)

    def get_methodology_version(self, mv_id, headers):
        return self._request("GET", f"/research/methodology-versions/{mv_id}", headers=headers)

    def pin_methodology_version(self, mv_id, payload, headers):
        return self._request("POST", f"/research/methodology-versions/{mv_id}/pin", payload, headers)

    def list_methodology_factors(self, mv_id, headers, params=None):
        return self._request("GET", f"/research/methodology-versions/{mv_id}/factors", headers=headers, params=params)

    def list_study_methodology_versions(self, study_id, headers, params=None):
        return self._request("GET", f"/research/studies/{study_id}/methodology-versions", headers=headers, params=params)

    # --- Sample frames ---
    def create_sample_frame(self, payload, headers):
        return self._request("POST", "/research/sample-frames", payload, headers)

    def list_sample_frames(self, headers, params=None):
        return self._request("GET", "/research/sample-frames", headers=headers, params=params)

    def get_sample_frame(self, frame_id, headers):
        return self._request("GET", f"/research/sample-frames/{frame_id}", headers=headers)

    def sample_frame_state(self, frame_id, payload, headers):
        return self._request("POST", f"/research/sample-frames/{frame_id}/state", payload, headers)

    # --- Responses ---
    def create_response(self, payload, headers):
        return self._request("POST", "/research/responses", payload, headers)

    def list_frame_responses(self, frame_id, headers, params=None):
        return self._request("GET", f"/research/sample-frames/{frame_id}/responses", headers=headers, params=params)

    # --- Scoring / brand results ---
    def compute_scoring(self, study_id, headers):
        return self._request("POST", f"/research/studies/{study_id}/scoring/compute", {}, headers)

    def list_brand_results(self, headers, params=None):
        return self._request("GET", "/research/brand-results", headers=headers, params=params)

    def get_brand_result(self, brand_result_id, headers):
        return self._request("GET", f"/research/brand-results/{brand_result_id}", headers=headers)

    # --- Awards ---
    def determine_awards(self, study_id, headers):
        return self._request("POST", f"/research/studies/{study_id}/awards/determine", {}, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/research/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/research/awards/{award_id}", headers=headers)

    # --- Licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/research/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/research/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/research/licenses/{license_id}", headers=headers)

    def license_state(self, license_id, payload, headers):
        return self._request("POST", f"/research/licenses/{license_id}/state", payload, headers)

    # --- Usage audits ---
    def create_usage_audit(self, payload, headers):
        return self._request("POST", "/research/usage-audits", payload, headers)

    def list_license_audits(self, license_id, headers, params=None):
        return self._request("GET", f"/research/licenses/{license_id}/usage-audits", headers=headers, params=params)

    def usage_audit_state(self, audit_id, payload, headers):
        return self._request("POST", f"/research/usage-audits/{audit_id}/state", payload, headers)

    # --- Clients / brands ---
    def create_client(self, payload, headers):
        return self._request("POST", "/research/clients", payload, headers)

    def list_brand_clients(self, brand_id, headers, params=None):
        return self._request("GET", f"/research/brands/{brand_id}/clients", headers=headers, params=params)

    def create_brand(self, payload, headers):
        return self._request("POST", "/research/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/research/brands/{brand_id}", headers=headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/research/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/research/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/research/subscriptions/{subscription_id}", headers=headers)

    def subscription_state(self, subscription_id, payload, headers):
        return self._request("POST", f"/research/subscriptions/{subscription_id}/state", payload, headers)

    # --- Insights / press ---
    def get_diagnostics(self, study_id, headers):
        return self._request("GET", f"/research/studies/{study_id}/diagnostics", headers=headers)

    def get_benchmarking(self, study_id, headers):
        return self._request("GET", f"/research/studies/{study_id}/benchmarking", headers=headers)

    def get_press_kit(self, study_id, headers):
        return self._request("GET", f"/research/studies/{study_id}/press-kit", headers=headers)


api_client = ApiClient()
