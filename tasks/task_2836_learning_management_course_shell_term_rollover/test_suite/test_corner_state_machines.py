"""State-machine PRD compliance: declared initial states, the full transition
sets, terminal-state lockdown, cross-dimension guards and the closing cascades.

The runner relaunches the API server before every test, so each test builds all
of its own preconditions and the logical clock always starts at
2026-08-01T00:00:00Z.
"""
from datetime import datetime, timezone

from test_helpers import (
    CLOCK_STARTUP_INSTANT,
    factories as fac,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import LMS_ADMIN_ALT_USER_ID, LMS_ADMIN_USER_ID


def parse_instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def test_newly_created_rows_start_in_their_declared_initial_state(
    api, registrar_headers, lms_admin_headers
):
    """PRD §3.3: "The new shell opens in `provisioning_state` `REQUESTED`, its
    `effective_seat_cap` seeded from the term's current `continuity_posture` by the
    capacity rule of §3.4, its `sandbox_expires_at` set to sixty days after the
    term's `term_end_at` when the class is `SANDBOX` or `DEV` and left null for
    `OFFICIAL`, and the term's `rollover_completion_pct` recomputed to account for
    the new eligible shell."
    PRD §3.7: "A new tool opens with `approval_state` `DRAFT`,
    `privacy_review_state` `PENDING`, `accessibility_review_state` `PENDING`,
    `risk_score` null, `approved_version` null, `active_placement_count` 0 and
    `suspension_reason` null."
    PRD §3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the placement
    opens in `placement_state` `REQUESTED` with `pinned_tool_version` null."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is
    `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)

    shell = validate_success(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], owner["id"]), lms_admin_headers
        ),
        201,
    )
    assert shell["provisioning_state"] == "REQUESTED"
    assert shell["version"] == 1

    tool = validate_success(
        api.create_tool_integration(
            fac.create_tool_integration_payload(), lms_admin_headers
        ),
        201,
    )
    assert tool["approval_state"] == "DRAFT"
    assert tool["privacy_review_state"] == "PENDING"
    assert tool["accessibility_review_state"] == "PENDING"
    assert tool["risk_score"] is None, "a tool is not scored until its review closes"
    assert tool["approved_version"] is None
    assert tool["active_placement_count"] == 0
    assert tool["suspension_reason"] is None
    assert tool["version"] == 1

    fx.provisioning_decision(api, shell["id"], "APPROVE")

    placement = validate_success(
        api.create_tool_placement(
            fac.create_tool_placement_payload(tool["id"], shell["id"]),
            lms_admin_headers,
        ),
        201,
    )
    assert placement["placement_state"] == "REQUESTED"
    assert placement["pinned_tool_version"] is None
    assert placement["version"] == 1

    student = fx.create_student(api)
    enrollment = validate_success(
        api.create_enrollment(
            fac.create_enrollment_payload(shell["id"], student["id"]), registrar_headers
        ),
        201,
    )
    assert enrollment["enrollment_state"] == "ACTIVE"
    assert enrollment["version"] == 1


def test_enrollment_walks_its_full_transition_set_including_drop_and_reinstate(api):
    """PRD §3.4: "**Promotion** takes `WAITLISTED` → `ACTIVE`; it requires the
    capacity rule to report at least one promotable slot (otherwise
    `ERR_SEAT_CAP_EXCEEDED`) and the shell to be `PROVISIONED` or `PUBLISHED`
    (otherwise `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."
    PRD §3.4: "The promoted row's `waitlist_position` becomes null and the shell's
    remaining queued rows are renumbered from 1 in `waitlist_position` ascending
    order with `created_at` ascending as the tie-break; the shell's
    `waitlisted_enrollment_count` falls by one, its `active_enrollment_count` rises
    by one, its `effective_seat_cap`, `seat_utilization_pct` and `overflow_flag` are
    re-derived, and the term's `total_active_enrollments` rises by one."
    PRD §3.4: "**Dropping** takes `ACTIVE` → `DROPPED` and needs only that the shell
    be `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."
    PRD §3.4: "It increments `reinstatement_count` by one, sets `dropped_at` back to
    null, and for a `STUDENT` row raises the shell's `active_enrollment_count` and
    the term's `total_active_enrollments` by one each while re-deriving
    `seat_utilization_pct` and `overflow_flag`."
    PRD §3.4: "**Completion** takes `ACTIVE` → `COMPLETED`, the terminal state, and
    requires the shell to be `PUBLISHED` or `CONCLUDED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`); it lowers the shell's
    `active_enrollment_count` and the term's `total_active_enrollments` by one each
    and re-derives the shell's `seat_utilization_pct` and `overflow_flag`."
    PRD §2.5: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to real time."
    PRD §2.5: "Timestamps the server stamps itself — `dropped_at`,
    `resolved_at`, `closed_at` — are taken from the logical clock at the moment of
    the transition."

    Design: Corner/state_machines/enrollment_walks_its_full_declared_transition_set_including_the_drop_reinstate_cycle
    """
    setup = fx.published_shell_setup(
        api, "IN_SESSION", shell_overrides={"base_seat_cap": 2}
    )
    shell_id = setup["shell"]["id"]
    first_student = fx.create_student(api)
    second_student = fx.create_student(api)

    live = fx.enrol(api, shell_id, first_student["id"])
    assert live["enrollment_state"] == "ACTIVE"

    queued = fx.enrol(api, shell_id, second_student["id"], requested_state="WAITLISTED")
    assert queued["enrollment_state"] == "WAITLISTED"
    assert queued["waitlist_position"] == 1

    promoted = fx.transition_enrollment(api, queued["id"], "PROMOTE")
    assert promoted["enrollment_state"] == "ACTIVE"
    assert promoted["waitlist_position"] is None
    after_promote = fx.read_shell(api, shell_id)
    assert after_promote["active_enrollment_count"] == 2
    assert after_promote["waitlisted_enrollment_count"] == 0
    assert after_promote["seat_utilization_pct"] == 100.00
    assert after_promote["overflow_flag"] is False

    dropped = fx.transition_enrollment(api, live["id"], "DROP", reason="withdrew")
    assert dropped["enrollment_state"] == "DROPPED"
    assert parse_instant(dropped["dropped_at"]) == parse_instant(CLOCK_STARTUP_INSTANT), (
        "dropped_at is stamped from the logical clock"
    )
    after_drop = fx.read_shell(api, shell_id)
    assert after_drop["active_enrollment_count"] == 1
    assert after_drop["seat_utilization_pct"] == 50.00

    reinstated = fx.transition_enrollment(api, live["id"], "REINSTATE")
    assert reinstated["enrollment_state"] == "ACTIVE"
    assert reinstated["reinstatement_count"] == 1
    assert reinstated["dropped_at"] is None
    after_reinstate = fx.read_shell(api, shell_id)
    assert after_reinstate["active_enrollment_count"] == 2
    assert after_reinstate["seat_utilization_pct"] == 100.00

    completed = fx.transition_enrollment(api, live["id"], "COMPLETE")
    assert completed["enrollment_state"] == "COMPLETED"
    final_shell = fx.read_shell(api, shell_id)
    assert final_shell["active_enrollment_count"] == 1
    assert final_shell["seat_utilization_pct"] == 50.00
    final_term = fx.read_term(api, setup["term"]["id"])
    assert final_term["total_active_enrollments"] == 1


def test_merge_request_rejects_every_trigger_not_declared_from_its_current_state(
    api, lms_admin_headers, lms_admin_alt_headers
):
    """PRD §3.5: "The request opens in `merge_state` `DRAFT` with
    `submitted_by_user_id` recorded from the acting user, `decided_by_user_id` null,
    both relocation tallies at zero, and both seat-ledger readings null."
    PRD §3.5: "The lifecycle runs `DRAFT` → `SUBMITTED` → `APPROVED` → `APPLIED` →
    `REVERSED`, with a divergent decision branch to the terminal `DECLINED`."
    PRD §2.10 band 11: "The target record's own state field permits the requested
    transition or mutation, including the `action` enum on every transition
    endpoint, terminal-state lockdown, and re-issuing a transition that has already
    been taken."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."

    Design: Corner/state_machines/merge_request_rejects_every_trigger_that_is_not_declared_from_its_current_state
    """
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    parent = fx.provision_shell(api, term["id"], owner["id"])
    child = fx.provision_shell(api, term["id"], owner["id"])

    merge = fx.open_merge_request(
        api, fx.read_shell(api, parent["id"]), child["id"], headers=lms_admin_headers
    )
    assert merge["merge_state"] == "DRAFT"
    assert merge["version"] == 1

    validate_error(
        api.merge_request_transition(merge["id"], {"action": "APPLY"}, lms_admin_headers),
        "ERR_INVALID_STATE_TRANSITION",
    )
    unchanged = fx.read_merge_request(api, merge["id"])
    assert unchanged["merge_state"] == "DRAFT"
    assert unchanged["version"] == 1, "a refused transition mutates nothing"

    submitted = fx.transition_merge_request(
        api, merge["id"], "SUBMIT", headers=lms_admin_headers
    )
    assert submitted["merge_state"] == "SUBMITTED"

    validate_error(
        api.merge_request_transition(
            merge["id"], {"action": "APPLY"}, lms_admin_alt_headers
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    approved = fx.transition_merge_request(
        api, merge["id"], "APPROVE", headers=lms_admin_alt_headers
    )
    assert approved["merge_state"] == "APPROVED"

    validate_error(
        api.merge_request_transition(
            merge["id"], {"action": "REVERSE"}, lms_admin_alt_headers
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    applied = fx.transition_merge_request(
        api, merge["id"], "APPLY", headers=lms_admin_alt_headers
    )
    assert applied["merge_state"] == "APPLIED"
    assert applied["moved_enrollment_count"] == 0, "the child holds no active rows"

    absorbed_child = fx.read_shell(api, child["id"])
    assert absorbed_child["provisioning_state"] == "MERGED"
    assert absorbed_child["merged_into_shell_id"] == parent["id"]


def test_a_declined_merge_request_is_terminal_and_refuses_further_transitions(
    api, lms_admin_headers, lms_admin_alt_headers
):
    """PRD §3.5: "**Declining** (`DECLINE`) shares the same segregation-of-duties
    gate and also records `decided_by_user_id`, but it is terminal and touches no
    shell and no enrollment at all: the two branches of the decision fork differ
    only in the action word, and one arms a relocation while the other leaves the
    world exactly as it found it."
    PRD §3.5: "`REVERSED` and `DECLINED` are the two terminal states."
    PRD §2.10 band 11: "The target record's own state field permits the requested
    transition or mutation, including the `action` enum on every transition
    endpoint, terminal-state lockdown, and re-issuing a transition that has already
    been taken."
    PRD §2.1: "The server records it where a transition says so — as
    `submitted_by_user_id` and `decided_by_user_id` on a `MergeRequest`, and as
    `reviewer_user_id` on a `ToolReview` — and compares it to other recorded
    operator identifiers for segregation-of-duties purposes, but never compares it
    to any entity's `id`."

    Design: Corner/state_machines/a_declined_merge_request_is_terminal_and_refuses_every_further_transition
    """
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    parent = fx.provision_shell(api, term["id"], owner["id"])
    child = fx.provision_shell(api, term["id"], owner["id"])

    merge = fx.open_merge_request(
        api, fx.read_shell(api, parent["id"]), child["id"], headers=lms_admin_headers
    )
    assert merge["submitted_by_user_id"] == LMS_ADMIN_USER_ID
    assert merge["decided_by_user_id"] is None
    fx.transition_merge_request(api, merge["id"], "SUBMIT", headers=lms_admin_headers)

    declined = fx.transition_merge_request(
        api, merge["id"], "DECLINE", headers=lms_admin_alt_headers
    )
    assert declined["merge_state"] == "DECLINED"
    assert declined["decided_by_user_id"] == LMS_ADMIN_ALT_USER_ID

    for action in ("APPROVE", "APPLY", "REVERSE"):
        validate_error(
            api.merge_request_transition(
                merge["id"], {"action": action}, lms_admin_alt_headers
            ),
            "ERR_INVALID_STATE_TRANSITION",
        )

    still_declined = fx.read_merge_request(api, merge["id"])
    assert still_declined["merge_state"] == "DECLINED"
    assert still_declined["moved_enrollment_count"] == 0

    untouched_child = fx.read_shell(api, child["id"])
    assert untouched_child["provisioning_state"] == "PROVISIONED", (
        "a declined request touches no shell"
    )
    assert untouched_child["merged_into_shell_id"] is None
    untouched_parent = fx.read_shell(api, parent["id"])
    assert untouched_parent["absorbed_child_count"] == 0


def test_repeating_a_completed_transition_is_rejected_rather_than_ignored(
    api, lms_admin_headers, registrar_headers
):
    """PRD §2.10 band 11: "The target record's own state field permits the requested
    transition or mutation, including the `action` enum on every transition
    endpoint, terminal-state lockdown, and re-issuing a transition that has already
    been taken."
    PRD §3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and increments
    the term's `published_shell_count` by one."
    PRD §3.4: "A `Registrar` stages one against a term through `term_id`, supplying
    `operations` — an ordered array of between 1 and 200 objects, each carrying an
    `op` of either `ADD` or `DROP` together with a `shell_id`, a `person_id` and a
    `role` — and optionally a `batch_seq`, which defaults to the term's
    `sis_sync_epoch` plus one."
    PRD §3.4: "A staged batch opens in `batch_state` `DRAFT` with every tally at
    zero."
    PRD §3.4: "Validating a batch (`VALIDATE`) takes `DRAFT` → `VALIDATED` and
    requires the term's `lifecycle_state` to be `REGISTRATION_OPEN` or `IN_SESSION`,
    otherwise `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.4: "Both `APPLIED` and `FAILED` are terminal."

    Design: Corner/state_machines/repeating_a_completed_transition_is_rejected_rather_than_silently_ignored
    """
    setup = fx.provisioned_shell_setup(api, "IN_SESSION")
    shell_id = setup["shell"]["id"]
    term_id = setup["term"]["id"]
    student = fx.create_student(api)

    batch = fx.stage_sync_batch(
        api, term_id, [fac.sync_operation("ADD", shell_id, student["id"])]
    )
    assert batch["batch_state"] == "DRAFT"
    assert batch["batch_seq"] == 1, "batch_seq defaults to sis_sync_epoch plus one"
    assert batch["validated_operation_count"] == 0
    assert batch["applied_add_count"] == 0

    published = fx.publish(api, shell_id)
    assert published["provisioning_state"] == "PUBLISHED"
    assert fx.read_term(api, term_id)["published_shell_count"] == 1

    validate_error(
        api.publish_shell(shell_id, lms_admin_headers),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assert fx.read_term(api, term_id)["published_shell_count"] == 1, (
        "the refused repeat leaves the term's counter alone"
    )

    validated = fx.transition_sync_batch(api, batch["id"], "VALIDATE")
    assert validated["batch_state"] == "VALIDATED"
    assert validated["validated_operation_count"] == 1
    assert validated["rejected_operation_count"] == 0

    validate_error(
        api.sync_batch_transition(batch["id"], {"action": "VALIDATE"}, registrar_headers),
        "ERR_INVALID_STATE_TRANSITION",
    )

    applied = fx.transition_sync_batch(api, batch["id"], "APPLY")
    assert applied["batch_state"] == "APPLIED"
    assert applied["applied_add_count"] == 1

    validate_error(
        api.sync_batch_transition(batch["id"], {"action": "APPLY"}, registrar_headers),
        "ERR_INVALID_STATE_TRANSITION",
    )

    term = fx.read_term(api, term_id)
    assert term["sis_sync_epoch"] == 1, "the epoch advanced exactly once"
    assert term["total_active_enrollments"] == 1


def test_archiving_a_shell_enforces_its_terms_lifecycle_precondition_first(
    api, registrar_headers
):
    """PRD §3.3: "`CONCLUDED` → `ARCHIVED` requires the shell's term to have reached
    `CLOSED` or `ARCHIVED` (`ERR_INVALID_STATE_TRANSITION`)."
    PRD §3.3: "Afterwards the shell's `blocked_placement_count` reads 0 and its
    `publish_readiness` reads true."
    PRD §3.3: "`PROVISIONED` → `CONCLUDED` and `PUBLISHED` → `CONCLUDED` both
    require the shell's `merged_into_shell_id` to be null
    (`ERR_SHELL_ALREADY_MERGED`), and both move every enrollment of the shell whose
    `enrollment_state` is `ACTIVE` to `COMPLETED` in `created_at` ascending order,
    zero the shell's `active_enrollment_count`, set its `seat_utilization_pct` to
    0.00 and its `overflow_flag` to false, and decrement the term's
    `total_active_enrollments` by the number of rows completed."

    Design: Corner/state_machines/archiving_a_shell_enforces_its_terms_lifecycle_precondition_first
    """
    setup = fx.published_shell_setup(api, "IN_SESSION")
    shell_id = setup["shell"]["id"]
    term_id = setup["term"]["id"]

    concluded = fx.transition_shell(api, shell_id, "CONCLUDED")
    assert concluded["provisioning_state"] == "CONCLUDED"

    validate_error(
        api.shell_lifecycle_transition(
            shell_id, {"target_state": "ARCHIVED"}, registrar_headers
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    fx.transition_term(api, term_id, "FINALS")
    fx.transition_term(api, term_id, "GRADING")
    validate_error(
        api.shell_lifecycle_transition(
            shell_id, {"target_state": "ARCHIVED"}, registrar_headers
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assert fx.read_shell(api, shell_id)["provisioning_state"] == "CONCLUDED"

    closed_term = fx.transition_term(api, term_id, "CLOSED")
    assert closed_term["lifecycle_state"] == "CLOSED"

    archived = fx.transition_shell(api, shell_id, "ARCHIVED")
    assert archived["provisioning_state"] == "ARCHIVED"
    assert archived["blocked_placement_count"] == 0
    assert archived["publish_readiness"] is True


def test_concluding_a_published_shell_completes_its_rows_and_updates_both_parents(
    api, registrar_headers
):
    """PRD §3.3: "`PROVISIONED` → `CONCLUDED` and `PUBLISHED` → `CONCLUDED` both
    require the shell's `merged_into_shell_id` to be null
    (`ERR_SHELL_ALREADY_MERGED`), and both move every enrollment of the shell whose
    `enrollment_state` is `ACTIVE` to `COMPLETED` in `created_at` ascending order,
    zero the shell's `active_enrollment_count`, set its `seat_utilization_pct` to
    0.00 and its `overflow_flag` to false, and decrement the term's
    `total_active_enrollments` by the number of rows completed."
    PRD §3.3: "The only difference between the two is that concluding a shell that
    was `PUBLISHED` additionally decrements the term's `published_shell_count` by
    one, while concluding a `PROVISIONED` shell does not, because it was never
    counted there."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered
    by `created_at` ascending."

    Design: Corner/state_machines/concluding_a_published_shell_completes_its_active_rows_and_updates_both_parents
    """
    setup = fx.published_shell_setup(
        api, "IN_SESSION", shell_overrides={"base_seat_cap": 3}
    )
    shell_id = setup["shell"]["id"]
    term_id = setup["term"]["id"]
    pairs = fx.enrol_new_students(api, shell_id, 3)

    before_shell = fx.read_shell(api, shell_id)
    assert before_shell["active_enrollment_count"] == 3
    assert before_shell["seat_utilization_pct"] == 100.00
    before_term = fx.read_term(api, term_id)
    assert before_term["published_shell_count"] == 1
    assert before_term["total_active_enrollments"] == 3

    concluded = fx.transition_shell(api, shell_id, "CONCLUDED")
    assert concluded["provisioning_state"] == "CONCLUDED"
    assert concluded["active_enrollment_count"] == 0
    assert concluded["seat_utilization_pct"] == 0.00
    assert concluded["overflow_flag"] is False

    after_term = fx.read_term(api, term_id)
    assert after_term["published_shell_count"] == 0, (
        "concluding a PUBLISHED shell releases its slot in the term's counter"
    )
    assert after_term["total_active_enrollments"] == 0

    rows, meta = validate_paginated(
        api.list_enrollments(
            registrar_headers,
            {"shell_id": shell_id, "enrollment_state": "COMPLETED"},
        )
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [pair[1]["id"] for pair in pairs], (
        "the completions run in created_at ascending order"
    )
    for row in rows:
        assert row["enrollment_state"] == "COMPLETED"


def test_term_lifecycle_and_continuity_posture_advance_as_independent_dimensions(
    api, lms_admin_headers
):
    """PRD §3.9: "The term's `continuity_posture` is the second, independent
    dimension of the term row, and an `LmsAdmin` moves it by naming a
    `target_posture` and an optional `reason`."
    PRD §3.9: "It escalates `NORMAL` → `ELEVATED`, which requires the term's
    `lifecycle_state` to be `IN_SESSION`, `FINALS` or `GRADING` (otherwise
    `ERR_INVALID_STATE_TRANSITION`)."
    PRD §3.9: "And it de-escalates `ELEVATED` → `NORMAL` unconditionally."
    PRD §3.2: "Its declared path runs `PLANNING` → `REGISTRATION_OPEN` →
    `IN_SESSION` → `FINALS` → `GRADING` → `CLOSED` → `ARCHIVED`, with one reversal —
    `FINALS` back to `IN_SESSION` — and `ARCHIVED` as the terminal state."
    PRD §3.2: "Every one of these transitions increments the term's `version` by
    one."
    PRD §3.2: "Advancing `FINALS` → `GRADING` requires the term to currently be in
    `FINALS` and requires `continuity_posture` to be anything other than
    `CONTINUITY_MODE`; attempting it during continuity mode is refused with
    `ERR_TERM_POSTURE_FROZEN`."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."

    Design: Corner/state_machines/term_lifecycle_and_continuity_posture_advance_as_independent_dimensions
    """
    term = fx.create_term(api)
    assert term["lifecycle_state"] == "PLANNING"
    assert term["continuity_posture"] == "NORMAL"
    assert term["version"] == 1

    validate_error(
        api.term_posture_change(
            term["id"],
            {"target_posture": "ELEVATED", "reason": "continuity drill"},
            lms_admin_headers,
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )
    refused = fx.read_term(api, term["id"])
    assert refused["continuity_posture"] == "NORMAL"
    assert refused["lifecycle_state"] == "PLANNING"
    assert refused["version"] == 1, "the refused posture change mutated nothing"

    opened = fx.transition_term(api, term["id"], "REGISTRATION_OPEN")
    assert opened["lifecycle_state"] == "REGISTRATION_OPEN"
    assert opened["continuity_posture"] == "NORMAL"
    assert opened["version"] == 2

    in_session = fx.transition_term(api, term["id"], "IN_SESSION")
    assert in_session["lifecycle_state"] == "IN_SESSION"
    assert in_session["version"] == 3

    elevated = fx.change_posture(api, term["id"], "ELEVATED")
    assert elevated["continuity_posture"] == "ELEVATED"
    assert elevated["lifecycle_state"] == "IN_SESSION", (
        "moving one dimension leaves the other where it was"
    )
    assert elevated["version"] == 4

    finals = fx.transition_term(api, term["id"], "FINALS")
    assert finals["lifecycle_state"] == "FINALS"
    assert finals["continuity_posture"] == "ELEVATED"
    assert finals["version"] == 5

    de_escalated = fx.change_posture(api, term["id"], "NORMAL")
    assert de_escalated["continuity_posture"] == "NORMAL"
    assert de_escalated["lifecycle_state"] == "FINALS"
    assert de_escalated["version"] == 6

    grading = fx.transition_term(api, term["id"], "GRADING")
    assert grading["lifecycle_state"] == "GRADING"
    assert grading["continuity_posture"] == "NORMAL"
    assert grading["version"] == 7


def test_closing_the_term_cascades_three_hops_across_shells_in_created_at_order(
    api, lms_admin_headers
):
    """PRD §3.2: "Once past the gate, three cascade hops run in order."
    PRD §3.2: "Hop one: every shell of the term whose `provisioning_state` is
    `PROVISIONED` or `PUBLISHED` and whose `merged_into_shell_id` is null transitions
    to `CONCLUDED`, processed in `created_at` ascending order."
    PRD §3.2: "Hop two: each of those conclusions moves that shell's enrollments
    whose `enrollment_state` is `ACTIVE` to `COMPLETED`."
    PRD §3.2: "Hop three: each of those completions zeroes the shell's
    `active_enrollment_count`, `seat_utilization_pct` and `overflow_flag`, and
    decrements the term's `total_active_enrollments` by the number of rows that shell
    completed."
    PRD §3.2: "The term's `published_shell_count` is then set to 0."
    PRD §3.2: "`GRADING` → `CLOSED` first requires the term's `open_amendment_count`
    to be 0, meaning no passback of the term is sitting in `DISPUTED` or `AMENDED`;
    otherwise it is refused with `ERR_OPEN_DISPUTES_BLOCK_CLOSE`."

    Design: Corner/state_machines/closing_the_term_cascades_three_hops_across_shells_in_created_at_order
    """
    setup = fx.published_shell_setup(
        api, "IN_SESSION", shell_overrides={"base_seat_cap": 3}
    )
    term_id = setup["term"]["id"]
    published_shell = setup["shell"]
    published_pairs = fx.enrol_new_students(api, published_shell["id"], 3)

    provisioned_shell = fx.provision_shell(
        api, term_id, setup["owner"]["id"], base_seat_cap=3
    )
    provisioned_pairs = fx.enrol_new_students(api, provisioned_shell["id"], 1)

    before = fx.read_term(api, term_id)
    assert before["total_active_enrollments"] == 4
    assert before["published_shell_count"] == 1

    fx.transition_term(api, term_id, "FINALS")
    fx.transition_term(api, term_id, "GRADING")
    closed = fx.transition_term(api, term_id, "CLOSED")
    assert closed["lifecycle_state"] == "CLOSED"
    assert closed["total_active_enrollments"] == 0
    assert closed["published_shell_count"] == 0

    for shell_id in (published_shell["id"], provisioned_shell["id"]):
        shell = fx.read_shell(api, shell_id)
        assert shell["provisioning_state"] == "CONCLUDED"
        assert shell["active_enrollment_count"] == 0
        assert shell["seat_utilization_pct"] == 0.00
        assert shell["overflow_flag"] is False

    first_row = fx.read_enrollment(api, published_pairs[0][1]["id"])
    assert first_row["enrollment_state"] == "COMPLETED"
    other_shell_row = fx.read_enrollment(api, provisioned_pairs[0][1]["id"])
    assert other_shell_row["enrollment_state"] == "COMPLETED", (
        "hop one reaches PROVISIONED shells too, not only PUBLISHED ones"
    )

    rows, meta = validate_paginated(
        api.list_course_shells(
            lms_admin_headers,
            {"term_id": term_id, "provisioning_state": "CONCLUDED"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [
        published_shell["id"], provisioned_shell["id"]
    ], "the cascade walks the term's shells in created_at ascending order"


def test_the_term_close_cascade_skips_terminal_shells_and_non_active_rows(api):
    """PRD §3.2: "Hop one: every shell of the term whose `provisioning_state` is
    `PROVISIONED` or `PUBLISHED` and whose `merged_into_shell_id` is null transitions
    to `CONCLUDED`, processed in `created_at` ascending order."
    PRD §3.2: "Hop two: each of those conclusions moves that shell's enrollments
    whose `enrollment_state` is `ACTIVE` to `COMPLETED`."
    PRD §3.2: "Hop three: each of those completions zeroes the shell's
    `active_enrollment_count`, `seat_utilization_pct` and `overflow_flag`, and
    decrements the term's `total_active_enrollments` by the number of rows that shell
    completed."
    PRD §3.3: "`REJECT` moves `REQUESTED` → `REJECTED`, which is terminal: it
    requires only that the shell still be `REQUESTED`, records the supplied reason
    into `reject_reason`, sets the shell's `storage_mb` to 0.00, and recomputes the
    owner's `sandbox_storage_charge_usd` — necessarily downward, since a rejected
    shell stops being billable."
    PRD §3.4: "It stamps `dropped_at` from the logical clock and then cascades in
    four hops: the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each fall by one; the freed seat re-runs the capacity
    rule, and while it reports at least one promotable slot the head of the shell's
    waitlist — chosen by `waitlist_position` ascending with `created_at` ascending as
    the tie-break — moves `WAITLISTED` → `ACTIVE`; each such promotion re-derives the
    shell's `effective_seat_cap`, `seat_utilization_pct` and `overflow_flag`; and any
    change in `overflow_flag` bubbles up to the term's `overflow_shell_count`."

    Design: Corner/state_machines/the_term_close_cascade_skips_terminal_shells_and_non_active_enrollment_rows
    """
    setup = fx.published_shell_setup(
        api, "IN_SESSION", shell_overrides={"base_seat_cap": 3}
    )
    term_id = setup["term"]["id"]
    live_shell = setup["shell"]

    kept_student = fx.create_student(api)
    dropped_student = fx.create_student(api)
    queued_student = fx.create_student(api)
    kept_row = fx.enrol(api, live_shell["id"], kept_student["id"])
    dropped_row = fx.enrol(api, live_shell["id"], dropped_student["id"])
    fx.transition_enrollment(api, dropped_row["id"], "DROP", reason="withdrew")
    queued_row = fx.enrol(
        api, live_shell["id"], queued_student["id"], requested_state="WAITLISTED"
    )
    assert queued_row["waitlist_position"] == 1

    rejected_shell = fx.request_shell(api, term_id, setup["owner"]["id"])
    fx.provisioning_decision(
        api, rejected_shell["id"], "REJECT", reason="duplicate section"
    )

    before = fx.read_term(api, term_id)
    assert before["total_active_enrollments"] == 1

    fx.transition_term(api, term_id, "FINALS")
    fx.transition_term(api, term_id, "GRADING")
    closed = fx.transition_term(api, term_id, "CLOSED")
    assert closed["lifecycle_state"] == "CLOSED"
    assert closed["total_active_enrollments"] == 0
    assert closed["published_shell_count"] == 0

    untouched = fx.read_shell(api, rejected_shell["id"])
    assert untouched["provisioning_state"] == "REJECTED", (
        "a terminal REJECTED shell is not swept into the cascade"
    )
    assert untouched["reject_reason"] == "duplicate section"

    concluded = fx.read_shell(api, live_shell["id"])
    assert concluded["provisioning_state"] == "CONCLUDED"
    assert concluded["active_enrollment_count"] == 0
    assert concluded["seat_utilization_pct"] == 0.00
    assert concluded["waitlisted_enrollment_count"] == 1, (
        "the cascade zeroes only the three named seat fields"
    )

    assert fx.read_enrollment(api, kept_row["id"])["enrollment_state"] == "COMPLETED"

    still_dropped = fx.read_enrollment(api, dropped_row["id"])
    assert still_dropped["enrollment_state"] == "DROPPED", (
        "hop two moves only ACTIVE rows"
    )
    assert parse_instant(still_dropped["dropped_at"]) == parse_instant(
        CLOCK_STARTUP_INSTANT
    )

    still_queued = fx.read_enrollment(api, queued_row["id"])
    assert still_queued["enrollment_state"] == "WAITLISTED"
    assert still_queued["waitlist_position"] == 1
