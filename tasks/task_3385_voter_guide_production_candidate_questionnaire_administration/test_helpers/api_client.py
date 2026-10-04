"""API client: one method per endpoint defined in PRD §4.

The API is mounted at the server root (PRD §2), so every path below is
relative to the root.  Every method returns the raw ``requests.Response``
so tests can assert on status code and envelope shape themselves.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock (PRD §2.4) ────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Election cycles and jurisdictions ───────────────────────────────
    def create_cycle(self, payload, headers):
        return self._request("POST", "/election-cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/election-cycles/{cycle_id}", headers=headers)

    def transition_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/election-cycles/{cycle_id}/transitions", payload, headers
        )

    def create_jurisdiction(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/election-cycles/{cycle_id}/jurisdictions", payload, headers
        )

    def list_jurisdictions(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/election-cycles/{cycle_id}/jurisdictions",
            headers=headers, params=params,
        )

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # ── Contests and filings ────────────────────────────────────────────
    def create_contest(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST", f"/jurisdictions/{jurisdiction_id}/contests", payload, headers
        )

    def list_contests(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/contests",
            headers=headers, params=params,
        )

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}", headers=headers)

    def transition_contest(self, contest_id, payload, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/transitions", payload, headers
        )

    def create_filing(self, contest_id, payload, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/filings", payload, headers
        )

    def list_filings(self, contest_id, headers, params=None):
        return self._request(
            "GET", f"/contests/{contest_id}/filings", headers=headers, params=params
        )

    def verify_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/verify", headers=headers)

    def withdraw_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/withdraw", headers=headers)

    def disqualify_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/disqualify", payload, headers
        )

    def refile_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/refile", headers=headers)

    # ── Questionnaires and candidate responses ──────────────────────────
    def create_questionnaire(self, contest_id, payload, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/questionnaire", payload, headers
        )

    def get_contest_questionnaire(self, contest_id, headers):
        return self._request(
            "GET", f"/contests/{contest_id}/questionnaire", headers=headers
        )

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "GET", f"/questionnaires/{questionnaire_id}", headers=headers
        )

    def amend_questionnaire(self, questionnaire_id, payload, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/amend", payload, headers
        )

    def issue_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/issue", headers=headers
        )

    def close_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/close", headers=headers
        )

    def pin_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/pin", headers=headers
        )

    def submit_response(self, questionnaire_id, payload, headers):
        return self._request(
            "POST", f"/questionnaires/{questionnaire_id}/responses", payload, headers
        )

    def list_responses(self, questionnaire_id, headers, params=None):
        return self._request(
            "GET", f"/questionnaires/{questionnaire_id}/responses",
            headers=headers, params=params,
        )

    def resubmit_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"/responses/{response_id}/resubmit", payload, headers
        )

    def sweep_nonresponses(self, contest_id, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/sweep-nonresponses", headers=headers
        )

    # ── Ballot measures, arguments, reviews ─────────────────────────────
    def create_measure(self, contest_id, payload, headers):
        return self._request(
            "POST", f"/contests/{contest_id}/measure", payload, headers
        )

    def get_contest_measure(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}/measure", headers=headers)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"/measures/{measure_id}", headers=headers)

    def revise_measure(self, measure_id, payload, headers):
        return self._request(
            "POST", f"/measures/{measure_id}/revise", payload, headers
        )

    def create_argument(self, measure_id, payload, headers):
        return self._request(
            "POST", f"/measures/{measure_id}/arguments", payload, headers
        )

    def list_arguments(self, measure_id, headers, params=None):
        return self._request(
            "GET", f"/measures/{measure_id}/arguments", headers=headers, params=params
        )

    def submit_measure_for_review(self, measure_id, headers):
        return self._request(
            "POST", f"/measures/{measure_id}/submit-for-review", headers=headers
        )

    def create_review(self, measure_id, payload, headers):
        return self._request(
            "POST", f"/measures/{measure_id}/reviews", payload, headers
        )

    def list_reviews(self, measure_id, headers, params=None):
        return self._request(
            "GET", f"/measures/{measure_id}/reviews", headers=headers, params=params
        )

    # ── Guide editions ──────────────────────────────────────────────────
    def create_edition(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/election-cycles/{cycle_id}/guide-editions", payload, headers
        )

    def list_editions(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/election-cycles/{cycle_id}/guide-editions",
            headers=headers, params=params,
        )

    def get_edition(self, edition_id, headers):
        return self._request("GET", f"/guide-editions/{edition_id}", headers=headers)

    def transition_edition(self, edition_id, payload, headers):
        return self._request(
            "POST", f"/guide-editions/{edition_id}/transitions", payload, headers
        )

    def distribute_edition(self, edition_id, payload, headers):
        return self._request(
            "POST", f"/guide-editions/{edition_id}/distribute", payload, headers
        )

    # ── Forums and questions ────────────────────────────────────────────
    def create_forum(self, contest_id, payload, headers):
        return self._request("POST", f"/contests/{contest_id}/forums", payload, headers)

    def list_forums(self, contest_id, headers, params=None):
        return self._request(
            "GET", f"/contests/{contest_id}/forums", headers=headers, params=params
        )

    def get_forum(self, forum_id, headers):
        return self._request("GET", f"/forums/{forum_id}", headers=headers)

    def transition_forum(self, forum_id, payload, headers):
        return self._request(
            "POST", f"/forums/{forum_id}/transitions", payload, headers
        )

    def create_forum_question(self, forum_id, payload, headers):
        return self._request(
            "POST", f"/forums/{forum_id}/questions", payload, headers
        )

    def list_forum_questions(self, forum_id, headers, params=None):
        return self._request(
            "GET", f"/forums/{forum_id}/questions", headers=headers, params=params
        )

    def select_forum_question(self, question_id, headers):
        return self._request(
            "POST", f"/forum-questions/{question_id}/select", headers=headers
        )

    def reject_forum_question(self, question_id, headers):
        return self._request(
            "POST", f"/forum-questions/{question_id}/reject", headers=headers
        )

    # ── Volunteers and incidents ────────────────────────────────────────
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def attest_volunteer(self, volunteer_id, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/attest", headers=headers
        )

    def flag_advocacy(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/flag-advocacy", payload, headers
        )

    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def list_volunteer_incidents(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/incidents",
            headers=headers, params=params,
        )

    def transition_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/transitions", payload, headers
        )


api_client = ApiClient()
