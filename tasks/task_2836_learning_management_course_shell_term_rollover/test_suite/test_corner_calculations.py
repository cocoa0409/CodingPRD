"""Computed-figure compliance tests: retention instants, grade percentages,
the sandbox storage chargeback, the tool risk score, the purge horizon and the
posture-driven seat allowance.

Every test builds its own world from scratch: the server is relaunched before
each test, so the database is empty and the logical clock reads its startup
instant of 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    active_placement,
    advance_clock,
    change_posture,
    create_academic_term_payload,
    create_content_item,
    create_faculty,
    create_student,
    create_students,
    create_term,
    enrol,
    file_review,
    open_window,
    provision_shell,
    provisioning_decision,
    read_content_item,
    read_enrollment,
    read_person,
    read_shell,
    read_term,
    read_tool,
    record_grade,
    register_tool,
    request_shell,
    transition_shell,
    transition_term,
    transition_tool,
    validate_error,
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


def test_retention_schedule_across_all_three_retention_classes(api, registrar_headers):
    """PRD §3.1: "Registration also computes the term's two retention instants, and a
    `Registrar` amending the term's `access_grace_days`, `retention_class` or
    `add_drop_deadline_at` recomputes them."
    PRD §3.1: "First, take the calendar date reached by advancing `term_end_at` forward
    by `access_grace_days` whole days, and set `student_access_end_at` to that date at
    23:59:59 UTC — a fixed wall time with no sub-second component."
    PRD §3.1: "Second, choose a retention horizon from `retention_class`: 365 days for
    `STANDARD`, 1825 days for `EXTENDED`, and no horizon at all for `LEGAL_HOLD`."
    PRD §3.1: "When there is no horizon, `retention_purge_at` is null and the shell purge
    path is closed permanently."
    PRD §3.1: "For a term ending `2026-12-11T00:00:00Z` with 30 grace days,
    `student_access_end_at` is `2027-01-10T23:59:59Z`; under `STANDARD` the purge horizon
    is `2028-01-10T23:59:59Z`, and under `EXTENDED` it is `2032-01-09T23:59:59Z`, the
    day-of-month shifting because 1825 days spans a leap day."
    PRD §3.1: "A grace period of 0 days is legal and collapses `student_access_end_at`
    onto the term's own end date at 23:59:59, so a student read at exactly that instant
    still succeeds while one instant later fails with `ERR_STUDENT_ACCESS_EXPIRED`."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same timestamp
    format, refreshed on every mutation — and `version`, an integer that starts at 1 on
    creation and increments by exactly one on every mutation of that record."

    Design: Corner/calculations/retention_schedule_computes_access_end_and_purge_horizon_for_all_three_classes
    """
    term = validate_success(
        api.create_academic_term(
            create_academic_term_payload(
                term_code="2026FA",
                term_start_at="2026-08-24T00:00:00Z",
                term_end_at="2026-12-11T00:00:00Z",
                access_grace_days=30,
                retention_class="STANDARD",
            ),
            registrar_headers,
        ),
        201,
    )
    assert _instant(term["student_access_end_at"]) == _instant("2027-01-10T23:59:59Z"), (
        "2026-12-11 advanced by 30 whole grace days, snapped to 23:59:59"
    )
    assert _instant(term["retention_purge_at"]) == _instant("2028-01-10T23:59:59Z"), (
        "STANDARD adds 365 days to student_access_end_at"
    )
    assert term["version"] == 1

    extended = validate_success(
        api.patch_academic_term(term["id"], {"retention_class": "EXTENDED"}, registrar_headers),
        200,
    )
    assert _instant(extended["retention_purge_at"]) == _instant("2032-01-09T23:59:59Z"), (
        "EXTENDED adds 1825 whole days, which spans a leap day"
    )
    assert _instant(extended["student_access_end_at"]) == _instant("2027-01-10T23:59:59Z"), (
        "the access-end step is independent of retention_class"
    )
    assert extended["version"] == 2

    held = validate_success(
        api.patch_academic_term(term["id"], {"retention_class": "LEGAL_HOLD"}, registrar_headers),
        200,
    )
    assert held["retention_purge_at"] is None, "LEGAL_HOLD has no horizon at all"
    assert _instant(held["student_access_end_at"]) == _instant("2027-01-10T23:59:59Z")
    assert held["version"] == 3

    collapsed = validate_success(
        api.patch_academic_term(
            term["id"], {"retention_class": "STANDARD", "access_grace_days": 0}, registrar_headers
        ),
        200,
    )
    assert _instant(collapsed["student_access_end_at"]) == _instant("2026-12-11T23:59:59Z")
    assert _instant(collapsed["retention_purge_at"]) == _instant("2027-12-11T23:59:59Z")
    assert collapsed["version"] == 4


def test_provisional_grade_percentage_rounds_half_up_at_the_third_decimal(
    api, instructor_headers_for
):
    """PRD §3.8: "A **grade percentage** is always the enrollment's `earned_points_total`
    divided by a denominator, multiplied by 100, with the division carried at full
    precision and the result rounded half up to two decimal places exactly once at the
    end; when the denominator is zero the percentage is 0.00."
    PRD §3.8: "The **provisional** variant divides by the enrollment's own
    `graded_points_possible` — the work graded so far — which flatters an incomplete
    gradebook, and it writes `provisional_grade_pct`."
    PRD §3.8: "Each write re-derives the enrollment's `earned_points_total` as the sum of
    its grade records and its `graded_points_possible` as the sum of the `points_possible`
    of the items it now carries a record for, and re-derives that enrollment's
    `provisional_grade_pct`."
    PRD §3.6: "Creating, editing or removing an item re-derives the owning shell's
    `storage_mb` (the sum of its items' `storage_mb`), its `content_item_count` (the
    number of its items whose `copy_state` is not `SKIPPED`) and its
    `total_points_possible` (the sum of `points_possible` over its `ASSIGNMENT` and `QUIZ`
    items whose `copy_state` is not `SKIPPED`), and re-derives the shell owner's
    `sandbox_storage_charge_usd` for `SANDBOX` and `DEV` shells."

    Design: Corner/calculations/grade_percentage_rounds_half_up_at_the_third_decimal_and_never_truncates
    """
    term = create_term(api)
    owner = create_faculty(api)
    owner_headers = instructor_headers_for(owner["id"])
    shell = provision_shell(api, term["id"], owner["id"], base_seat_cap=5)

    project = create_content_item(
        api, shell["id"], owner_headers,
        item_type="ASSIGNMENT", title="Capstone Project", points_possible=800.00,
    )
    quiz = create_content_item(
        api, shell["id"], owner_headers,
        item_type="QUIZ", title="Unit Quiz", points_possible=300.00,
    )
    assert read_shell(api, shell["id"])["total_points_possible"] == _money(1100.00)

    students = create_students(api, 3)
    rows = [enrol(api, shell["id"], person["id"]) for person in students]

    # 71.24 / 800 * 100 = 8.905 exactly, which rounds half up to 8.91.
    record_grade(api, rows[0]["id"], project["id"], 71.24, owner_headers)
    first = read_enrollment(api, rows[0]["id"])
    assert first["earned_points_total"] == _money(71.24)
    assert first["graded_points_possible"] == _money(800.00)
    assert first["provisional_grade_pct"] == _money(8.91), (
        "8.905 must round half up rather than truncate to 8.90"
    )

    # 71.23 / 800 * 100 = 8.90375, which rounds down to 8.90.
    record_grade(api, rows[1]["id"], project["id"], 71.23, owner_headers)
    second = read_enrollment(api, rows[1]["id"])
    assert second["graded_points_possible"] == _money(800.00)
    assert second["provisional_grade_pct"] == _money(8.90)

    # 100 / 300 * 100 = 33.3333..., which rounds to 33.33.
    record_grade(api, rows[2]["id"], quiz["id"], 100.00, owner_headers)
    third = read_enrollment(api, rows[2]["id"])
    assert third["graded_points_possible"] == _money(300.00), (
        "the provisional denominator is only the graded item, not the whole shell"
    )
    assert third["provisional_grade_pct"] == _money(33.33)


def test_regrading_an_item_re_sums_the_gradebook_instead_of_double_counting(
    api, instructor_headers_for
):
    """PRD §3.8: "An `Instructor` records — or overwrites — one enrollment's earned points
    for one content item by naming `enrollment_id`, `content_item_id` and `earned_points`;
    this is the only way points reach a gradebook."
    PRD §3.8: "Each write re-derives the enrollment's `earned_points_total` as the sum of
    its grade records and its `graded_points_possible` as the sum of the `points_possible`
    of the items it now carries a record for, and re-derives that enrollment's
    `provisional_grade_pct`."
    PRD §3.8: "A **grade percentage** is always the enrollment's `earned_points_total`
    divided by a denominator, multiplied by 100, with the division carried at full
    precision and the result rounded half up to two decimal places exactly once at the
    end; when the denominator is zero the percentage is 0.00."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same timestamp
    format, refreshed on every mutation — and `version`, an integer that starts at 1 on
    creation and increments by exactly one on every mutation of that record."

    Design: Corner/calculations/regrading_an_item_re_sums_the_gradebook_instead_of_double_counting_it
    """
    term = create_term(api)
    owner = create_faculty(api)
    owner_headers = instructor_headers_for(owner["id"])
    shell = provision_shell(api, term["id"], owner["id"], base_seat_cap=5)

    essay = create_content_item(
        api, shell["id"], owner_headers,
        item_type="ASSIGNMENT", title="Essay One", points_possible=100.00,
    )
    lab = create_content_item(
        api, shell["id"], owner_headers,
        item_type="ASSIGNMENT", title="Lab One", points_possible=100.00,
    )

    student = create_student(api)
    row = enrol(api, shell["id"], student["id"])
    assert row["version"] == 1

    record_grade(api, row["id"], essay["id"], 80.00, owner_headers)
    after_first = read_enrollment(api, row["id"])
    assert after_first["earned_points_total"] == _money(80.00)
    assert after_first["graded_points_possible"] == _money(100.00)
    assert after_first["provisional_grade_pct"] == _money(80.00)

    record_grade(api, row["id"], lab["id"], 50.00, owner_headers)
    after_second = read_enrollment(api, row["id"])
    assert after_second["earned_points_total"] == _money(130.00)
    assert after_second["graded_points_possible"] == _money(200.00)
    assert after_second["provisional_grade_pct"] == _money(65.00)

    # Overwriting the essay must replace its 80.00, not add a second record.
    record_grade(api, row["id"], essay["id"], 90.00, owner_headers)
    after_regrade = read_enrollment(api, row["id"])
    assert after_regrade["earned_points_total"] == _money(140.00), (
        "the overwrite replaces the earlier 80.00 instead of stacking on top of it"
    )
    assert after_regrade["graded_points_possible"] == _money(200.00), (
        "the item is still counted exactly once in the denominator"
    )
    assert after_regrade["provisional_grade_pct"] == _money(70.00)
    assert after_regrade["version"] == 4, (
        "three grade writes are three mutations of the enrollment"
    )


def test_chargeback_bills_only_megabytes_above_the_free_tier_at_the_class_multiplier(
    api, instructor_headers_for
):
    """PRD §3.3: "A person's `sandbox_storage_charge_usd` starts at 0.00 and is only ever
    written by the chargeback computation described later in this subsection."
    PRD §3.3: "Whenever a content item is added to or removed from such a shell, whenever
    such a shell's `storage_mb` changes because a rollover copied into it or a
    compensation unwound the copy, and whenever a shell is purged, the owner's
    `sandbox_storage_charge_usd` is recomputed from scratch."
    PRD §3.3: "For each shell, subtract a free allowance of 100.00 megabytes from its
    `storage_mb` and treat any negative result as zero; multiply the remainder by a rate
    of 0.0150 US dollars per megabyte; multiply again by the class multiplier, which is
    1.00 for a `SANDBOX` shell and 0.50 for a `DEV` shell; then round that single shell's
    charge half up to two decimal places."
    PRD §3.3: "The person's total is the sum of those already-rounded per-shell charges."

    Design: Corner/calculations/chargeback_bills_only_megabytes_above_the_free_tier_at_the_shell_type_multiplier
    """
    term = create_term(api)
    at_the_tier = create_faculty(api)
    over_the_tier = create_faculty(api)
    assert at_the_tier["sandbox_storage_charge_usd"] == _money(0.00)
    assert over_the_tier["sandbox_storage_charge_usd"] == _money(0.00)

    free_shell = request_shell(
        api, term["id"], at_the_tier["id"], shell_type="SANDBOX", base_seat_cap=1
    )
    sandbox = request_shell(
        api, term["id"], over_the_tier["id"], shell_type="SANDBOX", base_seat_cap=1
    )
    dev = request_shell(
        api, term["id"], over_the_tier["id"], shell_type="DEV", base_seat_cap=1
    )

    # Exactly at the free allowance: 100.00 - 100.00 leaves nothing billable.
    create_content_item(
        api, free_shell["id"], instructor_headers_for(at_the_tier["id"]),
        item_type="FILE", title="Lecture Media", points_possible=0.00, storage_mb=100.00,
    )
    assert read_shell(api, free_shell["id"])["storage_mb"] == _money(100.00)
    assert read_person(api, at_the_tier["id"])["sandbox_storage_charge_usd"] == _money(0.00)

    owner_headers = instructor_headers_for(over_the_tier["id"])
    # SANDBOX at 300.00 MB: (300.00 - 100.00) * 0.0150 * 1.00 = 3.00.
    create_content_item(
        api, sandbox["id"], owner_headers,
        item_type="FILE", title="Sandbox Media", points_possible=0.00, storage_mb=300.00,
    )
    assert read_person(api, over_the_tier["id"])["sandbox_storage_charge_usd"] == _money(3.00)

    # DEV at 300.00 MB adds (300.00 - 100.00) * 0.0150 * 0.50 = 1.50, totalling 4.50.
    create_content_item(
        api, dev["id"], owner_headers,
        item_type="FILE", title="Dev Media", points_possible=0.00, storage_mb=300.00,
    )
    assert read_person(api, over_the_tier["id"])["sandbox_storage_charge_usd"] == _money(4.50), (
        "the DEV multiplier is 0.50 against the same 200.00 billable megabytes"
    )
    assert read_person(api, at_the_tier["id"])["sandbox_storage_charge_usd"] == _money(0.00), (
        "one owner's charge is computed only from their own shells"
    )


def test_chargeback_input_set_covers_only_live_sandbox_and_dev_shells(
    api, instructor_headers_for, lms_admin_headers
):
    """PRD §3.3: "The billable set is that person's shells whose `shell_type` is `SANDBOX`
    or `DEV` and whose `provisioning_state` is neither `REJECTED` nor `PURGED`; `OFFICIAL`
    shells are never charged."
    PRD §3.3: "For each shell, subtract a free allowance of 100.00 megabytes from its
    `storage_mb` and treat any negative result as zero; multiply the remainder by a rate
    of 0.0150 US dollars per megabyte; multiply again by the class multiplier, which is
    1.00 for a `SANDBOX` shell and 0.50 for a `DEV` shell; then round that single shell's
    charge half up to two decimal places."
    PRD §3.3: "`REJECT` moves `REQUESTED` → `REJECTED`, which is terminal: it requires
    only that the shell still be `REQUESTED`, records the supplied reason into
    `reject_reason`, sets the shell's `storage_mb` to 0.00, and recomputes the owner's
    `sandbox_storage_charge_usd` — necessarily downward, since a rejected shell stops
    being billable."

    Design: Corner/calculations/chargeback_input_set_covers_only_live_sandbox_and_dev_shells
    """
    term = create_term(api)
    owner = create_faculty(api)
    owner_headers = instructor_headers_for(owner["id"])

    official = request_shell(api, term["id"], owner["id"], shell_type="OFFICIAL")
    first_sandbox = request_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1
    )
    second_sandbox = request_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1
    )

    # 500.00 MB on an OFFICIAL shell is never billable.
    create_content_item(
        api, official["id"], owner_headers,
        item_type="FILE", title="Official Media", points_possible=0.00, storage_mb=500.00,
    )
    assert read_shell(api, official["id"])["storage_mb"] == _money(500.00)
    assert read_person(api, owner["id"])["sandbox_storage_charge_usd"] == _money(0.00)

    # (210.00 - 100.00) * 0.0150 * 1.00 = 1.65.
    create_content_item(
        api, first_sandbox["id"], owner_headers,
        item_type="FILE", title="Scratch One", points_possible=0.00, storage_mb=210.00,
    )
    assert read_person(api, owner["id"])["sandbox_storage_charge_usd"] == _money(1.65)

    # (400.00 - 100.00) * 0.0150 * 1.00 = 4.50, so the total becomes 6.15.
    create_content_item(
        api, second_sandbox["id"], owner_headers,
        item_type="FILE", title="Scratch Two", points_possible=0.00, storage_mb=400.00,
    )
    assert read_person(api, owner["id"])["sandbox_storage_charge_usd"] == _money(6.15)

    rejected = provisioning_decision(
        api, second_sandbox["id"], "REJECT", lms_admin_headers, reason="duplicate request"
    )
    assert rejected["provisioning_state"] == "REJECTED"
    assert rejected["storage_mb"] == _money(0.00)
    assert read_person(api, owner["id"])["sandbox_storage_charge_usd"] == _money(1.65), (
        "a rejected shell leaves the billable set entirely"
    )


def test_placement_exposure_points_stop_climbing_at_the_exposure_cap(api):
    """PRD §3.7: "The exposure points are the `active_placement_count` multiplied by 3,
    capped at 15."
    PRD §3.7: "The raw total is the sum of those five, and the stored `risk_score` is that
    total clamped into the range from 0.00 to 100.00 and then rounded half up to two
    decimal places — rounded **once**, after clamping, never per addend."
    PRD §3.7: "The PII points are the `pii_tier` multiplied by 10, so 0 through 30."
    PRD §3.7: "The scope points are 0 for `NONE`, 10 for `ROSTER_ONLY`, 25 for
    `ROSTER_AND_GRADES` and 40 for `FULL_PROFILE`."
    PRD §3.7: "The accessibility-gap points are 100 minus the `vpat_score`, multiplied by
    0.30."
    PRD §3.7: "The conformance points are 20 for `NONE`, 10 for `A`, 0 for `AA` and
    **minus 5** for `AAA` — the top conformance level earns a credit, which is why the raw
    total can go below zero."
    PRD §3.7: "The score is recomputed and persisted whenever the review is finalized,
    whenever a placement becomes active or is removed, and whenever the tool is suspended."
    PRD §3.7: "A new tool opens with `approval_state` `DRAFT`, `privacy_review_state`
    `PENDING`, `accessibility_review_state` `PENDING`, `risk_score` null,
    `approved_version` null, `active_placement_count` 0 and `suspension_reason` null."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension is
    `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is below
    40.00; `approved_version` is set to the tool's current `tool_version`."
    PRD §3.7: "Activation pins `pinned_tool_version` to the tool's `approved_version`,
    raises the tool's `active_placement_count` by one, re-scores the tool, and re-derives
    the shell's `publish_readiness`."

    Design: Corner/calculations/placement_exposure_points_stop_climbing_at_the_declared_exposure_cap
    """
    # Every metadata addend is worth zero, so risk_score is pure exposure.
    tool = register_tool(
        api, data_sharing_scope="NONE", pii_tier=0, vpat_score=100.00,
        wcag_level="AA", tool_version="3.0.0",
    )
    assert tool["approval_state"] == "DRAFT"
    assert tool["risk_score"] is None
    assert tool["active_placement_count"] == 0

    transition_tool(api, tool["id"], "OPEN_REVIEW")
    file_review(api, tool["id"], "PRIVACY", "CLEAR")
    file_review(api, tool["id"], "ACCESSIBILITY", "CLEAR")
    finalized = transition_tool(api, tool["id"], "FINALIZE_REVIEW")
    assert finalized["approval_state"] == "APPROVED"
    assert finalized["approved_version"] == "3.0.0"
    assert finalized["risk_score"] == _money(0.00), (
        "0 PII + 0 scope + 0.00 accessibility gap + 0 conformance + 0 exposure"
    )

    term = create_term(api)
    owner = create_faculty(api)
    shells = [provision_shell(api, term["id"], owner["id"], base_seat_cap=1) for _ in range(6)]

    for shell in shells[:4]:
        active_placement(api, tool["id"], shell["id"])
    after_four = read_tool(api, tool["id"])
    assert after_four["active_placement_count"] == 4
    assert after_four["risk_score"] == _money(12.00), "4 placements times 3 is still under the cap"

    active_placement(api, tool["id"], shells[4]["id"])
    after_five = read_tool(api, tool["id"])
    assert after_five["active_placement_count"] == 5
    assert after_five["risk_score"] == _money(15.00), "5 placements times 3 lands exactly on the cap"

    last = active_placement(api, tool["id"], shells[5]["id"])
    after_six = read_tool(api, tool["id"])
    assert after_six["active_placement_count"] == 6
    assert after_six["risk_score"] == _money(15.00), (
        "the sixth placement cannot push exposure points past 15"
    )
    assert after_six["approval_state"] == "APPROVED", (
        "0.00 through 15.00 stays below the 40.00 conditional threshold"
    )
    assert last["pinned_tool_version"] == "3.0.0"


def test_purge_becomes_due_exactly_at_the_retention_instant_and_not_one_second_earlier(
    api, instructor_headers_for, registrar_headers
):
    """PRD §3.3: "Second, the logical clock must have reached or passed the term's
    `retention_purge_at`; an early attempt is refused with `ERR_PURGE_NOT_DUE`."
    PRD §3.3: "Purging sets every content item of the shell to `copy_state` `SKIPPED` with
    `storage_mb` 0.00, sets the shell's own `content_item_count` to 0, its
    `total_points_possible` to 0.00 and its `storage_mb` to 0.00, and recomputes the
    owner's `sandbox_storage_charge_usd`."
    PRD §3.3: "`CONCLUDED` → `ARCHIVED` requires the shell's term to have reached `CLOSED`
    or `ARCHIVED` (`ERR_INVALID_STATE_TRANSITION`)."
    PRD §3.1: "A grace period of 0 days is legal and collapses `student_access_end_at`
    onto the term's own end date at 23:59:59, so a student read at exactly that instant
    still succeeds while one instant later fails with `ERR_STUDENT_ACCESS_EXPIRED`."
    PRD §3.1: "Second, choose a retention horizon from `retention_class`: 365 days for
    `STANDARD`, 1825 days for `EXTENDED`, and no horizon at all for `LEGAL_HOLD`."

    Design: Corner/calculations/purge_becomes_due_exactly_at_the_retention_instant_and_not_one_second_earlier
    """
    term = create_term(
        api,
        term_start_at="2026-08-24T00:00:00Z",
        term_end_at="2026-12-11T00:00:00Z",
        access_grace_days=0,
        retention_class="STANDARD",
    )
    assert _instant(term["retention_purge_at"]) == _instant("2027-12-11T23:59:59Z")

    # Registration opens while the term still has no shells, so rollover is complete.
    walk_term_to(api, term["id"], "IN_SESSION")
    owner = create_faculty(api)
    shell = provision_shell(api, term["id"], owner["id"])
    item = create_content_item(
        api, shell["id"], instructor_headers_for(owner["id"]),
        item_type="FILE", title="Course Media", points_possible=0.00, storage_mb=250.00,
    )

    transition_term(api, term["id"], "FINALS")
    transition_term(api, term["id"], "GRADING")
    transition_term(api, term["id"], "CLOSED")
    assert read_shell(api, shell["id"])["provisioning_state"] == "CONCLUDED"

    archived = transition_shell(api, shell["id"], "ARCHIVED")
    assert archived["provisioning_state"] == "ARCHIVED"
    assert archived["storage_mb"] == _money(250.00)

    advance_clock(api, "2027-12-11T23:59:58Z")
    validate_error(
        api.shell_lifecycle_transition(shell["id"], {"target_state": "PURGED"}, registrar_headers),
        "ERR_PURGE_NOT_DUE",
    )
    assert read_shell(api, shell["id"])["provisioning_state"] == "ARCHIVED"

    advance_clock(api, "2027-12-11T23:59:59Z")
    purged = transition_shell(api, shell["id"], "PURGED")
    assert purged["provisioning_state"] == "PURGED", "the horizon instant itself is due"
    assert purged["storage_mb"] == _money(0.00)
    assert purged["content_item_count"] == 0
    assert purged["total_points_possible"] == _money(0.00)

    purged_item = read_content_item(api, item["id"])
    assert purged_item["copy_state"] == "SKIPPED"
    assert purged_item["storage_mb"] == _money(0.00)


def test_posture_change_propagates_a_new_overflow_allowance_to_every_shell(api):
    """PRD §3.4: "Step one derives the overflow ratio from the *term's*
    `continuity_posture` and from nothing else: 0.00 under `NORMAL`, 0.10 under
    `ELEVATED`, and 0.20 under `CONTINUITY_MODE`. The overflow allowance is the shell's
    `base_seat_cap` multiplied by that ratio and rounded **down** to a whole seat. Step
    two freezes `effective_seat_cap` at `base_seat_cap` plus that allowance, and that
    frozen value governs the entire run — it is never recomputed between individual
    promotions inside one run."
    PRD §3.4: "The capacity rule is evaluated on every enrollment create, on every drop
    that frees a seat, on every applied SIS operation in array order, on both directions of
    a cross-list merge, and whenever the term's `continuity_posture` changes, since the
    ratio moves with it."
    PRD §3.9: "And it **relaxes seat capacity**: the overflow ratio of §3.4 is read
    straight off the posture, so escalating a term to `ELEVATED` or `CONTINUITY_MODE`
    widens the `effective_seat_cap` of every shell in it, and de-escalating narrows it
    again."
    PRD §3.9: "It escalates again `ELEVATED` → `CONTINUITY_MODE`, which requires at least
    one window of that term whose `kind` is `OUTAGE` and whose `window_state` is `OPEN` to
    exist, otherwise `ERR_INVALID_STATE_TRANSITION` — the highest posture must be justified
    by a live outage on the record."
    PRD §3.9: "Creating a window increments the **term's** `version` by one, which is what
    makes two clients racing to open windows against the same term visible to each other."
    PRD §3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty days after
    the term's `term_end_at` for a `SANDBOX` or `DEV` shell while remaining null for an
    `OFFICIAL` one."

    Design: Corner/calculations/a_posture_change_propagates_a_new_overflow_allowance_to_every_shell_in_the_term
    """
    term = create_term(api)
    walk_term_to(api, term["id"], "IN_SESSION")
    owner = create_faculty(api)
    small = provision_shell(api, term["id"], owner["id"], base_seat_cap=10)
    large = provision_shell(api, term["id"], owner["id"], base_seat_cap=25)
    assert small["effective_seat_cap"] == 10, "a NORMAL term grants no allowance at all"
    assert large["effective_seat_cap"] == 25

    elevated = change_posture(api, term["id"], "ELEVATED")
    assert elevated["continuity_posture"] == "ELEVATED"
    small_elevated = read_shell(api, small["id"])
    large_elevated = read_shell(api, large["id"])
    assert small_elevated["effective_seat_cap"] == 11, "floor(10 * 0.10) is 1"
    assert large_elevated["effective_seat_cap"] == 27, "floor(25 * 0.10) is 2"
    assert small_elevated["base_seat_cap"] == 10, "the SIS base cap is never rewritten"
    assert large_elevated["base_seat_cap"] == 25

    before_window = read_term(api, term["id"])
    window = open_window(
        api, before_window, "OUTAGE", "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z"
    )
    assert window["window_state"] == "OPEN"
    after_window = read_term(api, term["id"])
    assert after_window["version"] == before_window["version"] + 1

    continuity = change_posture(api, term["id"], "CONTINUITY_MODE")
    assert continuity["continuity_posture"] == "CONTINUITY_MODE"
    small_continuity = read_shell(api, small["id"])
    large_continuity = read_shell(api, large["id"])
    assert small_continuity["effective_seat_cap"] == 12, "floor(10 * 0.20) is 2"
    assert large_continuity["effective_seat_cap"] == 30, "floor(25 * 0.20) is 5"
    assert small_continuity["base_seat_cap"] == 10
    assert large_continuity["base_seat_cap"] == 25

    # The widened cap is stored, not derived per read.
    assert read_shell(api, large["id"])["effective_seat_cap"] == 30
