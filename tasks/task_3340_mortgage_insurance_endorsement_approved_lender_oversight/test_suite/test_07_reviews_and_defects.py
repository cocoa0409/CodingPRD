"""Post-endorsement reviews, defect taxonomy, and cascade A."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_startswith,
    close_review,
    confirm_defect,
    create_case,
    create_escrow,
    declare_default,
    get_case,
    get_review_of_case,
    list_agreements,
    list_escrows,
    open_review,
    record_defect,
    set_clock,
    setup_approved_lender,
    setup_endorsed_case,
    submit_case,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_approver_headers,
    make_examiner_headers,
    make_reviewer_headers,
)


def _setup_endorsed_with_review(api, legal_name="Review Co", endorser="rev-1",
                                reviewer="rev-2", default=False):
    """Endorsed case (endorsed by `endorser`) plus an open review by `reviewer`."""
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": legal_name}, endorser=endorser
    )
    if default:
        declare_default(case["id"], lender["id"])
    review = open_review(case["id"], reviewer=reviewer)
    return lender, case, review


# ---------------------------------------------------------------------------
# Defect dispositions
# ---------------------------------------------------------------------------
def test_defect_dismiss_records_confirmer(api):
    """PRD §3.5: "An `FhaApprover` disposes of each defect through a `decision` of
    `CONFIRM`, `DISMISS`, or `MARK_REMEDIATED`: confirming it moves it from `OPEN` to
    `CONFIRMED`, dismissing moves it from `OPEN` to `DISMISSED`, and marking
    remediation moves a `CONFIRMED` defect to `REMEDIATED`; in all three the approver's
    identifier is recorded in `confirmed_by_user_id`."

    Design: Corner/state_machines/defect_dismiss_records_confirmer
    """
    _lender, _case, review = _setup_endorsed_with_review(api, legal_name="Dismiss Co")
    defect = record_defect(
        review["id"], defect_code="ASSET_VERIFICATION_MISSING", detail="missing VOD"
    )
    response = api_client.confirm_defect(
        defect["id"], {"decision": "DISMISS"}, make_approver_headers("app-1")
    )
    data = validate_success(response)
    assert data["status"] == "DISMISSED"
    assert data["confirmed_by_user_id"] == "app-1"


def test_defect_confirm_tier3_leaves_review_and_case_untouched(api):
    """PRD §3.5: "Confirming a `TIER_1` defect fires cascade A in three hops"
    PRD §3.5: "a score of at least 50 lands the defect in `TIER_1`; a score of at least
    25 but below 50 lands it in `TIER_2`; anything below 25 is `TIER_3`."

    Design: Corner/state_machines/defect_confirm_tier3_leaves_review_and_case_untouched
    """
    lender, case, review = _setup_endorsed_with_review(api, legal_name="Tier3 Co")
    defect = record_defect(
        review["id"], defect_code="ASSET_VERIFICATION_MISSING", detail="missing VOD"
    )
    # Weight 20, no pattern, case not in default: score 20 -> TIER_3.
    assert defect["severity_score"] == 20
    assert defect["severity_tier"] == "TIER_3"
    confirmed = confirm_defect(defect["id"], "CONFIRM")
    assert confirmed["status"] == "CONFIRMED"
    # No cascade: the review and the case are untouched.
    assert get_review_of_case(case["id"])["status"] == "FINDINGS_RECORDED"
    assert get_case(case["id"])["endorsement_integrity"] == "SOUND"


def test_defect_mark_remediated_moves_confirmed_to_remediated(api):
    """PRD §3.5: "marking remediation moves a `CONFIRMED` defect to `REMEDIATED`"

    Design: Corner/state_machines/defect_mark_remediated_moves_confirmed_to_remediated
    """
    _lender, _case, review = _setup_endorsed_with_review(api, legal_name="Remediate Co")
    defect = record_defect(
        review["id"], defect_code="ASSET_VERIFICATION_MISSING", detail="missing VOD"
    )
    confirm_defect(defect["id"], "CONFIRM")
    response = api_client.confirm_defect(
        defect["id"], {"decision": "MARK_REMEDIATED"}, make_approver_headers("app-1")
    )
    data = validate_success(response)
    assert data["status"] == "REMEDIATED"


# ---------------------------------------------------------------------------
# Review close
# ---------------------------------------------------------------------------
def test_review_close_success_sets_closed_at(api):
    """PRD §3.5: "Closure stamps `closed_at` from the logical clock. If any `CONFIRMED`
    `TIER_1` defect remains unremediated at close, the system auto-creates an
    `IndemnificationAgreement` in `DRAFT` status whose `coverage_cap_cents` equals the
    defect severity exposure — the claim total basis — and whose `created_by_user_id`
    is the literal value `system`. If no `CONFIRMED` `TIER_1` defect remains, the
    case's `endorsement_integrity` restores to `SOUND` and every escrow frozen with
    `freeze_origin` `IMPAIRMENT` returns to `OPEN`."

    Design: Corner/state_machines/review_close_success_sets_closed_at
    """
    _lender, case, review = _setup_endorsed_with_review(api, legal_name="Close Co")
    defect = record_defect(
        review["id"], defect_code="ASSET_VERIFICATION_MISSING", detail="missing VOD"
    )
    confirm_defect(defect["id"], "DISMISS")
    closed = close_review(review["id"])
    assert closed["status"] == "CLOSED"
    assert_timestamp_startswith(closed["closed_at"], "2026-09-01T00:00:00", "closed_at")
    assert get_case(case["id"])["endorsement_integrity"] == "SOUND"
    agreements = list_agreements(case["id"])
    assert agreements == [] or len(agreements) == 0


def test_review_close_with_unremediated_tier1_auto_drafts_indemnification(api):
    """PRD §3.5: "If any `CONFIRMED` `TIER_1` defect remains unremediated at close, the
    system auto-creates an `IndemnificationAgreement` in `DRAFT` status whose
    `coverage_cap_cents` equals the defect severity exposure — the claim total basis —
    and whose `created_by_user_id` is the literal value `system`."

    Design: Corner/state_machines/review_close_with_unremediated_tier1_auto_drafts_indemnification
    """
    # INCOME_MISCALC (weight 40) on an IN_DEFAULT case: 40 * 1.25 == 50 -> TIER_1.
    lender, case, review = _setup_endorsed_with_review(
        api, legal_name="Auto Draft Co", default=True
    )
    defect = record_defect(
        review["id"], defect_code="INCOME_MISCALC", detail="overtime averaged wrong"
    )
    confirm_defect(defect["id"], "CONFIRM")
    closed = close_review(review["id"])
    assert closed["status"] == "CLOSED"
    data, meta = validate_paginated(
        api_client.list_indemnification_agreements(case["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1
    assert data[0]["status"] == "DRAFT"
    assert data[0]["created_by_user_id"] == "system"


# ---------------------------------------------------------------------------
# Review opening gates
# ---------------------------------------------------------------------------
def test_reviewer_conflict_when_endorser_opens_review(api):
    """PRD §3.5: "the reviewer must differ from the case's `endorsement_reviewer_id` —
    the person who endorsed the case may not review their own endorsement, and the
    attempt is rejected with `ERR_REVIEWER_CONFLICT`"

    Design: Corner/validations/reviewer_conflict_when_endorser_opens_review
    """
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Conflict Co"}, endorser="rev-1"
    )
    response = api_client.create_post_endorsement_review(
        case["id"], {"scope_codes": ["INCOME"]}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_REVIEWER_CONFLICT)


def test_error_review_window_passed(api):
    """PRD §3.5: "the review must be opened within 24 months of the `endorsement_date`,
    or it is rejected with `ERR_REVIEW_WINDOW_PASSED`"

    Design: Corner/errors/error_review_window_passed
    """
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Window Co"}, endorser="rev-1"
    )
    # More than 24 months after the 2026-09-01 endorsement; a different reviewer, so
    # only the temporal gate can fail.
    set_clock("2028-09-02T00:00:00Z")
    response = api_client.create_post_endorsement_review(
        case["id"], {"scope_codes": ["INCOME"]}, make_reviewer_headers("rev-2")
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_PASSED)


def test_error_review_already_open(api):
    """PRD §3.5: "the case must not already have a review in `INITIATED`,
    `FINDINGS_RECORDED`, or `CLOSURE_PENDING`, or the attempt is rejected with
    `ERR_REVIEW_ALREADY_OPEN`."

    Design: Corner/errors/error_review_already_open
    """
    _lender, case, _review = _setup_endorsed_with_review(api, legal_name="Two Reviews Co")
    response = api_client.create_post_endorsement_review(
        case["id"], {"scope_codes": ["ASSETS"]}, make_reviewer_headers("rev-3")
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_ALREADY_OPEN)


def test_error_defects_open_on_review_close(api):
    """PRD §3.5: "Closing the review requires every defect of the review to have
    reached a terminal disposition — `CONFIRMED`, `REMEDIATED`, or `DISMISSED` — and is
    rejected with `ERR_DEFECTS_OPEN` while any defect remains `OPEN`."

    Design: Corner/errors/error_defects_open_on_review_close
    """
    _lender, _case, review = _setup_endorsed_with_review(api, legal_name="Open Defect Co")
    record_defect(review["id"], defect_code="QC_PLAN_VIOLATION", detail="missing sample")
    response = api_client.close_review(review["id"], make_reviewer_headers("rev-2"))
    validate_error(response, ApiErrorId.ERR_DEFECTS_OPEN)
    assert get_review_of_case(_case["id"])["status"] == "FINDINGS_RECORDED"


def test_claims_examiner_cannot_confirm_defects(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the endpoint
    — or, on the lender lifecycle endpoint, not permitted for the requested action — is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mi/defects/{defectId}/confirm | Confirm, dismiss, or mark a
    defect remediated | FhaApprover |"

    Design: Corner/rbac/claims_examiner_cannot_confirm_defects
    """
    _lender, _case, review = _setup_endorsed_with_review(api, legal_name="RBAC Defect Co")
    defect = record_defect(review["id"], defect_code="QC_PLAN_VIOLATION", detail="missing sample")
    response = api_client.confirm_defect(
        defect["id"], {"decision": "CONFIRM"}, make_examiner_headers("cx-1")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Difficulty: cascade A — TIER_1 confirm reaches review, case, escrow
# ---------------------------------------------------------------------------
def _setup_tier1_cascade(api):
    """Endorsed (by rev-alpha) then defaulted case holding an OPEN escrow and a review
    (by rev-gamma) with one recorded INCOME_MISCALC defect."""
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Cascade A Co"}, endorser="rev-alpha"
    )
    lid, cid = lender["id"], case["id"]
    escrow = create_escrow(
        cid, lid, amount_cents=500_000, start_date="2026-09-01", end_date="2026-12-31"
    )
    set_clock("2026-10-01T00:00:00Z")
    declare_default(cid, lid)
    review = open_review(cid, reviewer="rev-gamma", scope_codes=["UNDERWRITING"])
    defect = record_defect(
        review["id"], reviewer="rev-gamma",
        defect_code="INCOME_MISCALC", detail="income overstated",
    )
    return lender, case, escrow, review, defect


def test_tier1_defect_scoring_and_confirm(api):
    """PRD §3.5: "The default multiplier is one and a quarter when the case is
    `IN_DEFAULT` at the moment the defect is created, and one otherwise. The
    `severity_score` is the base weight multiplied by both multipliers, rounded half-up
    to an integer, with the multipliers applied before rounding. The score determines
    the defect's `severity_tier`: a score of at least 50 lands the defect in `TIER_1`"
    PRD §3.5: "confirming it moves it from `OPEN` to `CONFIRMED`, dismissing moves it
    from `OPEN` to `DISMISSED`, and marking remediation moves a `CONFIRMED` defect to
    `REMEDIATED`; in all three the approver's identifier is recorded in
    `confirmed_by_user_id`."

    Design: Difficulty/transitive_cascade/tier1_defect_confirm_cascades_review_case_escrow
    """
    _lender, case, _escrow, review, defect = _setup_tier1_cascade(api)
    # INCOME_MISCALC weight 40 x default multiplier 1.25 == 50: exactly TIER_1.
    assert defect["severity_score"] == 50
    assert defect["severity_tier"] == "TIER_1"
    confirmed = confirm_defect(defect["id"], "CONFIRM", approver="appr-beta")
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by_user_id"] == "appr-beta"
    # Cascade hop 1: the review moved to CLOSURE_PENDING.
    assert get_review_of_case(case["id"])["status"] == "CLOSURE_PENDING"


def test_tier1_defect_confirm_cascades_to_case_and_escrow(api):
    """PRD §3.5: "Confirming a `TIER_1` defect fires cascade A in three hops: the
    defect's review moves from `FINDINGS_RECORDED` to `CLOSURE_PENDING`; the case's
    `endorsement_integrity` flips to `IMPAIRED`; and every `OPEN` repair escrow of the
    case is frozen with `freeze_origin` set to `IMPAIRMENT`."

    Design: Difficulty/transitive_cascade/tier1_defect_confirm_cascades_review_case_escrow
    """
    _lender, case, escrow, _review, defect = _setup_tier1_cascade(api)
    confirm_defect(defect["id"], "CONFIRM", approver="appr-beta")
    # Hop 2: the case is impaired.
    assert get_case(case["id"])["endorsement_integrity"] == "IMPAIRED"
    # Hop 3: the case's OPEN escrow froze with the impairment origin.
    escrows = list_escrows(case["id"])
    by_id = {e["id"]: e for e in escrows}
    assert by_id[escrow["id"]]["status"] == "FROZEN"
    assert by_id[escrow["id"]]["freeze_origin"] == "IMPAIRMENT"


# ---------------------------------------------------------------------------
# Difficulty: priority pair — segregation beats temporal window
# ---------------------------------------------------------------------------
def _setup_endorsed_past_review_window(api):
    """Case endorsed 2026-09-01 by rev-alpha; clock advanced past the 24-month
    review window."""
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Priority Review Co"}, endorser="rev-alpha"
    )
    set_clock("2028-09-02T00:00:00Z")
    return lender, case


def test_review_create_segregation_beats_temporal_window(api):
    """PRD §2.7: "When a request violates more than one rule, the platform reports the
    violation whose category ranks earliest in the following priority order, so a
    caller always sees the most fundamental problem first:"
    PRD §2.7: "8. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`,
    `ERR_REVIEWER_CONFLICT`)."
    PRD §2.7: "10. Temporal windows (`ERR_APPRAISAL_EXPIRED`,
    `ERR_TRANSFER_WINDOW_CLOSED`, `ERR_FILING_STALE`, `ERR_REVIEW_WINDOW_PASSED`,
    `ERR_CLAIM_DEADLINE_PASSED`, `ERR_ESCROW_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/review_create_segregation_beats_temporal_window
    """
    _lender, case = _setup_endorsed_past_review_window(api)
    # The caller is BOTH the original endorser (segregation, priority 8) AND past the
    # 24-month window (temporal, priority 10): the earlier category is reported.
    response = api_client.create_post_endorsement_review(
        case["id"], {"scope_codes": ["UNDERWRITING"]}, make_reviewer_headers("rev-alpha")
    )
    validate_error(response, ApiErrorId.ERR_REVIEWER_CONFLICT)
    data, meta = validate_paginated(
        api_client.list_post_endorsement_reviews(case["id"], make_admin_headers())
    )
    assert meta["total_count"] == 0


def test_review_create_temporal_window_fires_in_isolation(api):
    """PRD §3.5: "the review must be opened within 24 months of the `endorsement_date`,
    or it is rejected with `ERR_REVIEW_WINDOW_PASSED`"

    The isolated temporal leg of the priority pair: with a reviewer who did not endorse
    the case, only the window can fail.

    Design: Difficulty/priority_pair_validation_conflict/review_create_segregation_beats_temporal_window
    """
    _lender, case = _setup_endorsed_past_review_window(api)
    response = api_client.create_post_endorsement_review(
        case["id"], {"scope_codes": ["UNDERWRITING"]}, make_reviewer_headers("rev-beta")
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_PASSED)

