"""API client: one transport method per endpoint in PRD §4.

Every method returns the raw ``requests.Response`` so tests assert on status
codes and envelopes themselves.  The ``/gfoa`` mount and every path shape
live here and nowhere else.

The logical-clock capability (PRD §2.4) is mounted OUTSIDE the ``/gfoa``
prefix — ``set_clock`` posts to ``/_clock/set_current_utc`` verbatim.

The base URL comes from the ``API_BASE_URL`` environment variable, which the
runner injects with its dynamically allocated port.
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

    # ─── Logical clock (outside the /gfoa mount — do not prefix) ─────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Governments ──────────────────────────────────────────────────────

    def create_government(self, payload, headers=None):
        return self.post(API_PREFIX + "/governments", json=payload, headers=headers)

    # ─── Members ──────────────────────────────────────────────────────────

    def create_member(self, payload, headers=None):
        return self.post(API_PREFIX + "/members", json=payload, headers=headers)

    # ─── Reviewer profiles ────────────────────────────────────────────────

    def create_reviewer_profile(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/reviewer-profiles", json=payload, headers=headers
        )

    def update_reviewer_profile(self, profile_id, payload, headers=None):
        return self.put(
            "{0}/reviewer-profiles/{1}".format(API_PREFIX, profile_id),
            json=payload,
            headers=headers,
        )

    def get_reviewer_profile(self, profile_id, headers=None):
        return self.get(
            "{0}/reviewer-profiles/{1}".format(API_PREFIX, profile_id),
            headers=headers,
        )

    def list_reviewer_profiles(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/reviewer-profiles", headers=headers, params=params
        )

    # ─── Checklist versions ───────────────────────────────────────────────

    def create_checklist_version(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/checklist-versions", json=payload, headers=headers
        )

    def list_checklist_versions(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/checklist-versions", headers=headers, params=params
        )

    # ─── Award cycles ─────────────────────────────────────────────────────

    def create_award_cycle(self, payload, headers=None):
        return self.post(API_PREFIX + "/award-cycles", json=payload, headers=headers)

    def get_award_cycle(self, cycle_id, headers=None):
        return self.get(
            "{0}/award-cycles/{1}".format(API_PREFIX, cycle_id), headers=headers
        )

    def list_award_cycles(self, headers=None, params=None):
        return self.get(API_PREFIX + "/award-cycles", headers=headers, params=params)

    # ─── Standards references ─────────────────────────────────────────────

    def create_standards_reference(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/standards-references", json=payload, headers=headers
        )

    def activate_standards_reference(self, standard_id, headers=None):
        return self.post(
            "{0}/standards-references/{1}/activate".format(API_PREFIX, standard_id),
            json={},
            headers=headers,
        )

    # ─── Report submissions ───────────────────────────────────────────────

    def create_report_submission(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/report-submissions", json=payload, headers=headers
        )

    def submit_report_submission(self, submission_id, headers=None):
        return self.post(
            "{0}/report-submissions/{1}/submit".format(API_PREFIX, submission_id),
            json={},
            headers=headers,
        )

    def decide_report_submission(self, submission_id, headers=None):
        return self.post(
            "{0}/report-submissions/{1}/decide".format(API_PREFIX, submission_id),
            json={},
            headers=headers,
        )

    def appeal_report_submission(self, submission_id, headers=None):
        return self.post(
            "{0}/report-submissions/{1}/appeal".format(API_PREFIX, submission_id),
            json={},
            headers=headers,
        )

    def get_report_submission(self, submission_id, headers=None):
        return self.get(
            "{0}/report-submissions/{1}".format(API_PREFIX, submission_id),
            headers=headers,
        )

    def list_report_submissions(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/report-submissions", headers=headers, params=params
        )

    # ─── Review assignments & findings ────────────────────────────────────

    def create_review_assignment(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/review-assignments", json=payload, headers=headers
        )

    def accept_review_assignment(self, assignment_id, headers=None):
        return self.post(
            "{0}/review-assignments/{1}/accept".format(API_PREFIX, assignment_id),
            json={},
            headers=headers,
        )

    def decline_review_assignment(self, assignment_id, headers=None):
        return self.post(
            "{0}/review-assignments/{1}/decline".format(API_PREFIX, assignment_id),
            json={},
            headers=headers,
        )

    def submit_review_finding(self, assignment_id, payload, headers=None):
        return self.post(
            "{0}/review-assignments/{1}/finding".format(API_PREFIX, assignment_id),
            json=payload,
            headers=headers,
        )

    def get_review_assignment(self, assignment_id, headers=None):
        return self.get(
            "{0}/review-assignments/{1}".format(API_PREFIX, assignment_id),
            headers=headers,
        )

    def list_review_assignments(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/review-assignments", headers=headers, params=params
        )

    def get_review_finding(self, finding_id, headers=None):
        return self.get(
            "{0}/review-findings/{1}".format(API_PREFIX, finding_id), headers=headers
        )

    def list_review_findings(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/review-findings", headers=headers, params=params
        )

    # ─── Best-practice publications & member comments ─────────────────────

    def create_publication(self, payload, headers=None):
        return self.post(API_PREFIX + "/publications", json=payload, headers=headers)

    def open_comment_period(self, publication_id, payload, headers=None):
        return self.post(
            "{0}/publications/{1}/open-comment-period".format(
                API_PREFIX, publication_id
            ),
            json=payload,
            headers=headers,
        )

    def close_comment_period(self, publication_id, headers=None):
        return self.post(
            "{0}/publications/{1}/close-comment-period".format(
                API_PREFIX, publication_id
            ),
            json={},
            headers=headers,
        )

    def revise_publication(self, publication_id, headers=None):
        return self.post(
            "{0}/publications/{1}/revise".format(API_PREFIX, publication_id),
            json={},
            headers=headers,
        )

    def publish_publication(self, publication_id, payload, headers=None):
        return self.post(
            "{0}/publications/{1}/publish".format(API_PREFIX, publication_id),
            json=payload,
            headers=headers,
        )

    def create_member_comment(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/member-comments", json=payload, headers=headers
        )

    def resolve_member_comment(self, comment_id, payload, headers=None):
        return self.post(
            "{0}/member-comments/{1}/resolve".format(API_PREFIX, comment_id),
            json=payload,
            headers=headers,
        )

    def get_member_comment(self, comment_id, headers=None):
        return self.get(
            "{0}/member-comments/{1}".format(API_PREFIX, comment_id), headers=headers
        )

    def list_member_comments(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/member-comments", headers=headers, params=params
        )

    # ─── Scholarship funds & applications ─────────────────────────────────

    def create_scholarship_fund(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/scholarship-funds", json=payload, headers=headers
        )

    def get_scholarship_fund(self, fund_id, headers=None):
        return self.get(
            "{0}/scholarship-funds/{1}".format(API_PREFIX, fund_id), headers=headers
        )

    def create_scholarship_application(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/scholarship-applications", json=payload, headers=headers
        )

    def allocate_scholarship_application(self, application_id, payload, headers=None):
        return self.post(
            "{0}/scholarship-applications/{1}/allocate".format(
                API_PREFIX, application_id
            ),
            json=payload,
            headers=headers,
        )

    def rescind_scholarship_application(self, application_id, headers=None):
        return self.post(
            "{0}/scholarship-applications/{1}/rescind".format(
                API_PREFIX, application_id
            ),
            json={},
            headers=headers,
        )

    def get_scholarship_application(self, application_id, headers=None):
        return self.get(
            "{0}/scholarship-applications/{1}".format(API_PREFIX, application_id),
            headers=headers,
        )

    def list_scholarship_applications(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/scholarship-applications", headers=headers, params=params
        )


api_client = ApiClient()
