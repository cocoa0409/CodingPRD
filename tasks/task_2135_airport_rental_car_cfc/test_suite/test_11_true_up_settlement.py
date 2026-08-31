"""The minimum guarantee true-up and its settlement."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    TREASURY,
    AUDIT_OFFICER_2_USER_ID,
    AUDIT_OFFICER_USER_ID,
    ApiErrorId,
    assert_settlement,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _five_million_base_settlement(api):
    """An agreement whose year lands `base_true_up_cents` on exactly 5,000,000 cents:
    75,000,000 of audited revenue at 1000 bps, 7,500,000 already billed, a 500,000 cent
    audit assessment and a 12,000,000 cent minimum annual guarantee."""
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=20_000_000,
        reported_on_airport_transaction_days=1_000,
        audited_gross_revenue_cents=25_000_000,
        audited_on_airport_transaction_days=1_000,
    )
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=50_000_000,
        reported_on_airport_transaction_days=1_000,
    )
    scenario["settlement"] = fx.create_settlement(api, agreement_id)
    return scenario


def test_credit_tier_is_keyed_on_the_base_figure(api):
    """PRD §3.10: "**Step two** selects the shuttle performance credit, and the tier is keyed
    on `base_true_up_cents` and never on the net figure. When `base_true_up_cents` is zero or
    negative, `credit_bps` is 0. When it is at least fifty thousand dollars — five million
    cents — `credit_bps` is 300, a three percent credit. Otherwise, when it is at least ten
    thousand dollars — one million cents — `credit_bps` is 150, a one and a half percent
    credit. Below that threshold `credit_bps` is 0. `shuttle_credit_cents` is
    `base_true_up_cents` multiplied by `credit_bps`, divided by 10,000 and rounded half up.
    **Step three** is the netting: `net_true_up_cents` is `base_true_up_cents` minus
    `shuttle_credit_cents`. Keying the tier on `net_true_up_cents` is explicitly wrong."

    Design: Difficulty/combinatorial_formula/true_up_credit_tier_keyed_on_base_not_on_net
    """
    scenario = _five_million_base_settlement(api)

    issued = validate_success(
        api.issue_settlement(scenario["settlement"]["id"], AUDITOR_2)
    )

    assert issued["base_true_up_cents"] == 5_000_000
    assert issued["credit_bps"] == 300, (
        "a base of exactly 5,000,000 cents sits on the inclusive edge of the 300 bps tier"
    )
    assert issued["shuttle_credit_cents"] == 150_000
    assert issued["net_true_up_cents"] == 4_850_000
    assert issued["net_true_up_cents"] != 4_927_250, (
        "keying the tier on the net figure would have produced 4,927,250"
    )


def test_issuance_freezes_the_step_one_figures(api):
    """PRD §3.10: "**Step one** builds the base. `final_percentage_rent_cents` is the
    agreement's `gross_revenue_ytd_cents` multiplied by its `percentage_rent_rate_bps`,
    divided by 10,000 and rounded half up. `mag_cents` is the agreement's `mag_annual_cents`.
    `rent_billed_cents` is the agreement's `rent_billed_to_date_cents`.
    `audit_assessment_cents` is the total of `variance_assessment_cents` over the agreement's
    reports in `ACCEPTED` status only — a superseded report's assessment is excluded even
    though it was once real. All four are read from the agreement at issue time and frozen
    onto the settlement row. `base_true_up_cents` is then the greater of `mag_cents` and
    `final_percentage_rent_cents`, minus `rent_billed_cents`, plus `audit_assessment_cents`;
    it may come out negative when the year was over-billed."
    PRD §3.10: "Issuance stamps `issued_by_user_id` with the acting `X-User-ID`, carries the
    settlement to `ISSUED`, and advances its `version` by 1."

    Design: Difficulty/combinatorial_formula/true_up_credit_tier_keyed_on_base_not_on_net
    """
    scenario = _five_million_base_settlement(api)

    issued = validate_success(
        api.issue_settlement(scenario["settlement"]["id"], AUDITOR_2)
    )

    assert_settlement(issued)
    assert issued["final_percentage_rent_cents"] == 7_500_000
    assert issued["mag_cents"] == 12_000_000
    assert issued["rent_billed_cents"] == 7_500_000
    assert issued["audit_assessment_cents"] == 500_000
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == AUDIT_OFFICER_2_USER_ID


def test_tier_flip_supersedes_a_drafted_settlement(api):
    """PRD §3.5: "**Hop three** propagates the tier change outward. Because hop two moved the
    agreement's `rent_tier` from `MAG_FLOOR` to `PERCENTAGE`, every true-up settlement of that
    agreement still sitting in `DRAFT` is invalidated and moves `DRAFT → SUPERSEDED`,
    processed in ascending `created_at` order, each advancing its own `version` by 1."
    PRD §3.10: "The other terminal exit is `SUPERSEDED`, reached only when a report acceptance
    flips the agreement's `rent_tier` into `PERCENTAGE` while the settlement is still
    `DRAFT`."

    Design: Difficulty/transitive_cascade/report_acceptance_cascades_to_true_up_supersede_depth_three
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    settlement = fx.create_settlement(api, agreement_id)
    second = fx.create_report_under_audit(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=20_000_000,
        reported_on_airport_transaction_days=8_000,
    )

    validate_success(
        api.accept_report(
            second["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=20_000_000,
                audited_on_airport_transaction_days=8_000,
            ),
            AUDITOR,
        )
    )

    stored = validate_success(api.get_settlement(settlement["id"], ADMIN))
    assert stored["status"] == "SUPERSEDED", (
        "a settlement drafted on a minimum-guarantee assumption cannot survive the tier flip"
    )
    assert stored["net_true_up_cents"] == 0, "the settlement never reached ISSUED"


def test_acceptance_rolls_the_agreement_into_percentage_rent(api):
    """PRD §3.5: "The agreement's `accepted_report_count` rises by 1, its
    `gross_revenue_ytd_cents` rises by `audited_gross_revenue_cents`, and its
    `transaction_days_ytd` rises by `audited_on_airport_transaction_days`."
    PRD §3.5: "Under the `CUMULATIVE_YTD` variant, the rent due to date is the greater of the
    year-to-date percentage rent and the minimum guarantee to date, and the installment for
    this acceptance is that rent due to date minus the agreement's `rent_billed_to_date_cents`
    as it stood before this acceptance."
    PRD §3.5: "The installment is also written onto the report as
    `period_rent_installment_cents`."

    Design: Difficulty/transitive_cascade/report_acceptance_cascades_to_true_up_supersede_depth_three
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    fx.create_settlement(api, agreement_id)
    second = fx.create_report_under_audit(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=20_000_000,
        reported_on_airport_transaction_days=8_000,
    )

    accepted = validate_success(
        api.accept_report(
            second["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=20_000_000,
                audited_on_airport_transaction_days=8_000,
            ),
            AUDITOR,
        )
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["period_rent_installment_cents"] == 1_500_000
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["gross_revenue_ytd_cents"] == 25_000_000
    assert agreement["percentage_rent_accrued_cents"] == 2_500_000
    assert agreement["rent_billed_to_date_cents"] == 2_500_000
    assert agreement["rent_tier"] == "PERCENTAGE"
    assert agreement["mag_shortfall_cents"] == 0
    assert agreement["accepted_report_count"] == 2


def test_unfinalised_report_blocks_issuance(api):
    """PRD §3.10: "Every transaction-day report of the agreement must have reached `ACCEPTED`
    or `SUPERSEDED`; if any report of the agreement is still in `DRAFT`, `SUBMITTED`,
    `UNDER_AUDIT` or `REJECTED`, the issuance is rejected with `ERR_REPORTS_NOT_FINALIZED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/true_up_issue_blocked_by_unfinalised_report
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    open_report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=7_000_000,
        reported_on_airport_transaction_days=2_000,
    )
    fx.submit_report(api, open_report["id"], operator)
    settlement = fx.create_settlement(api, agreement_id)

    response = api.issue_settlement(settlement["id"], AUDITOR_2)

    validate_error(response, ApiErrorId.ERR_REPORTS_NOT_FINALIZED.value, 409)
    stored_report = validate_success(api.get_report(open_report["id"], ADMIN))
    assert stored_report["status"] == "SUBMITTED"


def test_blocked_issuance_leaves_the_settlement_in_draft(api):
    """PRD §3.10: "Every transaction-day report of the agreement must have reached `ACCEPTED`
    or `SUPERSEDED`; if any report of the agreement is still in `DRAFT`, `SUBMITTED`,
    `UNDER_AUDIT` or `REJECTED`, the issuance is rejected with `ERR_REPORTS_NOT_FINALIZED`
    (HTTP 409)."
    PRD §3.10: "A drafted settlement starts in `DRAFT` with `final_percentage_rent_cents`,
    `mag_cents`, `rent_billed_cents`, `audit_assessment_cents`, `base_true_up_cents`,
    `credit_bps`, `shuttle_credit_cents`, `net_true_up_cents` and `amount_paid_cents` all at
    0, and `issued_by_user_id` null."

    Design: Difficulty/cross_entity_state_dependency/true_up_issue_blocked_by_unfinalised_report
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    open_report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=7_000_000,
        reported_on_airport_transaction_days=2_000,
    )
    fx.submit_report(api, open_report["id"], operator)
    settlement = fx.create_settlement(api, agreement_id)

    api.issue_settlement(settlement["id"], AUDITOR_2)

    stored = validate_success(api.get_settlement(settlement["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["net_true_up_cents"] == 0
    assert stored["issued_by_user_id"] is None


def test_dispute_then_reissue_closes_the_loop(api):
    """PRD §3.10: "Disputing an issued settlement is the one action reserved exclusively to a
    `ConcessionaireOperator`; it carries `ISSUED → DISPUTED` and advances the settlement's
    `version` by 1, and re-issuance closes the `ISSUED → DISPUTED → ISSUED` negotiation loop,
    which may run any number of times."
    PRD §3.10: "Re-issuance from `DISPUTED` re-runs the whole computation against the
    agreement's current figures rather than reusing the frozen ones, so a settlement that was
    disputed and then re-issued after further audit activity carries fresh numbers."

    Design: Corner/state_machines/true_up_dispute_then_reissue_closes_the_negotiation_loop
    """
    scenario = fx.setup_issued_settlement(
        api, mag_annual_cents=12_000_000, audited_gross_revenue_cents=5_000_000
    )
    settlement_id = scenario["settlement"]["id"]

    disputed = validate_success(api.dispute_settlement(settlement_id, scenario["operator"]))
    assert disputed["status"] == "DISPUTED"

    reissued = validate_success(api.issue_settlement(settlement_id, AUDITOR_2))

    assert reissued["status"] == "ISSUED"
    assert reissued["final_percentage_rent_cents"] == 500_000
    assert reissued["mag_cents"] == 12_000_000
    assert reissued["rent_billed_cents"] == 1_000_000
    assert reissued["audit_assessment_cents"] == 0
    assert reissued["base_true_up_cents"] == 11_000_000
    assert reissued["credit_bps"] == 300
    assert reissued["shuttle_credit_cents"] == 330_000
    assert reissued["net_true_up_cents"] == 10_670_000


def test_credit_tier_boundary_at_one_million_uses_150_bps(api):
    """PRD §3.10: "Otherwise, when it is at least ten thousand dollars — one million cents —
    `credit_bps` is 150, a one and a half percent credit. Below that threshold `credit_bps` is
    0. `shuttle_credit_cents` is `base_true_up_cents` multiplied by `credit_bps`, divided by
    10,000 and rounded half up. **Step three** is the netting: `net_true_up_cents` is
    `base_true_up_cents` minus `shuttle_credit_cents`."
    PRD §3.10: "`base_true_up_cents` is then the greater of `mag_cents` and
    `final_percentage_rent_cents`, minus `rent_billed_cents`, plus `audit_assessment_cents`;
    it may come out negative when the year was over-billed."

    Design: Corner/calculations/true_up_credit_tier_boundary_at_exactly_one_million_uses_150_bps
    """
    scenario = fx.setup_active_agreement(
        api, agreement_overrides={"mag_annual_cents": 1_500_000}
    )
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["rent_billed_to_date_cents"] == 500_000
    settlement = fx.create_settlement(api, agreement_id)

    issued = validate_success(api.issue_settlement(settlement["id"], AUDITOR_2))

    assert issued["final_percentage_rent_cents"] == 500_000
    assert issued["base_true_up_cents"] == 1_000_000
    assert issued["credit_bps"] == 150, (
        "1,000,000 cents is the inclusive lower edge of the mid tier"
    )
    assert issued["shuttle_credit_cents"] == 15_000
    assert issued["net_true_up_cents"] == 985_000
    assert issued["status"] == "ISSUED"


def test_settlement_for_the_wrong_contract_year_is_rejected(api):
    """PRD §3.10: "A settlement is drafted against an `agreement_id` and a
    `contract_year_index` of at least 1, which must equal the referenced agreement's own
    `contract_year_index`; a mismatch is rejected with `ERR_CONTRACT_YEAR_MISMATCH` (HTTP
    422)."

    Design: Corner/validations/true_up_with_mismatched_contract_year_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id = scenario["agreement"]["id"]

    response = api.create_settlement(
        f.settlement_payload(agreement_id, contract_year_index=2), AUDITOR_2
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_YEAR_MISMATCH.value, 422)
    _rows, meta = validate_paginated(
        api.list_settlements(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 0


def test_second_open_settlement_for_a_year_is_rejected(api):
    """PRD §3.10: "At most one settlement per agreement and contract year may exist in
    `DRAFT`, `ISSUED` or `DISPUTED` at a time, and a second is rejected with
    `ERR_DUPLICATE_SETTLEMENT` (HTTP 409)."

    Design: Corner/errors/second_open_true_up_settlement_for_the_same_year_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    first = fx.create_settlement(api, agreement_id)

    response = api.create_settlement(f.settlement_payload(agreement_id), AUDITOR_2)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SETTLEMENT.value, 409)
    _rows, meta = validate_paginated(
        api.list_settlements(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
    stored = validate_success(api.get_settlement(first["id"], ADMIN))
    assert stored["status"] == "DRAFT"


def test_underpaid_settlement_is_rejected(api):
    """PRD §3.10: "Settling is the treasury's closing act: it is available only from `ISSUED`,
    and the supplied `amount_paid_cents` must be at least `net_true_up_cents` or the request
    is rejected with `ERR_SETTLEMENT_UNDERPAID` (HTTP 422)."

    Design: Corner/validations/settlement_payment_below_net_true_up_is_rejected
    """
    scenario = fx.setup_issued_settlement(
        api, mag_annual_cents=1_500_000, audited_gross_revenue_cents=5_000_000
    )
    settlement_id = scenario["settlement"]["id"]
    assert scenario["settlement"]["net_true_up_cents"] == 985_000

    response = api.settle_settlement(settlement_id, f.settle_payload(900_000), TREASURY)

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_UNDERPAID.value, 422)
    stored = validate_success(api.get_settlement(settlement_id, ADMIN))
    assert stored["status"] == "ISSUED"
    assert stored["amount_paid_cents"] == 0
    assert stored["net_true_up_cents"] == 985_000


def test_auditor_who_accepted_the_report_cannot_issue(api):
    """PRD §2.10: "On true-up issuance, an `AuditOfficer` whose `X-User-ID` appears as
    `audited_by_user_id` on any `ACCEPTED` transaction-day report of the agreement may not
    issue a true-up settlement for that agreement. A match on any such report rejects the
    issuance with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.5: "`audited_by_user_id` is stamped with the accepting officer's `X-User-ID`; and
    the report's status becomes `ACCEPTED`."

    Design: Corner/rbac/auditor_who_accepted_the_report_cannot_issue_its_true_up
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    settlement = fx.create_settlement(api, agreement_id)

    response = api.issue_settlement(settlement["id"], AUDITOR)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    stored_report = validate_success(api.get_report(report["id"], ADMIN))
    assert stored_report["audited_by_user_id"] == AUDIT_OFFICER_USER_ID
    stored = validate_success(api.get_settlement(settlement["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["issued_by_user_id"] is None
    assert stored["net_true_up_cents"] == 0
