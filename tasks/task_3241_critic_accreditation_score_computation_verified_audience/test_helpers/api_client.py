"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- publications ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/publications", payload, headers)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/publications/{publication_id}",
                             headers=headers)

    def transition_publication(self, publication_id, payload, headers):
        return self._request("POST", f"/publications/{publication_id}/transition",
                             payload, headers)

    def list_publication_critics(self, publication_id, headers, params=None):
        return self._request("GET", f"/publications/{publication_id}/critics",
                             headers=headers, params=params)

    # --- critics ---
    def create_critic(self, payload, headers):
        return self._request("POST", "/critics", payload, headers)

    def get_critic(self, critic_id, headers):
        return self._request("GET", f"/critics/{critic_id}", headers=headers)

    def transition_critic(self, critic_id, payload, headers):
        return self._request("POST", f"/critics/{critic_id}/transition",
                             payload, headers)

    # --- accreditation reviews ---
    def create_accreditation_review(self, payload, headers):
        return self._request("POST", "/accreditation-reviews", payload, headers)

    def list_accreditation_reviews(self, headers, params=None):
        return self._request("GET", "/accreditation-reviews",
                             headers=headers, params=params)

    def get_accreditation_review(self, review_id, headers):
        return self._request("GET", f"/accreditation-reviews/{review_id}",
                             headers=headers)

    def transition_accreditation_review(self, review_id, payload, headers):
        return self._request("POST",
                             f"/accreditation-reviews/{review_id}/transition",
                             payload, headers)

    # --- titles ---
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def update_title(self, title_id, payload, headers):
        return self._request("PATCH", f"/titles/{title_id}", payload, headers)

    def create_release(self, title_id, payload, headers):
        return self._request("POST", f"/titles/{title_id}/releases",
                             payload, headers)

    # --- releases ---
    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", headers=headers, params=params)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}", headers=headers)

    def transition_release(self, release_id, payload, headers):
        return self._request("POST", f"/releases/{release_id}/transition",
                             payload, headers)

    def recalculate_release_score(self, release_id, payload, headers):
        return self._request("POST",
                             f"/releases/{release_id}/score-recalculation",
                             payload, headers)

    def list_score_snapshots(self, release_id, headers, params=None):
        return self._request("GET", f"/releases/{release_id}/score-snapshots",
                             headers=headers, params=params)

    def list_bombing_incidents(self, release_id, headers, params=None):
        return self._request("GET", f"/releases/{release_id}/bombing-incidents",
                             headers=headers, params=params)

    # --- critic reviews ---
    def create_review(self, release_id, payload, headers):
        return self._request("POST", f"/releases/{release_id}/reviews",
                             payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def transition_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/transition",
                             payload, headers)

    # --- audience members ---
    def create_audience_member(self, payload, headers):
        return self._request("POST", "/audience-members", payload, headers)

    # --- ticket verifications ---
    def create_ticket_verification(self, release_id, payload, headers):
        return self._request("POST",
                             f"/releases/{release_id}/ticket-verifications",
                             payload, headers)

    def list_ticket_verifications(self, headers, params=None):
        return self._request("GET", "/ticket-verifications",
                             headers=headers, params=params)

    def get_ticket_verification(self, tv_id, headers):
        return self._request("GET", f"/ticket-verifications/{tv_id}",
                             headers=headers)

    def transition_ticket_verification(self, tv_id, payload, headers):
        return self._request("POST",
                             f"/ticket-verifications/{tv_id}/transition",
                             payload, headers)

    # --- audience ratings ---
    def create_audience_rating(self, release_id, payload, headers):
        return self._request("POST", f"/releases/{release_id}/audience-ratings",
                             payload, headers)

    def list_audience_ratings(self, headers, params=None):
        return self._request("GET", "/audience-ratings",
                             headers=headers, params=params)

    def get_audience_rating(self, rating_id, headers):
        return self._request("GET", f"/audience-ratings/{rating_id}",
                             headers=headers)

    def transition_audience_rating(self, rating_id, payload, headers):
        return self._request("POST",
                             f"/audience-ratings/{rating_id}/transition",
                             payload, headers)

    # --- bombing incidents ---
    def create_bombing_incident(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/bombing-incidents",
                             {}, headers)

    def transition_bombing_incident(self, incident_id, payload, headers):
        return self._request("POST",
                             f"/bombing-incidents/{incident_id}/transition",
                             payload, headers)

    # --- disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def transition_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/transition",
                             payload, headers)


api_client = ApiClient()
