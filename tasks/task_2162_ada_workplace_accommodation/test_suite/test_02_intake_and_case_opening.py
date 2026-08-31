"""Opening an accommodation case: the profile pin, the open-case ceiling and
the version counter."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_STARTUP_DEFAULT,
    assert_accommodation_request,
    assert_documentation_budget_invariant,
    assert_three_fraction_digits,
    case_version,
    create_accommodation_request_payload,
    make_employee_headers,
    open_case,
    read_case,
    set_clock,
    setup_workforce,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_intake_pins_the_published_profile_and_its_version_label(api):
    """PRD §3.3: "The case copies the requesting employee's `job_profile_id` and
    copies that profile's `profile_version_label` into the case's own
    `pinned_profile_version_label`."
    PRD §3.3: "A new case is born in stage `INTAKE` with
    `confidentiality_posture` `STANDARD`, `decision` `PENDING`,
    `interactive_round_count` at zero, `cleared_option_count` at zero,
    `blocked_option_count` at zero, `review_cycle_index` at zero,
    `interactive_process_integrity_score` at 100, and `selected_option_id`,
    `renewal_of_request_id`, `review_cadence_days` and `review_due_date` all
    null."
    PRD §3.3: "Two optional inputs shape the case from the outset:
    `disability_obvious`, which defaults to false, and `absence_record_id`,
    which defaults to null and cross-references an existing leave or
    workers'-compensation record."
    PRD §3.3: "Opening also increments the employee's `open_case_count`, and an
    employee may not hold more than **two** cases open simultaneously — an
    intake that would push the count past two is refused with
    `ERR_OPEN_CASE_LIMIT`."
    PRD §3.3: "Start from a base allowance of **two** rounds."

    Design: Corner/entities/corner_accommodation_request_system_fields_pin_profile_version
    """
    set_clock()
    ctx = setup_workforce(department_code="CN7", profile_version_label="2026.7")

    payload = create_accommodation_request_payload(
        ctx["employee"]["id"],
        request_channel="HR_INITIATED",
        requested_accommodation_text="Corner accommodation seven",
    )
    payload.pop("disability_obvious")

    response = api.create_accommodation_request(payload, COORD)
    data = validate_success(response, 201)

    assert_accommodation_request(data)
    assert data["stage"] == "INTAKE"
    assert data["confidentiality_posture"] == "STANDARD"
    assert data["decision"] == "PENDING"
    assert data["job_profile_id"] == ctx["profile"]["id"]
    assert data["pinned_profile_version_label"] == "2026.7"
    assert data["disability_obvious"] is False, "disability_obvious defaults to false"
    assert data["absence_record_id"] is None
    assert data["selected_option_id"] is None
    assert data["renewal_of_request_id"] is None
    assert data["review_cadence_days"] is None
    assert data["review_due_date"] is None
    assert data["interactive_process_integrity_score"] == 100
    assert data["medical_doc_request_limit"] == 2
    assert data["documentation_budget_remaining"] == 2
    assert_documentation_budget_invariant(data)

    employee = validate_success(api.get_employee(ctx["employee"]["id"], COORD))
    assert employee["open_case_count"] == 1


def test_a_third_concurrent_case_breaches_the_open_case_ceiling(api):
    """PRD §3.3: "Opening also increments the employee's `open_case_count`, and
    an employee may not hold more than **two** cases open simultaneously — an
    intake that would push the count past two is refused with
    `ERR_OPEN_CASE_LIMIT`."

    Design: Corner/validations/corner_open_case_limit_blocks_third_concurrent_case
    """
    set_clock()
    ctx = setup_workforce(department_code="CNQ")

    for wording in ("First corner case", "Second corner case"):
        validate_success(
            api.create_accommodation_request(
                create_accommodation_request_payload(
                    ctx["employee"]["id"],
                    request_channel="HR_INITIATED",
                    requested_accommodation_text=wording,
                ),
                COORD,
            ),
            201,
        )

    third = api.create_accommodation_request(
        create_accommodation_request_payload(
            ctx["employee"]["id"],
            request_channel="HR_INITIATED",
            requested_accommodation_text="Third corner case",
        ),
        COORD,
    )
    validate_error(third, ApiErrorId.ERR_OPEN_CASE_LIMIT)

    employee = validate_success(api.get_employee(ctx["employee"]["id"], COORD))
    assert employee["open_case_count"] == 2

    _rows, meta = validate_paginated(
        api.list_accommodation_requests(COORD, {"employee_id": ctx["employee"]["id"]})
    )
    assert meta["total_count"] == 2


def test_skipping_documentation_needs_an_obvious_disability(api):
    """PRD §3.3: "A case whose `disability_obvious` is true may skip
    documentation entirely: an `AccommodationCoordinator` advances it straight
    from `INTAKE` to `FUNCTION_ANALYSIS` by naming that `target_stage`, and that
    advance is legal only when `disability_obvious` is true."
    PRD §2.6: "**Transition is declared** — the target resource must be in a
    state from which the requested transition exists, otherwise the
    state-machine rejection for that resource type:
    `ERR_INVALID_STAGE_TRANSITION`, `ERR_DOC_REQUEST_NOT_OPEN`,
    `ERR_OPTION_NOT_ASSESSABLE`, `ERR_TRIAL_NOT_RESOLVABLE`,
    `ERR_DENIAL_NOT_APPEALABLE`, `ERR_APPEAL_NOT_ACTIONABLE`,
    `ERR_ABSENCE_TRANSITION_INVALID` or `ERR_PROFILE_NOT_DRAFT`, each HTTP 409."

    Design: Corner/state_machines/corner_advance_to_function_analysis_without_obvious_disability_rejected
    """
    set_clock()
    ctx = setup_workforce(department_code="CNC")
    case = open_case(ctx, disability_obvious=False)

    response = api.advance_accommodation_request(
        case["id"], {"target_stage": "FUNCTION_ANALYSIS"}, COORD
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STAGE_TRANSITION)

    assert read_case(case["id"])["stage"] == "INTAKE"


def test_every_case_mutation_moves_the_version_by_exactly_one(api):
    """PRD §2.4: "Most resources additionally carry `updated_at` — same format,
    refreshed on every mutation of that row — and `version`, an integer that
    begins at 1 when the row is created and increases by exactly 1 on every
    mutation of that row."
    PRD §3.3: "An `AccommodationCoordinator` may later amend
    `requested_accommodation_text`, `disability_obvious` and `absence_record_id`
    on an open case; linking an absence record after the fact is the ordinary
    way a leave or workers'-compensation matter gets cross-referenced, and it
    later shortens the renewal cadence."
    PRD §3.3: "It then increments the case's `medical_doc_request_count`,
    recomputes `documentation_budget_remaining`, recomputes the case's
    `interactive_process_integrity_score`, and increments the case's `version`."

    Design: Corner/cross_cutting_complexity_layers/corner_version_increments_on_every_case_mutation
    """
    set_clock()
    ctx = setup_workforce(department_code="CNV")

    created = validate_success(
        api.create_accommodation_request(
            create_accommodation_request_payload(
                ctx["employee"]["id"],
                requested_accommodation_text="First wording",
                disability_obvious=False,
            ),
            make_employee_headers(ctx["employee"]["id"]),
        ),
        201,
    )
    assert created["version"] == 1

    patched = validate_success(
        api.update_accommodation_request(
            created["id"], {"requested_accommodation_text": "Second wording"}, COORD
        ),
        200,
    )
    assert patched["version"] == 2
    assert patched["requested_accommodation_text"] == "Second wording"

    validate_success(
        api.create_medical_doc_request(
            created["id"],
            {
                "scope_fields_requested": ["functional_limitations"],
                "due_date": "2026-08-17T00:00:00Z",
                "is_second_opinion": False,
                "expected_request_version": patched["version"],
            },
            COORD,
        ),
        201,
    )

    final = read_case(created["id"])
    assert final["version"] == 3
    assert final["stage"] == "DOC_PENDING"


def test_the_logical_clock_starts_at_its_declared_instant(api):
    """PRD §2.5: "Nothing in this service reads the host machine's wall clock."
    PRD §2.5: "At process startup that clock reads exactly
    `2026-08-01T00:00:00Z`, and it holds that value until it is explicitly
    moved."
    PRD §2.5: "A `ComplianceAuditor` moves the clock by supplying `to_iso8601`;
    the response reports the newly effective instant as `current_utc`."
    PRD §3.3: "A successful issue creates the round in `status` `ISSUED` with
    `issued_at` read from the logical clock and `round_index` set to the case's
    `medical_doc_request_count` plus one — a 1-based ordinal assigned in
    issuance order."

    Design: Corner/endpoints/corner_logical_clock_defaults_to_fixed_startup_instant
    """
    ctx = setup_workforce(department_code="CNL")
    case = open_case(ctx, disability_obvious=False)

    response = api.create_medical_doc_request(
        case["id"],
        {
            "scope_fields_requested": ["functional_limitations"],
            "due_date": "2026-08-15T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": case_version(case["id"]),
        },
        COORD,
    )
    data = validate_success(response, 201)

    assert data["issued_at"] == CLOCK_STARTUP_DEFAULT, (
        "issued_at must read the startup default, never real wall-clock time"
    )
    assert_three_fraction_digits(data["issued_at"], "issued_at")
    assert data["status"] == "ISSUED"

    moved = set_clock("2026-08-20T00:00:00Z")
    assert moved["current_utc"] == "2026-08-20T00:00:00.000Z"
