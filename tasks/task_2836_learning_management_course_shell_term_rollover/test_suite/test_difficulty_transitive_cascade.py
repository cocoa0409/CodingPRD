"""Transitive cascades: one action fanning out across three further entities.

Two chains are exercised here. Suspending a tool blocks its placement, the
blocked placement turns its shell unready and unpublishes it, and the unpublish
lowers the term's published shell count. Dropping an active enrollment frees a
seat, the freed seat promotes the head of the waitlist, and the promotion
renumbers the surviving queue while leaving the term's headcount exactly where
it started.

The server is relaunched before every test, so each test builds its own term,
shells, people, tool and placements from scratch through the public API, and the
logical clock always reads its startup instant unless a test moves it.
"""
from datetime import datetime

import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx

CLOCK_STARTUP = "2026-08-01T00:00:00Z"

TOOL_METADATA = {
    "vendor_name": "OpenCampus", "tool_name": "PeerNotes", "tool_version": "1.0.0",
    "data_sharing_scope": "ROSTER_ONLY", "pii_tier": 0, "vpat_score": 90.00,
    "wcag_level": "AA",
}


def _instant(value):
    """Parse an ISO-8601 UTC instant into a comparable datetime."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _published_shell_with_active_placement(api):
    """An IN_SESSION term carrying a PUBLISHED official shell whose only tool
    placement is ACTIVE, with every intermediate row kept for assertions."""
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    requested = fx.request_shell(
        api, term["id"], owner["id"], sis_section_code="CS401-01", base_seat_cap=20
    )
    shell_at_approve = fx.provisioning_decision(api, requested["id"], "APPROVE")
    tool_at_finalize = fx.approved_tool(api, **TOOL_METADATA)
    placement_at_create = fx.request_placement(
        api, tool_at_finalize["id"], shell_at_approve["id"]
    )
    placement_at_activate = fx.transition_placement(
        api, placement_at_create["id"], "ACTIVATE"
    )
    tool_after_activate = fx.read_tool(api, tool_at_finalize["id"])
    shell_published = fx.publish(api, shell_at_approve["id"])
    term_after_publish = fx.read_term(api, term["id"])
    return {
        "term": term,
        "owner": owner,
        "shell_at_approve": shell_at_approve,
        "tool_at_finalize": tool_at_finalize,
        "placement_at_create": placement_at_create,
        "placement_at_activate": placement_at_activate,
        "tool_after_activate": tool_after_activate,
        "shell_published": shell_published,
        "term_after_publish": term_after_publish,
    }


def test_activating_a_placement_rescores_the_tool_and_lets_the_shell_publish(api):
    """PRD §3.3: "On approval `effective_seat_cap` is set equal to
    `base_seat_cap`, `publish_readiness` is set to true, and `sandbox_expires_at`
    is set to sixty days after the term's `term_end_at` for a `SANDBOX` or `DEV`
    shell while remaining null for an `OFFICIAL` one."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension is
    `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."
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
    PRD §3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the placement
    opens in `placement_state` `REQUESTED` with `pinned_tool_version` null."
    PRD §3.7: "Activation pins `pinned_tool_version` to the tool's
    `approved_version`, raises the tool's `active_placement_count` by one,
    re-scores the tool, and re-derives the shell's `publish_readiness`."
    PRD §3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and
    increments the term's `published_shell_count` by one."

    Design: Difficulty/transitive_cascade/tool_suspension_cascades_four_hops_from_placement_to_term_published_count
    """
    world = _published_shell_with_active_placement(api)

    assert world["shell_at_approve"]["publish_readiness"] is True

    assert world["tool_at_finalize"]["approval_state"] == "APPROVED"
    assert world["tool_at_finalize"]["approved_version"] == "1.0.0"
    assert world["tool_at_finalize"]["risk_score"] == pytest.approx(13.00, abs=0.005), (
        "0 for pii_tier 0, 10 for ROSTER_ONLY, 3.00 for a vpat_score of 90.00, 0 "
        "for AA and 0 for no active placement, got "
        f"{world['tool_at_finalize']['risk_score']}"
    )

    assert world["placement_at_create"]["placement_state"] == "REQUESTED"
    assert world["placement_at_create"]["pinned_tool_version"] is None
    assert world["placement_at_activate"]["placement_state"] == "ACTIVE"
    assert world["placement_at_activate"]["pinned_tool_version"] == "1.0.0"

    assert world["tool_after_activate"]["active_placement_count"] == 1
    assert world["tool_after_activate"]["risk_score"] == pytest.approx(16.00, abs=0.005), (
        "one active placement adds 3 exposure points to the earlier 13.00, got "
        f"{world['tool_after_activate']['risk_score']}"
    )

    assert world["shell_published"]["provisioning_state"] == "PUBLISHED"
    assert world["term_after_publish"]["published_shell_count"] == 1


def test_suspending_the_tool_cascades_four_hops_to_the_terms_published_count(
    api, lms_admin_headers
):
    """PRD §3.7: "An approved or conditional tool can be **suspended** (`SUSPEND`),
    which records `suspension_reason` from the request `reason` (defaulting to
    "privacy incident") and runs the service's deepest cascade in four hops."
    PRD §3.7: "Every placement of the tool whose `placement_state` is `REQUESTED`
    or `ACTIVE` moves to `BLOCKED` in `created_at` ascending order; each of those
    blockings raises its shell's `blocked_placement_count` by one and sets that
    shell's `publish_readiness` to false; each shell whose `publish_readiness` just
    became false and whose `provisioning_state` is `PUBLISHED` is unpublished back
    to `PROVISIONED` with `unpublish_reason` "tool placement blocked"; and each of
    those unpublishings lowers the term's `published_shell_count` by one."
    PRD §3.7: "The tool's `active_placement_count` is set to 0 and its `risk_score`
    is recomputed."
    PRD §3.7: "A placement may also be driven into `BLOCKED` from either
    `REQUESTED` or `ACTIVE` by a tool rejection or suspension; each such blocking
    records `blocked_reason`, raises the shell's `blocked_placement_count` and sets
    its `publish_readiness` to false, and blocking an already-active placement
    additionally lowers the tool's `active_placement_count` by one."
    PRD §3.3: "When the server drives it as a safety response to a tool placement
    becoming `BLOCKED`, `unpublish_reason` is recorded as `tool placement blocked`
    and the posture gate is deliberately bypassed — pulling a shell offline because
    a tool was blocked is a protective act, not an authoring action."
    PRD §3.7: "The exposure points are the `active_placement_count` multiplied by
    3, capped at 15."

    Design: Difficulty/transitive_cascade/tool_suspension_cascades_four_hops_from_placement_to_term_published_count
    """
    world = _published_shell_with_active_placement(api)
    assert world["term_after_publish"]["published_shell_count"] == 1

    suspended = validate_success(
        api.tool_integration_transition(
            world["tool_at_finalize"]["id"],
            {"action": "SUSPEND", "reason": "vendor privacy incident"},
            lms_admin_headers,
        ),
        200,
    )
    assert suspended["approval_state"] == "SUSPENDED"

    placement_after = fx.read_placement(api, world["placement_at_create"]["id"])
    assert placement_after["placement_state"] == "BLOCKED", (
        "hop one: the tool's ACTIVE placement is driven to BLOCKED"
    )
    assert placement_after["blocked_reason"] is not None, (
        "each blocking records a blocked_reason"
    )

    shell_after = fx.read_shell(api, world["shell_at_approve"]["id"])
    assert shell_after["blocked_placement_count"] == 1, (
        "hop two follows from the blocked placement, not from the suspension "
        "directly"
    )
    assert shell_after["publish_readiness"] is False
    assert shell_after["provisioning_state"] == "PROVISIONED", (
        "hop three: the shell whose publish_readiness just became false is "
        f"unpublished, got {shell_after['provisioning_state']}"
    )
    assert shell_after["unpublish_reason"] == "tool placement blocked"

    term_after = fx.read_term(api, world["term"]["id"])
    assert term_after["published_shell_count"] == 0, (
        "hop four: the unpublish lowers the term's published_shell_count from 1 "
        f"to 0, got {term_after['published_shell_count']}"
    )

    assert suspended["active_placement_count"] == 0
    assert suspended["risk_score"] == pytest.approx(13.00, abs=0.005), (
        "the exposure points leave with the placement, so the recomputed score "
        f"returns to 13.00, got {suspended['risk_score']}"
    )


def test_the_unpublished_shell_cannot_republish_until_the_blocked_placement_goes(
    api, lms_admin_headers
):
    """PRD §2.10: "Publishing requires `publish_readiness` to be true, on
    `POST /course-shells/{id}/publish` — otherwise `ERR_SHELL_NOT_PUBLISH_READY`."
    PRD §3.7: "**Removal** (`REMOVE`) reaches the terminal `REMOVED` from all three
    earlier states, and can also arrive as the shell-archival cascade of §3.3, but
    its bookkeeping differs by origin state: removing an `ACTIVE` placement lowers
    the tool's `active_placement_count` by one, re-scores the tool and re-derives
    the shell's `publish_readiness`; removing a `BLOCKED` placement lowers the
    shell's `blocked_placement_count` by one and re-derives its `publish_readiness`;
    removing a `REQUESTED` placement only re-derives `publish_readiness`."
    PRD §3.7: "A shell is publish-ready exactly when its `blocked_placement_count`
    is 0."
    PRD §3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and
    increments the term's `published_shell_count` by one."

    Design: Difficulty/transitive_cascade/tool_suspension_cascades_four_hops_from_placement_to_term_published_count
    """
    world = _published_shell_with_active_placement(api)
    fx.transition_tool(
        api, world["tool_at_finalize"]["id"], "SUSPEND", reason="vendor privacy incident"
    )
    shell_id = world["shell_at_approve"]["id"]

    refused = api.publish_shell(shell_id, lms_admin_headers)
    validate_error(refused, ApiErrorId.ERR_SHELL_NOT_PUBLISH_READY.value)

    still_down = fx.read_shell(api, shell_id)
    assert still_down["provisioning_state"] == "PROVISIONED", (
        "the refused publish leaves the shell where the cascade put it"
    )

    removed = fx.transition_placement(api, world["placement_at_create"]["id"], "REMOVE")
    assert removed["placement_state"] == "REMOVED"

    ready_again = fx.read_shell(api, shell_id)
    assert ready_again["blocked_placement_count"] == 0, (
        "removing the BLOCKED placement lowers the shell's blocked_placement_count"
    )
    assert ready_again["publish_readiness"] is True, (
        "a shell is publish-ready exactly when its blocked_placement_count is 0"
    )

    republished = validate_success(api.publish_shell(shell_id, lms_admin_headers), 200)
    assert republished["provisioning_state"] == "PUBLISHED"
    term_after = fx.read_term(api, world["term"]["id"])
    assert term_after["published_shell_count"] == 1, (
        "the term's published_shell_count climbs back to 1 with the republish, got "
        f"{term_after['published_shell_count']}"
    )


def _shell_with_two_seats_taken_and_two_queued(api):
    """A base_seat_cap 2 shell in a NORMAL IN_SESSION term holding two ACTIVE
    students and two queued ones, returning every row for assertions."""
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    requested = fx.request_shell(
        api, term["id"], owner["id"], sis_section_code="CS150-01", base_seat_cap=2
    )
    shell_at_approve = fx.provisioning_decision(api, requested["id"], "APPROVE")
    students = fx.create_students(api, 4)
    seated = [
        fx.enrol(api, shell_at_approve["id"], person["id"], "ACTIVE")
        for person in students[:2]
    ]
    queued = [
        fx.enrol(api, shell_at_approve["id"], person["id"], "WAITLISTED")
        for person in students[2:]
    ]
    return {
        "term": term,
        "shell_at_approve": shell_at_approve,
        "students": students,
        "first_seat": seated[0],
        "second_seat": seated[1],
        "queue_head": queued[0],
        "queue_tail": queued[1],
        "shell_before": fx.read_shell(api, shell_at_approve["id"]),
        "term_before": fx.read_term(api, term["id"]),
    }


def test_queue_positions_and_seat_observables_before_any_drop(api):
    """PRD §3.3: "On approval `effective_seat_cap` is set equal to
    `base_seat_cap`, `publish_readiness` is set to true, and `sandbox_expires_at`
    is set to sixty days after the term's `term_end_at` for a `SANDBOX` or `DEV`
    shell while remaining null for an `OFFICIAL` one."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is
    `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD §3.4: "A waitlisted row's `waitlist_position` is set to one more than the
    shell's current `waitlisted_enrollment_count`, and that count then rises by one;
    a waitlisted row consumes no seat and moves neither the shell's active count nor
    the term's total."
    PRD §3.4: "Step one derives the overflow ratio from the *term's*
    `continuity_posture` and from nothing else: 0.00 under `NORMAL`, 0.10 under
    `ELEVATED`, and 0.20 under `CONTINUITY_MODE`."
    PRD §3.4: "The overflow allowance is the shell's `base_seat_cap` multiplied by
    that ratio and rounded **down** to a whole seat."
    PRD §3.4: "Only in step five are the observables recomputed:
    `seat_utilization_pct` becomes `active_enrollment_count` divided by
    `base_seat_cap`, multiplied by 100, rounded half up to two decimal places, and
    `overflow_flag` becomes true exactly when `active_enrollment_count` is greater
    than `base_seat_cap`."

    Design: Difficulty/transitive_cascade/enrollment_drop_cascades_waitlist_promotion_renumbering_and_term_headcount
    """
    world = _shell_with_two_seats_taken_and_two_queued(api)

    assert world["shell_at_approve"]["effective_seat_cap"] == 2, (
        "a NORMAL term gives a 0.00 overflow ratio, so the frozen cap equals the "
        f"base_seat_cap of 2, got {world['shell_at_approve']['effective_seat_cap']}"
    )
    assert world["queue_head"]["waitlist_position"] == 1
    assert world["queue_tail"]["waitlist_position"] == 2, (
        "positions come from waitlisted_enrollment_count + 1 rather than from row "
        f"order, got {world['queue_tail']['waitlist_position']}"
    )

    assert world["shell_before"]["active_enrollment_count"] == 2
    assert world["shell_before"]["waitlisted_enrollment_count"] == 2
    assert world["shell_before"]["seat_utilization_pct"] == pytest.approx(
        100.00, abs=0.005
    ), "2 active over a base_seat_cap of 2 reads 100.00"
    assert world["term_before"]["total_active_enrollments"] == 2, (
        "the two queued rows consume no seat and never reach the term's headcount"
    )


def test_dropping_one_seat_promotes_the_queue_head_and_nets_the_term_to_zero(
    api, registrar_headers
):
    """PRD §3.4: "It stamps `dropped_at` from the logical clock and then cascades in
    four hops: the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each fall by one; the freed seat re-runs the capacity
    rule, and while it reports at least one promotable slot the head of the shell's
    waitlist — chosen by `waitlist_position` ascending with `created_at` ascending as
    the tie-break — moves `WAITLISTED` → `ACTIVE`; each such promotion re-derives the
    shell's `effective_seat_cap`, `seat_utilization_pct` and `overflow_flag`; and any
    change in `overflow_flag` bubbles up to the term's `overflow_shell_count`."
    PRD §3.4: "A drop whose freed seat is immediately consumed by a promotion
    therefore nets to zero at the term level: minus one for the drop, plus one for
    the promotion."
    PRD §3.4: "The promoted row's `waitlist_position` becomes null and the shell's
    remaining queued rows are renumbered from 1 in `waitlist_position` ascending
    order with `created_at` ascending as the tie-break; the shell's
    `waitlisted_enrollment_count` falls by one, its `active_enrollment_count` rises
    by one, its `effective_seat_cap`, `seat_utilization_pct` and `overflow_flag` are
    re-derived, and the term's `total_active_enrollments` rises by one."
    PRD §3.4: "Only in step five are the observables recomputed:
    `seat_utilization_pct` becomes `active_enrollment_count` divided by
    `base_seat_cap`, multiplied by 100, rounded half up to two decimal places, and
    `overflow_flag` becomes true exactly when `active_enrollment_count` is greater
    than `base_seat_cap`."
    PRD §2.5: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to real time."
    PRD §2.5: "Timestamps the server stamps itself — `dropped_at`, `resolved_at`,
    `closed_at` — are taken from the logical clock at the moment of the transition."

    Design: Difficulty/transitive_cascade/enrollment_drop_cascades_waitlist_promotion_renumbering_and_term_headcount
    """
    world = _shell_with_two_seats_taken_and_two_queued(api)

    dropped = validate_success(
        api.enrollment_transition(
            world["first_seat"]["id"],
            {"action": "DROP", "reason": "student withdrew from the course"},
            registrar_headers,
        ),
        200,
    )
    assert dropped["enrollment_state"] == "DROPPED"
    assert _instant(dropped["dropped_at"]) == _instant(CLOCK_STARTUP), (
        "dropped_at comes from the logical clock, which still reads its startup "
        f"instant {CLOCK_STARTUP}, got {dropped['dropped_at']}"
    )

    head = fx.read_enrollment(api, world["queue_head"]["id"])
    assert head["enrollment_state"] == "ACTIVE", (
        "the freed seat promotes the head of the queue, never the row behind it"
    )
    assert head["waitlist_position"] is None

    tail = fx.read_enrollment(api, world["queue_tail"]["id"])
    assert tail["enrollment_state"] == "WAITLISTED"
    assert tail["waitlist_position"] == 1, (
        "the surviving queue is renumbered from 1, so the row that stood second "
        f"now stands first, got {tail['waitlist_position']}"
    )

    shell_after = fx.read_shell(api, world["shell_at_approve"]["id"])
    assert shell_after["active_enrollment_count"] == 2
    assert shell_after["waitlisted_enrollment_count"] == 1
    assert shell_after["seat_utilization_pct"] == pytest.approx(100.00, abs=0.005), (
        "2 active over a base_seat_cap of 2 still reads 100.00"
    )
    assert shell_after["overflow_flag"] is False

    term_after = fx.read_term(api, world["term"]["id"])
    assert term_after["total_active_enrollments"] == 2, (
        "minus one for the drop and plus one for the promotion nets to zero at the "
        f"term level, got {term_after['total_active_enrollments']}"
    )
    assert term_after["overflow_shell_count"] == 0

    untouched = fx.read_enrollment(api, world["second_seat"]["id"])
    assert untouched["enrollment_state"] == "ACTIVE", (
        "the other seated row is not touched by the cascade"
    )
    assert untouched["waitlist_position"] is None


def test_exactly_one_row_is_promoted_and_the_next_one_stays_queued(
    api, registrar_headers
):
    """PRD §3.4: "Step three derives the open seats as `effective_seat_cap` minus
    `active_enrollment_count`, treated as zero if that difference would be negative,
    and derives the promotable head count as the smaller of the open seats and the
    shell's `waitlisted_enrollment_count`."
    PRD §3.4: "Step four promotes exactly that many queued rows, taken in
    `waitlist_position` ascending order with `created_at` ascending as the
    tie-break, and renumbers the surviving queue from 1 upward."
    PRD §3.4: "**Promotion** takes `WAITLISTED` → `ACTIVE`; it requires the capacity
    rule to report at least one promotable slot (otherwise `ERR_SEAT_CAP_EXCEEDED`)
    and the shell to be `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."

    Design: Difficulty/transitive_cascade/enrollment_drop_cascades_waitlist_promotion_renumbering_and_term_headcount
    """
    world = _shell_with_two_seats_taken_and_two_queued(api)
    fx.transition_enrollment(
        api, world["first_seat"]["id"], "DROP",
        reason="student withdrew from the course",
    )

    shell_after = fx.read_shell(api, world["shell_at_approve"]["id"])
    assert shell_after["active_enrollment_count"] == 2, (
        "one freed seat and two queued rows give min(1, 2) = 1 promotion, so the "
        f"shell is full again rather than over cap, got "
        f"{shell_after['active_enrollment_count']}"
    )
    assert shell_after["effective_seat_cap"] == 2
    assert shell_after["waitlisted_enrollment_count"] == 1

    tail = fx.read_enrollment(api, world["queue_tail"]["id"])
    assert tail["enrollment_state"] == "WAITLISTED", (
        "the second queued row was not promoted by the single freed seat"
    )

    refused = api.enrollment_transition(
        world["queue_tail"]["id"], {"action": "PROMOTE"}, registrar_headers
    )
    validate_error(refused, ApiErrorId.ERR_SEAT_CAP_EXCEEDED.value)

    still_queued = fx.read_enrollment(api, world["queue_tail"]["id"])
    assert still_queued["enrollment_state"] == "WAITLISTED"
    assert still_queued["waitlist_position"] == 1, (
        "the refused promotion leaves the renumbered queue untouched"
    )
