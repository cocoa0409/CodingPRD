"""Composite setup helpers (PRD §3 workflows).

Every helper drives the public API only and builds preconditions from scratch
(the runner restarts the server before every test, so nothing persists).
Setup calls go through ``get_success_data`` so a failure surfaces as a clear
"Setup step failed" instead of a confusing assertion deep in a test.

Identity threading is mandatory throughout: any ownership-gated call is made
with ``make_<role>_headers(entity["id"])`` built from the freshly created
entity — never with the shared entity-backed constants from ``TEST_USERS``.

The heavier builders return a plain dict of named pieces (``government``,
``checklist``, ``cycle``, ``submission``, ``reviewers``, ``assignments``,
``findings``, ...) so tests can read exactly the piece they assert on.

Selector-ordering note: reviewers are created, trained, and attested strictly
sequentially in list order.  With the logical clock frozen, ``trained_at``
and ``created_at`` tie across reviewers, so any test that asserts selection
order beyond the primary ``open_assignment_count`` key is relying on the
implementation's insertion order — such assertions belong to the test layer,
not to these builders.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient, api_client as _default_client
from .constants import (
    AFTER_COMMENT_CLOSES_INSTANT,
    CLOCK_START_INSTANT,
    DEFAULT_COMMENT_CLOSES_AT,
    DEFAULT_PASS_SCORE,
    DEFAULT_PER_APPLICANT_CAP_CENTS,
    DEFAULT_POOL_TOTAL_CENTS,
    DEFAULT_REQUESTED_CENTS,
    DEFAULT_TEST_INSTANT,
    REQUIRED_FINDINGS_PER_ROUND,
)
from .factories import (
    allocate_payload,
    award_cycle_payload,
    budget_documents_payload,
    checklist_version_payload,
    finding_payload,
    government_payload,
    member_comment_payload,
    member_payload,
    open_comment_period_payload,
    publication_payload,
    report_submission_payload,
    resolve_comment_payload,
    review_assignment_payload,
    reviewer_profile_payload,
    scholarship_application_payload,
    scholarship_fund_payload,
    scores_for_criteria,
    standards_reference_payload,
    publish_payload,
)
from .test_users import (
    AWARDS_DIRECTOR,
    PLATFORM_ADMIN,
    make_committee_member_headers,
    make_government_contact_headers,
    make_member_headers,
    make_reviewer_headers,
)

__all__ = [
    "set_logical_clock",
    "reset_logical_clock",
    "create_government",
    "create_small_government",
    "create_member",
    "apply_for_reviewer",
    "update_reviewer_profile",
    "train_reviewer",
    "attest_independence",
    "suspend_reviewer",
    "reinstate_reviewer",
    "retire_reviewer",
    "create_eligible_reviewer",
    "create_eligible_reviewers",
    "create_checklist",
    "create_cycle",
    "create_standard",
    "activate_standard",
    "create_draft_submission",
    "submit_submission",
    "setup_submitted_submission",
    "create_assignment",
    "accept_assignment",
    "decline_assignment",
    "file_finding",
    "file_round_findings",
    "setup_submission_with_review_round",
    "setup_decision_ready_submission",
    "decide_submission",
    "setup_decided_submission",
    "appeal_submission",
    "refresh_submission",
    "refresh_cycle",
    "refresh_reviewer",
    "create_publication",
    "setup_publication",
    "open_comment_period",
    "close_comment_period",
    "revise_publication",
    "publish_publication",
    "create_comment",
    "resolve_comment",
    "setup_publication_in_resolution",
    "create_fund",
    "get_fund",
    "create_application",
    "allocate_application",
    "rescind_application",
    "setup_fund_with_applications",
]


def _client(api):
    return api if api is not None else _default_client


# ─── Logical clock (PRD §2.4) ───────────────────────────────────────────────


def set_logical_clock(api=None, to_iso8601=DEFAULT_TEST_INSTANT):
    """Advance the logical clock; returns the server's ``current_utc`` payload."""
    api = _client(api)
    return get_success_data(api.set_clock(to_iso8601, headers=PLATFORM_ADMIN))


def reset_logical_clock(api=None):
    """Return the clock to its startup default 2026-09-01T00:00:00Z."""
    return set_logical_clock(api, CLOCK_START_INSTANT)


# ─── Governments & members (PRD §3.2) ───────────────────────────────────────


def create_government(api=None, **overrides):
    api = _client(api)
    return get_success_data(
        api.create_government(government_payload(**overrides), headers=PLATFORM_ADMIN)
    )


def create_small_government(api=None, **overrides):
    """A population_band SMALL government — the scholarship-eligible kind."""
    overrides.setdefault("population_band", "SMALL")
    return create_government(api, **overrides)


def create_member(api=None, **overrides):
    api = _client(api)
    return get_success_data(
        api.create_member(member_payload(**overrides), headers=PLATFORM_ADMIN)
    )


# ─── Reviewer pipeline (PRD §3.3) ───────────────────────────────────────────


def apply_for_reviewer(api=None, member_id=None, employer_government_id=None,
                       **overrides):
    """Member self-application: X-User-ID must equal member_id."""
    api = _client(api)
    payload = reviewer_profile_payload(member_id, employer_government_id, **overrides)
    return get_success_data(
        api.create_reviewer_profile(payload, headers=make_member_headers(member_id))
    )


def update_reviewer_profile(api=None, profile_id=None, fields=None, as_admin=False):
    """PUT on a profile.  ``as_admin=True`` is the PlatformAdmin status path;
    otherwise the Reviewer self-service path (X-User-ID == profile id)."""
    api = _client(api)
    headers = PLATFORM_ADMIN if as_admin else make_reviewer_headers(profile_id)
    return get_success_data(
        api.update_reviewer_profile(profile_id, fields or {}, headers=headers)
    )


def train_reviewer(api=None, profile_id=None):
    """PlatformAdmin records training: APPLICANT -> TRAINED, stamps trained_at."""
    return update_reviewer_profile(api, profile_id, {"status": "TRAINED"},
                                   as_admin=True)


def attest_independence(api=None, profile_id=None, **extra_fields):
    """Reviewer self-attestation: TRAINED -> ELIGIBLE (plus optional window or
    conflict-list updates in the same PUT)."""
    fields = {"independence_attested": True}
    fields.update(extra_fields)
    return update_reviewer_profile(api, profile_id, fields)


def suspend_reviewer(api=None, profile_id=None):
    return update_reviewer_profile(api, profile_id, {"status": "SUSPENDED"},
                                   as_admin=True)


def reinstate_reviewer(api=None, profile_id=None):
    return update_reviewer_profile(api, profile_id, {"status": "ELIGIBLE"},
                                   as_admin=True)


def retire_reviewer(api=None, profile_id=None):
    return update_reviewer_profile(api, profile_id, {"status": "RETIRED"},
                                   as_admin=True)


def create_eligible_reviewer(api=None, member_overrides=None,
                             employer_overrides=None, profile_overrides=None):
    """Full recruitment pipeline: member + distinct employer government +
    APPLICANT profile + TRAINED + independence attested.  Returns the ELIGIBLE
    profile (whose ``member_id`` and ``employer_government_id`` fields lead back
    to the other two rows)."""
    api = _client(api)
    member = create_member(api, **(member_overrides or {}))
    employer = create_government(api, **(employer_overrides or {}))
    profile = apply_for_reviewer(
        api, member["id"], employer["id"], **(profile_overrides or {})
    )
    train_reviewer(api, profile["id"])
    return attest_independence(api, profile["id"])


def create_eligible_reviewers(api=None, count=REQUIRED_FINDINGS_PER_ROUND):
    """N ELIGIBLE reviewers, created and trained strictly in list order (a new
    member and employer government each, so no independence bar can fire)."""
    return [create_eligible_reviewer(api) for _ in range(count)]


def refresh_reviewer(api=None, profile_id=None, headers=None):
    api = _client(api)
    return get_success_data(
        api.get_reviewer_profile(profile_id, headers=headers or PLATFORM_ADMIN)
    )


# ─── Program configuration (PRD §3.1, §3.7) ─────────────────────────────────


def create_checklist(api=None, program_type="FINANCIAL_REPORTING", **overrides):
    api = _client(api)
    payload = checklist_version_payload(program_type=program_type, **overrides)
    return get_success_data(
        api.create_checklist_version(payload, headers=PLATFORM_ADMIN)
    )


def create_cycle(api=None, checklist_version_id=None,
                 program_type="FINANCIAL_REPORTING", **overrides):
    api = _client(api)
    payload = award_cycle_payload(
        checklist_version_id, program_type=program_type, **overrides
    )
    return get_success_data(api.create_award_cycle(payload, headers=PLATFORM_ADMIN))


def create_standard(api=None, **overrides):
    api = _client(api)
    return get_success_data(
        api.create_standards_reference(
            standards_reference_payload(**overrides), headers=PLATFORM_ADMIN
        )
    )


def activate_standard(api=None, standard_id=None):
    api = _client(api)
    return get_success_data(
        api.activate_standards_reference(standard_id, headers=PLATFORM_ADMIN)
    )


def refresh_cycle(api=None, cycle_id=None, headers=None):
    api = _client(api)
    return get_success_data(
        api.get_award_cycle(cycle_id, headers=headers or PLATFORM_ADMIN)
    )


# ─── Award applications (PRD §3.4) ──────────────────────────────────────────


def create_draft_submission(api=None, government_id=None, cycle_id=None,
                            budget_documents=None):
    """DRAFT creation by the government's own contact; pins the cycle's
    checklist at write time."""
    api = _client(api)
    payload = report_submission_payload(
        government_id, cycle_id, budget_documents=budget_documents
    )
    return get_success_data(
        api.create_report_submission(
            payload, headers=make_government_contact_headers(government_id)
        )
    )


def submit_submission(api=None, submission_id=None, government_id=None):
    """DRAFT -> SUBMITTED by the owning GovernmentContact."""
    api = _client(api)
    return get_success_data(
        api.submit_report_submission(
            submission_id, headers=make_government_contact_headers(government_id)
        )
    )


def setup_submitted_submission(api=None, program_type="FINANCIAL_REPORTING",
                               pass_score=DEFAULT_PASS_SCORE, criteria=None,
                               government_overrides=None, cycle_overrides=None,
                               budget_documents="auto",
                               set_clock_to=DEFAULT_TEST_INSTANT):
    """Checklist + cycle + government + SUBMITTED submission.

    ``budget_documents="auto"`` attaches the full three-document set for
    BUDGET_PRESENTATION and omits the field for FINANCIAL_REPORTING; pass an
    explicit list (or None) to override.
    Returns {"checklist", "cycle", "government", "submission"}.
    """
    api = _client(api)
    if set_clock_to is not None:
        set_logical_clock(api, set_clock_to)
    checklist_overrides = {"pass_score": pass_score}
    if criteria is not None:
        checklist_overrides["criteria"] = criteria
    checklist = create_checklist(api, program_type=program_type,
                                 **checklist_overrides)
    cycle = create_cycle(api, checklist["id"], program_type=program_type,
                         **(cycle_overrides or {}))
    government = create_government(api, **(government_overrides or {}))
    docs = budget_documents
    if docs == "auto":
        docs = (
            budget_documents_payload()
            if program_type == "BUDGET_PRESENTATION"
            else None
        )
    submission = create_draft_submission(api, government["id"], cycle["id"],
                                         budget_documents=docs)
    submission = submit_submission(api, submission["id"], government["id"])
    return {
        "checklist": checklist,
        "cycle": cycle,
        "government": government,
        "submission": submission,
    }


def refresh_submission(api=None, submission_id=None, headers=None):
    api = _client(api)
    return get_success_data(
        api.get_report_submission(submission_id, headers=headers or PLATFORM_ADMIN)
    )


# ─── Blind assignment & the review round (PRD §3.5) ────────────────────────


def create_assignment(api=None, submission_id=None):
    """AwardsDirector blind-assigns the next eligible reviewer.  Returns the
    OFFERED assignment (reviewer_id visible to privileged callers)."""
    api = _client(api)
    payload = review_assignment_payload(submission_id)
    return get_success_data(
        api.create_review_assignment(payload, headers=AWARDS_DIRECTOR)
    )


def accept_assignment(api=None, assignment=None):
    """OFFERED -> ACCEPTED by the assigned reviewer (X-User-ID == reviewer_id)."""
    api = _client(api)
    return get_success_data(
        api.accept_review_assignment(
            assignment["id"], headers=make_reviewer_headers(assignment["reviewer_id"])
        )
    )


def decline_assignment(api=None, assignment=None):
    """OFFERED -> DECLINED by the assigned reviewer."""
    api = _client(api)
    return get_success_data(
        api.decline_review_assignment(
            assignment["id"], headers=make_reviewer_headers(assignment["reviewer_id"])
        )
    )


def file_finding(api=None, assignment=None, criterion_scores=None, comments=None):
    """ACCEPTED -> SUBMITTED with a checklist-scored finding (201).

    ``criterion_scores`` must cover exactly the pinned checklist's criteria;
    build it with ``factories.scores_for_criteria(checklist["criteria"], ...)``.
    """
    api = _client(api)
    payload = finding_payload(criterion_scores, comments=comments)
    return get_success_data(
        api.submit_review_finding(
            assignment["id"], payload,
            headers=make_reviewer_headers(assignment["reviewer_id"]),
        )
    )


def file_round_findings(api=None, assignments=None, criteria=None, scores=None,
                        comments=None):
    """File one finding per assignment, in assignment order.

    ``scores``: a single number (uniform per criterion on every finding), or a
    list parallel to ``assignments`` whose entries are a number or a
    per-criterion list.  ``comments``: None, one comment list applied to every
    finding, or a list parallel to ``assignments``.
    """
    api = _client(api)
    findings = []
    for index, assignment in enumerate(assignments):
        if isinstance(scores, (list, tuple)) and scores and isinstance(
            scores[0], (list, tuple)
        ):
            per_assignment_scores = scores[index]
        elif scores is None:
            per_assignment_scores = 85
        else:
            per_assignment_scores = scores
        if isinstance(comments, (list, tuple)) and comments and isinstance(
            comments[0], (list, tuple)
        ):
            per_assignment_comments = comments[index]
        else:
            per_assignment_comments = comments
        criterion_scores = scores_for_criteria(criteria, per_assignment_scores)
        findings.append(
            file_finding(
                api, assignment,
                criterion_scores=criterion_scores,
                comments=per_assignment_comments,
            )
        )
    return findings


def setup_submission_with_review_round(api=None,
                                       program_type="FINANCIAL_REPORTING",
                                       num_reviewers=REQUIRED_FINDINGS_PER_ROUND,
                                       accept=True,
                                       pass_score=DEFAULT_PASS_SCORE,
                                       criteria=None,
                                       government_overrides=None,
                                       set_clock_to=DEFAULT_TEST_INSTANT):
    """SUBMITTED submission plus ``num_reviewers`` ELIGIBLE reviewers, each
    blind-assigned (assignments returned in creation order, aliases R1-1..N).
    With ``accept=True`` every assignment is ACCEPTED and ready for findings.

    Returns {"checklist", "cycle", "government", "submission", "reviewers",
    "assignments"}.
    """
    api = _client(api)
    bundle = setup_submitted_submission(
        api, program_type=program_type, pass_score=pass_score, criteria=criteria,
        government_overrides=government_overrides, set_clock_to=set_clock_to,
    )
    reviewers = create_eligible_reviewers(api, count=num_reviewers)
    assignments = [
        create_assignment(api, bundle["submission"]["id"])
        for _ in range(num_reviewers)
    ]
    if accept:
        assignments = [accept_assignment(api, a) for a in assignments]
    bundle["reviewers"] = reviewers
    bundle["assignments"] = assignments
    # Refresh: the first assignment of the round flips SUBMITTED -> UNDER_REVIEW.
    bundle["submission"] = refresh_submission(api, bundle["submission"]["id"])
    return bundle


# ─── Decision & appeal (PRD §3.6) ───────────────────────────────────────────


def setup_decision_ready_submission(api=None, program_type="FINANCIAL_REPORTING",
                                    scores=None, comments=None,
                                    pass_score=DEFAULT_PASS_SCORE, criteria=None,
                                    government_overrides=None,
                                    set_clock_to=DEFAULT_TEST_INSTANT):
    """Full review round: three ACCEPTED assignments each file a finding; the
    third finding cascades the submission UNDER_REVIEW -> DECISION_READY.

    Default scores are a uniform 85 per criterion (weighted 85.00 per finding
    on the default criteria).  Returns the round bundle plus "findings".
    """
    api = _client(api)
    bundle = setup_submission_with_review_round(
        api, program_type=program_type, accept=True, pass_score=pass_score,
        criteria=criteria, government_overrides=government_overrides,
        set_clock_to=set_clock_to,
    )
    findings = file_round_findings(
        api, bundle["assignments"], bundle["checklist"]["criteria"],
        scores=scores, comments=comments,
    )
    bundle["findings"] = findings
    bundle["submission"] = refresh_submission(api, bundle["submission"]["id"])
    return bundle


def decide_submission(api=None, submission_id=None):
    """AwardsDirector decides from DECISION_READY; returns the decided
    submission (AWARDED or DENIED per the score fork)."""
    api = _client(api)
    return get_success_data(
        api.decide_report_submission(submission_id, headers=AWARDS_DIRECTOR)
    )


def setup_decided_submission(api=None, awarded=True,
                             program_type="FINANCIAL_REPORTING",
                             pass_score=DEFAULT_PASS_SCORE,
                             major_comment_text="Missing note disclosure",
                             government_overrides=None,
                             set_clock_to=DEFAULT_TEST_INSTANT):
    """Full lifecycle through a decide.

    ``awarded=True``: findings weighted 85.00 / 86.00 / 84.00 on the default
    FR criteria (mean exactly 85.00 == default pass score, zero comments), so
    the fork selects DECIDED_AWARDED.  ``awarded=False``: uniform 80.00
    findings with one MAJOR comment on the first finding, so the fork selects
    DECIDED_DENIED and ``required_improvements`` carries that comment's text.

    Returns the round bundle plus "findings" and the decided "submission".
    """
    api = _client(api)
    if awarded:
        if program_type == "BUDGET_PRESENTATION":
            scores = 85
        else:
            scores = [[90, 80], [88, 84], [92, 76]]
    else:
        scores = 80
    comments = None  # for the denied branch, built once the checklist is known
    bundle = setup_submission_with_review_round(
        api, program_type=program_type, accept=True, pass_score=pass_score,
        government_overrides=government_overrides, set_clock_to=set_clock_to,
    )
    if not awarded:
        first_criterion = bundle["checklist"]["criteria"][0]["criterion_code"]
        comments = [
            [
                {
                    "criterion_code": first_criterion,
                    "severity": "MAJOR",
                    "text": major_comment_text,
                }
            ],
            None,
            None,
        ]
    findings = file_round_findings(
        api, bundle["assignments"], bundle["checklist"]["criteria"],
        scores=scores, comments=comments,
    )
    bundle["findings"] = findings
    bundle["submission"] = decide_submission(api, bundle["submission"]["id"])
    return bundle


def appeal_submission(api=None, submission=None):
    """DECIDED_DENIED -> APPEALED by the owning GovernmentContact; starts a
    fresh blind review round (appeal_round += 1)."""
    api = _client(api)
    return get_success_data(
        api.appeal_report_submission(
            submission["id"],
            headers=make_government_contact_headers(submission["government_id"]),
        )
    )


# ─── Best-practice publications (PRD §3.8) ──────────────────────────────────


def create_publication(api=None, chair_member_id=None, creator_member_id=None,
                       member_ids=None, pinned_standards_reference_id=None,
                       **overrides):
    """Committee creates a DRAFTING publication; the creator calls (and must
    sit on member_ids, as must the chair)."""
    api = _client(api)
    if member_ids is None:
        member_ids = [chair_member_id, creator_member_id]
    if pinned_standards_reference_id is not None:
        overrides["pinned_standards_reference_id"] = pinned_standards_reference_id
    payload = publication_payload(chair_member_id, member_ids, **overrides)
    return get_success_data(
        api.create_publication(
            payload, headers=make_committee_member_headers(creator_member_id)
        )
    )


def setup_publication(api=None, pinned_standards_reference_id=None,
                      set_clock_to=DEFAULT_TEST_INSTANT, **overrides):
    """A two-member committee (chair != creator, so the publish path is
    segregation-of-duties clean) with a DRAFTING publication.
    Returns {"publication", "chair", "creator", "members"}.
    """
    api = _client(api)
    if set_clock_to is not None:
        set_logical_clock(api, set_clock_to)
    chair = create_member(api)
    creator = create_member(api)
    publication = create_publication(
        api, chair_member_id=chair["id"], creator_member_id=creator["id"],
        member_ids=[chair["id"], creator["id"]],
        pinned_standards_reference_id=pinned_standards_reference_id, **overrides,
    )
    return {
        "publication": publication,
        "chair": chair,
        "creator": creator,
        "members": [chair, creator],
    }


def open_comment_period(api=None, publication=None,
                        closes_at=DEFAULT_COMMENT_CLOSES_AT, member_id=None):
    """DRAFTING -> MEMBER_COMMENT; stamps the comment window.  Returns the
    updated publication (its version has advanced)."""
    api = _client(api)
    member_id = member_id or publication["created_by_member_id"]
    return get_success_data(
        api.open_comment_period(
            publication["id"], open_comment_period_payload(closes_at),
            headers=make_committee_member_headers(member_id),
        )
    )


def close_comment_period(api=None, publication=None, member_id=None):
    """MEMBER_COMMENT -> RESOLUTION (clock must have reached closes_at).
    Returns the updated publication."""
    api = _client(api)
    member_id = member_id or publication["created_by_member_id"]
    return get_success_data(
        api.close_comment_period(
            publication["id"], headers=make_committee_member_headers(member_id)
        )
    )


def revise_publication(api=None, publication=None, member_id=None):
    """RESOLUTION -> DRAFTING: draft_number += 1, comment window reset.
    Returns the updated publication."""
    api = _client(api)
    member_id = member_id or publication["created_by_member_id"]
    return get_success_data(
        api.revise_publication(
            publication["id"], headers=make_committee_member_headers(member_id)
        )
    )


def publish_publication(api=None, publication=None, chair_member_id=None,
                        expected_publication_version=None):
    """Chair-only publish from RESOLUTION with OCC on the publication version.
    Both default to the latest ``publication`` dict the caller holds — keep it
    fresh (every comment/transition bumps the version)."""
    api = _client(api)
    chair_member_id = chair_member_id or publication["chair_member_id"]
    if expected_publication_version is None:
        expected_publication_version = publication["version"]
    return get_success_data(
        api.publish_publication(
            publication["id"], publish_payload(expected_publication_version),
            headers=make_committee_member_headers(chair_member_id),
        )
    )


def create_comment(api=None, publication_id=None, member_id=None, body=None):
    """A Member files a PENDING comment while the window is open."""
    api = _client(api)
    payload = member_comment_payload(publication_id, body=body)
    return get_success_data(
        api.create_member_comment(payload, headers=make_member_headers(member_id))
    )


def resolve_comment(api=None, comment_id=None, member_id=None,
                    resolution="ACCEPTED", resolution_note=None):
    """Committee resolves a PENDING comment during RESOLUTION."""
    api = _client(api)
    payload = resolve_comment_payload(resolution, resolution_note=resolution_note)
    return get_success_data(
        api.resolve_member_comment(
            comment_id, payload, headers=make_committee_member_headers(member_id)
        )
    )


def setup_publication_in_resolution(api=None, with_pending_comment=False,
                                    pinned_standards_reference_id=None,
                                    set_clock_to=DEFAULT_TEST_INSTANT,
                                    closes_at=DEFAULT_COMMENT_CLOSES_AT,
                                    advance_to=AFTER_COMMENT_CLOSES_INSTANT,
                                    **overrides):
    """Publication walked DRAFTING -> MEMBER_COMMENT -> RESOLUTION.

    With ``with_pending_comment=True`` a third member files one PENDING
    comment during the open window (it blocks publish until resolved).
    Returns {"publication" (latest, in RESOLUTION), "chair", "creator",
    "members", "commenter", "comment"}.
    """
    api = _client(api)
    bundle = setup_publication(
        api, pinned_standards_reference_id=pinned_standards_reference_id,
        set_clock_to=set_clock_to, **overrides,
    )
    publication = open_comment_period(api, bundle["publication"],
                                      closes_at=closes_at)
    commenter = None
    comment = None
    if with_pending_comment:
        commenter = create_member(api)
        comment = create_comment(api, publication["id"], commenter["id"])
    if advance_to is not None:
        set_logical_clock(api, advance_to)
    publication = close_comment_period(api, publication)
    bundle.update(
        {
            "publication": publication,
            "commenter": commenter,
            "comment": comment,
        }
    )
    return bundle


# ─── Small-government funds (PRD §3.9) ──────────────────────────────────────


def create_fund(api=None, **overrides):
    api = _client(api)
    return get_success_data(
        api.create_scholarship_fund(
            scholarship_fund_payload(**overrides), headers=PLATFORM_ADMIN
        )
    )


def get_fund(api=None, fund_id=None):
    """Read one fund (remaining_cents, derived status) as AwardsDirector."""
    api = _client(api)
    return get_success_data(api.get_scholarship_fund(fund_id, headers=AWARDS_DIRECTOR))


def create_application(api=None, fund_id=None, government_id=None, purpose=None,
                       requested_cents=DEFAULT_REQUESTED_CENTS, **overrides):
    """SMALL-government application by its own contact (purpose must match the
    fund's program label)."""
    api = _client(api)
    if purpose is not None:
        overrides["purpose"] = purpose
    payload = scholarship_application_payload(
        fund_id, government_id, requested_cents=requested_cents, **overrides
    )
    return get_success_data(
        api.create_scholarship_application(
            payload, headers=make_government_contact_headers(government_id)
        )
    )


def allocate_application(api=None, application_id=None, fund_id=None,
                         expected_fund_version=None):
    """AwardsDirector grants a PENDING application (OCC on the fund version).
    When ``expected_fund_version`` is omitted the fund is re-read first, so the
    happy path always carries the current version."""
    api = _client(api)
    if expected_fund_version is None:
        expected_fund_version = get_fund(api, fund_id)["version"]
    return get_success_data(
        api.allocate_scholarship_application(
            application_id, allocate_payload(expected_fund_version),
            headers=AWARDS_DIRECTOR,
        )
    )


def rescind_application(api=None, application_id=None):
    """AwardsDirector rescinds a GRANTED application; the pool is recredited."""
    api = _client(api)
    return get_success_data(
        api.rescind_scholarship_application(application_id, headers=AWARDS_DIRECTOR)
    )


def setup_fund_with_applications(api=None,
                                 pool_total_cents=DEFAULT_POOL_TOTAL_CENTS,
                                 per_applicant_cap_cents=DEFAULT_PER_APPLICANT_CAP_CENTS,
                                 allocation_policy="FLAT_CAP",
                                 program_label="SCHOLARSHIP",
                                 requested_amounts=(DEFAULT_REQUESTED_CENTS,),
                                 set_clock_to=DEFAULT_TEST_INSTANT):
    """One fund plus one SMALL-government PENDING application per requested
    amount (a fresh government per application).  The purpose is derived from
    the fund's program label so every application is lawful.

    Returns {"fund", "applications", "governments"}.
    """
    api = _client(api)
    if set_clock_to is not None:
        set_logical_clock(api, set_clock_to)
    fund = create_fund(
        api, pool_total_cents=pool_total_cents,
        per_applicant_cap_cents=per_applicant_cap_cents,
        allocation_policy=allocation_policy, program_label=program_label,
    )
    purpose = (
        "CONFERENCE_SCHOLARSHIP"
        if program_label == "SCHOLARSHIP"
        else "TECHNICAL_ASSISTANCE"
    )
    governments = []
    applications = []
    for amount in requested_amounts:
        government = create_small_government(api)
        application = create_application(
            api, fund["id"], government["id"], purpose=purpose,
            requested_cents=amount,
        )
        governments.append(government)
        applications.append(application)
    return {"fund": fund, "applications": applications, "governments": governments}
