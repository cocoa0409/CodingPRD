"""Corner coverage: the role surface of PRD 2.1, 2.9 and the section 4 role tables.

Every test in this module translates exactly one non-stub ``rbac`` instance of
``SCAFFOLD_CORNER_DESIGN.yaml``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_HEADERS,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    add_workstation,
    assert_cents,
    assert_points,
    citation_payload,
    create_candidate,
    create_establishment,
    create_school,
    create_violation_code,
    establishment_payload,
    hearing_payload,
    make_establishment_owner_headers,
    make_headers,
    make_practitioner_headers,
    make_school_registrar_headers,
    posting_payload,
    practitioner_payload,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    setup_finalized_inspection,
    setup_submitted_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    violation_code_payload,
    workstation_payload,
)


def test_inspector_cannot_finalize_the_review_they_submitted(api):
    """Board review is BoardAdmin-exclusive even for the officer who submitted it.

    PRD 2.1: "An `Inspector` schedules and conducts inspections, records findings,
    declares imminent hazards and submits for review, but may never finalize a
    review, issue a citation or adjudicate one." PRD section 4 lists
    `POST /cosmetology/inspections/{id}/finalize` under `BoardAdmin` alone, and PRD
    2.9 step 2 makes a recognised role off the endpoint's list `ERR_UNAUTHORIZED`.

    Design: Corner/rbac/rbac_inspector_cannot_finalize_the_review_they_submitted
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=2.00, fine_cents_base=3000
    )
    est = create_establishment(api, station_capacity=4)
    submitted = setup_submitted_inspection(
        api, est["id"], findings=[{"violation_code_id": code["id"]}]
    )
    inspection_id = submitted["inspection"]["id"]

    validate_error(
        api.finalize_inspection(inspection_id, INSPECTOR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    held = refresh_inspection(api, inspection_id)
    assert held["status"] == "PENDING_REVIEW"
    assert held["final_adjusted_score"] is None
    assert held["final_outcome"] is None
    untouched = refresh_establishment(api, est["id"])
    assert untouched["license_status"] == "PENDING_INSPECTION"
    assert_points(untouched["demerit_balance"], 0.00, "demerit_balance")

    finalized = validate_success(
        api.finalize_inspection(inspection_id, BOARD_ADMIN_HEADERS)
    )
    assert finalized["status"] == "FINALIZED"
    # 2.00 base points x 1.0 MINOR weight x 1 observation x 1.0 repeat factor.
    assert_points(finalized["final_adjusted_score"], 2.00, "final_adjusted_score")
    promoted = refresh_establishment(api, est["id"])
    assert promoted["license_status"] == "ACTIVE"
    assert_points(promoted["demerit_balance"], 2.00, "demerit_balance")


def test_inspector_cannot_issue_a_citation_and_the_hearing_officer_cannot_schedule_one(api):
    """Both writes are BoardAdmin-exclusive, and the role gate precedes every state gate.

    PRD 2.1: "A `BoardAdmin` alone owns ... citation issuance, hearing scheduling";
    "A `HearingOfficer` records hearing decisions and nothing else." PRD 2.9 puts
    "Role permitted on the endpoint — `ERR_UNAUTHORIZED`" at step 2, ahead of the
    state precondition `ERR_CITATION_NOT_CONTESTED` at step 11.

    Design: Corner/rbac/rbac_inspector_cannot_issue_a_citation_and_the_hearing_officer_cannot_schedule_one
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=2.00, fine_cents_base=3000
    )
    est = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api, est["id"], findings=[{"violation_code_id": code["id"]}]
    )
    inspection = refresh_inspection(api, finalized["inspection"]["id"])
    payload = citation_payload(
        inspection_id=inspection["id"],
        expected_inspection_version=inspection["version"],
        subject_type="ESTABLISHMENT",
    )

    validate_error(
        api.create_citation(payload, INSPECTOR_HEADERS), ApiErrorId.ERR_UNAUTHORIZED
    )

    citation = validate_success(api.create_citation(payload, BOARD_ADMIN_HEADERS), 201)
    assert citation["status"] == "ISSUED"
    assert_cents(citation["total_due_cents"], 5250, "total_due_cents")

    validate_error(
        api.schedule_hearing(
            citation["id"],
            hearing_payload(HEARING_OFFICER_USER_ID, scheduled_at="2026-08-14T10:00:00.000Z"),
            HEARING_OFFICER_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    after = refresh_citation(api, citation["id"])
    assert after["hearing_round_count"] == 0
    assert after["status"] == "ISSUED"
    assert refresh_inspection(api, inspection["id"])["citation_count"] == 1


def test_establishment_owner_cannot_set_the_logical_clock(api):
    """The clock belongs to BoardAdmin alone, and the refusal leaves it where it was.

    PRD 2.1: "A `BoardAdmin` alone owns the reference registries ... and the logical
    clock", and PRD section 4 lists `POST /_clock/set_current_utc` under `BoardAdmin`
    only. PRD 2.4: "the clock may only move forward, so a `to_iso8601` less than or
    equal to the current value is rejected with `ERR_CLOCK_MUST_ADVANCE`".

    Design: Corner/rbac/rbac_establishment_owner_cannot_set_the_logical_clock
    """
    est = create_establishment(api, station_capacity=4)
    owner_headers = make_establishment_owner_headers(est["id"])

    validate_error(
        api.set_clock("2026-09-01T00:00:00.000Z", owner_headers),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # The identical target is still accepted, which proves the clock never moved:
    # had the refused call advanced it, this would now be ERR_CLOCK_MUST_ADVANCE.
    validate_success(api.set_clock("2026-09-01T00:00:00.000Z", BOARD_ADMIN_HEADERS))
    assert refresh_establishment(api, est["id"])["license_status"] == "PENDING_INSPECTION"


def test_school_registrar_cannot_register_an_establishment_or_publish_a_violation_code(api):
    """The registrar is confined to the school-to-licence pipeline, per endpoint.

    PRD 2.1: "A `SchoolRegistrar` enrols candidates and files clock-hour records for
    candidates of their own school", and PRD section 4 lists
    `POST /cosmetology/establishments` under `BoardAdmin`, `EstablishmentOwner` and
    `POST /cosmetology/violation-codes` under `BoardAdmin` alone, while
    `POST /cosmetology/practitioners` accepts `BoardAdmin`, `SchoolRegistrar`.

    Design: Corner/rbac/rbac_school_registrar_cannot_register_an_establishment_or_publish_a_violation_code
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED"
    )
    registrar_headers = make_school_registrar_headers(school["id"])

    validate_error(
        api.create_establishment(
            establishment_payload(
                legal_name="Registrar Side Salon", county_code="ZZR", station_capacity=4
            ),
            registrar_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.create_violation_code(
            violation_code_payload(
                code="REC-966", category="RECORDKEEPING", severity="MINOR",
                base_points=2.00, fine_cents_base=3000,
            ),
            registrar_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    candidate = validate_success(
        api.create_practitioner(
            practitioner_payload(
                full_name="Fenn Oduya", license_type="COSMETOLOGIST", school_id=school["id"]
            ),
            registrar_headers,
        ),
        201,
    )
    assert candidate["school_id"] == school["id"]
    assert candidate["license_status"] == "STUDENT"
    assert_points(
        candidate["required_clock_hours_effective"], 16.00, "required_clock_hours_effective"
    )
    _, meta = validate_paginated(
        api.list_establishments(BOARD_ADMIN_HEADERS, {"county_code": "ZZR"})
    )
    assert meta["total_count"] == 0


def test_practitioner_cannot_add_capacity_or_post_a_licence_at_a_salon(api):
    """Capacity and posting writes belong to the establishment side of the graph.

    PRD section 4 lists `POST /cosmetology/establishments/{id}/workstations` and
    `POST /cosmetology/workstations/{id}/posting` under `BoardAdmin`,
    `EstablishmentOwner` only, and PRD 2.1 confines a `Practitioner` to terminating
    their own rental, logging their own sanitation procedures and contesting or
    paying a citation naming them.

    Design: Corner/rbac/rbac_practitioner_cannot_add_capacity_or_post_a_licence_at_a_salon
    """
    candidate = create_candidate(api, full_name="Gita Almeida")
    est = create_establishment(api, station_capacity=4)
    station = add_workstation(api, est["id"], station_number=1)
    practitioner_headers = make_practitioner_headers(candidate["id"])

    validate_error(
        api.create_workstation(
            est["id"], workstation_payload(2, "NAIL_TABLE"), practitioner_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.post_licence_at_workstation(
            station["id"], posting_payload(candidate["id"]), practitioner_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    assert refresh_establishment(api, est["id"])["station_count"] == 1
    unchanged = refresh_workstation(api, station["id"])
    assert unchanged["posted_practitioner_id"] is None
    assert unchanged["posting_status"] == "MISSING_POSTING"
    _, meta = validate_paginated(
        api.list_workstations(BOARD_ADMIN_HEADERS, {"establishment_id": est["id"]})
    )
    assert meta["total_count"] == 1


def test_owner_scope_is_confined_to_their_own_establishment_and_is_unauthorized_across_salons(api):
    """An entity-backed owner is scoped by X-User-ID, and the miss is 403 rather than 404.

    PRD 2.1: "an `X-User-ID` that is syntactically well-formed but names no row of
    the backing entity is an authorization failure — `ERR_UNAUTHORIZED` (HTTP 403) —
    never a 404". PRD 2.9 step 6: "**Ownership scope** for entity-backed roles —
    `ERR_UNAUTHORIZED`. This runs after existence, so a caller cannot probe for row
    existence through the authorization surface".

    Design: Corner/rbac/rbac_owner_scope_is_confined_to_their_own_establishment_and_is_unauthorized_across_salons
    """
    est_a = create_establishment(api, station_capacity=4, county_code="AAT")
    est_b = create_establishment(api, station_capacity=4, county_code="AAU")

    validate_error(
        api.create_workstation(
            est_b["id"],
            workstation_payload(1, "STYLING_CHAIR"),
            make_establishment_owner_headers(est_a["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.create_workstation(
            est_a["id"],
            workstation_payload(1, "STYLING_CHAIR"),
            make_establishment_owner_headers(NON_EXISTENT_UUID),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    created = validate_success(
        api.create_workstation(
            est_a["id"],
            workstation_payload(1, "STYLING_CHAIR"),
            make_establishment_owner_headers(est_a["id"]),
        ),
        201,
    )
    assert created["establishment_id"] == est_a["id"]
    assert created["station_number"] == 1
    assert refresh_establishment(api, est_a["id"])["station_count"] == 1
    assert refresh_establishment(api, est_b["id"])["station_count"] == 0


def test_absent_blank_or_unknown_role_headers_are_unauthenticated_before_authorization(api):
    """Authentication is settled before authorization and before existence.

    PRD 2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) ... A value of `X-User-Role` that is not one of
    those seven strings is treated as an unauthenticated caller rather than an
    unauthorized one, and likewise yields `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/rbac_absent_blank_or_unknown_role_headers_are_unauthenticated_before_authorization
    """
    est = create_establishment(api, station_capacity=4)

    for headers in (
        NO_HEADERS,
        MISSING_USER_ID_HEADERS,
        MISSING_ROLE_HEADERS,
        UNKNOWN_ROLE_HEADERS,
        make_headers("clerk-001", "CountyHealthClerk"),
    ):
        validate_error(
            api.get_establishment(est["id"], headers),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

    fetched = validate_success(api.get_establishment(est["id"], BOARD_ADMIN_HEADERS))
    assert fetched["id"] == est["id"]
    assert fetched["license_status"] == "PENDING_INSPECTION"
