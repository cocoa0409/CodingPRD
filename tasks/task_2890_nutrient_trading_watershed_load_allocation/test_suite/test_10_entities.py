"""Entity-level shape claims: field echo, defaults, computed and system fields."""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_TMDL_ASSESSMENT_NOT_FOUND,
    ERR_WATERSHED_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_common_fields,
    assert_instant_equals,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_object_envelope,
    assert_pagination_meta,
    assert_pct,
    assert_ratio,
    assert_request_metadata,
    assert_trading_gate,
)
from test_helpers.constants import CLOCK_BASE, UNKNOWN_UUID_A, UNKNOWN_UUID_AA
from test_helpers.test_users import ADMIN, ANALYST, BASELINE_VERIFIER, REGISTRY


def test_watershed_creation_echoes_every_input_and_stamps_the_program_defaults(api):
    """Registration returns the declared inputs plus the derived program fields.

    "Upon registration the watershed's `program_status` is `PROVISIONAL`,
    `trading_enabled` is false, `reserve_pool_lbs` is 0.00, `serial_counter` is 0,
    and both `allocated_wla_total_lbs_yr` and `allocated_la_total_lbs_yr` are 0.00,
    with `version` at 1."

    Design: Corner/entities/watershed_creation_returns_every_declared_field_and_program_defaults
    """
    fx.pin_clock(api)

    response = api.create_watershed(
        f.watershed_payload(
            name="Scioto Headwaters",
            state_code="OH",
            watershed_code="SCR",
            pollutant="TOTAL_PHOSPHORUS",
            baseline_year=2020,
            baseline_load_lbs_yr=120000.00,
            interim_target_pct=25.00,
            uncertainty_ratio=2.0000,
            retirement_ratio=0.1000,
            equivalence_ratio=1.0000,
            eligible_zone_codes=["Z1", "Z2"],
        ),
        ADMIN,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert_object_envelope(body)
    assert_request_metadata(body)
    data = validate_success(response, 201)

    assert data["name"] == "Scioto Headwaters", data
    assert data["state_code"] == "OH", data
    assert data["watershed_code"] == "SCR", data
    assert data["pollutant"] == "TOTAL_PHOSPHORUS", data
    assert_integer(data["baseline_year"], 2020, "baseline_year")
    assert_load(data["baseline_load_lbs_yr"], 120000.00, "baseline_load_lbs_yr")
    assert data["eligible_zone_codes"] == ["Z1", "Z2"], data

    assert_trading_gate(data, "PROVISIONAL")
    assert_load(data["reserve_pool_lbs"], 0.00, "reserve_pool_lbs")
    assert_integer(data["serial_counter"], 0, "serial_counter")
    assert_load(data["allocated_wla_total_lbs_yr"], 0.00, "allocated_wla_total_lbs_yr")
    assert_load(data["allocated_la_total_lbs_yr"], 0.00, "allocated_la_total_lbs_yr")

    assert_common_fields(data, expected_version=1)
    assert_instant_equals(data["created_at"], CLOCK_BASE, "created_at")
    assert_instant_equals(data["updated_at"], CLOCK_BASE, "updated_at")


def test_reach_retrieval_returns_the_stored_row_with_its_downstream_link(api):
    """A read of the mainstem reach reproduces exactly what the write stored.

    "The optional `downstream_reach_id` names that neighbour and defaults to null,
    which marks the reach as the outlet of its own branch."

    Design: Corner/entities/reach_retrieval_returns_the_stored_row_including_its_downstream_link
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    r_out = fx.make_reach(
        api,
        watershed["id"],
        "R_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    r_mid = fx.make_reach(
        api,
        watershed["id"],
        "R_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9000,
        downstream_reach_id=r_out["id"],
    )

    response = api.get_reach(r_mid["id"], ANALYST)

    assert response.status_code == 200, response.text
    assert_object_envelope(response.json())
    data = validate_success(response)

    assert data["id"] == r_mid["id"], data
    assert data["watershed_id"] == watershed["id"], data
    assert data["reach_code"] == "R_MID", data
    assert data["trading_zone_code"] == "Z2", data
    assert data["reach_class"] == "MAINSTEM", data
    assert_ratio(data["delivery_factor"], 0.9000, "delivery_factor")
    assert data["downstream_reach_id"] == r_out["id"], data
    assert_integer(data["version"], 1, "version")

    outlet = get_success_data(api.get_reach(r_out["id"], ANALYST))
    assert_is_null(outlet["downstream_reach_id"], "downstream_reach_id of the outlet")


def test_practice_project_listing_paginates_with_total_count_and_has_more(api):
    """Three projects read back in two pages, then in one default-limit page.

    "Every list response carries `limit`, `offset`, `total_count` and `has_more` in
    its `meta` ... `limit` defaults to 10"

    Design: Corner/entities/practice_project_listing_paginates_with_total_count_and_has_more
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer_id = fx.make_producer(api)["id"]
    for tract, acres, pre, post in (
        ("T-101", 100.00, 950.50, 300.00),
        ("T-102", 60.00, 600.00, 200.00),
        ("T-103", 30.00, 300.00, 100.00),
    ):
        fx.make_practice_project(
            api,
            producer_id,
            reaches["r_up"]["id"],
            tract,
            enrolled_acres=acres,
            pre_load_lbs_yr=pre,
            post_load_lbs_yr=post,
        )

    first_page, first_meta = validate_paginated(
        api.list_practice_projects(REGISTRY, {"producer_id": producer_id, "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, first_page
    assert_pagination_meta(first_meta, 2, 0, 3, True)

    second_page, second_meta = validate_paginated(
        api.list_practice_projects(REGISTRY, {"producer_id": producer_id, "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, second_page
    assert_pagination_meta(second_meta, 2, 2, 3, False)

    all_rows, default_meta = validate_paginated(
        api.list_practice_projects(REGISTRY, {"producer_id": producer_id})
    )
    assert len(all_rows) == 3, all_rows
    assert_pagination_meta(default_meta, 10, 0, 3, False)


def test_watershed_get_with_an_unused_uuid_is_watershed_not_found(api):
    """A well-formed but unused identifier is a 404 against a populated table.

    "The path resource exists — `ERR_<RESOURCE>_NOT_FOUND`, 404."

    Design: Corner/entities/watershed_get_with_unknown_uuid_returns_watershed_not_found
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    missing = api.get_watershed(UNKNOWN_UUID_A, ADMIN)

    validate_error(missing, ERR_WATERSHED_NOT_FOUND, 404)
    body = missing.json()
    assert body["response_type"] == "error", body
    assert body["data"]["message"].strip(), body

    survivor = get_success_data(api.get_watershed(watershed["id"], ADMIN))
    assert survivor["id"] == watershed["id"], survivor


def test_a_tmdl_assessment_without_a_loading_capacity_is_rejected(api):
    """The one required input with no default cannot be omitted.

    "The request body is shape-valid: every required field present, no unknown
    fields, every value of the declared type and within its declared range —
    `ERR_INVALID_REQUEST`, 422."

    Design: Corner/entities/tmdl_assessment_missing_required_loading_capacity_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    refused = api.create_tmdl_assessment(
        {
            "watershed_id": watershed["id"],
            "assessment_code": "TMDL-P-2026",
            "margin_of_safety_pct": 0.1000,
            "background_load_lbs_yr": 6000.00,
            "period_start_date": "2026-01-01",
            "period_end_date": "2035-12-31",
        },
        ANALYST,
    )

    validate_error(refused, ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(
        api.list_tmdl_assessments(ANALYST, {"watershed_id": watershed["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)


def test_omitted_program_ratios_fall_back_to_the_declared_defaults(api):
    """The four optional program parameters default rather than arriving null.

    "`interim_target_pct` ... defaults to 25.00. `uncertainty_ratio` ... defaults to
    2.0000 ... `retirement_ratio` ... defaults to 0.1000 ... `equivalence_ratio` ...
    defaults to 1.0000."

    Design: Corner/entities/watershed_optional_ratio_fields_fall_back_to_declared_defaults
    """
    fx.pin_clock(api)

    created = validate_success(
        api.create_watershed(
            f.watershed_payload(
                name="Default Creek",
                state_code="OH",
                watershed_code="DEF",
                pollutant="TOTAL_NITROGEN",
                baseline_year=2021,
                baseline_load_lbs_yr=80000.00,
                interim_target_pct=None,
                uncertainty_ratio=None,
                retirement_ratio=None,
                equivalence_ratio=None,
                eligible_zone_codes=["Z1"],
            ),
            ADMIN,
        ),
        201,
    )

    assert_pct(created["interim_target_pct"], 25.00, "interim_target_pct")
    assert_ratio(created["uncertainty_ratio"], 2.0000, "uncertainty_ratio")
    assert_ratio(created["retirement_ratio"], 0.1000, "retirement_ratio")
    assert_ratio(created["equivalence_ratio"], 1.0000, "equivalence_ratio")
    assert created["eligible_zone_codes"] == ["Z1"], created


def test_the_sample_load_is_computed_by_the_server_for_every_qa_status(api):
    """The annualized load is derived from the declared constants, quality flag aside.

    "This field is computed and stored for every sample regardless of `qa_status`;
    the quality flag never changes the stored value, it only governs which samples
    the downstream aggregations are allowed to consume"

    Design: Corner/entities/monitoring_sample_computed_load_is_derived_and_client_input_ignored
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    r_out = fx.make_reach(
        api,
        watershed["id"],
        "R_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )

    accepted = validate_success(
        api.create_monitoring_sample(
            f.monitoring_sample_payload(r_out["id"], "2026-07-01T12:00:00Z", 0.0500, 1000.00),
            ANALYST,
        ),
        201,
    )
    rejected = validate_success(
        api.create_monitoring_sample(
            f.monitoring_sample_payload(
                r_out["id"], "2026-07-02T12:00:00Z", 0.0250, 100.00, qa_status="REJECTED"
            ),
            ANALYST,
        ),
        201,
    )

    assert_load(accepted["computed_load_lbs_yr"], 98422.25, "computed_load_lbs_yr")
    assert accepted["qa_status"] == "ACCEPTED", accepted
    assert_load(rejected["computed_load_lbs_yr"], 4921.11, "computed_load_lbs_yr")
    assert rejected["qa_status"] == "REJECTED", rejected

    reread = get_success_data(api.get_monitoring_sample(accepted["id"], ANALYST))
    assert_load(reread["computed_load_lbs_yr"], 98422.25, "computed_load_lbs_yr on re-read")
    assert_append_only_fields(reread)


def test_producer_identity_and_timestamps_are_server_generated(api):
    """The producer's `id`, both timestamps and its version come from the server.

    "Every `created_at`, `updated_at`, ... value the server writes is read from
    this clock"

    Design: Corner/entities/producer_system_fields_are_server_generated_and_client_id_input_ignored
    """
    fx.pin_clock(api)

    created = validate_success(
        api.create_producer(
            f.producer_payload(
                legal_name="Bluegrass Farms LLC",
                county_code="OH-041",
                contact_email="ops@bluegrass.example",
            ),
            ADMIN,
        ),
        201,
    )

    assert is_valid_uuid(created["id"]), created
    assert_common_fields(created, expected_version=1)
    assert_instant_equals(created["created_at"], CLOCK_BASE, "created_at")
    assert_instant_equals(created["updated_at"], CLOCK_BASE, "updated_at")

    reread = get_success_data(api.get_producer(created["id"], ADMIN))
    assert reread["id"] == created["id"], reread
    assert_instant_equals(reread["created_at"], created["created_at"], "created_at on re-read")
    assert_integer(reread["version"], 1, "version on re-read")


def test_a_reach_class_outside_the_enum_is_rejected(api):
    """`TRIBUTARY` is not one of the four declared reach classes.

    "a `reach_class` drawn from `HEADWATER`, `MAINSTEM`, `COMPLIANCE_POINT` and
    `BACKGROUND`"

    Design: Corner/entities/reach_class_outside_the_declared_enum_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    refused = api.create_reach(
        f.reach_payload(
            watershed["id"],
            "R_BAD",
            trading_zone_code="Z2",
            reach_class="TRIBUTARY",
            delivery_factor=1.0000,
        ),
        ANALYST,
    )

    validate_error(refused, ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_reaches(ANALYST, {"watershed_id": watershed["id"]}))
    assert_pagination_meta(meta, 10, 0, 0, False)


def test_a_verification_event_carries_no_version_and_no_updated_at(api):
    """The event is append-only, so it exposes only `id` and `created_at`.

    "A monitoring sample and a verification event are append-only records and each
    carry only `id` and `created_at`. Neither has an `updated_at` field nor a
    `version` field"

    Design: Corner/entities/verification_event_is_immutable_with_no_version_and_no_update_endpoint
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer_id = fx.make_producer(api)["id"]
    project = fx.make_practice_project(api, producer_id, reaches["r_up"]["id"], "T-101")

    event = validate_success(
        api.create_verification_event(
            f.verification_event_payload(
                project["id"],
                "BASELINE",
                "PASS",
                narrative="Baseline soil sampling complete on tract T-101.",
            ),
            BASELINE_VERIFIER,
        ),
        201,
    )

    assert event["resulting_project_status"] == "BASELINE_VERIFIED", event
    assert event["inspector_user_id"] == "verifier-1", event
    assert_instant_equals(event["created_at"], CLOCK_BASE, "created_at")
    assert_append_only_fields(event)

    reread = get_success_data(api.get_verification_event(event["id"], BASELINE_VERIFIER))
    assert reread == event, (reread, event)
    assert_append_only_fields(reread)


def test_a_source_assessment_under_an_unknown_assessment_is_not_found(api):
    """The body-referenced parent is resolved before anything else is judged.

    "Every resource referenced by the request body exists —
    `ERR_<RESOURCE>_NOT_FOUND`, 404."

    Design: Corner/entities/source_assessment_with_unknown_parent_assessment_returns_not_found
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    r_mid = fx.make_reach(
        api,
        watershed["id"],
        "R_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9000,
    )

    refused = api.create_source_assessment(
        f.source_assessment_payload(
            UNKNOWN_UUID_AA, r_mid["id"], "City WWTP", "POINT", 20000.00, 0.8000
        ),
        ANALYST,
    )

    validate_error(refused, ERR_TMDL_ASSESSMENT_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_source_assessments(ANALYST, {"reach_id": r_mid["id"]}))
    assert_pagination_meta(meta, 10, 0, 0, False)
