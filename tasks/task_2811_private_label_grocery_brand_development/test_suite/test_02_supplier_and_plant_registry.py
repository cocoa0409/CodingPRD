"""Enrolling suppliers, registering plant lines and scheduling audits."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_freshly_created,
    assert_instant_equals,
    assert_supplier_status,
)
from test_helpers.constants import (
    DEFAULT_CHANGEOVER_BUFFER_MINUTES,
    SUPPLIER_PROSPECT,
    UNKNOWN_UUID_1,
)
from test_helpers.fixtures import advance_clock
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    SOURCING_HEADERS,
)


def test_supplier_read_echoes_its_stored_fields_and_untouched_defaults(api, program):
    """An enrolled supplier reads back PROSPECT with null qualified_at.

    PRD 3.2: "Enrolment opens the supplier at `qualification_status` `PROSPECT`
    with `qualified_at` null, `composite_score_cached` null,
    `probation_item_count` at zero and `weighted_complaint_points` at zero."

    Design: Corner/entities/supplier_get_by_id_returns_stored_fields
    """
    created = validate_success(
        api.create_supplier(f.supplier_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    supplier = validate_success(api.get_supplier(created["id"], QUALITY_HEADERS))
    assert supplier["legal_name"] == "Northmill Bakers"
    assert supplier["plant_country"] == "US"
    assert_instant_equals(
        supplier["gfsi_certificate_expiry"],
        "2027-06-30T00:00:00Z",
        "gfsi_certificate_expiry",
    )
    assert_supplier_status(supplier, SUPPLIER_PROSPECT)
    assert supplier["qualified_at"] is None
    assert supplier["composite_score_cached"] is None
    assert supplier["probation_item_count"] == 0
    assert supplier["weighted_complaint_points"] == 0
    assert supplier["version"] == 1


def test_supplier_create_stamps_its_system_fields_from_the_logical_clock(api, program):
    """created_at and updated_at are stamped from the logical clock at insert.

    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with exactly three fractional-second digits, recorded at insert and never
    changed thereafter."

    Design: Corner/entities/supplier_create_stamps_system_fields_and_version_one
    """
    advance_clock(api, "2026-08-05T00:00:00Z")

    supplier = validate_success(
        api.create_supplier(f.supplier_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    assert is_valid_uuid(supplier["id"]), "the server mints the id as a UUID"
    assert_instant_equals(
        supplier["created_at"], "2026-08-05T00:00:00Z", "created_at"
    )
    assert_freshly_created(supplier, "supplier")
    assert_supplier_status(supplier, SUPPLIER_PROSPECT)


def test_plant_line_read_for_an_unknown_id_is_a_plant_line_not_found(api, program):
    """An unresolvable path identifier is a 404, not an empty success body.

    PRD 2.9: "Path identifiers are resolved left to right, and the first
    unresolvable segment determines the 404 code."

    Design: Corner/entities/plant_line_get_unknown_id_returns_not_found
    """
    response = api.get_plant_line(UNKNOWN_UUID_1, SOURCING_HEADERS)
    validate_error(response, ApiErrorId.ERR_PLANT_LINE_NOT_FOUND.value, 404)


def test_plant_line_omitting_the_changeover_buffer_defaults_it_to_two_hours(
    api, program
):
    """An omitted changeover buffer stores the declared two-hour default.

    PRD 3.2: "The buffer may be zero or any positive number of minutes and
    defaults to two hours when the field is omitted at registration."

    Design: Corner/entities/plant_line_create_omitting_changeover_buffer_defaults_to_120
    """
    supplier = validate_success(
        api.create_supplier(f.supplier_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    line = validate_success(
        api.create_plant_line(
            f.plant_line_payload(
                supplier["id"],
                line_code="CRK-9",
                daily_capacity_units=48000,
                changeover_buffer_minutes=None,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    assert line["changeover_buffer_minutes"] == DEFAULT_CHANGEOVER_BUFFER_MINUTES
    assert line["daily_capacity_units"] == 48000
    assert_freshly_created(line, "plant line")


def test_second_line_reusing_a_line_code_at_the_same_plant_is_rejected(
    api, prospect_supplier
):
    """A line code is unique within its supplier whatever its capacity.

    PRD 3.2: "A line carries the `supplier_id` that owns it, a `line_code` that
    must be unique within that supplier — a repeat is refused with
    `ERR_DUPLICATE_LINE_CODE` (HTTP 409)"

    Design: Corner/validations/duplicate_line_code_for_same_supplier_rejected
    """
    supplier_id = prospect_supplier["supplier_id"]

    response = api.create_plant_line(
        f.plant_line_payload(
            supplier_id,
            line_code="CRK-1",
            daily_capacity_units=45000,
            changeover_buffer_minutes=None,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_LINE_CODE.value, 409)

    rows, meta = validate_paginated(
        api.list_plant_lines(SOURCING_HEADERS, params={"supplier_id": supplier_id})
    )
    assert meta["total_count"] == 1, "the duplicate must not have been registered"
    assert rows[0]["line_code"] == "CRK-1"
    assert rows[0]["daily_capacity_units"] == 60000
    assert rows[0]["changeover_buffer_minutes"] == DEFAULT_CHANGEOVER_BUFFER_MINUTES


def test_audit_with_an_unrecognised_audit_type_fails_the_shape_gate_first(
    api, program
):
    """A bad enum is a well-formedness rejection, ahead of window ordering.

    PRD 2.9: "Checks are evaluated in a strict order, and the **first** violated
    check determines the response; later violations are neither reported nor
    merged into the response, even when they are also true."

    Design: Corner/entities/plant_audit_create_with_invalid_enum_audit_type_rejected
    """
    supplier = validate_success(
        api.create_supplier(f.supplier_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    response = api.create_plant_audit(
        f.plant_audit_payload(
            supplier["id"],
            audit_type="SUPPLIER_VISIT",
            window_start="2026-09-10T08:00:00Z",
            window_end="2026-09-09T08:00:00Z",
        ),
        QUALITY_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    _, meta = validate_paginated(
        api.list_plant_audits(
            DIRECTOR_HEADERS, params={"supplier_id": supplier["id"]}
        )
    )
    assert meta["total_count"] == 0, "a refused schedule persists no audit"
