"""Rule proposal drafting, editing (OCC), comment-window opening, and the
decision gate (PRD sections 2.6, 3.1; effectiveness scheduling per 2.4/3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_days,
    assert_instant,
    create_approved_proposal,
    create_disapproved_proposal,
    create_pending_approval_proposal,
    create_rule_proposal,
    decide_proposal,
    get_success_data,
    make_regulator_headers,
    open_comment_period,
    patch_rule_proposal_payload,
    read_proposal,
    set_clock,
    submit_proposal,
    validate_error,
    validate_success,
)
from test_helpers import CLOCK_START

OFFICER = TEST_USERS["rulemaking_officer_headers"]
OFFICER_ALT = TEST_USERS["rulemaking_officer_alt_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


def test_proposal_created_draft_with_zeroed_round_and_no_supersession(api):
    """PRD section 3.1: "A proposal is born in `DRAFT` with its
    `comment_round` at 0 and its `expedited` flag false." The supersession
    target is optional at creation ("the officer may also declare an
    optional `supersedes_proposal_id`"), so an undeclared proposal has no
    supersession target.

    Design: Corner/entities/proposal_create_defaults_draft_no_supersede
    """
    resp = api.create_rule_proposal(
        {"rule_code": "G-001", "title": "Defaults rule", "body": "d", "category": "QUALIFICATION"},
        OFFICER,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", f"fresh proposal must be DRAFT, got {data['status']!r}"
    assert data["comment_round"] == 0
    assert data["expedited"] is False
    assert data.get("supersedes_proposal_id") is None


def test_decide_on_draft_proposal_rejected_invalid_state(api):
    """PRD section 3.1: "A decision attempted on a proposal that is not
    `PENDING_APPROVAL` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_on_draft_proposal_returns_invalid_state
    """
    proposal = create_rule_proposal(
        api, rule_code="G-002", title="Early decide", body="e", category="DISCLOSURE"
    )
    resp = api.decide_proposal(proposal["id"], {"decision": "APPROVE"}, REGULATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_open_comment_period_stamps_window_and_round(api):
    """PRD section 3.1: "Opening records `comment_window_start` as the
    current logical time and derives `comment_window_end` as the start plus
    the stated number of days; the window is half-open, accepting comments
    strictly before the end instant. The `comment_round` counter, 0 at
    creation, is set to 1 by the first opening and increments by one on
    every subsequent `DRAFT` → `OPEN_FOR_COMMENT` transition after a
    revision cycle". The logical clock starts at exactly
    `2026-09-01T00:00:00Z` (PRD section 2.4).

    Design: Corner/state_machines/open_comment_period_sets_window_fields
    """
    proposal = create_rule_proposal(
        api, rule_code="G-004", title="Window rule", body="w", category="DISCLOSURE"
    )
    resp = api.open_comment_period(
        proposal["id"], {"comment_period_days": 21, "expedited": True}, OFFICER
    )
    data = validate_success(resp, 200)
    assert data["status"] == "OPEN_FOR_COMMENT"
    assert_instant(data["comment_window_start"], "2026-09-01T00:00:00Z", "comment_window_start")
    assert_instant(data["comment_window_end"], "2026-09-22T00:00:00Z", "comment_window_end")
    assert data["comment_round"] == 1
    assert data["expedited"] is True


def test_stale_patch_rejected_then_fresh_patch_succeeds(api):
    """PRD section 2.6: "If the presented value does not match the
    proposal's current `version` — for example because another edit, an
    open-comment-period, or a decision has advanced the proposal since the
    client last read it — the write is rejected as stale with
    `ERR_STALE_VERSION` (HTTP 412)". PRD section 3.1: "Every successful
    edit increments the proposal's `version` by one."

    Design: Corner/cross_cutting_layers/stale_patch_rejected_then_fresh_patch_succeeds
    """
    proposal = create_rule_proposal(
        api, rule_code="G-600", title="OCC rule", body="o", category="DISCLOSURE"
    )
    observed_version = proposal["version"]

    stale = api.patch_rule_proposal(
        proposal["id"],
        patch_rule_proposal_payload(observed_version - 1, title="stale edit"),
        OFFICER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = api.patch_rule_proposal(
        proposal["id"],
        patch_rule_proposal_payload(observed_version, title="fresh edit"),
        OFFICER,
    )
    data = validate_success(fresh, 200)
    assert data["version"] == observed_version + 1, (
        f"successful edit must increment version by exactly one: "
        f"{observed_version} -> {data['version']}"
    )
    assert data["title"] == "fresh edit"


def test_approved_proposal_waits_for_its_effective_date(api):
    """PRD section 3.2: "Effectiveness itself is conferred by the epoch
    pass of §2.4: when the logical clock reaches or passes a proposal's
    `effective_at`, the proposal transitions from `APPROVED` to
    `EFFECTIVE`, with due proposals processed oldest-effective-first."

    Design: Corner/cross_cutting_layers/approved_proposal_waits_for_effective_date
    """
    proposal = create_approved_proposal(
        api, days=21, expedited=False, rule_code="G-601", title="Scheduled rule",
        body="s", category="DEALER_CONDUCT",
    )
    # Approved at the 21-day window end (2026-09-22); standard delay is 30 days.
    assert_instant(proposal["approval_at"], "2026-09-22T00:00:00Z", "approval_at")
    assert_instant(proposal["effective_at"], "2026-10-22T00:00:00Z", "effective_at")

    set_clock(api, "2026-10-21T00:00:00Z")
    before = read_proposal(api, proposal["id"])
    assert before["status"] == "APPROVED", (
        f"one day before effective_at the proposal must still be APPROVED, got {before['status']!r}"
    )

    set_clock(api, "2026-10-22T00:00:00Z")
    at = read_proposal(api, proposal["id"])
    assert at["status"] == "EFFECTIVE", (
        f"at exactly effective_at the epoch pass must effectuate, got {at['status']!r}"
    )


def test_regulator_who_submitted_proposal_cannot_decide_it(api):
    """PRD section 3.1: "Segregation of duties is enforced: the deciding
    regulator's `X-User-ID` must differ from the recorded
    `submitted_by_user_id`, and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/regulator_deciding_own_submission_returns_segregation
    """
    proposal = create_pending_approval_proposal(
        api, rule_code="G-301", title="SoD rule", body="s", category="DEALER_CONDUCT"
    )
    # The proposal was submitted by officer-1 (the default officer identity);
    # a Regulator presenting that same identifier is the segregated case.
    resp = api.decide_proposal(
        proposal["id"], {"decision": "APPROVE"}, make_regulator_headers("officer-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_disapproval_revision_cycle_reopens_with_round_two(api):
    """PRD section 3.1: "A successful revision of a `DISAPPROVED` proposal
    reopens it as a draft — the revision cycle". PRD section 3.1: "The
    `comment_round` counter, 0 at creation, is set to 1 by the first opening
    and increments by one on every subsequent `DRAFT` → `OPEN_FOR_COMMENT`
    transition after a revision cycle". PRD section 2.8: "`version` — a
    system-managed integer that increments by exactly one on every mutation
    of the resource".

    Design: Difficulty/non_linear_state_machine/proposal_disapproval_revision_cycle
    """
    proposal = create_rule_proposal(
        api, rule_code="G-910", title="Cycle rule", body="v1", category="DISCLOSURE"
    )
    open_comment_period(api, proposal["id"], days=21, expedited=False)
    set_clock(api, "2026-09-22T00:00:00Z")
    submit_proposal(api, proposal["id"])
    disapproved = decide_proposal(api, proposal["id"], "DISAPPROVE", reason="needs rework")
    decide_version = disapproved["version"]

    patched = get_success_data(
        api.patch_rule_proposal(
            proposal["id"],
            patch_rule_proposal_payload(decide_version, title="Cycle rule revised"),
            OFFICER,
        )
    )
    assert patched["status"] == "DRAFT", (
        f"revising a DISAPPROVED proposal must reopen it as DRAFT, got {patched['status']!r}"
    )
    assert patched["version"] == decide_version + 1

    reopened = open_comment_period(api, proposal["id"], days=30, expedited=False)
    assert reopened["status"] == "OPEN_FOR_COMMENT"
    assert reopened["comment_round"] == 2, (
        f"second open after a revision cycle must yield comment_round 2, got {reopened['comment_round']}"
    )
    # The second window anchors at the current logical time (2026-09-22).
    assert_instant(reopened["comment_window_start"], "2026-09-22T00:00:00Z", "round-2 window start")
    assert_instant(reopened["comment_window_end"], "2026-10-22T00:00:00Z", "round-2 window end")


def test_revision_of_disapproved_proposal_clears_decision_history(api):
    """PRD section 3.1: "A successful revision of a `DISAPPROVED` proposal
    reopens it as a draft — the revision cycle — and in doing so clears
    `submitted_by_user_id`, `decided_by_user_id`, and `decision_reason`, so
    the reworked proposal re-enters the pipeline with a clean decision
    history."

    Design: Difficulty/non_linear_state_machine/proposal_disapproval_revision_cycle
    """
    proposal = create_disapproved_proposal(api, reason="needs rework", rule_code="G-911")
    current = read_proposal(api, proposal["id"])
    assert current["status"] == "DISAPPROVED"
    assert current["decision_reason"] == "needs rework"
    assert current["submitted_by_user_id"] == "officer-1"

    patched = get_success_data(
        api.patch_rule_proposal(
            proposal["id"],
            patch_rule_proposal_payload(current["version"], title="Cycle rule revised"),
            OFFICER_ALT,
        )
    )
    assert patched["status"] == "DRAFT"
    assert patched.get("submitted_by_user_id") is None, "revision must clear submitted_by_user_id"
    assert patched.get("decided_by_user_id") is None, "revision must clear decided_by_user_id"
    assert patched.get("decision_reason") is None, "revision must clear decision_reason"
