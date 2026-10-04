"""Pricing bands, the coverage step-down, milestone monotonicity and remaining
cross-entity guards."""
import pytest

from prd_bench_local_runner.testing import (
    validate_success, validate_error, get_success_data, is_valid_uuid,
    is_iso8601_timestamp,
)

from test_helpers import (
    ApiErrorId, api_client, create_book, setup_loan, add_rate_card,
    submit_application, approve_delegated, underwrite_and_approve, issue_loan,
    file_claim, begin_claim_review, refresh_loan, add_servicer, amortize,
    make_servicer_headers, setup_loan_with_approved_claim, settle_claim,
    ADMIN, UNDERWRITER,
)


def test_rate_lookup_bands_are_inclusive_at_the_upper_bound():
    """PRD §3.2: "A ratio at or below 85.0000 percent falls in `831_TO_85`. A
    ratio strictly above 85.0000 and at or below 90.0000 falls in `851_TO_90`."
    PRD §3.2: "Each band therefore includes its upper bound and excludes its
    lower bound."

    Design: Corner/calculations/rate_lookup_scales_the_rate_across_ltv_bands_with_inclusive_upper_bounds
    """
    book = create_book()
    rc_90 = add_rate_card(book, ltv_band="851_TO_90", rate_bps=85)

    # 34000000 on a 40000000 value is exactly 85.0000 percent.
    app_a = submit_application(book, borrower_reference="BAND-A",
                               rate_card_id=book["rate_card_id"])
    approve_delegated(book, app_a["id"])
    loan_a = issue_loan(book, app_a["id"])
    # 34000400 on the same value is 85.0010 percent, inside the next band.
    app_b = submit_application(book, borrower_reference="BAND-B",
                               loan_amount_cents=34_000_400,
                               rate_card_id=rc_90["id"])
    approve_delegated(book, app_b["id"])
    loan_b = issue_loan(book, app_b["id"])

    loan_a = get_success_data(api_client.get_loan(loan_a["id"], UNDERWRITER))
    loan_b = get_success_data(api_client.get_loan(loan_b["id"], UNDERWRITER))

    assert loan_a["rate_bps_applied"] == 62
    assert loan_a["coverage_base_upb_cents"] == 8_500_000
    assert loan_a["annual_premium_cents"] == 52_700

    assert loan_b["rate_bps_applied"] == 85
    assert loan_b["coverage_base_upb_cents"] == 8_500_100
    # The band selection changed the priced rate, not merely the label.
    assert loan_a["annual_premium_cents"] != loan_b["annual_premium_cents"]


def test_non_delegated_approval_steps_coverage_down_five_points_per_failed_condition():
    """PRD §3.1: "Each failing condition costs five points, each is applied once
    regardless of how badly the condition fails, and the two reductions are added
    together rather than compounded — so an application that fails both is
    reduced by ten points, neither more nor less."

    Design: Corner/state_machines/delegated_approve_freezes_the_rate_and_computes_the_coverage_base
    """
    book = create_book(lender_delegated=False,
                       rate_card_overrides={"min_borrower_reserves_months": 6})

    # Both conditions fail: grade C is worse than the card's B band, and no
    # reserves are documented against a six-month requirement.
    both = submit_application(book, borrower_reference="STEP-BOTH",
                              credit_grade="C", borrower_reserves_months=0)
    underwrite_and_approve(both["id"])
    stepped = get_success_data(api_client.get_application(both["id"], ADMIN))
    assert stepped["status"] == "APPROVED"
    assert stepped["approved_coverage_percent"] == 15
    assert stepped["coverage_base_upb_cents"] == 5_100_000

    # Only the reserve condition fails: a single five-point reduction.
    one = submit_application(book, borrower_reference="STEP-ONE",
                             credit_grade="B", borrower_reserves_months=0)
    underwrite_and_approve(one["id"])
    single = get_success_data(api_client.get_application(one["id"], ADMIN))
    assert single["approved_coverage_percent"] == 20
    assert single["coverage_base_upb_cents"] == 6_800_000


def test_the_amortization_axis_never_regresses_after_reaching_at_78():
    """PRD §3.5: "The axis is monotonic and never regresses, so a loan already at
    `AT_78` stays there on a later report even if the newly submitted balance
    would only qualify it for `AT_80`."
    PRD §3.5: "The first time a loan enters `AT_78`, the logical clock is stamped
    into `milestone_78_reached_utc` and is never revisited afterward."

    Design: Corner/state_machines/coverage_application_underwrite_moves_the_application_to_in_underwriting
    """
    book = setup_loan()
    amortize(book, 31_190_000)
    first = refresh_loan(book)
    assert first["amortization_status"] == "AT_78"
    stamped = first["milestone_78_reached_utc"]

    # A later balance would qualify only for AT_80 if recomputed from scratch.
    amortize(book, 31_800_000)
    second = refresh_loan(book)
    assert second["amortization_status"] == "AT_78"
    assert second["milestone_78_reached_utc"] == stamped


def test_milestone_record_is_refused_while_the_balance_exceeds_the_eighty_percent_line():
    """PRD §3.5: "The operation is refused outright with `ERR_MILESTONE_NOT_REACHED`
    when the submitted balance still exceeds eighty percent of the loan's
    `origination_property_value_cents` — that is, when the balance is greater
    than the floor of 0.80 times that value."
    PRD §3.5: "the balance is greater than the floor of 0.80 times that value".

    Design: Corner/state_machines/coverage_application_underwrite_moves_the_application_to_in_underwriting
    """
    book = setup_loan()
    # Sixty percent of a 40000000-cent value is still well above the 80 line.
    response = api_client.record_amortization_milestone(
        book["loan_id"], {"current_upb_cents": 32_000_001}, ADMIN)
    validate_error(response, ApiErrorId.ERR_MILESTONE_NOT_REACHED)

    unchanged = refresh_loan(book)
    assert unchanged["amortization_status"] == "IN_AMORTIZATION"
    assert unchanged["current_upb_cents"] == 34_000_000


def test_delinquency_report_from_a_non_designated_servicer_is_refused():
    """PRD §3.4: "The reporting servicer must also be the loan's own designated
    servicer; a report from any other organization is refused with
    `ERR_SERVICER_NOT_DESIGNATED`."

    Design: Corner/validations/delinquency_report_from_a_servicer_that_is_not_the_loans_designated_one_is_rejected
    """
    book = setup_loan()
    other = add_servicer(servicer_name="Redline Servicing")

    payload = {
        "loan_id": book["loan_id"],
        "servicer_id": other["id"],
        "as_of_period": "2026-01",
        "delinquency_class": "A",
        "months_delinquent": 2,
        "loss_mitigation_activities": [],
    }
    response = api_client.create_delinquency_report(
        payload, make_servicer_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_SERVICER_NOT_DESIGNATED)
    assert get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_id"], UNDERWRITER)) == []

    # The designated servicer's identical report is accepted.
    designated = dict(payload, servicer_id=book["servicer_id"])
    accepted = api_client.create_delinquency_report(designated, book["servicer_headers"])
    assert validate_success(accepted, expected_status=201)["status"] == "FILED"


def test_a_loan_round_trips_its_audit_fields_and_inherited_terms():
    """PRD §2.4: "Alongside `id`, every resource carries a `created_at` instant,
    an `updated_at` instant and an integer `version`."
    PRD §3.3: "Issuance also denormalizes the application's `lender_id` and
    `master_policy_id` onto the loan".

    Design: Corner/entities/lender_create_with_delegated_authority_round_trips_through_get
    """
    book = setup_loan()
    loan = get_success_data(api_client.get_loan(book["loan_id"], UNDERWRITER))

    assert is_valid_uuid(loan["id"])
    assert is_iso8601_timestamp(loan["created_at"])
    assert is_iso8601_timestamp(loan["updated_at"])
    assert isinstance(loan["version"], int) and loan["version"] >= 1

    assert loan["coverage_percent"] == 25
    assert loan["premium_plan"] == "BPM"
    assert loan["borrower_paid"] is True
    assert loan["underwriting_path"] == "DELEGATED"
    assert loan["coverage_base_upb_cents"] == 8_500_000
    assert loan["current_upb_cents"] == 34_000_000
    assert loan["current_coverage_base_cents"] == 8_500_000
    assert loan["lender_id"] == book["lender_id"]
    assert loan["master_policy_id"] == book["mp_id"]
    assert loan["credit_grade"] == "B"
    assert loan["approval_credit_grade"] == "B"
    assert loan["county_code"] == "06037"
    assert loan["term_months"] == 360
    assert loan["claim_blocked"] is False
    assert loan["aggregate_ceded_cents"] == 0
    assert loan["rescission_relief_status"] == "NONE"
    assert loan["verified_property_value_cents"] is None
    assert loan["verified_loan_amount_cents"] is None