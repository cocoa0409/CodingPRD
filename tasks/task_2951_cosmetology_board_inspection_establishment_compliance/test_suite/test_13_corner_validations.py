"""Corner-case validation coverage (SCAFFOLD_CORNER_DESIGN.yaml, section ``validations``).

Each test below translates exactly one design instance: a boundary that a
well-formed request can still fall the wrong side of — a strict inequality, a
conditional field pairing, an inclusive capacity or gap comparison, or a
cross-entity rule that reaches through one row to another.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    ApiErrorId,
    add_workstation,
    assert_cents,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_ledger_entry_shape,
    citation_payload,
    contest_citation,
    create_candidate,
    create_establishment,
    create_violation_code,
    file_sanitation_log,
    get_success_data,
    hearing_payload,
    inspection_payload,
    issue_citation,
    make_establishment_owner_headers,
    payment_payload,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    sanitation_log_payload,
    schedule_inspection,
    setup_establishment_with_posted_practitioner,
    setup_finalized_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    workstation_payload,
)


def test_inspection_window_end_equal_to_start_is_rejected_and_one_millisecond_passes(api):
    """A zero-length inspection window is not a valid window.

    PRD 2.9 step 9 pairs the two window fields: "an inspection's `window_end_at`
    must be strictly after its `window_start_at`", reported as
    `ERR_INVALID_REQUEST` (HTTP 400). One millisecond of width satisfies the
    strict inequality.

    Design: Corner/validations/validation_inspection_window_end_must_be_after_window_start
    """
    establishment = create_establishment(api, station_capacity=4)

    equal_endpoints = api.create_inspection(
        inspection_payload(
            establishment_id=establishment["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="ROUTINE",
            window_start_at="2026-08-03T09:00:00.000Z",
            window_end_at="2026-08-03T09:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(equal_endpoints, ApiErrorId.ERR_INVALID_REQUEST)

    one_millisecond = api.create_inspection(
        inspection_payload(
            establishment_id=establishment["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="ROUTINE",
            window_start_at="2026-08-03T09:00:00.000Z",
            window_end_at="2026-08-03T09:00:00.001Z",
        ),
        INSPECTOR_HEADERS,
    )
    inspection = validate_success(one_millisecond, 201)
    assert_instants_equal(
        inspection["window_end_at"], "2026-08-03T09:00:00.001Z", "window_end_at"
    )

    rows, meta = validate_paginated(
        api.list_inspections(
            BOARD_ADMIN_HEADERS, {"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected window must not have persisted"
    assert [row["id"] for row in rows] == [inspection["id"]]


def test_complaint_driven_inspection_without_a_complaint_reference_is_rejected(api):
    """The docket string is conditionally required, keyed on the visit type.

    PRD 2.9 step 9: "`complaint_reference` is required when `inspection_type` is
    `COMPLAINT_DRIVEN` and forbidden otherwise" — `ERR_INVALID_REQUEST` (400).

    Design: Corner/validations/validation_complaint_reference_is_required_for_a_complaint_driven_inspection
    """
    establishment = create_establishment(api, station_capacity=4)

    missing_reference = api.create_inspection(
        {
            "establishment_id": establishment["id"],
            "inspection_type": "COMPLAINT_DRIVEN",
            "inspector_user_id": INSPECTOR_USER_ID,
            "window_start_at": "2026-08-05T09:00:00.000Z",
            "window_end_at": "2026-08-05T12:00:00.000Z",
        },
        INSPECTOR_HEADERS,
    )
    validate_error(missing_reference, ApiErrorId.ERR_INVALID_REQUEST)

    with_reference = api.create_inspection(
        inspection_payload(
            establishment_id=establishment["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="COMPLAINT_DRIVEN",
            window_start_at="2026-08-05T09:00:00.000Z",
            window_end_at="2026-08-05T12:00:00.000Z",
            complaint_reference="CMP-2026-0731",
        ),
        INSPECTOR_HEADERS,
    )
    inspection = validate_success(with_reference, 201)
    assert inspection["complaint_reference"] == "CMP-2026-0731"
    assert inspection["inspection_type"] == "COMPLAINT_DRIVEN"
    assert inspection["status"] == "SCHEDULED"

    _, meta = validate_paginated(
        api.list_inspections(
            BOARD_ADMIN_HEADERS, {"inspection_type": "COMPLAINT_DRIVEN"}
        )
    )
    assert meta["total_count"] == 1


def test_complaint_reference_supplied_on_a_routine_inspection_is_rejected(api):
    """The pairing is two-sided: the docket string is forbidden off type.

    PRD 2.9 step 9: `complaint_reference` "is required when `inspection_type` is
    `COMPLAINT_DRIVEN` and forbidden otherwise", so a `ROUTINE` window carrying
    one is `ERR_INVALID_REQUEST` (400) rather than a field quietly ignored.

    Design: Corner/validations/validation_complaint_reference_on_a_routine_inspection_is_rejected
    """
    establishment = create_establishment(api, station_capacity=4)

    forbidden_reference = api.create_inspection(
        {
            "establishment_id": establishment["id"],
            "inspection_type": "ROUTINE",
            "inspector_user_id": INSPECTOR_USER_ID,
            "window_start_at": "2026-08-05T09:00:00.000Z",
            "window_end_at": "2026-08-05T12:00:00.000Z",
            "complaint_reference": "CMP-2026-0777",
        },
        INSPECTOR_HEADERS,
    )
    validate_error(forbidden_reference, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_inspections(
            BOARD_ADMIN_HEADERS, {"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected inspection must not have persisted"


def test_station_capacity_is_inclusive_and_only_the_next_station_is_refused(api):
    """Capacity is compared inclusively against the facility permit.

    PRD 3.3: "the addition that brings `station_count` to exactly
    `station_capacity` succeeds, and the next one is rejected with
    `ERR_STATION_CAPACITY_EXCEEDED` (HTTP 409)".

    Design: Corner/validations/validation_station_capacity_upper_bound_is_inclusive_then_exceeded
    """
    establishment = create_establishment(api, station_capacity=2)
    add_workstation(
        api, establishment["id"], station_number=1, station_type="STYLING_CHAIR"
    )

    at_capacity = api.create_workstation(
        establishment["id"],
        workstation_payload(station_number=2, station_type="NAIL_TABLE"),
        BOARD_ADMIN_HEADERS,
    )
    second_station = validate_success(at_capacity, 201)
    assert second_station["station_type"] == "NAIL_TABLE"
    assert second_station["posting_status"] == "MISSING_POSTING"

    over_capacity = api.create_workstation(
        establishment["id"],
        workstation_payload(station_number=3, station_type="FACIAL_ROOM"),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(over_capacity, ApiErrorId.ERR_STATION_CAPACITY_EXCEEDED)

    assert refresh_establishment(api, establishment["id"])["station_count"] == 2
    _, meta = validate_paginated(
        api.list_workstations(
            BOARD_ADMIN_HEADERS, {"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_duplicate_station_number_is_scoped_to_one_establishment(api):
    """Station numbers are unique per establishment, and need not be contiguous.

    PRD 3.3: "two stations of the same establishment may never share a
    `station_number`, and a collision is rejected with
    `ERR_DUPLICATE_STATION_NUMBER` (HTTP 409) — but numbering need not be
    contiguous, so a facility may run stations 1, 2 and 7."

    Design: Corner/validations/validation_duplicate_station_number_within_one_establishment_is_rejected
    """
    unique_salon = create_establishment(api, station_capacity=4)
    other_salon = create_establishment(api, station_capacity=4)
    add_workstation(
        api, unique_salon["id"], station_number=1, station_type="STYLING_CHAIR"
    )

    duplicate = api.create_workstation(
        unique_salon["id"],
        workstation_payload(station_number=1, station_type="NAIL_TABLE"),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_STATION_NUMBER)

    elsewhere = api.create_workstation(
        other_salon["id"],
        workstation_payload(station_number=1, station_type="NAIL_TABLE"),
        BOARD_ADMIN_HEADERS,
    )
    other_station = validate_success(elsewhere, 201)
    assert other_station["establishment_id"] == other_salon["id"]
    assert other_station["station_number"] == 1

    non_contiguous = api.create_workstation(
        unique_salon["id"],
        workstation_payload(station_number=7, station_type="FACIAL_ROOM"),
        BOARD_ADMIN_HEADERS,
    )
    seventh_station = validate_success(non_contiguous, 201)
    assert seventh_station["station_number"] == 7

    assert refresh_establishment(api, unique_salon["id"])["station_count"] == 2
    assert refresh_establishment(api, other_salon["id"])["station_count"] == 1


def test_presiding_officer_may_not_be_the_inspector_who_conducted_the_visit(api):
    """Segregation of duties reaches through the citation to the inspection.

    PRD 2.10 / 3.8: "the supplied `presiding_officer_user_id` must differ from
    that `inspector_user_id`", and a match "is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)" even for an authorised `BoardAdmin`.

    Design: Corner/validations/validation_presiding_officer_may_not_be_the_conducting_inspector
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
    )
    establishment = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[{"violation_code_id": code["id"]}],
        inspector_user_id=INSPECTOR_USER_ID,
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    contest_citation(api, citation["id"])

    conflicted = api.schedule_hearing(
        citation["id"],
        hearing_payload(INSPECTOR_USER_ID, scheduled_at="2026-08-14T10:00:00.000Z"),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    independent = api.schedule_hearing(
        citation["id"],
        hearing_payload(
            HEARING_OFFICER_USER_ID, scheduled_at="2026-08-14T10:00:00.000Z"
        ),
        BOARD_ADMIN_HEADERS,
    )
    hearing = validate_success(independent, 201)
    assert hearing["presiding_officer_user_id"] == HEARING_OFFICER_USER_ID
    assert hearing["round_index"] == 1

    reread = refresh_citation(api, citation["id"])
    assert reread["status"] == "HEARING_SCHEDULED"
    assert reread["hearing_round_count"] == 1

    _, meta = validate_paginated(
        api.list_citation_hearings(citation["id"], BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_foot_spa_cycle_gap_is_measured_from_occupancy_end_and_is_inclusive(api):
    """The rest gap runs from ``occupancy_end_at``, not from ``performed_at``.

    PRD 3.4: "the next cycle on the same station may not begin until at least
    five minutes after the previous cycle's `occupancy_end_at` — the gap is
    inclusive, so a new `performed_at` exactly five minutes after the previous
    `occupancy_end_at` is accepted, while anything earlier ... is rejected with
    `ERR_FOOT_SPA_CYCLE_GAP_VIOLATION` (HTTP 409)."

    Design: Corner/validations/validation_foot_spa_cycle_gap_is_inclusive_at_exactly_five_minutes
    """
    salon = setup_establishment_with_posted_practitioner(api, station_type="FOOT_SPA")
    station_id = salon["workstation"]["id"]

    first_log = file_sanitation_log(
        api,
        station_id,
        log_type="FOOT_SPA_AFTER_CLIENT",
        performed_at="2026-07-30T10:00:00.000Z",
        contact_minutes=10.00,
    )
    assert_instants_equal(
        first_log["occupancy_end_at"], "2026-07-30T10:10:00.000Z", "occupancy_end_at"
    )

    too_soon = api.create_sanitation_log(
        sanitation_log_payload(
            workstation_id=station_id,
            log_type="FOOT_SPA_AFTER_CLIENT",
            performed_at="2026-07-30T10:14:00.000Z",
            contact_minutes=10.00,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(too_soon, ApiErrorId.ERR_FOOT_SPA_CYCLE_GAP_VIOLATION)

    exactly_five_minutes = api.create_sanitation_log(
        sanitation_log_payload(
            workstation_id=station_id,
            log_type="FOOT_SPA_AFTER_CLIENT",
            performed_at="2026-07-30T10:15:00.000Z",
            contact_minutes=10.00,
        ),
        BOARD_ADMIN_HEADERS,
    )
    accepted = validate_success(exactly_five_minutes, 201)
    assert_instants_equal(
        accepted["occupancy_end_at"], "2026-07-30T10:25:00.000Z", "occupancy_end_at"
    )

    assert refresh_workstation(api, station_id)["last_biofilm_cycle_at"] is None
    _, meta = validate_paginated(
        api.list_workstation_sanitation_logs(station_id, BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2


def test_routine_window_exactly_twenty_four_hours_clear_of_the_other_is_accepted(api):
    """The cooldown buffer is satisfied inclusively at the 24-hour boundary.

    PRD 3.5: a `ROUTINE` window "must additionally clear a symmetric cooldown
    buffer of 24 hours ... the requested `window_start_at` must fall at or after
    the other window's `window_end_at` advanced by 24 hours", failing which the
    request is `ERR_INSPECTION_WINDOW_COOLDOWN` (HTTP 409).

    Design: Corner/validations/validation_routine_window_clearing_the_cooldown_buffer_is_accepted
    """
    establishment = create_establishment(api, station_capacity=4)
    first = schedule_inspection(
        api,
        establishment["id"],
        inspection_type="ROUTINE",
        window_start_at="2026-08-03T09:00:00.000Z",
        window_end_at="2026-08-03T17:00:00.000Z",
    )

    one_millisecond_short = api.create_inspection(
        inspection_payload(
            establishment_id=establishment["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="ROUTINE",
            window_start_at="2026-08-04T16:59:59.999Z",
            window_end_at="2026-08-04T20:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(one_millisecond_short, ApiErrorId.ERR_INSPECTION_WINDOW_COOLDOWN)

    exactly_clear = api.create_inspection(
        inspection_payload(
            establishment_id=establishment["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="ROUTINE",
            window_start_at="2026-08-04T17:00:00.000Z",
            window_end_at="2026-08-04T20:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    second = validate_success(exactly_clear, 201)
    assert second["status"] == "SCHEDULED"
    assert second["inspection_type"] == "ROUTINE"
    assert refresh_inspection(api, first["id"])["status"] == "SCHEDULED"

    _, meta = validate_paginated(
        api.list_inspections(
            BOARD_ADMIN_HEADERS, {"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_overpayment_is_refused_while_the_exact_outstanding_amount_settles(api):
    """Overpayment is refused rather than credited; the exact balance settles.

    PRD 3.8: `amount_cents` "must be strictly positive and must not exceed the
    citation's current `outstanding_fine_cents`: overpayment is refused rather
    than credited, with `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422)", and "when
    the balance reaches exactly 0 the citation moves to `SETTLED`".

    Design: Corner/validations/validation_payment_above_outstanding_is_rejected_and_the_exact_amount_settles
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
    )
    establishment = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[{"violation_code_id": code["id"]}],
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    # PRD 3.7: base 3000 -> clamped up to the 5000-cent floor, 5 percent fee.
    assert_fine_breakdown(citation, 5000, 250, 5250, 5250)
    owner_headers = make_establishment_owner_headers(establishment["id"])

    overpayment = api.pay_citation(
        citation["id"],
        payment_payload(5251, payer_reference="CHK-8891"),
        owner_headers,
    )
    validate_error(overpayment, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)

    settlement = api.pay_citation(
        citation["id"],
        payment_payload(5250, payer_reference="CHK-8892"),
        owner_headers,
    )
    entry = get_success_data(settlement)
    assert_ledger_entry_shape(entry)
    assert entry["ledger_type"] == "FINE_CENTS"
    assert entry["entry_reason"] == "CITATION_PAYMENT"
    assert_cents(entry["delta_cents"], -5250, "delta_cents")
    assert entry["citation_id"] == citation["id"]

    settled = refresh_citation(api, citation["id"])
    assert settled["status"] == "SETTLED"
    assert_cents(settled["outstanding_fine_cents"], 0, "outstanding_fine_cents")
    assert_cents(
        refresh_establishment(api, establishment["id"])["outstanding_fine_total_cents"],
        0,
        "outstanding_fine_total_cents",
    )

    _, meta = validate_paginated(
        api.list_ledger_entries(BOARD_ADMIN_HEADERS, {"citation_id": citation["id"]})
    )
    assert meta["total_count"] == 2, "the assessment and the payment rows"


def test_practitioner_subject_citation_needs_an_attributed_finding_on_that_visit(api):
    """The subject must be evidenced by the findings of the cited visit.

    PRD 3.7: "when `subject_type` is `PRACTITIONER`, the supplied
    `subject_practitioner_id` must equal the `attributed_practitioner_id` of at
    least one finding on that inspection", failing which the create is
    `ERR_CITATION_SUBJECT_NOT_IN_FINDINGS` (HTTP 422); an `ESTABLISHMENT` subject
    needs only "at least one finding at all".

    Design: Corner/validations/validation_practitioner_subject_citation_requires_an_attributed_finding
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
    )
    bystander = create_candidate(api, full_name="Zed Amari")
    establishment = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[{"violation_code_id": code["id"]}],
    )
    inspection_id = finalized["inspection"]["id"]
    version = refresh_inspection(api, inspection_id)["version"]

    unevidenced = api.create_citation(
        citation_payload(
            inspection_id=inspection_id,
            expected_inspection_version=version,
            subject_type="PRACTITIONER",
            subject_practitioner_id=bystander["id"],
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(unevidenced, ApiErrorId.ERR_CITATION_SUBJECT_NOT_IN_FINDINGS)

    against_the_facility = api.create_citation(
        citation_payload(
            inspection_id=inspection_id,
            expected_inspection_version=version,
            subject_type="ESTABLISHMENT",
        ),
        BOARD_ADMIN_HEADERS,
    )
    citation = validate_success(against_the_facility, 201)
    assert citation["subject_type"] == "ESTABLISHMENT"
    assert citation["subject_practitioner_id"] is None
    assert_fine_breakdown(citation, 5000, 250, 5250, 5250)
    assert refresh_inspection(api, inspection_id)["citation_count"] == 1

    _, meta = validate_paginated(
        api.list_citations(
            BOARD_ADMIN_HEADERS, {"subject_practitioner_id": bystander["id"]}
        )
    )
    assert meta["total_count"] == 0
