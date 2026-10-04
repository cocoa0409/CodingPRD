"""Entity surfaces, request shape and existence ordering."""
from test_helpers import (
    ERR_BORROWER_NOT_FOUND,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_COSIGNER_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SCHOOL_NOT_FOUND,
    NON_EXISTENT_UUID,
    TEST_USERS,
    approve,
    assert_accrual_entry,
    assert_borrower,
    assert_loan,
    assert_policy,
    assert_school,
    build_origination,
    create_accrual_entry,
    create_borrower,
    create_policy,
    create_school,
    create_application_payload,
    file_and_certify,
    file_certification,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_accrual_entries,
    list_borrowers,
    list_schools,
    make_borrower_headers,
    record_enrollment,
    schedule_and_release,
    setup_certified_loan,
    setup_loan_in_repayment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as client


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

def test_borrower_creation_returns_every_declared_field_and_starts_active(api):
    """PRD §3.1: "A `PlatformAdmin` registers a student borrower, supplying the
    borrower's `full_name`, a unique login and notification `email`, a two-letter
    `state_code`, and a `program_level`"
    PRD §3.1: "On creation the borrower receives a `status` of `ACTIVE`... Both start
    at 0."

    Design: Corner/entities/borrower_creation_returns_every_declared_field_and_starts_active
    """
    response = client.create_borrower(
        {"full_name": "Nora Borrower", "email": "nora@example.com", "state_code": "OH",
         "program_level": "GRADUATE", "credit_score": 720, "dti_ratio": 0.26},
        TEST_USERS["admin_headers"],
    )
    borrower = validate_success(response, expected_status=201)
    borrower_id = borrower["id"]

    read_back = validate_success(
        client.get_borrower(borrower_id, TEST_USERS["admin_headers"])
    )
    assert read_back["full_name"] == "Nora Borrower"
    assert read_back["program_level"] == "GRADUATE"
    assert read_back["status"] == "ACTIVE"
    assert read_back["version"] == 1
    assert read_back["on_time_payment_run_count"] == 0
    assert read_back["lifetime_on_time_payment_count"] == 0
    assert read_back["id"] is not None
    assert read_back["created_at"] is not None
    assert read_back["updated_at"] is not None
    assert_borrower(read_back)


def test_borrower_retrieval_round_trips_every_stored_field(api):
    """PRD §3.1: "The registration also captures the borrower's own credit figures,
    the `credit_score` and the debt-to-income `dti_ratio` that the combined
    underwriting will later consume."

    Design: Corner/entities/borrower_retrieval_round_trips_every_stored_field
    """
    borrower = create_borrower(
        full_name="Nora Borrower", email="nora2@example.com", state_code="OH",
        program_level="GRADUATE", credit_score=720, dti_ratio=0.26,
    )
    read = validate_success(
        client.get_borrower(borrower["id"], make_borrower_headers(borrower["id"]))
    )
    assert read["email"] == "nora2@example.com"
    assert read["state_code"] == "OH"
    assert read["credit_score"] == 720
    assert read["dti_ratio"] == 0.26
    assert read["program_level"] == "GRADUATE"


def test_borrower_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`total_count` reflects the total number of matching records
    irrespective of the page window, and `has_more` indicates whether further pages
    exist."

    Design: Corner/entities/borrower_listing_paginates_and_reports_total_count_and_has_more
    """
    for index in range(3):
        create_borrower(full_name=f"P{index}", email=f"page{index}@example.com")
    baseline = validate_paginated(
        client.list_borrowers(TEST_USERS["admin_headers"])
    )[1]["total_count"]
    first_page = client.list_borrowers(TEST_USERS["admin_headers"], params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == baseline
    assert meta["has_more"] is True
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta

    second_page = client.list_borrowers(
        TEST_USERS["admin_headers"], params={"limit": 2, "offset": baseline - 1}
    )
    tail, tail_meta = validate_paginated(second_page)
    assert len(tail) == 1
    assert tail_meta["has_more"] is False


def test_unknown_borrower_id_returns_not_found(api):
    """PRD §2.9: "The existence failures each carry their own identifier and an HTTP
    404 status. An unresolved borrower yields `ERR_BORROWER_NOT_FOUND`"

    Design: Corner/entities/unknown_borrower_id_returns_not_found
    """
    response = client.get_borrower(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    error = validate_error(response, ERR_BORROWER_NOT_FOUND)
    assert error["message"]


def test_school_creation_without_a_school_code_is_rejected(api):
    """PRD §2.12: "a missing required body field or an enum-valued field carrying a
    value outside its declared set yields `ERR_INVALID_REQUEST`"

    Design: Corner/entities/school_creation_without_school_code_is_rejected
    """
    baseline = validate_paginated(client.list_schools(TEST_USERS["admin_headers"]))[1][
        "total_count"
    ]
    response = client.create_school(
        {"name": "Nameless College", "state_code": "OH",
         "certification_capacity_per_period_cents": 1000},
        TEST_USERS["admin_headers"],
    )
    validate_error(response, ERR_INVALID_REQUEST)

    created = validate_success(
        client.create_school(
            {"name": "Nameless College", "school_code": "009999", "state_code": "OH",
             "certification_capacity_per_period_cents": 1000},
            TEST_USERS["admin_headers"],
        ),
        expected_status=201,
    )
    assert is_valid_uuid(created["id"])
    _, meta = validate_paginated(client.list_schools(TEST_USERS["admin_headers"]))
    assert meta["total_count"] == baseline + 1, "only the valid registration persisted"


def test_school_and_policy_defaults_apply_when_omitted(api):
    """PRD §3.1: "together with an `active` flag that defaults to true and marks
    whether the institution is currently an eligible lender-partner school"
    PRD §3.1: "the `delinquency_notice_threshold_days` (defaulting to 5); and the
    `allows_standalone_borrower` flag (defaulting to false)."

    Design: Corner/entities/school_and_policy_defaults_apply_when_omitted
    """
    school = validate_success(
        client.create_school(
            {"name": "Default College", "school_code": "009998", "state_code": "OH",
             "certification_capacity_per_period_cents": 5000},
            TEST_USERS["admin_headers"],
        ),
        expected_status=201,
    )
    assert school["active"] is True

    policy = validate_success(
        client.create_policy(
            {"product_code": "SM-DEF-2026", "program_level": "UNDERGRADUATE"},
            TEST_USERS["admin_headers"],
        ),
        expected_status=201,
    )
    stored = validate_success(client.get_policy(policy["id"], TEST_USERS["admin_headers"]))
    assert stored["cosigner_release_min_on_time_payments"] == 24
    assert stored["cosigner_release_min_credit_score"] == 660
    assert stored["cosigner_release_max_dti_ratio"] == 0.45
    assert stored["capitalized_interest_cap_pct"] == 0.10
    assert stored["in_school_max_deferment_months"] == 48
    assert stored["repayment_max_deferment_months"] == 24
    assert stored["delinquency_notice_threshold_days"] == 5
    assert stored["allows_standalone_borrower"] is False
    assert_policy(stored)


def test_application_computed_fields_are_server_derived(api):
    """PRD §3.2: "its `certification_limit_cents` is fixed at this point as the cost
    of attendance minus other aid, floored at zero."
    PRD §3.1: "the combined score is whichever of the borrower's `credit_score` and
    the cosigner's `credit_score` is higher."

    Design: Corner/entities/application_computed_fields_ignore_client_input
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=760,
        application_overrides={
            "requested_amount_cents": 900000,
            "cost_of_attendance_cents": 900000,
            "other_aid_cents": 95000,
        },
    )
    app = orig.application
    assert app["certified_limit_cents"] == 805000
    assert app["combined_credit_score"] == 760
    assert app["tier"] == "A"
    assert app["margin_rate_pct"] == 2.75
    assert app["decision_path"] == "COSIGNER_PRIMARY"


def test_system_identifiers_and_stamps_are_server_minted(api):
    """PRD §2.6: "`id`: a unique, server-minted identifier formatted as a UUID with no
    type prefix."
    PRD §2.6: "`created_at`: an ISO 8601 UTC timestamp with three fractional digits,
    recording when the resource was created."

    Design: Corner/entities/system_identifiers_and_stamps_are_server_minted
    """
    school = create_school(school_code="009996")
    stored = validate_success(client.get_school(school["id"], TEST_USERS["admin_headers"]))
    assert is_valid_uuid(stored["id"])
    assert not stored["id"].startswith("sch_")
    assert stored["version"] == 1
    assert is_iso8601_timestamp(stored["created_at"])
    assert stored["created_at"] == stored["updated_at"]
    assert stored["school_code"] == "009996"
    assert_school(stored)


def test_an_undeclared_accrual_option_is_rejected(api):
    """PRD §3.2: "selecting an in-school `interest_accrual_option` of `DEFERRED`,
    `INTEREST_ONLY` or `IMMEDIATE`"
    PRD §2.12: "a missing required body field or an enum-valued field carrying a value
    outside its declared set yields `ERR_INVALID_REQUEST`"

    Design: Corner/entities/application_rejects_an_undeclared_accrual_option
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    bad = client.create_application(
        create_application_payload(
            orig.borrower["id"], orig.school["id"], orig.policy["id"],
            cosigner_id=orig.cosigner["id"], interest_accrual_option="FEDERAL_SUBSIDIZED",
        ),
        orig.applicant_headers,
    )
    validate_error(bad, ERR_INVALID_REQUEST)

    good = validate_success(
        client.create_application(
            create_application_payload(
                orig.borrower["id"], orig.school["id"], orig.policy["id"],
                cosigner_id=orig.cosigner["id"], interest_accrual_option="INTEREST_ONLY",
            ),
            orig.applicant_headers,
        ),
        expected_status=201,
    )
    assert good["interest_accrual_option"] == "INTEREST_ONLY"


def test_the_interest_ledger_row_is_an_append_only_log_without_a_version(api):
    """PRD §2.6: "The `InterestAccrualEntry` ledger row is created without the common
    fields beyond its identifier and creation instant: it carries only `id` and
    `created_at`, and it has neither an `updated_at` nor a `version` field."

    Design: Corner/entities/accrual_entry_is_an_append_only_log_row_without_a_version
    """
    orig = setup_certified_loan(disburse=True)
    create_accrual_entry(orig.loan["id"], window_months=6)
    entries = list_accrual_entries(orig.loan["id"], TEST_USERS["servicer_headers"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_status"] == "ACCRUED"
    assert entry["source_event"] == "PERIOD_ACCRUAL"
    assert "version" not in entry
    assert "updated_at" not in entry
    assert_accrual_entry(entry)
    assert validate_success(
        client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"])
    )["unpaid_interest_cents"] == 15096


def test_cancelling_an_already_cancelled_application_is_rejected(api):
    """PRD §3.2: "An application's `application_status` runs through `SUBMITTED`,
    `UNDER_REVIEW`, `SCHOOL_CERT_PENDING`, `APPROVED`, `DENIED`, `CANCELLED`,
    `DISBURSED` and `CLOSED`; `CANCELLED` and `CLOSED` are terminal."

    Design: Corner/state_machines/cancel_an_already_cancelled_application_returns_invalid_state
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    first = get_success_data(
        client.cancel_application(orig.application["id"], orig.applicant_headers)
    )
    assert first["application_status"] == "CANCELLED"

    response = client.cancel_application(orig.application["id"], orig.applicant_headers)
    validate_error(response, ERR_INVALID_STATE)
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "CANCELLED"


def test_a_filed_certification_starts_in_requested(api):
    """PRD §3.3: "Filing a request moves the application from `APPROVED` to
    `SCHOOL_CERT_PENDING` and creates the certification in `REQUESTED` status — its
    `certification_status`."

    Design: Corner/state_machines/school_certification_creation_starts_in_requested
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    approve(orig)
    certification = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=805000
    )
    assert certification["certification_status"] == "REQUESTED"
    assert certification["certified_date"] is None
    assert certification["rejection_reason"] is None
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "SCHOOL_CERT_PENDING"


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------

def test_an_application_naming_an_unknown_school_returns_school_not_found(api):
    """PRD §2.9: "an unresolved school yields `ERR_SCHOOL_NOT_FOUND`; an unresolved
    policy yields `ERR_POLICY_NOT_FOUND`"

    Design: Corner/validations/application_with_unknown_school_returns_school_not_found
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    baseline = validate_paginated(
        client.list_applications(TEST_USERS["underwriter_headers"])
    )[1]["total_count"]
    response = client.create_application(
        create_application_payload(
            orig.borrower["id"], NON_EXISTENT_UUID, orig.policy["id"],
            cosigner_id=orig.cosigner["id"],
        ),
        orig.applicant_headers,
    )
    validate_error(response, ERR_SCHOOL_NOT_FOUND)
    rows, meta = validate_paginated(
        client.list_applications(TEST_USERS["underwriter_headers"])
    )
    assert meta["total_count"] == baseline, "the rejected submission persists nothing"


def test_certification_existence_precedes_the_amount_ceiling(api):
    """PRD §2.9: "an unresolved loan yields `ERR_LOAN_NOT_FOUND`; and an unresolved
    certification yields `ERR_CERTIFICATION_NOT_FOUND`"
    PRD §2.12: "Existence follows, in the left-to-right order described in §2.9."

    Design: Corner/validations/certification_existence_precedes_the_amount_ceiling
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    approve(orig)
    response = client.certify(
        NON_EXISTENT_UUID,
        {"certified_amount_cents": 900000, "certified_enrollment_status": "IN_SCHOOL"},
        orig.school_headers,
    )
    validate_error(response, ERR_CERTIFICATION_NOT_FOUND)


def test_an_identical_application_body_is_accepted_after_a_cancellation(api):
    """PRD §2.12: "Authentication runs first: `ERR_UNAUTHENTICATED`, then
    authorization and ownership, `ERR_FORBIDDEN`."
    PRD §2.12: "State preconditions then apply: an operation that is not a declared
    transition out of the resource's current state, including any operation attempted
    on a resource already in a terminal state, yields `ERR_INVALID_STATE`"
    PRD §3.2: "Cancellation is likewise a borrower action, allowed only by the owning
    borrower, and is available from `SUBMITTED` or from `UNDER_REVIEW`"

    Design: Corner/validations/identical_application_body_is_accepted_when_the_first_is_cancelled
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    first = orig.application
    get_success_data(client.cancel_application(first["id"], orig.applicant_headers))

    second = validate_success(
        client.create_application(
            create_application_payload(
                orig.borrower["id"], orig.school["id"], orig.policy["id"],
                cosigner_id=orig.cosigner["id"],
            ),
            orig.applicant_headers,
        ),
        expected_status=201,
    )
    assert second["id"] != first["id"]
    assert second["application_status"] == "UNDER_REVIEW"

    rows = validate_success(
        client.list_borrower_applications(orig.borrower["id"], orig.applicant_headers)
    )
    statuses = sorted(row["application_status"] for row in rows)
    assert statuses == ["CANCELLED", "UNDER_REVIEW"]


def test_a_cosigner_less_file_is_refused_when_the_policy_requires_one(api):
    """PRD §3.2: "An application that names no cosigner at all may only be approved
    when the product policy permits a standalone file — that is, when the policy's
    `allows_standalone_borrower` is true, which defaults to false; otherwise the
    approval is refused with `ERR_COSIGNER_REQUIRED`."

    Design: Corner/errors/standalone_file_is_rejected_when_the_product_requires_a_cosigner
    """
    orig = build_origination(
        borrower_score=700, with_cosigner=False,
        policy_overrides={"allows_standalone_borrower": False},
    )
    response = client.decide_application(
        orig.application["id"], {"decision": "APPROVE"}, TEST_USERS["underwriter_headers"]
    )
    validate_error(response, ERR_COSIGNER_REQUIRED)


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------

def test_a_certification_at_or_below_the_ceiling_is_kept_whole(api):
    """PRD §3.3: "When the requested certifications fit at or below the ceiling, every
    child keeps its full amount and the headroom simply equals the ceiling minus the
    disbursed total."

    Design: Corner/calculations/certification_limit_waterfall_accepts_totals_at_or_below_the_ceiling
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=760,
        application_overrides={
            "requested_amount_cents": 900000,
            "cost_of_attendance_cents": 1210000,
            "other_aid_cents": 0,
        },
    )
    approve(orig)
    certification = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=900000
    )
    assert certification["certified_amount_cents"] == 900000
    assert certification["certification_status"] == "CERTIFIED"
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["certified_amount_cents"] == 900000
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 900000


def test_the_certified_aggregate_excludes_rejected_and_expired_children(api):
    """PRD §3.1: "a row in `UNPAID_DUE` or `WRITTEN_OFF` status contributes to
    neither total."
    PRD §3.3: "The eligible children — those in `CERTIFIED` or `PARTIAL_CERTIFIED`
    status, excluded of anything `REJECTED` or `EXPIRED`"

    Design: Corner/calculations/aggregation_input_set_excludes_rejected_and_expired_certifications
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=760,
        application_overrides={
            "requested_amount_cents": 900000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    live = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    rejected = file_certification(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=300000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    get_success_data(
        client.reject_certification(rejected["id"], {"rejection_reason": "PROGRAM_INELIGIBLE"},
                                    orig.school_headers)
    )
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["certified_amount_cents"] == 400000
    stored_rejected = validate_success(
        client.get_certification(rejected["id"], orig.school_headers)
    )
    assert stored_rejected["certification_status"] == "REJECTED"
    assert stored_rejected["rejection_reason"] == "PROGRAM_INELIGIBLE"
    assert live is not None


def test_the_plan_payment_stays_pinned_when_the_loan_rate_changes(api):
    """PRD §3.6: "The snapshot is read *first*, from the loan as of submission, and
    only then is the payment solved; a later automatic-debit change moves the loan's
    live rate but must never move this plan's payment."

    Design: Corner/calculations/monthly_payment_amortization_honours_the_pinned_snapshot
    """
    orig = setup_loan_in_repayment(periods=30)
    before = validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )[0]
    assert before["principal_snapshot_cents"] == 805000
    assert before["rate_snapshot_pct"] == 3.75
    assert before["term_months"] == 120
    assert before["monthly_payment_cents"] == 8055

    get_success_data(
        client.set_autodebit(orig.loan["id"], {"enrolled": True}, orig.applicant_headers)
    )
    after = validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )[0]
    assert after["monthly_payment_cents"] == 8055, "the pinned snapshot does not move"
    assert after["plan_status"] == "ACTIVE"
    assert_loan(validate_success(
        client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"])
    ))

def test_accrual_and_the_capitalization_cap_are_exact_whole_cent_figures(api):
    """PRD §2.7: "Wherever a calculation produces a monetary result, the final value is
    rounded half up to a whole cent, and any intermediate decimal arithmetic is carried
    at two decimal places before that final rounding."
    PRD §3.5: "the amount actually capitalized is the lesser of the two. At the exact
    boundary, when the unpaid interest equals the cap, the whole unpaid amount is
    capitalized — the comparison is inclusive at the cap."

    Design: Corner/calculations/capitalised_interest_stays_un_rounded_below_the_cap
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE",
        certified_amount_cents=805000, disbursement_amount_cents=805000,
    )
    create_accrual_entry(orig.loan["id"], window_months=1)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["unpaid_interest_cents"] == 2516, "805000 * 0.003125 = 2515.625"
    assert isinstance(loan["unpaid_interest_cents"], int), "cents are whole integers"
    assert loan["max_allowed_capitalization_cents"] == 80500, "10 percent of 805000"

    entries = list_accrual_entries(orig.loan["id"], TEST_USERS["servicer_headers"])
    assert entries[0]["accrued_amount_cents"] == 2516
    assert isinstance(entries[0]["accrued_amount_cents"], int)
