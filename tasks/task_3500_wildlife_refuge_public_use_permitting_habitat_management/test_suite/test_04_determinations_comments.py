"""Compatibility determinations and the public comment record: state machine
transitions, clock-driven adjudication, and finalization gating.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_determination, get_determination,
    create_determination_in_public_comment,
    create_determination_in_adjudication,
    setup_determination_with_comment,
    submit_comment, adjudicate_comment,
    create_finalize_payload, create_comment_payload,
    create_adjudicate_payload,
    advance_clock,
)

PO = TEST_USERS["permit_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_finalize_requires_exactly_zero_unresolved_comments(api):
    """PRD §3.2: "Finalization is refused while any comment remains
    unresolved: an `unresolved_comment_count` above zero is rejected with
    `ERR_UNRESOLVED_COMMENTS`."

    Design: Difficulty/boundary_precision_check/finalize_requires_exactly_zero_unresolved_comments
    """
    det = create_determination_in_public_comment(use_type="PHOTOGRAPHY")
    comment = submit_comment(
        det["id"], author_name="Citizen A",
        body="Concerned about nesting disturbance.")
    advance_clock("2026-09-21T00:00:00Z")

    blocked = api_client.finalize_determination(
        det["id"], create_finalize_payload(), PO)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_COMMENTS)

    adjudicated = adjudicate_comment(comment["id"], disposition="NOTED")
    assert adjudicated["status"] == "ADJUDICATED"

    finalized = validate_success(api_client.finalize_determination(
        det["id"], create_finalize_payload(
            finding="COMPATIBLE", rationale="ok"), PO))
    assert finalized["status"] == "FINAL"
    assert finalized["finding"] == "COMPATIBLE"


def test_finalize_from_draft_rejected(api):
    """PRD §3.2: "Finalization moves the determination from `ADJUDICATION` to
    `FINAL` and is the point of decision."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/finalize_from_draft_rejected
    """
    det = create_determination(use_type="RESEARCH", title="Research use")
    assert det["status"] == "DRAFT"
    resp = api_client.finalize_determination(
        det["id"], create_finalize_payload(), PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_determination(det["id"])["status"] == "DRAFT"


def test_open_comment_twice_rejected(api):
    """PRD §3.2: "The action is only valid while the determination is in
    `DRAFT` — any other status is rejected with `ERR_INVALID_STATE` — and
    only while the current clock date falls within the declared window, on or
    after `comment_open_date` and on or before `comment_close_date`; a clock
    date outside the window is rejected with `ERR_WINDOW_IN_PAST` or
    `ERR_INVALID_STATE` according to the validation order of §2.6."

    Design: Corner/state_machines/open_comment_twice_rejected
    """
    det = create_determination_in_public_comment(use_type="RESEARCH")
    assert det["status"] == "PUBLIC_COMMENT"
    resp = api_client.open_determination_comment(det["id"], PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_adjudicate_twice_terminal_lockdown(api):
    """PRD §3.2: "A comment can be adjudicated only while it is `SUBMITTED`
    and only while its parent determination — the one its `determination_id`
    references — stands in `PUBLIC_COMMENT` or `ADJUDICATION`; each
    adjudication moves the comment to `ADJUDICATED` and decrements the
    determination's `unresolved_comment_count` by one."

    Design: Corner/state_machines/adjudicate_twice_terminal_lockdown
    """
    det, comment = setup_determination_with_comment(use_type="PHOTOGRAPHY")
    adjudicate_comment(comment["id"], disposition="NOTED")
    resp = api_client.adjudicate_comment(
        comment["id"], create_adjudicate_payload(disposition="REJECTED"), PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_determination_auto_adjudicates_after_comment_close(api):
    """PRD §3.2: "When the clock advances past `comment_close_date`, the
    determination moves on its own from `PUBLIC_COMMENT` to `ADJUDICATION`,
    closing intake."

    Design: Corner/state_machines/determination_auto_adjudicates_after_comment_close
    """
    det = create_determination_in_public_comment(use_type="RESEARCH")
    advance_clock("2026-09-21T00:00:00Z")
    after = get_determination(det["id"])
    assert after["status"] == "ADJUDICATION", (
        f"clock past comment_close_date must move the determination to "
        f"ADJUDICATION, got {after['status']}")


def test_comment_after_window_close_rejected(api):
    """PRD §3.2: "Submission is a creature of the window: comments attach only
    to a determination in `PUBLIC_COMMENT`, and an attempt against a
    determination in any other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/comment_after_window_close_rejected
    """
    det = create_determination_in_adjudication(use_type="RESEARCH")
    resp = api_client.create_comment(
        det["id"], create_comment_payload(
            author_name="Late Larry", body="too late"), ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
