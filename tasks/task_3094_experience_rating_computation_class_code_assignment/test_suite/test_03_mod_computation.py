"""Experience modification computation, promulgation, and eligibility.

Covers the PRD's computation contract (section 3.5): expected losses, the
primary/excess split at the split point, promulgation preconditions, and the
eligibility threshold boundary.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_report_for_policy,
    create_sheet_for_employer,
    create_unit_stat_report_payload,
    make_carrier_data_reporter_headers,
    set_clock,
    setup_employer_with_validated_report,
    setup_rated_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]

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


def test_sheet_promulgation_locks_consumed_reports(api):
    """PRD section 3.5: "A successful promulgation locks every consumed
    report — each moves from `VALIDATED` to `LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/sheet_promulgation_locks_consumed_reports
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    assert sheet["status"] == "DRAFT"
    before = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert before["status"] == "VALIDATED"

    promulgated = validate_success(
        api.promulgate_experience_mod_sheet(sheet["id"], ANALYST), expected_status=200
    )
    assert promulgated["status"] == "PROMULGATED"
    after = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert after["status"] == "LOCKED", (
        f"Promulgation must lock consumed reports, got {after['status']}"
    )


def test_promulgate_sheet_with_submitted_reports_returns_unvalidated_reports(api):
    """PRD section 3.5: "every unit statistical report contributing to the
    sheet must be `VALIDATED` or `LOCKED`, with any still-`SUBMITTED` report
    surfacing `ERR_UNVALIDATED_REPORTS`"; PRD section 5:
    ERR_UNVALIDATED_REPORTS maps to HTTP 409.

    Design: Corner/validations/promulgate_sheet_with_submitted_reports_returns_unvalidated_reports
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report1 = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    # Second policy with a report left in SUBMITTED.
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    policy2 = validate_success(
        api.create_policy(
            {
                "employer_id": employer["id"],
                "carrier_id": carrier["id"],
                "policy_number": "WC-1002",
                "effective_date": "2025-01-01",
                "expiration_date": "2026-01-01",
                "class_codes": [
                    {"class_code": class_code["code"], "payroll_dollars": 500000}
                ],
            },
            reporter,
        ),
        expected_status=201,
    )
    report2 = validate_success(
        api.create_unit_stat_report(
            create_unit_stat_report_payload(
                policy_id=policy2["id"],
                payroll_lines=[
                    {"class_code": class_code["code"], "payroll_dollars": 500000}
                ],
                claim_lines=[
                    {
                        "claim_number": "C9",
                        "claim_type": "MEDICAL",
                        "incurred_cents": 0,
                        "paid_cents": 0,
                        "claim_status": "CLOSED",
                        "state_code": "TX",
                    }
                ],
            ),
            reporter,
        ),
        expected_status=201,
    )
    assert report2["status"] == "SUBMITTED"

    sheet = create_sheet_for_employer(employer["id"])
    resp = api.promulgate_experience_mod_sheet(sheet["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_UNVALIDATED_REPORTS, expected_status=409)
    after = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert after["status"] == "DRAFT", (
        f"Rejected promulgation must leave the sheet DRAFT, got {after['status']}"
    )

    # Once the outstanding report is validated, the same promulgation succeeds.
    validate_success(api.validate_unit_stat_report(report2["id"], ANALYST))
    sheet2 = create_sheet_for_employer(employer["id"])
    promulgated = validate_success(
        api.promulgate_experience_mod_sheet(sheet2["id"], ANALYST), expected_status=200
    )
    assert promulgated["status"] == "PROMULGATED"


def test_promulgation_locks_reports_blocks_corrections_path_mutation(api):
    """PRD section 3.5: "A successful promulgation locks every consumed
    report — each moves from `VALIDATED` to `LOCKED`." PRD section 3.3: "Reports
    locked into a promulgated sheet are otherwise immutable: a report moves
    from `VALIDATED` to `LOCKED` automatically when the policy's experience
    modification sheet is promulgated."

    Design: Difficulty/cross_entity_state_dependency/sheet_promulgation_locks_consumed_reports
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    # The policy back-reference is set at validation time, before promulgation.
    policy_mid = validate_success(api.get_policy(policy["id"], ADMIN))
    assert policy_mid["unit_stat_report_id"] == report["id"]

    sheet = create_sheet_for_employer(employer["id"])
    validate_success(
        api.promulgate_experience_mod_sheet(sheet["id"], ANALYST), expected_status=200
    )
    locked = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert locked["status"] == "LOCKED"
    # LOCKED is sticky: a fresh direct transition attempt is rejected.
    resp = api.validate_unit_stat_report(report["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_claim_exactly_at_split_point_is_all_primary(api):
    """PRD section 3.5: "For each claim line, the primary portion is the
    lesser of the claim's `incurred_cents` and the bureau's
    `split_point_cents`; the excess portion is the remainder. Summing the
    primary portions across all claims yields `actual_primary_cents`; summing
    the remainders yields `actual_excess_cents`."

    Design: Difficulty/boundary_precision_check/claim_exactly_at_split_point_is_all_primary
    """
    set_clock("2026-06-01T00:00:00Z")
    claims = [
        {
            "claim_number": "K1",
            "claim_type": "INDEMNITY",
            "incurred_cents": 1000000,  # exactly the split point
            "paid_cents": 1000000,
            "claim_status": "CLOSED",
            "state_code": "TX",
        },
        {
            "claim_number": "K2",
            "claim_type": "INDEMNITY",
            "incurred_cents": 1000001,  # one cent over the split point
            "paid_cents": 1000001,
            "claim_status": "CLOSED",
            "state_code": "TX",
        },
    ]
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=500000,
            claim_lines=claims,
            employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"},
            policy_number="WC-3001",
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    # min() is inclusive: 1,000,000 + 1,000,000 primary; 0 + 1 excess.
    assert sheet["actual_primary_cents"] == 2000000, (
        f"Expected actual_primary_cents 2000000, got {sheet['actual_primary_cents']}"
    )
    assert sheet["actual_excess_cents"] == 1, (
        f"Expected actual_excess_cents 1, got {sheet['actual_excess_cents']}"
    )


def test_claim_below_split_point_contributes_no_excess(api):
    """PRD section 3.5: "For each claim line, the primary portion is the
    lesser of the claim's `incurred_cents` and the bureau's
    `split_point_cents`; the excess portion is the remainder."

    Design: Difficulty/boundary_precision_check/claim_exactly_at_split_point_is_all_primary
    """
    set_clock("2026-06-01T00:00:00Z")
    claims = [
        {
            "claim_number": "L1",
            "claim_type": "INDEMNITY",
            "incurred_cents": 999999,  # one cent below the split point
            "paid_cents": 999999,
            "claim_status": "CLOSED",
            "state_code": "TX",
        }
    ]
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=500000,
            claim_lines=claims,
            employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"},
            policy_number="WC-3001",
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    # min(999999, 1000000) = 999999 primary; remainder 0 excess.
    assert sheet["actual_primary_cents"] == 999999, (
        f"Expected actual_primary_cents 999999, got {sheet['actual_primary_cents']}"
    )
    assert sheet["actual_excess_cents"] == 0, (
        f"Expected actual_excess_cents 0, got {sheet['actual_excess_cents']}"
    )


def test_expected_losses_at_threshold_computed_mod_below_threshold_unity(api):
    """PRD section 3.5: "eligibility is then enforced — when the employer's total
    `expected_losses_cents` are at least the bureau's
    `eligibility_threshold_cents` the computed `mod_factor` stands, but below
    that threshold the factor is fixed at exactly 1.00 (unity) and the sheet
    still promulgates with that value"

    Design: Difficulty/boundary_precision_check/expected_losses_exactly_at_threshold_is_eligible_one_cent_below_is_unity
    """
    set_clock("2026-06-01T00:00:00Z")
    one_claim_100k = [
        {
            "claim_number": "X1",
            "claim_type": "INDEMNITY",
            "incurred_cents": 100000,
            "paid_cents": 100000,
            "claim_status": "CLOSED",
            "state_code": "TX",
        }
    ]
    # Employer X: payroll 333,333 dollars at ELR 150 -> expected losses exactly
    # 500,000 cents == eligibility threshold (at least -> eligible).
    _b, _c, employer_x, _cc, _t, _p, _r = setup_employer_with_validated_report(
        payroll_dollars=333333,
        claim_lines=one_claim_100k,
        employer_overrides={"fein": "75-1000010", "legal_name": "Employer Exact"},
        policy_number="WC-X1",
    )
    # Employer Y: payroll 300,000 dollars at ELR 150 -> expected losses
    # 450,000 cents < threshold (ineligible -> unity).
    _b2, _c2, employer_y, _cc2, _t2, _p2, _r2 = setup_employer_with_validated_report(
        payroll_dollars=300000,
        claim_lines=one_claim_100k,
        employer_overrides={"fein": "75-1000011", "legal_name": "Employer Below"},
        policy_number="WC-Y1",
    )

    sheet_x = create_sheet_for_employer(employer_x["id"])
    assert sheet_x["expected_losses_cents"] == 500000, (
        f"Expected 500000, got {sheet_x['expected_losses_cents']}"
    )
    promulgated_x = validate_success(
        api.promulgate_experience_mod_sheet(sheet_x["id"], ANALYST), expected_status=200
    )
    assert promulgated_x["status"] == "PROMULGATED"
    assert promulgated_x["mod_factor"] != "1.00", (
        "An employer at the eligibility threshold must be rated with the "
        f"computed factor, got unity {promulgated_x['mod_factor']}"
    )

    sheet_y = create_sheet_for_employer(employer_y["id"])
    assert sheet_y["expected_losses_cents"] == 450000, (
        f"Expected 450000, got {sheet_y['expected_losses_cents']}"
    )
    promulgated_y = validate_success(
        api.promulgate_experience_mod_sheet(sheet_y["id"], ANALYST), expected_status=200
    )
    assert promulgated_y["status"] == "PROMULGATED"
    assert promulgated_y["mod_factor"] == "1.00", (
        f"An ineligible employer must promulgate at unity 1.00, got "
        f"{promulgated_y['mod_factor']}"
    )


def test_well_below_threshold_employer_promulgates_at_unity(api):
    """PRD section 3.5: "eligibility is then enforced — when the employer's total
    `expected_losses_cents` are at least the bureau's
    `eligibility_threshold_cents` the computed `mod_factor` stands, but below
    that threshold the factor is fixed at exactly 1.00 (unity) and the sheet
    still promulgates with that value"

    Design: Difficulty/boundary_precision_check/expected_losses_exactly_at_threshold_is_eligible_one_cent_below_is_unity
    """
    set_clock("2026-06-01T00:00:00Z")
    # Payroll 10,000 dollars at ELR 150 -> expected losses 15,000 cents, far
    # below the 500,000-cent eligibility threshold.
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=10000,
            employer_overrides={"fein": "75-1000012", "legal_name": "Employer Small"},
            policy_number="WC-S1",
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    assert sheet["expected_losses_cents"] == 15000, (
        f"Expected 15000, got {sheet['expected_losses_cents']}"
    )
    promulgated = validate_success(
        api.promulgate_experience_mod_sheet(sheet["id"], ANALYST), expected_status=200
    )
    assert promulgated["status"] == "PROMULGATED"
    assert promulgated["mod_factor"] == "1.00", (
        f"An ineligible employer must promulgate at unity 1.00, got "
        f"{promulgated['mod_factor']}"
    )


def test_class_code_without_rating_entry_returns_class_code_not_rated(api):
    """PRD section 3.5: "A payroll line whose class code has no entry in the
    in-force table is excluded from the sum, and the sheet computation fails
    outright with `ERR_CLASS_CODE_NOT_RATED`."; PRD section 5:
    ERR_CLASS_CODE_NOT_RATED maps to HTTP 409.

    Design: Corner/errors/class_code_without_rating_entry_returns_class_code_not_rated
    """
    from test_helpers import (
        create_bureau,
        create_carrier,
        create_class_code,
        create_employer,
        create_and_promulgate_rating_table,
        create_rating_table,
        create_policy_payload,
    )

    set_clock("2026-06-01T00:00:00Z")
    create_bureau()
    carrier = create_carrier()
    employer = create_employer()
    create_class_code()  # 3632, rated in both tables below
    create_class_code(code="9999", description="Experimental Class")

    # Policy is issued under table 1, which rates both 3632 and 9999, so
    # issuance succeeds per section 3.2.
    table_1 = create_and_promulgate_rating_table(
        effective_date="2024-01-01",
        values=[
            {
                "class_code": "3632",
                "rate_per_100_payroll_cents": 250,
                "elr_per_100_payroll_cents": 150,
                "d_ratio_bp": 4000,
            },
            {
                "class_code": "9999",
                "rate_per_100_payroll_cents": 100,
                "elr_per_100_payroll_cents": 100,
                "d_ratio_bp": 4000,
            },
        ],
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    policy = validate_success(
        api.create_policy(
            create_policy_payload(
                employer_id=employer["id"],
                carrier_id=carrier["id"],
                policy_number="WC-9009",
                class_codes=[{"class_code": "9999", "payroll_dollars": 100000}],
            ),
            reporter,
        ),
        expected_status=201,
    )
    # The report's payroll line uses class code 9999; the claim's state matches
    # so validation itself succeeds.
    report = validate_success(
        api.create_unit_stat_report(
            create_unit_stat_report_payload(
                policy_id=policy["id"],
                payroll_lines=[{"class_code": "9999", "payroll_dollars": 100000}],
            ),
            reporter,
        ),
        expected_status=201,
    )
    validate_success(api.validate_unit_stat_report(report["id"], ANALYST))

    # Table 2 (in force at the sheet's rating effective date) no longer rates
    # 9999, so the sheet computation fails outright per section 3.5.
    table_2 = create_rating_table(effective_date="2026-01-01")
    validate_success(api.promulgate_rating_table(table_2["id"], ADMIN), expected_status=200)

    employer_now = validate_success(api.get_employer(employer["id"], ADMIN))
    resp = api.create_experience_mod_sheet(
        {
            "employer_id": employer["id"],
            "rating_effective_date": "2026-01-01",
            "expected_employer_version": employer_now["version"],
        },
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_CLASS_CODE_NOT_RATED, expected_status=409)
