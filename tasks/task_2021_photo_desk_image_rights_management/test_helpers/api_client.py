"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Photographers (PRD §3.1) ---
    def create_photographer(self, payload, headers):
        return self._request("POST", "/photographers", payload, headers)

    def get_photographer(self, photographer_id, headers):
        return self._request("GET", f"/photographers/{photographer_id}", headers=headers)

    def suspend_photographer(self, photographer_id, headers):
        return self._request("POST", f"/photographers/{photographer_id}/suspend", {}, headers)

    def reactivate_photographer(self, photographer_id, headers):
        return self._request("POST", f"/photographers/{photographer_id}/reactivate", {}, headers)

    def list_photographer_payment_runs(self, photographer_id, headers, params=None):
        return self._request("GET", f"/photographers/{photographer_id}/payment-runs", headers=headers, params=params)

    def create_payment_run(self, photographer_id, payload, headers):
        return self._request("POST", f"/photographers/{photographer_id}/payment-runs", payload, headers)

    # --- Story requests (PRD §3.2) ---
    def create_story_request(self, payload, headers):
        return self._request("POST", "/story-requests", payload, headers)

    def get_story_request(self, story_id, headers):
        return self._request("GET", f"/story-requests/{story_id}", headers=headers)

    def decide_story_request(self, story_id, payload, headers):
        return self._request("POST", f"/story-requests/{story_id}/decide", payload, headers)

    def cancel_story_request(self, story_id, headers):
        return self._request("POST", f"/story-requests/{story_id}/cancel", {}, headers)

    # --- Assignments (PRD §3.4) ---
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def submit_assignment_image(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/images", payload, headers)

    def list_assignment_images(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/images", headers=headers, params=params)

    def submit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/submit", {}, headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def request_revision(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/request-revision", payload, headers)

    def cancel_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", payload or {}, headers)

    # --- Images (PRD §3.3) ---
    def ingest_image(self, payload, headers):
        return self._request("POST", "/images", payload, headers)

    def list_images(self, headers, params=None):
        return self._request("GET", "/images", headers=headers, params=params)

    def get_image(self, image_id, headers):
        return self._request("GET", f"/images/{image_id}", headers=headers)

    def clear_image(self, image_id, headers):
        return self._request("POST", f"/images/{image_id}/clear", {}, headers)

    def archive_image(self, image_id, headers):
        return self._request("POST", f"/images/{image_id}/archive", {}, headers)

    def set_embargo(self, image_id, payload, headers):
        return self._request("PUT", f"/images/{image_id}/embargo", payload, headers)

    def reuse_check(self, image_id, headers, params=None):
        return self._request("GET", f"/images/{image_id}/reuse-check", headers=headers, params=params)

    # --- Usage runs (PRD §3.7) ---
    def create_usage_run(self, image_id, payload, headers):
        return self._request("POST", f"/images/{image_id}/usage-runs", payload, headers)

    def list_image_usage_runs(self, image_id, headers, params=None):
        return self._request("GET", f"/images/{image_id}/usage-runs", headers=headers, params=params)

    # --- Licenses (PRD §3.5) ---
    def create_license(self, image_id, payload, headers):
        return self._request("POST", f"/images/{image_id}/licenses", payload, headers)

    def list_image_licenses(self, image_id, headers, params=None):
        return self._request("GET", f"/images/{image_id}/licenses", headers=headers, params=params)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_license_usage_runs(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/usage-runs", headers=headers, params=params)

    def activate_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/activate", {}, headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/revoke", {}, headers)

    # --- Releases (PRD §3.6) ---
    def create_release(self, image_id, payload, headers):
        return self._request("POST", f"/images/{image_id}/releases", payload, headers)

    def list_image_releases(self, image_id, headers, params=None):
        return self._request("GET", f"/images/{image_id}/releases", headers=headers, params=params)

    def revoke_release(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/revoke", {}, headers)

    # --- Infringement claims (PRD §3.8) ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/infringement-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/infringement-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/infringement-claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/infringement-claims/{claim_id}/review", {}, headers)

    def offer_settlement(self, claim_id, payload, headers):
        return self._request("POST", f"/infringement-claims/{claim_id}/offer", payload, headers)

    def counter_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/infringement-claims/{claim_id}/counter", payload, headers)

    def escalate_claim(self, claim_id, headers):
        return self._request("POST", f"/infringement-claims/{claim_id}/escalate", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/infringement-claims/{claim_id}/resolve", payload, headers)

    # --- Payment runs (PRD §3.9) ---
    def get_payment_run(self, run_id, headers):
        return self._request("GET", f"/payment-runs/{run_id}", headers=headers)

    def approve_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/approve", {}, headers)

    def pay_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/pay", {}, headers)

    def void_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/void", {}, headers)

    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
