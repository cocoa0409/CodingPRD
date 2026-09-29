"""Validation-rule compliance tests: uniqueness scopes, the fixed precedence of the
validation bands, boundary-instant time gates, the sandbox ceiling, the sandbox
publish/enrollment exemption, and the freshly derived seat capacity.

Every test builds its own world from scratch: the server is relaunched before
each test, so the database is empty and the logical clock reads its startup
instant of 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    change_posture,
    create_academic_term_payload,
    create_content_item,
    create_content_item_payload,
    create_course_shell_payload,
    create_enrollment_payload,
    create_faculty,
    create_student,
    create_students,
    create_term,
    create_tool_integration_payload,
    enrol,
    open_window_for,
    provision_shell,
    provisioning_decision,
    publish,
    read_shell,
    read_term,
    request_shell,
    transition_window,
    validate_error,
    validate_paginated,
    validate_success,
    walk_term_to,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _money(value):
    """A two-decimal figure compared tightly enough to separate adjacent cents."""
    return pytest.approx(value, abs=0.005)


def test_duplicate_term_codes_and_duplicate_vendor_tool_pairs_are_rejected_on_create(
    api, registrar_headers, lms_admin_headers
):
    """PRD §2.10: "`term_code` is unique across all terms, on `POST /academic-terms` —
    otherwise `ERR_DUPLICATE_TERM_CODE`."
    PRD §2.10: "The pair of `vendor_name` and `tool_name` is unique across tools, on
    `POST /tool-integrations` — otherwise `ERR_DUPLICATE_TOOL`."
    PRD §2.3: "Both values are echoed back in the `meta` object of the envelope, alongside
    `total_count` (the number of records matching the filter before the page window is
    applied) and `has_more` (true when records remain beyond the current window)."

    Design: Corner/validations/duplicate_term_codes_and_duplicate_vendor_tool_pairs_are_rejected_on_create
    """
    validate_success(
        api.create_academic_term(
            create_academic_term_payload(term_code="2027SP"), registrar_headers
        ),
        201,
    )
    validate_error(
        api.create_academic_term(
            create_academic_term_payload(term_code="2027SP"), registrar_headers
        ),
        "ERR_DUPLICATE_TERM_CODE",
    )
    validate_success(
        api.create_academic_term(
            create_academic_term_payload(term_code="2027SU"), registrar_headers
        ),
        201,
    )

    validate_success(
        api.create_tool_integration(
            create_tool_integration_payload(
                vendor_name="PollCo", tool_name="LivePoll", tool_version="1.0.0"
            ),
            lms_admin_headers,
        ),
        201,
    )
    validate_error(
        api.create_tool_integration(
            create_tool_integration_payload(
                vendor_name="PollCo", tool_name="LivePoll", tool_version="2.0.0"
            ),
            lms_admin_headers,
        ),
        "ERR_DUPLICATE_TOOL",
    )
    validate_success(
        api.create_tool_integration(
            create_tool_integration_payload(
                vendor_name="PollCo", tool_name="LiveQuiz", tool_version="1.0.0"
            ),
            lms_admin_headers,
        ),
        201,
    )

    _, term_meta = validate_paginated(api.list_academic_terms(registrar_headers, {"limit": 100}))
    assert term_meta["total_count"] == 2, "the rejected duplicate term was never stored"
    _, tool_meta = validate_paginated(
        api.list_tool_integrations(lms_admin_headers, {"limit": 100})
    )
    assert tool_meta["total_count"] == 2, (
        "one vendor may hold several tools; only the repeated pair is refused"
    )


def test_section_code_uniqueness_is_scoped_to_live_official_shells_of_one_term(
    api, lms_admin_headers
):
    """PRD §2.10: "`sis_section_code` is unique per term among that term's `OFFICIAL`
    shells whose `provisioning_state` is neither `REJECTED` nor `PURGED`; `SANDBOX` and
    `DEV` shells are exempt from the uniqueness rule entirely. On `POST /course-shells` —
    otherwise `ERR_DUPLICATE_SECTION_CODE`."
    PRD §3.3: "Two limits bite at request time: section codes must be unique per term among
    live `OFFICIAL` shells (`ERR_DUPLICATE_SECTION_CODE`), and one person may own at most
    three live sandbox or development shells (`ERR_SANDBOX_QUOTA_EXCEEDED`)."
    PRD §3.3: "`REJECT` moves `REQUESTED` → `REJECTED`, which is terminal: it requires only
    that the shell still be `REQUESTED`, records the supplied reason into `reject_reason`,
    sets the shell's `storage_mb` to 0.00, and recomputes the owner's
    `sandbox_storage_charge_usd` — necessarily downward, since a rejected shell stops being
    billable."

    Design: Corner/validations/section_code_uniqueness_is_scoped_to_live_official_shells_of_one_term
    """
    fall = create_term(api, term_code="2026FA")
    spring = create_term(api, term_code="2027SP")
    owner = create_faculty(api)

    holder = request_shell(
        api, fall["id"], owner["id"], sis_section_code="BIO101-01", shell_type="OFFICIAL"
    )
    assert holder["provisioning_state"] == "REQUESTED"

    validate_error(
        api.create_course_shell(
            create_course_shell_payload(
                fall["id"], owner["id"], sis_section_code="BIO101-01", shell_type="OFFICIAL"
            ),
            lms_admin_headers,
        ),
        "ERR_DUPLICATE_SECTION_CODE",
    )

    sandbox_twin = request_shell(
        api, fall["id"], owner["id"], sis_section_code="BIO101-01",
        shell_type="SANDBOX", base_seat_cap=1,
    )
    assert sandbox_twin["sis_section_code"] == "BIO101-01", (
        "a SANDBOX shell is exempt from the uniqueness rule entirely"
    )

    other_term = request_shell(
        api, spring["id"], owner["id"], sis_section_code="BIO101-01", shell_type="OFFICIAL"
    )
    assert other_term["term_id"] == spring["id"], "the scope is one term, not the whole service"

    rejected = provisioning_decision(
        api, holder["id"], "REJECT", lms_admin_headers, reason="section cancelled"
    )
    assert rejected["provisioning_state"] == "REJECTED"

    replacement = request_shell(
        api, fall["id"], owner["id"], sis_section_code="BIO101-01", shell_type="OFFICIAL"
    )
    assert replacement["sis_section_code"] == "BIO101-01", (
        "a rejected holder no longer occupies the code"
    )

    _, meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, {"term_id": fall["id"], "limit": 100})
    )
    assert meta["total_count"] == 3, (
        "the fall term holds the rejected shell, the sandbox twin and the replacement"
    )


def test_lower_numbered_validation_bands_win_when_two_rules_fire_on_one_request(
    api, registrar_headers, privacy_reviewer_headers
):
    """PRD §2.10: "When several rules could reject the same request, exactly one of them
    decides the response, and the order is fixed."
    PRD §2.10: "`X-User-Role` is one of the six declared roles and is authorized for the
    target endpoint; and on `POST /tool-reviews` the body's `dimension` matches the acting
    reviewer role — otherwise `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."
    PRD §2.10: "Every identifier embedded in the path exists, checked left to right, on
    every path containing an identifier — otherwise the record-specific 404 code from §2.4."
    PRD §2.10: "Request shape, on every endpoint — otherwise `ERR_INVALID_REQUEST`."
    PRD §2.10: "`term_code` is unique across all terms, on `POST /academic-terms` —
    otherwise `ERR_DUPLICATE_TERM_CODE`."
    PRD §2.1: "`PrivacyReviewer` and `AccessibilityReviewer` are peer reviewer roles from
    the campus privacy and accessibility offices respectively."
    PRD §2.4: "A request whose path names a record that does not exist is rejected with the
    404 code specific to that record type — `ERR_TERM_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`,
    `ERR_SHELL_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_MERGE_REQUEST_NOT_FOUND`, `ERR_CONTENT_ITEM_NOT_FOUND`,
    `ERR_ROLLOVER_JOB_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_PLACEMENT_NOT_FOUND`, `ERR_PASSBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or
    `ERR_WINDOW_NOT_FOUND`."

    Design: Corner/validations/lower_numbered_validation_bands_win_when_two_rules_fire_on_one_request
    """
    # An unauthorized role and a missing record on one request: the role band is lower.
    validate_error(
        api.get_course_shell(NON_EXISTENT_UUID, privacy_reviewer_headers),
        "ERR_ROLE_NOT_PERMITTED",
    )

    # A missing record and a bad enum on one request: existence outranks request shape.
    validate_error(
        api.patch_academic_term(
            NON_EXISTENT_UUID, {"retention_class": "PERMANENT"}, registrar_headers
        ),
        "ERR_TERM_NOT_FOUND",
    )

    existing = validate_success(
        api.create_academic_term(
            create_academic_term_payload(
                term_code="2026FA",
                term_start_at="2026-08-24T00:00:00Z",
                term_end_at="2026-12-11T00:00:00Z",
            ),
            registrar_headers,
        ),
        201,
    )
    assert existing["term_code"] == "2026FA"

    # A duplicate code and an inverted calendar on one request: shape outranks uniqueness.
    validate_error(
        api.create_academic_term(
            create_academic_term_payload(
                term_code="2026FA",
                term_start_at="2026-08-24T00:00:00Z",
                term_end_at="2026-08-01T00:00:00Z",
            ),
            registrar_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    _, meta = validate_paginated(api.list_academic_terms(registrar_headers, {"limit": 100}))
    assert meta["total_count"] == 1, "no refused request left a row behind"


def test_time_gated_writes_compare_the_logical_clock_at_their_exact_boundary_instants(
    api, lms_admin_headers, instructor_headers_for
):
    """PRD §2.10: "Cancelling a continuity window happens strictly before its
    `window_start`, on `POST /continuity-windows/{id}/transitions` with action `CANCEL` —
    otherwise `ERR_WINDOW_ALREADY_STARTED`."
    PRD §3.9: "A window is **closed** (`CLOSE`) from `OPEN`, which stamps `closed_at` from
    the logical clock, or **cancelled** (`CANCEL`) from `OPEN`, which requires the logical
    clock to still be strictly before its `window_start`, otherwise
    `ERR_WINDOW_ALREADY_STARTED` — a window that has already begun affecting students can
    be closed but never cancelled. Cancelling also resets `affected_enrollment_count` and
    `extension_days_granted` to 0, since nothing was in fact affected or granted."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the shell's
    `active_enrollment_count` for a shell-scoped window, or the term's
    `total_active_enrollments` for a term-wide one — and, for a window whose `kind` is
    `EXTENSION`, records `extension_days_granted` as the window's length in seconds divided
    by 86,400 and rounded **up** to a whole day, so that any partial day counts as a full
    granted day; every other kind records 0."
    PRD §2.10: "A `SANDBOX` or `DEV` shell receives no new content, placements or rollover
    output after its `sandbox_expires_at`, on `POST /content-items`,
    `POST /tool-placements` and `POST /rollover-jobs` — otherwise `ERR_SANDBOX_EXPIRED`."
    PRD §3.3: "Once the logical clock passes a shell's `sandbox_expires_at`, that shell
    accepts no new content items, no new tool placements and no new rollover jobs targeting
    it; each such attempt is refused with `ERR_SANDBOX_EXPIRED`."
    PRD §2.5: "Timestamps the server stamps itself — `dropped_at`, `resolved_at`,
    `closed_at` — are taken from the logical clock at the moment of the transition."

    Design: Corner/validations/time_gated_writes_compare_the_logical_clock_at_their_exact_boundary_instants
    """
    term = create_term(
        api, term_start_at="2026-08-24T00:00:00Z", term_end_at="2026-12-11T00:00:00Z"
    )
    walk_term_to(api, term["id"], "IN_SESSION")
    owner = create_faculty(api)
    owner_headers = instructor_headers_for(owner["id"])
    official = provision_shell(api, term["id"], owner["id"], base_seat_cap=5)
    for student in create_students(api, 2):
        enrol(api, official["id"], student["id"])
    assert read_term(api, term["id"])["total_active_enrollments"] == 2

    sandbox = request_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1
    )
    assert _instant(sandbox["sandbox_expires_at"]) == _instant("2027-02-09T00:00:00Z"), (
        "sixty days after the term's term_end_at"
    )

    early = open_window_for(
        api, term["id"], "MAINTENANCE", "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z"
    )
    assert early["window_state"] == "OPEN"
    assert early["affected_enrollment_count"] == 2
    cancelled = transition_window(api, early["id"], "CANCEL")
    assert cancelled["window_state"] == "CANCELLED", "the clock is still before window_start"
    assert cancelled["affected_enrollment_count"] == 0
    assert cancelled["extension_days_granted"] == 0

    started = open_window_for(
        api, term["id"], "MAINTENANCE", "2026-08-02T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    advance_clock(api, "2026-08-03T00:00:00Z")
    validate_error(
        api.continuity_window_transition(started["id"], {"action": "CANCEL"}, lms_admin_headers),
        "ERR_WINDOW_ALREADY_STARTED",
    )
    closed = transition_window(api, started["id"], "CLOSE")
    assert closed["window_state"] == "CLOSED", "a started window can still be closed"
    assert _instant(closed["closed_at"]) == _instant("2026-08-03T00:00:00Z")

    # Exactly at sandbox_expires_at the clock has not yet passed it.
    advance_clock(api, "2027-02-09T00:00:00Z")
    on_the_boundary = create_content_item(
        api, sandbox["id"], owner_headers,
        item_type="PAGE", title="Sandbox Syllabus", points_possible=0.00,
    )
    assert on_the_boundary["shell_id"] == sandbox["id"]

    advance_clock(api, "2027-02-09T00:00:01Z")
    validate_error(
        api.create_content_item(
            create_content_item_payload(
                sandbox["id"], item_type="PAGE", title="Late Page", points_possible=0.00
            ),
            owner_headers,
        ),
        "ERR_SANDBOX_EXPIRED",
    )


def test_sandbox_shell_ceiling_counts_only_live_sandbox_and_dev_shells_per_owner(
    api, lms_admin_headers
):
    """PRD §2.10: "A person owns at most three shells whose `shell_type` is `SANDBOX` or
    `DEV` and whose `provisioning_state` is neither `REJECTED` nor `PURGED`, on
    `POST /course-shells` — otherwise `ERR_SANDBOX_QUOTA_EXCEEDED`."
    PRD §3.3: "Two limits bite at request time: section codes must be unique per term among
    live `OFFICIAL` shells (`ERR_DUPLICATE_SECTION_CODE`), and one person may own at most
    three live sandbox or development shells (`ERR_SANDBOX_QUOTA_EXCEEDED`)."
    PRD §3.3: "`REJECT` moves `REQUESTED` → `REJECTED`, which is terminal: it requires only
    that the shell still be `REQUESTED`, records the supplied reason into `reject_reason`,
    sets the shell's `storage_mb` to 0.00, and recomputes the owner's
    `sandbox_storage_charge_usd` — necessarily downward, since a rejected shell stops being
    billable."

    Design: Corner/validations/sandbox_shell_ceiling_counts_only_live_sandbox_and_dev_shells_per_owner
    """
    term = create_term(api)
    owner = create_faculty(api)

    request_shell(api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1)
    request_shell(api, term["id"], owner["id"], shell_type="DEV", base_seat_cap=1)
    third = request_shell(api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1)

    validate_error(
        api.create_course_shell(
            create_course_shell_payload(
                term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1
            ),
            lms_admin_headers,
        ),
        "ERR_SANDBOX_QUOTA_EXCEEDED",
    )
    validate_error(
        api.create_course_shell(
            create_course_shell_payload(
                term["id"], owner["id"], shell_type="DEV", base_seat_cap=1
            ),
            lms_admin_headers,
        ),
        "ERR_SANDBOX_QUOTA_EXCEEDED",
    )

    official = validate_success(
        api.create_course_shell(
            create_course_shell_payload(term["id"], owner["id"], shell_type="OFFICIAL"),
            lms_admin_headers,
        ),
        201,
    )
    assert official["shell_type"] == "OFFICIAL", "OFFICIAL shells are outside the ceiling"

    provisioning_decision(
        api, third["id"], "REJECT", lms_admin_headers, reason="not needed after all"
    )
    replacement = validate_success(
        api.create_course_shell(
            create_course_shell_payload(
                term["id"], owner["id"], shell_type="DEV", base_seat_cap=1
            ),
            lms_admin_headers,
        ),
        201,
    )
    assert replacement["shell_type"] == "DEV", "rejecting one shell frees a slot"

    rows, meta = validate_paginated(
        api.list_course_shells(
            lms_admin_headers, {"owner_person_id": owner["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 5
    live = [
        row for row in rows
        if row["shell_type"] in ("SANDBOX", "DEV")
        and row["provisioning_state"] not in ("REJECTED", "PURGED")
    ]
    assert len(live) == 3, "exactly three live sandbox or development shells remain"
    assert [row["provisioning_state"] for row in rows if row["id"] == third["id"]] == ["REJECTED"]


def test_publish_and_student_enrollment_rules_apply_only_to_sandbox_and_dev_shells(
    api, lms_admin_headers, registrar_headers
):
    """PRD §2.10: "A `SANDBOX` or `DEV` shell can never be published and can never carry an
    enrollment whose `role` is `STUDENT`; such shells remain legal rollover targets. On
    `POST /course-shells/{id}/publish` and `POST /enrollments` — otherwise
    `ERR_SANDBOX_NOT_PUBLISHABLE`."
    PRD §3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty days after
    the term's `term_end_at` for a `SANDBOX` or `DEV` shell while remaining null for an
    `OFFICIAL` one."
    PRD §3.3: "A successful publish moves `PROVISIONED` → `PUBLISHED` and increments the
    term's `published_shell_count` by one."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is
    `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's `seat_utilization_pct` and
    `overflow_flag` are re-derived."
    PRD §3.4: "Only rows whose `role` is `STUDENT` participate in any of this — `TEACHER`,
    `TA`, `DESIGNER` and `OBSERVER` rows never consume a seat and never appear on a
    waitlist."

    Design: Corner/validations/publish_and_student_enrollment_rules_apply_only_to_sandbox_and_dev_shell_types
    """
    term = create_term(api)
    walk_term_to(api, term["id"], "IN_SESSION")
    owner = create_faculty(api)
    designer = create_faculty(api)
    student = create_student(api)

    sandbox = provision_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=5
    )
    assert sandbox["provisioning_state"] == "PROVISIONED"
    assert sandbox["publish_readiness"] is True, (
        "approval readies the shell; the refusal below is about its class, not readiness"
    )

    validate_error(
        api.publish_shell(sandbox["id"], lms_admin_headers), "ERR_SANDBOX_NOT_PUBLISHABLE"
    )
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                sandbox["id"], student["id"], role="STUDENT", requested_state="ACTIVE"
            ),
            registrar_headers,
        ),
        "ERR_SANDBOX_NOT_PUBLISHABLE",
    )

    staff_row = enrol(api, sandbox["id"], designer["id"], role="DESIGNER")
    assert staff_row["enrollment_state"] == "ACTIVE", (
        "only a STUDENT row is barred from a sandbox shell"
    )

    official = provision_shell(api, term["id"], owner["id"], base_seat_cap=5)
    published = publish(api, official["id"])
    assert published["provisioning_state"] == "PUBLISHED"
    student_row = enrol(api, official["id"], student["id"])
    assert student_row["enrollment_state"] == "ACTIVE"

    sandbox_after = read_shell(api, sandbox["id"])
    assert sandbox_after["active_enrollment_count"] == 0, "a DESIGNER row consumes no seat"
    assert sandbox_after["provisioning_state"] == "PROVISIONED", "the refused publish changed nothing"


def test_the_seat_cap_check_reads_a_freshly_derived_effective_cap_not_the_stored_base(
    api, registrar_headers
):
    """PRD §2.10: "A student enrollment may occupy a seat only while at least one seat is
    open under the shell's effective capacity, on `POST /enrollments` and on
    `POST /enrollments/{id}/transitions` with action `PROMOTE` or `REINSTATE` — otherwise
    `ERR_SEAT_CAP_EXCEEDED`."
    PRD §3.4: "Asking for a live seat requires three things: the shell's
    `provisioning_state` is `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`); no other enrollment exists for that same
    shell-and-person pair whose `enrollment_state` is `ACTIVE`, `WAITLISTED` or `DROPPED`
    (otherwise `ERR_ROLE_CONFLICT`); and, when the `role` is `STUDENT`, the shell's
    `active_enrollment_count` is still below its `effective_seat_cap` (otherwise
    `ERR_SEAT_CAP_EXCEEDED`)."
    PRD §3.4: "Step one derives the overflow ratio from the *term's* `continuity_posture`
    and from nothing else: 0.00 under `NORMAL`, 0.10 under `ELEVATED`, and 0.20 under
    `CONTINUITY_MODE`. The overflow allowance is the shell's `base_seat_cap` multiplied by
    that ratio and rounded **down** to a whole seat. Step two freezes `effective_seat_cap`
    at `base_seat_cap` plus that allowance, and that frozen value governs the entire run —
    it is never recomputed between individual promotions inside one run."
    PRD §3.4: "Only in step five are the observables recomputed: `seat_utilization_pct`
    becomes `active_enrollment_count` divided by `base_seat_cap`, multiplied by 100, rounded
    half up to two decimal places, and `overflow_flag` becomes true exactly when
    `active_enrollment_count` is greater than `base_seat_cap`."
    PRD §3.4: "The utilization denominator is always `base_seat_cap` and never
    `effective_seat_cap`, and `overflow_flag` is strictly an output of step five: it must
    never feed back into the ratio chosen in step one."
    PRD §3.9: "And it **relaxes seat capacity**: the overflow ratio of §3.4 is read straight
    off the posture, so escalating a term to `ELEVATED` or `CONTINUITY_MODE` widens the
    `effective_seat_cap` of every shell in it, and de-escalating narrows it again."

    Design: Corner/validations/the_seat_cap_check_reads_a_freshly_derived_effective_cap_not_the_stored_base
    """
    term = create_term(api)
    walk_term_to(api, term["id"], "IN_SESSION")
    owner = create_faculty(api)
    shell = provision_shell(api, term["id"], owner["id"], base_seat_cap=5)
    assert shell["effective_seat_cap"] == 5

    for student in create_students(api, 5):
        enrol(api, shell["id"], student["id"])
    assert read_shell(api, shell["id"])["active_enrollment_count"] == 5

    sixth = create_student(api)
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                shell["id"], sixth["id"], role="STUDENT", requested_state="ACTIVE"
            ),
            registrar_headers,
        ),
        "ERR_SEAT_CAP_EXCEEDED",
    )

    change_posture(api, term["id"], "ELEVATED")
    assert read_shell(api, shell["id"])["effective_seat_cap"] == 5, "floor(5 * 0.10) is 0"
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                shell["id"], sixth["id"], role="STUDENT", requested_state="ACTIVE"
            ),
            registrar_headers,
        ),
        "ERR_SEAT_CAP_EXCEEDED",
    )

    open_window_for(api, term["id"], "OUTAGE", "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z")
    change_posture(api, term["id"], "CONTINUITY_MODE")
    assert read_shell(api, shell["id"])["effective_seat_cap"] == 6, "floor(5 * 0.20) is 1"

    accepted = enrol(api, shell["id"], sixth["id"])
    assert accepted["enrollment_state"] == "ACTIVE", (
        "the check reads the widened effective cap, not the stored base cap"
    )
    overflowing = read_shell(api, shell["id"])
    assert overflowing["active_enrollment_count"] == 6
    assert overflowing["base_seat_cap"] == 5
    assert overflowing["seat_utilization_pct"] == _money(120.00), "6 over the base cap of 5"
    assert overflowing["overflow_flag"] is True

    seventh = create_student(api)
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                shell["id"], seventh["id"], role="STUDENT", requested_state="ACTIVE"
            ),
            registrar_headers,
        ),
        "ERR_SEAT_CAP_EXCEEDED",
    )
