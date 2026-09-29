"""Cross-cutting layers: optimistic concurrency on a parent row, and soft delete.

Three creates in this service carry an expected-version token for a *parent*
record rather than for the row being created, and one terminal shell transition
is a soft delete rather than an erasure. Every test below drives the published
endpoints over HTTP against a freshly relaunched server whose logical clock
reads 2026-08-01T00:00:00Z, and builds all of its own preconditions.
"""
from datetime import datetime, timezone

from test_helpers import (
    advance_clock,
    create_content_item,
    create_continuity_window_payload,
    create_faculty,
    create_merge_request_payload,
    create_rollover_job_payload,
    create_student,
    create_term,
    enrol,
    get_success_data,
    make_instructor_headers,
    provisioning_decision,
    publish,
    read_content_item,
    read_person,
    read_shell,
    read_term,
    request_shell,
    transition_rollover_job,
    transition_shell,
    transition_term,
    unpublish,
    validate_error,
    validate_paginated,
)


def _instant(value):
    """Parse a wire timestamp so two spellings of the same instant compare equal."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_merge_request_creation_is_guarded_by_the_parent_shells_stored_version(
    api, registrar_headers, lms_admin_headers
):
    """The cross-list create is guarded on the parent shell's stored version.

    The guard sits on the parent `CourseShell`, not on the request being created
    and not on the child: an off-by-one token is refused with 412, the very same
    literal goes stale the instant the parent is written again, and a second
    request for the same pair is perfectly legal once the client re-reads.

    PRD §2.7: "`POST /merge-requests` requires `expected_parent_shell_version` as a non-optional input field, carrying the client's last observed `version` of the parent `CourseShell` named by `parent_shell_id`. If it does not equal that shell's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create increments the parent shell's `version` by one, so a superseding request must re-read the parent shell first."
    PRD §2.10: "12. `expected_parent_shell_version`, `expected_target_shell_version` or `expected_term_version` matches the referenced parent's current `version`, on `POST /merge-requests`, `POST /rollover-jobs` and `POST /continuity-windows` — otherwise `ERR_STALE_VERSION`."
    PRD §2.10: "When several rules could reject the same request, exactly one of them decides the response, and the order is fixed."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same timestamp format, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly one on every mutation of that record."
    PRD §3.5: "The request opens in `merge_state` `DRAFT` with `submitted_by_user_id` recorded from the acting user, `decided_by_user_id` null, both relocation tallies at zero, and both seat-ledger readings null."
    PRD §3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and increments the term's `published_shell_count` by one."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."
    PRD §2.3: "Filter values are also the state fields themselves, so a caller can ask for one lifecycle stage at a time."

    Design: Corner/cross_cutting_complexity_layers/merge_request_creation_is_guarded_by_the_parent_shells_stored_version
    """
    term = create_term(
        api, registrar_headers,
        term_code="OCC-2027-SP",
        term_start_at="2027-01-11T00:00:00Z",
        term_end_at="2027-05-14T00:00:00Z",
    )
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    assert term["lifecycle_state"] == "REGISTRATION_OPEN"

    professor = create_faculty(
        api, registrar_headers, sis_person_id="OCC-F-01", full_name="Ida Tarbell"
    )

    parent = request_shell(
        api, term["id"], professor["id"], lms_admin_headers,
        sis_section_code="OCC-250-001", shell_type="OFFICIAL", base_seat_cap=18,
    )
    assert parent["version"] == 1, "a freshly created record starts at version 1"
    parent = provisioning_decision(api, parent["id"], "APPROVE", lms_admin_headers)
    assert parent["provisioning_state"] == "PROVISIONED"

    child = request_shell(
        api, term["id"], professor["id"], lms_admin_headers,
        sis_section_code="OCC-250-002", shell_type="OFFICIAL", base_seat_cap=18,
    )
    child = provisioning_decision(api, child["id"], "APPROVE", lms_admin_headers)
    assert child["provisioning_state"] == "PROVISIONED"

    observed_version = read_shell(api, parent["id"], lms_admin_headers)["version"]
    assert observed_version > 1, "the provisioning decision mutated the parent shell"

    # An off-by-one token loses, and it loses on the version rather than on any
    # of the merge-pair rules: the pair itself is entirely legal here.
    stale = api.create_merge_request(
        create_merge_request_payload(
            parent["id"], child["id"], observed_version - 1,
            justification="stale read of the parent",
        ),
        lms_admin_headers,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    rows, meta = validate_paginated(
        api.list_merge_requests(lms_admin_headers, {"parent_shell_id": parent["id"]})
    )
    assert meta["total_count"] == 0, "a refused create must not have written a row"
    assert rows == []

    first = get_success_data(
        api.create_merge_request(
            create_merge_request_payload(
                parent["id"], child["id"], observed_version,
                justification="first cross-list request",
            ),
            lms_admin_headers,
        )
    )
    assert first["merge_state"] == "DRAFT"
    assert first["parent_shell_id"] == parent["id"]
    assert first["child_shell_id"] == child["id"]
    assert first["justification"] == "first cross-list request"
    assert first["decided_by_user_id"] is None
    assert first["moved_enrollment_count"] == 0
    assert first["reversed_enrollment_count"] == 0
    assert first["seat_ledger_before"] is None
    assert first["seat_ledger_after"] is None

    # The accepted create is itself a write to the guarded parent.
    parent_after_create = read_shell(api, parent["id"], lms_admin_headers)
    assert parent_after_create["version"] == observed_version + 1, (
        "a successful merge-request create increments the parent shell's version "
        f"by one: expected {observed_version + 1}, got "
        f"{parent_after_create['version']}"
    )
    assert parent_after_create["provisioning_state"] == "PROVISIONED"

    published = publish(api, parent["id"], lms_admin_headers)
    assert published["provisioning_state"] == "PUBLISHED"
    assert published["version"] > parent_after_create["version"], (
        "publishing the parent is another mutation of the guarded record"
    )

    # Byte-identical to the body that just succeeded, and now refused.
    replay = api.create_merge_request(
        create_merge_request_payload(
            parent["id"], child["id"], observed_version,
            justification="second request on a stale view",
        ),
        lms_admin_headers,
    )
    validate_error(replay, "ERR_STALE_VERSION", 412)

    live_version = read_shell(api, parent["id"], lms_admin_headers)["version"]
    second = get_success_data(
        api.create_merge_request(
            create_merge_request_payload(
                parent["id"], child["id"], live_version,
                justification="second request on a fresh view",
            ),
            lms_admin_headers,
        )
    )
    assert second["merge_state"] == "DRAFT"
    assert second["id"] != first["id"], (
        "two live DRAFT requests for the same pair are legal once the client "
        "re-reads the parent"
    )
    assert read_shell(api, parent["id"], lms_admin_headers)["version"] == (
        live_version + 1
    )

    rows, meta = validate_paginated(
        api.list_merge_requests(
            registrar_headers,
            {"parent_shell_id": parent["id"], "merge_state": "DRAFT"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert [row["justification"] for row in rows] == [
        "first cross-list request",
        "second request on a fresh view",
    ]


def test_rollover_job_creation_is_guarded_by_the_target_shells_stored_version(
    api, registrar_headers, lms_admin_headers
):
    """The rollover create is guarded on the target shell's stored version.

    A publish-and-unpublish round trip on the target returns it to a state that
    satisfies every business precondition for a rollover while leaving its
    version advanced, so the stale replay can only be explained by the version
    guard — never by the target's eligibility.

    PRD §2.7: "`POST /rollover-jobs` requires `expected_target_shell_version` as a non-optional input field, carrying the client's last observed `version` of the target `CourseShell` named by `target_shell_id`. A mismatch with that shell's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create increments the target shell's `version` by one."
    PRD §2.10: "12. `expected_parent_shell_version`, `expected_target_shell_version` or `expected_term_version` matches the referenced parent's current `version`, on `POST /merge-requests`, `POST /rollover-jobs` and `POST /continuity-windows` — otherwise `ERR_STALE_VERSION`."
    PRD §2.10: "34. A rollover job's target shell has a `provisioning_state` of `REQUESTED` or `PROVISIONED`, a `content_item_count` of 0, and no enrollments, on `POST /rollover-jobs` and on `POST /rollover-jobs/{id}/transitions` with action `VALIDATE` — otherwise `ERR_ROLLOVER_TARGET_NOT_EMPTY`."
    PRD §2.10: "When several rules could reject the same request, exactly one of them decides the response, and the order is fixed."
    PRD §3.6: "An `LmsAdmin` stages one by naming `source_shell_id`, `target_shell_id` and `target_term_id`, supplying the mandatory `expected_target_shell_version`, and optionally overriding four switches: `strip_dates` (default true), `strip_submissions` (default true), `strip_grades` (default true) and `date_shift_mode` (default `ANCHOR_PROPORTIONAL`, the alternative being `FIXED_OFFSET`)."
    PRD §3.6: "The job opens in `job_state` `DRAFT` with every tally at zero."
    PRD §3.6: "Validation sets `eligible_item_count` to the number of the source shell's items whose `copy_state` is not `SKIPPED`, and copies nothing."
    PRD §3.3: "When an operator drives it, an optional `reason` is recorded into `unpublish_reason` and the posture gate applies exactly as it does for publishing, so unpublishing during `CONTINUITY_MODE` is refused with `ERR_TERM_POSTURE_FROZEN`."
    PRD §3.3: "Either form decrements the term's `published_shell_count` by one, and a shell may cycle between `PROVISIONED` and `PUBLISHED` any number of times."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/cross_cutting_complexity_layers/rollover_job_creation_is_guarded_by_the_target_shells_stored_version
    """
    source_term = create_term(
        api, registrar_headers,
        term_code="OCC-2026-FA",
        term_start_at="2026-08-24T00:00:00Z",
        term_end_at="2026-12-11T00:00:00Z",
    )
    source_term = transition_term(
        api, source_term["id"], "REGISTRATION_OPEN", registrar_headers
    )
    target_term = create_term(
        api, registrar_headers,
        term_code="OCC-2027-FA",
        term_start_at="2027-08-23T00:00:00Z",
        term_end_at="2027-12-10T00:00:00Z",
    )
    target_term = transition_term(
        api, target_term["id"], "REGISTRATION_OPEN", registrar_headers
    )
    assert source_term["lifecycle_state"] == "REGISTRATION_OPEN"
    assert target_term["lifecycle_state"] == "REGISTRATION_OPEN"

    professor = create_faculty(
        api, registrar_headers,
        sis_person_id="OCC-F-02", full_name="Chien-Shiung Wu",
    )
    owner_headers = make_instructor_headers(professor["id"])

    source = request_shell(
        api, source_term["id"], professor["id"], lms_admin_headers,
        sis_section_code="OCC-360-001", shell_type="OFFICIAL", base_seat_cap=20,
    )
    source = provisioning_decision(api, source["id"], "APPROVE", lms_admin_headers)
    assert source["provisioning_state"] == "PROVISIONED"
    item = create_content_item(
        api, source["id"], owner_headers,
        item_type="ASSIGNMENT", title="Legacy essay",
        due_at="2026-10-05T23:59:00Z", points_possible=50.00, storage_mb=8.00,
    )
    assert item["copy_state"] == "SOURCE"
    source = transition_shell(api, source["id"], "CONCLUDED", registrar_headers)
    assert source["provisioning_state"] == "CONCLUDED"

    target = request_shell(
        api, target_term["id"], professor["id"], lms_admin_headers,
        sis_section_code="OCC-360-001", shell_type="OFFICIAL", base_seat_cap=20,
    )
    target = provisioning_decision(api, target["id"], "APPROVE", lms_admin_headers)
    assert target["provisioning_state"] == "PROVISIONED"
    assert target["content_item_count"] == 0
    observed_version = target["version"]

    stale = api.create_rollover_job(
        create_rollover_job_payload(
            source["id"], target["id"], target_term["id"], observed_version - 1
        ),
        lms_admin_headers,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    rows, meta = validate_paginated(
        api.list_rollover_jobs(lms_admin_headers, {"target_shell_id": target["id"]})
    )
    assert meta["total_count"] == 0, "the refused create left no job behind"
    assert rows == []

    first = get_success_data(
        api.create_rollover_job(
            create_rollover_job_payload(
                source["id"], target["id"], target_term["id"], observed_version
            ),
            lms_admin_headers,
        )
    )
    assert first["job_state"] == "DRAFT"
    assert first["strip_dates"] is True
    assert first["strip_submissions"] is True
    assert first["strip_grades"] is True
    assert first["date_shift_mode"] == "ANCHOR_PROPORTIONAL"
    for tally in (
        "eligible_item_count", "copied_item_count", "skipped_item_count",
        "date_stripped_count", "date_shifted_count",
    ):
        assert first[tally] == 0, f"a DRAFT job opens with {tally} at zero"
    assert first["copied_storage_mb"] == 0.00

    after_create = read_shell(api, target["id"], lms_admin_headers)
    assert after_create["version"] == observed_version + 1, (
        "a successful rollover create increments the target shell's version by "
        f"one: expected {observed_version + 1}, got {after_create['version']}"
    )

    # A full publish/unpublish round trip: every business precondition for a
    # rollover target is restored, yet the guarded field has moved on.
    published = publish(api, target["id"], lms_admin_headers)
    assert published["provisioning_state"] == "PUBLISHED"
    unpublished = unpublish(
        api, target["id"], reason="rollover pending", headers=lms_admin_headers
    )
    assert unpublished["provisioning_state"] == "PROVISIONED"
    assert unpublished["unpublish_reason"] == "rollover pending"
    assert unpublished["content_item_count"] == 0
    assert unpublished["version"] > published["version"] > after_create["version"]

    replay = api.create_rollover_job(
        create_rollover_job_payload(
            source["id"], target["id"], target_term["id"], observed_version
        ),
        lms_admin_headers,
    )
    validate_error(replay, "ERR_STALE_VERSION", 412)

    live_version = read_shell(api, target["id"], lms_admin_headers)["version"]
    second = get_success_data(
        api.create_rollover_job(
            create_rollover_job_payload(
                source["id"], target["id"], target_term["id"], live_version,
                strip_dates=False,
            ),
            lms_admin_headers,
        )
    )
    assert second["job_state"] == "DRAFT"
    assert second["strip_dates"] is False
    assert second["id"] != first["id"]

    validated = transition_rollover_job(
        api, second["id"], "VALIDATE", lms_admin_headers
    )
    assert validated["job_state"] == "VALIDATED"
    assert validated["eligible_item_count"] == 1, (
        "the source shell holds exactly one item whose copy_state is not SKIPPED"
    )
    assert validated["copied_item_count"] == 0, "validation copies nothing"
    assert validated["copied_storage_mb"] == 0.00
    assert read_shell(api, target["id"], lms_admin_headers)["content_item_count"] == 0

    owner_rows, owner_meta = validate_paginated(
        api.list_rollover_jobs(owner_headers, {"target_shell_id": target["id"]})
    )
    assert owner_meta["total_count"] == 2
    assert [row["id"] for row in owner_rows] == [first["id"], second["id"]]
    assert owner_rows[0]["job_state"] == "DRAFT", (
        "the untouched first job sorts first under created_at ascending"
    )
    assert owner_rows[1]["job_state"] == "VALIDATED"


def test_continuity_window_creation_is_guarded_by_the_terms_stored_version(
    api, registrar_headers, lms_admin_headers
):
    """Opening a window is guarded on the term's version, which it then consumes.

    This is the one guard whose own success invalidates the caller's token: the
    accepted create advances the very field it compared against, so replaying a
    body that just worked is refused, and the guard is read off the term even
    when the window names a shell.

    PRD §2.7: "`POST /continuity-windows` requires `expected_term_version` as a non-optional input field, carrying the client's last observed `version` of the `AcademicTerm` named by `term_id`. A mismatch with the term's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create increments the term's `version` by one, so a superseding window must re-read the term."
    PRD §2.10: "12. `expected_parent_shell_version`, `expected_target_shell_version` or `expected_term_version` matches the referenced parent's current `version`, on `POST /merge-requests`, `POST /rollover-jobs` and `POST /continuity-windows` — otherwise `ERR_STALE_VERSION`."
    PRD §3.9: "An `LmsAdmin` opens one by naming `term_id`, a `kind` of `OUTAGE`, `EXTENSION` or `MAINTENANCE`, a `window_start`, a `window_end` and the mandatory `expected_term_version`, optionally narrowing the window to a single shell with `shell_id`."
    PRD §3.9: "The `expected_term_version` must match the term's current `version`, otherwise `ERR_STALE_VERSION`: an operator opens a window against a posture and an enrollment picture they have just read, and because a superseding window is perfectly legitimate, only the term's version can tell them the picture moved underneath them."
    PRD §3.9: "Creating a window increments the **term's** `version` by one, which is what makes two clients racing to open windows against the same term visible to each other."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the shell's `active_enrollment_count` for a shell-scoped window, or the term's `total_active_enrollments` for a term-wide one — and, for a window whose `kind` is `EXTENSION`, records `extension_days_granted` as the window's length in seconds divided by 86,400 and rounded **up** to a whole day, so that any partial day counts as a full granted day; every other kind records 0."
    PRD §3.9: "Counting the new window itself, no more than two open outage windows of one term may cover any single instant."
    PRD §3.9: "The first is a per-shell exclusion. When `shell_id` is present, no other window with the same `shell_id`, the same `kind` and `window_state` `OPEN` may intersect the new interval **half-open**, treating the interval as including its start and excluding its end; a collision is refused with `ERR_WINDOW_OVERLAP`."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is `STUDENT` the shell's `active_enrollment_count` and the term's `total_active_enrollments` each rise by one, and the shell's `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."
    PRD §2.3: "Filter values are also the state fields themselves, so a caller can ask for one lifecycle stage at a time."

    Design: Corner/cross_cutting_complexity_layers/continuity_window_creation_is_guarded_by_the_terms_stored_version
    """
    term = create_term(
        api, registrar_headers,
        term_code="OCC-2027-SU",
        term_start_at="2027-06-01T00:00:00Z",
        term_end_at="2027-08-06T00:00:00Z",
    )
    assert term["version"] == 1
    transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)

    professor = create_faculty(
        api, registrar_headers, sis_person_id="OCC-F-03", full_name="Barbara Liskov"
    )
    student = create_student(
        api, registrar_headers, sis_person_id="OCC-S-03", full_name="Omar Haddad"
    )

    shell = request_shell(
        api, term["id"], professor["id"], lms_admin_headers,
        sis_section_code="OCC-410-001", shell_type="OFFICIAL", base_seat_cap=10,
    )
    shell = provisioning_decision(api, shell["id"], "APPROVE", lms_admin_headers)
    assert shell["provisioning_state"] == "PROVISIONED"

    enrollment = enrol(
        api, shell["id"], student["id"], "ACTIVE", headers=registrar_headers
    )
    assert enrollment["enrollment_state"] == "ACTIVE"
    assert read_shell(api, shell["id"], lms_admin_headers)["active_enrollment_count"] == 1

    term = transition_term(api, term["id"], "IN_SESSION", registrar_headers)
    assert term["lifecycle_state"] == "IN_SESSION"
    assert term["continuity_posture"] == "NORMAL"
    assert term["total_active_enrollments"] == 1

    observed_version = read_term(api, term["id"], registrar_headers)["version"]

    # The interval, the kind and the posture are all legal here, so only the
    # version can explain the refusal.
    stale = api.create_continuity_window(
        create_continuity_window_payload(
            term["id"], "OUTAGE",
            "2027-07-06T00:00:00Z", "2027-07-08T00:00:00Z",
            observed_version - 1,
        ),
        lms_admin_headers,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    first = get_success_data(
        api.create_continuity_window(
            create_continuity_window_payload(
                term["id"], "OUTAGE",
                "2027-07-06T00:00:00Z", "2027-07-08T00:00:00Z",
                observed_version,
            ),
            lms_admin_headers,
        )
    )
    assert first["window_state"] == "OPEN"
    assert first["kind"] == "OUTAGE"
    assert first.get("shell_id") is None, "a window with no shell_id is term-wide"
    assert first["affected_enrollment_count"] == 1, (
        "a term-wide window snapshots the term's total_active_enrollments"
    )
    assert first["extension_days_granted"] == 0, (
        "every kind other than EXTENSION records 0 granted days"
    )

    mid_term = read_term(api, term["id"], lms_admin_headers)
    assert mid_term["version"] == observed_version + 1, (
        "creating a window increments the term's version by exactly one: expected "
        f"{observed_version + 1}, got {mid_term['version']}"
    )
    assert mid_term["lifecycle_state"] == "IN_SESSION", (
        "the window create touches neither state dimension of the term"
    )
    assert mid_term["continuity_posture"] == "NORMAL"

    # The client's own success consumed the token it was holding.
    self_stale = api.create_continuity_window(
        create_continuity_window_payload(
            term["id"], "OUTAGE",
            "2027-07-20T00:00:00Z", "2027-07-21T00:00:00Z",
            observed_version,
        ),
        lms_admin_headers,
    )
    validate_error(self_stale, "ERR_STALE_VERSION", 412)

    second = get_success_data(
        api.create_continuity_window(
            create_continuity_window_payload(
                term["id"], "OUTAGE",
                "2027-07-20T00:00:00Z", "2027-07-21T00:00:00Z",
                observed_version + 1,
            ),
            lms_admin_headers,
        )
    )
    assert second["window_state"] == "OPEN"
    assert second["affected_enrollment_count"] == 1
    assert read_term(api, term["id"], lms_admin_headers)["version"] == (
        observed_version + 2
    ), "every accepted window advances the term by exactly one"

    # A shell-scoped window still reads the guard off the term.
    shell_stale = api.create_continuity_window(
        create_continuity_window_payload(
            term["id"], "MAINTENANCE",
            "2027-07-06T00:00:00Z", "2027-07-07T00:00:00Z",
            observed_version + 1,
            shell_id=shell["id"],
        ),
        lms_admin_headers,
    )
    validate_error(shell_stale, "ERR_STALE_VERSION", 412)

    third = get_success_data(
        api.create_continuity_window(
            create_continuity_window_payload(
                term["id"], "MAINTENANCE",
                "2027-07-06T00:00:00Z", "2027-07-07T00:00:00Z",
                observed_version + 2,
                shell_id=shell["id"],
            ),
            lms_admin_headers,
        )
    )
    assert third["kind"] == "MAINTENANCE"
    assert third["shell_id"] == shell["id"]
    assert third["window_state"] == "OPEN", (
        "the per-shell exclusion is scoped to one shell_id and one kind, so this "
        "window may sit inside the term-wide outage"
    )
    assert third["affected_enrollment_count"] == 1, (
        "a shell-scoped window snapshots the shell's active_enrollment_count"
    )
    assert third["extension_days_granted"] == 0
    assert read_term(api, term["id"], lms_admin_headers)["version"] == (
        observed_version + 3
    )

    rows, meta = validate_paginated(
        api.list_continuity_windows(
            registrar_headers, {"term_id": term["id"], "window_state": "OPEN"}
        )
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]
    assert [row["kind"] for row in rows] == ["OUTAGE", "OUTAGE", "MAINTENANCE"]


def test_purged_shells_stay_readable_by_id_but_drop_out_of_the_default_listing(
    api, registrar_headers, lms_admin_headers
):
    """Purging a shell is a soft delete with three separable consequences.

    The row and its content items survive and stay readable by identifier, the
    shell vanishes from the collection unless a caller explicitly asks for the
    purged state, and the shell leaves the chargeback input set so its owner's
    bill drops.

    PRD §3.3: "Purging sets every content item of the shell to `copy_state` `SKIPPED` with `storage_mb` 0.00, sets the shell's own `content_item_count` to 0, its `total_points_possible` to 0.00 and its `storage_mb` to 0.00, and recomputes the owner's `sandbox_storage_charge_usd`."
    PRD §3.3: "A purged shell is soft-deleted rather than erased: it disappears from shell listings unless the caller explicitly filters on a `provisioning_state` of `PURGED`, in which case it is returned as normal, and it remains readable by identifier."
    PRD §3.3: "Second, the logical clock must have reached or passed the term's `retention_purge_at`; an early attempt is refused with `ERR_PURGE_NOT_DUE`."
    PRD §3.3: "`CONCLUDED` → `ARCHIVED` requires the shell's term to have reached `CLOSED` or `ARCHIVED` (`ERR_INVALID_STATE_TRANSITION`)."
    PRD §3.3: "The billable set is that person's shells whose `shell_type` is `SANDBOX` or `DEV` and whose `provisioning_state` is neither `REJECTED` nor `PURGED`; `OFFICIAL` shells are never charged."
    PRD §3.3: "For each shell, subtract a free allowance of 100.00 megabytes from its `storage_mb` and treat any negative result as zero; multiply the remainder by a rate of 0.0150 US dollars per megabyte; multiply again by the class multiplier, which is 1.00 for a `SANDBOX` shell and 0.50 for a `DEV` shell; then round that single shell's charge half up to two decimal places."
    PRD §3.3: "The person's total is the sum of those already-rounded per-shell charges."
    PRD §3.3: "A person's `sandbox_storage_charge_usd` starts at 0.00 and is only ever written by the chargeback computation described later in this subsection."
    PRD §3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`, `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty days after the term's `term_end_at` for a `SANDBOX` or `DEV` shell while remaining null for an `OFFICIAL` one."
    PRD §3.6: "Creating, editing or removing an item re-derives the owning shell's `storage_mb` (the sum of its items' `storage_mb`), its `content_item_count` (the number of its items whose `copy_state` is not `SKIPPED`) and its `total_points_possible` (the sum of `points_possible` over its `ASSIGNMENT` and `QUIZ` items whose `copy_state` is not `SKIPPED`), and re-derives the shell owner's `sandbox_storage_charge_usd` for `SANDBOX` and `DEV` shells."
    PRD §3.2: "Hop one: every shell of the term whose `provisioning_state` is `PROVISIONED` or `PUBLISHED` and whose `merged_into_shell_id` is null transitions to `CONCLUDED`, processed in `created_at` ascending order."
    PRD §3.1: "First, take the calendar date reached by advancing `term_end_at` forward by `access_grace_days` whole days, and set `student_access_end_at` to that date at 23:59:59 UTC — a fixed wall time with no sub-second component."
    PRD §3.1: "Second, choose a retention horizon from `retention_class`: 365 days for `STANDARD`, 1825 days for `EXTENDED`, and no horizon at all for `LEGAL_HOLD`."
    PRD §3.1: "Otherwise `retention_purge_at` is `student_access_end_at` advanced by that many whole days, keeping the same 23:59:59 wall time."
    PRD §2.5: "An `LmsAdmin` may move it by supplying a `to_iso8601` instant to the clock-setting capability; that operation mutates no entity, but every subsequent request evaluates `add_drop_deadline_at`, `sandbox_expires_at`, `student_access_end_at`, `retention_purge_at`, `access_revoked_at` and continuity window bounds against the new instant."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."
    PRD §2.3: "Filter values are also the state fields themselves, so a caller can ask for one lifecycle stage at a time."

    Design: Corner/cross_cutting_complexity_layers/purged_shells_stay_readable_by_id_but_drop_out_of_the_default_listing
    """
    term = create_term(
        api, registrar_headers,
        term_code="SD-2026-FA",
        term_start_at="2026-08-24T00:00:00Z",
        term_end_at="2026-12-11T00:00:00Z",
        access_grace_days=0,
        retention_class="STANDARD",
    )
    assert _instant(term["student_access_end_at"]) == _instant("2026-12-11T23:59:59Z")
    assert _instant(term["retention_purge_at"]) == _instant("2027-12-11T23:59:59Z")
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    assert term["lifecycle_state"] == "REGISTRATION_OPEN"

    professor = create_faculty(
        api, registrar_headers, sis_person_id="SD-F-01", full_name="Mary Jackson"
    )
    assert professor["sandbox_storage_charge_usd"] == 0.00
    owner_headers = make_instructor_headers(professor["id"])

    first_shell = request_shell(
        api, term["id"], professor["id"], lms_admin_headers,
        sis_section_code="SD-SBX-001", shell_type="SANDBOX", base_seat_cap=5,
    )
    first_shell = provisioning_decision(
        api, first_shell["id"], "APPROVE", lms_admin_headers
    )
    assert first_shell["provisioning_state"] == "PROVISIONED"
    assert _instant(first_shell["sandbox_expires_at"]) == _instant(
        "2027-02-09T00:00:00Z"
    ), "sixty days after the term's term_end_at"

    second_shell = request_shell(
        api, term["id"], professor["id"], lms_admin_headers,
        sis_section_code="SD-SBX-002", shell_type="SANDBOX", base_seat_cap=5,
    )
    second_shell = provisioning_decision(
        api, second_shell["id"], "APPROVE", lms_admin_headers
    )
    assert second_shell["provisioning_state"] == "PROVISIONED"

    first_item = create_content_item(
        api, first_shell["id"], owner_headers,
        item_type="FILE", title="Lecture capture archive",
        points_possible=0.00, storage_mb=300.00,
    )
    create_content_item(
        api, second_shell["id"], owner_headers,
        item_type="FILE", title="Dataset mirror",
        points_possible=0.00, storage_mb=180.00,
    )

    for target_state in ("IN_SESSION", "FINALS", "GRADING", "CLOSED"):
        term = transition_term(api, term["id"], target_state, registrar_headers)
    assert term["lifecycle_state"] == "CLOSED"
    assert read_shell(api, first_shell["id"], lms_admin_headers)[
        "provisioning_state"
    ] == "CONCLUDED"
    assert read_shell(api, second_shell["id"], lms_admin_headers)[
        "provisioning_state"
    ] == "CONCLUDED"

    advance_clock(api, "2027-12-11T23:59:59Z", lms_admin_headers)

    archived_first = transition_shell(
        api, first_shell["id"], "ARCHIVED", registrar_headers
    )
    assert archived_first["provisioning_state"] == "ARCHIVED"
    assert archived_first["storage_mb"] == 300.00, (
        "archival leaves the stored megabytes alone; only a purge zeroes them"
    )
    assert archived_first["content_item_count"] == 1
    archived_second = transition_shell(
        api, second_shell["id"], "ARCHIVED", registrar_headers
    )
    assert archived_second["provisioning_state"] == "ARCHIVED"

    charge_before = read_person(api, professor["id"], lms_admin_headers)[
        "sandbox_storage_charge_usd"
    ]
    assert charge_before == 4.20, (
        "(300.00 - 100.00) * 0.0150 * 1.00 = 3.00 plus "
        "(180.00 - 100.00) * 0.0150 * 1.00 = 1.20, each rounded per shell"
    )

    rows, meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, {"term_id": term["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["sis_section_code"] for row in rows] == ["SD-SBX-001", "SD-SBX-002"]

    purged = transition_shell(
        api, first_shell["id"], "PURGED", registrar_headers,
        reason="retention horizon reached",
    )
    assert purged["provisioning_state"] == "PURGED"
    assert purged["storage_mb"] == 0.00
    assert purged["content_item_count"] == 0
    assert purged["total_points_possible"] == 0.00

    rows, meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, {"term_id": term["id"]})
    )
    assert meta["total_count"] == 1, (
        "the purged shell drops out of the listing even though no state filter "
        "was supplied"
    )
    assert meta["has_more"] is False
    assert [row["sis_section_code"] for row in rows] == ["SD-SBX-002"]

    rows, meta = validate_paginated(
        api.list_course_shells(
            lms_admin_headers,
            {"term_id": term["id"], "provisioning_state": "PURGED"},
        )
    )
    assert meta["total_count"] == 1, (
        "the row comes back only when it is asked for by name"
    )
    assert [row["id"] for row in rows] == [first_shell["id"]]
    assert rows[0]["sis_section_code"] == "SD-SBX-001"
    assert rows[0]["provisioning_state"] == "PURGED"

    by_id = read_shell(api, first_shell["id"], registrar_headers)
    assert by_id["provisioning_state"] == "PURGED", (
        "a read by identifier is never filtered, so this is a soft delete and "
        "never a 404"
    )
    assert by_id["sis_section_code"] == "SD-SBX-001"
    assert by_id["storage_mb"] == 0.00
    assert by_id["total_points_possible"] == 0.00

    item_rows, item_meta = validate_paginated(
        api.list_content_items(lms_admin_headers, {"shell_id": first_shell["id"]})
    )
    assert item_meta["total_count"] == 1, "the child rows survive the purge"
    assert item_rows[0]["id"] == first_item["id"]
    assert item_rows[0]["copy_state"] == "SKIPPED"
    assert item_rows[0]["storage_mb"] == 0.00

    surviving_item = read_content_item(api, first_item["id"], lms_admin_headers)
    assert surviving_item["title"] == "Lecture capture archive"
    assert surviving_item["copy_state"] == "SKIPPED"
    assert surviving_item["storage_mb"] == 0.00

    charge_after = read_person(api, professor["id"], lms_admin_headers)[
        "sandbox_storage_charge_usd"
    ]
    assert charge_after == 1.20, (
        "the purged shell left the billable set entirely, so only the surviving "
        "sandbox shell contributes"
    )

    survivor = read_shell(api, second_shell["id"], lms_admin_headers)
    assert survivor["provisioning_state"] == "ARCHIVED"
    assert survivor["storage_mb"] == 180.00
