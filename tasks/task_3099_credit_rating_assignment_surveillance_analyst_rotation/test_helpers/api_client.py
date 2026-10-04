"""API client: one method per endpoint the service exposes.

All paths are mounted under `/rating-agency`. Methods return the raw
requests.Response so tests can assert status codes directly.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rating-agency"


class ApiClient(GenericApiClient):
    # ─── Logical clock ───
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ─── Methodologies ───
    def create_methodology(self, payload, headers):
        return self._request("POST", f"{PREFIX}/methodologies", payload, headers)

    def list_methodologies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/methodologies", headers=headers, params=params)

    def get_methodology(self, methodology_id, headers):
        return self._request("GET", f"{PREFIX}/methodologies/{methodology_id}", headers=headers)

    def publish_methodology(self, methodology_id, headers):
        return self._request(
            "POST", f"{PREFIX}/methodologies/{methodology_id}/publish", {}, headers
        )

    def publish_methodology_disclosure(self, methodology_id, headers):
        return self._request(
            "POST", f"{PREFIX}/methodologies/{methodology_id}/publish-disclosure", {}, headers
        )

    def supersede_methodology(self, methodology_id, headers):
        return self._request(
            "POST", f"{PREFIX}/methodologies/{methodology_id}/supersede", {}, headers
        )

    # ─── Rated entities ───
    def create_rated_entity(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rated-entities", payload, headers)

    def list_rated_entities(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rated-entities", headers=headers, params=params)

    def get_rated_entity(self, rated_entity_id, headers):
        return self._request("GET", f"{PREFIX}/rated-entities/{rated_entity_id}", headers=headers)

    # ─── Engagement letters ───
    def create_engagement_letter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/engagement-letters", payload, headers)

    def list_engagement_letters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/engagement-letters", headers=headers, params=params)

    def get_engagement_letter(self, engagement_letter_id, headers):
        return self._request(
            "GET", f"{PREFIX}/engagement-letters/{engagement_letter_id}", headers=headers
        )

    def submit_engagement_letter(self, engagement_letter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engagement-letters/{engagement_letter_id}/submit", {}, headers
        )

    def activate_engagement_letter(self, engagement_letter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engagement-letters/{engagement_letter_id}/activate", {}, headers
        )

    def revert_engagement_letter_to_draft(self, engagement_letter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engagement-letters/{engagement_letter_id}/revert-to-draft", {}, headers
        )

    def terminate_engagement_letter(self, engagement_letter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engagement-letters/{engagement_letter_id}/terminate", {}, headers
        )

    # ─── Rating requests ───
    def create_rating_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rating-requests", payload, headers)

    def list_rating_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rating-requests", headers=headers, params=params)

    def get_rating_request(self, rating_request_id, headers):
        return self._request("GET", f"{PREFIX}/rating-requests/{rating_request_id}", headers=headers)

    def open_screening(self, rating_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-requests/{rating_request_id}/open-screening", {}, headers
        )

    def return_request_to_submitted(self, rating_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-requests/{rating_request_id}/return-to-submitted", {}, headers
        )

    def confirm_request_team(self, rating_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-requests/{rating_request_id}/confirm-team", {}, headers
        )

    def withdraw_rating_request(self, rating_request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-requests/{rating_request_id}/withdraw", {}, headers
        )

    # ─── Analysts ───
    def create_analyst(self, payload, headers):
        return self._request("POST", f"{PREFIX}/analysts", payload, headers)

    def list_analysts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/analysts", headers=headers, params=params)

    def get_analyst(self, analyst_id, headers):
        return self._request("GET", f"{PREFIX}/analysts/{analyst_id}", headers=headers)

    def list_analyst_team_assignments(self, analyst_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/analysts/{analyst_id}/team-assignments", headers=headers, params=params
        )

    def list_analyst_votes(self, analyst_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/analysts/{analyst_id}/votes", headers=headers, params=params
        )

    def list_analyst_conflict_screenings(self, analyst_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/analysts/{analyst_id}/conflict-screenings", headers=headers, params=params
        )

    def depart_analyst(self, analyst_id, payload, headers):
        return self._request("POST", f"{PREFIX}/analysts/{analyst_id}/depart", payload, headers)

    # ─── Team assignments ───
    def create_team_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/team-assignments", payload, headers)

    def list_team_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/team-assignments", headers=headers, params=params)

    def get_team_assignment(self, team_assignment_id, headers):
        return self._request("GET", f"{PREFIX}/team-assignments/{team_assignment_id}", headers=headers)

    def list_team_assignment_screenings(self, team_assignment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/team-assignments/{team_assignment_id}/screenings",
            headers=headers, params=params,
        )

    def screen_team_assignment(self, team_assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/team-assignments/{team_assignment_id}/screen", {}, headers
        )

    def return_team_assignment_to_proposed(self, team_assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/team-assignments/{team_assignment_id}/return-to-proposed", {}, headers
        )

    def confirm_team_assignment(self, team_assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/team-assignments/{team_assignment_id}/confirm", payload, headers
        )

    def revoke_team_assignment(self, team_assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/team-assignments/{team_assignment_id}/revoke", payload, headers
        )

    # ─── Conflict screenings ───
    def create_conflict_screening(self, payload, headers):
        return self._request("POST", f"{PREFIX}/conflict-screenings", payload, headers)

    def list_conflict_screenings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/conflict-screenings", headers=headers, params=params)

    # ─── Rating committees ───
    def create_rating_committee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rating-committees", payload, headers)

    def list_rating_committees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rating-committees", headers=headers, params=params)

    def get_rating_committee(self, rating_committee_id, headers):
        return self._request("GET", f"{PREFIX}/rating-committees/{rating_committee_id}", headers=headers)

    def list_committee_votes(self, rating_committee_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rating-committees/{rating_committee_id}/votes", headers=headers, params=params
        )

    def open_committee_session(self, rating_committee_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-committees/{rating_committee_id}/open-session", {}, headers
        )

    def cast_committee_vote(self, rating_committee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-committees/{rating_committee_id}/votes", payload, headers
        )

    def decide_committee(self, rating_committee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-committees/{rating_committee_id}/decide", payload, headers
        )

    def reopen_committee(self, rating_committee_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-committees/{rating_committee_id}/reopen", {}, headers
        )

    def redecide_committee(self, rating_committee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-committees/{rating_committee_id}/redecide", payload, headers
        )

    # ─── Rating decisions ───
    def list_rating_decisions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rating-decisions", headers=headers, params=params)

    def get_rating_decision(self, rating_decision_id, headers):
        return self._request("GET", f"{PREFIX}/rating-decisions/{rating_decision_id}", headers=headers)

    def open_appeal_window(self, rating_decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-decisions/{rating_decision_id}/open-appeal-window", {}, headers
        )

    def publish_decision(self, rating_decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-decisions/{rating_decision_id}/publish", payload, headers
        )

    def withdraw_decision(self, rating_decision_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-decisions/{rating_decision_id}/withdraw", {}, headers
        )

    def file_appeal(self, rating_decision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-decisions/{rating_decision_id}/appeals", payload, headers
        )

    # ─── Issuer appeals ───
    def list_issuer_appeals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/issuer-appeals", headers=headers, params=params)

    def get_issuer_appeal(self, issuer_appeal_id, headers):
        return self._request("GET", f"{PREFIX}/issuer-appeals/{issuer_appeal_id}", headers=headers)

    def resolve_issuer_appeal(self, issuer_appeal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/issuer-appeals/{issuer_appeal_id}/resolve", payload, headers
        )

    # ─── Surveillance reviews ───
    def create_surveillance_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/surveillance-reviews", payload, headers)

    def list_surveillance_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/surveillance-reviews", headers=headers, params=params)

    def get_surveillance_review(self, surveillance_review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/surveillance-reviews/{surveillance_review_id}", headers=headers
        )

    def start_surveillance_review(self, surveillance_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/surveillance-reviews/{surveillance_review_id}/start", {}, headers
        )

    def complete_surveillance_review(self, surveillance_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/surveillance-reviews/{surveillance_review_id}/complete", {}, headers
        )

    def reopen_surveillance_review(self, surveillance_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/surveillance-reviews/{surveillance_review_id}/reopen", {}, headers
        )

    # ─── Rating action events ───
    def create_rating_action_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rating-action-events", payload, headers)

    def list_rating_action_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rating-action-events", headers=headers, params=params)

    def get_rating_action_event(self, rating_action_event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rating-action-events/{rating_action_event_id}", headers=headers
        )

    def apply_rating_action_event(self, rating_action_event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-action-events/{rating_action_event_id}/apply", {}, headers
        )

    def cancel_rating_action_event(self, rating_action_event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rating-action-events/{rating_action_event_id}/cancel", {}, headers
        )

    # ─── Compensation records ───
    def create_compensation_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compensation-records", payload, headers)

    def list_compensation_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/compensation-records", headers=headers, params=params)

    def get_compensation_record(self, compensation_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/compensation-records/{compensation_record_id}", headers=headers
        )

    def approve_compensation_record(self, compensation_record_id, headers):
        return self._request(
            "POST", f"{PREFIX}/compensation-records/{compensation_record_id}/approve", {}, headers
        )

    def pay_compensation_record(self, compensation_record_id, headers):
        return self._request(
            "POST", f"{PREFIX}/compensation-records/{compensation_record_id}/pay", {}, headers
        )

    def revise_compensation_record(self, compensation_record_id, headers):
        return self._request(
            "POST", f"{PREFIX}/compensation-records/{compensation_record_id}/revise", {}, headers
        )

    # ─── Look-back reviews ───
    def create_look_back_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/look-back-reviews", payload, headers)

    def list_look_back_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/look-back-reviews", headers=headers, params=params)

    def get_look_back_review(self, look_back_review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/look-back-reviews/{look_back_review_id}", headers=headers
        )

    def start_look_back_review(self, look_back_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/look-back-reviews/{look_back_review_id}/start", {}, headers
        )

    def close_look_back_review(self, look_back_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/look-back-reviews/{look_back_review_id}/close", {}, headers
        )

    # ─── Review slots ───
    def create_review_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/review-slots", payload, headers)

    def list_review_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/review-slots", headers=headers, params=params)

    def get_review_slot(self, review_slot_id, headers):
        return self._request("GET", f"{PREFIX}/review-slots/{review_slot_id}", headers=headers)

    def cancel_review_slot(self, review_slot_id, headers):
        return self._request("POST", f"{PREFIX}/review-slots/{review_slot_id}/cancel", {}, headers)

    # ─── Appearance reconciliations ───
    def create_appearance_reconciliation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appearance-reconciliations", payload, headers)

    def list_appearance_reconciliations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/appearance-reconciliations", headers=headers, params=params
        )

    def get_appearance_reconciliation(self, appearance_reconciliation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/appearance-reconciliations/{appearance_reconciliation_id}",
            headers=headers,
        )

    def confirm_appearance_breach(self, appearance_reconciliation_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/appearance-reconciliations/{appearance_reconciliation_id}/confirm-breach",
            {}, headers,
        )

    def appeal_appearance_reconciliation(self, appearance_reconciliation_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/appearance-reconciliations/{appearance_reconciliation_id}/appeal",
            {}, headers,
        )

    def clear_appearance_reconciliation(self, appearance_reconciliation_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/appearance-reconciliations/{appearance_reconciliation_id}/clear",
            {}, headers,
        )


api_client = ApiClient()