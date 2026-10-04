"""Concurrency control, validation precedence, authorization, and ownership.

Covers the PRD's optimistic concurrency contract (section 2.6), validation
precedence (section 2.7), role-based access control (section 2.1), temporal
rules (sections 3.2/3.4), rating table supersession (section 3.2), and
ownership-change combinability (section 3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_promulgate_rating_table,
    create_class_code,
    create_employer,
    create_policy_payload,
    create_rating_table,
    create_report_for_policy,
    create_sheet_for_employer,
    get_employer,
    make_carrier_data_reporter_headers,
    make_employer_representative_headers,
    set_clock,
    setup_bureau_carrier_employer,
    setup_employer_with_validated_report,
    setup_rated_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]
POOL_ADMIN = TEST_USERS["pool_administrator_headers"]

_BASE_CLAIMS = [
    {
        "claim_number": "C1",
        "claim_type": "INDEMNITY",
        "incurred_cents": 1600000,
        "paid_cents": 1600000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
    {
        "claim_number": "C2",
        "claim_type": "INDEMNITY",
        "incurred_cents": 2400000,
        "paid_cents": 2400000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
]


def test_mod_sheet_create_rejects_stale_employer_version(api):
    """PRD section 2.6: "When a bureau analyst creates an experience
    modification sheet for an employer, the request must include
    `expected_employer_version` carrying the employer's `version` as last
    observed by the client; if the employer's current `version` differs -
    because another writer has advanced it since the client last read it -
    the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/mod_sheet_create_rejects_stale_employer_version
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    # Stale view: the version observed before the first sheet was created.
    stale_version = employer["version"]
    sheet_1 = create_sheet_for_employer(employer["id"])
    assert sheet_1["status"] == "DRAFT"

    resp = api.create_experience_mod_sheet(
        {
            "employer_id": employer["id"],
            "rating_effective_date": "2027-01-01",
            "expected_employer_version": stale_version,
        },
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    sheets, meta = validate_paginated(
        api.list_employer_experience_mod_sheets(employer["id"], ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"Stale create must not persist a sheet, got total_count {meta['total_count']}"
    )


def test_takeout_create_rejects_stale_enrollment_version(api):
    """PRD section 2.6: "When a voluntary carrier representative files a
    take-out request against an assigned risk enrollment, the request must
    include `expected_enrollment_version` carrying the enrollment's `version`
    as last observed by the client; a mismatch with the enrollment's current
    `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/takeout_create_rejects_stale_enrollment_version
    """
    from test_helpers import (
        create_bureau,
        create_carrier,
        create_assigned_risk_enrollment_payload,
        make_voluntary_carrier_representative_headers,
    )

    set_clock("2026-07-01T00:00:00Z")
    create_bureau()
    pool_carrier = create_carrier(
        naic_number="10002", legal_name="Pool Carrier One", assigned_risk_quota_cents=10000000
    )
    voluntary_carrier = create_carrier(
        naic_number="10003", legal_name="Voluntary Carrier Two", assigned_risk_quota_cents=1000000
    )
    employer = create_employer(fein="75-1000003", legal_name="Capitol Fasteners")
    enrollment = validate_success(
        api.create_assigned_risk_enrollment(
            create_assigned_risk_enrollment_payload(employer_id=employer["id"]),
            POOL_ADMIN,
        ),
        expected_status=201,
    )
    stale_version = enrollment["version"]  # version observed before assign
    assigned = validate_success(
        api.assign_assigned_risk_enrollment(
            enrollment["id"], {"carrier_id": pool_carrier["id"]}, POOL_ADMIN
        )
    )
    assert assigned["version"] != stale_version, (
        "Setup failed: assign must advance the enrollment version"
    )

    resp = api.create_assigned_risk_take_out(
        {
            "enrollment_id": enrollment["id"],
            "voluntary_carrier_id": voluntary_carrier["id"],
            "exit_date": "2026-07-01",
            "expected_enrollment_version": stale_version,
        },
        make_voluntary_carrier_representative_headers(voluntary_carrier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_assigned_risk_enrollment(enrollment["id"], ADMIN))
    assert after["status"] == "ACTIVE"


def test_policy_create_with_bad_dates_yields_temporal_conflict(api):
    """PRD section 3.2: "The effective date must precede the expiration date,
    or the request is rejected with `ERR_TEMPORAL_CONFLICT`." PRD section 2.7:
    "Temporal rules - date ranges and overlapping effective dates
    (`ERR_TEMPORAL_CONFLICT`) - are evaluated after state checks. Referential
    rules come next"; PRD section 5: ERR_TEMPORAL_CONFLICT maps to HTTP 409.

    Design: Difficulty/priority_pair_validation_conflict/policy_create_with_inactive_class_code_and_bad_dates_yields_temporal_conflict
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer = setup_bureau_carrier_employer(
        employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"}
    )
    # Class code 3632 exists but is deliberately not rated (referential rule
    # would fail too); the reversed dates violate the temporal rule, which the
    # PRD's precedence evaluates first.
    create_class_code()
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    resp = api.create_policy(
        create_policy_payload(
            employer_id=employer["id"],
            carrier_id=carrier["id"],
            policy_number="WC-BAD1",
            effective_date="2027-02-01",
            expiration_date="2026-02-01",
            class_codes=[{"class_code": "3632", "payroll_dollars": 100000}],
        ),
        reporter,
    )
    error = validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT, expected_status=409)
    assert error["error_id"] not in (
        ApiErrorId.ERR_CLASS_CODE_INACTIVE,
        ApiErrorId.ERR_CLASS_CODE_NOT_RATED,
    )


def test_superseding_rating_table_closes_prior_table_interval(api):
    """PRD section 3.2: "Promulgation moves the table to `PROMULGATED` and
    simultaneously moves any prior promulgated table for the same state to
    `SUPERSEDED`, stamping that table's `superseded_at`; only one promulgated
    table is in force for a state at a time, and lookups always resolve
    against the table in force at the relevant date."

    Design: Difficulty/resource_temporal_overlap/superseding_rating_table_closes_prior_table_interval
    """
    set_clock("2026-08-01T00:00:00Z")
    bureau, carrier, employer = setup_bureau_carrier_employer(
        employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"}
    )
    class_code = create_class_code()
    table_1 = create_and_promulgate_rating_table(effective_date="2026-01-01")
    table_2 = create_rating_table(
        effective_date="2026-07-01",
        values=[
            {
                "class_code": "3632",
                "rate_per_100_payroll_cents": 300,
                "elr_per_100_payroll_cents": 150,
                "d_ratio_bp": 4000,
            }
        ],
    )
    promulgated_2 = validate_success(
        api.promulgate_rating_table(table_2["id"], ADMIN), expected_status=200
    )
    assert promulgated_2["status"] == "PROMULGATED"
    table_1_after = validate_success(api.get_rating_table(table_1["id"], ADMIN))
    assert table_1_after["status"] == "SUPERSEDED", (
        f"Prior table must be superseded, got {table_1_after['status']}"
    )
    assert table_1_after.get("superseded_at"), "superseded_at must be stamped"

    reporter = make_carrier_data_reporter_headers(carrier["id"])
    policy_jun = validate_success(
        api.create_policy(
            create_policy_payload(
                employer_id=employer["id"],
                carrier_id=carrier["id"],
                policy_number="WC-JUN",
                effective_date="2026-06-01",
                expiration_date="2027-06-01",
                class_codes=[{"class_code": "3632", "payroll_dollars": 100000}],
            ),
            reporter,
        ),
        expected_status=201,
    )
    # June policy resolves against the table in force at 2026-06-01 (rate 250).
    assert policy_jun["manual_premium_cents"] == 250000, (
        f"Expected 250000 from the old table, got {policy_jun['manual_premium_cents']}"
    )
    policy_aug = validate_success(
        api.create_policy(
            create_policy_payload(
                employer_id=employer["id"],
                carrier_id=carrier["id"],
                policy_number="WC-AUG",
                effective_date="2026-08-01",
                expiration_date="2027-08-01",
                class_codes=[{"class_code": "3632", "payroll_dollars": 100000}],
            ),
            reporter,
        ),
        expected_status=201,
    )
    # August policy resolves against the new table (rate 300).
    assert policy_aug["manual_premium_cents"] == 300000, (
        f"Expected 300000 from the new table, got {policy_aug['manual_premium_cents']}"
    )


def test_overlapping_class_assignment_effective_dates_rejected(api):
    """PRD section 3.4: "No two assignments for the same employer may hold
    `ASSIGNED` or `CONFIRMED` status with overlapping effective dates; an
    overlapping proposal is rejected with `ERR_CLASS_ASSIGNMENT_OVERLAP`";
    PRD section 5: ERR_CLASS_ASSIGNMENT_OVERLAP maps to HTTP 409.

    Design: Difficulty/resource_temporal_overlap/overlapping_class_assignment_effective_dates_rejected
    """
    from test_helpers import create_bureau, create_class_assignment_payload

    set_clock("2026-01-01T00:00:00Z")
    create_bureau()
    employer = create_employer()
    cc_3632 = create_class_code()
    cc_8810 = create_class_code(code="8810", description="Clerical Office Employees")

    assignment_1 = validate_success(
        api.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"],
                class_code_id=cc_3632["id"],
                effective_date="2026-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    validate_success(api.assign_class_assignment(assignment_1["id"], ANALYST))

    assignment_2 = validate_success(
        api.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"],
                class_code_id=cc_8810["id"],
                effective_date="2026-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    resp = api.assign_class_assignment(assignment_2["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_CLASS_ASSIGNMENT_OVERLAP, expected_status=409)
    after = validate_success(api.get_class_assignment(assignment_2["id"], ADMIN))
    assert after["status"] == "PENDING_INSPECTION", (
        f"Rejected assignment must remain PENDING_INSPECTION, got {after['status']}"
    )


def test_employer_representative_cannot_validate_unit_stat_report(api):
    """PRD section 2.1: "When the headers are well-formed but the declared
    role is not authorized for the requested endpoint, the request is rejected
    with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."; PRD section 4: validating a
    unit statistical report is authorized for BureauAnalyst only.

    Design: Corner/rbac/employer_representative_cannot_validate_unit_stat_report
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=100000
    )
    report = create_report_for_policy(policy, carrier, payroll_dollars=100000, validate=False)
    assert report["status"] == "SUBMITTED"

    resp = api.validate_unit_stat_report(
        report["id"], make_employer_representative_headers(employer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
    after = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert after["status"] == "SUBMITTED", (
        f"Forbidden validation must not mutate the report, got {after['status']}"
    )


def test_employers_policies_subresource_lists_children(api):
    """PRD section 4: | GET | `/employers/{employerId}/policies` | List
    policies for an employer | Any |. PRD section 2.3: "Paginated list
    responses include the
    fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the response envelope."

    Design: Corner/endpoints/employers_policies_subresource_lists_children
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=100000
    )
    other_employer = create_employer(
        fein="75-1000002", legal_name="Brazos Fabrication", state_code="TX"
    )

    data_a, meta_a = validate_paginated(
        api.list_employer_policies(employer["id"], ADMIN)
    )
    assert meta_a["total_count"] == 1
    assert len(data_a) == 1
    assert data_a[0]["id"] == policy["id"]
    assert data_a[0]["employer_id"] == employer["id"]

    data_b, meta_b = validate_paginated(
        api.list_employer_policies(other_employer["id"], ADMIN)
    )
    assert meta_b["total_count"] == 0
    assert data_b == []
    assert meta_b["has_more"] is False


def test_ownership_change_combines_employers_and_produces_group_mod(api):
    """PRD section 3.8: "A successful combination creates a
    `CombinabilityGroup` in `ACTIVE` status whose `member_employer_ids` list
    the change's employer together with the related employers supplied as
    `member_employer_ids`, records the originating change on the group's
    `created_from_change_id`, stamps the change's `combinability_group_id`,
    and creates a combined `ExperienceModSheet` in `DRAFT` for the group,
    recorded on the group's `combined_mod_sheet_id`."

    Design: Corner/cross_cutting/ownership_change_combines_employers_and_produces_group_mod
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer_a, class_code, table, policy_a, report_a = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    # Employer B with its own validated report (payroll 500,000; claim 400,000).
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    employer_b = create_employer(fein="75-1000002", legal_name="Brazos Fabrication")
    policy_b = validate_success(
        api.create_policy(
            create_policy_payload(
                employer_id=employer_b["id"],
                carrier_id=carrier["id"],
                policy_number="WC-3001",
                class_codes=[{"class_code": "3632", "payroll_dollars": 500000}],
            ),
            reporter,
        ),
        expected_status=201,
    )
    create_report_for_policy(
        policy_b,
        carrier,
        payroll_dollars=500000,
        claim_lines=[
            {
                "claim_number": "K1",
                "claim_type": "INDEMNITY",
                "incurred_cents": 400000,
                "paid_cents": 400000,
                "claim_status": "CLOSED",
                "state_code": "TX",
            }
        ],
    )

    change = validate_success(
        api.create_ownership_change(
            {
                "employer_id": employer_a["id"],
                "change_type": "MERGER",
                "effective_date": "2026-06-01",
            },
            ANALYST,
        ),
        expected_status=201,
    )
    combined = validate_success(
        api.combine_ownership_change(
            change["id"],
            {"member_employer_ids": [employer_a["id"], employer_b["id"]]},
            ANALYST,
        ),
        expected_status=200,
    )
    assert combined["status"] == "COMBINED"
    assert combined.get("combinability_group_id"), (
        "Combination must stamp the group id on the change"
    )

    group = validate_success(
        api.get_combinability_group(combined["combinability_group_id"], ADMIN)
    )
    assert group["status"] == "ACTIVE"
    assert set(group["member_employer_ids"]) == {employer_a["id"], employer_b["id"]}
    assert group["created_from_change_id"] == change["id"]

    combined_sheet = validate_success(
        api.get_experience_mod_sheet(group["combined_mod_sheet_id"], ADMIN)
    )
    assert combined_sheet["status"] == "DRAFT"
    # Combined experience: expected losses 2,000,000*150/100 + 500,000*150/100.
    assert combined_sheet["expected_losses_cents"] == 3750000, (
        f"Expected combined expected_losses_cents 3750000, got "
        f"{combined_sheet['expected_losses_cents']}"
    )
    # Combined actual losses: min per claim at the 1,000,000 split point.
    # 1,000,000 + 1,000,000 + 400,000 primary; 600,000 + 1,400,000 + 0 excess.
    assert combined_sheet["actual_primary_cents"] == 2400000, (
        f"Expected combined actual_primary_cents 2400000, got "
        f"{combined_sheet['actual_primary_cents']}"
    )
    assert combined_sheet["actual_excess_cents"] == 2000000, (
        f"Expected combined actual_excess_cents 2000000, got "
        f"{combined_sheet['actual_excess_cents']}"
    )


def test_policy_create_with_valid_dates_and_rated_class_accepted(api):
    """PRD section 3.2: "The effective date must precede the expiration date,
    or the request is rejected with `ERR_TEMPORAL_CONFLICT`." PRD section 4:
    creating a policy responds with HTTP 201.

    Design: Difficulty/priority_pair_validation_conflict/policy_create_with_inactive_class_code_and_bad_dates_yields_temporal_conflict
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer, class_code, table, _policy = setup_rated_policy(
        payroll_dollars=100000, policy_number="WC-BASE"
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    resp = api.create_policy(
        create_policy_payload(
            employer_id=employer["id"],
            carrier_id=carrier["id"],
            policy_number="WC-OK1",
            effective_date="2026-02-01",
            expiration_date="2027-02-01",
            class_codes=[{"class_code": class_code["code"], "payroll_dollars": 100000}],
        ),
        reporter,
    )
    policy = validate_success(resp, expected_status=201)
    assert policy["effective_date"] < policy["expiration_date"]
    assert policy["status"] == "ACTIVE"


def test_superseded_at_stamped_and_single_promulgated_table_per_state(api):
    """PRD section 3.2: "Promulgation moves the table to `PROMULGATED` and
    simultaneously moves any prior promulgated table for the same state to
    `SUPERSEDED`, stamping that table's `superseded_at`; only one promulgated
    table is in force for a state at a time, and lookups always resolve
    against the table in force at the relevant date."

    Design: Difficulty/resource_temporal_overlap/superseding_rating_table_closes_prior_table_interval
    """
    set_clock("2026-08-01T00:00:00Z")
    bureau, carrier, employer = setup_bureau_carrier_employer()
    create_class_code()
    table_1 = create_and_promulgate_rating_table(effective_date="2026-01-01")
    table_2 = create_rating_table(effective_date="2026-07-01")
    validate_success(api.promulgate_rating_table(table_2["id"], ADMIN))

    table_1_after = validate_success(api.get_rating_table(table_1["id"], ADMIN))
    assert table_1_after["status"] == "SUPERSEDED"
    superseded_at = table_1_after.get("superseded_at")
    assert superseded_at, "superseded_at must be stamped on the superseded table"

    table_2_after = validate_success(api.get_rating_table(table_2["id"], ADMIN))
    assert table_2_after["status"] == "PROMULGATED"
    assert table_2_after.get("superseded_at") in (None, ""), (
        "The table currently in force must not be stamped superseded"
    )


def test_non_overlapping_class_assignment_dates_accepted(api):
    """PRD section 3.4: "No two assignments for the same employer may hold
    `ASSIGNED` or `CONFIRMED` status with overlapping effective dates; an
    overlapping proposal is rejected with `ERR_CLASS_ASSIGNMENT_OVERLAP`, and
    any malformed date range surfaces `ERR_TEMPORAL_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlapping_class_assignment_effective_dates_rejected
    """
    from test_helpers import create_bureau, create_class_assignment_payload

    set_clock("2026-01-01T00:00:00Z")
    create_bureau()
    employer = create_employer()
    cc_3632 = create_class_code()
    cc_8810 = create_class_code(code="8810", description="Clerical Office Employees")

    assignment_1 = validate_success(
        api.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"],
                class_code_id=cc_3632["id"],
                effective_date="2026-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    validate_success(api.assign_class_assignment(assignment_1["id"], ANALYST))

    # A second assignment with a different, later effective date does not
    # overlap the first and may itself be assigned.
    assignment_2 = validate_success(
        api.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"],
                class_code_id=cc_8810["id"],
                effective_date="2027-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assigned_2 = validate_success(
        api.assign_class_assignment(assignment_2["id"], ANALYST), expected_status=200
    )
    assert assigned_2["status"] == "ASSIGNED"
