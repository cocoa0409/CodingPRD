"""Non-linear state machines: the term's two independent dimensions and the
tool's three-way finalize fork with a full review cycle.

Every test builds its own world from scratch — the server is relaunched before
each test, so the database is empty and the logical clock reads its startup
instant.
"""
from datetime import datetime

import pytest

from test_helpers import ApiErrorId, validate_error, validate_paginated, validate_success
from test_helpers import factories as fac
from test_helpers import fixtures as fx

#: The instant the logical clock reads on startup (PRD §2.5).
CLOCK_STARTUP = "2026-08-01T00:00:00Z"

#: Governance metadata whose risk score is 0 + 10 + 3.00 + 0 + 0 = 13.00.
TOOL_METADATA = {
    "vendor_name": "OpenCampus",
    "tool_name": "PeerNotes",
    "tool_version": "1.0.0",
    "data_sharing_scope": "ROSTER_ONLY",
    "pii_tier": 0,
    "vpat_score": 90.00,
    "wcag_level": "AA",
}

OUTAGE_WINDOW_START = "2026-12-07T08:00:00Z"
OUTAGE_WINDOW_END = "2026-12-08T08:00:00Z"


def _instant(value):
    """Parse an ISO-8601 UTC instant into a comparable datetime."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _term_in_finals(api):
    """A term walked PLANNING -> REGISTRATION_OPEN -> IN_SESSION -> FINALS.

    Returns (term_at_create, term_at_registration_open, term_at_finals).
    """
    term = fx.create_term(api)
    at_open = fx.transition_term(api, term["id"], "REGISTRATION_OPEN")
    fx.transition_term(api, term["id"], "IN_SESSION")
    at_finals = fx.transition_term(api, term["id"], "FINALS")
    return term, at_open, at_finals


def _open_outage_window(api, term_id):
    """Open a term-wide OUTAGE window, echoing the term's live version."""
    return fx.open_window_for(
        api, term_id, "OUTAGE", OUTAGE_WINDOW_START, OUTAGE_WINDOW_END
    )


def _tool_with_round_one_verdicts(api, privacy_decision, accessibility_decision,
                                  privacy_user="priv-rev-1",
                                  accessibility_user="acc-rev-1"):
    """A registered tool moved to UNDER_REVIEW with both dimensions decided."""
    tool = fx.register_tool(api, **TOOL_METADATA)
    fx.transition_tool(api, tool["id"], "OPEN_REVIEW")
    privacy_extra = (
        {"conditions_note": "no third-party analytics on roster data"}
        if privacy_decision == "CONDITIONS" else {}
    )
    review_privacy = fx.file_review(
        api, tool["id"], "PRIVACY", privacy_decision,
        user_id=privacy_user, **privacy_extra
    )
    review_access = fx.file_review(
        api, tool["id"], "ACCESSIBILITY", accessibility_decision,
        user_id=accessibility_user,
    )
    return tool, review_privacy, review_access


def test_term_opens_with_two_independent_dimensions_and_no_direct_posture_edge(
    api, lms_admin_headers
):
    """PRD §3.1: "A newly registered term opens with `lifecycle_state` `PLANNING`
    and `continuity_posture` `NORMAL`, and with every aggregate counter at its
    floor: `published_shell_count`, `overflow_shell_count`,
    `total_active_enrollments`, `open_amendment_count` and `sis_sync_epoch` all
    read 0, while `rollover_completion_pct` reads 100.00 for the reason explained
    in §3.2."
    PRD §3.2: "When the eligible set is empty the percentage is 100.00 by
    convention — which is precisely why a brand-new term with no shells at all
    can open registration."
    PRD §3.9: "Jumping straight from `NORMAL` to `CONTINUITY_MODE` is **not** a
    declared transition and is refused with `ERR_INVALID_STATE_TRANSITION`; the
    escalation must be walked one step at a time."
    PRD §3.9: "It escalates `NORMAL` → `ELEVATED`, which requires the term's
    `lifecycle_state` to be `IN_SESSION`, `FINALS` or `GRADING` (otherwise
    `ERR_INVALID_STATE_TRANSITION`)."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer
    that starts at 1 on creation and increments by exactly one on every mutation
    of that record."

    Design: Difficulty/non_linear_state_machine/academic_term_reverse_edge_and_cross_dimension_guard_between_lifecycle_and_posture
    """
    term, at_open, at_finals = _term_in_finals(api)

    assert term["lifecycle_state"] == "PLANNING", (
        f"a newly registered term opens in PLANNING, got {term['lifecycle_state']}"
    )
    assert term["continuity_posture"] == "NORMAL", (
        f"a newly registered term opens in NORMAL, got {term['continuity_posture']}"
    )
    assert at_open["rollover_completion_pct"] == pytest.approx(100.00, abs=0.005), (
        "an empty eligible-shell set reads 100.00 and passes the registration "
        f"gate, got {at_open['rollover_completion_pct']}"
    )

    version_at_finals = at_finals["version"]

    jump = api.term_posture_change(
        term["id"],
        {"target_posture": "CONTINUITY_MODE", "reason": "skipping the ELEVATED step"},
        lms_admin_headers,
    )
    validate_error(jump, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    after_reject = fx.read_term(api, term["id"])
    assert after_reject["continuity_posture"] == "NORMAL", (
        "the refused posture change must leave the posture dimension where it was"
    )
    assert after_reject["version"] == version_at_finals, (
        f"a refused request mutates nothing, so version stays {version_at_finals}, "
        f"got {after_reject['version']}"
    )
    assert after_reject["lifecycle_state"] == "FINALS"

    elevated = validate_success(
        api.term_posture_change(
            term["id"],
            {"target_posture": "ELEVATED", "reason": "regional storm watch"},
            lms_admin_headers,
        ),
        200,
    )
    assert elevated["continuity_posture"] == "ELEVATED"
    assert elevated["version"] == version_at_finals + 1, (
        "escalating the posture mutates the term row exactly once, so version "
        f"should be {version_at_finals + 1}, got {elevated['version']}"
    )
    assert elevated["lifecycle_state"] == "FINALS", (
        "a posture change never moves the lifecycle dimension"
    )


def test_continuity_mode_freezes_finals_to_grading_and_unlocks_the_reverse_edge(
    api, registrar_headers, lms_admin_headers
):
    """PRD §3.9: "It escalates again `ELEVATED` → `CONTINUITY_MODE`, which requires
    at least one window of that term whose `kind` is `OUTAGE` and whose
    `window_state` is `OPEN` to exist, otherwise `ERR_INVALID_STATE_TRANSITION` —
    the highest posture must be justified by a live outage on the record."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the
    shell's `active_enrollment_count` for a shell-scoped window, or the term's
    `total_active_enrollments` for a term-wide one — and, for a window whose
    `kind` is `EXTENSION`, records `extension_days_granted` as the window's
    length in seconds divided by 86,400 and rounded **up** to a whole day, so
    that any partial day counts as a full granted day; every other kind records
    0."
    PRD §3.2: "Advancing `FINALS` → `GRADING` requires the term to currently be
    in `FINALS` and requires `continuity_posture` to be anything other than
    `CONTINUITY_MODE`; attempting it during continuity mode is refused with
    `ERR_TERM_POSTURE_FROZEN`."
    PRD §3.2: "Reversing `FINALS` → `IN_SESSION` is the mirror image: it is legal
    **only** while `continuity_posture` is `CONTINUITY_MODE`, and outside
    continuity mode it is refused with `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/academic_term_reverse_edge_and_cross_dimension_guard_between_lifecycle_and_posture
    """
    term, _at_open, _at_finals = _term_in_finals(api)
    fx.change_posture(api, term["id"], "ELEVATED", reason="regional storm watch")

    window = _open_outage_window(api, term["id"])
    assert window["window_state"] == "OPEN", (
        f"a freshly opened window is OPEN, got {window['window_state']}"
    )
    assert window["affected_enrollment_count"] == 0, (
        "a term-wide window records the term's total_active_enrollments, which is "
        f"0 here, got {window['affected_enrollment_count']}"
    )
    assert window["extension_days_granted"] == 0, (
        "only an EXTENSION window grants days; every other kind records 0, got "
        f"{window['extension_days_granted']}"
    )

    frozen = fx.change_posture(
        api, term["id"], "CONTINUITY_MODE", reason="campus network outage during finals"
    )
    assert frozen["continuity_posture"] == "CONTINUITY_MODE"
    assert frozen["lifecycle_state"] == "FINALS", (
        "the posture change must not move the lifecycle dimension off FINALS"
    )

    blocked = api.term_lifecycle_transition(
        term["id"], {"target_state": "GRADING"}, registrar_headers
    )
    validate_error(blocked, ApiErrorId.ERR_TERM_POSTURE_FROZEN.value)
    assert fx.read_term(api, term["id"])["lifecycle_state"] == "FINALS", (
        "the refused advance leaves the term in FINALS"
    )

    reversed_term = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "IN_SESSION"}, registrar_headers
        ),
        200,
    )
    assert reversed_term["lifecycle_state"] == "IN_SESSION", (
        "the backward FINALS -> IN_SESSION edge is reachable while the posture "
        f"is CONTINUITY_MODE, got {reversed_term['lifecycle_state']}"
    )
    assert reversed_term["continuity_posture"] == "CONTINUITY_MODE"


def test_closing_the_last_outage_window_does_not_walk_the_posture_back_by_itself(
    api, registrar_headers, lms_admin_headers
):
    """PRD §3.9: "It de-escalates `CONTINUITY_MODE` → `ELEVATED`, which requires
    the mirror image: **no** window of that term with `kind` `OUTAGE` and
    `window_state` `OPEN` may remain, otherwise `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.9: "Closing the last open outage window does not by itself change the
    posture."
    PRD §3.9: "A window is **closed** (`CLOSE`) from `OPEN`, which stamps
    `closed_at` from the logical clock, or **cancelled** (`CANCEL`) from `OPEN`,
    which requires the logical clock to still be strictly before its
    `window_start`, otherwise `ERR_WINDOW_ALREADY_STARTED` — a window that has
    already begun affecting students can be closed but never cancelled."
    PRD §2.5: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to real time."
    PRD §3.2: "Advancing `FINALS` → `GRADING` requires the term to currently be
    in `FINALS` and requires `continuity_posture` to be anything other than
    `CONTINUITY_MODE`; attempting it during continuity mode is refused with
    `ERR_TERM_POSTURE_FROZEN`."

    Design: Difficulty/non_linear_state_machine/academic_term_reverse_edge_and_cross_dimension_guard_between_lifecycle_and_posture
    """
    term, _at_open, _at_finals = _term_in_finals(api)
    fx.change_posture(api, term["id"], "ELEVATED", reason="regional storm watch")
    window = _open_outage_window(api, term["id"])
    fx.change_posture(
        api, term["id"], "CONTINUITY_MODE", reason="campus network outage during finals"
    )
    fx.transition_term(api, term["id"], "IN_SESSION")

    premature = api.term_posture_change(
        term["id"],
        {"target_posture": "ELEVATED", "reason": "outage not yet closed"},
        lms_admin_headers,
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    closed = validate_success(
        api.continuity_window_transition(
            window["id"], {"action": "CLOSE"}, lms_admin_headers
        ),
        200,
    )
    assert closed["window_state"] == "CLOSED"
    assert _instant(closed["closed_at"]) == _instant(CLOCK_STARTUP), (
        "closed_at is stamped from the logical clock, which still reads its "
        f"startup instant {CLOCK_STARTUP}, got {closed['closed_at']}"
    )

    still_frozen = fx.read_term(api, term["id"])
    assert still_frozen["continuity_posture"] == "CONTINUITY_MODE", (
        "closing the last open outage window must not walk the posture back by "
        f"itself, got {still_frozen['continuity_posture']}"
    )

    de_escalated = validate_success(
        api.term_posture_change(
            term["id"], {"target_posture": "ELEVATED", "reason": "outage resolved"},
            lms_admin_headers,
        ),
        200,
    )
    assert de_escalated["continuity_posture"] == "ELEVATED", (
        "de-escalation is legal once no OPEN OUTAGE window remains"
    )

    fx.transition_term(api, term["id"], "FINALS")
    graded = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "GRADING"}, registrar_headers
        ),
        200,
    )
    assert graded["lifecycle_state"] == "GRADING", (
        "the identical FINALS -> GRADING request now succeeds, decided purely by "
        "the sibling posture dimension"
    )


def test_new_tool_opens_pending_and_each_review_moves_exactly_one_dimension(
    api, lms_admin_headers, privacy_reviewer_headers, accessibility_reviewer_headers
):
    """PRD §3.7: "A new tool opens with `approval_state` `DRAFT`,
    `privacy_review_state` `PENDING`, `accessibility_review_state` `PENDING`,
    `risk_score` null, `approved_version` null, `active_placement_count` 0 and
    `suspension_reason` null."
    PRD §3.7: "An `LmsAdmin` opens the review by an `action` of `OPEN_REVIEW`,
    which takes `approval_state` `DRAFT` → `UNDER_REVIEW` and requires both
    verdict dimensions to be `PENDING`."
    PRD §3.7: "A `CLEAR` decision moves that dimension `PENDING` → `CLEARED`,
    `CONDITIONS` moves it `PENDING` → `CONDITIONAL`, and `BLOCK` moves it
    `PENDING` → `BLOCKED`."

    Design: Difficulty/non_linear_state_machine/tool_integration_three_way_finalize_fork_and_full_review_cycle_reset
    """
    created = validate_success(
        api.create_tool_integration(
            fac.create_tool_integration_payload(**TOOL_METADATA), lms_admin_headers
        ),
        201,
    )
    assert created["approval_state"] == "DRAFT"
    assert created["privacy_review_state"] == "PENDING"
    assert created["accessibility_review_state"] == "PENDING"
    assert created["risk_score"] is None
    assert created["approved_version"] is None
    assert created["active_placement_count"] == 0
    assert created["suspension_reason"] is None

    opened = validate_success(
        api.tool_integration_transition(
            created["id"], {"action": "OPEN_REVIEW"}, lms_admin_headers
        ),
        200,
    )
    assert opened["approval_state"] == "UNDER_REVIEW"
    assert opened["privacy_review_state"] == "PENDING"
    assert opened["accessibility_review_state"] == "PENDING", (
        "opening the review round moves only the approval dimension"
    )

    validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(
                created["id"], "PRIVACY", "CONDITIONS",
                conditions_note="no third-party analytics on roster data",
            ),
            privacy_reviewer_headers,
        ),
        201,
    )
    after_privacy = fx.read_tool(api, created["id"])
    assert after_privacy["privacy_review_state"] == "CONDITIONAL", (
        "a CONDITIONS decision moves its own dimension PENDING -> CONDITIONAL"
    )
    assert after_privacy["accessibility_review_state"] == "PENDING", (
        "one review moves one sibling dimension and nothing else"
    )
    assert after_privacy["approval_state"] == "UNDER_REVIEW", (
        "filing a verdict does not itself finalize the review"
    )

    validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(created["id"], "ACCESSIBILITY", "CLEAR"),
            accessibility_reviewer_headers,
        ),
        201,
    )
    after_both = fx.read_tool(api, created["id"])
    assert after_both["privacy_review_state"] == "CONDITIONAL"
    assert after_both["accessibility_review_state"] == "CLEARED", (
        "a CLEAR decision moves its own dimension PENDING -> CLEARED"
    )
    assert after_both["approval_state"] == "UNDER_REVIEW"


def test_conditions_verdict_forks_a_low_scoring_tool_into_conditional_then_suspends(
    api, lms_admin_headers
):
    """PRD §3.7: "All three branches first require both verdict dimensions to have
    left `PENDING`, otherwise `ERR_REVIEW_INCOMPLETE`, and all three recompute and
    persist `risk_score`."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension is
    `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `CONDITIONAL` when neither dimension
    is `BLOCKED` and either at least one dimension is `CONDITIONAL` or the score
    falls in the range from 40.00 up to but not including 70.00; `approved_version`
    is likewise set to the current `tool_version`, and a conditional tool may still
    be placed."
    PRD §3.7: "The PII points are the `pii_tier` multiplied by 10, so 0 through 30."
    PRD §3.7: "The scope points are 0 for `NONE`, 10 for `ROSTER_ONLY`, 25 for
    `ROSTER_AND_GRADES` and 40 for `FULL_PROFILE`."
    PRD §3.7: "The accessibility-gap points are 100 minus the `vpat_score`,
    multiplied by 0.30."
    PRD §3.7: "The conformance points are 20 for `NONE`, 10 for `A`, 0 for `AA` and
    **minus 5** for `AAA` — the top conformance level earns a credit, which is why
    the raw total can go below zero."
    PRD §3.7: "The exposure points are the `active_placement_count` multiplied by
    3, capped at 15."
    PRD §3.7: "An approved or conditional tool can be **suspended** (`SUSPEND`),
    which records `suspension_reason` from the request `reason` (defaulting to
    "privacy incident") and runs the service's deepest cascade in four hops."
    PRD §3.7: "The tool's `active_placement_count` is set to 0 and its `risk_score`
    is recomputed."

    Design: Difficulty/non_linear_state_machine/tool_integration_three_way_finalize_fork_and_full_review_cycle_reset
    """
    tool, _privacy_review, _accessibility_review = _tool_with_round_one_verdicts(
        api, "CONDITIONS", "CLEAR"
    )

    forked = validate_success(
        api.tool_integration_transition(
            tool["id"], {"action": "FINALIZE_REVIEW"}, lms_admin_headers
        ),
        200,
    )
    assert forked["risk_score"] == pytest.approx(13.00, abs=0.005), (
        "pii_tier 0 scores 0, ROSTER_ONLY scores 10, a vpat_score of 90.00 scores "
        "(100 - 90.00) * 0.30 = 3.00, wcag_level AA scores 0 and no active "
        f"placement scores 0, so the total is 13.00, got {forked['risk_score']}"
    )
    assert forked["approval_state"] == "CONDITIONAL", (
        "13.00 is below 40.00, so the number alone would have selected APPROVED; "
        "the CONDITIONAL privacy dimension picks the middle branch instead, got "
        f"{forked['approval_state']}"
    )
    assert forked["approved_version"] == "1.0.0", (
        "the CONDITIONAL branch pins approved_version to the current tool_version"
    )

    suspended = validate_success(
        api.tool_integration_transition(
            tool["id"],
            {"action": "SUSPEND", "reason": "vendor breach notification"},
            lms_admin_headers,
        ),
        200,
    )
    assert suspended["approval_state"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "vendor breach notification", (
        "suspension_reason is recorded from the request reason rather than the "
        "default"
    )
    assert suspended["active_placement_count"] == 0
    assert suspended["risk_score"] == pytest.approx(13.00, abs=0.005), (
        "the score is recomputed on suspension and the addends have not changed"
    )


def test_reopening_resets_both_dimensions_and_a_fresh_round_reaches_approved(
    api, lms_admin_headers, privacy_reviewer_headers, accessibility_reviewer_headers
):
    """PRD §3.7: "A suspended tool can be **reopened** (`REOPEN_REVIEW`), which
    takes `approval_state` `SUSPENDED` → `UNDER_REVIEW` and resets both verdict
    dimensions to `PENDING` — a `CLEARED` dimension returns to `PENDING`, and so
    does a `CONDITIONAL` one."
    PRD §3.7: "The tool's existing review rows are retained as history but no longer
    decide either dimension, `approved_version` returns to null, and
    `suspension_reason` is left standing as history."
    PRD §3.7: "Re-review therefore requires two fresh review rows, one per
    dimension, and the cycle from `UNDER_REVIEW` through `APPROVED` and `SUSPENDED`
    back to `UNDER_REVIEW` can be walked repeatedly."
    PRD §2.4: "Both `updated_at` and `version` are absent from a `ToolReview`
    response, there is no update operation for one, and a review is never rewritten
    — a re-review round produces new review records rather than editing the old
    ones."
    PRD §2.10: "Finalizing a review requires both `privacy_review_state` and
    `accessibility_review_state` to have left `PENDING`, on
    `POST /tool-integrations/{id}/transitions` with action `FINALIZE_REVIEW` —
    otherwise `ERR_REVIEW_INCOMPLETE`."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension is
    `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."

    Design: Difficulty/non_linear_state_machine/tool_integration_three_way_finalize_fork_and_full_review_cycle_reset
    """
    tool, round_one_privacy, round_one_accessibility = _tool_with_round_one_verdicts(
        api, "CONDITIONS", "CLEAR"
    )
    fx.transition_tool(api, tool["id"], "FINALIZE_REVIEW")
    fx.transition_tool(
        api, tool["id"], "SUSPEND", reason="vendor breach notification"
    )

    reopened = validate_success(
        api.tool_integration_transition(
            tool["id"], {"action": "REOPEN_REVIEW"}, lms_admin_headers
        ),
        200,
    )
    assert reopened["approval_state"] == "UNDER_REVIEW"
    assert reopened["privacy_review_state"] == "PENDING", (
        "a CONDITIONAL dimension returns to PENDING on reopen"
    )
    assert reopened["accessibility_review_state"] == "PENDING", (
        "a CLEARED dimension returns to PENDING on reopen"
    )
    assert reopened["approved_version"] is None
    assert reopened["suspension_reason"] == "vendor breach notification", (
        "suspension_reason is left standing as history"
    )

    round_two_privacy = validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            privacy_reviewer_headers,
        ),
        201,
    )
    assert round_two_privacy["id"] not in {
        round_one_privacy["id"], round_one_accessibility["id"]
    }, "a fresh review round produces a new review record"

    rows, _meta = validate_paginated(
        api.list_tool_reviews(lms_admin_headers, params={"tool_id": tool["id"]})
    )
    assert len(rows) == 3, (
        "the two round-one verdicts are retained as history alongside the new "
        f"round-two privacy verdict, got {len(rows)} rows"
    )
    assert {row["id"] for row in rows} == {
        round_one_privacy["id"], round_one_accessibility["id"],
        round_two_privacy["id"],
    }

    premature = api.tool_integration_transition(
        tool["id"], {"action": "FINALIZE_REVIEW"}, lms_admin_headers
    )
    validate_error(premature, ApiErrorId.ERR_REVIEW_INCOMPLETE.value)

    validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(tool["id"], "ACCESSIBILITY", "CLEAR"),
            accessibility_reviewer_headers,
        ),
        201,
    )
    final = validate_success(
        api.tool_integration_transition(
            tool["id"], {"action": "FINALIZE_REVIEW"}, lms_admin_headers
        ),
        200,
    )
    assert final["approval_state"] == "APPROVED", (
        "with both dimensions CLEARED and the same 13.00 score, the identical "
        f"action now selects the first branch of the fork, got "
        f"{final['approval_state']}"
    )
    assert final["risk_score"] == pytest.approx(13.00, abs=0.005)
    assert final["approved_version"] == "1.0.0"
