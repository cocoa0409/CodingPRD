"""Payload factories — one per creatable resource, input fields only (PRD §4).

Optional fields with PRD-stated server defaults (``independent_finance_officer``,
``conflicted_government_ids``, ``unavailability_windows``, ``budget_documents``,
``pinned_standards_reference_id``, ``allocation_policy``, ``comments``,
``resolution_note``) are included only when the caller passes a non-None value,
so a test can always exercise the omission path.

Computed and system fields (``annual_dues_cents``, ``program_type``,
``pinned_checklist_version_id``, ``member_id`` on comments, ...) are never
emitted by default, but ``**overrides`` passes arbitrary extra keys through so
a test can deliberately supply a computed field and assert it is ignored.
"""

import itertools

from .constants import (
    AFTER_COMMENT_CLOSES_INSTANT,
    BUDGET_DOC_TYPES_REQUIRED,
    DEFAULT_COMMENT_CLOSES_AT,
    DEFAULT_DOC_PAGE_COUNTS,
    DEFAULT_DOC_TITLES,
    DEFAULT_FISCAL_YEAR,
    DEFAULT_PASS_SCORE,
    DEFAULT_PER_APPLICANT_CAP_CENTS,
    DEFAULT_POOL_TOTAL_CENTS,
    DEFAULT_REQUESTED_CENTS,
    DEFAULT_REVIEW_CLOSE_AT,
    DEFAULT_STANDARD_EFFECTIVE_DATE,
    DEFAULT_STANDARD_TOPIC,
    DEFAULT_WINDOW_DEADLINE_AT,
    DEFAULT_WINDOW_OPENS_AT,
    FR_CRITERIA,
    BUDGET_CRITERIA,
)

__all__ = [
    "government_payload",
    "member_payload",
    "reviewer_profile_payload",
    "reviewer_update_payload",
    "checklist_version_payload",
    "award_cycle_payload",
    "standards_reference_payload",
    "report_submission_payload",
    "budget_documents_payload",
    "review_assignment_payload",
    "criterion_score",
    "finding_comment",
    "finding_payload",
    "scores_for_criteria",
    "publication_payload",
    "member_comment_payload",
    "resolve_comment_payload",
    "open_comment_period_payload",
    "publish_payload",
    "scholarship_fund_payload",
    "scholarship_application_payload",
    "allocate_payload",
    "set_clock_payload",
]

_seq = itertools.count(1)


def _next(prefix):
    return "{0}-{1}".format(prefix, next(_seq))


# ─── Governments ────────────────────────────────────────────────────────────


def government_payload(**overrides):
    payload = {
        "legal_name": _next("City of Example"),
        "gov_type": "CITY",
        "population_band": "MEDIUM",
        "state_code": "OH",
    }
    payload.update(overrides)
    return payload


# ─── Members ────────────────────────────────────────────────────────────────


def member_payload(**overrides):
    n = next(_seq)
    payload = {
        "full_name": "Member {0}".format(n),
        "email": "member{0}@example.org".format(n),
        "government_size_band": "MEDIUM",
    }
    payload.update(overrides)
    return payload


# ─── Reviewer profiles ──────────────────────────────────────────────────────


def reviewer_profile_payload(member_id, employer_government_id, **overrides):
    payload = {
        "member_id": member_id,
        "employer_government_id": employer_government_id,
    }
    payload.update(overrides)
    return payload


def reviewer_update_payload(**overrides):
    """PUT body: any of conflicted_government_ids / unavailability_windows /
    independence_attested / status (status is PlatformAdmin-only)."""
    return dict(overrides)


# ─── Checklist versions ─────────────────────────────────────────────────────


def checklist_version_payload(program_type="FINANCIAL_REPORTING", **overrides):
    criteria = FR_CRITERIA if program_type == "FINANCIAL_REPORTING" else BUDGET_CRITERIA
    payload = {
        "program_type": program_type,
        "version_label": _next("2026."),
        "pass_score": DEFAULT_PASS_SCORE,
        "criteria": [dict(c) for c in criteria],
    }
    payload.update(overrides)
    return payload


# ─── Award cycles ───────────────────────────────────────────────────────────


def award_cycle_payload(checklist_version_id, program_type="FINANCIAL_REPORTING",
                        **overrides):
    payload = {
        "program_type": program_type,
        "fiscal_year": DEFAULT_FISCAL_YEAR,
        "submission_opens_at": DEFAULT_WINDOW_OPENS_AT,
        "submission_deadline_at": DEFAULT_WINDOW_DEADLINE_AT,
        "review_close_at": DEFAULT_REVIEW_CLOSE_AT,
        "checklist_version_id": checklist_version_id,
    }
    payload.update(overrides)
    return payload


# ─── Standards references ───────────────────────────────────────────────────


def standards_reference_payload(**overrides):
    payload = {
        "topic_code": DEFAULT_STANDARD_TOPIC,
        "title": "Financial Reporting Model Improvements",
        "program_type": "FINANCIAL_REPORTING",
        "effective_date": DEFAULT_STANDARD_EFFECTIVE_DATE,
    }
    payload.update(overrides)
    return payload


# ─── Report submissions ─────────────────────────────────────────────────────


def budget_documents_payload(page_counts=None, titles=None, **overrides):
    """All three required budget document types (PRD §3.4), one entry each."""
    page_counts = page_counts or DEFAULT_DOC_PAGE_COUNTS
    titles = titles or DEFAULT_DOC_TITLES
    docs = [
        {
            "doc_type": doc_type,
            "title": titles.get(doc_type, doc_type.title()),
            "page_count": page_counts.get(doc_type, 10),
        }
        for doc_type in BUDGET_DOC_TYPES_REQUIRED
    ]
    if overrides.get("extra"):
        docs.extend(overrides["extra"])
    return docs


def report_submission_payload(government_id, cycle_id, budget_documents=None,
                              **overrides):
    payload = {"government_id": government_id, "cycle_id": cycle_id}
    if budget_documents is not None:
        payload["budget_documents"] = budget_documents
    payload.update(overrides)
    return payload


# ─── Review assignments & findings ──────────────────────────────────────────


def review_assignment_payload(submission_id, **overrides):
    payload = {"submission_id": submission_id}
    payload.update(overrides)
    return payload


def criterion_score(criterion_code, score):
    return {"criterion_code": criterion_code, "score": score}


def finding_comment(criterion_code, severity, text):
    return {"criterion_code": criterion_code, "severity": severity, "text": text}


def scores_for_criteria(criteria, scores):
    """Zip a checklist's criteria with per-criterion scores, in criteria order.

    ``scores`` may be a single number (uniform) or a list parallel to
    ``criteria``.
    """
    if isinstance(scores, (int, float)):
        scores = [scores] * len(criteria)
    return [
        criterion_score(c["criterion_code"], s) for c, s in zip(criteria, scores)
    ]


def finding_payload(criterion_scores, comments=None, **overrides):
    payload = {"criterion_scores": criterion_scores}
    if comments is not None:
        payload["comments"] = comments
    payload.update(overrides)
    return payload


# ─── Publications & member comments ─────────────────────────────────────────


def publication_payload(chair_member_id, member_ids, **overrides):
    payload = {
        "committee_name": "Accounting Practices Committee",
        "chair_member_id": chair_member_id,
        "member_ids": member_ids,
        "title": _next("Practice Title"),
        "topic_code": "IC-GRANTS",
    }
    payload.update(overrides)
    return payload


def open_comment_period_payload(closes_at=DEFAULT_COMMENT_CLOSES_AT, **overrides):
    payload = {"closes_at": closes_at}
    payload.update(overrides)
    return payload


def publish_payload(expected_publication_version, **overrides):
    payload = {"expected_publication_version": expected_publication_version}
    payload.update(overrides)
    return payload


def member_comment_payload(publication_id, body=None, **overrides):
    payload = {
        "publication_id": publication_id,
        "body": body or _next("Comment body"),
    }
    payload.update(overrides)
    return payload


def resolve_comment_payload(resolution="ACCEPTED", resolution_note=None, **overrides):
    payload = {"resolution": resolution}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    payload.update(overrides)
    return payload


# ─── Scholarship funds & applications ───────────────────────────────────────


def scholarship_fund_payload(**overrides):
    payload = {
        "fiscal_year": DEFAULT_FISCAL_YEAR,
        "program_label": "SCHOLARSHIP",
        "pool_total_cents": DEFAULT_POOL_TOTAL_CENTS,
        "per_applicant_cap_cents": DEFAULT_PER_APPLICANT_CAP_CENTS,
        "allocation_policy": "FLAT_CAP",
    }
    if overrides.get("allocation_policy") is None and "allocation_policy" in overrides:
        # Explicit None: omit the field entirely to exercise the server default.
        del payload["allocation_policy"]
        del overrides["allocation_policy"]
    payload.update(overrides)
    return payload


def scholarship_application_payload(fund_id, government_id, **overrides):
    payload = {
        "fund_id": fund_id,
        "government_id": government_id,
        "purpose": "CONFERENCE_SCHOLARSHIP",
        "requested_cents": DEFAULT_REQUESTED_CENTS,
    }
    payload.update(overrides)
    return payload


def allocate_payload(expected_fund_version, **overrides):
    payload = {"expected_fund_version": expected_fund_version}
    payload.update(overrides)
    return payload


# ─── Clock ──────────────────────────────────────────────────────────────────


def set_clock_payload(to_iso8601=AFTER_COMMENT_CLOSES_INSTANT):
    return {"to_iso8601": to_iso8601}
