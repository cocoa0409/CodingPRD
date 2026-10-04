"""Corner queue: entity-system-field and computed-field claims."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_days,
    assert_charge,
    assert_complainant,
    assert_deferral_agency,
    assert_disclosure_record,
    assert_employer,
    assert_evidence_request,
    assert_witness_interview,
    assign_investigator,
    create_complainant,
    create_complainant_payload,
    create_deferral_agency,
    create_deferral_agency_payload,
    create_employer,
    expected_size_band,
    file_charge,
    is_valid_uuid,
    log_interview,
    make_platform_admin_headers,
    read_charge,
    record_disclosure,
    set_clock,
    setup_docketed_charge,
    setup_gathering,
    setup_under_investigation,
    update_employer_payload,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_complainant_creation_system_fields(api):
    """PRD section 4: "Operations that create a new resource return `201 Created`; operations that modify an existing resource, record a party action, or drive a state transition return `200 OK`, as do all reads."
    PRD section 2.5: "`id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix."
    PRD section 2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created."
    PRD section 2.4: "Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z` — a fixed startup default, never the host's wall-clock time."

    Design: Corner/entities/complainant_creation_system_fields
    """
    response = api_client.create_complainant(
        create_complainant_payload(full_name="Casey One", email="c1@x.com"),
        _INTAKE,
    )
    data = validate_created(response)
    assert_complainant(data)
    assert is_valid_uuid(data["id"])
    # created_at derives from the untouched boot clock, 2026-09-01T00:00:00Z.
    assert data["created_at"].startswith("2026-09-01T00:00:00")


def test_employer_band_recomputed_on_patch(api):
    """PRD section 3.1: "From that headcount the system derives the employer's `size_band`, recomputed on creation and again on every update: `UNDER_15` for 0–14 employees, `FROM_15_TO_19` for 15–19, `FROM_20_TO_100` for 20–100, `FROM_101_TO_200` for 101–200, `FROM_201_TO_500` for 201–500, and `OVER_500` for 501 or more."
    PRD section 3.1: "Updating an employer (the intake officer may patch `employee_count_current` and/or `legal_name`) increments the employer's `version` by 1, recomputes `size_band`, and re-bands every `PROVISIONAL` `RemedyPackage` attached to that employer's non-terminal conciliations — each re-banded package keeps its original `projection_date`, only the cap tier moves."

    Design: Corner/entities/employer_band_recomputed_on_patch
    """
    employer = create_employer(state_code="FL", employee_count_current=90,
                               legal_name="Band Co")
    assert_employer(employer)
    assert employer["size_band"] == expected_size_band(90) == "FROM_20_TO_100"
    created_version = employer["version"]

    patched_up = validate_ok(
        api_client.update_employer(
            employer["id"], update_employer_payload(employee_count_current=101),
            _INTAKE,
        )
    )
    assert patched_up["size_band"] == expected_size_band(101) == "FROM_101_TO_200"
    assert patched_up["version"] == created_version + 1

    patched_down = validate_ok(
        api_client.update_employer(
            employer["id"], update_employer_payload(employee_count_current=14),
            _INTAKE,
        )
    )
    assert patched_down["size_band"] == expected_size_band(14) == "UNDER_15"
    assert patched_down["version"] == created_version + 2


def test_deferral_agency_deadline_invalid_enum_rejected(api):
    """PRD section 3.1: "Only two deadline values are accepted — 180 or 300 days — and any other value is rejected with `ERR_VALIDATION_FAILED`."

    Design: Corner/entities/deferral_agency_deadline_invalid_enum_rejected
    """
    response = api_client.create_deferral_agency(
        create_deferral_agency_payload(
            state_code="CA", agency_name="CA FEPA", filing_deadline_days=200,
            work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        ),
        _ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION_FAILED)


def test_deferral_agency_duplicate_state_rejected(api):
    """PRD section 3.1: "One agency exists per state: registering a second agency for a `state_code` already on file is rejected with `ERR_DUPLICATE_AGENCY_STATE`."

    Design: Corner/entities/deferral_agency_duplicate_state_rejected
    """
    first = create_deferral_agency(
        state_code="CA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        agency_name="CA FEPA",
    )
    assert_deferral_agency(first)
    duplicate = api_client.create_deferral_agency(
        create_deferral_agency_payload(
            state_code="CA", agency_name="CA Second Agency",
            filing_deadline_days=180, work_sharing_policy="EEOC_RETAINS_ALL",
            covers_age=False,
        ),
        make_platform_admin_headers("test-admin-2"),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_AGENCY_STATE)


def test_charge_received_date_stamped_from_clock(api):
    """PRD section 3.2: "The `received_date` is stamped from the logical clock."
    PRD section 3.2: "The charge's `filing_deadline_date` is the `incident_date` plus that many days, and the timeliness test is inclusive — a charge whose `received_date` falls on or before the `filing_deadline_date` is timely; one received after it is not."

    Design: Corner/entities/charge_received_date_stamped_from_clock
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Stamp Co")
    complainant = create_complainant(full_name="Casey Two", email="c2@x.com")
    set_clock("2026-10-15T00:00:00Z")

    charge = file_charge(employer, complainant, basis_codes=["RACE"],
                         incident_date="2026-08-01", harm_description="fired",
                         employee_count_at_incident=40)
    assert_charge(charge)
    assert charge["received_date"][:10] == "2026-10-15"  # the logical clock date
    # Deadline under the federal 180-day default: 2026-08-01 + 180 = 2027-01-28,
    # still after the receipt date, so the charge dockets.
    assert charge["filing_deadline_date"][:10] == add_days("2026-08-01", 180) == "2027-01-28"
    assert charge["case_status"] == "DOCKETED"


def test_charge_snapshot_immune_to_employer_patch(api):
    """PRD section 3.2: "The size screen uses only the `employee_count_at_incident` snapshot — never the employer's current headcount."
    PRD section 3.1: "Updating an employer (the intake officer may patch `employee_count_current` and/or `legal_name`) increments the employer's `version` by 1, recomputes `size_band`, and re-bands every `PROVISIONAL` `RemedyPackage` attached to that employer's non-terminal conciliations — each re-banded package keeps its original `projection_date`, only the cap tier moves."

    Design: Corner/entities/charge_snapshot_immune_to_employer_patch
    """
    base = setup_docketed_charge(employee_count=90, incident_date="2026-06-01")
    employer = base["employer"]
    charge = base["charge"]
    assert charge["case_status"] == "DOCKETED"

    shrunk = validate_ok(
        api_client.update_employer(
            employer["id"], update_employer_payload(employee_count_current=4),
            _INTAKE,
        )
    )
    assert shrunk["size_band"] == "UNDER_15"

    # The 90-person snapshot governs: the charge neither re-screens nor moves.
    reread = read_charge(charge["id"])
    assert reread["case_status"] == "DOCKETED"
    assert reread["investigation_owner"] == "EEOC"
    assert reread["covered_bases"] == ["RACE"]
    assert reread["employee_count_at_incident"] == 90


def test_evidence_request_due_date_computed_30_days(api):
    """PRD section 3.5: "The `issued_date` is stamped from the logical clock and the `due_date` is computed as exactly 30 days after issuance — the respondent's statutory response window."

    Design: Corner/entities/evidence_request_due_date_computed_30_days
    """
    base = setup_gathering(investigator_user_id="inv-020")
    request = base["evidence_request"]
    assert_evidence_request(request)
    assert request["status"] == "PENDING"
    assert request["issued_date"][:10] == "2026-09-01"
    assert request["due_date"][:10] == add_days("2026-09-01", 30) == "2026-10-01"


def test_charge_list_pagination_and_filters(api):
    """PRD section 2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0."
    PRD section 2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD section 3.2: "The paginated charge list supports filters `status`, `employer_id`, `complainant_id`, `deferral_agency_id`, `systemic_case_id`, and `basis`, alongside the standard `limit` and `offset`."

    Design: Corner/entities/charge_list_pagination_and_filters
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Page Co")
    complainant = create_complainant(full_name="Casey Five", email="c5@x.com")
    for day in range(1, 12):  # 2026-06-01 .. 2026-06-11, all timely at boot
        file_charge(employer, complainant, basis_codes=["RACE"],
                    incident_date=f"2026-06-{day:02d}",
                    harm_description=f"c{day}", employee_count_at_incident=40)

    first_page, meta = validate_paginated(api_client.list_charges(_DIRECTOR))
    assert len(first_page) == 10
    assert meta["total_count"] == 11
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api_client.list_charges(_DIRECTOR, params={"offset": 10})
    )
    assert len(second_page) == 1
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api_client.list_charges(
            _DIRECTOR,
            params={"employer_id": employer["id"], "status": "DOCKETED"},
        )
    )
    assert meta3["total_count"] == 11
    assert all(
        row["employer_id"] == employer["id"] and row["case_status"] == "DOCKETED"
        for row in filtered
    )


def test_disclosure_record_append_only_no_version(api):
    """PRD section 2.5: "Because it is an append-only audit row with no update or delete path, it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it."
    PRD section 3.9: "Each `DisclosureRecord` stamps the acting `accessor_role` and `accessor_user_id` and the clock time `disclosed_at`."

    Design: Corner/entities/disclosure_record_append_only_no_version
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    record = record_disclosure(
        base["charge"], legal_basis="PARTY_CONSENT",
        target_description="charging party's attorney",
    )
    # assert_disclosure_record pins the absence of updated_at and version.
    assert_disclosure_record(record)
    assert record["accessor_role"] == "Director"
    assert record["legal_basis"] == "PARTY_CONSENT"
    assert record["disclosed_at"][:10] == "2026-09-01"
    assert record["created_at"].startswith("2026-09-01T00:00:00")

    rows, _meta = validate_paginated(
        api_client.list_disclosures(base["charge"]["id"], _DIRECTOR)
    )
    assert len(rows) == 1 and rows[0]["id"] == record["id"]


def test_interview_stamps_logging_investigator(api):
    """PRD section 3.5: "The logging investigator is stamped as `investigator_user_id` and must be the case's assignee."
    PRD section 3.5: "The first evidence activity on a case (a request or an interview) moves it `OPEN` → `GATHERING`."

    Design: Corner/entities/interview_stamps_logging_investigator
    """
    base = setup_under_investigation(basis_codes=["RACE"],
                                     incident_date="2026-06-01")
    case_id = base["investigation_case_id"]
    assign_investigator(case_id, "inv-021")

    interview = log_interview(
        case_id, "inv-021", witness_name="W1",
        interview_start="2026-09-05T10:00:00Z",
        interview_end="2026-09-05T11:00:00Z", summary="corroborates",
    )
    assert_witness_interview(interview)
    assert interview["investigator_user_id"] == "inv-021"  # stamped from header

    # The interview is this case's first evidence activity.
    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["status"] == "GATHERING"
