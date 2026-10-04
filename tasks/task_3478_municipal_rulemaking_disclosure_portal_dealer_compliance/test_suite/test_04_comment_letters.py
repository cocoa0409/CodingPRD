"""Comment letters: filing gates (state before temporal), moderation
terminal states, window bounds, and the submission gate (PRD sections
2.5, 3.1, 3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_comment_letter,
    create_dealer_org,
    create_open_for_comment_proposal,
    create_pending_approval_proposal,
    create_rule_proposal,
    make_dealer_rep_headers,
    moderate_letter,
    open_comment_period,
    set_clock,
    submit_proposal,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["rulemaking_officer_headers"]
PUBLIC = TEST_USERS["public_reader_headers"]
PORTAL_OPERATOR = TEST_USERS["portal_operator_headers"]

UNKNOWN_LETTER_ID = "11111111-2222-3333-4444-555555555555"


def test_comment_on_pending_approval_reports_state_gate_not_window(api):
    """PRD section 3.1: "the proposal must currently be `OPEN_FOR_COMMENT`
    — a filing against a proposal in any other status is rejected with
    `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` (HTTP 409) regardless of whether
    its window has also ended". Here the window has ended AND the proposal
    has moved on; the state gate still reports.

    Design: Difficulty/priority_pair_validation_conflict/comment_state_gate_beats_window_temporal
    """
    proposal = create_pending_approval_proposal(
        api, rule_code="G-920", title="Priority rule", body="p", category="MARKET_DATA"
    )
    # Clock is at the 21-day window end; the proposal is PENDING_APPROVAL.
    resp = api.create_comment_letter(
        proposal["id"],
        {"author_name": "Ann", "body": "too late", "sentiment": "SUPPORT"},
        PUBLIC,
    )
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT)


def test_comment_on_never_opened_draft_reports_state_gate(api):
    """PRD section 2.5: "a comment letter filed on a proposal that was
    never opened reports `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` even if its
    window would also have ended".

    Design: Difficulty/priority_pair_validation_conflict/comment_state_gate_beats_window_temporal
    """
    proposal = create_rule_proposal(
        api, rule_code="G-921", title="Draft target", body="d", category="DISCLOSURE"
    )
    resp = api.create_comment_letter(
        proposal["id"],
        {"author_name": "Bea", "body": "not open", "sentiment": "NEUTRAL"},
        PUBLIC,
    )
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT)


def test_submit_blocked_by_unmoderated_letter_then_published_retry_passes(api):
    """PRD section 3.1: "it requires that zero comment letters on the
    proposal remain in `RECEIVED`: every letter must first be moderated per
    §3.3, and any unmoderated remainder is rejected with
    `ERR_UNRESOLVED_COMMENTS` (HTTP 409)". PRD section 3.3: "both outcomes
    clear the proposal's path to approval — what matters is that no letter
    remains unexamined."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_unmoderated_comment_letters
    """
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-930", title="Gate rule", body="g", category="ADVISOR_CONDUCT"
    )
    letter = create_comment_letter(
        api, proposal["id"], author_name="Citizen", body="concerns", sentiment="OPPOSE"
    )
    set_clock(api, "2026-09-22T00:00:00Z")  # window has ended

    blocked = api.submit_for_approval(proposal["id"], OFFICER)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_COMMENTS)

    moderate_letter(api, letter["id"], "PUBLISH")
    submitted = submit_proposal(api, proposal["id"])
    assert submitted["status"] == "PENDING_APPROVAL", (
        f"after moderation the identical retry must succeed, got {submitted['status']!r}"
    )


def test_unresolved_comments_gate_fires_before_window_still_open(api):
    """PRD section 3.1: "and, evaluated before that window check per
    §2.5, it requires that zero comment letters on the proposal remain in
    `RECEIVED`". With the window still open and one letter
    unmoderated, the comment gate reports first; a dismissal also clears
    the path (section 3.3: "both outcomes clear the proposal's path to
    approval").

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_unmoderated_comment_letters
    """
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-931", title="Priority gate", body="g", category="ADVISOR_CONDUCT"
    )
    letter = create_comment_letter(
        api, proposal["id"], author_name="Citizen", body="concerns", sentiment="NEUTRAL"
    )
    # Window still open (clock untouched) AND one letter in RECEIVED.
    blocked = api.submit_for_approval(proposal["id"], OFFICER)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_COMMENTS)

    moderate_letter(api, letter["id"], "DISMISS", reason="duplicative")
    set_clock(api, "2026-09-22T00:00:00Z")
    submitted = submit_proposal(api, proposal["id"])
    assert submitted["status"] == "PENDING_APPROVAL"


def test_moderating_dismissed_letter_rejected_invalid_state(api):
    """PRD section 3.3: "Both `PUBLISHED` and `DISMISSED` are terminal, and
    moderating a letter that has already reached either state is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/moderate_dismissed_letter_returns_invalid_state
    """
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-003", title="Moderation rule", body="m", category="MARKET_DATA"
    )
    letter = create_comment_letter(
        api, proposal["id"], author_name="Spammer", body="junk", sentiment="NEUTRAL"
    )
    moderate_letter(api, letter["id"], "DISMISS", reason="duplicative")

    resp = api.moderate_comment_letter(letter["id"], {"action": "PUBLISH"}, PORTAL_OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_comment_window_is_half_open_at_the_end_instant(api):
    """PRD section 3.1: "the window is half-open, accepting comments
    strictly before the end instant" and "at exactly the end instant the
    window is already closed and the filing is rejected with
    `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422)". A 21-day window opened at
    2026-09-01T00:00:00Z ends at 2026-09-22T00:00:00Z.

    Design: Corner/validations/comment_window_half_open_end_boundary
    """
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-306", title="Half-open rule", body="h", category="DISCLOSURE"
    )
    set_clock(api, "2026-09-21T23:59:59Z")
    in_time = create_comment_letter(
        api, proposal["id"], author_name="In Time", body="ok", sentiment="SUPPORT"
    )
    assert in_time["status"] == "RECEIVED"

    set_clock(api, "2026-09-22T00:00:00Z")
    resp = api.create_comment_letter(
        proposal["id"],
        {"author_name": "Too Late", "body": "nope", "sentiment": "OPPOSE"},
        PUBLIC,
    )
    validate_error(resp, ApiErrorId.ERR_COMMENT_WINDOW_CLOSED)


def test_submit_before_window_end_rejected_period_still_open(api):
    """PRD section 3.1: "Submission requires the comment window to have
    ended — the current logical time must be at or after
    `comment_window_end`, otherwise the request is rejected with
    `ERR_COMMENT_PERIOD_STILL_OPEN` (HTTP 422)".

    Design: Corner/validations/submit_before_window_end_returns_period_still_open
    """
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-307", title="Early submit", body="e", category="ADVISOR_CONDUCT"
    )
    # No letters, but the clock has not reached the window end.
    resp = api.submit_for_approval(proposal["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_STILL_OPEN)


def test_comment_period_days_bounds_enforced(api):
    """PRD section 3.1: `comment_period_days` is "the length of the comment
    window in days, which must be at least 21 and at most 90, with anything
    outside that range rejected as `ERR_COMMENT_PERIOD_TOO_SHORT`
    (HTTP 422)".

    Design: Corner/validations/comment_period_days_bounds_enforced
    """
    proposal = create_rule_proposal(
        api, rule_code="G-305", title="Bounds rule", body="b", category="QUALIFICATION"
    )
    too_short = api.open_comment_period(proposal["id"], {"comment_period_days": 20}, OFFICER)
    validate_error(too_short, ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT)
    too_long = api.open_comment_period(proposal["id"], {"comment_period_days": 91}, OFFICER)
    validate_error(too_long, ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT)

    ok = api.open_comment_period(proposal["id"], {"comment_period_days": 21}, OFFICER)
    data = validate_success(ok, 200)
    assert data["status"] == "OPEN_FOR_COMMENT", (
        f"21 days is the inclusive lower bound and must open, got {data['status']!r}"
    )


def test_dealer_rep_cannot_moderate_comment_letter(api):
    """PRD section 2.1: "an attempt to perform an action outside the
    caller's designated role is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)". PRD section 3.3: letters are moderated by "a
    `PortalOperator`".

    Design: Corner/rbac/dealerrep_cannot_moderate_comment
    """
    org = create_dealer_org(api, org_code="BD-6001", name="Dealer Moderator")
    proposal = create_open_for_comment_proposal(
        api, days=21, rule_code="G-501", title="Moderation rbac", body="m", category="DISCLOSURE"
    )
    letter = create_comment_letter(
        api, proposal["id"], author_name="Reader", body="note", sentiment="NEUTRAL"
    )
    resp = api.moderate_comment_letter(
        letter["id"], {"action": "PUBLISH"}, make_dealer_rep_headers(org["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_moderate_unknown_letter_returns_comment_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for comment letters that identifier is
    `ERR_COMMENT_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/moderate_unknown_letter_returns_comment_not_found
    """
    resp = api.moderate_comment_letter(UNKNOWN_LETTER_ID, {"action": "PUBLISH"}, PORTAL_OPERATOR)
    validate_error(resp, ApiErrorId.ERR_COMMENT_NOT_FOUND)
