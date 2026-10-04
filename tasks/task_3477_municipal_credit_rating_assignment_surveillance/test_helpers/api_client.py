"""API client: one transport method per endpoint in PRD section 4.

Every method returns the raw ``requests.Response`` so that tests assert on
status codes and envelopes themselves.

Mounting (PRD sections 1 and 4): every business endpoint lives under the
``/muni`` prefix; the logical-clock advance is a platform endpoint mounted
outside that prefix at ``/_clock/set_current_utc``.  ``set_clock`` therefore
sends to the bare path while every other method is prefixed.

Success statuses (PRD section 4): operations that create a new stand-alone
resource answer ``201 Created`` — registering an issuer or an underwriter,
opening an engagement, drafting a criteria version, scheduling a committee
session, casting a ballot, filing an appeal, pricing a bond sale.  Every
other operation, all reads, and the clock advance answer ``200 OK``.  The
relevant methods note their status in their docstrings; tests pass it to
``validate_success(response, expected_status=...)`` explicitly.
"""

import os

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # ─── Logical clock (platform endpoint, OUTSIDE the /muni prefix) ──────
    # PRD section 2.4: answers 200; every advance runs the full sweep.

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Issuers ──────────────────────────────────────────────────────────

    def create_issuer(self, payload, headers=None):
        """POST /muni/issuers — 201."""
        return self.post(API_PREFIX + "/issuers", json=payload, headers=headers)

    def list_issuers(self, headers=None, params=None):
        return self.get(API_PREFIX + "/issuers", headers=headers, params=params)

    def get_issuer(self, issuer_id, headers=None):
        return self.get("{0}/issuers/{1}".format(API_PREFIX, issuer_id), headers=headers)

    def list_issuer_notifications(self, issuer_id, headers=None, params=None):
        return self.get(
            "{0}/issuers/{1}/notifications".format(API_PREFIX, issuer_id),
            headers=headers,
            params=params,
        )

    # ─── Underwriters ─────────────────────────────────────────────────────

    def create_underwriter(self, payload, headers=None):
        """POST /muni/underwriters — 201."""
        return self.post(API_PREFIX + "/underwriters", json=payload, headers=headers)

    def get_underwriter(self, underwriter_id, headers=None):
        return self.get(
            "{0}/underwriters/{1}".format(API_PREFIX, underwriter_id), headers=headers
        )

    # ─── Engagements ──────────────────────────────────────────────────────

    def create_engagement(self, payload, headers=None):
        """POST /muni/engagements — 201."""
        return self.post(API_PREFIX + "/engagements", json=payload, headers=headers)

    def list_engagements(self, headers=None, params=None):
        return self.get(API_PREFIX + "/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers=None):
        return self.get(
            "{0}/engagements/{1}".format(API_PREFIX, engagement_id), headers=headers
        )

    def accept_terms(self, engagement_id, payload, headers=None):
        """POST /muni/engagements/{id}/accept-terms — 200."""
        return self.post(
            "{0}/engagements/{1}/accept-terms".format(API_PREFIX, engagement_id),
            json=payload,
            headers=headers,
        )

    def submit_document(self, engagement_id, payload, headers=None):
        """POST /muni/engagements/{id}/documents — 200."""
        return self.post(
            "{0}/engagements/{1}/documents".format(API_PREFIX, engagement_id),
            json=payload,
            headers=headers,
        )

    def withdraw_engagement(self, engagement_id, headers=None):
        """POST /muni/engagements/{id}/withdraw — 200."""
        return self.post(
            "{0}/engagements/{1}/withdraw".format(API_PREFIX, engagement_id),
            json={},
            headers=headers,
        )

    def submit_scorecard(self, engagement_id, payload, headers=None):
        """POST /muni/engagements/{id}/scorecard — 200 (OCC-guarded)."""
        return self.post(
            "{0}/engagements/{1}/scorecard".format(API_PREFIX, engagement_id),
            json=payload,
            headers=headers,
        )

    def get_engagement_scorecard(self, engagement_id, headers=None):
        """GET /muni/engagements/{id}/scorecard — array of 0 or 1, unpaginated."""
        return self.get(
            "{0}/engagements/{1}/scorecard".format(API_PREFIX, engagement_id),
            headers=headers,
        )

    def list_criteria_scorecards(self, criteria_version_id, headers=None, params=None):
        return self.get(
            "{0}/criteria-versions/{1}/scorecards".format(API_PREFIX, criteria_version_id),
            headers=headers,
            params=params,
        )

    # ─── Criteria versions ────────────────────────────────────────────────

    def create_criteria_version(self, payload, headers=None):
        """POST /muni/criteria-versions — 201."""
        return self.post(
            API_PREFIX + "/criteria-versions", json=payload, headers=headers
        )

    def list_criteria_versions(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/criteria-versions", headers=headers, params=params
        )

    def get_criteria_version(self, criteria_version_id, headers=None):
        return self.get(
            "{0}/criteria-versions/{1}".format(API_PREFIX, criteria_version_id),
            headers=headers,
        )

    def activate_criteria_version(self, criteria_version_id, headers=None):
        """POST /muni/criteria-versions/{id}/activate — 200."""
        return self.post(
            "{0}/criteria-versions/{1}/activate".format(API_PREFIX, criteria_version_id),
            json={},
            headers=headers,
        )

    # ─── Committee sessions ───────────────────────────────────────────────

    def schedule_session(self, engagement_id, payload, headers=None):
        """POST /muni/engagements/{id}/committee-sessions — 201."""
        return self.post(
            "{0}/engagements/{1}/committee-sessions".format(API_PREFIX, engagement_id),
            json=payload,
            headers=headers,
        )

    def list_sessions(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/committee-sessions", headers=headers, params=params
        )

    def get_session(self, session_id, headers=None):
        return self.get(
            "{0}/committee-sessions/{1}".format(API_PREFIX, session_id),
            headers=headers,
        )

    def open_session(self, session_id, headers=None):
        """POST /muni/committee-sessions/{id}/open — 200."""
        return self.post(
            "{0}/committee-sessions/{1}/open".format(API_PREFIX, session_id),
            json={},
            headers=headers,
        )

    def cast_vote(self, session_id, payload, headers=None):
        """POST /muni/committee-sessions/{id}/votes — 201."""
        return self.post(
            "{0}/committee-sessions/{1}/votes".format(API_PREFIX, session_id),
            json=payload,
            headers=headers,
        )

    def list_votes(self, session_id, headers=None, params=None):
        return self.get(
            "{0}/committee-sessions/{1}/votes".format(API_PREFIX, session_id),
            headers=headers,
            params=params,
        )

    def appoint_alternate(self, session_id, payload, headers=None):
        """POST /muni/committee-sessions/{id}/alternates — 200."""
        return self.post(
            "{0}/committee-sessions/{1}/alternates".format(API_PREFIX, session_id),
            json=payload,
            headers=headers,
        )

    def close_session(self, session_id, headers=None):
        """POST /muni/committee-sessions/{id}/close — 200."""
        return self.post(
            "{0}/committee-sessions/{1}/close".format(API_PREFIX, session_id),
            json={},
            headers=headers,
        )

    # ─── Ratings ──────────────────────────────────────────────────────────

    def list_ratings(self, headers=None, params=None):
        return self.get(API_PREFIX + "/ratings", headers=headers, params=params)

    def get_rating(self, rating_id, headers=None):
        return self.get("{0}/ratings/{1}".format(API_PREFIX, rating_id), headers=headers)

    def publish_rating(self, rating_id, payload, headers=None):
        """POST /muni/ratings/{id}/publish — 200."""
        return self.post(
            "{0}/ratings/{1}/publish".format(API_PREFIX, rating_id),
            json=payload,
            headers=headers,
        )

    def post_rating_action(self, rating_id, payload, headers=None):
        """POST /muni/ratings/{id}/actions — 200 (OCC-guarded)."""
        return self.post(
            "{0}/ratings/{1}/actions".format(API_PREFIX, rating_id),
            json=payload,
            headers=headers,
        )

    def reinstate_rating(self, rating_id, headers=None):
        """POST /muni/ratings/{id}/reinstate — 200."""
        return self.post(
            "{0}/ratings/{1}/reinstate".format(API_PREFIX, rating_id),
            json={},
            headers=headers,
        )

    # ─── Appeals ──────────────────────────────────────────────────────────

    def file_appeal(self, rating_id, payload, headers=None):
        """POST /muni/ratings/{id}/appeals — 201."""
        return self.post(
            "{0}/ratings/{1}/appeals".format(API_PREFIX, rating_id),
            json=payload,
            headers=headers,
        )

    def list_appeals(self, rating_id, headers=None, params=None):
        return self.get(
            "{0}/ratings/{1}/appeals".format(API_PREFIX, rating_id),
            headers=headers,
            params=params,
        )

    def get_appeal(self, appeal_id, headers=None):
        return self.get("{0}/appeals/{1}".format(API_PREFIX, appeal_id), headers=headers)

    def decide_appeal(self, appeal_id, payload, headers=None):
        """POST /muni/appeals/{id}/decide — 200."""
        return self.post(
            "{0}/appeals/{1}/decide".format(API_PREFIX, appeal_id),
            json=payload,
            headers=headers,
        )

    # ─── Disclosure obligations ───────────────────────────────────────────

    def list_obligations(self, rating_id, headers=None, params=None):
        return self.get(
            "{0}/ratings/{1}/disclosure-obligations".format(API_PREFIX, rating_id),
            headers=headers,
            params=params,
        )

    def get_obligation(self, obligation_id, headers=None):
        return self.get(
            "{0}/disclosure-obligations/{1}".format(API_PREFIX, obligation_id),
            headers=headers,
        )

    def submit_obligation(self, obligation_id, headers=None):
        """POST /muni/disclosure-obligations/{id}/submit — 200."""
        return self.post(
            "{0}/disclosure-obligations/{1}/submit".format(API_PREFIX, obligation_id),
            json={},
            headers=headers,
        )

    # ─── Bond sales ───────────────────────────────────────────────────────

    def create_bond_sale(self, payload, headers=None):
        """POST /muni/bond-sales — 201."""
        return self.post(API_PREFIX + "/bond-sales", json=payload, headers=headers)

    def list_bond_sales(self, headers=None, params=None):
        return self.get(API_PREFIX + "/bond-sales", headers=headers, params=params)

    def get_bond_sale(self, bond_sale_id, headers=None):
        return self.get(
            "{0}/bond-sales/{1}".format(API_PREFIX, bond_sale_id), headers=headers
        )

    # ─── Criteria review items ────────────────────────────────────────────

    def list_review_items(self, headers=None, params=None):
        return self.get(API_PREFIX + "/review-items", headers=headers, params=params)

    def get_review_item(self, review_item_id, headers=None):
        return self.get(
            "{0}/review-items/{1}".format(API_PREFIX, review_item_id), headers=headers
        )

    def begin_review_item(self, review_item_id, headers=None):
        """POST /muni/review-items/{id}/begin — 200."""
        return self.post(
            "{0}/review-items/{1}/begin".format(API_PREFIX, review_item_id),
            json={},
            headers=headers,
        )

    def complete_review_item(self, review_item_id, payload, headers=None):
        """POST /muni/review-items/{id}/complete — 200."""
        return self.post(
            "{0}/review-items/{1}/complete".format(API_PREFIX, review_item_id),
            json=payload,
            headers=headers,
        )


api_client = ApiClient()
