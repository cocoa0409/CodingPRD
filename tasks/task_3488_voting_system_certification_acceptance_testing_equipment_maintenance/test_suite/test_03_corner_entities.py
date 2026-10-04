"""Breadth probes over resource creation defaults, schema constraints,
immutable records, path resolution, and list filtering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_acceptance_test,
    assert_custody_transfer,
    assert_voting_system,
    create_campaign_payload,
    create_equipment_unit,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_official,
    create_official_payload,
    create_test_laboratory,
    create_test_laboratory_payload,
    create_voting_system,
    create_voting_system_payload,
    make_election_official_headers,
    record_acceptance_test,
    set_clock,
    setup_certified_jurisdiction,
    setup_procurement,
    transfer_custody,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
VENDOR = TEST_USERS["vendor_rep_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_voting_system_create_returns_defaults(api):
    """PRD §3.1: "A new system enters life in `REGISTERED` status."
    PRD §2.4: "The server must boot with its logical clock fixed at
    `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under
    any circumstance."
    PRD §2.5: "`id` is a server-minted UUID with no type prefix. `created_at`
    is an ISO 8601 UTC timestamp with three fractional digits recording
    creation. `updated_at` is the same shape, refreshed on every mutation."

    Design: Corner/entities/voting_system_create_returns_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_voting_system(create_voting_system_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert_voting_system(data)
    assert resp.json()["response_type"] == "object"
    assert data["status"] == "REGISTERED"
    assert data["version"] == 1
    assert data["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must be stamped from the booted logical clock, got {data['created_at']!r}"
    )


def test_laboratory_create_applies_default_capacity(api):
    """PRD §3.1: "A `PlatformAdmin` accredits a **test laboratory** with a
    globally unique `lab_code` (a duplicate is rejected with
    `ERR_DUPLICATE_LAB_CODE`), a display `lab_name`, an
    `accreditation_scope` of `FEDERAL`, `STATE`, or `DUAL`, and an optional
    `max_concurrent_campaigns` that defaults to 3 and must lie between 1 and
    10 inclusive. A laboratory is `ACCREDITED` on creation".

    Design: Corner/entities/laboratory_create_applies_default_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = create_test_laboratory_payload(lab_name="Alpha Test Lab")
    assert "max_concurrent_campaigns" not in payload, "client omits the optional field"
    resp = api.create_test_laboratory(payload, ADMIN)
    data = validate_success(resp, 201)
    assert data["max_concurrent_campaigns"] == 3, "server applies the declared default"
    assert data["status"] == "ACCREDITED"


def test_campaign_create_initializes_counters(api):
    """PRD §3.2: "A new campaign starts `SUBMITTED` with
    `resubmission_count`, `open_critical_count`, `open_major_count`, and
    `open_minor_count` all at zero, both conformity scores at 10000 basis
    points, `last_submitted_at` stamped from the logical clock, and
    `completed_at` null."

    Design: Corner/entities/campaign_create_initializes_counters
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    resp = api.create_certification_campaign(
        create_campaign_payload(system["id"], lab["id"], state_code="CA"), VENDOR
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SUBMITTED"
    assert data["open_critical_count"] == 0
    assert data["open_major_count"] == 0
    assert data["open_minor_count"] == 0
    assert data["resubmission_count"] == 0
    assert data["conformity_screen_bp"] == 10000
    assert data["conformity_final_bp"] == 10000
    assert data["last_submitted_at"].startswith("2026-09-01T00:00:00")
    assert data["completed_at"] is None


def test_invalid_enum_member_rejected(api):
    """PRD §2.7: "4. **Body well-formedness** — required fields present, no
    undeclared fields, enum values in range, types correct, integer bounds
    respected (`quantity` at least 1, defect and finding counts at least 0,
    `scheduled_end` strictly after `scheduled_start`,
    `max_concurrent_campaigns` between 1 and 10 inclusive); otherwise
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "A `VendorRep` opens a **certification campaign** by naming the
    system under test (`voting_system_id`), the laboratory that will run it
    (`lab_id`), the federal guideline `guidelines_baseline` (`VVSG_1_1` or
    `VVSG_2_0`), and optionally a two-letter `state_code`".

    Design: Corner/entities/invalid_enum_member_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    resp = api.create_certification_campaign(
        create_campaign_payload(
            system["id"], lab["id"], guidelines_baseline="VVSG_9_9", state_code="CA"
        ),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_with_system_field_rejected(api):
    """PRD §2.7: "4. **Body well-formedness** — required fields present, no
    undeclared fields, enum values in range, types correct, integer bounds
    respected (`quantity` at least 1, defect and finding counts at least 0,
    `scheduled_end` strictly after `scheduled_start`,
    `max_concurrent_campaigns` between 1 and 10 inclusive); otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_with_system_field_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = create_jurisdiction_payload(
        name="Mono County", state_code="CA", budget_total_cents=100_000_000
    )
    payload["id"] = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    payload["available_cents"] = 5
    resp = api.create_jurisdiction(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_campaign_create_missing_required_field_rejected(api):
    """PRD §2.7: "4. **Body well-formedness** — required fields present, no
    undeclared fields, enum values in range, types correct, integer bounds
    respected (`quantity` at least 1, defect and finding counts at least 0,
    `scheduled_end` strictly after `scheduled_start`,
    `max_concurrent_campaigns` between 1 and 10 inclusive); otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/campaign_create_missing_required_field_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    resp = api.create_certification_campaign(
        {"voting_system_id": system["id"], "guidelines_baseline": "VVSG_2_0"},
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_equipment_unit_create_initializes_parallel_dimensions(api):
    """PRD §3.7: "A unit is born with `operational_status` `IN_STORAGE`,
    `custody_status` `SECURED`, `current_custodian_id` equal to
    `initial_custodian_id`, `battery_cycles` 0, `storage_excursion_count` 0,
    `pre_maintenance_status` null, and both calibrated paper fields null."

    Design: Corner/entities/equipment_unit_create_initializes_parallel_dimensions
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    resp = api.create_equipment_unit(
        {
            "jurisdiction_id": base["jurisdiction"]["id"],
            "voting_system_id": base["system"]["id"],
            "serial_number": "SN-1001",
            "initial_custodian_id": off1,
        },
        make_election_official_headers(off1),
    )
    data = validate_success(resp, 201)
    assert data["operational_status"] == "IN_STORAGE"
    assert data["custody_status"] == "SECURED"
    assert data["battery_cycles"] == 0
    assert data["storage_excursion_count"] == 0
    assert data["current_custodian_id"] == off1
    assert data["pre_maintenance_status"] is None
    assert data["calibrated_paper_weight_gsm"] is None
    assert data["calibrated_paper_thickness_microns"] is None


def test_event_records_carry_no_version_field(api):
    """PRD §2.5: "Two resource types are exceptions because they are
    immutable records: an **AcceptanceTest** and a **CustodyTransfer** carry
    only `id` and `created_at`. Both `updated_at` and `version` are absent
    from these two resources, and no endpoint modifies them after creation."

    Design: Corner/entities/event_records_carry_no_version_field
    """
    base = setup_procurement("ACCEPTANCE_TESTING")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-1001"
    )
    acceptance = record_acceptance_test(
        base["procurement"]["id"], off1,
        test_type="HARDWARE_DIAGNOSTIC",
        critical_defects=0, major_defects=1, minor_defects=0,
    )
    assert_acceptance_test(acceptance)
    assert "version" not in acceptance and "updated_at" not in acceptance
    assert acceptance["deficiency_index"] == 8, "25*0 + 8*1 + 2*0 = 8"
    assert acceptance["result"] == "PASS"

    transfer = transfer_custody(
        unit["id"], off1, off2, seal_number="SEAL-1001-A", seal_intact=True
    )
    assert_custody_transfer(transfer)
    assert "version" not in transfer and "updated_at" not in transfer
    assert transfer["transferred_at"]


def test_unknown_path_id_returns_not_found(api):
    """PRD §2.7: "3. **Path resolution** — path identifiers resolve
    left-to-right, parent before child; the first unresolvable segment yields
    `ERR_NOT_FOUND` (404). This applies to every endpoint with path
    parameters."

    Design: Corner/entities/unknown_path_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    create_voting_system()
    resp = api.get_voting_system(NON_EXISTENT_UUID, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    resp = api.create_official(
        NON_EXISTENT_UUID,
        create_official_payload(full_name="Ghost", badge_no="B900"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_officials_list_filters_by_jurisdiction(api):
    """PRD §4: "| GET | `/evote/officials` | List officials; optional filters
    `jurisdiction_id`, `status` | All roles |"
    PRD §2.3: "`offset` sets the number of items skipped and defaults to 0.
    Unless otherwise specified, list endpoints return resources sorted by
    `created_at` in ascending order. The `meta` object of a list response
    carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/officials_list_filters_by_jurisdiction
    """
    set_clock("2026-09-01T00:00:00Z")
    jur_a = create_jurisdiction(name="Alpha County", state_code="CA",
                                budget_total_cents=5_000_000)
    jur_b = create_jurisdiction(name="Beta County", state_code="NV",
                                budget_total_cents=5_000_000)
    create_official(jur_a["id"], full_name="A One")
    create_official(jur_a["id"], full_name="A Two")
    create_official(jur_b["id"], full_name="B One")

    rows, meta = validate_paginated(
        api.list_officials(AUDITOR, params={"jurisdiction_id": jur_a["id"]})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2, "total_count reflects the filtered set"
    assert meta["has_more"] is False
    assert all(row["jurisdiction_id"] == jur_a["id"] for row in rows)
