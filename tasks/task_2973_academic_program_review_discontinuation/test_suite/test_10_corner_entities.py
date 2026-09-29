"""Corner-index coverage of the entities section: envelopes, defaults, system
fields, append-only rows, per-term diagnostics, field constraints, parent
resolution and the one cross-cutting association."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_hr_partner_headers,
    make_program_chair_headers,
    make_provost_proposer_headers,
    make_review_coordinator_headers,
)

# The design index's own well-formed-but-unknown identifier.
UNKNOWN_ID = "11111111-2222-4333-8444-555555555555"

# The three Fixture A per-term diagnostics, in term_index order.
PER_TERM_CPH = constants.FIXTURE_A_PER_SNAPSHOT_CPH_CENTS


def test_program_create_returns_full_envelope_with_initial_derived_fields(api):
    """§3.1 registration returns 201 with the whole entity, including every
    derived field that has no input yet.

    §2.7 fixes those starting values exactly: ``snapshot_count`` 0, both
    cost-per-credit-hour figures null, ``composite_score`` null (not 0.00),
    ``viability_band`` ``INSUFFICIENT_DATA`` (not ``NONVIABLE``),
    ``discontinuation_override`` false, ``consolidated_into_program_id`` and
    ``catalog_status_pre_decision`` null, and every FTE aggregate at 0.00 rather
    than null. §3.11's walk over an empty appointment set leaves
    ``staffing_liability_cents`` at its running total of 0.

    Design: Corner/entities/program_create_returns_full_envelope_with_initial_derived_fields
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    response = api.create_program(
        factories.program_payload(
            code="HIST-BA",
            name="History BA",
            degree_level="UNDERGRADUATE",
            department_code="HIST",
            host_capacity_per_day=3,
        ),
        make_review_coordinator_headers(),
    )

    body = response.json()
    assertions.assert_envelope_meta(body)
    assertions.assert_object_response(body)

    program = validate_success(response, 201)

    # The supplied inputs are echoed verbatim.
    assert program["code"] == "HIST-BA"
    assert program["name"] == "History BA"
    assert program["degree_level"] == "UNDERGRADUATE"
    assert program["department_code"] == "HIST"
    assert program["host_capacity_per_day"] == 3

    # §2.4: a bare UUID and a version that begins at 1.
    assert is_valid_uuid(program["id"]), (
        f"program.id must be a bare UUID with no type prefix, got {program['id']!r}"
    )
    assertions.assert_audit_quartet(program, "program")
    assertions.assert_version_is(program, 1, "program")

    # §2.6 + §2.7: both axes at their initial values and every derived figure at
    # its declared start.
    assertions.assert_axes(program, lifecycle_state="ACTIVE", catalog_status="LISTED")
    assertions.assert_program_registration_defaults(program)
    assertions.assert_integer_cents(
        program["staffing_liability_cents"], "program.staffing_liability_cents"
    )
    assert program["staffing_liability_cents"] == 0


def test_program_get_by_id_returns_the_stored_row_unchanged(api):
    """§4's GET is a retrieval, so §2.4's version rule leaves the row alone.

    ``version`` refreshes only "on every mutation of that row", so a re-read
    still reports 1 and ``updated_at`` still reports the creation instant taken
    from the §2.5 logical clock.

    Design: Corner/entities/program_get_by_id_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    created = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=3,
    )

    response = api.get_program(created["id"], make_provost_proposer_headers())
    body = response.json()
    assertions.assert_object_response(body)
    program = validate_success(response, 200)

    assert program["id"] == created["id"]
    assert program["code"] == "HIST-BA"
    assert program["degree_level"] == "UNDERGRADUATE"
    assert program["host_capacity_per_day"] == 3

    # The GET did not mutate the row.
    assertions.assert_version_is(program, 1, "program")
    assertions.assert_instant_equals(
        program["created_at"], constants.CLOCK_STARTUP_DEFAULT, "program.created_at"
    )
    assertions.assert_instant_equals(
        program["updated_at"], program["created_at"], "program.updated_at"
    )
    assertions.assert_unchanged(
        created,
        program,
        ["id", "code", "name", "degree_level", "department_code", "version"],
        "program",
    )


def test_program_list_applies_filter_then_pagination_window(api):
    """§2.3: ``total_count`` counts the rows matching the filters *before* the
    page window is taken, and ``has_more`` is computed against that filtered
    count — not against the size of the table.

    Two of three programs sit in department HIST, so a ``department_code`` filter
    with ``limit`` 1 reports ``total_count`` 2 across two pages while the PHIL
    row never appears. An unfiltered, unpaginated call applies the declared
    defaults of ``limit`` 10 and ``offset`` 0 over all three rows.

    Design: Corner/entities/program_list_applies_filter_then_pagination_window
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    p1 = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    p2 = fixtures.create_program(
        api,
        code="HIST-MA",
        name="History MA",
        degree_level="GRADUATE",
        department_code="HIST",
    )
    p3 = fixtures.create_program(
        api,
        code="PHIL-BA",
        name="Philosophy BA",
        degree_level="UNDERGRADUATE",
        department_code="PHIL",
    )

    first_page, first_meta = validate_paginated(
        api.list_programs(
            make_review_coordinator_headers(),
            params={"department_code": "HIST", "limit": 1, "offset": 0},
        )
    )
    assert len(first_page) == 1
    assertions.assert_pagination_meta(
        first_meta, limit=1, offset=0, total_count=2, has_more=True
    )

    second_page, second_meta = validate_paginated(
        api.list_programs(
            make_review_coordinator_headers(),
            params={"department_code": "HIST", "limit": 1, "offset": 1},
        )
    )
    assert len(second_page) == 1
    assertions.assert_pagination_meta(
        second_meta, limit=1, offset=1, total_count=2, has_more=False
    )

    windowed_ids = {first_page[0]["id"], second_page[0]["id"]}
    assert windowed_ids == {p1["id"], p2["id"]}, (
        f"the two HIST pages must together return {p1['id']} and {p2['id']}, "
        f"got {sorted(windowed_ids)}"
    )
    assert p3["id"] not in windowed_ids, (
        "the PHIL program must appear on neither page of a HIST-filtered list"
    )

    # No filter and no pagination input: the §2.3 defaults apply over all rows.
    all_rows, all_meta = validate_paginated(
        api.list_programs(make_review_coordinator_headers())
    )
    assertions.assert_pagination_meta(
        all_meta,
        limit=constants.DEFAULT_LIMIT,
        offset=constants.DEFAULT_OFFSET,
        total_count=3,
        has_more=False,
    )
    assert len(all_rows) == 3


def test_program_get_unknown_uuid_returns_program_not_found(api):
    """§2.9 / §2.10 check 7: a well-formed but unknown path identifier is a 404
    naming the missing record type.

    The response is ``ERR_PROGRAM_NOT_FOUND`` at HTTP 404 per §5 — not a generic
    ``ERR_VALIDATION`` and not a 400 — and its ``meta`` carries only the two
    request fields §2.2 declares for an error envelope.

    Design: Corner/entities/program_get_unknown_uuid_returns_program_not_found
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    response = api.get_program(UNKNOWN_ID, make_provost_proposer_headers())

    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body['response_type']!r}"
    )
    assertions.assert_error_meta_is_minimal(body)

    error = validate_error(response, ERR_PROGRAM_NOT_FOUND, 404)
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"data.message must be a non-empty string, got {error.get('message')!r}"
    )


def test_program_create_missing_required_field_rejected(api):
    """§3.1 declares ``code``, ``name``, ``degree_level`` and ``department_code``
    as the inputs registration takes, and §2.10 check 9 covers "required fields
    being present".

    Omitting any one of them is ``ERR_VALIDATION`` at 422, and because the
    refusal happens at the body-schema step nothing at all is persisted.

    Design: Corner/entities/program_create_missing_required_field_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    missing_code = api.create_program(
        {
            "name": "History BA",
            "degree_level": "UNDERGRADUATE",
            "department_code": "HIST",
        },
        make_review_coordinator_headers(),
    )
    validate_error(missing_code, ERR_VALIDATION, 422)

    missing_name = api.create_program(
        {
            "code": "HIST-BA",
            "degree_level": "UNDERGRADUATE",
            "department_code": "HIST",
        },
        make_review_coordinator_headers(),
    )
    validate_error(missing_name, ERR_VALIDATION, 422)

    missing_degree_level = api.create_program(
        {"code": "HIST-BA", "name": "History BA", "department_code": "HIST"},
        make_review_coordinator_headers(),
    )
    validate_error(missing_degree_level, ERR_VALIDATION, 422)

    missing_department = api.create_program(
        {
            "code": "HIST-BA",
            "name": "History BA",
            "degree_level": "UNDERGRADUATE",
        },
        make_review_coordinator_headers(),
    )
    validate_error(missing_department, ERR_VALIDATION, 422)

    rows, meta = validate_paginated(api.list_programs(make_review_coordinator_headers()))
    assert meta["total_count"] == 0, (
        f"no partial row may be written by a rejected create, got "
        f"total_count {meta['total_count']}"
    )
    assert rows == []


def test_program_and_reviewer_defaults_applied_when_field_omitted(api):
    """The two declared input defaults are non-zero and the array default is the
    empty list.

    §3.1 defaults ``host_capacity_per_day`` to 2 and §3.4 defaults
    ``travel_buffer_hours`` to 48 and ``conflict_program_codes`` to empty, so an
    implementation that falls back to 0 or to null is detectable. §3.4 also fixes
    a newly registered reviewer's ``visit_count`` at 0.

    Design: Corner/entities/program_and_reviewer_defaults_applied_when_field_omitted
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = validate_success(
        api.create_program(
            factories.program_payload(
                code="HIST-BA",
                name="History BA",
                degree_level="UNDERGRADUATE",
                department_code="HIST",
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert program["host_capacity_per_day"] == constants.DEFAULT_HOST_CAPACITY_PER_DAY, (
        "§3.1 defaults host_capacity_per_day to 2 when the field is omitted, got "
        f"{program['host_capacity_per_day']!r}"
    )

    reviewer = validate_success(
        api.create_external_reviewer(
            factories.external_reviewer_payload(
                full_name="Dr Alice Reyes",
                institution="Northfield University",
                specialty_code="HIST",
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert reviewer["travel_buffer_hours"] == constants.DEFAULT_TRAVEL_BUFFER_HOURS, (
        "§3.4 defaults travel_buffer_hours to 48 when the field is omitted, got "
        f"{reviewer['travel_buffer_hours']!r}"
    )
    assert reviewer["conflict_program_codes"] == [], (
        "§3.4 defaults conflict_program_codes to an empty array, not null, got "
        f"{reviewer['conflict_program_codes']!r}"
    )
    assert reviewer["visit_count"] == 0


def test_program_create_mints_system_fields_server_side(api):
    """§2.4 mints ``id``, ``created_at``, ``updated_at`` and ``version`` on the
    server, and §2.6 fixes where the two axes begin.

    §4's create endpoint takes no state field at all, so ``ACTIVE`` and
    ``LISTED`` are the only possible starting values, ``id`` is a bare UUID with
    no type prefix, ``created_at`` carries exactly three fractional digits taken
    from the §2.5 logical clock, and ``version`` begins at 1.

    Design: Corner/entities/program_create_mints_system_fields_server_side
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = validate_success(
        api.create_program(
            factories.program_payload(
                code="HIST-BA",
                name="History BA",
                degree_level="UNDERGRADUATE",
                department_code="HIST",
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )

    assert is_valid_uuid(program["id"]), (
        f"program.id must be a server-minted bare UUID, got {program['id']!r}"
    )
    assert len(program["id"]) == 36, (
        f"program.id must be 36 characters with no type prefix, got {program['id']!r}"
    )
    assertions.assert_instant_precision(program["created_at"], "program.created_at")
    assertions.assert_instant_equals(
        program["created_at"], constants.CLOCK_STARTUP_DEFAULT, "program.created_at"
    )
    assertions.assert_instant_precision(program["updated_at"], "program.updated_at")
    assertions.assert_instant_equals(
        program["updated_at"], program["created_at"], "program.updated_at"
    )
    assertions.assert_version_is(program, 1, "program")
    assertions.assert_axes(program, lifecycle_state="ACTIVE", catalog_status="LISTED")


def test_metric_snapshot_is_immutable_and_append_only(api):
    """§2.4: a ``ViabilityMetricSnapshot`` is an immutable term observation, so it
    carries only ``id`` and ``created_at`` — ``updated_at`` and ``version`` are
    "absent from their payloads entirely".

    §4 offers no PATCH and no DELETE on any metric-snapshot path: the POST append
    is the only write, which is what makes §3.1's rolling window well defined.
    Each append raises the program's ``snapshot_count`` by 1.

    Design: Corner/entities/metric_snapshot_is_immutable_and_append_only
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )

    created = validate_success(
        api.create_metric_snapshot(
            program["id"],
            factories.metric_snapshot_payload(**constants.FIXTURE_A_SNAPSHOTS[0]),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assertions.assert_append_only_stamps(created, "snapshot")

    rows, meta = validate_paginated(
        api.list_metric_snapshots(
            program["id"],
            make_review_coordinator_headers(),
            params={"limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["id"] == created["id"]

    # The list projection carries the same two stamps and no others.
    assertions.assert_append_only_stamps(row, "snapshot row")
    assert "version" not in row, (
        "an append-only ViabilityMetricSnapshot must not expose version"
    )
    assert "updated_at" not in row, (
        "an append-only ViabilityMetricSnapshot must not expose updated_at"
    )

    refreshed = fixtures.read_program(api, program["id"])
    assert refreshed["snapshot_count"] == 1


def test_snapshot_per_term_cost_is_computed_and_never_feeds_program_rollup(api):
    """§3.1's most consequential arithmetic rule: each snapshot's
    ``cost_per_credit_hour_cents`` is "a diagnostic only and is never an input to
    any program-level figure".

    The three Fixture A terms diagnose 40000, 45833 and 55000 cents. The program's
    ``cost_per_credit_hour_rolling_cents`` must be the sum-then-divide value
    45946 — summing ``direct_cost_cents`` and ``credit_hours`` across the window
    first and rounding half up exactly once — and never 46944, the forbidden mean
    of the three rounded per-term diagnostics. The latest figure reads the newest
    observation alone, so it is 55000.

    Design: Corner/entities/snapshot_per_term_cost_is_computed_and_never_feeds_program_rollup
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    fixtures.append_snapshots(
        api, program["id"], constants.FIXTURE_A_SNAPSHOTS[:2]
    )

    third = validate_success(
        api.create_metric_snapshot(
            program["id"],
            factories.metric_snapshot_payload(**constants.FIXTURE_A_SNAPSHOTS[2]),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assertions.assert_integer_cents(
        third["cost_per_credit_hour_cents"], "snapshot.cost_per_credit_hour_cents"
    )
    assert third["cost_per_credit_hour_cents"] == PER_TERM_CPH[2], (
        "the newest term's diagnostic is 11000000 / 200 = 55000, got "
        f"{third['cost_per_credit_hour_cents']}"
    )

    rows, _meta = validate_paginated(
        api.list_metric_snapshots(program["id"], make_review_coordinator_headers())
    )
    by_term = {row["term_index"]: row for row in rows}
    assert sorted(by_term) == [1, 2, 3]
    assert by_term[1]["cost_per_credit_hour_cents"] == PER_TERM_CPH[0], (
        "term 1 diagnoses 12000000 / 300 = 40000, got "
        f"{by_term[1]['cost_per_credit_hour_cents']}"
    )
    assert by_term[2]["cost_per_credit_hour_cents"] == PER_TERM_CPH[1], (
        "term 2 diagnoses 11000000 / 240 = 45833.33 rounded half up to 45833, got "
        f"{by_term[2]['cost_per_credit_hour_cents']}"
    )

    refreshed = fixtures.read_program(api, program["id"])
    assert refreshed["snapshot_count"] == 3
    assert (
        refreshed["cost_per_credit_hour_rolling_cents"]
        == constants.FIXTURE_A_ROLLING_CPH_CENTS
    ), (
        "the rolling figure must sum first and divide last: 34000000 / 740 = 45946, "
        f"got {refreshed['cost_per_credit_hour_rolling_cents']}"
    )
    assert (
        refreshed["cost_per_credit_hour_rolling_cents"]
        != constants.FIXTURE_A_FORBIDDEN_AVERAGED_CPH_CENTS
    ), (
        "the rolling figure must not be the mean of the three per-term "
        "diagnostics (46944) — §3.1 forbids the divide-then-average order"
    )
    assert (
        refreshed["cost_per_credit_hour_latest_cents"]
        == constants.FIXTURE_A_LATEST_CPH_CENTS
    )


def test_enum_and_range_constraints_rejected_across_entities(api):
    """§2.10 check 9 collapses every declared field-constraint class onto one
    error id.

    An unknown enum member (``degree_level`` ``MASTERS`` against §3.1's three
    award levels), a bounded integer one past its ceiling
    (``market_demand_index`` 101 against "between 0 and 100 inclusive"), a
    decimal outside the declared interval (``fte`` 1.50 against "above 0 and at
    or below 1.00") and an ordering constraint between two datetime inputs
    (``window_end_at`` not "strictly after ``window_start_at``") are all
    ``ERR_VALIDATION`` at 422 — not four different identifiers. Because the
    refusal happens at the body-schema step, nothing is persisted and the
    rejected visit cascades nothing onto its cycle.

    Design: Corner/entities/enum_and_range_constraints_rejected_across_entities
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    cycle = fixtures.open_cycle(api, program["id"])
    self_study = fixtures.create_self_study(api, cycle["id"], program["id"])
    fixtures.accept_self_study(api, self_study["id"], program["id"])
    reviewer = fixtures.register_reviewer(api)

    # 1. An unknown enum member on program registration.
    bad_enum = api.create_program(
        factories.program_payload(
            code="PHIL-BA",
            name="Philosophy BA",
            degree_level="MASTERS",
            department_code="PHIL",
        ),
        make_review_coordinator_headers(),
    )
    validate_error(bad_enum, ERR_VALIDATION, 422)

    # 2. A bounded integer one past its declared ceiling.
    bad_range = api.create_metric_snapshot(
        program["id"],
        factories.metric_snapshot_payload(
            term_code="2025FA",
            term_index=1,
            enrollment_headcount=30,
            credit_hours=300,
            direct_cost_cents=12000000,
            completions_count=4,
            market_demand_index=101,
        ),
        make_review_coordinator_headers(),
    )
    validate_error(bad_range, ERR_VALIDATION, 422)

    # 3. A decimal outside the interval (0, 1.00].
    bad_fte = api.create_faculty_appointment(
        program["id"],
        factories.faculty_appointment_payload(
            faculty_number="F-ADJ-1",
            tenure_status="ADJUNCT",
            fte=1.50,
            annual_salary_cents=4000000,
        ),
        make_hr_partner_headers(),
    )
    validate_error(bad_fte, ERR_VALIDATION, 422)

    # 4. An ordering constraint between two datetime inputs.
    bad_order = api.create_reviewer_visit(
        factories.reviewer_visit_payload(
            cycle["id"],
            reviewer["id"],
            window_start_at="2026-08-22T17:00:00Z",
            window_end_at="2026-08-20T09:00:00Z",
        ),
        make_review_coordinator_headers(),
    )
    validate_error(bad_order, ERR_VALIDATION, 422)

    # Nothing was written by any of the four refusals.
    _programs, program_meta = validate_paginated(
        api.list_programs(make_review_coordinator_headers())
    )
    assert program_meta["total_count"] == 1, (
        "the rejected PHIL-BA create must not have been persisted"
    )
    refreshed = fixtures.read_program(api, program["id"])
    assert refreshed["snapshot_count"] == 0
    _visits, visit_meta = validate_paginated(
        api.list_reviewer_visits(make_review_coordinator_headers())
    )
    assert visit_meta["total_count"] == 0

    # The rejected visit did not cascade onto the cycle.
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_ACCEPTED"


def test_child_creation_under_unknown_parent_rejected(api):
    """§2.10 existence-checks path parents at check 7 and body foreign keys at
    check 8, and each reports the record type that is actually missing.

    An unknown program in the path of a review-cycle create is
    ``ERR_PROGRAM_NOT_FOUND``; an unknown cycle in the path of a self-study
    create is ``ERR_CYCLE_NOT_FOUND`` — §2.9 makes "the first identifier that
    resolves to nothing" decide the response; and a valid ``cycle_id`` with an
    unresolvable ``reviewer_id`` in a reviewer-visit body is
    ``ERR_REVIEWER_NOT_FOUND``, all at HTTP 404.

    Design: Corner/entities/child_creation_under_unknown_parent_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    cycle = fixtures.open_cycle(api, program["id"])
    self_study = fixtures.create_self_study(api, cycle["id"], program["id"])
    fixtures.accept_self_study(api, self_study["id"], program["id"])

    # Check 7 on the program segment of a nested create.
    unknown_program = api.create_review_cycle(
        UNKNOWN_ID,
        factories.review_cycle_payload(),
        make_review_coordinator_headers(),
    )
    validate_error(unknown_program, ERR_PROGRAM_NOT_FOUND, 404)

    # Check 7 on the cycle segment of a nested create.
    unknown_cycle = api.create_self_study(
        UNKNOWN_ID,
        factories.self_study_payload(narrative="Orphan self-study"),
        make_program_chair_headers(program["id"]),
    )
    validate_error(unknown_cycle, ERR_CYCLE_NOT_FOUND, 404)

    # Check 8 on a body foreign key: the cycle resolves, the reviewer does not.
    unknown_reviewer = api.create_reviewer_visit(
        factories.reviewer_visit_payload(cycle["id"], UNKNOWN_ID),
        make_review_coordinator_headers(),
    )
    validate_error(unknown_reviewer, ERR_REVIEWER_NOT_FOUND, 404)

    # None of the three refusals created or advanced anything.
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_ACCEPTED"
    _visits, visit_meta = validate_paginated(
        api.list_reviewer_visits(make_review_coordinator_headers())
    )
    assert visit_meta["total_count"] == 0
    _cycles, cycle_meta = validate_paginated(
        api.list_review_cycles(program["id"], make_review_coordinator_headers())
    )
    assert cycle_meta["total_count"] == 1


def test_reviewer_visit_associates_cycle_and_reviewer_across_the_hierarchy(api):
    """The one cross-cutting edge in the topology: a ``ReviewerVisit`` hangs off a
    ``ReviewCycle`` inside the program hierarchy while also pointing at the flat
    ``ExternalReviewer`` registry.

    §2.9 stamps neither foreign key from a path segment — both ``cycle_id`` and
    ``reviewer_id`` arrive in the body — and §2.3 declares both as filters on the
    same list channel, so the hierarchy side and the registry side must each be
    queryable. One reviewer with ``travel_buffer_hours`` 0 is booked onto two
    cycles belonging to two different programs, and §3.4 advances each cycle
    ``SELF_STUDY_ACCEPTED -> VISIT_SCHEDULED`` on its own first visit while the
    programs stay ``UNDER_REVIEW`` on the lifecycle axis.

    Design: Corner/entities/reviewer_visit_associates_cycle_and_reviewer_across_the_hierarchy
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    p1 = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    c1 = fixtures.open_cycle(api, p1["id"])
    ss1 = fixtures.create_self_study(api, c1["id"], p1["id"])
    fixtures.accept_self_study(api, ss1["id"], p1["id"])

    p2 = fixtures.create_program(
        api,
        code="PHIL-BA",
        name="Philosophy BA",
        degree_level="UNDERGRADUATE",
        department_code="PHIL",
    )
    c2 = fixtures.open_cycle(api, p2["id"])
    ss2 = fixtures.create_self_study(api, c2["id"], p2["id"])
    fixtures.accept_self_study(api, ss2["id"], p2["id"])

    reviewer = fixtures.register_reviewer(
        api,
        full_name="Dr Alice Reyes",
        institution="Northfield University",
        specialty_code="HUM",
        travel_buffer_hours=0,
    )
    v1 = fixtures.schedule_visit(
        api,
        c1["id"],
        reviewer["id"],
        window_start_at="2026-08-20T09:00:00Z",
        window_end_at="2026-08-22T17:00:00Z",
    )

    # The same reviewer is booked onto a cycle under a completely different
    # program, three weeks later, so no buffered window overlaps.
    v2 = validate_success(
        api.create_reviewer_visit(
            factories.reviewer_visit_payload(
                c2["id"],
                reviewer["id"],
                window_start_at="2026-09-10T09:00:00Z",
                window_end_at="2026-09-11T17:00:00Z",
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert v2["cycle_id"] == c2["id"]
    assert v2["reviewer_id"] == reviewer["id"]

    # The hierarchy side of the association.
    by_cycle, by_cycle_meta = validate_paginated(
        api.list_reviewer_visits(
            make_review_coordinator_headers(), params={"cycle_id": c1["id"]}
        )
    )
    assert by_cycle_meta["total_count"] == 1
    assertions.assert_id_order(by_cycle, [v1["id"]])

    # The registry side of the same association.
    by_reviewer, by_reviewer_meta = validate_paginated(
        api.list_reviewer_visits(
            make_review_coordinator_headers(), params={"reviewer_id": reviewer["id"]}
        )
    )
    assert by_reviewer_meta["total_count"] == 2
    assert {row["id"] for row in by_reviewer} == {v1["id"], v2["id"]}, (
        "a reviewer_id filter must reach both visits, across two different programs"
    )

    # Each cycle advanced on its own first visit; neither program's lifecycle
    # axis moved off UNDER_REVIEW.
    assert fixtures.read_cycle(api, c1["id"])["state"] == "VISIT_SCHEDULED"
    assert fixtures.read_cycle(api, c2["id"])["state"] == "VISIT_SCHEDULED"
    assertions.assert_axes(
        fixtures.read_program(api, p1["id"]), lifecycle_state="UNDER_REVIEW"
    )
    assertions.assert_axes(
        fixtures.read_program(api, p2["id"]), lifecycle_state="UNDER_REVIEW"
    )
