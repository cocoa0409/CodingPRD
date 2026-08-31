"""Agencies, volunteers and trail segments: the register everything else hangs off."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_land_manager,
    assert_three_fractional_digits,
    assert_trail_segment,
    assert_volunteer,
    create_land_manager,
    create_land_manager_from,
    create_trail_segment,
    is_valid_uuid,
    make_crew_leader_headers,
    make_volunteer_headers,
    minimal_land_manager_payload,
    observe_weather,
    setup_active_adoption,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_land_manager_registration_applies_every_declared_default(api):
    """PRD 3.1: "The `permit_required` flag defaults to true and decides whether crews on this agency's land must hold an issued permit before a work party may be confirmed."
    PRD 3.1: "The `permit_lead_days` value defaults to 14 and states the number of whole days that must separate the logical clock date from a requested permit's first authorised day."
    PRD 3.1: "The `max_party_size` ceiling defaults to 20 and caps how many people the agency will allow on the ground."
    PRD 3.1: "The `wet_threshold_index` defaults to 0.65, is expressed to two decimal places on a scale from 0.0 to 1.0, and names the soil-moisture level at or above which this agency's segments become wet-restricted."
    PRD 3.1: "The `requires_engineering_review` flag defaults to false and, when true, forces a structural sign-off reference onto bridge requisitions."
    PRD 3.1: "The `requires_certified_sawyer` flag defaults to true and, when true, insists that a chainsaw party keep at least one certified sawyer on its roster."
    PRD 3.1: "Two further fields are maintained by the server rather than the caller: `policy_version` is initialised to 1 and is snapshotted onto each adoption at activation time, and `adopted_segment_count` is initialised to 0 and tracks how many of this agency's segments currently sit in `ADOPTED`."

    Design: Corner/entities/land_manager_creation_applies_declared_defaults_and_system_fields
    """
    created = validate_success(
        api.create_land_manager(minimal_land_manager_payload(), COORD), 201
    )
    fetched = validate_success(api.get_land_manager(created["id"], COORD))

    assert_land_manager(fetched)
    assert fetched["permit_required"] is True
    assert fetched["permit_lead_days"] == 14
    assert fetched["max_party_size"] == 20
    assert float(fetched["wet_threshold_index"]) == 0.65
    assert fetched["requires_engineering_review"] is False
    assert fetched["requires_certified_sawyer"] is True
    assert fetched["policy_version"] == 1
    assert fetched["adopted_segment_count"] == 0
    assert created["version"] == 1, "version starts at 1 on creation"
    assert is_valid_uuid(created["id"]) and "_" not in created["id"]
    assert_three_fractional_digits(created["created_at"], "created_at")


def test_volunteer_skill_class_and_waiver_expiry_are_derived_by_the_server(api):
    """PRD 3.1: "It is chosen by precedence, highest band first: a volunteer holding `CERT_ENGINEER` is `PROFESSIONAL`; failing that, a volunteer holding `CERT_SAWYER_B` or `CERT_SAWYER_C` is `CERTIFIED_SAWYER`; failing that, a volunteer holding `CERT_TRAIL_SKILLS` or `CERT_CREW_LEADER` is `SKILLED_TRAIL`; and a volunteer holding none of those is `GENERAL`."
    PRD 3.1: "Liability paperwork is captured as `waiver_signed_on`, a `YYYY-MM-DD` date that is null when the volunteer has never signed; from it the server derives `waiver_expires_on` as the day exactly 365 days after `waiver_signed_on`, likewise formatted `YYYY-MM-DD` and likewise null when nothing has been signed."
    PRD 3.1: "The four hour buckets described in section 2.9 — `lifetime_credited_hours`, `pending_hours`, `verified_hours` and `certified_hours` — all start at 0, as does `active_registration_count`, which tracks how many of the volunteer's shifts currently sit in `REGISTERED` or `CHECKED_IN`."

    Design: Corner/entities/volunteer_skill_class_and_waiver_expiry_are_computed
    """
    general = validate_success(
        api.create_volunteer(
            {
                "full_name": "Petra Novak",
                "email": "petra@example.org",
                "waiver_signed_on": "2026-07-01",
                "certifications": [],
            },
            COORD,
        ),
        201,
    )
    skilled = validate_success(
        api.create_volunteer(
            {
                "full_name": "Tomas Reyes",
                "email": "tomas@example.org",
                "waiver_signed_on": "2026-07-01",
                "certifications": ["CERT_TRAIL_SKILLS"],
            },
            COORD,
        ),
        201,
    )
    sawyer = validate_success(
        api.create_volunteer(
            {
                "full_name": "Milo Okonkwo",
                "email": "milo@example.org",
                "waiver_signed_on": "2026-07-01",
                "certifications": ["CERT_SAWYER_B", "CERT_TRAIL_SKILLS"],
            },
            COORD,
        ),
        201,
    )
    professional = validate_success(
        api.create_volunteer(
            {
                "full_name": "Inez Vogel",
                "email": "inez@example.org",
                "waiver_signed_on": "2026-07-01",
                "certifications": ["CERT_ENGINEER", "CERT_SAWYER_C", "CERT_TRAIL_SKILLS"],
            },
            COORD,
        ),
        201,
    )

    assert general["skill_class"] == "GENERAL"
    assert skilled["skill_class"] == "SKILLED_TRAIL"
    assert sawyer["skill_class"] == "CERTIFIED_SAWYER"
    assert professional["skill_class"] == "PROFESSIONAL"
    assert general["waiver_expires_on"] == "2027-07-01"

    fetched = validate_success(api.get_volunteer(general["id"], COORD))
    assert_volunteer(fetched)
    assert float(fetched["lifetime_credited_hours"]) == 0
    assert float(fetched["pending_hours"]) == 0
    assert float(fetched["verified_hours"]) == 0
    assert float(fetched["certified_hours"]) == 0
    assert fetched["active_registration_count"] == 0


def test_reading_an_unknown_trail_segment_returns_the_path_keyed_not_found(api):
    """PRD 2.7: "Path-parameter existence, resolved left to right along the URL."
    PRD 2.7: "The code names the segment of the path that failed: `ERR_LAND_MANAGER_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_TRAIL_SEGMENT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_WORK_PLAN_NOT_FOUND`, `ERR_CONDITION_REPORT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_PARTY_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_MATERIAL_ORDER_NOT_FOUND` or `ERR_INCIDENT_NOT_FOUND`."
    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/trail_segment_get_with_unknown_id_returns_not_found
    """
    create_land_manager()

    response = api.get_trail_segment(NON_EXISTENT_UUID, COORD)
    error_data = validate_error(
        response, ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND.value, 404
    )
    assert error_data["message"].strip(), "message must be a non-empty string"

    body = response.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_work_plan_creation_without_requested_budget_is_a_malformed_request(api):
    """PRD 2.7: "Request-body well-formedness (`ERR_INVALID_REQUEST`): the body parses, every required field is present, every enum value is a declared member, every number satisfies its declared range, `lines` is a non-empty array whose members each carry a `sku` string, a `unit_price_cents` integer of at least 0 and a `quantity` integer of at least 1, dates are `YYYY-MM-DD`, datetimes are ISO 8601 UTC, and pagination values are within their declared bounds."
    PRD 3.3: "A `CrewLeader` drafts a seasonal work plan under an adoption, supplying the `adoption_agreement_id`, the `season_year` the plan covers, and a `requested_budget_cents` figure of at least 0."

    Design: Corner/entities/work_plan_creation_missing_required_field_returns_invalid_request
    """
    world = setup_active_adoption()

    response = api.create_work_plan(
        {"adoption_agreement_id": world["agreement_id"], "season_year": 2026},
        world["lead_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_work_plans(
            COORD, params={"adoption_agreement_id": world["agreement_id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected draft must not have been persisted"


def test_condition_report_with_an_undeclared_severity_member_is_rejected(api):
    """PRD 3.4: "The report names the `trail_segment_id` carrying the defect and the `reported_by_volunteer_id` who saw it, classifies the defect with a `hazard_type` drawn from `BLOWDOWN`, `TREAD_EROSION`, `DRAINAGE_FAILURE`, `BRIDGE_DAMAGE`, `SIGNAGE_MISSING` and `BRUSH_ENCROACHMENT`, assigns a first-pass `severity_class` of `LOW`, `MODERATE`, `HIGH` or `CRITICAL`, and carries a free-text `description` of the field notes."
    PRD 2.7: "Request-body well-formedness (`ERR_INVALID_REQUEST`): the body parses, every required field is present, every enum value is a declared member, every number satisfies its declared range, `lines` is a non-empty array whose members each carry a `sku` string, a `unit_price_cents` integer of at least 0 and a `quantity` integer of at least 1, dates are `YYYY-MM-DD`, datetimes are ISO 8601 UTC, and pagination values are within their declared bounds."

    Design: Corner/entities/condition_report_rejects_undeclared_severity_enum_member
    """
    world = setup_registry()

    response = api.create_condition_report(
        {
            "trail_segment_id": world["seg_id"],
            "reported_by_volunteer_id": world["gen_id"],
            "hazard_type": "BLOWDOWN",
            "severity_class": "CATASTROPHIC",
            "description": "Large fir across the tread.",
        },
        make_volunteer_headers(world["gen_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_condition_reports(COORD, params={"trail_segment_id": world["seg_id"]})
    )
    assert meta["total_count"] == 0, "the rejected report must not have been persisted"


def test_agreement_creation_with_an_unknown_segment_reports_the_segment_code(api):
    """PRD 2.7: "Foreign-key existence for identifiers supplied in the request body, validated in the field order in which the entity declares them — on a material order creation, for instance, `work_plan_id` is resolved before `condition_report_id`."
    PRD 3.2: "A `CrewLeader` opens an adoption by drafting an agreement that names the `trail_segment_id` being adopted, the `crew_leader_volunteer_id` of the volunteer signing as crew leader, and the inclusive term boundaries `term_start_date` and `term_end_date`, both `YYYY-MM-DD`, with the end strictly after the start."

    Design: Corner/entities/adoption_agreement_creation_with_unknown_segment_returns_not_found
    """
    world = setup_registry()

    response = api.create_adoption_agreement(
        {
            "trail_segment_id": NON_EXISTENT_UUID,
            "crew_leader_volunteer_id": world["lead_id"],
            "term_start_date": "2026-08-01",
            "term_end_date": "2027-07-31",
        },
        make_crew_leader_headers(world["lead_id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND.value, 404)


def test_trail_segment_listing_filters_by_agency_and_paginates_the_filtered_set(api):
    """PRD 3.1: "Segment listings may be narrowed by `land_manager_id`, by `posture` and by `adoption_status`."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object, where `total_count` reflects the number of rows matching the supplied filters before pagination is applied and `has_more` is true exactly when rows remain beyond the returned page."
    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/trail_segment_list_filters_by_land_manager_and_paginates
    """
    primary = create_land_manager()
    other = create_land_manager_from(minimal_land_manager_payload())
    create_trail_segment(primary["id"], name="Alder Creek")
    create_trail_segment(primary["id"], name="Bear Hollow")
    create_trail_segment(primary["id"], name="Cedar Bench")
    excluded = create_trail_segment(
        other["id"],
        name="Dune Loop",
        length_miles=1.5,
        surface_class="GRAVEL",
        traffic_class="LIGHT",
    )

    page, meta = validate_paginated(
        api.list_trail_segments(
            COORD, params={"land_manager_id": primary["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2, f"expected a page of 2 segments, got {len(page)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    for segment in page:
        assert_trail_segment(segment)
        assert segment["land_manager_id"] == primary["id"]
        assert segment["id"] != excluded["id"]

    validate_error(
        api.list_trail_segments(COORD, params={"limit": 200}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )


def test_wet_restriction_fires_at_exactly_the_configured_threshold_index(api):
    """PRD 2.6: "Otherwise, if `latest_soil_moisture_index` is not null, is greater than or equal to the governing land manager's `wet_threshold_index`, and the elapsed time from `latest_moisture_observed_at` to the logical clock is strictly less than 72 hours, the posture is `WET_RESTRICTED`."
    PRD 3.1: "The server stores those as the segment's `latest_soil_moisture_index` and `latest_moisture_observed_at`, recomputes the posture against the governing agency's `wet_threshold_index`, and returns the segment with its new posture."

    Design: Corner/cross_cutting_complexity_layers/wet_threshold_is_inclusive_at_the_configured_index
    """
    manager = create_land_manager()
    segment = create_trail_segment(manager["id"])

    under = observe_weather(segment["id"], 0.64, "2026-08-01T00:00:00.000Z")
    assert float(under["latest_soil_moisture_index"]) == 0.64
    assert under["posture"] == "OPEN", "0.64 sits below the 0.65 threshold"

    at_threshold = observe_weather(segment["id"], 0.65, "2026-08-01T00:00:00.000Z")
    assert float(at_threshold["latest_soil_moisture_index"]) == 0.65
    assert at_threshold["posture"] == "WET_RESTRICTED", "the comparison is >=, not >"
    assert at_threshold["latest_moisture_observed_at"] == "2026-08-01T00:00:00.000Z"


def test_the_logical_clock_refuses_to_run_backwards(api):
    """PRD 2.5: "On startup the clock is fixed at `2026-08-01T00:00:00Z`; it must never fall back to real wall-clock time."
    PRD 2.5: "An administrative capability sets the clock forward to a supplied `to_iso8601` instant. The clock never runs backwards: a requested instant that is not strictly greater than the current clock is rejected with `ERR_CLOCK_REWIND` (HTTP 422)."

    Design: Corner/validations/logical_clock_cannot_be_rewound
    """
    advanced = validate_success(
        api.set_clock({"to_iso8601": "2026-09-05T09:00:00.000Z"}, COORD)
    )
    assert advanced["current_utc"] == "2026-09-05T09:00:00.000Z"

    rewind = api.set_clock({"to_iso8601": "2026-08-01T00:00:00.000Z"}, COORD)
    validate_error(rewind, ApiErrorId.ERR_CLOCK_REWIND.value, 422)

    forward = validate_success(
        api.set_clock({"to_iso8601": "2026-09-06T00:00:00.000Z"}, COORD)
    )
    assert forward["current_utc"] == "2026-09-06T00:00:00.000Z"
