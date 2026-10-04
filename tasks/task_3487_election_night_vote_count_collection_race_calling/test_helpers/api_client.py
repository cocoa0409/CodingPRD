"""API client: one method per endpoint defined in the PRD (§4).

Every method takes explicit `headers` (see test_users.py) and returns the raw
requests.Response so tests can assert status codes; fixtures wrap these with
get_success_data().
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving; PRD §2.4)
    # ------------------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ------------------------------------------------------------------
    # Election events and posture
    # ------------------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/election-events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/election-events/{event_id}", headers=headers)

    def transition_posture(self, event_id, target_posture, headers):
        return self._request(
            "POST", f"/election-events/{event_id}/posture-transitions",
            {"target_posture": target_posture}, headers,
        )

    # ------------------------------------------------------------------
    # Counties
    # ------------------------------------------------------------------
    def create_county(self, event_id, payload, headers):
        return self._request("POST", f"/election-events/{event_id}/counties", payload, headers)

    def list_counties(self, event_id, headers, params=None):
        return self._request("GET", f"/election-events/{event_id}/counties", headers=headers, params=params)

    def get_county(self, county_id, headers):
        return self._request("GET", f"/counties/{county_id}", headers=headers)

    # ------------------------------------------------------------------
    # Contests
    # ------------------------------------------------------------------
    def create_contest(self, event_id, payload, headers):
        return self._request("POST", f"/election-events/{event_id}/contests", payload, headers)

    def list_contests(self, event_id, headers, params=None):
        return self._request("GET", f"/election-events/{event_id}/contests", headers=headers, params=params)

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}", headers=headers)

    def patch_contest(self, contest_id, payload, headers):
        return self._request("PATCH", f"/contests/{contest_id}", payload, headers)

    # ------------------------------------------------------------------
    # County links (contest geography)
    # ------------------------------------------------------------------
    def create_county_link(self, contest_id, county_id, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/county-links",
            {"county_id": county_id}, headers,
        )

    def list_contest_county_links(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/county-links", headers=headers, params=params)

    def list_county_links_for_county(self, county_id, headers, params=None):
        return self._request("GET", f"/counties/{county_id}/county-links", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------
    def create_candidate(self, contest_id, payload, headers):
        return self._request("POST", f"/contests/{contest_id}/candidates", payload, headers)

    def list_candidates(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/candidates", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Feed sources
    # ------------------------------------------------------------------
    def create_feed_source(self, event_id, payload, headers):
        return self._request("POST", f"/election-events/{event_id}/feed-sources", payload, headers)

    def list_feed_sources(self, event_id, headers, params=None):
        return self._request("GET", f"/election-events/{event_id}/feed-sources", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Stringers and assignments
    # ------------------------------------------------------------------
    def create_stringer(self, payload, headers):
        return self._request("POST", "/stringers", payload, headers)

    def get_stringer(self, stringer_id, headers):
        return self._request("GET", f"/stringers/{stringer_id}", headers=headers)

    def create_assignment(self, event_id, payload, headers):
        return self._request("POST", f"/election-events/{event_id}/assignments", payload, headers)

    def list_event_assignments(self, event_id, headers, params=None):
        return self._request("GET", f"/election-events/{event_id}/assignments", headers=headers, params=params)

    def list_stringer_assignments(self, stringer_id, headers, params=None):
        return self._request("GET", f"/stringers/{stringer_id}/assignments", headers=headers, params=params)

    def list_county_assignments(self, county_id, headers, params=None):
        return self._request("GET", f"/counties/{county_id}/assignments", headers=headers, params=params)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", {}, headers)

    def assignment_status_action(self, assignment_id, action, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/status-actions",
            {"action": action}, headers,
        )

    # ------------------------------------------------------------------
    # Vote reports
    # ------------------------------------------------------------------
    def create_vote_report(self, contest_id, payload, headers):
        return self._request("POST", f"/contests/{contest_id}/vote-reports", payload, headers)

    def list_contest_vote_reports(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/vote-reports", headers=headers, params=params)

    def list_county_vote_reports(self, county_id, headers, params=None):
        return self._request("GET", f"/counties/{county_id}/vote-reports", headers=headers, params=params)

    def list_stringer_vote_reports(self, stringer_id, headers, params=None):
        return self._request("GET", f"/stringers/{stringer_id}/vote-reports", headers=headers, params=params)

    def review_vote_report(self, report_id, decision, headers):
        return self._request(
            "POST", f"/vote-reports/{report_id}/review-decisions",
            {"decision": decision}, headers,
        )

    def resubmit_vote_report(self, report_id, payload, headers):
        return self._request("POST", f"/vote-reports/{report_id}/resubmit", payload, headers)

    # ------------------------------------------------------------------
    # Tabulation board
    # ------------------------------------------------------------------
    def get_tabulation(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}/tabulation", headers=headers)

    # ------------------------------------------------------------------
    # Race calls
    # ------------------------------------------------------------------
    def create_call(self, contest_id, payload, headers):
        return self._request("POST", f"/contests/{contest_id}/calls", payload, headers)

    def list_calls(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/calls", headers=headers, params=params)

    def decide_call(self, call_id, action, headers, reason=None):
        payload = {"action": action}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/calls/{call_id}/decisions", payload, headers)

    # ------------------------------------------------------------------
    # Recount cases
    # ------------------------------------------------------------------
    def create_recount_case(self, contest_id, headers, note=None):
        payload = {}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/contests/{contest_id}/recount-cases", payload, headers)

    def list_recount_cases(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/recount-cases", headers=headers, params=params)

    def decide_recount_case(self, case_id, action, headers, outcome=None, note=None):
        payload = {"action": action}
        if outcome is not None:
            payload["outcome"] = outcome
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/recount-cases/{case_id}/decisions", payload, headers)

    # ------------------------------------------------------------------
    # Coverage decisions
    # ------------------------------------------------------------------
    def create_coverage_decision(self, event_id, payload, headers):
        return self._request("POST", f"/election-events/{event_id}/coverage-decisions", payload, headers)

    def list_event_coverage_decisions(self, event_id, headers, params=None):
        return self._request("GET", f"/election-events/{event_id}/coverage-decisions", headers=headers, params=params)

    def list_contest_coverage_decisions(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/coverage-decisions", headers=headers, params=params)

    def review_coverage_decision(self, decision_id, decision, headers):
        return self._request(
            "POST", f"/coverage-decisions/{decision_id}/review",
            {"decision": decision}, headers,
        )

    def revise_coverage_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/coverage-decisions/{decision_id}/revise", payload, headers)

    # ------------------------------------------------------------------
    # Media customers, deliveries, invoices
    # ------------------------------------------------------------------
    def create_media_customer(self, payload, headers):
        return self._request("POST", "/media-customers", payload, headers)

    def get_media_customer(self, customer_id, headers):
        return self._request("GET", f"/media-customers/{customer_id}", headers=headers)

    def list_customer_deliveries(self, customer_id, headers, params=None):
        return self._request("GET", f"/media-customers/{customer_id}/deliveries", headers=headers, params=params)

    def list_contest_deliveries(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/deliveries", headers=headers, params=params)

    def create_invoice(self, customer_id, period, headers):
        return self._request(
            "POST", f"/media-customers/{customer_id}/invoices",
            {"period": period}, headers,
        )

    def list_invoices(self, customer_id, headers, params=None):
        return self._request("GET", f"/media-customers/{customer_id}/invoices", headers=headers, params=params)


api_client = ApiClient()
