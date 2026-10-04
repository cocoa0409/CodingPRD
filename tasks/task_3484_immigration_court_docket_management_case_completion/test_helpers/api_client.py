"""API client: one method per endpoint in the PRD's endpoint table.

Every method returns the raw ``requests.Response`` so tests assert on status
codes and envelopes directly.  All paths live under the ``/eoir`` prefix —
including the logical-clock endpoint ``POST /eoir/_clock/set_current_utc``.

``canonical_instant``/``same_instant`` normalise ISO 8601 UTC renderings so
that an expected instant spelled ``...T00:00:00Z`` compares equal to the same
instant rendered with fractional seconds (``...T00:00:00.000Z``); the PRD's
three-fractional-digit rendering is one legal spelling, not the only one.
"""

import re

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/eoir"
CLOCK_PATH = API_PREFIX + "/_clock/set_current_utc"

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 instant string in one canonical spelling (Z, 3-digit frac)."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        tz = tz.replace(":", "")
        suffix = "{0}:{1}".format(tz[:3], tz[3:])
    return "{0}T{1}.{2}{3}".format(match.group("date"), match.group("time"), frac, suffix)


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin endpoint-shaped facade over the shared HTTP client."""

    # ─── Logical clock ──────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Courts ─────────────────────────────────────────────────────────

    def create_court(self, payload, headers=None):
        return self.post(API_PREFIX + "/courts", json=payload, headers=headers)

    def get_court(self, court_id, headers=None):
        return self.get("{0}/courts/{1}".format(API_PREFIX, court_id), headers=headers)

    # ─── Judges ─────────────────────────────────────────────────────────

    def create_judge(self, payload, headers=None):
        return self.post(API_PREFIX + "/judges", json=payload, headers=headers)

    def list_judges(self, headers=None, params=None):
        return self.get(API_PREFIX + "/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers=None):
        return self.get("{0}/judges/{1}".format(API_PREFIX, judge_id), headers=headers)

    # ─── Interpreters ───────────────────────────────────────────────────

    def create_interpreter(self, payload, headers=None):
        return self.post(API_PREFIX + "/interpreters", json=payload, headers=headers)

    def list_interpreters(self, headers=None, params=None):
        return self.get(API_PREFIX + "/interpreters", headers=headers, params=params)

    def get_interpreter(self, interpreter_id, headers=None):
        return self.get(
            "{0}/interpreters/{1}".format(API_PREFIX, interpreter_id), headers=headers
        )

    # ─── Legal orientation programs ─────────────────────────────────────

    def create_orientation_program(self, payload, headers=None):
        return self.post(API_PREFIX + "/orientation-programs", json=payload, headers=headers)

    def list_orientation_programs(self, headers=None, params=None):
        return self.get(API_PREFIX + "/orientation-programs", headers=headers, params=params)

    def get_orientation_program(self, program_id, headers=None):
        return self.get(
            "{0}/orientation-programs/{1}".format(API_PREFIX, program_id), headers=headers
        )

    def set_program_coverage(self, program_id, payload, headers=None):
        return self.post(
            "{0}/orientation-programs/{1}/set-coverage".format(API_PREFIX, program_id),
            json=payload,
            headers=headers,
        )

    # ─── Cases ──────────────────────────────────────────────────────────

    def create_case(self, payload, headers=None):
        return self.post(API_PREFIX + "/cases", json=payload, headers=headers)

    def list_cases(self, headers=None, params=None):
        return self.get(API_PREFIX + "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers=None):
        return self.get("{0}/cases/{1}".format(API_PREFIX, case_id), headers=headers)

    def assign_judge(self, case_id, payload, headers=None):
        return self.post(
            "{0}/cases/{1}/assign-judge".format(API_PREFIX, case_id),
            json=payload,
            headers=headers,
        )

    def administrative_closure(self, case_id, payload, headers=None):
        return self.post(
            "{0}/cases/{1}/administrative-closure".format(API_PREFIX, case_id),
            json=payload,
            headers=headers,
        )

    def recalendar_case(self, case_id, headers=None):
        return self.post(
            "{0}/cases/{1}/recalendar".format(API_PREFIX, case_id),
            json={},
            headers=headers,
        )

    # ─── Hearings ───────────────────────────────────────────────────────

    def create_hearing(self, payload, headers=None):
        return self.post(API_PREFIX + "/hearings", json=payload, headers=headers)

    def list_hearings(self, headers=None, params=None):
        return self.get(API_PREFIX + "/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id, headers=None):
        return self.get("{0}/hearings/{1}".format(API_PREFIX, hearing_id), headers=headers)

    def complete_hearing(self, hearing_id, headers=None):
        return self.post(
            "{0}/hearings/{1}/complete".format(API_PREFIX, hearing_id),
            json={},
            headers=headers,
        )

    def record_no_show(self, hearing_id, headers=None):
        return self.post(
            "{0}/hearings/{1}/record-no-show".format(API_PREFIX, hearing_id),
            json={},
            headers=headers,
        )

    # ─── Hearing notices ────────────────────────────────────────────────

    def create_notice(self, payload, headers=None):
        return self.post(API_PREFIX + "/notices", json=payload, headers=headers)

    def list_hearing_notices(self, hearing_id, headers=None, params=None):
        return self.get(
            "{0}/hearings/{1}/notices".format(API_PREFIX, hearing_id),
            headers=headers,
            params=params,
        )

    def mark_notice_defective(self, notice_id, headers=None):
        return self.post(
            "{0}/notices/{1}/mark-defective".format(API_PREFIX, notice_id),
            json={},
            headers=headers,
        )

    # ─── Continuance requests ───────────────────────────────────────────

    def create_continuance_request(self, payload, headers=None):
        return self.post(API_PREFIX + "/continuance-requests", json=payload, headers=headers)

    def list_continuance_requests(self, headers=None, params=None):
        return self.get(API_PREFIX + "/continuance-requests", headers=headers, params=params)

    def get_continuance_request(self, request_id, headers=None):
        return self.get(
            "{0}/continuance-requests/{1}".format(API_PREFIX, request_id), headers=headers
        )

    def decide_continuance_request(self, request_id, payload, headers=None):
        return self.post(
            "{0}/continuance-requests/{1}/decide".format(API_PREFIX, request_id),
            json=payload,
            headers=headers,
        )

    # ─── Change-of-venue motions ────────────────────────────────────────

    def create_venue_motion(self, payload, headers=None):
        return self.post(API_PREFIX + "/venue-motions", json=payload, headers=headers)

    def list_venue_motions(self, headers=None, params=None):
        return self.get(API_PREFIX + "/venue-motions", headers=headers, params=params)

    def get_venue_motion(self, motion_id, headers=None):
        return self.get(
            "{0}/venue-motions/{1}".format(API_PREFIX, motion_id), headers=headers
        )

    def decide_venue_motion(self, motion_id, payload, headers=None):
        return self.post(
            "{0}/venue-motions/{1}/decide".format(API_PREFIX, motion_id),
            json=payload,
            headers=headers,
        )

    # ─── Case reassignments ─────────────────────────────────────────────

    def create_case_reassignment(self, payload, headers=None):
        return self.post(API_PREFIX + "/case-reassignments", json=payload, headers=headers)

    def list_case_reassignments(self, headers=None, params=None):
        return self.get(API_PREFIX + "/case-reassignments", headers=headers, params=params)

    def get_case_reassignment(self, reassignment_id, headers=None):
        return self.get(
            "{0}/case-reassignments/{1}".format(API_PREFIX, reassignment_id), headers=headers
        )

    # ─── Decisions ──────────────────────────────────────────────────────

    def create_decision(self, payload, headers=None):
        return self.post(API_PREFIX + "/decisions", json=payload, headers=headers)

    def list_decisions(self, headers=None, params=None):
        return self.get(API_PREFIX + "/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers=None):
        return self.get("{0}/decisions/{1}".format(API_PREFIX, decision_id), headers=headers)

    # ─── Appeals ────────────────────────────────────────────────────────

    def create_appeal(self, payload, headers=None):
        return self.post(API_PREFIX + "/appeals", json=payload, headers=headers)

    def list_appeals(self, headers=None, params=None):
        return self.get(API_PREFIX + "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers=None):
        return self.get("{0}/appeals/{1}".format(API_PREFIX, appeal_id), headers=headers)

    def decide_appeal(self, appeal_id, payload, headers=None):
        return self.post(
            "{0}/appeals/{1}/decide".format(API_PREFIX, appeal_id),
            json=payload,
            headers=headers,
        )

    # ─── Motions to reopen ──────────────────────────────────────────────

    def create_motion_to_reopen(self, payload, headers=None):
        return self.post(API_PREFIX + "/motions-to-reopen", json=payload, headers=headers)

    def list_motions_to_reopen(self, headers=None, params=None):
        return self.get(API_PREFIX + "/motions-to-reopen", headers=headers, params=params)

    def get_motion_to_reopen(self, motion_id, headers=None):
        return self.get(
            "{0}/motions-to-reopen/{1}".format(API_PREFIX, motion_id), headers=headers
        )

    def decide_motion_to_reopen(self, motion_id, payload, headers=None):
        return self.post(
            "{0}/motions-to-reopen/{1}/decide".format(API_PREFIX, motion_id),
            json=payload,
            headers=headers,
        )

    # ─── Docket reviews ─────────────────────────────────────────────────

    def create_docket_review(self, court_id, headers=None):
        return self.post(
            "{0}/courts/{1}/docket-reviews".format(API_PREFIX, court_id),
            json={},
            headers=headers,
        )

    def list_docket_reviews(self, headers=None, params=None):
        return self.get(API_PREFIX + "/docket-reviews", headers=headers, params=params)

    def get_docket_review(self, review_id, headers=None):
        return self.get(
            "{0}/docket-reviews/{1}".format(API_PREFIX, review_id), headers=headers
        )


api_client = ApiClient()
