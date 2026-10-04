"""Server-managed resource fields, global uniqueness, and role reach."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_qualification,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


# ══════════════════════════════════════════════════════════════════════════
# Server-managed equipment fields
# ══════════════════════════════════════════════════════════════════════════

def test_commissioning_ignores_client_supplied_status_and_verdict(api):
    """PRD §3.1: "Two fields of the equipment record — `equipment_status` and
    `performance_verdict` — are server-managed and are not client inputs. A
    caller may include them in a commissioning payload, but the values are
    ignored: a new item always starts with `equipment_status` `ACTIVE` and
    `performance_verdict` `PENDING`"

    Design: Corner/entities/equipment_create_ignores_system_equipment_status_and_verdict
    """
    scenario = setup_imaging_facility()
    commissioned = validate_success(
        api_client.create_equipment(
            {
                "unit_id": scenario.unit_id,
                "manufacturer": "GE",
                "model_number": "REV-A",
                "serial_number": "SN-CT-0002",
                "modality_code": "CT",
                "installed_on": "2026-08-02T00:00:00Z",
                "equipment_status": "RETIRED",
                "performance_verdict": "FAIL",
            },
            scenario.admin,
        ),
        201,
    )
    assert commissioned["equipment_status"] == "ACTIVE"
    assert commissioned["performance_verdict"] == "PENDING"
    assert commissioned["modality_code"] == "CT"
    assert commissioned["serial_number"] == "SN-CT-0002"


def test_a_newly_commissioned_item_starts_at_version_one(api):
    """PRD §2.8: "`version` (integer): a server-managed counter that starts at
    1 and advances by one on every mutation of the resource"
    PRD §2.5: "Each affected resource has its `updated_at` refreshed, and each
    affected resource's `version` advances by exactly one per mutation"

    Design: Corner/entities/equipment_create_ignores_system_equipment_status_and_verdict
    """
    scenario = setup_imaging_facility()
    version_before = read_unit(scenario.unit_id)["version"]

    commissioned = validate_success(
        api_client.create_equipment(
            {
                "unit_id": scenario.unit_id,
                "manufacturer": "GE",
                "model_number": "REV-A",
                "serial_number": "SN-CT-0002",
                "modality_code": "CT",
                "installed_on": "2026-08-02T00:00:00Z",
                "equipment_status": "RETIRED",
                "performance_verdict": "FAIL",
            },
            scenario.admin,
        ),
        201,
    )
    assert commissioned["version"] == 1
    assert read_unit(scenario.unit_id)["version"] == version_before + 1


# ══════════════════════════════════════════════════════════════════════════
# Globally unique credential numbers
# ══════════════════════════════════════════════════════════════════════════

def test_a_credential_number_is_unique_across_facilities(api, facility_admin_headers):
    """PRD §3.8: "The `credential_number` must be globally unique across all
    qualifications, with `ERR_CREDENTIAL_NUMBER_DUPLICATE` raised on
    collision."

    Design: Corner/validations/credential_number_unique_across_facilities_not_just_within_one
    """
    setup_imaging_facility()
    other = validate_success(
        api.create_facility(
            {"name": "Lakeside MRI", "state_code": "MN", "facility_type": "HOSPITAL"},
            facility_admin_headers,
        ),
        201,
    )

    res = api_client.create_personnel_qualification(
        {
            "facility_id": other["id"],
            "person_name": "Hana Reyes",
            "personnel_role": "TECHNOLOGIST",
            "credential_number": "TECH-1001",
            "ce_credit_hours": 24.0,
            "required_ce_hours": 24.0,
            "credential_expires_on": "2027-06-30T00:00:00Z",
        },
        REVIEWER,
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_CREDENTIAL_NUMBER_DUPLICATE")
    assert error["error_id"] != "ERR_INVALID_REQUEST"


def test_a_colliding_credential_number_creates_no_row_at_the_other_facility(api, facility_admin_headers):
    """PRD §2.11: "Optional cross-references are validated on the same
    footing"
    PRD §3.8: "A new qualification begins in `PENDING` status with
    `qualification_verified_at` null and `survey_count` at `0`."

    Design: Corner/validations/credential_number_unique_across_facilities_not_just_within_one
    """
    scenario = setup_imaging_facility()
    other = validate_success(
        api.create_facility(
            {"name": "Lakeside MRI", "state_code": "MN", "facility_type": "HOSPITAL"},
            facility_admin_headers,
        ),
        201,
    )
    api_client.create_personnel_qualification(
        {
            "facility_id": other["id"],
            "person_name": "Hana Reyes",
            "personnel_role": "TECHNOLOGIST",
            "credential_number": "TECH-1001",
            "ce_credit_hours": 24.0,
            "required_ce_hours": 24.0,
            "credential_expires_on": "2027-06-30T00:00:00Z",
        },
        REVIEWER,
    )

    data, meta = validate_paginated(
        api_client.list_personnel_qualifications(READER, {"facility_id": other["id"]})
    )
    assert meta["total_count"] == 0
    assert data == []
    assert read_facility(other["id"])["roster_disposition"] == "CLEAR"

    # The original row still belongs to the first facility.
    original = read_qualification(scenario.tech_qualification_id)
    assert original["facility_id"] == scenario.facility_id
    assert original["credential_number"] == "TECH-1001"


# ══════════════════════════════════════════════════════════════════════════
# Role reach on the qualification roster
# ══════════════════════════════════════════════════════════════════════════

def test_the_roster_read_is_reachable_by_an_any_principal(api):
    """PRD §2.1: "`Any` denotes any authenticated caller of any role and
    exists only so that read operations, the facility summary, and the
    logical clock can be reached without pinning a specific role"

    Design: Corner/roles/only_facility_admin_and_any_can_read_the_qualification_roster
    """
    scenario = setup_imaging_facility()
    data, meta = validate_paginated(
        api_client.list_personnel_qualifications(READER, {"facility_id": scenario.facility_id})
    )
    assert meta["total_count"] == 2
    numbers = {row["credential_number"] for row in data}
    assert numbers == {"TECH-1001", "PHYS-2001"}


def test_an_undeclared_role_is_refused_on_the_roster_read(api):
    """PRD §2.1: "A request that omits either header, or that supplies a role
    value not among the declared roles, is rejected with `ERR_UNAUTHENTICATED`
    at HTTP 401."

    Design: Corner/roles/only_facility_admin_and_any_can_read_the_qualification_roster
    """
    scenario = setup_imaging_facility()
    before, _ = validate_paginated(
        api_client.list_personnel_qualifications(READER, {"facility_id": scenario.facility_id})
    )

    res = api_client.list_personnel_qualifications(
        {"X-User-ID": "roster-auditor", "X-User-Role": "Auditor", "Content-Type": "application/json"},
        {"facility_id": scenario.facility_id},
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNAUTHENTICATED")
    assert error["error_id"] != "ERR_UNAUTHORIZED"

    after, _ = validate_paginated(
        api_client.list_personnel_qualifications(READER, {"facility_id": scenario.facility_id})
    )
    assert len(after) == len(before) == 2