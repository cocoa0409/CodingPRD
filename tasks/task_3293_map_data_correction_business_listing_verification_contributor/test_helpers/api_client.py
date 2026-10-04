"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- platform plumbing ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def sweep_verification_expired(self, headers):
        return self._request("POST", "/v1/verification-attempts/sweep-expired", {}, headers)

    def sweep_listings_reverify(self, headers):
        return self._request("POST", "/v1/business-listings/sweep-reverify", {}, headers)

    def sweep_routing_activation(self, headers):
        return self._request("POST", "/v1/routing-updates/sweep-activation", {}, headers)

    def sweep_routing_expired(self, headers):
        return self._request("POST", "/v1/routing-updates/sweep-expired", {}, headers)

    def sweep_reviews_fake_detection(self, headers):
        return self._request("POST", "/v1/reviews/sweep-fake-detection", {}, headers)

    # --- regions ---
    def create_region(self, payload, headers):
        return self._request("POST", "/v1/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/v1/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/v1/regions/{region_id}", headers=headers)

    # --- contributors ---
    def create_contributor(self, payload, headers):
        return self._request("POST", "/v1/contributors", payload, headers)

    def list_contributors(self, headers, params=None):
        return self._request("GET", "/v1/contributors", headers=headers, params=params)

    def get_contributor(self, contributor_id, headers):
        return self._request("GET", f"/v1/contributors/{contributor_id}", headers=headers)

    def list_contributor_grants(self, contributor_id, headers, params=None):
        return self._request(
            "GET", f"/v1/contributors/{contributor_id}/grants", headers=headers, params=params
        )

    def create_contributor_grant(self, payload, headers):
        return self._request("POST", "/v1/contributor-grants", payload, headers)

    def revoke_contributor_grant(self, grant_id, headers):
        return self._request("POST", f"/v1/contributor-grants/{grant_id}/revoke", {}, headers)

    # --- business listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/v1/business-listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/v1/business-listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/v1/business-listings/{listing_id}", headers=headers)

    def update_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/v1/business-listings/{listing_id}", payload, headers)

    def claim_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/business-listings/{listing_id}/claim", payload, headers)

    def suspend_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"/v1/business-listings/{listing_id}/suspend", payload, headers
        )

    def require_reverify(self, listing_id, headers):
        return self._request(
            "POST", f"/v1/business-listings/{listing_id}/require-reverify", {}, headers
        )

    def list_listing_map_edits(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/v1/business-listings/{listing_id}/map-edits", headers=headers, params=params
        )

    def list_listing_reviews(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/v1/business-listings/{listing_id}/reviews", headers=headers, params=params
        )

    def list_listing_hours_observations(self, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/business-listings/{listing_id}/hours-observations",
            headers=headers,
            params=params,
        )

    def resolve_listing_hours(self, listing_id, payload, headers):
        return self._request(
            "POST", f"/v1/business-listings/{listing_id}/hours/resolve", payload, headers
        )

    def list_listing_suspension_cases(self, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/business-listings/{listing_id}/suspension-cases",
            headers=headers,
            params=params,
        )

    # --- verification attempts ---
    def create_verification_attempt(self, payload, headers):
        return self._request("POST", "/v1/verification-attempts", payload, headers)

    def list_verification_attempts(self, headers, params=None):
        return self._request("GET", "/v1/verification-attempts", headers=headers, params=params)

    def get_verification_attempt(self, attempt_id, headers):
        return self._request("GET", f"/v1/verification-attempts/{attempt_id}", headers=headers)

    def submit_verification_code(self, attempt_id, payload, headers):
        return self._request(
            "POST", f"/v1/verification-attempts/{attempt_id}/submit-code", payload, headers
        )

    def cancel_verification_attempt(self, attempt_id, headers):
        return self._request(
            "POST", f"/v1/verification-attempts/{attempt_id}/cancel", {}, headers
        )

    # --- map edits ---
    def create_map_edit(self, payload, headers):
        return self._request("POST", "/v1/map-edits", payload, headers)

    def list_map_edits(self, headers, params=None):
        return self._request("GET", "/v1/map-edits", headers=headers, params=params)

    def get_map_edit(self, edit_id, headers):
        return self._request("GET", f"/v1/map-edits/{edit_id}", headers=headers)

    def supply_edit_info(self, edit_id, payload, headers):
        return self._request("POST", f"/v1/map-edits/{edit_id}/supply-info", payload, headers)

    def revert_map_edit(self, edit_id, headers):
        return self._request("POST", f"/v1/map-edits/{edit_id}/revert", {}, headers)

    def list_map_edit_review_tickets(self, edit_id, headers, params=None):
        return self._request(
            "GET", f"/v1/map-edits/{edit_id}/review-tickets", headers=headers, params=params
        )

    # --- review tickets ---
    def create_review_ticket(self, payload, headers):
        return self._request("POST", "/v1/review-tickets", payload, headers)

    def list_review_tickets(self, headers, params=None):
        return self._request("GET", "/v1/review-tickets", headers=headers, params=params)

    def get_review_ticket(self, ticket_id, headers):
        return self._request("GET", f"/v1/review-tickets/{ticket_id}", headers=headers)

    def claim_review_ticket(self, ticket_id, headers):
        return self._request("POST", f"/v1/review-tickets/{ticket_id}/claim", {}, headers)

    def resolve_review_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/v1/review-tickets/{ticket_id}/resolve", payload, headers)

    def escalate_review_ticket(self, ticket_id, headers):
        return self._request("POST", f"/v1/review-tickets/{ticket_id}/escalate", {}, headers)

    # --- user reviews & flags ---
    def create_review(self, payload, headers):
        return self._request("POST", "/v1/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/v1/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/v1/reviews/{review_id}", headers=headers)

    def flag_review(self, review_id, payload, headers):
        return self._request("POST", f"/v1/reviews/{review_id}/flag", payload, headers)

    def list_review_flags(self, headers, params=None):
        return self._request("GET", "/v1/review-flags", headers=headers, params=params)

    def get_review_flag(self, flag_id, headers):
        return self._request("GET", f"/v1/review-flags/{flag_id}", headers=headers)

    def dismiss_review_flag(self, flag_id, headers):
        return self._request("POST", f"/v1/review-flags/{flag_id}/dismiss", {}, headers)

    def list_review_flag_tickets(self, flag_id, headers, params=None):
        return self._request(
            "GET", f"/v1/review-flags/{flag_id}/review-tickets", headers=headers, params=params
        )

    # --- suspension cases ---
    def list_suspension_cases(self, headers, params=None):
        return self._request("GET", "/v1/suspension-cases", headers=headers, params=params)

    def get_suspension_case(self, case_id, headers):
        return self._request("GET", f"/v1/suspension-cases/{case_id}", headers=headers)

    def appeal_suspension_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/v1/suspension-cases/{case_id}/appeal", payload, headers
        )

    def start_appeal_review(self, case_id, headers):
        return self._request(
            "POST", f"/v1/suspension-cases/{case_id}/start-appeal-review", {}, headers
        )

    def decide_suspension_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/v1/suspension-cases/{case_id}/decide", payload, headers
        )

    # --- hours observations ---
    def create_hours_observation(self, payload, headers):
        return self._request("POST", "/v1/hours-observations", payload, headers)

    def get_hours_observation(self, observation_id, headers):
        return self._request("GET", f"/v1/hours-observations/{observation_id}", headers=headers)

    # --- imagery tasks ---
    def create_imagery_task(self, payload, headers):
        return self._request("POST", "/v1/imagery-tasks", payload, headers)

    def list_imagery_tasks(self, headers, params=None):
        return self._request("GET", "/v1/imagery-tasks", headers=headers, params=params)

    def get_imagery_task(self, task_id, headers):
        return self._request("GET", f"/v1/imagery-tasks/{task_id}", headers=headers)

    def schedule_imagery_task(self, task_id, headers):
        return self._request("POST", f"/v1/imagery-tasks/{task_id}/schedule", {}, headers)

    def capture_imagery_task(self, task_id, payload, headers):
        return self._request("POST", f"/v1/imagery-tasks/{task_id}/capture", payload, headers)

    def blur_complete_imagery_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/v1/imagery-tasks/{task_id}/blur-complete", payload, headers
        )

    def publish_imagery_task(self, task_id, headers):
        return self._request("POST", f"/v1/imagery-tasks/{task_id}/publish", {}, headers)

    def cancel_imagery_task(self, task_id, headers):
        return self._request("POST", f"/v1/imagery-tasks/{task_id}/cancel", {}, headers)

    # --- routing updates ---
    def create_routing_update(self, payload, headers):
        return self._request("POST", "/v1/routing-updates", payload, headers)

    def list_routing_updates(self, headers, params=None):
        return self._request("GET", "/v1/routing-updates", headers=headers, params=params)

    def get_routing_update(self, update_id, headers):
        return self._request("GET", f"/v1/routing-updates/{update_id}", headers=headers)

    def validate_routing_update(self, update_id, headers):
        return self._request("POST", f"/v1/routing-updates/{update_id}/validate", {}, headers)

    def activate_routing_update(self, update_id, headers):
        return self._request("POST", f"/v1/routing-updates/{update_id}/activate", {}, headers)

    def cancel_routing_update(self, update_id, headers):
        return self._request("POST", f"/v1/routing-updates/{update_id}/cancel", {}, headers)


api_client = ApiClient()
