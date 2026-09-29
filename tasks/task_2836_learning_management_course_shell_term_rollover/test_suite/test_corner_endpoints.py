"""Endpoint-surface compliance tests for the LMS course-shell service.

Every test in this module drives the public HTTP API only, through the `api`
fixture, and rebuilds all of its preconditions from an empty database. The
logical clock reads 2026-08-01T00:00:00Z at the start of each test.
"""
from test_helpers import (
    advance_clock,
    make_instructor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TERM_START = "2026-08-24T00:00:00Z"
TERM_END = "2026-12-11T00:00:00Z"


def _num(value):
    """Compare a JSON money/decimal figure at two-decimal precision."""
    return round(float(value), 2)


def test_content_item_full_crud_cycle_rederives_parent_shell(
    api, registrar_headers, lms_admin_headers
):
    """Create, read, list, update and hard-delete one content item.

    PRD 3.6: "A new item opens with `copy_state` `SOURCE`, `date_stripped`
    false, `submission_count` 0, `has_submissions` false and `source_item_id`
    null — the last field is the copy-provenance self-reference, filled in only
    on rollover copies."

    PRD 2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer
    that starts at 1 on creation and increments by exactly one on every
    mutation of that record."

    PRD 3.6: "Creating, editing or removing an item re-derives the owning
    shell's `storage_mb` (the sum of its items' `storage_mb`), its
    `content_item_count` (the number of its items whose `copy_state` is not
    `SKIPPED`) and its `total_points_possible` (the sum of `points_possible`
    over its `ASSIGNMENT` and `QUIZ` items whose `copy_state` is not
    `SKIPPED`), and re-derives the shell owner's `sandbox_storage_charge_usd`
    for `SANDBOX` and `DEV` shells."

    PRD 3.6: "An item may be edited in place — `title`, `due_at`,
    `points_possible`, `storage_mb` — and may be removed only while its
    `has_submissions` is false; removing an item that has submissions is
    refused with `ERR_ITEM_HAS_SUBMISSIONS`, because the gradebook must keep
    them."

    PRD 4: "Successful creates answer with `201 Created`, successful reads,
    updates, transitions and decisions with `200 OK`, and the single delete
    with `204 No Content` and an empty body."

    PRD 2.4: "A request whose path names a record that does not exist is
    rejected with the 404 code specific to that record type —
    `ERR_TERM_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`, `ERR_SHELL_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_MERGE_REQUEST_NOT_FOUND`, `ERR_CONTENT_ITEM_NOT_FOUND`,
    `ERR_ROLLOVER_JOB_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
    `ERR_PASSBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or
    `ERR_WINDOW_NOT_FOUND`."

    PRD 2.3: "Both values are echoed back in the `meta` object of the envelope,
    alongside `total_count` (the number of records matching the filter before
    the page window is applied) and `has_more` (true when records remain beyond
    the current window)."

    Design: Corner/endpoints/content_items_support_the_full_create_read_update_delete_cycle
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6120",
                "full_name": "Barbara Liskov",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "CS500-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 20,
            },
            lms_admin_headers,
        ),
        201,
    )
    owner = make_instructor_headers(prof["id"])

    item = validate_success(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "ASSIGNMENT",
                "title": "Problem Set 1",
                "due_at": "2026-09-15T23:59:00Z",
                "points_possible": 50.00,
                "storage_mb": 12.00,
            },
            owner,
        ),
        201,
    )
    assert item["copy_state"] == "SOURCE"
    assert item["date_stripped"] is False
    assert item["submission_count"] == 0
    assert item["version"] == 1

    read = validate_success(api.get_content_item(item["id"], lms_admin_headers))
    assert read["title"] == "Problem Set 1"
    assert read["due_at"] == "2026-09-15T23:59:00Z"
    assert _num(read["points_possible"]) == 50.00

    rows, meta = validate_paginated(
        api.list_content_items(lms_admin_headers, params={"shell_id": shell["id"]})
    )
    assert [r["id"] for r in rows] == [item["id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    patched = validate_success(
        api.patch_content_item(
            item["id"],
            {
                "title": "Problem Set 1 (revised)",
                "points_possible": 60.00,
                "storage_mb": 20.00,
            },
            owner,
        )
    )
    assert patched["title"] == "Problem Set 1 (revised)"
    assert _num(patched["points_possible"]) == 60.00
    assert patched["version"] == 2

    shell_before = validate_success(
        api.get_course_shell(shell["id"], lms_admin_headers)
    )
    assert shell_before["content_item_count"] == 1
    assert _num(shell_before["total_points_possible"]) == 60.00
    assert _num(shell_before["storage_mb"]) == 20.00

    deleted = api.delete_content_item(item["id"], owner)
    assert deleted.status_code == 204, deleted.text
    assert deleted.text == ""

    validate_error(
        api.get_content_item(item["id"], lms_admin_headers),
        "ERR_CONTENT_ITEM_NOT_FOUND",
    )

    shell_after = validate_success(
        api.get_course_shell(shell["id"], lms_admin_headers)
    )
    assert shell_after["content_item_count"] == 0
    assert _num(shell_after["total_points_possible"]) == 0.00
    assert _num(shell_after["storage_mb"]) == 0.00

    empty_rows, empty_meta = validate_paginated(
        api.list_content_items(lms_admin_headers, params={"shell_id": shell["id"]})
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 0


def test_publish_and_unpublish_recheck_readiness_and_keep_the_term_count_exact(
    api, registrar_headers, lms_admin_headers
):
    """Cycle one shell PROVISIONED -> PUBLISHED -> PROVISIONED -> PUBLISHED.

    PRD 3.3: "On approval `effective_seat_cap` is set equal to
    `base_seat_cap`, `publish_readiness` is set to true, and
    `sandbox_expires_at` is set to sixty days after the term's `term_end_at`
    for a `SANDBOX` or `DEV` shell while remaining null for an `OFFICIAL` one."

    PRD 3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the
    placement opens in `placement_state` `REQUESTED` with `pinned_tool_version`
    null."

    PRD 3.7: "**Removal** (`REMOVE`) reaches the terminal `REMOVED` from all
    three earlier states, and can also arrive as the shell-archival cascade of
    §3.3, but its bookkeeping differs by origin state: removing an `ACTIVE`
    placement lowers the tool's `active_placement_count` by one, re-scores the
    tool and re-derives the shell's `publish_readiness`; removing a `BLOCKED`
    placement lowers the shell's `blocked_placement_count` by one and
    re-derives its `publish_readiness`; removing a `REQUESTED` placement only
    re-derives `publish_readiness`."

    PRD 3.7: "A shell is publish-ready exactly when its
    `blocked_placement_count` is 0."

    PRD 3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and
    increments the term's `published_shell_count` by one."

    PRD 3.3: "When an operator drives it, an optional `reason` is recorded into
    `unpublish_reason` and the posture gate applies exactly as it does for
    publishing, so unpublishing during `CONTINUITY_MODE` is refused with
    `ERR_TERM_POSTURE_FROZEN`."

    PRD 3.3: "Either form decrements the term's `published_shell_count` by one,
    and a shell may cycle between `PROVISIONED` and `PUBLISHED` any number of
    times."

    PRD 2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer
    that starts at 1 on creation and increments by exactly one on every
    mutation of that record."

    Design: Corner/endpoints/publish_and_unpublish_are_action_endpoints_that_recheck_readiness_each_time
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6130",
                "full_name": "Frances Allen",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "MA210-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 40,
            },
            lms_admin_headers,
        ),
        201,
    )
    approved = validate_success(
        api.shell_provisioning_decision(
            shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    assert approved["publish_readiness"] is True
    assert approved["version"] == 2

    tool = validate_success(
        api.create_tool_integration(
            {
                "vendor_name": "Delta",
                "tool_name": "QuizEngine",
                "tool_version": "3.1.0",
                "data_sharing_scope": "NONE",
            },
            lms_admin_headers,
        ),
        201,
    )
    placement = validate_success(
        api.create_tool_placement(
            {"tool_id": tool["id"], "shell_id": shell["id"]}, lms_admin_headers
        ),
        201,
    )
    assert placement["placement_state"] == "REQUESTED"
    assert placement["pinned_tool_version"] is None

    with_placement = validate_success(
        api.get_course_shell(shell["id"], lms_admin_headers)
    )
    assert with_placement["blocked_placement_count"] == 0
    assert with_placement["publish_readiness"] is True

    removed = validate_success(
        api.tool_placement_transition(
            placement["id"], {"action": "REMOVE"}, lms_admin_headers
        )
    )
    assert removed["placement_state"] == "REMOVED"

    before_publish = validate_success(
        api.get_course_shell(shell["id"], lms_admin_headers)
    )
    assert before_publish["publish_readiness"] is True
    v_before_pub = before_publish["version"]

    owner = make_instructor_headers(prof["id"])
    published = validate_success(api.publish_shell(shell["id"], owner))
    assert published["provisioning_state"] == "PUBLISHED"
    v_pub = published["version"]

    term_after_pub = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_after_pub["published_shell_count"] == 1

    unpublished = validate_success(
        api.unpublish_shell(shell["id"], owner, {"reason": "roster embargo"})
    )
    assert unpublished["provisioning_state"] == "PROVISIONED"
    assert unpublished["unpublish_reason"] == "roster embargo"
    v_unpub = unpublished["version"]

    term_after_unpub = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_after_unpub["published_shell_count"] == 0

    republished = validate_success(api.publish_shell(shell["id"], lms_admin_headers))
    assert republished["provisioning_state"] == "PUBLISHED"
    v_repub = republished["version"]

    term_after_repub = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_after_repub["published_shell_count"] == 1

    assert v_before_pub < v_pub < v_unpub < v_repub
    assert v_repub == v_before_pub + 3


def test_sync_batch_apply_is_all_or_nothing_and_runs_in_array_order(
    api, registrar_headers, lms_admin_headers
):
    """Stage, validate and apply three SIS batches against one term.

    PRD 3.1: "A newly registered term opens with `lifecycle_state` `PLANNING`
    and `continuity_posture` `NORMAL`, and with every aggregate counter at its
    floor: `published_shell_count`, `overflow_shell_count`,
    `total_active_enrollments`, `open_amendment_count` and `sis_sync_epoch` all
    read 0, while `rollover_completion_pct` reads 100.00 for the reason
    explained in §3.2."

    PRD 3.4: "A `Registrar` stages one against a term through `term_id`,
    supplying `operations` — an ordered array of between 1 and 200 objects, each
    carrying an `op` of either `ADD` or `DROP` together with a `shell_id`, a
    `person_id` and a `role` — and optionally a `batch_seq`, which defaults to
    the term's `sis_sync_epoch` plus one."

    PRD 3.4: "A staged batch opens in `batch_state` `DRAFT` with every tally at
    zero."

    PRD 3.4: "Each operation is examined in array order and counts as valid
    when its `shell_id` resolves to a shell belonging to this batch's term whose
    `provisioning_state` is `PROVISIONED` or `PUBLISHED`, and its `person_id`
    resolves to a person whose `access_revoked_at` is null."

    PRD 3.4: "The pass writes `validated_operation_count` and
    `rejected_operation_count` and touches no enrollment whatsoever."

    PRD 3.4: "Applying a validated batch (`APPLY`) forks two ways on the same
    action, and both branches are ordinary 200 responses carrying the batch —
    the failure branch is not an error envelope."

    PRD 3.4: "The batch instead takes `VALIDATED` → `FAILED` when its
    `rejected_operation_count` is greater than 0, or when at least one
    operation's shell has left `PROVISIONED` and `PUBLISHED` since validation;
    on that branch `failure_reason` is recorded, not a single enrollment is
    created or mutated — the batch applies all-or-nothing — and the term's
    `sis_sync_epoch` is left exactly as it was."

    PRD 3.4: "On the applied branch the operations execute in array order: an
    `ADD` creates an enrollment with `batch_id` set to this batch, live when the
    capacity rule reports a free seat and `WAITLISTED` when it does not, and a
    `DROP` moves the matching live enrollment to `DROPPED`."

    PRD 3.4: "The batch records `applied_add_count` and `applied_drop_count`,
    each drop's freed seat cascades waitlist promotions exactly as an individual
    drop does, `promoted_from_waitlist_count` records how many promotions fired
    across the whole batch, and the term's `sis_sync_epoch` advances by one."

    PRD 3.4: "The batch takes `VALIDATED` → `APPLIED` when its
    `rejected_operation_count` is 0 and every operation's shell is still
    `PROVISIONED` or `PUBLISHED`; it additionally requires `batch_seq` to equal
    the term's `sis_sync_epoch` plus one, and a batch arriving out of feed order
    is refused outright with `ERR_SYNC_EPOCH_OUT_OF_ORDER`."

    PRD 2.10: "36. A sync batch may be applied only when its `batch_seq` equals
    the term's `sis_sync_epoch` plus one, on
    `POST /enrollment-sync-batches/{id}/transitions` with action `APPLY` —
    otherwise `ERR_SYNC_EPOCH_OUT_OF_ORDER`."

    Design: Corner/endpoints/applying_a_sync_batch_is_all_or_nothing_and_processes_operations_in_array_order
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    opened = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    assert opened["sis_sync_epoch"] == 0

    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6140",
                "full_name": "Jean Bartik",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    sa = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "EC101-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 2,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            sa["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    sb = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "EC101-02",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 5,
            },
            lms_admin_headers,
        ),
        201,
    )
    assert sb["provisioning_state"] == "REQUESTED"

    learners = {}
    for tag, sis_id, name in (
        ("pa", "S-6141", "Learner A"),
        ("pb", "S-6142", "Learner B"),
        ("pc", "S-6143", "Learner C"),
        ("pd", "S-6144", "Learner D"),
    ):
        learners[tag] = validate_success(
            api.create_person(
                {
                    "sis_person_id": sis_id,
                    "full_name": name,
                    "primary_affiliation": "STUDENT",
                },
                registrar_headers,
            ),
            201,
        )

    b1 = validate_success(
        api.create_sync_batch(
            {
                "term_id": term["id"],
                "operations": [
                    {
                        "op": "ADD",
                        "shell_id": sa["id"],
                        "person_id": learners["pa"]["id"],
                        "role": "STUDENT",
                    },
                    {
                        "op": "ADD",
                        "shell_id": sb["id"],
                        "person_id": learners["pb"]["id"],
                        "role": "STUDENT",
                    },
                ],
            },
            registrar_headers,
        ),
        201,
    )
    assert b1["batch_state"] == "DRAFT"
    assert b1["batch_seq"] == 1

    b1_validated = validate_success(
        api.sync_batch_transition(
            b1["id"], {"action": "VALIDATE"}, registrar_headers
        )
    )
    assert b1_validated["batch_state"] == "VALIDATED"
    assert b1_validated["validated_operation_count"] == 1
    assert b1_validated["rejected_operation_count"] == 1

    rows_after_validate, _ = validate_paginated(
        api.list_enrollments(registrar_headers, params={"shell_id": sa["id"]})
    )
    assert rows_after_validate == []

    b1_applied = api.sync_batch_transition(
        b1["id"], {"action": "APPLY"}, registrar_headers
    )
    b1_failed = validate_success(b1_applied, 200)
    assert b1_failed["batch_state"] == "FAILED"
    assert b1_failed["failure_reason"] is not None
    assert b1_failed["applied_add_count"] == 0

    term_after_fail = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_after_fail["sis_sync_epoch"] == 0
    assert term_after_fail["total_active_enrollments"] == 0

    b2 = validate_success(
        api.create_sync_batch(
            {
                "term_id": term["id"],
                "operations": [
                    {
                        "op": "ADD",
                        "shell_id": sa["id"],
                        "person_id": learners["pa"]["id"],
                        "role": "STUDENT",
                    },
                    {
                        "op": "ADD",
                        "shell_id": sa["id"],
                        "person_id": learners["pb"]["id"],
                        "role": "STUDENT",
                    },
                    {
                        "op": "ADD",
                        "shell_id": sa["id"],
                        "person_id": learners["pc"]["id"],
                        "role": "STUDENT",
                    },
                    {
                        "op": "DROP",
                        "shell_id": sa["id"],
                        "person_id": learners["pa"]["id"],
                        "role": "STUDENT",
                    },
                ],
            },
            registrar_headers,
        ),
        201,
    )
    assert b2["batch_seq"] == 1

    b2_validated = validate_success(
        api.sync_batch_transition(
            b2["id"], {"action": "VALIDATE"}, registrar_headers
        )
    )
    assert b2_validated["validated_operation_count"] == 4
    assert b2_validated["rejected_operation_count"] == 0

    b2_applied = validate_success(
        api.sync_batch_transition(b2["id"], {"action": "APPLY"}, registrar_headers)
    )
    assert b2_applied["batch_state"] == "APPLIED"
    assert b2_applied["applied_add_count"] == 3
    assert b2_applied["applied_drop_count"] == 1
    assert b2_applied["promoted_from_waitlist_count"] == 1

    sa_after = validate_success(api.get_course_shell(sa["id"], lms_admin_headers))
    assert sa_after["active_enrollment_count"] == 2
    assert sa_after["waitlisted_enrollment_count"] == 0

    term_after_apply = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_after_apply["sis_sync_epoch"] == 1
    assert term_after_apply["total_active_enrollments"] == 2

    b3 = validate_success(
        api.create_sync_batch(
            {
                "term_id": term["id"],
                "batch_seq": 5,
                "operations": [
                    {
                        "op": "ADD",
                        "shell_id": sa["id"],
                        "person_id": learners["pd"]["id"],
                        "role": "STUDENT",
                    }
                ],
            },
            registrar_headers,
        ),
        201,
    )
    assert b3["batch_seq"] == 5

    b3_validated = validate_success(
        api.sync_batch_transition(
            b3["id"], {"action": "VALIDATE"}, registrar_headers
        )
    )
    assert b3_validated["validated_operation_count"] == 1

    validate_error(
        api.sync_batch_transition(b3["id"], {"action": "APPLY"}, registrar_headers),
        "ERR_SYNC_EPOCH_OUT_OF_ORDER",
    )

    term_final = validate_success(
        api.get_academic_term(term["id"], registrar_headers)
    )
    assert term_final["sis_sync_epoch"] == 1


def test_tool_placement_resolves_both_foreign_keys_and_is_reachable_both_ways(
    api, registrar_headers, lms_admin_headers
):
    """Link one tool to one shell and read the junction from both directions.

    PRD 2.4: "Foreign keys supplied in a request body are resolved the same way
    and return the same record-specific codes, checked in the order the
    endpoint declares its input fields, so the first unresolvable reference
    decides the response."

    PRD 3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the
    placement opens in `placement_state` `REQUESTED` with `pinned_tool_version`
    null."

    PRD 2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is
    how the reverse direction of each relationship is reachable."

    PRD 3.7: "A new tool opens with `approval_state` `DRAFT`,
    `privacy_review_state` `PENDING`, `accessibility_review_state` `PENDING`,
    `risk_score` null, `approved_version` null, `active_placement_count` 0 and
    `suspension_reason` null."

    PRD 3.7: "Activation pins `pinned_tool_version` to the tool's
    `approved_version`, raises the tool's `active_placement_count` by one,
    re-scores the tool, and re-derives the shell's `publish_readiness`."

    Design: Corner/endpoints/a_tool_placement_links_two_entities_and_both_sides_must_resolve_first
    """
    missing_tool_id = "00000000-0000-4000-8000-000000000911"
    missing_shell_id = "00000000-0000-4000-8000-000000000912"

    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6150",
                "full_name": "Karen Uhlenbeck",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "ST220-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 30,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    tool = validate_success(
        api.create_tool_integration(
            {
                "vendor_name": "Epsilon",
                "tool_name": "PeerReview",
                "tool_version": "0.9.0",
                "data_sharing_scope": "ROSTER_ONLY",
            },
            lms_admin_headers,
        ),
        201,
    )

    validate_error(
        api.create_tool_placement(
            {"tool_id": missing_tool_id, "shell_id": shell["id"]}, lms_admin_headers
        ),
        "ERR_TOOL_NOT_FOUND",
    )
    validate_error(
        api.create_tool_placement(
            {"tool_id": tool["id"], "shell_id": missing_shell_id}, lms_admin_headers
        ),
        "ERR_SHELL_NOT_FOUND",
    )

    placement = validate_success(
        api.create_tool_placement(
            {"tool_id": tool["id"], "shell_id": shell["id"]}, lms_admin_headers
        ),
        201,
    )
    assert placement["placement_state"] == "REQUESTED"
    assert placement["pinned_tool_version"] is None

    by_tool, by_tool_meta = validate_paginated(
        api.list_tool_placements(lms_admin_headers, params={"tool_id": tool["id"]})
    )
    assert [r["id"] for r in by_tool] == [placement["id"]]
    assert by_tool_meta["total_count"] == 1

    by_shell, by_shell_meta = validate_paginated(
        api.list_tool_placements(lms_admin_headers, params={"shell_id": shell["id"]})
    )
    assert [r["id"] for r in by_shell] == [placement["id"]]
    assert by_shell_meta["total_count"] == 1

    read = validate_success(
        api.get_tool_placement(placement["id"], make_instructor_headers(prof["id"]))
    )
    assert read["tool_id"] == tool["id"]
    assert read["shell_id"] == shell["id"]

    tool_after = validate_success(
        api.get_tool_integration(tool["id"], lms_admin_headers)
    )
    assert tool_after["active_placement_count"] == 0


def test_owner_chargeback_read_reflects_every_storage_write(
    api, registrar_headers, lms_admin_headers
):
    """Recompute one owner's sandbox chargeback after create, patch and delete.

    PRD 3.3: "A person's `sandbox_storage_charge_usd` starts at 0.00 and is only
    ever written by the chargeback computation described later in this
    subsection."

    PRD 3.3: "Whenever a content item is added to or removed from such a shell,
    whenever such a shell's `storage_mb` changes because a rollover copied into
    it or a compensation unwound the copy, and whenever a shell is purged, the
    owner's `sandbox_storage_charge_usd` is recomputed from scratch."

    PRD 3.3: "The billable set is that person's shells whose `shell_type` is
    `SANDBOX` or `DEV` and whose `provisioning_state` is neither `REJECTED` nor
    `PURGED`; `OFFICIAL` shells are never charged."

    PRD 3.3: "For each shell, subtract a free allowance of 100.00 megabytes from
    its `storage_mb` and treat any negative result as zero; multiply the
    remainder by a rate of 0.0150 US dollars per megabyte; multiply again by the
    class multiplier, which is 1.00 for a `SANDBOX` shell and 0.50 for a `DEV`
    shell; then round that single shell's charge half up to two decimal places."

    PRD 3.3: "The person's total is the sum of those already-rounded per-shell
    charges."

    PRD 3.6: "Creating, editing or removing an item re-derives the owning
    shell's `storage_mb` (the sum of its items' `storage_mb`), its
    `content_item_count` (the number of its items whose `copy_state` is not
    `SKIPPED`) and its `total_points_possible` (the sum of `points_possible`
    over its `ASSIGNMENT` and `QUIZ` items whose `copy_state` is not
    `SKIPPED`), and re-derives the shell owner's `sandbox_storage_charge_usd`
    for `SANDBOX` and `DEV` shells."

    Design: Corner/endpoints/the_owner_chargeback_read_reflects_every_storage_write_to_their_sandbox_shells
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6160",
                "full_name": "Adele Goldberg",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    assert _num(prof["sandbox_storage_charge_usd"]) == 0.00

    sandbox = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "SBX-R1",
                "shell_type": "SANDBOX",
                "base_seat_cap": 1,
            },
            lms_admin_headers,
        ),
        201,
    )
    dev = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "DEV-R2",
                "shell_type": "DEV",
                "base_seat_cap": 1,
            },
            lms_admin_headers,
        ),
        201,
    )
    owner = make_instructor_headers(prof["id"])

    item_a = validate_success(
        api.create_content_item(
            {
                "shell_id": sandbox["id"],
                "item_type": "PAGE",
                "title": "big media page",
                "points_possible": 0.00,
                "storage_mb": 250.00,
            },
            owner,
        ),
        201,
    )
    charge_1 = validate_success(api.get_person(prof["id"], lms_admin_headers))
    assert _num(charge_1["sandbox_storage_charge_usd"]) == 2.25

    patched = validate_success(
        api.patch_content_item(item_a["id"], {"storage_mb": 100.00}, owner)
    )
    assert _num(patched["storage_mb"]) == 100.00
    charge_2 = validate_success(api.get_person(prof["id"], lms_admin_headers))
    assert _num(charge_2["sandbox_storage_charge_usd"]) == 0.00

    item_b = validate_success(
        api.create_content_item(
            {
                "shell_id": sandbox["id"],
                "item_type": "FILE",
                "title": "lecture capture bundle",
                "points_possible": 0.00,
                "storage_mb": 400.00,
            },
            owner,
        ),
        201,
    )
    charge_3 = validate_success(api.get_person(prof["id"], lms_admin_headers))
    assert _num(charge_3["sandbox_storage_charge_usd"]) == 6.00

    validate_success(
        api.create_content_item(
            {
                "shell_id": dev["id"],
                "item_type": "FILE",
                "title": "dev fixtures",
                "points_possible": 0.00,
                "storage_mb": 300.00,
            },
            owner,
        ),
        201,
    )
    charge_4 = validate_success(api.get_person(prof["id"], lms_admin_headers))
    assert _num(charge_4["sandbox_storage_charge_usd"]) == 7.50

    removed = api.delete_content_item(item_b["id"], owner)
    assert removed.status_code == 204, removed.text

    charge_5 = validate_success(api.get_person(prof["id"], lms_admin_headers))
    assert _num(charge_5["sandbox_storage_charge_usd"]) == 1.50

    sandbox_after = validate_success(
        api.get_course_shell(sandbox["id"], lms_admin_headers)
    )
    assert _num(sandbox_after["storage_mb"]) == 100.00


def test_purge_of_an_archived_shell_is_gated_by_the_terms_retention_class(
    api, registrar_headers, lms_admin_headers
):
    """Purge two identically archived shells whose terms differ only in class.

    PRD 3.1: "First, take the calendar date reached by advancing `term_end_at`
    forward by `access_grace_days` whole days, and set `student_access_end_at`
    to that date at 23:59:59 UTC — a fixed wall time with no sub-second
    component."

    PRD 3.1: "Second, choose a retention horizon from `retention_class`: 365
    days for `STANDARD`, 1825 days for `EXTENDED`, and no horizon at all for
    `LEGAL_HOLD`."

    PRD 3.1: "When there is no horizon, `retention_purge_at` is null and the
    shell purge path is closed permanently."

    PRD 3.1: "Otherwise `retention_purge_at` is `student_access_end_at` advanced
    by that many whole days, keeping the same 23:59:59 wall time."

    PRD 3.2: "Hop one: every shell of the term whose `provisioning_state` is
    `PROVISIONED` or `PUBLISHED` and whose `merged_into_shell_id` is null
    transitions to `CONCLUDED`, processed in `created_at` ascending order."

    PRD 3.3: "`CONCLUDED` → `ARCHIVED` requires the shell's term to have
    reached `CLOSED` or `ARCHIVED` (`ERR_INVALID_STATE_TRANSITION`)."

    PRD 3.3: "First, the term's `retention_class` must not be `LEGAL_HOLD`; a
    shell under legal hold is refused with `ERR_RETENTION_HOLD_ACTIVE`, and
    because that check outranks the horizon check, it is the code reported even
    though such a term's `retention_purge_at` is null."

    PRD 3.3: "Purging sets every content item of the shell to `copy_state`
    `SKIPPED` with `storage_mb` 0.00, sets the shell's own `content_item_count`
    to 0, its `total_points_possible` to 0.00 and its `storage_mb` to 0.00, and
    recomputes the owner's `sandbox_storage_charge_usd`."

    PRD 2.10: "27. A term whose `retention_class` is `LEGAL_HOLD` forbids purge
    outright, regardless of elapsed time. On
    `POST /course-shells/{id}/lifecycle-transitions` targeting `PURGED` —
    otherwise `ERR_RETENTION_HOLD_ACTIVE`. This band deliberately outranks the
    next one, so a shell under legal hold reports the hold rather than an unmet
    horizon even though its `retention_purge_at` is null."

    Design: Corner/endpoints/purging_an_archived_shell_is_permitted_only_when_the_terms_retention_class_allows_it
    """
    t_std = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
                "access_grace_days": 0,
                "retention_class": "STANDARD",
            },
            registrar_headers,
        ),
        201,
    )
    t_hold = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FB",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
                "access_grace_days": 0,
                "retention_class": "LEGAL_HOLD",
            },
            registrar_headers,
        ),
        201,
    )
    assert t_std["retention_purge_at"] == "2027-12-11T23:59:59Z"
    assert t_hold["retention_purge_at"] is None

    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6170",
                "full_name": "Evelyn Boyd Granville",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )

    shells = {}
    for tag, term in (("std", t_std), ("hold", t_hold)):
        validate_success(
            api.term_lifecycle_transition(
                term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
            )
        )
        shell = validate_success(
            api.create_course_shell(
                {
                    "term_id": term["id"],
                    "owner_person_id": prof["id"],
                    "sis_section_code": "HI110-01",
                    "shell_type": "OFFICIAL",
                    "base_seat_cap": 15,
                },
                lms_admin_headers,
            ),
            201,
        )
        validate_success(
            api.shell_provisioning_decision(
                shell["id"], {"decision": "APPROVE"}, lms_admin_headers
            )
        )
        shells[tag] = shell

    for term in (t_std, t_hold):
        for target in ("IN_SESSION", "FINALS", "GRADING", "CLOSED"):
            validate_success(
                api.term_lifecycle_transition(
                    term["id"], {"target_state": target}, registrar_headers
                )
            )

    for tag in ("std", "hold"):
        archived = validate_success(
            api.shell_lifecycle_transition(
                shells[tag]["id"], {"target_state": "ARCHIVED"}, registrar_headers
            )
        )
        assert archived["provisioning_state"] == "ARCHIVED"

    advance_clock(api, "2027-12-11T23:59:59Z", lms_admin_headers)

    purged = validate_success(
        api.shell_lifecycle_transition(
            shells["std"]["id"],
            {"target_state": "PURGED", "reason": "retention horizon reached"},
            registrar_headers,
        )
    )
    assert purged["provisioning_state"] == "PURGED"
    assert _num(purged["storage_mb"]) == 0.00
    assert purged["content_item_count"] == 0

    validate_error(
        api.shell_lifecycle_transition(
            shells["hold"]["id"],
            {"target_state": "PURGED", "reason": "retention horizon reached"},
            registrar_headers,
        ),
        "ERR_RETENTION_HOLD_ACTIVE",
    )

    held = validate_success(
        api.get_course_shell(shells["hold"]["id"], registrar_headers)
    )
    assert held["provisioning_state"] == "ARCHIVED"
