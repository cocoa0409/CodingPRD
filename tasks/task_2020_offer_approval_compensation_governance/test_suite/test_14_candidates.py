"""Candidates: email uniqueness, archive gating, hirability."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_candidate_payload,
    create_open_requisition, create_candidate_recruited, create_draft_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]


def test_candidate_email_uniqueness_case_insensitive(api):
    """PRD §3.2: "the email must be unique case-insensitively across all
    candidates, and a duplicate is rejected with `ERR_CANDIDATE_EMAIL_EXISTS`."

    Design: Corner/entities/candidate_email_uniqueness
    """
    validate_success(api.create_candidate(
        create_candidate_payload(full_name="Dup One", email="cand.dup@x.com"), REC
    ), expected_status=201)
    resp = api.create_candidate(
        create_candidate_payload(full_name="Dup Two", email="CAND.DUP@x.com"), REC
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_EMAIL_EXISTS)


def test_candidate_not_hirable_after_archive(api):
    """PRD §3.2: "`ARCHIVED` is terminal, and creating an offer for an archived
    candidate is rejected with `ERR_CANDIDATE_NOT_HIRABLE`."

    Design: Corner/validations/candidate_not_hirable_after_archive
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand NH")
    validate_success(api.archive_candidate(cand["id"], REC))
    resp = api.create_offer(
        {"requisition_id": req["id"], "candidate_id": cand["id"], "base_cents": 18000000,
         "bonus_target_pct": 0, "equity_shares": 0, "equity_fmv_cents": 0},
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_HIRABLE)


def test_candidate_archive_blocked_by_active_offer(api):
    """PRD §3.2: "A `Recruiter` may archive a candidate from `PROSPECT` or
    `IN_PROCESS`, but only when the candidate has no offer in any live status —
    `DRAFT`, `RETURNED`, `PENDING_APPROVAL`, `APPROVED`, `LETTER_GENERATED`,
    `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` — otherwise the archive is
    rejected with `ERR_CANDIDATE_HAS_ACTIVE_OFFER`."

    Design: Corner/validations/candidate_archive_blocked_by_active_offer
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand AB")
    offer = create_draft_offer(req, cand, REC, base_cents=18000000)
    resp = api.archive_candidate(cand["id"], REC)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_HAS_ACTIVE_OFFER)
    validate_success(api.withdraw_offer(offer["id"], {"reason": "pipeline reset"}, REC))
    archived = validate_success(api.archive_candidate(cand["id"], REC))
    assert archived["status"] == "ARCHIVED"
