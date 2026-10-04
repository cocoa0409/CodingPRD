"""Marketing fund: accrual variants, disbursement boundary, clawback invariant."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    get_success_data,
    seed_active_agreement,
    add_second_active_agreement,
    post_accrual,
    create_fund_entry_payload,
    ops_headers,
    make_bottler_ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def test_marketing_accrual_case_volume_variant_amount(api):
    """PRD §3.7: "When the basis is `CASE_VOLUME`, the accrual is the entry's
    `cases_sold` multiplied by a flat rate of 40 cents per case, and
    `cases_sold` is required while `net_revenue_cents` is ignored."
    PRD §3.7: "Every accepted entry moves the derived
    `marketing_fund_balance_cents`: accruals add, disbursements subtract, and
    clawbacks subtract."

    Design: Difficulty/dual_variant_calc/marketing_accrual_case_volume_vs_net_revenue_diverge
    """
    env = seed_active_agreement(basis="CASE_VOLUME")
    entry = post_accrual(env, cases_sold=50000, net_revenue_cents=10000000)
    assert entry["amount_cents"] == 2000000  # 50000 * 40
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["marketing_fund_balance_cents"] == 2000000


def test_marketing_accrual_net_revenue_variant_diverges(api):
    """PRD §3.7: "When the basis is `NET_REVENUE`, the accrual is the entry's
    `net_revenue_cents` multiplied by two and a half percent, rounded half-up
    to whole cents, and `net_revenue_cents` is required while `cases_sold` is
    ignored. Because the two variants consume different inputs, the same
    period's data yields a different accrual under each basis."

    Design: Difficulty/dual_variant_calc/marketing_accrual_case_volume_vs_net_revenue_diverge
    """
    env = seed_active_agreement(basis="NET_REVENUE")
    entry = post_accrual(env, cases_sold=50000, net_revenue_cents=10000000)
    assert entry["amount_cents"] == 250000  # round_half_up(10000000 * 0.025)
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["marketing_fund_balance_cents"] == 250000


def test_marketing_fund_accrual_then_equal_clawback_restores_balance(api):
    """PRD §3.7: "A `CLAWBACK` entry also takes `requested_amount_cents`, and
    additionally requires a `reference_entry_id` pointing at an `ACCRUAL` entry
    of the same agreement; a reference to another agreement's entry, or to a
    non-accrual entry, is rejected with `ERR_REFERENTIAL_INTEGRITY`, and a
    clawback amount exceeding the referenced accrual's amount is rejected with
    `ERR_CLAWBACK_EXCEEDS_ACCRUAL` (HTTP 422)."
    PRD §3.7: "Every accepted entry moves the derived
    `marketing_fund_balance_cents`: accruals add, disbursements subtract, and
    clawbacks subtract."

    Design: Difficulty/compensating_invariant/marketing_fund_accrual_then_equal_clawback_restores_balance
    """
    env = seed_active_agreement(basis="CASE_VOLUME")
    accrual = post_accrual(env, cases_sold=50000)
    assert accrual["amount_cents"] == 2000000
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement"]["id"],
            entry_type="CLAWBACK",
            requested_amount_cents=2000001,
            reference_entry_id=accrual["id"],
        ),
        BOA,
    )
    validate_error(r, ApiErrorId.ERR_CLAWBACK_EXCEEDS_ACCRUAL.value)
    assert r.status_code == 422
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement"]["id"],
            entry_type="CLAWBACK",
            requested_amount_cents=2000000,
            reference_entry_id=accrual["id"],
        ),
        BOA,
    )
    assert r.status_code == 201, f"equal clawback must be accepted: {r.text}"
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["marketing_fund_balance_cents"] == 0, (
        "accrue A then claw back A must restore the prior balance"
    )


def test_marketing_fund_partial_clawback_leaves_remainder(api):
    """PRD §3.7: "A `CLAWBACK` entry also takes `requested_amount_cents`, and
    additionally requires a `reference_entry_id` pointing at an `ACCRUAL` entry
    of the same agreement; a reference to another agreement's entry, or to a
    non-accrual entry, is rejected with `ERR_REFERENTIAL_INTEGRITY`, and a
    clawback amount exceeding the referenced accrual's amount is rejected with
    `ERR_CLAWBACK_EXCEEDS_ACCRUAL` (HTTP 422)."
    PRD §3.7: "Every accepted entry moves the derived
    `marketing_fund_balance_cents`: accruals add, disbursements subtract, and
    clawbacks subtract."

    Design: Difficulty/compensating_invariant/marketing_fund_accrual_then_equal_clawback_restores_balance
    """
    env = seed_active_agreement(basis="CASE_VOLUME")
    accrual = post_accrual(env, cases_sold=50000)
    assert accrual["amount_cents"] == 2000000
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement"]["id"],
            entry_type="CLAWBACK",
            requested_amount_cents=500000,
            reference_entry_id=accrual["id"],
        ),
        BOA,
    )
    assert r.status_code == 201, f"clawback within the referenced accrual must be accepted: {r.text}"
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["marketing_fund_balance_cents"] == 1500000


def test_disbursement_exceeding_fund_balance_rejected(api):
    """PRD §3.7: "A `DISBURSEMENT` entry instead takes its amount from the
    caller's `requested_amount_cents`, which must be strictly greater than
    zero, and the disbursement must not exceed the agreement's current
    `marketing_fund_balance_cents` — an overdraw is rejected with
    `ERR_FUND_INSUFFICIENT_BALANCE` (HTTP 422)."

    Design: Corner/validations/disbursement_exceeding_fund_balance_rejected
    """
    env = seed_active_agreement(basis="CASE_VOLUME")
    post_accrual(env, cases_sold=1000)  # balance 40000
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement"]["id"],
            entry_type="DISBURSEMENT",
            requested_amount_cents=40001,
        ),
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_FUND_INSUFFICIENT_BALANCE.value)
    assert r.status_code == 422
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement"]["id"],
            entry_type="DISBURSEMENT",
            requested_amount_cents=40000,
        ),
        ops_headers(env),
    )
    assert r.status_code == 201, f"exact-balance disbursement must be accepted: {r.text}"
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["marketing_fund_balance_cents"] == 0


def test_clawback_referencing_other_agreements_accrual_rejected(api):
    """PRD §3.7: "A `CLAWBACK` entry also takes `requested_amount_cents`, and
    additionally requires a `reference_entry_id` pointing at an `ACCRUAL` entry
    of the same agreement; a reference to another agreement's entry, or to a
    non-accrual entry, is rejected with `ERR_REFERENTIAL_INTEGRITY`, and a
    clawback amount exceeding the referenced accrual's amount is rejected with
    `ERR_CLAWBACK_EXCEEDS_ACCRUAL` (HTTP 422)."

    Design: Corner/validations/clawback_referencing_other_agreements_accrual_rejected
    """
    env = seed_active_agreement(basis="CASE_VOLUME")
    add_second_active_agreement(env)
    accrual1 = post_accrual(env, cases_sold=50000)  # 2000000 on agreement 1
    post_accrual(
        {**env, "agreement": env["agreement2"]}, cases_sold=1000
    )  # 40000 on agreement 2
    r = api_client.create_fund_entry(
        create_fund_entry_payload(
            agreement_id=env["agreement2"]["id"],
            entry_type="CLAWBACK",
            requested_amount_cents=30000,
            reference_entry_id=accrual1["id"],
        ),
        BOA,
    )
    validate_error(r, ApiErrorId.ERR_REFERENTIAL_INTEGRITY.value)
    assert r.status_code == 422
    agreement2 = get_success_data(api_client.get_agreement(env["agreement2"]["id"], PA))
    assert agreement2["marketing_fund_balance_cents"] == 40000
