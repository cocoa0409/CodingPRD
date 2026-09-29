"""Corner coverage for the `entities` section of the breadth index.

Every test in this module translates exactly one instance of
`SCAFFOLD_CORNER_DESIGN.yaml` -> `section: entities`, and asserts only what the
PRD states verbatim about entity creation, retrieval, listing, defaults,
computed fields, immutability, parent resolution and the entity topology.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    CLOCK_START,
    DEFAULT_LIMIT,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    NON_EXISTENT_UUID,
    STANDALONE_APPRENTICESHIP_REQUIRED_HOURS,
    ApiErrorId,
    add_workstation,
    assert_booth_rental_shape,
    assert_cents,
    assert_common_fields,
    assert_establishment_shape,
    assert_fresh_establishment,
    assert_fresh_practitioner,
    assert_immutable_fields,
    assert_inspection_shape,
    assert_instants_equal,
    assert_points,
    assert_practitioner_shape,
    booth_rental_payload,
    create_candidate,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    establishment_payload,
    inspection_payload,
    practitioner_payload,
    refresh_establishment,
    refresh_practitioner,
    refresh_workstation,
    school_payload,
    setup_finalized_inspection,
    training_record_payload,
    make_school_registrar_headers,
    validate_error,
    validate_paginated,
    validate_success,
    workstation_payload,
)

PLANTED_UUID = "11111111-1111-1111-1111-111111111111"


def test_establishment_create_returns_every_declared_field(api):
    """A 201 create echoes the four declared inputs and opens every derived field.

    PRD 3.1: "A freshly registered facility opens at `license_status` of
    `PENDING_INSPECTION` and `compliance_posture` of `CLEAR`, with `station_count`
    at 0, `demerit_balance` at 0.00, `open_critical_citation_count` at 0, both
    `outstanding_fine_total_cents` and `delinquent_fine_total_cents` at 0,
    `foot_spa_biofilm_current` true because it has no foot spas yet, and
    `last_finalized_inspection_at` null."  PRD 2.4 adds that `version` "starts at
    1 on creation".

    Design: Corner/entities/entity_establishment_create_returns_every_declared_field
    """
    response = api.create_establishment(
        establishment_payload(
            legal_name="Corner Salon",
            establishment_type="SALON",
            county_code="AAA",
            station_capacity=5,
        ),
        BOARD_ADMIN_HEADERS,
    )
    est = validate_success(response, 201)

    assert_establishment_shape(est)
    assert est["legal_name"] == "Corner Salon"
    assert est["establishment_type"] == "SALON"
    assert est["county_code"] == "AAA"
    assert est["station_capacity"] == 5
    assert_fresh_establishment(est)
    assert est["version"] == 1


def test_establishment_get_by_id_returns_the_stored_row(api):
    """GET /establishments/{id} echoes the created row at version 1.

    PRD 2.4: every resource carries `created_at`, and `updated_at` is "refreshed
    on every mutation" while `version` "starts at 1 on creation and increases by
    exactly 1 on each mutation" — so a never-mutated row reads version 1 with
    `created_at` equal to `updated_at`.  PRD 4 authorises `Inspector` on the
    single-establishment read.

    Design: Corner/entities/entity_establishment_get_by_id_returns_the_stored_row
    """
    created = validate_success(
        api.create_establishment(
            establishment_payload(
                legal_name="Corner Salon",
                establishment_type="BARBERSHOP",
                county_code="AAB",
                station_capacity=7,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    fetched = validate_success(api.get_establishment(created["id"], INSPECTOR_HEADERS))

    assert_establishment_shape(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["legal_name"] == "Corner Salon"
    assert fetched["establishment_type"] == "BARBERSHOP"
    assert fetched["county_code"] == "AAB"
    assert fetched["station_capacity"] == 7
    assert fetched["version"] == 1
    assert_instants_equal(fetched["updated_at"], fetched["created_at"], "updated_at")


def test_establishment_list_paginates_with_total_count_and_has_more(api):
    """The establishments list windows three rows and reports the pre-window count.

    PRD 2.3: "`limit` is an integer with a default of 10 ... Every list response
    carries `limit`, `offset`, `total_count` and `has_more` inside `meta`, where
    `total_count` is the number of rows matching the filters before the window is
    applied and `has_more` indicates whether rows remain beyond the current
    window."  Establishments also filter on `county_code`.

    Design: Corner/entities/entity_establishment_list_paginates_with_total_count_and_has_more
    """
    create_establishment(
        api, station_capacity=2, county_code="AAC", legal_name="Alpha Salon"
    )
    create_establishment(
        api, station_capacity=2, county_code="AAC", legal_name="Bravo Salon"
    )
    create_establishment(
        api, station_capacity=2, county_code="AAD", legal_name="Charlie Salon"
    )

    first_rows, first_meta = validate_paginated(
        api.list_establishments(BOARD_ADMIN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_establishments(BOARD_ADMIN_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    filtered_rows, filtered_meta = validate_paginated(
        api.list_establishments(BOARD_ADMIN_HEADERS, {"county_code": "AAC"})
    )
    assert filtered_meta["total_count"] == 2
    assert filtered_meta["limit"] == DEFAULT_LIMIT
    assert filtered_meta["offset"] == 0
    assert filtered_meta["has_more"] is False
    assert len(filtered_rows) == 2
    assert {row["county_code"] for row in filtered_rows} == {"AAC"}


def test_establishment_get_unknown_id_returns_not_found(api):
    """A well-formed UUID naming no row is a 404, not an empty 200.

    PRD 2.4: a request "fails on the leftmost identifier that names no row, and
    the error names the entity that was missing: `ERR_ESTABLISHMENT_NOT_FOUND`
    ... each with HTTP 404."

    Design: Corner/entities/entity_establishment_get_unknown_id_returns_not_found
    """
    create_establishment(
        api, station_capacity=1, county_code="AAE", legal_name="Only Salon"
    )

    response = api.get_establishment(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND, 404)


def test_establishment_create_missing_capacity_returns_invalid_request(api):
    """Omitting the required `station_capacity` is a 400 and writes no row.

    PRD 3.1: an establishment registers with "a `station_capacity` of at least 1
    giving the maximum number of workstations the facility permit allows".  PRD
    2.9 step 7 checks "required fields present" and reports
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/entity_establishment_create_missing_capacity_returns_invalid_request
    """
    payload = establishment_payload(
        legal_name="Headless Salon", establishment_type="SALON", county_code="AAF"
    )
    del payload["station_capacity"]

    response = api.create_establishment(payload, BOARD_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(api.list_establishments(BOARD_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_school_create_applies_declared_defaults_for_optional_flags(api):
    """An omitted accreditation status and apprenticeship flag take their defaults.

    PRD 3.1: a school's "`accreditation_status` is one of `ACCREDITED`,
    `PROBATIONARY` or `WITHDRAWN`, defaulting to `ACCREDITED`, and its
    `apprenticeship_program_approved` flag, defaulting to false".

    Design: Corner/entities/entity_school_create_applies_declared_defaults_for_optional_flags
    """
    payload = school_payload(
        name="Default Academy", county_code="AAG", required_clock_hours=1500.00
    )
    assert "accreditation_status" not in payload
    assert "apprenticeship_program_approved" not in payload

    school = validate_success(api.create_school(payload, BOARD_ADMIN_HEADERS), 201)

    assert_common_fields(school)
    assert school["name"] == "Default Academy"
    assert school["county_code"] == "AAG"
    assert school["accreditation_status"] == "ACCREDITED"
    assert school["apprenticeship_program_approved"] is False
    assert_points(school["required_clock_hours"], 1500.00, "required_clock_hours")
    assert school["version"] == 1


def test_establishment_computed_and_system_fields_extra_field_ignored(api):
    """Client-supplied computed, system and identity fields are ignored, not honoured.

    PRD 2.3: "Unknown fields anywhere in a query string or a request body are
    ignored rather than rejected."  PRD 2.4: the `id` "is a UUID with no type
    prefix and is never accepted as client input", and the logical clock's
    "startup value is exactly `2026-08-01T00:00:00Z`", which is the instant a
    creation in an untouched database is stamped with.

    Design: Corner/entities/entity_establishment_computed_and_system_fields_extra_field_ignored
    """
    response = api.create_establishment(
        establishment_payload(
            legal_name="Sneaky Salon",
            establishment_type="SALON",
            county_code="AAH",
            station_capacity=3,
            station_count=99,
            demerit_balance=500.00,
            license_status="ACTIVE",
            id=PLANTED_UUID,
            version=42,
        ),
        BOARD_ADMIN_HEADERS,
    )
    est = validate_success(response, 201)

    assert_establishment_shape(est)
    assert est["station_count"] == 0
    assert_points(est["demerit_balance"], 0.00, "demerit_balance")
    assert est["license_status"] == "PENDING_INSPECTION"
    assert est["version"] == 1
    assert est["id"] != PLANTED_UUID
    assert_instants_equal(est["created_at"], CLOCK_START, "created_at")
    assert_instants_equal(est["updated_at"], CLOCK_START, "updated_at")


def test_establishment_type_invalid_enum_rejected(api):
    """A closed enum, a malformed county code and a zero capacity are each a 400.

    PRD 3.1: an establishment carries "an `establishment_type` of `SALON`,
    `BARBERSHOP`, `NAIL_SALON`, `ESTHETICS_SPA` or `SCHOOL_CLINIC` ... a
    `county_code` of exactly three uppercase letters ... and a `station_capacity`
    of at least 1".  PRD 2.9 step 7 checks "enum fields carrying a declared
    member, quantities non-negative where the field demands it" and reports
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/entity_establishment_type_invalid_enum_rejected
    """
    bad_enum = api.create_establishment(
        establishment_payload(
            legal_name="Ink Salon",
            establishment_type="TATTOO_PARLOR",
            county_code="AAJ",
            station_capacity=3,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 400)

    bad_county = api.create_establishment(
        establishment_payload(
            legal_name="Lower Salon",
            establishment_type="SALON",
            county_code="aa1",
            station_capacity=3,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(bad_county, ApiErrorId.ERR_INVALID_REQUEST, 400)

    bad_capacity = api.create_establishment(
        establishment_payload(
            legal_name="Zero Salon",
            establishment_type="SALON",
            county_code="AAJ",
            station_capacity=0,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(bad_capacity, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(api.list_establishments(BOARD_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_violation_code_is_immutable_with_no_version_or_update_surface(api):
    """A published schedule entry carries only id and created_at.

    PRD 2.4: "Four record types are immutable by design and therefore carry only
    `id` and `created_at` — both `updated_at` and `version` are absent from
    `TrainingRecord`, `ViolationCode`, `SanitationLog` and `LedgerEntry` ... a
    violation code is published reference data".  PRD 3.1 adds that "Schedule
    entries are reference data and are never amended", and PRD 4 exposes only a
    publish and two read surfaces for them.

    Design: Corner/entities/entity_violation_code_is_immutable_with_no_version_or_update_surface
    """
    published = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.00,
        fine_cents_base=1000,
        category="SANITATION",
        code="SAN-900",
    )
    assert_immutable_fields(published)

    fetched = validate_success(api.get_violation_code(published["id"], INSPECTOR_HEADERS))

    assert_immutable_fields(fetched)
    assert "version" not in fetched
    assert "updated_at" not in fetched
    assert fetched["code"] == "SAN-900"
    assert fetched["category"] == "SANITATION"
    assert fetched["severity"] == "MINOR"
    assert_points(fetched["base_points"], 1.00, "base_points")
    assert_cents(fetched["fine_cents_base"], 1000, "fine_cents_base")


def test_training_record_is_immutable_and_append_only(api):
    """Two 4.00-hour filings on one date accumulate as two rows, neither versioned.

    PRD 2.4: `TrainingRecord` carries "only `id` and `created_at`" and "A training
    record is never amended once filed ... corrections to any of them take the
    form of new rows, never edits."  PRD 3.2: the school ledger takes "for each
    such date the lesser of the total hours claimed on that date and the daily cap
    of eight hours", `credited_hours_total` is the sum of the two ledgers, and
    `exam_eligible` becomes true only once the total reaches
    `required_clock_hours_effective`.

    Design: Corner/entities/entity_training_record_is_immutable_and_append_only
    """
    school = create_school(
        api,
        required_clock_hours=100.00,
        accreditation_status="ACCREDITED",
        county_code="AAK",
    )
    candidate = create_candidate(
        api, school_id=school["id"], license_type="ESTHETICIAN", full_name="Ivy Park"
    )
    registrar_headers = make_school_registrar_headers(school["id"])

    first = validate_success(
        api.create_training_record(
            training_record_payload(
                practitioner_id=candidate["id"],
                credit_type="SCHOOL_CLOCK_HOUR",
                hours=4.00,
                performed_on="2026-07-10",
                discipline="THEORY",
                school_id=school["id"],
            ),
            registrar_headers,
        ),
        201,
    )
    second = validate_success(
        api.create_training_record(
            training_record_payload(
                practitioner_id=candidate["id"],
                credit_type="SCHOOL_CLOCK_HOUR",
                hours=4.00,
                performed_on="2026-07-10",
                discipline="PRACTICAL",
                school_id=school["id"],
            ),
            registrar_headers,
        ),
        201,
    )

    assert_immutable_fields(first)
    assert_immutable_fields(second)
    assert second["id"] != first["id"]
    assert_points(first["hours"], 4.00, "hours")
    assert first["discipline"] == "THEORY"
    assert second["discipline"] == "PRACTICAL"

    rows, meta = validate_paginated(
        api.list_training_records(
            BOARD_ADMIN_HEADERS, {"practitioner_id": candidate["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}

    subject = refresh_practitioner(api, candidate["id"])
    assert_points(subject["credited_hours_school"], 8.00, "credited_hours_school")
    assert_points(subject["credited_hours_total"], 8.00, "credited_hours_total")
    assert_points(
        subject["required_clock_hours_effective"],
        100.00,
        "required_clock_hours_effective",
    )
    assert subject["exam_eligible"] is False


def test_workstation_create_under_unknown_establishment_not_found(api):
    """The path parent is resolved before the body, so an unknown salon is a 404.

    PRD 2.4: "Nested resources are addressed through their parent, and path
    identifiers are resolved strictly left to right ... the error names the entity
    that was missing: `ERR_ESTABLISHMENT_NOT_FOUND`".  PRD 2.9 puts path existence
    at step 4, ahead of request shape at step 7.

    Design: Corner/entities/entity_workstation_create_under_unknown_establishment_not_found
    """
    create_establishment(
        api, station_capacity=2, county_code="AAL", legal_name="Real Salon"
    )

    response = api.create_workstation(
        NON_EXISTENT_UUID,
        workstation_payload(station_number=1, station_type="STYLING_CHAIR"),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND, 404)

    _rows, meta = validate_paginated(api.list_workstations(BOARD_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_practitioner_without_school_uses_standalone_required_hours(api):
    """A candidate with no school falls back to the 1600.00-hour standalone requirement.

    PRD 3.2: "A `school_id` may be supplied to bind the candidate to a licensed
    school, or omitted entirely for a pure apprenticeship candidate who never
    enrolled anywhere ... The candidate's `required_clock_hours_effective` is
    resolved at once: it is the `required_clock_hours` of the school named by
    `school_id` when that field is non-null, and otherwise the standalone
    apprenticeship requirement of 1600.00 hours."

    Design: Corner/entities/entity_practitioner_without_school_uses_standalone_required_hours
    """
    payload = practitioner_payload(full_name="Solo Candidate", license_type="APPRENTICE")
    assert "school_id" not in payload

    candidate = validate_success(api.create_practitioner(payload, BOARD_ADMIN_HEADERS), 201)

    assert_practitioner_shape(candidate)
    assert candidate["school_id"] is None
    assert_points(
        candidate["required_clock_hours_effective"],
        STANDALONE_APPRENTICESHIP_REQUIRED_HOURS,
        "required_clock_hours_effective",
    )
    assert_fresh_practitioner(candidate)


def test_topology_graph_one_practitioner_rents_at_two_establishments(api):
    """One licensee holds simultaneous rentals on stations of two different salons.

    PRD 3.3: "A booth rental records the commercial relationship between a station
    and the person who occupies it ... The rental opens at `status` of `PROPOSED`
    with `terminated_at` null", it "additionally requires the stale-version token
    described in §2.8", and a station "opens with `posted_practitioner_id` null,
    `posting_status` at `MISSING_POSTING`".  The half-open overlap rule is scoped
    to "the same workstation", so two stations of two establishments never collide.
    PRD 2.3 lets booth rentals be filtered by `practitioner_id` and by
    `workstation_id`, which is the junction row read from either side.

    Design: Corner/entities/entity_topology_graph_one_practitioner_rents_at_two_establishments
    """
    school = create_school(
        api,
        required_clock_hours=16.00,
        accreditation_status="ACCREDITED",
        county_code="AAM",
    )
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], license_type="COSMETOLOGIST", full_name="Kai Renn"
    )
    east = create_establishment(
        api, station_capacity=2, county_code="AAN", legal_name="East Salon"
    )
    west = create_establishment(
        api, station_capacity=2, county_code="AAP", legal_name="West Salon"
    )
    east_station = add_workstation(
        api, east["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    west_station = add_workstation(
        api, west["id"], station_number=1, station_type="STYLING_CHAIR"
    )

    east_rental = validate_success(
        api.create_booth_rental(
            booth_rental_payload(
                workstation_id=east_station["id"],
                practitioner_id=practitioner["id"],
                expected_workstation_version=refresh_workstation(
                    api, east_station["id"]
                )["version"],
                rental_type="BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
                term_start_at="2026-08-01T00:00:00.000Z",
                monthly_rent_cents=60000,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    west_rental = validate_success(
        api.create_booth_rental(
            booth_rental_payload(
                workstation_id=west_station["id"],
                practitioner_id=practitioner["id"],
                expected_workstation_version=refresh_workstation(
                    api, west_station["id"]
                )["version"],
                rental_type="EMPLOYEE",
                term_start_at="2026-08-01T00:00:00.000Z",
                monthly_rent_cents=0,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    assert_booth_rental_shape(east_rental)
    assert_booth_rental_shape(west_rental)
    assert east_rental["status"] == "PROPOSED"
    assert west_rental["status"] == "PROPOSED"
    assert west_rental["rental_type"] == "EMPLOYEE"
    assert_cents(west_rental["monthly_rent_cents"], 0, "monthly_rent_cents")

    _by_practitioner, practitioner_meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"practitioner_id": practitioner["id"]}
        )
    )
    assert practitioner_meta["total_count"] == 2

    by_station, station_meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"workstation_id": east_station["id"]}
        )
    )
    assert station_meta["total_count"] == 1
    assert by_station[0]["id"] == east_rental["id"]

    assert refresh_workstation(api, east_station["id"])["posting_status"] == (
        "MISSING_POSTING"
    )
    assert refresh_workstation(api, west_station["id"])["posting_status"] == (
        "MISSING_POSTING"
    )
    assert refresh_establishment(api, east["id"])["station_count"] == 1
    assert refresh_establishment(api, west["id"])["station_count"] == 1


def test_topology_graph_reinspection_parent_must_share_the_establishment(api):
    """A finalized parent at another salon cannot anchor a reinspection.

    PRD 3.5: "The parent named by `reinspection_of_id` ... must be an inspection of
    the **same** establishment, its `status` must be `FINALIZED`, and its
    `final_outcome` must be one of `CONDITIONAL_PASS`, `FAIL` or
    `IMMEDIATE_CLOSURE` ... a parent on another establishment is nonsense; either
    case ... is reported as `ERR_REINSPECTION_PARENT_REQUIRED` (HTTP 422)."  The
    parent's own score follows §3.5: 6.00 base points times the 2.5 `MAJOR`
    weight times one occurrence at repeat factor 1.0 with no credit is 15.00,
    which is "strictly greater than 10.00" and therefore `CONDITIONAL_PASS`.

    Design: Corner/entities/entity_topology_graph_reinspection_parent_must_share_the_establishment
    """
    code = create_violation_code(
        api,
        severity="MAJOR",
        base_points=6.00,
        fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
        code="IMP-900",
    )
    alpha = create_establishment(
        api, station_capacity=2, county_code="AAQ", legal_name="Alpha Salon"
    )
    beta = create_establishment(
        api, station_capacity=2, county_code="AAR", legal_name="Beta Salon"
    )

    parent = setup_finalized_inspection(
        api,
        alpha["id"],
        findings=[
            {
                "violation_code_id": code["id"],
                "observed_count": 1,
                "corrected_on_site": False,
            }
        ],
        window_index=0,
    )["inspection"]
    assert_points(parent["final_adjusted_score"], 15.00, "final_adjusted_score")
    assert parent["final_outcome"] == "CONDITIONAL_PASS"

    cross_establishment = api.create_inspection(
        inspection_payload(
            establishment_id=beta["id"],
            inspector_user_id=INSPECTOR_USER_ID,
            inspection_type="REINSPECTION",
            reinspection_of_id=parent["id"],
            window_start_at="2026-08-20T09:00:00.000Z",
            window_end_at="2026-08-20T12:00:00.000Z",
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(
        cross_establishment, ApiErrorId.ERR_REINSPECTION_PARENT_REQUIRED, 422
    )

    same_establishment = validate_success(
        api.create_inspection(
            inspection_payload(
                establishment_id=alpha["id"],
                inspector_user_id=INSPECTOR_USER_ID,
                inspection_type="REINSPECTION",
                reinspection_of_id=parent["id"],
                window_start_at="2026-08-20T09:00:00.000Z",
                window_end_at="2026-08-20T12:00:00.000Z",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )

    assert_inspection_shape(same_establishment)
    assert same_establishment["establishment_id"] == alpha["id"]
    assert same_establishment["reinspection_of_id"] == parent["id"]
    assert same_establishment["inspection_type"] == "REINSPECTION"
    assert same_establishment["status"] == "SCHEDULED"

    children, children_meta = validate_paginated(
        api.list_inspections(BOARD_ADMIN_HEADERS, {"reinspection_of_id": parent["id"]})
    )
    assert children_meta["total_count"] == 1
    assert children[0]["id"] == same_establishment["id"]
