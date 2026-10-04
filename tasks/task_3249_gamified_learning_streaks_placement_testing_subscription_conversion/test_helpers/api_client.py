"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Learner ──────────────────────────────────────────────────────────────
    def create_learner(self, payload, headers=None):
        return self._request("POST", "/learners", payload, headers)

    def get_learner(self, learner_id, headers):
        return self._request("GET", f"/learners/{learner_id}", headers=headers)

    def patch_learner(self, learner_id, payload, headers):
        return self._request("PATCH", f"/learners/{learner_id}", payload, headers)

    def list_learner_memberships(self, learner_id, headers, params=None):
        return self._request(
            "GET", f"/learners/{learner_id}/family-memberships",
            headers=headers, params=params,
        )

    # ── Course tree ──────────────────────────────────────────────────────────
    def create_course_unit(self, payload, headers):
        return self._request("POST", "/course-units", payload, headers)

    def get_course_unit(self, unit_id, headers):
        return self._request("GET", f"/course-units/{unit_id}", headers=headers)

    def list_unit_nodes(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/course-units/{unit_id}/nodes", headers=headers, params=params
        )

    def create_lesson_node(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/course-units/{unit_id}/nodes", payload, headers
        )

    def list_lesson_nodes(self, headers, params=None):
        return self._request("GET", "/lesson-nodes", headers=headers, params=params)

    def get_lesson_node(self, node_id, headers):
        return self._request("GET", f"/lesson-nodes/{node_id}", headers=headers)

    def practice(self, node_id, payload, headers):
        return self._request(
            "POST", f"/lesson-nodes/{node_id}/practice", payload, headers
        )

    def review(self, node_id, payload, headers):
        return self._request(
            "PUT", f"/lesson-nodes/{node_id}/review", payload, headers
        )

    # ── Practice attempts ────────────────────────────────────────────────────
    def list_practice_attempts(self, headers, params=None):
        return self._request(
            "GET", "/practice-attempts", headers=headers, params=params
        )

    def get_practice_attempt(self, attempt_id, headers):
        return self._request(
            "GET", f"/practice-attempts/{attempt_id}", headers=headers
        )

    # ── Streaks ──────────────────────────────────────────────────────────────
    def list_streak_states(self, headers, params=None):
        return self._request("GET", "/streak-states", headers=headers, params=params)

    def repair_streak(self, streak_id, payload, headers):
        return self._request(
            "POST", f"/streak-states/{streak_id}/repair", payload, headers
        )

    # ── Subscriptions and family seats ───────────────────────────────────────
    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def update_subscription(self, subscription_id, payload, headers):
        return self._request(
            "PUT", f"/subscriptions/{subscription_id}", payload, headers
        )

    def list_subscription_memberships(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/family-memberships",
            headers=headers, params=params,
        )

    # ── Placement testing ────────────────────────────────────────────────────
    def create_placement_test(self, payload, headers):
        return self._request("POST", "/placement-tests", payload, headers)

    def list_placement_tests(self, headers, params=None):
        return self._request(
            "GET", "/placement-tests", headers=headers, params=params
        )

    def get_placement_test(self, placement_id, headers):
        return self._request(
            "GET", f"/placement-tests/{placement_id}", headers=headers
        )

    def update_placement_test(self, placement_id, payload, headers):
        return self._request(
            "PUT", f"/placement-tests/{placement_id}", payload, headers
        )

    # ── Leagues ──────────────────────────────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def update_league(self, league_id, payload, headers):
        return self._request("PUT", f"/leagues/{league_id}", payload, headers)

    def list_league_standings(self, headers, params=None):
        return self._request(
            "GET", "/league-standings", headers=headers, params=params
        )

    def get_league_standing(self, standing_id, headers):
        return self._request(
            "GET", f"/league-standings/{standing_id}", headers=headers
        )

    # ── Certification exams and score reports ────────────────────────────────
    def create_certification_exam(self, payload, headers):
        return self._request("POST", "/certification-exams", payload, headers)

    def list_certification_exams(self, headers, params=None):
        return self._request(
            "GET", "/certification-exams", headers=headers, params=params
        )

    def get_certification_exam(self, exam_id, headers):
        return self._request(
            "GET", f"/certification-exams/{exam_id}", headers=headers
        )

    def update_certification_exam(self, exam_id, payload, headers):
        return self._request(
            "PUT", f"/certification-exams/{exam_id}", payload, headers
        )

    def create_score_report(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/certification-exams/{exam_id}/reports", payload, headers
        )

    def list_score_reports(self, headers, params=None):
        return self._request("GET", "/score-reports", headers=headers, params=params)

    def get_score_report(self, report_id, headers):
        return self._request("GET", f"/score-reports/{report_id}", headers=headers)

    # ── Engagement offers ────────────────────────────────────────────────────
    def create_engagement_offer(self, payload, headers):
        return self._request("POST", "/engagement-offers", payload, headers)

    def list_engagement_offers(self, headers, params=None):
        return self._request(
            "GET", "/engagement-offers", headers=headers, params=params
        )

    # ── Operator capabilities ────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def fire_event(self, event_type, headers):
        return self._request(
            "POST", "/_events/auto-transition", {"event_type": event_type}, headers
        )

    def inject_payment_outcome(self, subscription_id, outcome, headers):
        return self._request(
            "POST", "/_inject/payment_outcome",
            {"subscription_id": subscription_id, "outcome": outcome}, headers,
        )

    def inject_gems(self, learner_id, gems, headers):
        return self._request(
            "POST", "/_inject/gems", {"learner_id": learner_id, "gems": gems}, headers
        )


api_client = ApiClient()