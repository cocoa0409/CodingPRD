"""Composite setup builders for the Newsroom Standards & Corrections API.

The harness restarts the API server before every individual test, so every
test begins against an empty database and must build the whole world it needs.
These builders assemble that world through the public API only: a newsroom, its
masthead, its reviewers, stories at each point of the publication and standards
dimensions, correction requests at each stage, investigations that suspend a
journalist, and reviewer ledgers with minutes already reserved.

Setup steps use the lenient ``get_success_data`` validator so that a broken
precondition surfaces as a clear setup failure rather than as a confusing
assertion inside the test body.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .test_users import (
    make_executive_editor_headers,
    make_legal_counsel_headers,
    make_public_editor_headers,
    make_reporter_headers,
    make_standards_editor_headers,
    TEST_USERS,
)


def shift_minutes(instant: str, minutes: int) -> str:
    """Return ``instant`` moved forward by ``minutes``, in the same UTC shape."""
    moment = datetime.strptime(
        instant.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"
    ).astimezone(timezone.utc) + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_hours(instant: str, hours: int) -> str:
    """Return ``instant`` moved forward by whole ``hours``."""
    return shift_minutes(instant, hours * 60)


# ─── The desk itself ──────────────────────────────────


@dataclass
class Desk:
    """A newsroom with the masthead every workflow needs to act."""

    newsroom: Dict[str, Any]
    exec_editor: Dict[str, Any]
    standards_editor: Dict[str, Any]
    reporter: Dict[str, Any]
    extra_reporters: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def newsroom_id(self) -> str:
        return self.newsroom["id"]

    @property
    def exec_id(self) -> str:
        return self.exec_editor["id"]

    @property
    def sed_id(self) -> str:
        return self.standards_editor["id"]

    @property
    def reporter_id(self) -> str:
        return self.reporter["id"]

    @property
    def exec_headers(self) -> Dict[str, str]:
        return make_executive_editor_headers(self.exec_id)

    @property
    def sed_headers(self) -> Dict[str, str]:
        return make_standards_editor_headers(self.sed_id)

    @property
    def reporter_headers(self) -> Dict[str, str]:
        return make_reporter_headers(self.reporter_id)

    @property
    def public_editor_headers(self) -> Dict[str, str]:
        return TEST_USERS["public_editor"]


def bootstrap_newsroom(api, **newsroom_kwargs) -> Dict[str, Any]:
    """Register a newsroom through the bootstrap-exempt endpoint of PRD §2.1."""
    return get_success_data(
        api.create_newsroom(
            F.newsroom_payload(**newsroom_kwargs), TEST_USERS["bootstrap_exec"]
        )
    )


def bootstrap_executive_editor(
    api,
    newsroom_id: str,
    full_name: str = "Dana Ruiz",
    email: str = "dana@ledger.test",
) -> Dict[str, Any]:
    """Create the first ``EXECUTIVE_EDITOR`` through the bootstrap exemption."""
    return get_success_data(
        api.create_journalist(
            F.executive_editor_payload(newsroom_id, full_name, email),
            TEST_USERS["bootstrap_exec"],
        )
    )


def add_journalist(
    api,
    desk_or_newsroom_id,
    full_name: str,
    email: str,
    role_title: str,
    exec_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Add a journalist under a real executive editor's identity."""
    if isinstance(desk_or_newsroom_id, Desk):
        newsroom_id = desk_or_newsroom_id.newsroom_id
        headers = exec_headers or desk_or_newsroom_id.exec_headers
    else:
        newsroom_id = desk_or_newsroom_id
        headers = exec_headers or TEST_USERS["bootstrap_exec"]
    return get_success_data(
        api.create_journalist(
            F.journalist_payload(newsroom_id, full_name, email, role_title), headers
        )
    )


def build_desk(api, **newsroom_kwargs) -> Desk:
    """Stand up a newsroom with an executive editor, standards editor and reporter.

    This is the shared opening of nearly every workflow in the PRD: the
    bootstrap endpoints create the newsroom and its first executive editor,
    and that editor then adds the rest of the masthead.
    """
    newsroom = bootstrap_newsroom(api, **newsroom_kwargs)
    exec_editor = bootstrap_executive_editor(api, newsroom["id"])
    exec_headers = make_executive_editor_headers(exec_editor["id"])
    standards_editor = add_journalist(
        api,
        newsroom["id"],
        "Sam Okoye",
        "sam@ledger.test",
        C.TITLE_STANDARDS_EDITOR,
        exec_headers,
    )
    reporter = add_journalist(
        api,
        newsroom["id"],
        "Rae Lindqvist",
        "rae@ledger.test",
        C.TITLE_REPORTER,
        exec_headers,
    )
    return Desk(
        newsroom=newsroom,
        exec_editor=exec_editor,
        standards_editor=standards_editor,
        reporter=reporter,
    )


def add_reporter(
    api, desk: Desk, full_name: str = "Yuki Sato", email: str = "yuki@ledger.test"
) -> Dict[str, Any]:
    """Add a second reporter to the desk and remember them on the Desk."""
    reporter = add_journalist(
        api, desk, full_name, email, C.TITLE_REPORTER, desk.exec_headers
    )
    desk.extra_reporters.append(reporter)
    return reporter


def add_reviewer(
    api,
    desk: Desk,
    full_name: str = "Lee Park",
    discipline: str = C.DISCIPLINE_STANDARDS,
    weekly_capacity_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Register a reviewer of the given discipline for this desk."""
    return get_success_data(
        api.create_reviewer(
            F.reviewer_payload(
                desk.newsroom_id, full_name, discipline, weekly_capacity_minutes
            ),
            desk.exec_headers,
        )
    )


def add_legal_reviewer(
    api,
    desk: Desk,
    full_name: str = "Iris Vance",
    weekly_capacity_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Register the ``LEGAL`` reviewer who backs a ``LegalCounsel`` identity."""
    return add_reviewer(
        api, desk, full_name, C.DISCIPLINE_LEGAL, weekly_capacity_minutes
    )


# ─── Reads that thread the OCC tokens ─────────────────


def read_newsroom(api, desk: Desk) -> Dict[str, Any]:
    return get_success_data(api.get_newsroom(desk.newsroom_id, desk.exec_headers))


def read_summary(api, desk: Desk) -> Dict[str, Any]:
    return get_success_data(
        api.get_standards_summary(desk.newsroom_id, desk.exec_headers)
    )


def read_story(api, desk: Desk, story_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_story(story_id, desk.exec_headers))


def read_journalist(api, desk: Desk, journalist_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_journalist(journalist_id, desk.exec_headers))


def read_reviewer(api, desk: Desk, reviewer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reviewer(reviewer_id, desk.exec_headers))


def read_review(api, desk: Desk, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_review(review_id, desk.exec_headers))


def read_assignment(api, desk: Desk, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assignment(assignment_id, desk.exec_headers))


def read_correction_request(api, desk: Desk, request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_correction_request(request_id, desk.exec_headers)
    )


def read_investigation(api, desk: Desk, investigation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_investigation(investigation_id, desk.exec_headers)
    )


def read_activity_request(api, desk: Desk, request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_activity_request(request_id, desk.exec_headers)
    )


def read_disclosure(api, desk: Desk, disclosure_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_disclosure(disclosure_id, desk.exec_headers))


def story_version(api, desk: Desk, story_id: str) -> int:
    """Read the story's current ``version`` for ``expected_story_version``."""
    return read_story(api, desk, story_id)["version"]


def reviewer_version(api, desk: Desk, reviewer_id: str) -> int:
    """Read the reviewer's current ``version`` for ``expected_reviewer_version``."""
    return read_reviewer(api, desk, reviewer_id)["version"]


# ─── The logical clock (PRD §2.5) ─────────────────────


def set_clock(api, desk: Desk, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical newsroom clock to the given instant."""
    return get_success_data(
        api.set_clock(F.clock_payload(to_iso8601), desk.exec_headers)
    )


# ─── Stories (PRD §3.2) ───────────────────────────────


def open_story(
    api,
    desk: Desk,
    headline: str = "A working headline",
    lead: Optional[Dict[str, Any]] = None,
    defamation_claim_count: Optional[int] = None,
    privacy_subject_count: Optional[int] = None,
    unverified_document_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a story file in the name of the acting reporter (PRD §3.2)."""
    lead = lead or desk.reporter
    return get_success_data(
        api.create_story(
            F.story_payload(
                desk.newsroom_id,
                lead["id"],
                headline,
                defamation_claim_count,
                privacy_subject_count,
                unverified_document_count,
            ),
            make_reporter_headers(lead["id"]),
        )
    )


def request_source(
    api,
    desk: Desk,
    story_id: str,
    lead: Optional[Dict[str, Any]] = None,
    **source_kwargs,
) -> Dict[str, Any]:
    """File an anonymous-source request against the lead journalist's own story."""
    lead = lead or desk.reporter
    return get_success_data(
        api.create_source_approval(
            F.source_approval_payload(story_id, **source_kwargs),
            make_reporter_headers(lead["id"]),
        )
    )


def approve_source(api, desk: Desk, approval_id: str) -> Dict[str, Any]:
    """Approve a ``REQUESTED`` source as the standards editor (never the author)."""
    return get_success_data(
        api.decide_source_approval(
            approval_id,
            F.source_decision_payload(C.DECISION_APPROVE),
            desk.sed_headers,
        )
    )


def deny_source(api, desk: Desk, approval_id: str) -> Dict[str, Any]:
    """Deny a ``REQUESTED`` source as the standards editor."""
    return get_success_data(
        api.decide_source_approval(
            approval_id,
            F.source_decision_payload(
                C.DECISION_DENY, "The identity is not held on the record."
            ),
            desk.sed_headers,
        )
    )


def revoke_source(api, desk: Desk, approval_id: str) -> Dict[str, Any]:
    """Revoke an ``APPROVED`` source after the fact."""
    return get_success_data(
        api.revoke_source_approval(
            approval_id, F.source_revocation_payload(), desk.sed_headers
        )
    )


def approved_source(
    api, desk: Desk, story_id: str, lead: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Request and then approve one anonymous source on the story."""
    approval = request_source(api, desk, story_id, lead=lead, **kwargs)
    return approve_source(api, desk, approval["id"])


def approved_sources(
    api,
    desk: Desk,
    story_id: str,
    harm_risk: str,
    count: int,
    lead: Optional[Dict[str, Any]] = None,
    alias_prefix: str = "source",
) -> List[Dict[str, Any]]:
    """Approve ``count`` sources at one harm-risk band, aliases kept unique."""
    approved: List[Dict[str, Any]] = []
    for index in range(count):
        corroboration = 2 if harm_risk == C.HARM_SEVERE else None
        approved.append(
            approved_source(
                api,
                desk,
                story_id,
                lead=lead,
                source_alias=f"{alias_prefix}-{harm_risk.lower()}-{index + 1}",
                harm_risk=harm_risk,
                corroboration_count=corroboration,
                justification_text=(
                    "A first-hand witness whose account the desk has verified."
                ),
            )
        )
    return approved


# ─── The pre-publication review cycle (PRD §3.3) ──────


def submit_review(
    api,
    desk: Desk,
    story_id: str,
    lead: Optional[Dict[str, Any]] = None,
    high_risk_declared: Optional[bool] = None,
    expected_story_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a review round as the story's own lead journalist (PRD §3.3)."""
    lead = lead or desk.reporter
    if expected_story_version is None:
        expected_story_version = story_version(api, desk, story_id)
    return get_success_data(
        api.create_review(
            F.review_payload(story_id, expected_story_version, high_risk_declared),
            make_reporter_headers(lead["id"]),
        )
    )


def record_legal_pass(
    api, desk: Desk, review_id: str, legal_reviewer: Dict[str, Any], **kwargs
) -> Dict[str, Any]:
    """Record a ``PASS`` legal verdict as the ``LEGAL`` reviewer."""
    return get_success_data(
        api.record_legal_verdict(
            review_id,
            F.legal_verdict_payload(C.VERDICT_PASS, **kwargs),
            make_legal_counsel_headers(legal_reviewer["id"]),
        )
    )


def record_legal_verdict(
    api,
    desk: Desk,
    review_id: str,
    legal_reviewer: Dict[str, Any],
    legal_verdict: str,
    **kwargs,
) -> Dict[str, Any]:
    """Record any legal verdict as the ``LEGAL`` reviewer."""
    return get_success_data(
        api.record_legal_verdict(
            review_id,
            F.legal_verdict_payload(legal_verdict, **kwargs),
            make_legal_counsel_headers(legal_reviewer["id"]),
        )
    )


def record_standards_pass(api, desk: Desk, review_id: str) -> Dict[str, Any]:
    """Record a ``PASS`` standards verdict as the standards editor."""
    return get_success_data(
        api.record_standards_verdict(
            review_id,
            F.standards_verdict_payload(C.VERDICT_PASS),
            desk.sed_headers,
        )
    )


def record_standards_changes_required(
    api, desk: Desk, review_id: str
) -> Dict[str, Any]:
    """Send the round back with ``CHANGES_REQUIRED`` (PRD §3.3)."""
    return get_success_data(
        api.record_standards_verdict(
            review_id,
            F.standards_verdict_payload(
                C.VERDICT_CHANGES_REQUIRED, "The sourcing needs another pass."
            ),
            desk.sed_headers,
        )
    )


def clear_round(
    api, desk: Desk, review_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Close out a ``STANDARDS_CLEARED`` round (PRD §3.3)."""
    return get_success_data(
        api.clear_review(review_id, {}, headers or desk.sed_headers)
    )


def resubmit_round(
    api, desk: Desk, review_id: str, lead: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Revive a ``CHANGES_REQUESTED`` round as its story's lead journalist."""
    lead = lead or desk.reporter
    return get_success_data(
        api.resubmit_review(
            review_id, F.resubmit_payload(), make_reporter_headers(lead["id"])
        )
    )


def standards_cleared_round(
    api,
    desk: Desk,
    story_id: str,
    lead: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Take a ``DRAFT`` story to a round awaiting clearance (PRD §3.3).

    The round takes the standards-only track, so the ``PASS`` standards
    verdict is recorded directly from ``SUBMITTED``.
    """
    review = submit_review(api, desk, story_id, lead=lead, high_risk_declared=False)
    record_standards_pass(api, desk, review["id"])
    return read_review(api, desk, review["id"])


def cleared_story(
    api,
    desk: Desk,
    headline: str = "Cleared and waiting",
    lead: Optional[Dict[str, Any]] = None,
    **story_kwargs,
) -> Dict[str, Any]:
    """Open a story and walk it all the way to ``publication_status`` ``CLEARED``."""
    story = open_story(api, desk, headline, lead=lead, **story_kwargs)
    review = standards_cleared_round(api, desk, story["id"], lead=lead)
    clear_round(api, desk, review["id"])
    return read_story(api, desk, story["id"])


def publish_story(api, desk: Desk, story_id: str) -> Dict[str, Any]:
    """Publish a ``CLEARED`` story as the executive editor (PRD §3.5)."""
    return get_success_data(api.publish_story(story_id, {}, desk.exec_headers))


def published_story(
    api,
    desk: Desk,
    headline: str = "Live on the site",
    lead: Optional[Dict[str, Any]] = None,
    **story_kwargs,
) -> Dict[str, Any]:
    """Open a story and walk it all the way to ``PUBLISHED`` (PRD §3.3, §3.5)."""
    story = cleared_story(api, desk, headline, lead=lead, **story_kwargs)
    return publish_story(api, desk, story["id"])


def third_round_changes_requested(
    api, desk: Desk, story_id: str, lead: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Drive a round to ``review_round`` 3 sitting in ``CHANGES_REQUESTED``.

    PRD §3.3 caps the revision cycle at three submissions, so this is the last
    state from which a resubmission is refused.
    """
    review = submit_review(api, desk, story_id, lead=lead, high_risk_declared=False)
    record_standards_changes_required(api, desk, review["id"])
    for _ in range(2):
        resubmit_round(api, desk, review["id"], lead=lead)
        record_standards_changes_required(api, desk, review["id"])
    return read_review(api, desk, review["id"])


# ─── Reviewer bookings (PRD §3.4) ─────────────────────


def book_slot(
    api,
    desk: Desk,
    review_id: str,
    reviewer: Dict[str, Any],
    starts_at: str,
    ends_at: str,
    headers: Optional[Dict[str, str]] = None,
    expected_reviewer_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Book a reviewer slot against an open round (PRD §3.4)."""
    if expected_reviewer_version is None:
        expected_reviewer_version = reviewer_version(api, desk, reviewer["id"])
    return get_success_data(
        api.create_assignment(
            F.assignment_payload(
                review_id,
                reviewer["id"],
                starts_at,
                ends_at,
                expected_reviewer_version,
            ),
            headers or desk.sed_headers,
        )
    )


def cancel_slot(api, desk: Desk, assignment_id: str) -> Dict[str, Any]:
    """Release a ``SCHEDULED`` booking (PRD §3.4)."""
    return get_success_data(
        api.cancel_assignment(
            assignment_id, F.cancellation_payload(), desk.sed_headers
        )
    )


# ─── Correction requests (PRD §3.6) ───────────────────


def file_correction(
    api,
    desk: Desk,
    story_id: str,
    headers: Optional[Dict[str, str]] = None,
    **correction_kwargs,
) -> Dict[str, Any]:
    """Log a correction request against a story (PRD §3.6)."""
    return get_success_data(
        api.create_correction_request(
            F.correction_request_payload(story_id, **correction_kwargs),
            headers or desk.public_editor_headers,
        )
    )


def start_investigation(api, desk: Desk, request_id: str) -> Dict[str, Any]:
    """Take a correction request ``INTAKE → INVESTIGATING`` (PRD §3.6)."""
    return get_success_data(
        api.start_correction_investigation(
            request_id, F.start_investigation_payload(), desk.sed_headers
        )
    )


def record_outreach(api, desk: Desk, request_id: str) -> Dict[str, Any]:
    """Take a request ``INVESTIGATING → AWAITING_SUBJECT`` as the public editor."""
    return get_success_data(
        api.record_subject_outreach(
            request_id, F.subject_outreach_payload(), desk.public_editor_headers
        )
    )


def adjudicate(
    api,
    desk: Desk,
    request_id: str,
    outcome_type: str,
    adjudicated_error_category: str,
    verified_reach: int,
    notice_text: Optional[str] = "An earlier version of this story was wrong.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Decide a correction request that is ``INVESTIGATING`` or awaiting a subject."""
    if outcome_type == C.OUTCOME_NO_ACTION:
        notice_text = None
    return get_success_data(
        api.adjudicate_correction_request(
            request_id,
            F.adjudication_payload(
                outcome_type, adjudicated_error_category, verified_reach, notice_text
            ),
            headers or desk.sed_headers,
        )
    )


def resolve_correction(api, desk: Desk, request_id: str) -> Dict[str, Any]:
    """Publish the notice and close out an ``ADJUDICATED`` request (PRD §3.6)."""
    return get_success_data(
        api.resolve_correction_request(
            request_id, F.resolution_payload(), desk.sed_headers
        )
    )


def investigating_correction(
    api, desk: Desk, story_id: str, **correction_kwargs
) -> Dict[str, Any]:
    """File a complaint and open its investigation in one step."""
    request = file_correction(api, desk, story_id, **correction_kwargs)
    return start_investigation(api, desk, request["id"])


def adjudicated_correction(
    api,
    desk: Desk,
    story_id: str,
    outcome_type: str = C.OUTCOME_CORRECTION,
    adjudicated_error_category: str = C.CATEGORY_IDENTIFICATION,
    verified_reach: int = 100000,
    submitter_email: str = "reader@example.test",
    subject_named: bool = True,
    **correction_kwargs,
) -> Dict[str, Any]:
    """File, investigate and adjudicate one complaint against the story.

    The default inputs land the adjudicated band at ``SEVERE``, which is what
    drives ``severe_correction_count`` and the newsroom's posture (PRD §2.9).
    """
    request = investigating_correction(
        api,
        desk,
        story_id,
        submitter_email=submitter_email,
        subject_named=subject_named,
        **correction_kwargs,
    )
    return adjudicate(
        api,
        desk,
        request["id"],
        outcome_type,
        adjudicated_error_category,
        verified_reach,
    )


def severe_adjudicated_corrections(
    api, desk: Desk, story_id: str, count: int
) -> List[Dict[str, Any]]:
    """Adjudicate ``count`` complaints at band ``SEVERE`` on one story.

    Each such request stays in the newsroom's high-severity pool until it is
    resolved, so this is the lever that escalates the desk-wide posture.
    """
    requests: List[Dict[str, Any]] = []
    for index in range(count):
        requests.append(
            adjudicated_correction(
                api,
                desk,
                story_id,
                submitter_email=f"reader{index + 1}@example.test",
                claim_text=(
                    f"The person named in paragraph {index + 1} is not the "
                    "person in the photograph."
                ),
            )
        )
    return requests


# ─── Misconduct investigations (PRD §3.7) ─────────────


def open_investigation(
    api,
    desk: Desk,
    journalist_id: str,
    allegation_type: str = C.ALLEGATION_PLAGIARISM,
    severity: str = C.SEVERITY_SERIOUS,
    story_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    allegation_summary: str = "Two paragraphs match a trade publication verbatim.",
) -> Dict[str, Any]:
    """Open a misconduct investigation as the standards editor (PRD §3.7)."""
    return get_success_data(
        api.create_investigation(
            F.investigation_payload(
                journalist_id, allegation_type, severity, allegation_summary, story_id
            ),
            headers or desk.sed_headers,
        )
    )


def advance_to_response_pending(
    api, desk: Desk, investigation_id: str
) -> Dict[str, Any]:
    """Walk a case ``OPENED → EVIDENCE_REVIEW → RESPONSE_PENDING`` (PRD §3.7)."""
    get_success_data(
        api.advance_investigation(
            investigation_id, F.advance_payload(), desk.sed_headers
        )
    )
    return get_success_data(
        api.advance_investigation(
            investigation_id,
            F.advance_payload("Response window opened."),
            desk.sed_headers,
        )
    )


def decide_investigation(
    api,
    desk: Desk,
    investigation_id: str,
    disposition: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record the finding from ``RESPONSE_PENDING``.

    The decider defaults to the executive editor, because PRD §2.10 bars the
    editor who opened the case from deciding it.
    """
    return get_success_data(
        api.decide_investigation(
            investigation_id,
            F.disposition_payload(disposition),
            headers or desk.exec_headers,
        )
    )


def sustained_investigation(
    api,
    desk: Desk,
    journalist_id: str,
    allegation_type: str = C.ALLEGATION_PLAGIARISM,
    severity: str = C.SEVERITY_SERIOUS,
    story_id: Optional[str] = None,
    allegation_summary: str = "Two paragraphs match a trade publication verbatim.",
) -> Dict[str, Any]:
    """Open, advance and sustain one investigation against a journalist."""
    investigation = open_investigation(
        api,
        desk,
        journalist_id,
        allegation_type,
        severity,
        story_id,
        allegation_summary=allegation_summary,
    )
    advance_to_response_pending(api, desk, investigation["id"])
    return decide_investigation(
        api, desk, investigation["id"], C.DISPOSITION_SUSTAINED
    )


def open_high_severity_investigation(
    api, desk: Desk, journalist_id: str, severity: str = C.SEVERITY_SERIOUS
) -> Dict[str, Any]:
    """Open a ``SERIOUS`` or ``EGREGIOUS`` case and leave it open.

    An undecided case at either severity sits in the newsroom's high-severity
    pool, which is the other half of ``open_high_severity_count`` (PRD §2.9).
    """
    return open_investigation(
        api,
        desk,
        journalist_id,
        C.ALLEGATION_PLAGIARISM,
        severity,
        allegation_summary="A recycled feature with no attribution.",
    )


def suspend_journalist(
    api, desk: Desk, journalist_id: str
) -> Dict[str, Any]:
    """Drive a journalist to ``SUSPENDED`` with a single sustained finding.

    PRD §3.7 puts an ``EGREGIOUS`` ``FABRICATION`` at 9 + 3 = 12 points, which
    is exactly the suspension threshold.
    """
    return sustained_investigation(
        api,
        desk,
        journalist_id,
        C.ALLEGATION_FABRICATION,
        C.SEVERITY_EGREGIOUS,
        allegation_summary="Two quoted sources cannot be shown to exist.",
    )


def appeal_investigation(
    api, desk: Desk, investigation_id: str, appeal_outcome: str
) -> Dict[str, Any]:
    """Hear an appeal against a sustained finding as the executive editor."""
    return get_success_data(
        api.appeal_investigation(
            investigation_id, F.appeal_payload(appeal_outcome), desk.exec_headers
        )
    )


# ─── Conflicts, outside work, training (PRD §3.8) ─────


def file_disclosure(
    api,
    desk: Desk,
    journalist: Optional[Dict[str, Any]] = None,
    **disclosure_kwargs,
) -> Dict[str, Any]:
    """File a reporter's own conflict-of-interest disclosure (PRD §3.8)."""
    journalist = journalist or desk.reporter
    return get_success_data(
        api.create_disclosure(
            F.disclosure_payload(journalist["id"], **disclosure_kwargs),
            make_reporter_headers(journalist["id"]),
        )
    )


def review_disclosure(
    api,
    desk: Desk,
    disclosure_id: str,
    review_outcome: str,
    restricted_beats: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Acknowledge, restrict or reject a filed disclosure (PRD §3.8)."""
    return get_success_data(
        api.review_disclosure(
            disclosure_id,
            F.disclosure_review_payload(review_outcome, restricted_beats),
            desk.sed_headers,
        )
    )


def restrict_beat(
    api,
    desk: Desk,
    beat: str,
    journalist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Put a beat on a journalist's ``restricted_beats`` through a disclosure.

    PRD §3.8 recomputes the journalist's own ``restricted_beats`` as the union
    over their disclosures in ``RESTRICTION_IMPOSED``.
    """
    journalist = journalist or desk.reporter
    disclosure = file_disclosure(
        api,
        desk,
        journalist,
        subject_entity_name="Harbourline Holdings",
        description=f"A financial interest touching the {beat} beat.",
    )
    return review_disclosure(
        api, desk, disclosure["id"], C.REVIEW_IMPOSE_RESTRICTION, [beat]
    )


def request_activity(
    api,
    desk: Desk,
    starts_on: str,
    ends_on: str,
    journalist: Optional[Dict[str, Any]] = None,
    **activity_kwargs,
) -> Dict[str, Any]:
    """File an outside-activity request in the reporter's own name (PRD §3.8)."""
    journalist = journalist or desk.reporter
    return get_success_data(
        api.create_activity_request(
            F.activity_request_payload(
                journalist["id"], starts_on, ends_on, **activity_kwargs
            ),
            make_reporter_headers(journalist["id"]),
        )
    )


def decide_activity(
    api, desk: Desk, request_id: str, decision: str
) -> Dict[str, Any]:
    """Approve or deny an outside-activity request (PRD §3.8)."""
    return get_success_data(
        api.decide_activity_request(
            request_id, F.activity_decision_payload(decision), desk.sed_headers
        )
    )


def approved_activity(
    api,
    desk: Desk,
    starts_on: str,
    ends_on: str,
    journalist: Optional[Dict[str, Any]] = None,
    **activity_kwargs,
) -> Dict[str, Any]:
    """File and approve one outside activity for the journalist."""
    request = request_activity(
        api, desk, starts_on, ends_on, journalist=journalist, **activity_kwargs
    )
    return decide_activity(api, desk, request["id"], C.DECISION_APPROVE)


def file_training(
    api,
    desk: Desk,
    journalist: Optional[Dict[str, Any]] = None,
    module_code: str = C.MODULE_SOURCING,
    case_study_reference: Optional[str] = "CS-2025-01",
) -> Dict[str, Any]:
    """File one completed standards training module (PRD §3.8)."""
    journalist = journalist or desk.reporter
    return get_success_data(
        api.create_training_record(
            F.training_record_payload(
                journalist["id"], module_code, case_study_reference
            ),
            make_reporter_headers(journalist["id"])
            if journalist["role_title"] == C.TITLE_REPORTER
            else (
                make_standards_editor_headers(journalist["id"])
                if journalist["role_title"] == C.TITLE_STANDARDS_EDITOR
                else make_executive_editor_headers(journalist["id"])
            ),
        )
    )


def file_training_modules(
    api,
    desk: Desk,
    journalist: Dict[str, Any],
    module_codes: List[str],
) -> List[Dict[str, Any]]:
    """File several modules for one journalist, one record per module."""
    records: List[Dict[str, Any]] = []
    for index, module_code in enumerate(module_codes):
        records.append(
            file_training(
                api,
                desk,
                journalist,
                module_code,
                case_study_reference=f"CS-2025-{index + 1:02d}",
            )
        )
    return records


def make_training_current(
    api, desk: Desk, journalist: Dict[str, Any]
) -> Dict[str, Any]:
    """File every module the newsroom requires, so ``training_current`` is true."""
    file_training_modules(
        api, desk, journalist, list(desk.newsroom["required_module_codes"])
    )
    return read_journalist(api, desk, journalist["id"])


# ─── Whole-desk states the design recipes reach for ───


def lockdown_desk(api, desk: Desk) -> Dict[str, Any]:
    """Escalate the desk to ``LOCKDOWN`` posture (PRD §2.9).

    Two adjudicated ``SEVERE`` corrections put ``open_high_severity_count`` at
    twice the default threshold of 2, which is where the gate trips.
    """
    carrier = open_story(api, desk, "The story that put the desk in lockdown")
    threshold = desk.newsroom["high_severity_open_threshold"]
    requests = severe_adjudicated_corrections(api, desk, carrier["id"], 2 * threshold)
    return {
        "story": read_story(api, desk, carrier["id"]),
        "requests": requests,
        "newsroom": read_newsroom(api, desk),
    }


def heightened_desk(api, desk: Desk) -> Dict[str, Any]:
    """Escalate the desk to exactly ``HEIGHTENED`` posture (PRD §2.9)."""
    carrier = open_story(api, desk, "The story that tightened the desk")
    threshold = desk.newsroom["high_severity_open_threshold"]
    requests = severe_adjudicated_corrections(api, desk, carrier["id"], threshold)
    return {
        "story": read_story(api, desk, carrier["id"]),
        "requests": requests,
        "newsroom": read_newsroom(api, desk),
    }


def reviewer_with_reserved_minutes(
    api,
    desk: Desk,
    minutes: int,
    starts_at: str = "2026-08-03T09:00:00Z",
    weekly_capacity_minutes: Optional[int] = None,
    full_name: str = "Lee Park",
) -> Dict[str, Any]:
    """Register a ``STANDARDS`` reviewer already holding ``minutes`` reserved.

    Returns the story, the round, the reviewer and the booking, so a test can
    add a second slot against the same ledger.
    """
    reviewer = add_reviewer(
        api,
        desk,
        full_name,
        C.DISCIPLINE_STANDARDS,
        weekly_capacity_minutes,
    )
    story = open_story(api, desk, "A routine read for the standards desk")
    review = submit_review(api, desk, story["id"], high_risk_declared=False)
    ends_at = shift_minutes(starts_at, minutes)
    assignment = book_slot(
        api, desk, review["id"], reviewer, starts_at, ends_at
    )
    return {
        "reviewer": read_reviewer(api, desk, reviewer["id"]),
        "story": story,
        "review": review,
        "assignment": assignment,
    }


def legal_round(
    api,
    desk: Desk,
    headline: str = "A story for the lawyers",
    weekly_capacity_minutes: Optional[int] = None,
    **story_kwargs,
) -> Dict[str, Any]:
    """A ``SUBMITTED`` round whose ``requires_legal_review`` is true.

    PRD §3.3 pins that boolean at submission from ``high_risk_declared`` or a
    ``HIGH`` risk tier, and PRD §3.4 makes ``LEGAL`` the discipline such a
    round is waiting on.
    """
    legal_reviewer = add_legal_reviewer(
        api, desk, weekly_capacity_minutes=weekly_capacity_minutes
    )
    story = open_story(api, desk, headline, **story_kwargs)
    review = submit_review(api, desk, story["id"], high_risk_declared=True)
    return {
        "legal_reviewer": legal_reviewer,
        "story": story,
        "review": review,
    }
