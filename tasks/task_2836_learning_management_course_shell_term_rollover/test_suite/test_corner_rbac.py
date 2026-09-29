"""Role-based access control: exclusive operations, shared operations, peers.

Six roles travel in `X-User-Role`. Each one owns endpoints no other role can
reach, several endpoints are shared by an explicit list of roles, the two
reviewer roles are symmetric peers bound to disjoint review dimensions, and two
holders of the same role are still separated by the segregation-of-duties gate.
"""
from datetime import datetime, timezone

from test_helpers import (
    ACCESSIBILITY_REVIEWER_USER_ID,
    CLOCK_STARTUP_INSTANT,
    LMS_ADMIN_ALT_USER_ID,
    LMS_ADMIN_USER_ID,
    PRIVACY_REVIEWER_USER_ID,
    create_content_item,
    create_course_shell_payload,
    create_academic_term_payload,
    create_enrollment_payload,
    create_faculty,
    create_grade_dispute_payload,
    create_grade_passback_payload,
    create_student,
    create_term,
    create_tool_review_payload,
    file_review,
    get_success_data,
    grade_record_payload,
    make_instructor_headers,
    open_merge_request,
    patch_content_item,
    provisioning_decision,
    publish,
    read_content_item,
    read_merge_request,
    read_shell,
    read_term,
    read_tool,
    record_submission,
    register_tool,
    request_placement,
    request_shell,
    set_clock_payload,
    transition_merge_request,
    transition_placement,
    transition_term,
    transition_tool,
    unpublish,
    validate_error,
    validate_paginated,
)


def _instant(value):
    """Parse a wire timestamp so two spellings of the same instant compare equal."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_each_role_can_perform_its_own_exclusive_operations(
    api, registrar_headers, lms_admin_headers, privacy_reviewer_headers,
    accessibility_reviewer_headers,
):
    """One walk exercises the operations each role alone may perform.

    The Registrar mints the term, the people and the enrollment plus its DROP;
    the LmsAdmin provisions the shell and flips the term posture; the owning
    Instructor grades, records a submission and edits the item; and the two
    reviewer roles each file the single review dimension bound to their role.

    PRD 2.1: "A value of `X-User-Role` that is not one of those six, or that is
    not listed among the authorized roles for the endpoint being called, is
    rejected with `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD 3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty
    days after the term's `term_end_at` for a `SANDBOX` or `DEV` shell while
    remaining null for an `OFFICIAL` one."
    PRD 3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role`
    is `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD 3.8: "Each write re-derives the enrollment's `earned_points_total` as
    the sum of its grade records and its `graded_points_possible` as the sum of
    the `points_possible` of the items it now carries a record for, and
    re-derives that enrollment's `provisional_grade_pct`."
    PRD 3.8: "The **provisional** variant divides by the enrollment's own
    `graded_points_possible` — the work graded so far — which flatters an
    incomplete gradebook, and it writes `provisional_grade_pct`."
    PRD 3.6: "A submission is recorded against an item by naming the
    `enrollment_id` it belongs to; the item's `has_submissions` becomes true and
    its `submission_count` rises by one."
    PRD 3.6: "An item may be edited in place — `title`, `due_at`,
    `points_possible`, `storage_mb` — and may be removed only while its
    `has_submissions` is false; removing an item that has submissions is refused
    with `ERR_ITEM_HAS_SUBMISSIONS`, because the gradebook must keep them."
    PRD 2.4: "Recomputing a derived figure counts as a mutation: when a shell's
    `seat_utilization_pct` is re-derived, when a term's
    `rollover_completion_pct` is recomputed and persisted, or when a tool's
    `risk_score` is re-scored, that record's `updated_at` is refreshed and its
    `version` advances."
    PRD 3.4: "**Dropping** takes `ACTIVE` → `DROPPED` and needs only that the
    shell be `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."
    PRD 2.5: "Timestamps the server stamps itself — `dropped_at`, `resolved_at`,
    `closed_at` — are taken from the logical clock at the moment of the
    transition."
    PRD 2.5: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to real time."
    PRD 3.9: "It escalates `NORMAL` → `ELEVATED`, which requires the term's
    `lifecycle_state` to be `IN_SESSION`, `FINALS` or `GRADING` (otherwise
    `ERR_INVALID_STATE_TRANSITION`)."
    PRD 3.7: "The two verdict dimensions move only through reviews; the overall
    dimension moves only through administrative actions."
    PRD 3.7: "A `CLEAR` decision moves that dimension `PENDING` → `CLEARED`,
    `CONDITIONS` moves it `PENDING` → `CONDITIONAL`, and `BLOCK` moves it
    `PENDING` → `BLOCKED`."
    PRD 2.1: "The server records it where a transition says so — as
    `submitted_by_user_id` and `decided_by_user_id` on a `MergeRequest`, and as
    `reviewer_user_id` on a `ToolReview` — and compares it to other recorded
    operator identifiers for segregation-of-duties purposes, but never compares
    it to any entity's `id`."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
    """
    # ── Registrar: the term and the people ──
    term = create_term(
        api, headers=registrar_headers, term_code="RBAC-2027-SP",
        term_start_at="2027-01-11T00:00:00Z", term_end_at="2027-05-14T00:00:00Z",
    )
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    assert term["lifecycle_state"] == "REGISTRATION_OPEN"
    professor = create_faculty(
        api, headers=registrar_headers, sis_person_id="RBAC-F-01",
        full_name="Dana Reyes",
    )
    student = create_student(
        api, headers=registrar_headers, sis_person_id="RBAC-S-01", full_name="Kim Ito",
    )
    instructor = make_instructor_headers(professor["id"])

    # ── LmsAdmin: the shell and its provisioning decision ──
    shell = request_shell(
        api, term["id"], professor["id"], headers=lms_admin_headers,
        sis_section_code="RBAC-101-001", shell_type="OFFICIAL", base_seat_cap=20,
    )
    shell = provisioning_decision(api, shell["id"], "APPROVE", headers=lms_admin_headers)
    assert shell["provisioning_state"] == "PROVISIONED"
    assert shell["effective_seat_cap"] == 20

    item = create_content_item(
        api, shell["id"], headers=instructor, item_type="ASSIGNMENT",
        title="Problem Set 1", points_possible=40.00, storage_mb=5.00,
    )
    assert item["version"] == 1

    tool = register_tool(
        api, headers=lms_admin_headers, vendor_name="Lumen", tool_name="Proctor Lite",
        tool_version="3.1.0", data_sharing_scope="ROSTER_ONLY", pii_tier=1,
        vpat_score=92.00, wcag_level="AA",
    )
    tool = transition_tool(api, tool["id"], "OPEN_REVIEW", headers=lms_admin_headers)
    assert tool["approval_state"] == "UNDER_REVIEW"

    # ── Registrar only: the enrollment ──
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(shell["id"], student["id"], role="STUDENT"),
            registrar_headers,
        )
    )
    assert enrollment["enrollment_state"] == "ACTIVE"

    # ── Instructor only: the grade record, the submission and the item edit ──
    graded = get_success_data(
        api.record_grade(
            grade_record_payload(enrollment["id"], item["id"], 30.00), instructor
        )
    )
    assert graded["earned_points_total"] == 30.00
    assert graded["graded_points_possible"] == 40.00
    assert graded["provisional_grade_pct"] == 75.00

    submitted = record_submission(api, item["id"], enrollment["id"], instructor)
    assert submitted["has_submissions"] is True
    assert submitted["submission_count"] == 1

    edited = patch_content_item(
        api, item["id"], {"title": "Problem Set 1 (revised)"}, instructor
    )
    assert edited["title"] == "Problem Set 1 (revised)"
    assert edited["version"] == 3, (
        "the item was created, then mutated by the submission, then edited - three "
        f"mutations of one record, so version must read 3, got {edited['version']}"
    )

    # ── Registrar only: the DROP, stamped from the untouched startup clock ──
    dropped = get_success_data(
        api.enrollment_transition(
            enrollment["id"], {"action": "DROP", "reason": "student withdrew"},
            registrar_headers,
        )
    )
    assert dropped["enrollment_state"] == "DROPPED"
    assert _instant(dropped["dropped_at"]) == _instant(CLOCK_STARTUP_INSTANT)

    # ── Registrar drives the lifecycle, LmsAdmin the independent posture ──
    term = transition_term(api, term["id"], "IN_SESSION", registrar_headers)
    assert term["lifecycle_state"] == "IN_SESSION"
    escalated = get_success_data(
        api.term_posture_change(
            term["id"],
            {"target_posture": "ELEVATED", "reason": "regional storm advisory"},
            lms_admin_headers,
        )
    )
    assert escalated["continuity_posture"] == "ELEVATED"
    assert escalated["lifecycle_state"] == "IN_SESSION", (
        "the posture write must not disturb the term's lifecycle dimension"
    )

    # ── each reviewer role files exactly the dimension bound to that role ──
    privacy_review = get_success_data(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            privacy_reviewer_headers,
        )
    )
    assert privacy_review["dimension"] == "PRIVACY"
    assert privacy_review["reviewer_user_id"] == PRIVACY_REVIEWER_USER_ID

    accessibility_review = get_success_data(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "ACCESSIBILITY", "CLEAR"),
            accessibility_reviewer_headers,
        )
    )
    assert accessibility_review["dimension"] == "ACCESSIBILITY"
    assert accessibility_review["reviewer_user_id"] == ACCESSIBILITY_REVIEWER_USER_ID

    tool_now = read_tool(api, tool["id"], lms_admin_headers)
    assert tool_now["privacy_review_state"] == "CLEARED"
    assert tool_now["accessibility_review_state"] == "CLEARED"
    assert tool_now["approval_state"] == "UNDER_REVIEW", (
        "the two verdict dimensions land independently; only an administrative "
        "FINALIZE_REVIEW compounds them into the overall dimension"
    )


def test_no_role_can_reach_another_roles_exclusive_operations(
    api, registrar_headers, lms_admin_headers, student_headers_for,
):
    """Ten refusals where the denied caller is privileged somewhere else.

    Every caller below holds a role that is legitimate on some other endpoint -
    the Registrar owns terms but not shells, the LmsAdmin owns shells but not
    terms, the LmsAdmin may create a content item but not delete one - so only a
    per-endpoint role list refuses all ten.

    PRD 2.1: "A value of `X-User-Role` that is not one of those six, or that is
    not listed among the authorized roles for the endpoint being called, is
    rejected with `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD 2.10: "`X-User-Role` is one of the six declared roles and is authorized
    for the target endpoint; and on `POST /tool-reviews` the body's `dimension`
    matches the acting reviewer role — otherwise `ERR_ROLE_NOT_PERMITTED`.
    Applies to every endpoint."
    PRD 2.10: "When several rules could reject the same request, exactly one of
    them decides the response, and the order is fixed."
    PRD 2.3: "Both values are echoed back in the `meta` object of the envelope,
    alongside `total_count` (the number of records matching the filter before
    the page window is applied) and `has_more` (true when records remain beyond
    the current window)."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operations
    """
    term = create_term(
        api, headers=registrar_headers, term_code="DENY-2027-SU",
        term_start_at="2027-06-01T00:00:00Z", term_end_at="2027-08-06T00:00:00Z",
    )
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    professor = create_faculty(
        api, headers=registrar_headers, sis_person_id="DENY-F-01",
        full_name="Ada Okoro",
    )
    student = create_student(
        api, headers=registrar_headers, sis_person_id="DENY-S-01",
        full_name="Luis Marin",
    )
    instructor = make_instructor_headers(professor["id"])
    student_hdrs = student_headers_for(student["id"])

    shell = request_shell(
        api, term["id"], professor["id"], headers=lms_admin_headers,
        sis_section_code="DENY-210-001", shell_type="OFFICIAL", base_seat_cap=15,
    )
    shell = provisioning_decision(api, shell["id"], "APPROVE", headers=lms_admin_headers)
    assert shell["provisioning_state"] == "PROVISIONED"
    item = create_content_item(
        api, shell["id"], headers=instructor, item_type="PAGE", title="Syllabus",
        points_possible=0.00, storage_mb=2.00,
    )
    tool = register_tool(
        api, headers=lms_admin_headers, vendor_name="Kestrel", tool_name="Quiz Bank",
        tool_version="1.0.0", data_sharing_scope="NONE", pii_tier=0,
        vpat_score=88.00, wcag_level="AA",
    )
    tool = transition_tool(api, tool["id"], "OPEN_REVIEW", headers=lms_admin_headers)
    assert tool["approval_state"] == "UNDER_REVIEW"

    # ── the Registrar owns terms, not shells ──
    validate_error(
        api.create_course_shell(
            create_course_shell_payload(
                term["id"], professor["id"], sis_section_code="DENY-210-002",
                shell_type="OFFICIAL", base_seat_cap=15,
            ),
            registrar_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the LmsAdmin owns shells, not the term row or its lifecycle ──
    validate_error(
        api.create_academic_term(
            create_academic_term_payload(
                term_code="DENY-2028-SP", term_start_at="2028-01-10T00:00:00Z",
                term_end_at="2028-05-12T00:00:00Z",
            ),
            lms_admin_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "IN_SESSION"}, lms_admin_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the posture dimension is the LmsAdmin's, not the Registrar's ──
    validate_error(
        api.term_posture_change(
            term["id"], {"target_posture": "ELEVATED"}, registrar_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── a Student cannot enroll themself even into free seats ──
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(shell["id"], student["id"], role="STUDENT"),
            student_hdrs,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the Registrar receives passbacks but may not stage one ──
    validate_error(
        api.create_grade_passback(
            create_grade_passback_payload(shell["id"]), registrar_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the LmsAdmin shares the item create but not the sibling verbs ──
    validate_error(
        api.delete_content_item(item["id"], lms_admin_headers),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the LmsAdmin runs the review workflow but casts no dimension verdict ──
    validate_error(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            lms_admin_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the Instructor resolves disputes but cannot file one; the role check
    #    decides before any foreign key is even resolved ──
    validate_error(
        api.create_grade_dispute(
            create_grade_dispute_payload(shell["id"], shell["id"], item["id"], 10.00),
            instructor,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # ── the test clock is the LmsAdmin's alone ──
    validate_error(
        api.set_clock(set_clock_payload("2027-07-01T00:00:00Z"), instructor),
        "ERR_ROLE_NOT_PERMITTED",
    )

    # ── not one of the ten refusals left a trace ──
    term_now = read_term(api, term["id"], registrar_headers)
    assert term_now["lifecycle_state"] == "REGISTRATION_OPEN"
    assert term_now["continuity_posture"] == "NORMAL"
    assert read_content_item(api, item["id"], instructor)["title"] == "Syllabus"

    rows, meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, params={"term_id": term["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["sis_section_code"] for row in rows] == ["DENY-210-001"]


def test_shared_operations_are_reachable_by_every_role_that_declares_them(
    api, registrar_headers, lms_admin_headers, privacy_reviewer_headers,
    accessibility_reviewer_headers,
):
    """Sharing is per endpoint: both sharers act, and a non-sharer is refused.

    The LmsAdmin and the owning Instructor each create content, publish,
    unpublish, place a tool and activate a placement the *other* role created,
    while the Registrar - broadly privileged elsewhere - is refused the one read
    that only the LmsAdmin and the two reviewers share.

    PRD 2.1: "A value of `X-User-Role` that is not one of those six, or that is
    not listed among the authorized roles for the endpoint being called, is
    rejected with `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD 3.6: "An `Instructor` or an `LmsAdmin` adds an item by naming
    `shell_id`, an `item_type` of `ASSIGNMENT`, `QUIZ`, `PAGE` or `FILE`, and a
    `title`, optionally with a `due_at`, a `points_possible` and a
    `storage_mb`."
    PRD 3.6: "Creating, editing or removing an item re-derives the owning
    shell's `storage_mb` (the sum of its items' `storage_mb`), its
    `content_item_count` (the number of its items whose `copy_state` is not
    `SKIPPED`) and its `total_points_possible` (the sum of `points_possible`
    over its `ASSIGNMENT` and `QUIZ` items whose `copy_state` is not
    `SKIPPED`), and re-derives the shell owner's `sandbox_storage_charge_usd`
    for `SANDBOX` and `DEV` shells."
    PRD 3.3: "Publishing a provisioned shell to students is available to both
    the owning `Instructor` and an `LmsAdmin`, and it carries five
    preconditions, each with its own refusal."
    PRD 3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and
    increments the term's `published_shell_count` by one."
    PRD 3.3: "When an operator drives it, an optional `reason` is recorded into
    `unpublish_reason` and the posture gate applies exactly as it does for
    publishing, so unpublishing during `CONTINUITY_MODE` is refused with
    `ERR_TERM_POSTURE_FROZEN`."
    PRD 3.3: "Either form decrements the term's `published_shell_count` by one,
    and a shell may cycle between `PROVISIONED` and `PUBLISHED` any number of
    times."
    PRD 3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the
    placement opens in `placement_state` `REQUESTED` with `pinned_tool_version`
    null."
    PRD 3.7: "Activation pins `pinned_tool_version` to the tool's
    `approved_version`, raises the tool's `active_placement_count` by one,
    re-scores the tool, and re-derives the shell's `publish_readiness`."
    PRD 3.7: "A shell is publish-ready exactly when its
    `blocked_placement_count` is 0."
    PRD 3.7: "The tool's `risk_score` is a weighted composite of its governance
    attributes and its live exposure, computed from five addends."
    PRD 3.7: "The PII points are the `pii_tier` multiplied by 10, so 0 through
    30."
    PRD 3.7: "The scope points are 0 for `NONE`, 10 for `ROSTER_ONLY`, 25 for
    `ROSTER_AND_GRADES` and 40 for `FULL_PROFILE`."
    PRD 3.7: "The accessibility-gap points are 100 minus the `vpat_score`,
    multiplied by 0.30."
    PRD 3.7: "The exposure points are the `active_placement_count` multiplied by
    3, capped at 15."
    PRD 3.7: "The raw total is the sum of those five, and the stored `risk_score`
    is that total clamped into the range from 0.00 to 100.00 and then rounded
    half up to two decimal places — rounded **once**, after clamping, never per
    addend."
    PRD 3.7: "The score is recomputed and persisted whenever the review is
    finalized, whenever a placement becomes active or is removed, and whenever
    the tool is suspended."
    PRD 3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension
    is `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score
    is below 40.00; `approved_version` is set to the tool's current
    `tool_version`."
    PRD 2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/rbac/shared_operations_are_reachable_by_every_role_that_declares_them
    """
    term = create_term(
        api, headers=registrar_headers, term_code="SHARE-2027-FA",
        term_start_at="2027-08-23T00:00:00Z", term_end_at="2027-12-10T00:00:00Z",
    )
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    professor = create_faculty(
        api, headers=registrar_headers, sis_person_id="SHARE-F-01",
        full_name="Rosa Delgado",
    )
    instructor = make_instructor_headers(professor["id"])

    shell_a = provisioning_decision(
        api,
        request_shell(
            api, term["id"], professor["id"], headers=lms_admin_headers,
            sis_section_code="SHARE-330-001", shell_type="OFFICIAL", base_seat_cap=30,
        )["id"],
        "APPROVE",
        headers=lms_admin_headers,
    )
    shell_b = provisioning_decision(
        api,
        request_shell(
            api, term["id"], professor["id"], headers=lms_admin_headers,
            sis_section_code="SHARE-330-002", shell_type="OFFICIAL", base_seat_cap=30,
        )["id"],
        "APPROVE",
        headers=lms_admin_headers,
    )
    assert shell_a["provisioning_state"] == "PROVISIONED"
    assert shell_b["provisioning_state"] == "PROVISIONED"
    assert shell_a["publish_readiness"] is True

    tool = register_tool(
        api, headers=lms_admin_headers, vendor_name="Verity",
        tool_name="Rubric Studio", tool_version="2.4.0", data_sharing_scope="NONE",
        pii_tier=0, vpat_score=90.00, wcag_level="AA",
    )
    tool = transition_tool(api, tool["id"], "OPEN_REVIEW", headers=lms_admin_headers)
    assert tool["approval_state"] == "UNDER_REVIEW"
    file_review(api, tool["id"], "PRIVACY", "CLEAR", headers=privacy_reviewer_headers)
    file_review(
        api, tool["id"], "ACCESSIBILITY", "CLEAR",
        headers=accessibility_reviewer_headers,
    )
    tool = transition_tool(api, tool["id"], "FINALIZE_REVIEW", headers=lms_admin_headers)
    assert tool["approval_state"] == "APPROVED"
    assert tool["risk_score"] == 3.00, (
        "0 PII + 0 scope for NONE + (100 - 90.00) * 0.30 + 0 for AA + 0 exposure "
        f"is 3.00, got {tool['risk_score']}"
    )
    assert tool["approved_version"] == "2.4.0"

    # ── POST /content-items is shared by the owning Instructor and the LmsAdmin ──
    item_by_instructor = create_content_item(
        api, shell_a["id"], headers=instructor, item_type="ASSIGNMENT",
        title="Lab 1", points_possible=25.00, storage_mb=4.00,
    )
    item_by_admin = create_content_item(
        api, shell_a["id"], headers=lms_admin_headers, item_type="PAGE",
        title="Accessibility statement", points_possible=0.00, storage_mb=1.00,
    )
    assert item_by_instructor["id"] != item_by_admin["id"]

    # ── publish and unpublish are shared in both directions ──
    published = publish(api, shell_a["id"], headers=instructor)
    assert published["provisioning_state"] == "PUBLISHED"
    assert published["content_item_count"] == 2

    unpublished = unpublish(
        api, shell_a["id"], reason="syllabus revision", headers=lms_admin_headers
    )
    assert unpublished["provisioning_state"] == "PROVISIONED"
    assert unpublished["unpublish_reason"] == "syllabus revision"

    republished = publish(api, shell_a["id"], headers=lms_admin_headers)
    assert republished["provisioning_state"] == "PUBLISHED", (
        "neither verb is reserved to the role that performed the other"
    )

    # ── placing a tool is shared, and the version is pinned only on activation ──
    placement_a = request_placement(
        api, tool["id"], shell_a["id"], headers=instructor
    )
    placement_b = request_placement(
        api, tool["id"], shell_b["id"], headers=lms_admin_headers
    )
    assert placement_a["placement_state"] == "REQUESTED"
    assert placement_b["placement_state"] == "REQUESTED"
    assert placement_a["pinned_tool_version"] is None
    assert placement_b["pinned_tool_version"] is None

    mid = read_shell(api, shell_a["id"], registrar_headers)
    assert mid["provisioning_state"] == "PUBLISHED"
    assert mid["blocked_placement_count"] == 0
    assert mid["publish_readiness"] is True, (
        "a merely REQUESTED placement blocks nothing, so the shell stays "
        "publish-ready and stays published"
    )

    # ── the transitions endpoint is shared ACROSS creators ──
    activated_a = transition_placement(
        api, placement_a["id"], "ACTIVATE", headers=lms_admin_headers
    )
    activated_b = transition_placement(
        api, placement_b["id"], "ACTIVATE", headers=instructor
    )
    assert activated_a["placement_state"] == "ACTIVE"
    assert activated_b["placement_state"] == "ACTIVE"
    assert activated_a["pinned_tool_version"] == "2.4.0"
    assert activated_b["pinned_tool_version"] == "2.4.0"

    rows, meta = validate_paginated(
        api.list_tool_placements(
            instructor, params={"tool_id": tool["id"], "placement_state": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 2
    assert [row["shell_id"] for row in rows] == [shell_a["id"], shell_b["id"]]

    tool_now = read_tool(api, tool["id"], instructor)
    assert tool_now["active_placement_count"] == 2
    assert tool_now["risk_score"] == 9.00, (
        "two active placements add min(15, 2 * 3) exposure points to the 3.00 "
        f"governance base, so the re-scored tool reads 9.00, got {tool_now['risk_score']}"
    )
    assert tool_now["approved_version"] == "2.4.0", (
        "re-scoring on activation must not touch the approved version"
    )

    # ── GET /tool-reviews is shared by the LmsAdmin and the reviewers only ──
    validate_error(
        api.list_tool_reviews(registrar_headers, params={"tool_id": tool["id"]}),
        "ERR_ROLE_NOT_PERMITTED",
    )
    rows, meta = validate_paginated(
        api.list_tool_reviews(lms_admin_headers, params={"tool_id": tool["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["dimension"] for row in rows] == ["PRIVACY", "ACCESSIBILITY"]

    end = read_shell(api, shell_a["id"], instructor)
    assert end["provisioning_state"] == "PUBLISHED"
    assert end["publish_readiness"] is True


def test_the_two_reviewer_roles_are_peers_with_disjoint_dimensions(
    api, lms_admin_headers, privacy_reviewer_headers, privacy_reviewer_alt_headers,
    accessibility_reviewer_headers,
):
    """Identical peers, disjoint dimensions, and neither verdict is sufficient alone.

    Both reviewer roles are listed on the same filing endpoint, so a cross-
    dimension attempt is refused on the strength of the body's `dimension`
    against the acting role. Downstream, one peer's verdict never finalizes the
    tool, and a single CONDITIONS verdict downgrades a tool whose score is far
    below the conditional threshold.

    PRD 2.1: "One further role rule is specific to tool review. The two reviewer
    roles have disjoint duties, so on `POST /tool-reviews` the `dimension` in the
    body must match the acting role: a `PrivacyReviewer` may file only `PRIVACY`
    and an `AccessibilityReviewer` only `ACCESSIBILITY`. A mismatch is a role
    failure, not a request-shape failure, and is rejected with
    `ERR_ROLE_NOT_PERMITTED`."
    PRD 2.10: "`X-User-Role` is one of the six declared roles and is authorized
    for the target endpoint; and on `POST /tool-reviews` the body's `dimension`
    matches the acting reviewer role — otherwise `ERR_ROLE_NOT_PERMITTED`.
    Applies to every endpoint."
    PRD 3.7: "A new tool opens with `approval_state` `DRAFT`,
    `privacy_review_state` `PENDING`, `accessibility_review_state` `PENDING`,
    `risk_score` null, `approved_version` null, `active_placement_count` 0 and
    `suspension_reason` null."
    PRD 3.7: "An `LmsAdmin` opens the review by an `action` of `OPEN_REVIEW`,
    which takes `approval_state` `DRAFT` → `UNDER_REVIEW` and requires both
    verdict dimensions to be `PENDING`."
    PRD 3.7: "A `CONDITIONS` decision must carry a non-empty `conditions_note`,
    otherwise `ERR_INVALID_REQUEST`."
    PRD 3.7: "Filing a review requires the tool's `approval_state` to be
    `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE_TRANSITION`) and requires that
    no review already exist for that tool in that same `dimension` (otherwise
    `ERR_REVIEW_DIMENSION_CONFLICT`); each dimension is decided exactly once per
    review round."
    PRD 3.7: "A `CLEAR` decision moves that dimension `PENDING` → `CLEARED`,
    `CONDITIONS` moves it `PENDING` → `CONDITIONAL`, and `BLOCK` moves it
    `PENDING` → `BLOCKED`."
    PRD 3.7: "All three branches first require both verdict dimensions to have
    left `PENDING`, otherwise `ERR_REVIEW_INCOMPLETE`, and all three recompute
    and persist `risk_score`."
    PRD 3.7: "The tool takes `UNDER_REVIEW` → `CONDITIONAL` when neither
    dimension is `BLOCKED` and either at least one dimension is `CONDITIONAL` or
    the score falls in the range from 40.00 up to but not including 70.00;
    `approved_version` is likewise set to the current `tool_version`, and a
    conditional tool may still be placed."
    PRD 3.7: "The PII points are the `pii_tier` multiplied by 10, so 0 through
    30."
    PRD 3.7: "The scope points are 0 for `NONE`, 10 for `ROSTER_ONLY`, 25 for
    `ROSTER_AND_GRADES` and 40 for `FULL_PROFILE`."
    PRD 3.7: "The accessibility-gap points are 100 minus the `vpat_score`,
    multiplied by 0.30."
    PRD 3.7: "The exposure points are the `active_placement_count` multiplied by
    3, capped at 15."
    PRD 3.7: "The raw total is the sum of those five, and the stored `risk_score`
    is that total clamped into the range from 0.00 to 100.00 and then rounded
    half up to two decimal places — rounded **once**, after clamping, never per
    addend."
    PRD 2.1: "The server records it where a transition says so — as
    `submitted_by_user_id` and `decided_by_user_id` on a `MergeRequest`, and as
    `reviewer_user_id` on a `ToolReview` — and compares it to other recorded
    operator identifiers for segregation-of-duties purposes, but never compares
    it to any entity's `id`."
    PRD 2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/rbac/the_two_reviewer_roles_are_peers_with_disjoint_dimensions
    """
    tool = register_tool(
        api, headers=lms_admin_headers, vendor_name="Northwind",
        tool_name="Peer Review Hub", tool_version="5.2.1",
        data_sharing_scope="ROSTER_ONLY", pii_tier=1, vpat_score=95.00,
        wcag_level="AA",
    )
    assert tool["privacy_review_state"] == "PENDING"
    assert tool["accessibility_review_state"] == "PENDING"
    tool = transition_tool(api, tool["id"], "OPEN_REVIEW", headers=lms_admin_headers)
    assert tool["approval_state"] == "UNDER_REVIEW"

    # ── neither peer may act in the other's dimension ──
    validate_error(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "ACCESSIBILITY", "CLEAR"),
            privacy_reviewer_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            accessibility_reviewer_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    # ── CONDITIONS without a note is a request-shape failure, so nothing moved ──
    validate_error(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "PRIVACY", "CONDITIONS"),
            privacy_reviewer_headers,
        ),
        "ERR_INVALID_REQUEST",
    )
    assert read_tool(api, tool["id"], lms_admin_headers)["privacy_review_state"] == "PENDING"

    privacy_review = file_review(
        api, tool["id"], "PRIVACY", "CONDITIONS", headers=privacy_reviewer_headers,
        conditions_note="vendor must disable analytics beacons",
    )
    assert privacy_review["dimension"] == "PRIVACY"
    assert privacy_review["decision"] == "CONDITIONS"
    assert privacy_review["reviewer_user_id"] == PRIVACY_REVIEWER_USER_ID

    # ── a second, different PrivacyReviewer is refused on the dimension, not
    #    on their identity ──
    validate_error(
        api.create_tool_review(
            create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            privacy_reviewer_alt_headers,
        ),
        "ERR_REVIEW_DIMENSION_CONFLICT",
    )

    # ── one peer's verdict is never enough to finalize ──
    validate_error(
        api.tool_integration_transition(
            tool["id"], {"action": "FINALIZE_REVIEW"}, lms_admin_headers
        ),
        "ERR_REVIEW_INCOMPLETE",
    )
    mid = read_tool(api, tool["id"], privacy_reviewer_headers)
    assert mid["privacy_review_state"] == "CONDITIONAL"
    assert mid["accessibility_review_state"] == "PENDING"
    assert mid["approval_state"] == "UNDER_REVIEW"

    accessibility_review = file_review(
        api, tool["id"], "ACCESSIBILITY", "CLEAR",
        headers=accessibility_reviewer_headers,
    )
    assert accessibility_review["dimension"] == "ACCESSIBILITY"
    assert accessibility_review["reviewer_user_id"] == ACCESSIBILITY_REVIEWER_USER_ID

    finalized = transition_tool(
        api, tool["id"], "FINALIZE_REVIEW", headers=lms_admin_headers
    )
    assert finalized["risk_score"] == 21.50, (
        "1 * 10 PII + 10 for ROSTER_ONLY + (100 - 95.00) * 0.30 + 0 for AA + 0 "
        f"exposure is 21.50, got {finalized['risk_score']}"
    )
    assert finalized["approval_state"] == "CONDITIONAL", (
        "21.50 is below the 40.00 threshold, so the conditional outcome comes "
        "purely from the privacy peer's CONDITIONS verdict"
    )
    assert finalized["approved_version"] == "5.2.1"

    # ── the peers read each other's work ──
    rows, meta = validate_paginated(
        api.list_tool_reviews(
            accessibility_reviewer_headers, params={"tool_id": tool["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert [row["reviewer_user_id"] for row in rows] == [
        PRIVACY_REVIEWER_USER_ID, ACCESSIBILITY_REVIEWER_USER_ID,
    ]
    own = get_success_data(
        api.get_tool_review(privacy_review["id"], privacy_reviewer_headers)
    )
    assert own["dimension"] == "PRIVACY"
    assert own["conditions_note"] == "vendor must disable analytics beacons"


def test_merge_approval_requires_a_different_admin_than_the_submitter(
    api, registrar_headers, lms_admin_headers, lms_admin_alt_headers,
):
    """Two holders of one role, separated on exactly the two decision edges.

    The admin who opened the merge request may still SUBMIT it and, once someone
    else has approved it, may APPLY it - only APPROVE and DECLINE are gated, and
    the byte-identical APPROVE from the second admin succeeds.

    PRD 2.9: "Three duty pairs must be performed by different people, and each is
    enforced by comparing `X-User-ID` values rather than roles."
    PRD 2.9: "The `LmsAdmin` whose `X-User-ID` created a merge request may not be
    the `X-User-ID` that approves or declines it."
    PRD 2.10: "Segregation of duties as described in §2.9, on `POST
    /merge-requests/{id}/transitions` with action `APPROVE` or `DECLINE`, on
    `POST /tool-reviews`, and on `POST /grade-passbacks/{id}/registrar-decisions`
    — otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.5: "The request opens in `merge_state` `DRAFT` with
    `submitted_by_user_id` recorded from the acting user, `decided_by_user_id`
    null, both relocation tallies at zero, and both seat-ledger readings null."
    PRD 3.5: "**Submitting** (`SUBMIT`) requires both the parent and the child
    shell to be `PROVISIONED` or `PUBLISHED`, otherwise
    `ERR_INVALID_STATE_TRANSITION`."
    PRD 3.5: "**Approving** (`APPROVE`) is the segregation-of-duties gate: the
    acting user must not be the `submitted_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.5: "Approving records `decided_by_user_id` from the acting user and
    arms the apply step."
    PRD 3.5: "**Declining** (`DECLINE`) shares the same segregation-of-duties
    gate and also records `decided_by_user_id`, but it is terminal and touches no
    shell and no enrollment at all: the two branches of the decision fork differ
    only in the action word, and one arms a relocation while the other leaves the
    world exactly as it found it."
    PRD 3.5: "It first records `seat_ledger_before` as the term's
    `total_active_enrollments` read immediately before any mutation."
    PRD 3.5: "Finally `seat_ledger_after` records the term's
    `total_active_enrollments` after the relocation, and the seat ledger requires
    that it equal `seat_ledger_before` exactly — a merge moves students between
    shells and never changes how many of them the term is carrying."
    PRD 3.5: "The parent's `active_enrollment_count`, `seat_utilization_pct` and
    `overflow_flag` are re-derived and its `absorbed_child_count` rises by one."
    PRD 2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer
    that starts at 1 on creation and increments by exactly one on every mutation
    of that record."

    Design: Corner/rbac/merge_approval_requires_a_different_admin_than_the_submitter
    """
    term = create_term(
        api, headers=registrar_headers, term_code="SOD-2027-SP",
        term_start_at="2027-01-11T00:00:00Z", term_end_at="2027-05-14T00:00:00Z",
    )
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    professor = create_faculty(
        api, headers=registrar_headers, sis_person_id="SOD-F-01", full_name="Grace Bell",
    )
    student = create_student(
        api, headers=registrar_headers, sis_person_id="SOD-S-01", full_name="Nia Roberts",
    )
    parent = provisioning_decision(
        api,
        request_shell(
            api, term["id"], professor["id"], headers=lms_admin_headers,
            sis_section_code="SOD-140-001", shell_type="OFFICIAL", base_seat_cap=12,
        )["id"],
        "APPROVE",
        headers=lms_admin_headers,
    )
    child = provisioning_decision(
        api,
        request_shell(
            api, term["id"], professor["id"], headers=lms_admin_headers,
            sis_section_code="SOD-140-002", shell_type="OFFICIAL", base_seat_cap=12,
        )["id"],
        "APPROVE",
        headers=lms_admin_headers,
    )
    assert parent["provisioning_state"] == "PROVISIONED"
    assert child["provisioning_state"] == "PROVISIONED"
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(child["id"], student["id"], role="STUDENT"),
            registrar_headers,
        )
    )
    assert enrollment["enrollment_state"] == "ACTIVE"

    parent = read_shell(api, parent["id"], lms_admin_headers)
    assert parent["version"] == 2, (
        "the parent shell has been created and then decided upon, two mutations, "
        f"so its version reads 2, got {parent['version']}"
    )

    merge = open_merge_request(
        api, parent, child["id"], headers=lms_admin_headers,
        justification="cross-listed with the honors section",
    )
    assert merge["merge_state"] == "DRAFT"
    assert merge["submitted_by_user_id"] == LMS_ADMIN_USER_ID
    assert merge["decided_by_user_id"] is None

    submitted = transition_merge_request(
        api, merge["id"], "SUBMIT", headers=lms_admin_headers
    )
    assert submitted["merge_state"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == LMS_ADMIN_USER_ID, (
        "the submitter may perform SUBMIT itself: the gate is not 'the creator "
        "touches nothing again'"
    )

    # ── both decision edges are gated against the submitter ──
    validate_error(
        api.merge_request_transition(
            merge["id"], {"action": "APPROVE"}, lms_admin_headers
        ),
        "ERR_SEGREGATION_OF_DUTIES",
    )
    validate_error(
        api.merge_request_transition(
            merge["id"], {"action": "DECLINE", "reason": "changed my mind"},
            lms_admin_headers,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
    )
    mid = read_merge_request(api, merge["id"], registrar_headers)
    assert mid["merge_state"] == "SUBMITTED"
    assert mid["decided_by_user_id"] is None, "neither refusal recorded a decider"

    # ── the byte-identical APPROVE from the second admin succeeds ──
    approved = transition_merge_request(
        api, merge["id"], "APPROVE", headers=lms_admin_alt_headers
    )
    assert approved["merge_state"] == "APPROVED"
    assert approved["decided_by_user_id"] == LMS_ADMIN_ALT_USER_ID

    # ── APPLY sits outside the gate, so the original submitter may drive it ──
    applied = transition_merge_request(
        api, merge["id"], "APPLY", headers=lms_admin_headers
    )
    assert applied["merge_state"] == "APPLIED"
    assert applied["moved_enrollment_count"] == 1
    assert applied["seat_ledger_before"] == 1
    assert applied["seat_ledger_after"] == 1

    assert read_shell(api, child["id"], lms_admin_headers)["provisioning_state"] == "MERGED"
    parent_end = read_shell(api, parent["id"], lms_admin_headers)
    assert parent_end["active_enrollment_count"] == 1
    assert parent_end["absorbed_child_count"] == 1
