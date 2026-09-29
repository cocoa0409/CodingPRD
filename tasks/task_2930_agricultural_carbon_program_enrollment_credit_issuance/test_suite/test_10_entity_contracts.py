"""Entity-level contracts: creation defaults, derived fields, not-found codes,
immutability, listing pagination and the transitive parent copy.

These are the resource-shape claims the rest of the suite builds on: what the server
stamps that the client never sends, and what a read of one row is required to expose.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_BASELINE_NOT_FOUND,
    ERR_BUFFER_ACCOUNT_NOT_FOUND,
    ERR_CREDIT_BATCH_NOT_FOUND,
    ERR_DATA_PACKET_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_FIELD_NOT_FOUND,
    ERR_GROWER_NOT_FOUND,
    ERR_GROWER_PAYMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PRACTICE_HISTORY_NOT_FOUND,
    ERR_PRACTICE_STANDARD_NOT_FOUND,
    ERR_QUANTIFICATION_RUN_NOT_FOUND,
    ERR_REVERSAL_EVENT_NOT_FOUND,
    ERR_VERIFICATION_BODY_NOT_FOUND,
    ERR_VERIFICATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_acres,
    assert_cents,
    assert_common_fields,
    assert_credits,
    assert_error_envelope,
    assert_immutable_common_fields,
    assert_rate,
    assert_success_envelope,
)
from test_helpers.constants import (
    CLOCK_2026,
    ENROLLMENT_DRAFT,
    EVIDENCE_FARM_RECORD,
    FIELD_DRAFT,
    GROWER_ACTIVE,
    PAYMENT_MODEL_PER_ACRE,
    PERMANENCE_NOT_STARTED,
    PRACTICE_COVER_CROP,
    PRACTICE_REDUCED_TILLAGE,
    SOIL_CLAY,
    SOIL_LOAM,
    SOIL_SAND,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import (
    enrollment_payload,
    field_payload,
    grower_payload,
    per_acre_enrollment_payload,
    practice_history_payload,
)
from test_helpers.test_users import ADMIN_HEADERS

HISTORY_KEYS = {
    "id",
    "created_at",
    "field_id",
    "crop_year",
    "practice_code",
    "adopted",
    "evidence_source",
    "acres",
    "observed_emissions_per_acre",
}


def test_grower_creation_stamps_the_defaults_the_request_never_supplies(scenario):
    """A registration body carrying only the four identity fields comes back with the audit
    quartet, an active status, a null suspension reason and five aggregates at zero.

    PRD §3.1: "A newly registered grower has `status` of `ACTIVE`, a null
    `suspension_reason`, and all five running aggregates at zero as described in §2.11."

    Design: Corner/entities/grower_creation_returns_success_envelope_with_system_defaults
    """
    scenario.set_clock(CLOCK_2026)
    payload = grower_payload(
        legal_name="Willow Creek Farms LLC", operator_type="LLC", mailing_state="IA"
    )

    response = scenario.api.create_grower(payload, ADMIN_HEADERS)

    grower = validate_success(response, 201)
    assert_success_envelope(response.json())
    assert_common_fields(grower)
    assert grower["version"] == 1
    assert grower["legal_name"] == payload["legal_name"]
    assert grower["operator_type"] == payload["operator_type"]
    assert grower["tax_id"] == payload["tax_id"]
    assert grower["mailing_state"] == payload["mailing_state"]
    assert grower["status"] == GROWER_ACTIVE
    assert grower["suspension_reason"] is None
    assert_acres(grower["total_enrolled_acres"], 0.00)
    assert_credits(grower["lifetime_credits_issued"], 0)
    assert_cents(grower["net_paid_cents"], 0)
    assert_cents(grower["outstanding_clawback_cents"], 0)
    assert grower["reversal_count"] == 0


def test_field_acreage_is_surveyed_from_the_rectangle_and_never_from_the_claim(scenario):
    """A 3333 by 1777 rectangle is 5922741 square grid units, so mapped_acres is 1480.69
    however extravagant the grower's own gross_acres claim, which is stored untouched.

    PRD §3.1: "Multiply width by height to get the enclosed area in square grid units,
    divide that area by the 4000 square grid units that make up one programme acre, and
    round the quotient half up to two decimal places."

    Design: Corner/entities/field_mapped_acres_computed_from_rectangle_with_gross_acres_input_ignored
    """
    scenario.set_clock(CLOCK_2026)
    grower = scenario.create_grower(operator_type="PARTNERSHIP", mailing_state="NE")
    payload = field_payload(
        field_name="North Quarter",
        boundary_min_x=0,
        boundary_min_y=0,
        boundary_max_x=3333,
        boundary_max_y=1777,
        gross_acres=9999.99,
        soil_group=SOIL_LOAM,
        county_code="NE-021",
    )

    response = scenario.api.create_field(grower["id"], payload, ADMIN_HEADERS)

    field = validate_success(response, 201)
    assert_acres(field["mapped_acres"], 1480.69)
    assert_acres(field["gross_acres"], 9999.99)
    assert field["status"] == FIELD_DRAFT
    assert field["surveyor_reference"] is None
    assert field["grower_id"] == grower["id"]
    assert field["soil_group"] == SOIL_LOAM
    assert field["county_code"] == "NE-021"
    assert field["version"] == 1


def test_every_addressable_family_answers_an_unknown_id_with_its_own_code(scenario):
    """Thirteen path families each carry their own 404, a body-borne foreign key reports the
    referenced family's 404 rather than a shape complaint, and an unresolvable path
    identifier answers before the malformed body it accompanies.

    PRD §2.6: "The path identifiers the API accepts are `grower_id`, `field_id`,
    `practice_history_id`, `practice_standard_id`, `enrollment_id`, `baseline_id`,
    `data_packet_id`, `quantification_run_id`, `verification_body_id`, `verification_id`,
    `credit_batch_id`, `buffer_account_id`, `reversal_event_id` and `grower_payment_id`;
    each has its own not-found code, listed in §5, and `practice_history_id` reports
    `ERR_PRACTICE_HISTORY_NOT_FOUND`."

    PRD §2.6: "Registering a field under an unknown grower reports `ERR_GROWER_NOT_FOUND`
    even when the request body is also malformed, because grower resolution precedes body
    validation."

    Design: Corner/entities/all_addressable_resources_return_not_found_for_unknown_ids
    """
    scenario.set_clock(CLOCK_2026)
    scenario.create_grower()
    scenario.create_field()
    api = scenario.api
    probes = [
        (api.get_field(UNKNOWN_UUIDS["field"], ADMIN_HEADERS), ERR_FIELD_NOT_FOUND),
        (api.get_practice_history(UNKNOWN_UUIDS["practice_history"], ADMIN_HEADERS),
         ERR_PRACTICE_HISTORY_NOT_FOUND),
        (api.get_practice_standard(UNKNOWN_UUIDS["practice_standard"], ADMIN_HEADERS),
         ERR_PRACTICE_STANDARD_NOT_FOUND),
        (api.get_enrollment(UNKNOWN_UUIDS["enrollment"], ADMIN_HEADERS),
         ERR_ENROLLMENT_NOT_FOUND),
        (api.get_baseline(UNKNOWN_UUIDS["baseline"], ADMIN_HEADERS), ERR_BASELINE_NOT_FOUND),
        (api.get_data_packet(UNKNOWN_UUIDS["data_packet"], ADMIN_HEADERS),
         ERR_DATA_PACKET_NOT_FOUND),
        (api.get_quantification_run(UNKNOWN_UUIDS["quantification_run"], ADMIN_HEADERS),
         ERR_QUANTIFICATION_RUN_NOT_FOUND),
        (api.get_verification_body(UNKNOWN_UUIDS["verification_body"], ADMIN_HEADERS),
         ERR_VERIFICATION_BODY_NOT_FOUND),
        (api.get_verification(UNKNOWN_UUIDS["verification"], ADMIN_HEADERS),
         ERR_VERIFICATION_NOT_FOUND),
        (api.get_credit_batch(UNKNOWN_UUIDS["credit_batch"], ADMIN_HEADERS),
         ERR_CREDIT_BATCH_NOT_FOUND),
        (api.get_buffer_account(UNKNOWN_UUIDS["buffer_account"], ADMIN_HEADERS),
         ERR_BUFFER_ACCOUNT_NOT_FOUND),
        (api.get_reversal_event(UNKNOWN_UUIDS["reversal_event"], ADMIN_HEADERS),
         ERR_REVERSAL_EVENT_NOT_FOUND),
        (api.get_grower_payment(UNKNOWN_UUIDS["grower_payment"], ADMIN_HEADERS),
         ERR_GROWER_PAYMENT_NOT_FOUND),
    ]

    for response, expected in probes:
        validate_error(response, expected, 404)
        assert_error_envelope(response.json(), expected)

    body_foreign_key = api.create_enrollment(
        enrollment_payload(
            UNKNOWN_UUIDS["field"], UNKNOWN_UUIDS["practice_standard"], enrolled_acres=100.00
        ),
        ADMIN_HEADERS,
    )
    validate_error(body_foreign_key, ERR_FIELD_NOT_FOUND, 404)
    assert ERR_INVALID_REQUEST not in body_foreign_key.text

    leftmost = api.create_field(
        UNKNOWN_UUIDS["grower"],
        field_payload(
            field_name="",
            boundary_min_x=10,
            boundary_min_y=0,
            boundary_max_x=5,
            boundary_max_y=20,
            gross_acres=-1.00,
            soil_group="MARS_REGOLITH",
        ),
        ADMIN_HEADERS,
    )
    validate_error(leftmost, ERR_GROWER_NOT_FOUND, 404)
    assert ERR_INVALID_REQUEST not in leftmost.text


def test_practice_history_rows_are_immutable_and_carry_no_version(scenario):
    """A filed evidence row exposes id and created_at and nothing else from the audit
    quartet, and the filtered list is the discovery channel that isolates one crop year.

    PRD §2.5: "It has neither `updated_at` nor `version`, there is no endpoint that edits
    or deletes it, and nothing in the system ever rewrites one."

    Design: Corner/entities/practice_history_is_immutable_with_no_version_field_and_no_update_endpoint
    """
    scenario.set_clock(CLOCK_2026)
    scenario.create_grower(operator_type="CORPORATION", mailing_state="MN")
    field = scenario.create_field(field_name="River Flat")
    first = validate_success(
        scenario.api.file_practice_history(
            field["id"],
            practice_history_payload(
                2021,
                practice_code=PRACTICE_COVER_CROP,
                adopted=True,
                evidence_source=EVIDENCE_FARM_RECORD,
                acres=200.00,
                observed_emissions_per_acre=0.1000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(
        scenario.api.file_practice_history(
            field["id"],
            practice_history_payload(2022, observed_emissions_per_acre=0.1500),
            ADMIN_HEADERS,
        ),
        201,
    )

    row = validate_success(scenario.api.get_practice_history(first["id"], ADMIN_HEADERS))

    assert set(row) == HISTORY_KEYS
    assert_immutable_common_fields(row)
    assert row["field_id"] == field["id"]
    assert row["crop_year"] == 2021
    assert row["practice_code"] == PRACTICE_COVER_CROP
    assert row["adopted"] is True
    assert row["evidence_source"] == EVIDENCE_FARM_RECORD
    assert_acres(row["acres"], 200.00)
    assert_rate(row["observed_emissions_per_acre"], 0.1000)
    rows, meta = validate_paginated(
        scenario.api.list_practice_history(
            {"field_id": field["id"], "crop_year": 2021}, ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert [r["id"] for r in rows] == [first["id"]]


def test_enrollment_listing_windows_filters_and_counts_independently(scenario):
    """Three draft enrollments across two growers page two-and-one under limit 2, and each
    filter narrows total_count without changing the envelope shape.

    PRD §2.3: "`total_count` reports the number of rows matching the filters before the
    window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/enrollment_listing_paginates_filters_and_reports_total_count
    """
    scenario.set_clock(CLOCK_2026)
    standard = scenario.publish_standard()
    first_grower = scenario.create_grower(legal_name="Alder Ridge Farms")
    field_one = scenario.mapped_field(field_name="A-1")
    field_two = scenario.register_field(
        field_name="A-2", boundary_min_x=2000, boundary_max_x=4000, soil_group=SOIL_CLAY
    )
    scenario.map_confirm(field_two["id"])
    second_grower = scenario.create_grower(
        legal_name="Beacon Hollow Farms", operator_type="SOLE_PROPRIETOR"
    )
    field_three = scenario.register_field(
        second_grower["id"], field_name="B-1", soil_group=SOIL_SAND
    )
    scenario.map_confirm(field_three["id"])
    first = validate_success(
        scenario.api.create_enrollment(
            enrollment_payload(field_one["id"], standard["id"]), ADMIN_HEADERS
        ),
        201,
    )
    second = validate_success(
        scenario.api.create_enrollment(
            enrollment_payload(field_two["id"], standard["id"], per_credit_share_pct=55.00),
            ADMIN_HEADERS,
        ),
        201,
    )
    third = validate_success(
        scenario.api.create_enrollment(
            per_acre_enrollment_payload(field_three["id"], standard["id"]), ADMIN_HEADERS
        ),
        201,
    )

    first_response = scenario.api.list_enrollments({"limit": 2, "offset": 0}, ADMIN_HEADERS)
    page_one, meta_one = validate_paginated(first_response)
    page_two, meta_two = validate_paginated(
        scenario.api.list_enrollments({"limit": 2, "offset": 2}, ADMIN_HEADERS)
    )
    by_model, meta_model = validate_paginated(
        scenario.api.list_enrollments({"payment_model": PAYMENT_MODEL_PER_ACRE}, ADMIN_HEADERS)
    )
    by_grower, meta_grower = validate_paginated(
        scenario.api.list_enrollments(
            {"grower_id": first_grower["id"], "status": ENROLLMENT_DRAFT}, ADMIN_HEADERS
        )
    )

    assert_success_envelope(first_response.json(), "array")
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2
    assert meta_model["total_count"] == 1
    assert [row["id"] for row in by_model] == [third["id"]]
    assert meta_grower["total_count"] == 2
    assert {row["id"] for row in by_grower} == {first["id"], second["id"]}
    windowed = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert sorted(windowed) == sorted([first["id"], second["id"], third["id"]])


def test_enrollment_copies_its_grower_from_the_field_it_names(scenario):
    """The creation body never mentions a grower, yet the enrollment comes back owned by the
    field's grower and pinned to the standard's practice code and version.

    PRD §3.4: "Three fields are copied at creation and never re-read afterwards:
    `grower_id` is derived from the referenced field's owning grower, `practice_code` is
    copied from the standard, and `pinned_standard_version` is copied from the standard's
    `standard_version`."

    Design: Corner/entities/enrollment_parent_relationship_binds_grower_through_field
    """
    scenario.set_clock(CLOCK_2026)
    standard = scenario.publish_standard(
        practice_code=PRACTICE_REDUCED_TILLAGE,
        sequestration_rate_per_acre=0.3000,
        modeled_baseline_rate_per_acre=0.1800,
        telemetry_required=False,
    )
    grower = scenario.create_grower(legal_name="Sandhill Acres", mailing_state="KS")
    field = scenario.mapped_field(field_name="West Pivot", soil_group=SOIL_SAND)
    payload = per_acre_enrollment_payload(
        field["id"], standard["id"], commitment_years=4, enrolled_acres=900.00,
        per_acre_rate_cents=800.00,
    )
    assert "grower_id" not in payload

    response = scenario.api.create_enrollment(payload, ADMIN_HEADERS)

    enrollment = validate_success(response, 201)
    assert enrollment["grower_id"] == grower["id"]
    assert enrollment["field_id"] == field["id"]
    assert enrollment["practice_code"] == PRACTICE_REDUCED_TILLAGE
    assert enrollment["pinned_standard_version"] == 1
    assert enrollment["status"] == ENROLLMENT_DRAFT
    assert enrollment["permanence_status"] == PERMANENCE_NOT_STARTED
    assert_credits(enrollment["credits_issued_total"], 0)
    assert_cents(enrollment["accrued_payment_cents"], 0)
    assert enrollment["additionality_score"] is None
    assert enrollment["documented_years"] is None
    _by_grower, meta_grower = validate_paginated(
        scenario.api.list_enrollments({"grower_id": grower["id"]}, ADMIN_HEADERS)
    )
    by_field, meta_field = validate_paginated(
        scenario.api.list_enrollments({"field_id": field["id"]}, ADMIN_HEADERS)
    )
    assert meta_grower["total_count"] == 1
    assert meta_field["total_count"] == 1
    assert [row["id"] for row in by_field] == [enrollment["id"]]
