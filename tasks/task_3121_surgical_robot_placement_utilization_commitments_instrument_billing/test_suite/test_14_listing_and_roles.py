"""Listing, pagination and role surfacing."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_case,
    create_training_record,
    get_success_data,
    make_compliance_officer_headers,
    set_clock,
    setup_account_with_review,
    setup_commissioned_system,
    validate_error,
    validate_paginated,
)


def test_case_listing_honours_pagination_and_reports_the_filtered_total(api):
    """PRD §2.3: "`total_count` reflects the full size of the filtered result set rather than
    the size of the returned page, and `has_more` is true when further items remain beyond
    the returned page."

    Design: Corner/entities/procedure_cases_list_paginates_with_status_and_window_filters
    """
    ctx = setup_commissioned_system()
    for day, family in ((10, "UROLOGY"), (11, "GYNECOLOGY"), (12, "UROLOGY")):
        create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                    procedure_family=family,
                    case_started_at=f"2026-09-{day}T08:00:00Z")

    page, meta = validate_paginated(api_client.list_procedure_cases(
        TEST_USERS["compliance_officer_headers"],
        {"robot_system_id": ctx.system["id"], "limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rest, meta = validate_paginated(api_client.list_procedure_cases(
        TEST_USERS["compliance_officer_headers"],
        {"robot_system_id": ctx.system["id"], "limit": 2, "offset": 2}))
    assert len(rest) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_case_listing_narrows_the_total_by_status_and_instant_range(api):
    """PRD §2.3: "`total_count` reflects the full size of the filtered result set".
    PRD §3.4: "Cases are listable fleet-wide and per system, filterable by system, by
    account, by `case_status`, by a `case_started_from` and `case_started_to` instant range".

    Design: Corner/entities/procedure_cases_list_paginates_with_status_and_window_filters
    """
    ctx = setup_commissioned_system()
    for day, family in ((10, "UROLOGY"), (11, "GYNECOLOGY"), (12, "UROLOGY")):
        create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                    procedure_family=family,
                    case_started_at=f"2026-09-{day}T08:00:00Z")

    scheduled, meta = validate_paginated(api_client.list_procedure_cases(
        TEST_USERS["compliance_officer_headers"],
        {"robot_system_id": ctx.system["id"], "case_status": "SCHEDULED"}))
    assert meta["total_count"] == 3
    assert all(c["case_status"] == "SCHEDULED" for c in scheduled)

    windowed, meta = validate_paginated(api_client.list_procedure_cases(
        TEST_USERS["compliance_officer_headers"],
        {"robot_system_id": ctx.system["id"],
         "case_started_from": "2026-09-11T00:00:00Z",
         "case_started_to": "2026-09-12T00:00:00Z"}))
    assert meta["total_count"] == 1
    assert windowed[0]["procedure_family"] == "GYNECOLOGY"


def test_case_listing_walks_every_row_exactly_once_in_creation_order(api):
    """PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by
    `created_at` ascending."

    Design: Corner/endpoints/case_list_ordering_is_stable_by_case_started_at
    """
    ctx = setup_commissioned_system()
    first_created = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                                case_started_at="2026-09-12T08:00:00Z")
    second_created = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                                 case_started_at="2026-09-10T08:00:00Z")

    seen = []
    for offset in (0, 1):
        page, meta = validate_paginated(api_client.list_procedure_cases(
            ctx.account_headers,
            {"robot_system_id": ctx.system["id"], "limit": 1, "offset": offset}))
        assert len(page) == 1
        assert meta["total_count"] == 2
        seen.append(page[0]["id"])

    assert sorted(seen) == sorted([first_created["id"], second_created["id"]]), (
        "paging with limit=1 walks each row exactly once"
    )
    assert seen[0] == first_created["id"], (
        "the list is ordered by created_at ascending, so the first-created case leads"
    )


def test_an_engineer_cannot_publish_a_software_release(api):
    """PRD §2.1: "Immediately after it, the server verifies that the declared role is
    permitted to invoke the operation at all; a role that is not among an endpoint's
    authorized roles is rejected with `ERR_AGENT_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/engineer_cannot_publish_software_releases
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_account_with_review(verdict="PASSED")

    res = api_client.create_software_release(
        ctx.config["id"], {"release_index": 1, "feature_codes": ["FIREFLY"]},
        TEST_USERS["service_engineer_headers"])

    validate_error(res, "ERR_AGENT_NOT_PERMITTED", expected_status=403)


def test_the_platform_admin_publishes_the_release_the_engineer_could_not(api):
    """PRD §3.5: "A `PlatformAdmin` publishes a software release against a system
    configuration, naming a `release_index` — a monotonic ordinal within that configuration —
    and the `feature_codes` the release unlocks."

    Design: Corner/rbac/engineer_cannot_publish_software_releases
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_account_with_review(verdict="PASSED")

    release = get_success_data(api_client.create_software_release(
        ctx.config["id"], {"release_index": 1, "feature_codes": ["FIREFLY"]},
        TEST_USERS["platform_admin_headers"]), 201)

    assert release["release_index"] == 1
    catalog = get_success_data(api_client.list_configuration_releases(
        ctx.config["id"], TEST_USERS["service_engineer_headers"]), 200)
    assert len(catalog) == 1


def test_an_account_owner_cannot_verify_the_accounts_own_compliance_evidence(api):
    """PRD §2.1: "The identity that approved a proctor case at credentialing time, and the
    identity that decides an expansion review, must differ from the `hospital_owner_user_id`
    recorded on the owning account — that is, the user id stamped from `X-User-ID` when the
    account was created. An approver whose `X-User-ID` equals `hospital_owner_user_id` is
    rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/account_owner_cannot_verify_its_own_compliance_evidence
    """
    owner_user_id = "owner-greyrock"
    ctx = setup_account_with_review(verdict="PASSED", owner_user_id=owner_user_id,
                                    account_overrides={
                                        "account_name": "Greyrock Surgical",
                                        "idn_group_code": "IDN-GREYROCK",
                                        "region_code": "EAST", "placement_cap": 3,
                                        "maximum_procedure_commitment": 20})
    record = create_training_record(ctx.account["id"], simulation_modules_completed=4,
                                    required_proctored_cases=1)
    record = get_success_data(api_client.complete_simulation(
        record["id"],
        {"simulation_modules_completed": 4,
         "expected_training_record_version": record["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    record = get_success_data(api_client.begin_proctoring(
        record["id"],
        {"required_proctored_cases": 1,
         "expected_training_record_version": record["version"]},
        TEST_USERS["regional_sales_director_headers"]), 200)
    get_success_data(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "CREDENTIAL_LETTER", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2027-08-01T00:00:00Z"},
        ctx.account_headers), 201)
    logged = api_client.log_proctor_case(
        record["id"],
        {"case_observation_ref": "OBS-SOD", "occurred_at_utc": "2026-08-20T00:00:00Z"},
        TEST_USERS["clinical_operations_lead_headers"])
    record = get_success_data(logged, logged.status_code)
    import json
    case_id = json.loads(logged.text)["data"].get("proctor_case_id")
    assert case_id

    res = api_client.approve_proctor_case(
        case_id, {"expected_training_record_version": record["version"]},
        make_compliance_officer_headers(owner_user_id))

    validate_error(res, "ERR_SEGREGATION_OF_DUTIES_VIOLATION", expected_status=403)


def test_an_independent_compliance_officer_credentialed_the_same_record(api):
    """PRD §3.5: "Approval increments the completed count and, when the proctoring requirement
    is met, carries the record through to `CREDENTIALED`, stamping `credential_expires_utc` at
    the credential issue instant plus 365 days".

    Design: Corner/rbac/account_owner_cannot_verify_its_own_compliance_evidence
    """
    owner_user_id = "owner-greyrock"
    ctx = setup_account_with_review(verdict="PASSED", owner_user_id=owner_user_id)
    record = create_training_record(ctx.account["id"], simulation_modules_completed=4,
                                    required_proctored_cases=1)
    record = get_success_data(api_client.complete_simulation(
        record["id"],
        {"simulation_modules_completed": 4,
         "expected_training_record_version": record["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    record = get_success_data(api_client.begin_proctoring(
        record["id"],
        {"required_proctored_cases": 1,
         "expected_training_record_version": record["version"]},
        TEST_USERS["regional_sales_director_headers"]), 200)
    get_success_data(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "CREDENTIAL_LETTER", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2027-08-01T00:00:00Z"},
        ctx.account_headers), 201)
    logged = api_client.log_proctor_case(
        record["id"],
        {"case_observation_ref": "OBS-OK", "occurred_at_utc": "2026-08-20T00:00:00Z"},
        TEST_USERS["clinical_operations_lead_headers"])
    record = get_success_data(logged, logged.status_code)
    import json
    case_id = json.loads(logged.text)["data"].get("proctor_case_id")

    approved = get_success_data(api_client.approve_proctor_case(
        case_id, {"expected_training_record_version": record["version"]},
        TEST_USERS["compliance_officer_headers"]), 200)

    assert approved["training_status"] == "CREDENTIALED"
    assert approved["credential_expires_utc"] is not None


def test_a_surgeon_may_read_only_its_own_training_record(api):
    """PRD §2.1: "When `X-User-Role` is `Surgeon`, `X-User-ID` is the `id` of the acting
    `SurgeonTrainingRecord`; ownership checks on any resource that references a
    `SurgeonTrainingRecord` compare the resource's foreign-key field to `X-User-ID`. An
    entity-backed role that acts on a resource whose owning foreign key is not the acting
    identity is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/surgeon_reads_only_its_own_training_record
    """
    ctx = setup_account_with_review(verdict="PASSED")
    first = ctx.surgeon
    second = create_training_record(ctx.account["id"], surgeon_name="Dr. Second",
                                    simulation_modules_completed=0,
                                    required_proctored_cases=2)

    own = get_success_data(api_client.get_training_record(
        first["id"], TEST_USERS["surgeon_headers"].copy() | {"X-User-ID": first["id"]}), 200)
    assert own["id"] == first["id"]

    res = api_client.get_training_record(
        second["id"], TEST_USERS["surgeon_headers"].copy() | {"X-User-ID": first["id"]})
    validate_error(res, "ERR_OWNERSHIP_MISMATCH", expected_status=403)


def test_a_clinical_operations_lead_may_read_both_training_records(api):
    """PRD §2.1: "`ClinicalOperationsLead` is opaque. `HospitalProcurementOfficer` is opaque."

    Design: Corner/rbac/surgeon_reads_only_its_own_training_record
    """
    ctx = setup_account_with_review(verdict="PASSED")
    second = create_training_record(ctx.account["id"], surgeon_name="Dr. Second",
                                    simulation_modules_completed=0,
                                    required_proctored_cases=2)

    for record_id in (ctx.surgeon["id"], second["id"]):
        fetched = get_success_data(api_client.get_training_record(
            record_id, TEST_USERS["clinical_operations_lead_headers"]), 200)
        assert fetched["id"] == record_id


def test_the_anonymous_role_is_admitted_to_the_clock_and_nothing_else(api):
    """PRD §2.4: "`PlatformAdmin` may drive it, and the `Anonymous` role is admitted here as
    well so that fixtures can be established from an empty database."
    PRD §2.1: "a role that is not among an endpoint's authorized roles is rejected with
    `ERR_AGENT_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/anonymous_can_only_reach_the_logical_clock
    """
    set_clock("2026-09-02T00:00:00Z", headers=TEST_USERS["anonymous_headers"])

    res = api_client.create_account(
        {"account_name": "Anon Attempt", "idn_group_code": "IDN-ANON",
         "region_code": "WEST", "placement_cap": 1, "maximum_procedure_commitment": 1},
        TEST_USERS["anonymous_headers"])

    validate_error(res, "ERR_AGENT_NOT_PERMITTED", expected_status=403)