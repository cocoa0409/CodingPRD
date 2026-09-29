"""Temporal overlap geometry: half-open booth terms, closed inspection windows.

Every test in this module translates exactly one non-stub instance of the
``resource_temporal_overlap`` rule of ``SCAFFOLD_DIFFICULTY_DESIGN.yaml``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    SECOND_INSPECTOR_USER_ID,
    ApiErrorId,
    add_workstation,
    assert_instants_equal,
    assert_points,
    booth_rental_payload,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    inspection_payload,
    refresh_booth_rental,
    refresh_inspection,
    refresh_workstation,
    setup_finalized_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- resource_temporal_overlap / one workstation's occupancy chain -------------
def _station_and_occupant(api):
    school = create_school(api, required_clock_hours=16.00)
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], full_name="Tova Lund"
    )
    establishment = create_establishment(
        api, station_capacity=3, legal_name="Cedar Studio"
    )
    station = add_workstation(
        api, establishment["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    return practitioner, establishment, station


def _create_rental(
    api, station_id, practitioner_id, term_start_at, term_end_at, monthly_rent_cents=70000
):
    """Re-read the station's ``version`` first: PRD 2.8 makes the token mandatory
    and every accepted rental create increments the parent workstation."""
    station = refresh_workstation(api, station_id)
    return api.create_booth_rental(
        booth_rental_payload(
            workstation_id=station_id,
            practitioner_id=practitioner_id,
            expected_workstation_version=station["version"],
            term_start_at=term_start_at,
            term_end_at=term_end_at,
            monthly_rent_cents=monthly_rent_cents,
        ),
        BOARD_ADMIN_HEADERS,
    )


def test_adjacent_booth_terms_touching_at_the_boundary_are_accepted(api):
    """PRD 3.3: occupancy is half-open, `term_start_at` inclusive to `term_end_at`
    exclusive, and "two rentals that merely touch, where the new term's
    `term_start_at` is exactly the previous term's `term_end_at`, are accepted".

    Design: Difficulty/resource_temporal_overlap/booth_rental_half_open_terms_allow_adjacency_but_reject_one_millisecond
    """
    practitioner, _establishment, station = _station_and_occupant(api)
    first = validate_success(
        _create_rental(
            api,
            station["id"],
            practitioner["id"],
            "2026-08-10T00:00:00.000Z",
            "2026-09-10T00:00:00.000Z",
        ),
        201,
    )
    second = validate_success(
        _create_rental(
            api,
            station["id"],
            practitioner["id"],
            "2026-09-10T00:00:00.000Z",
            "2026-10-10T00:00:00.000Z",
            monthly_rent_cents=72000,
        ),
        201,
    )
    assert second["status"] == "PROPOSED"
    assert_instants_equal(
        second["term_start_at"], first["term_end_at"], "clean midnight handover"
    )
    assert_instants_equal(
        second["term_start_at"], "2026-09-10T00:00:00.000Z", "term_start_at"
    )
    rows, meta = validate_paginated(
        api.list_booth_rentals(BOARD_ADMIN_HEADERS, {"workstation_id": station["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    # No licence was ever posted at this station (PRD 3.3's derived verdict).
    assert refresh_workstation(api, station["id"])["posting_status"] == "MISSING_POSTING"


def test_a_one_millisecond_booth_term_overlap_is_rejected(api):
    """PRD 3.3: "No two rentals in `PROPOSED` or `ACTIVE` status on the same
    workstation may overlap, and an overlap of a single millisecond is rejected with
    `ERR_BOOTH_RENTAL_OVERLAP` (409)".

    Design: Difficulty/resource_temporal_overlap/booth_rental_half_open_terms_allow_adjacency_but_reject_one_millisecond
    """
    practitioner, _establishment, station = _station_and_occupant(api)
    first = validate_success(
        _create_rental(
            api,
            station["id"],
            practitioner["id"],
            "2026-08-10T00:00:00.000Z",
            "2026-09-10T00:00:00.000Z",
        ),
        201,
    )
    second = validate_success(
        _create_rental(
            api,
            station["id"],
            practitioner["id"],
            "2026-09-10T00:00:00.000Z",
            "2026-10-10T00:00:00.000Z",
            monthly_rent_cents=72000,
        ),
        201,
    )
    # Steals only the final millisecond of the first term while merely touching
    # the second, so a closed-interval or date-granularity check gets it wrong.
    sliver = _create_rental(
        api,
        station["id"],
        practitioner["id"],
        "2026-09-09T23:59:59.999Z",
        "2026-09-10T00:00:00.000Z",
        monthly_rent_cents=500,
    )
    validate_error(sliver, ApiErrorId.ERR_BOOTH_RENTAL_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_booth_rentals(BOARD_ADMIN_HEADERS, {"workstation_id": station["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert_instants_equal(
        refresh_booth_rental(api, first["id"])["term_end_at"],
        "2026-09-10T00:00:00.000Z",
        "first term_end_at",
    )


# --- resource_temporal_overlap / one establishment's inspection calendar -------
def _harbor_calendar(api):
    """A terminal reinspection parent plus one SCHEDULED window that occupies the
    calendar (PRD 3.5: only SCHEDULED / IN_PROGRESS / PENDING_REVIEW collide)."""
    code = create_violation_code(
        api,
        severity="MAJOR",
        base_points=6.00,
        fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
        code="IMP-200",
    )
    establishment = create_establishment(
        api, station_capacity=6, legal_name="Harbor Salon"
    )
    parent = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[
            {
                "violation_code_id": code["id"],
                "observed_count": 1,
                "corrected_on_site": False,
            }
        ],
        window_index=0,
    )["inspection"]
    # 6.00 base * 2.5 MAJOR weight * 1 observed * 1.0 repeat = 15.00, which is
    # strictly greater than 10.00 and not above 40.00, so PRD 3.5 bands it
    # CONDITIONAL_PASS -- a legal reinspection parent under PRD 3.5.
    assert_points(parent["final_adjusted_score"], 15.00, "final_adjusted_score")
    assert parent["final_outcome"] == "CONDITIONAL_PASS"
    occupying = validate_success(
        api.create_inspection(
            inspection_payload(
                establishment_id=establishment["id"],
                inspector_user_id=SECOND_INSPECTOR_USER_ID,
                inspection_type="ROUTINE",
                window_start_at="2026-08-10T09:00:00.000Z",
                window_end_at="2026-08-10T17:00:00.000Z",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )
    assert occupying["status"] == "SCHEDULED"
    return {"establishment": establishment, "parent": parent, "occupying": occupying}


def test_routine_window_refused_by_the_cooldown_buffer_that_a_reinspection_is_exempt_from(
    api,
):
    """PRD 3.5: a `ROUTINE` window "must additionally clear a symmetric cooldown
    buffer of 24 hours around every non-terminal window on the same establishment",
    failing which the refusal is `ERR_INSPECTION_WINDOW_COOLDOWN` (409), while "a
    `REINSPECTION` is exempt from the buffer".

    Design: Difficulty/resource_temporal_overlap/inspection_windows_closed_interval_with_cooldown_exempt_reinspection
    """
    world = _harbor_calendar(api)
    establishment_id = world["establishment"]["id"]
    # 2026-08-11T10:00 is clear of the 08-10 window itself but inside the 24-hour
    # buffer that runs to 2026-08-11T17:00.
    routine = api.create_inspection(
        inspection_payload(
            establishment_id=establishment_id,
            inspector_user_id="inspector-013",
            inspection_type="ROUTINE",
            window_start_at="2026-08-11T10:00:00.000Z",
            window_end_at="2026-08-11T12:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(routine, ApiErrorId.ERR_INSPECTION_WINDOW_COOLDOWN, 409)

    reinspection = validate_success(
        api.create_inspection(
            inspection_payload(
                establishment_id=establishment_id,
                inspector_user_id="inspector-013",
                inspection_type="REINSPECTION",
                reinspection_of_id=world["parent"]["id"],
                window_start_at="2026-08-11T10:00:00.000Z",
                window_end_at="2026-08-11T12:00:00.000Z",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )
    assert reinspection["status"] == "SCHEDULED"
    assert reinspection["reinspection_of_id"] == world["parent"]["id"]
    assert refresh_inspection(api, world["occupying"]["id"])["status"] == "SCHEDULED"


def test_reinspection_still_collides_on_a_touching_closed_interval_endpoint(api):
    """PRD 3.5: the inspection window is "a **closed** interval running from
    `window_start_at` through `window_end_at` inclusive, so windows that merely touch
    at an endpoint *do* collide", and a `REINSPECTION` remains "subject to the strict
    closed-interval overlap check" -- `ERR_INSPECTION_WINDOW_OVERLAP` (409).

    Design: Difficulty/resource_temporal_overlap/inspection_windows_closed_interval_with_cooldown_exempt_reinspection
    """
    world = _harbor_calendar(api)
    establishment_id = world["establishment"]["id"]
    exempt = validate_success(
        api.create_inspection(
            inspection_payload(
                establishment_id=establishment_id,
                inspector_user_id="inspector-013",
                inspection_type="REINSPECTION",
                reinspection_of_id=world["parent"]["id"],
                window_start_at="2026-08-11T10:00:00.000Z",
                window_end_at="2026-08-11T12:00:00.000Z",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )
    # Starts on exactly the instant the SCHEDULED window ends, which the booth-rental
    # geometry of PRD 3.3 would allow and this closed interval must not.
    touching = api.create_inspection(
        inspection_payload(
            establishment_id=establishment_id,
            inspector_user_id="inspector-013",
            inspection_type="REINSPECTION",
            reinspection_of_id=world["parent"]["id"],
            window_start_at="2026-08-10T17:00:00.000Z",
            window_end_at="2026-08-10T18:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(touching, ApiErrorId.ERR_INSPECTION_WINDOW_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_inspections(
            BOARD_ADMIN_HEADERS, {"establishment_id": establishment_id}
        )
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {
        world["parent"]["id"],
        world["occupying"]["id"],
        exempt["id"],
    }
