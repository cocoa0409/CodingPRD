"""Entity-level PRD compliance: creates, defaults, reads, listings, system
fields, type constraints, immutability, not-found codes and body foreign keys.

The runner relaunches the API server before every test, so each test builds all
of its own preconditions and the logical clock always starts at
2026-08-01T00:00:00Z.
"""
import re
from datetime import datetime, timezone

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    factories as fac,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import PRIVACY_REVIEWER_USER_ID

#: A syntactically valid UUID that is never minted by any of these tests.
MISSING_UUID = "00000000-0000-4000-8000-0000000000f2"

_THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


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


def instant(text):
    return parse_instant(text)


def test_academic_term_create_echoes_inputs_and_mints_the_retention_calendar(
    api, registrar_headers
):
    """PRD §3.1: "A newly registered term opens with `lifecycle_state` `PLANNING`
    and `continuity_posture` `NORMAL`, and with every aggregate counter at its
    floor: `published_shell_count`, `overflow_shell_count`,
    `total_active_enrollments`, `open_amendment_count` and `sis_sync_epoch` all
    read 0, while `rollover_completion_pct` reads 100.00 for the reason explained
    in §3.2."
    PRD §3.1: "For a term ending `2026-12-11T00:00:00Z` with 30 grace days,
    `student_access_end_at` is `2027-01-10T23:59:59Z`; under `STANDARD` the purge
    horizon is `2028-01-10T23:59:59Z`, and under `EXTENDED` it is
    `2032-01-09T23:59:59Z`, the day-of-month shifting because 1825 days spans a
    leap day."
    PRD §2.4: "Every persisted record in the service carries an `id`: a
    server-minted UUID with no type prefix and no embedded meaning."

    Design: Corner/entities/academic_term_creation_echoes_every_input_and_mints_the_computed_calendar
    """
    payload = {
        "term_code": "2026FA",
        "term_start_at": "2026-08-24T00:00:00Z",
        "term_end_at": "2026-12-11T00:00:00Z",
        "add_drop_deadline_at": "2026-09-07T00:00:00Z",
        "finals_window_start_at": "2026-12-04T00:00:00Z",
        "finals_window_end_at": "2026-12-11T00:00:00Z",
        "access_grace_days": 30,
        "retention_class": "STANDARD",
    }
    term = validate_success(api.create_academic_term(payload, registrar_headers), 201)

    assert term["term_code"] == "2026FA"
    assert term["lifecycle_state"] == "PLANNING", "both state dimensions start declared"
    assert term["continuity_posture"] == "NORMAL"
    assert parse_instant(term["term_start_at"]) == instant("2026-08-24T00:00:00Z")
    assert parse_instant(term["term_end_at"]) == instant("2026-12-11T00:00:00Z")
    assert parse_instant(term["add_drop_deadline_at"]) == instant("2026-09-07T00:00:00Z")
    assert parse_instant(term["finals_window_start_at"]) == instant("2026-12-04T00:00:00Z")
    assert parse_instant(term["finals_window_end_at"]) == instant("2026-12-11T00:00:00Z")
    assert term["access_grace_days"] == 30
    assert term["retention_class"] == "STANDARD"

    assert parse_instant(term["student_access_end_at"]) == instant(
        "2027-01-10T23:59:59Z"
    ), "student_access_end_at is computed at create time, not lazily"
    assert parse_instant(term["retention_purge_at"]) == instant(
        "2028-01-10T23:59:59Z"
    ), "STANDARD adds a 365-day horizon to student_access_end_at"

    assert term["rollover_completion_pct"] == 100.00
    assert term["published_shell_count"] == 0
    assert term["overflow_shell_count"] == 0
    assert term["total_active_enrollments"] == 0
    assert term["open_amendment_count"] == 0
    assert term["sis_sync_epoch"] == 0
    assert term["version"] == 1
    assert "_" not in term["id"] and len(term["id"]) == 36, (
        f"id must be a bare UUID with no type prefix, got {term['id']!r}"
    )


def test_academic_term_optional_calendar_fields_take_their_declared_defaults(
    api, registrar_headers
):
    """PRD §3.1: "`add_drop_deadline_at` is the last instant at which a dropped
    enrollment may be reinstated, and defaults to fourteen days after
    `term_start_at`."
    PRD §3.1: "`finals_window_start_at` defaults to seven days before
    `term_end_at`, and `finals_window_end_at` defaults to `term_end_at` itself;
    the latter may equal `term_end_at` but may never fall after it."
    PRD §3.1: "`access_grace_days` is the number of days of read access students
    keep after the term ends; it defaults to 30 and must be at least 0 and at
    most 365."
    PRD §3.1: "Finally, `retention_class` selects the retention schedule and
    defaults to `STANDARD`, the alternatives being `EXTENDED` and `LEGAL_HOLD`."
    PRD §3.1: "First, take the calendar date reached by advancing `term_end_at`
    forward by `access_grace_days` whole days, and set `student_access_end_at` to
    that date at 23:59:59 UTC — a fixed wall time with no sub-second component."

    Design: Corner/entities/academic_term_defaults_derive_the_add_drop_and_finals_calendar_from_term_bounds
    """
    payload = {
        "term_code": "2027SP",
        "term_start_at": "2027-01-11T00:00:00Z",
        "term_end_at": "2027-05-07T00:00:00Z",
    }
    term = validate_success(api.create_academic_term(payload, registrar_headers), 201)

    assert parse_instant(term["add_drop_deadline_at"]) == instant(
        "2027-01-25T00:00:00Z"
    ), "add_drop_deadline_at defaults to term_start_at + 14 days"
    assert parse_instant(term["finals_window_start_at"]) == instant(
        "2027-04-30T00:00:00Z"
    ), "finals_window_start_at defaults to term_end_at - 7 days"
    assert parse_instant(term["finals_window_end_at"]) == instant(
        "2027-05-07T00:00:00Z"
    ), "finals_window_end_at defaults to term_end_at itself"
    assert term["access_grace_days"] == 30
    assert term["retention_class"] == "STANDARD"
    assert parse_instant(term["student_access_end_at"]) == instant(
        "2027-06-06T23:59:59Z"
    ), "the default grace period feeds the retention calendar in the same request"


def test_course_shell_read_returns_the_stored_row_with_its_derived_seat_fields(
    api, lms_admin_headers, instructor_headers_for
):
    """PRD §3.3: "The new shell opens in `provisioning_state` `REQUESTED`, its
    `effective_seat_cap` seeded from the term's current `continuity_posture` by the
    capacity rule of §3.4, its `sandbox_expires_at` set to sixty days after the
    term's `term_end_at` when the class is `SANDBOX` or `DEV` and left null for
    `OFFICIAL`, and the term's `rollover_completion_pct` recomputed to account for
    the new eligible shell."
    PRD §3.4: "Step one derives the overflow ratio from the *term's*
    `continuity_posture` and from nothing else: 0.00 under `NORMAL`, 0.10 under
    `ELEVATED`, and 0.20 under `CONTINUITY_MODE`."
    PRD §3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty
    days after the term's `term_end_at` for a `SANDBOX` or `DEV` shell while
    remaining null for an `OFFICIAL` one."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."

    Design: Corner/entities/course_shell_retrieval_returns_the_stored_row_with_its_derived_seat_fields
    """
    term = fx.create_term(api)
    owner = fx.create_faculty(api)
    created = fx.request_shell(
        api, term["id"], owner["id"], shell_type="OFFICIAL", base_seat_cap=40
    )

    before = validate_success(api.get_course_shell(created["id"], lms_admin_headers))
    assert before["id"] == created["id"]
    assert before["provisioning_state"] == "REQUESTED"
    assert before["term_id"] == term["id"]
    assert before["owner_person_id"] == owner["id"]
    assert before["base_seat_cap"] == 40
    assert before["effective_seat_cap"] == 40, (
        "a NORMAL term contributes a 0.00 overflow ratio, so the seeded cap is the base cap"
    )
    assert before["sandbox_expires_at"] is None, "OFFICIAL shells never expire"
    assert before["version"] == 1

    fx.provisioning_decision(api, created["id"], "APPROVE")

    after = validate_success(
        api.get_course_shell(created["id"], instructor_headers_for(owner["id"]))
    )
    assert after["provisioning_state"] == "PROVISIONED"
    assert after["base_seat_cap"] == 40
    assert after["effective_seat_cap"] == 40
    assert after["publish_readiness"] is True
    assert after["sandbox_expires_at"] is None
    assert after["active_enrollment_count"] == 0
    assert after["waitlisted_enrollment_count"] == 0
    assert after["storage_mb"] == 0.00, "no content items have been added yet"
    assert after["version"] == 2, "the provisioning decision is one mutation"
    assert after["created_at"] == before["created_at"], "created_at never moves"


def test_course_shell_listing_filters_by_term_and_paginates(api, lms_admin_headers):
    """PRD §2.3: "Every collection endpoint accepts two optional query parameters.
    `limit` caps the number of records returned; it defaults to 10, may not be
    smaller than 1, and may not be larger than 100. `offset` names how many records
    to skip before the page begins and defaults to 0. Both values are echoed back
    in the `meta` object of the envelope, alongside `total_count` (the number of
    records matching the filter before the page window is applied) and `has_more`
    (true when records remain beyond the current window)."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable."

    Design: Corner/entities/course_shell_listing_filters_by_term_and_shell_type_and_paginates
    """
    term_a = fx.create_term(api)
    term_b = fx.create_term(api)
    owner = fx.create_faculty(api)
    first = fx.request_shell(api, term_a["id"], owner["id"])
    second = fx.request_shell(api, term_a["id"], owner["id"])
    third = fx.request_shell(api, term_a["id"], owner["id"])
    other_term_shell = fx.request_shell(api, term_b["id"], owner["id"])

    rows, meta = validate_paginated(
        api.list_course_shells(
            lms_admin_headers, {"term_id": term_a["id"], "limit": 2, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "the page window follows created_at ascending"
    )
    assert meta["total_count"] == 3, (
        "total_count counts the filtered set before the window, not the whole table"
    )
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows2, meta2 = validate_paginated(
        api.list_course_shells(
            lms_admin_headers, {"term_id": term_a["id"], "limit": 2, "offset": 2}
        )
    )
    assert [row["id"] for row in rows2] == [third["id"]]
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2
    assert other_term_shell["id"] not in [row["id"] for row in rows + rows2], (
        "the term_id filter excludes shells of every other term"
    )

    defaults, default_meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, {"term_id": term_a["id"]})
    )
    assert default_meta["limit"] == 10, "limit defaults to 10"
    assert default_meta["offset"] == 0, "offset defaults to 0"
    assert default_meta["has_more"] is False
    assert [row["id"] for row in defaults] == [
        first["id"], second["id"], third["id"]
    ]


def test_content_item_create_requires_shell_id_and_title(api, lms_admin_headers):
    """PRD §2.10 band 6: "Request shape, on every endpoint — otherwise
    `ERR_INVALID_REQUEST`. This band covers: every required input field present;
    every enum value a declared member; every number inside its declared range;
    every datetime parseable as ISO 8601 UTC; `term_end_at` strictly after
    `term_start_at`; `finals_window_end_at` equal to or before `term_end_at`;
    `window_end` strictly after `window_start`; a merge request's `child_shell_id`
    different from its `parent_shell_id`; `points_possible` equal to 0 on a `PAGE`
    or `FILE` item; `conditions_note` present when a review `decision` is
    `CONDITIONS`; and `adjusted_earned_points` present and at least 0 when a
    dispute resolution `outcome` is `CHANGED`."
    PRD §3.6: "An `Instructor` or an `LmsAdmin` adds an item by naming `shell_id`,
    an `item_type` of `ASSIGNMENT`, `QUIZ`, `PAGE` or `FILE`, and a `title`,
    optionally with a `due_at`, a `points_possible` and a `storage_mb`."
    PRD §3.6: "A new item opens with `copy_state` `SOURCE`, `date_stripped` false,
    `submission_count` 0, `has_submissions` false and `source_item_id` null — the
    last field is the copy-provenance self-reference, filled in only on rollover
    copies."
    PRD §3.6: "`PAGE` and `FILE` items carry `points_possible` 0.00 and never
    contribute points."

    Design: Corner/entities/content_item_create_missing_required_shell_id_returns_invalid_request
    """
    setup = fx.provisioned_shell_setup(api)
    shell_id = setup["shell"]["id"]

    validate_error(
        api.create_content_item(
            {"item_type": "PAGE", "title": "Syllabus"}, lms_admin_headers
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_content_item(
            {"shell_id": shell_id, "item_type": "PAGE"}, lms_admin_headers
        ),
        "ERR_INVALID_REQUEST",
    )

    item = validate_success(
        api.create_content_item(
            {"shell_id": shell_id, "item_type": "PAGE", "title": "Syllabus"},
            lms_admin_headers,
        ),
        201,
    )
    assert item["shell_id"] == shell_id
    assert item["item_type"] == "PAGE"
    assert item["title"] == "Syllabus"
    assert item["copy_state"] == "SOURCE"
    assert item["date_stripped"] is False
    assert item["submission_count"] == 0
    assert item["has_submissions"] is False
    assert item["source_item_id"] is None
    assert item["points_possible"] == 0, "PAGE items carry points_possible 0.00"
    assert item["version"] == 1


def test_course_shell_seat_fields_are_computed_from_enrollment_rows_not_from_input(
    api, registrar_headers, lms_admin_headers
):
    """PRD §2.10 band 6: "Unknown keys in a payload are ignored rather than
    rejected."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is
    `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD §3.4: "Only in step five are the observables recomputed:
    `seat_utilization_pct` becomes `active_enrollment_count` divided by
    `base_seat_cap`, multiplied by 100, rounded half up to two decimal places, and
    `overflow_flag` becomes true exactly when `active_enrollment_count` is greater
    than `base_seat_cap`."
    PRD §3.4: "Only rows whose `role` is `STUDENT` participate in any of this —
    `TEACHER`, `TA`, `DESIGNER` and `OBSERVER` rows never consume a seat and never
    appear on a waitlist."

    Design: Corner/entities/course_shell_seat_fields_are_computed_from_enrollment_rows_not_from_input
    """
    setup = fx.provisioned_shell_setup(
        api,
        "IN_SESSION",
        shell_overrides={
            "base_seat_cap": 8,
            "active_enrollment_count": 99,
            "seat_utilization_pct": 77.00,
        },
    )
    shell_id = setup["shell"]["id"]
    seeded = validate_success(api.get_course_shell(shell_id, lms_admin_headers))
    assert seeded["active_enrollment_count"] == 0, (
        "seat observables come from enrollment rows, so a supplied count is ignored"
    )
    assert seeded["seat_utilization_pct"] == 0.00
    assert seeded["overflow_flag"] is False

    first_student = fx.create_student(api)
    first = validate_success(
        api.create_enrollment(
            fac.create_enrollment_payload(shell_id, first_student["id"]),
            registrar_headers,
        ),
        201,
    )
    assert first["enrollment_state"] == "ACTIVE", (
        "an omitted requested_state comes in through the live-seat door"
    )

    second_student = fx.create_student(api)
    fx.enrol(api, shell_id, second_student["id"])
    after_two = validate_success(api.get_course_shell(shell_id, lms_admin_headers))
    assert after_two["active_enrollment_count"] == 2
    assert after_two["seat_utilization_pct"] == 25.00, "2 of 8 seats is 25.00 percent"
    assert after_two["overflow_flag"] is False

    teacher_row = fx.enrol(
        api, shell_id, setup["owner"]["id"], requested_state="ACTIVE", role="TEACHER"
    )
    assert teacher_row["enrollment_state"] == "ACTIVE"
    assert teacher_row["role"] == "TEACHER"

    after_teacher = validate_success(api.get_course_shell(shell_id, lms_admin_headers))
    assert after_teacher["active_enrollment_count"] == 2, (
        "a TEACHER row consumes no seat"
    )
    assert after_teacher["seat_utilization_pct"] == 25.00
    assert after_teacher["waitlisted_enrollment_count"] == 0

    term = fx.read_term(api, setup["term"]["id"])
    assert term["total_active_enrollments"] == 2, (
        "only STUDENT rows reach the term's seat ledger"
    )


def test_person_system_fields_are_server_minted_and_version_advances_on_every_write(
    api, registrar_headers
):
    """PRD §2.4: "Every persisted record in the service carries an `id`: a
    server-minted UUID with no type prefix and no embedded meaning."
    PRD §2.4: "Every record also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits recording when the row was first written."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."
    PRD §3.3: "Two compliance switches may be set at registration or adjusted
    later, together with the display name: `ferpa_block`, which defaults to false
    and when true forbids exporting that person's records to a third-party tool or
    to the registrar, and `access_revoked_at`, the instant at which LMS access was
    withdrawn, which stays null while access is live."
    PRD §3.3: "A person's `sandbox_storage_charge_usd` starts at 0.00 and is only
    ever written by the chargeback computation described later in this subsection."

    Design: Corner/entities/person_system_fields_are_server_minted_and_version_advances_on_every_write
    """
    payload = fac.create_person_payload(full_name="Ada Byron")
    created = validate_success(api.create_person(payload, registrar_headers), 201)

    assert created["sis_person_id"] == payload["sis_person_id"]
    assert created["version"] == 1
    assert created["ferpa_block"] is False
    assert created["access_revoked_at"] is None
    assert created["sandbox_storage_charge_usd"] == 0.00
    assert _THREE_FRACTIONAL_DIGITS.match(created["created_at"]), (
        f"created_at must carry three fractional digits, got {created['created_at']!r}"
    )
    assert "id" not in payload, "the client never supplies an id"
    assert len(created["id"]) == 36 and created["id"].count("-") == 4

    updated = validate_success(
        api.patch_person(
            created["id"], {"ferpa_block": True, "full_name": "Ada Lovelace"},
            registrar_headers,
        )
    )
    assert updated["id"] == created["id"], "the identifier is stable across writes"
    assert updated["created_at"] == created["created_at"], "created_at is write-once"
    assert updated["version"] == 2, "one mutation advances version by exactly one"
    assert updated["ferpa_block"] is True
    assert updated["full_name"] == "Ada Lovelace"
    assert updated["sis_person_id"] == payload["sis_person_id"]
    assert _THREE_FRACTIONAL_DIGITS.match(updated["updated_at"]), (
        f"updated_at uses the same format, got {updated['updated_at']!r}"
    )


def test_type_constraints_reject_undeclared_enums_and_out_of_range_numbers(
    api, registrar_headers, lms_admin_headers
):
    """PRD §2.10 band 6: "Request shape, on every endpoint — otherwise
    `ERR_INVALID_REQUEST`. This band covers: every required input field present;
    every enum value a declared member; every number inside its declared range;
    every datetime parseable as ISO 8601 UTC; `term_end_at` strictly after
    `term_start_at`; `finals_window_end_at` equal to or before `term_end_at`;
    `window_end` strictly after `window_start`; a merge request's `child_shell_id`
    different from its `parent_shell_id`; `points_possible` equal to 0 on a `PAGE`
    or `FILE` item; `conditions_note` present when a review `decision` is
    `CONDITIONS`; and `adjusted_earned_points` present and at least 0 when a
    dispute resolution `outcome` is `CHANGED`."
    PRD §3.3: "An optional `base_seat_cap` declares the SIS seat cap before any
    overflow allowance; it defaults to 25 and must be at least 1 and at most 2000."
    PRD §3.1: "`access_grace_days` is the number of days of read access students
    keep after the term ends; it defaults to 30 and must be at least 0 and at
    most 365."

    Design: Corner/entities/type_constraints_reject_undeclared_enums_and_out_of_range_numbers
    """
    term = fx.create_term(api)
    owner = fx.create_faculty(api)

    validate_error(
        api.create_course_shell(
            fac.create_course_shell_payload(
                term["id"], owner["id"], shell_type="PRACTICE"
            ),
            lms_admin_headers,
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], owner["id"], base_seat_cap=0),
            lms_admin_headers,
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], owner["id"], base_seat_cap=2001),
            lms_admin_headers,
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_academic_term(
            fac.create_academic_term_payload(access_grace_days=366), registrar_headers
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_academic_term(
            fac.create_academic_term_payload(
                term_start_at="2026-12-11T00:00:00Z", term_end_at="2026-08-24T00:00:00Z"
            ),
            registrar_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    edge_shell = validate_success(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], owner["id"], base_seat_cap=1),
            lms_admin_headers,
        ),
        201,
    )
    assert edge_shell["base_seat_cap"] == 1, "the inclusive lower bound is accepted"

    edge_term = validate_success(
        api.create_academic_term(
            fac.create_academic_term_payload(access_grace_days=365), registrar_headers
        ),
        201,
    )
    assert edge_term["access_grace_days"] == 365, (
        "the inclusive upper bound is accepted"
    )


def test_tool_review_is_immutable_with_no_version_field(
    api, lms_admin_headers, privacy_reviewer_headers
):
    """PRD §2.4: "There is one exception. `ToolReview` records are immutable review
    verdicts: they carry `id` and `created_at` only. Both `updated_at` and `version`
    are absent from a `ToolReview` response, there is no update operation for one,
    and a review is never rewritten — a re-review round produces new review records
    rather than editing the old ones."
    PRD §3.7: "A review row is a permanent record: it carries only its own
    identifier and its creation timestamp, it is never edited, never deleted and
    carries no row version of its own — the audit trail is append-only."
    PRD §2.1: "The server records it where a transition says so — as
    `submitted_by_user_id` and `decided_by_user_id` on a `MergeRequest`, and as
    `reviewer_user_id` on a `ToolReview` — and compares it to other recorded
    operator identifiers for segregation-of-duties purposes, but never compares it
    to any entity's `id`."

    Design: Corner/entities/tool_review_is_immutable_with_no_update_path_and_no_version_field
    """
    tool = fx.register_tool(api)
    fx.transition_tool(api, tool["id"], "OPEN_REVIEW")

    review = validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            privacy_reviewer_headers,
        ),
        201,
    )
    assert review["tool_id"] == tool["id"]
    assert review["dimension"] == "PRIVACY"
    assert review["decision"] == "CLEAR"
    assert review["reviewer_user_id"] == PRIVACY_REVIEWER_USER_ID, (
        "reviewer_user_id is taken from the acting X-User-ID"
    )
    assert _THREE_FRACTIONAL_DIGITS.match(review["created_at"])
    assert "version" not in review, "a ToolReview carries no row version of its own"
    assert "updated_at" not in review, "a ToolReview is never rewritten"

    fetched = validate_success(api.get_tool_review(review["id"], lms_admin_headers))
    assert fetched["id"] == review["id"]
    assert fetched["created_at"] == review["created_at"]
    assert fetched["reviewer_user_id"] == PRIVACY_REVIEWER_USER_ID
    assert "version" not in fetched
    assert "updated_at" not in fetched

    rows, meta = validate_paginated(
        api.list_tool_reviews(lms_admin_headers, {"tool_id": tool["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [review["id"]]
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


NOT_FOUND_PROBES = [
    ("get_academic_term", "ERR_TERM_NOT_FOUND", "lms_admin"),
    ("get_person", "ERR_PERSON_NOT_FOUND", "lms_admin"),
    ("get_course_shell", "ERR_SHELL_NOT_FOUND", "lms_admin"),
    ("get_enrollment", "ERR_ENROLLMENT_NOT_FOUND", "registrar"),
    ("get_sync_batch", "ERR_BATCH_NOT_FOUND", "registrar"),
    ("get_merge_request", "ERR_MERGE_REQUEST_NOT_FOUND", "lms_admin"),
    ("get_content_item", "ERR_CONTENT_ITEM_NOT_FOUND", "lms_admin"),
    ("get_rollover_job", "ERR_ROLLOVER_JOB_NOT_FOUND", "lms_admin"),
    ("get_tool_integration", "ERR_TOOL_NOT_FOUND", "lms_admin"),
    ("get_tool_review", "ERR_REVIEW_NOT_FOUND", "lms_admin"),
    ("get_tool_placement", "ERR_PLACEMENT_NOT_FOUND", "lms_admin"),
    ("get_grade_passback", "ERR_PASSBACK_NOT_FOUND", "lms_admin"),
    ("get_grade_dispute", "ERR_DISPUTE_NOT_FOUND", "registrar"),
    ("get_continuity_window", "ERR_WINDOW_NOT_FOUND", "lms_admin"),
]


@pytest.mark.parametrize("method_name,expected_error,role", NOT_FOUND_PROBES)
def test_every_path_id_not_found_returns_its_own_entity_specific_error_code(
    api, registrar_headers, lms_admin_headers, method_name, expected_error, role
):
    """PRD §2.4: "Path identifiers are validated left to right. A request whose path
    names a record that does not exist is rejected with the 404 code specific to
    that record type — `ERR_TERM_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`,
    `ERR_SHELL_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_MERGE_REQUEST_NOT_FOUND`, `ERR_CONTENT_ITEM_NOT_FOUND`,
    `ERR_ROLLOVER_JOB_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_PLACEMENT_NOT_FOUND`, `ERR_PASSBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    or `ERR_WINDOW_NOT_FOUND`."
    PRD §2.10 band 4: "Every identifier embedded in the path exists, checked left to
    right, on every path containing an identifier — otherwise the record-specific
    404 code from §2.4."

    Design: Corner/entities/every_path_id_not_found_returns_its_own_entity_specific_error_code
    """
    headers = registrar_headers if role == "registrar" else lms_admin_headers
    response = getattr(api, method_name)(MISSING_UUID, headers)
    validate_error(response, expected_error)


def test_body_foreign_keys_are_validated_in_declaration_order_left_to_right(
    api, lms_admin_headers
):
    """PRD §2.4: "Foreign keys supplied in a request body are resolved the same way
    and return the same record-specific codes, checked in the order the endpoint
    declares its input fields, so the first unresolvable reference decides the
    response."
    PRD §3.3: "An `LmsAdmin` requests a **course shell** by naming the term it
    belongs to through `term_id`, the instructor of record through
    `owner_person_id` — who must have a `primary_affiliation` of `FACULTY` or
    `STAFF` — the SIS section code as `sis_section_code`, and the governance class
    as `shell_type`, which is `OFFICIAL` for a real section, `SANDBOX` for an
    instructor's scratch space, or `DEV` for a development copy."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable."

    Design: Corner/entities/body_foreign_keys_are_validated_in_declaration_order_left_to_right
    """
    term = fx.create_term(api)
    owner = fx.create_faculty(api)

    validate_error(
        api.create_course_shell(
            fac.create_course_shell_payload(MISSING_UUID, NON_EXISTENT_UUID),
            lms_admin_headers,
        ),
        "ERR_TERM_NOT_FOUND",
    )
    validate_error(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], NON_EXISTENT_UUID),
            lms_admin_headers,
        ),
        "ERR_PERSON_NOT_FOUND",
    )

    shell = validate_success(
        api.create_course_shell(
            fac.create_course_shell_payload(term["id"], owner["id"]), lms_admin_headers
        ),
        201,
    )
    assert shell["term_id"] == term["id"]
    assert shell["owner_person_id"] == owner["id"]

    rows, meta = validate_paginated(
        api.list_course_shells(lms_admin_headers, {"owner_person_id": owner["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [shell["id"]]
