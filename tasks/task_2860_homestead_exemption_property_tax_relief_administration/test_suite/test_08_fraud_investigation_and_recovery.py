"""Investigating a residency lie, scoring it twice and collecting on it.

A case carries two independent axes — guilt and money — and two risk scores read
from the same cross-match log: the screening snapshot believes the latest word on
each source, while the adjudication replay latches every mismatch ever recorded.
Substantiation then freezes a per-year assessment and cascades across the roll.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_ALREADY_ADJUDICATED,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_RECOVERY_NOT_ASSESSED,
    ERR_RISK_SCORE_BELOW_THRESHOLD,
    ERR_TAXPAYER_BARRED,
)
from test_helpers.assertions import (
    assert_claim_amounts,
    assert_grant,
    assert_money,
    assert_parcel_decomposition,
    assert_recovery_assessment,
    assert_taxpayer_ledger,
)
from test_helpers.constants import ADDR_ELM
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    INVESTIGATOR,
    INVESTIGATOR_2,
    INVESTIGATOR_USER_ID,
    RECOVERY,
    REVIEWER,
    REVIEWER_2,
)


def _screened_case(api):
    """An investigation opened over a log whose address mismatch was corrected.

    The voter row first sat at a foreign address and was cross-matched there
    before a corrected row was checked, the postal row reports a forwarding order
    and the revenue row contradicts the certification. The household holds one
    homestead grant on one parcel, so the multiple-claims factor cannot fire.
    """
    world = fx.mismatching_check_world(api)
    world["case"] = fx.open_fraud_case(
        api,
        world["grant_id"],
        world["taxpayer"]["id"],
        improper_start_tax_year=2025,
        improper_end_tax_year=2025,
    )
    return world


def test_screening_believes_the_latest_word_on_each_cross_match_source(api):
    """PRD §3.8: "The screening variant, run at case opening, collapses the log to
    the latest check per source — latest by `checked_at` descending, with the later
    `created_at` breaking a tie — and treats a source as mismatched only when that
    latest check reads `MISMATCH`. A subsequent `MATCH` therefore hides an earlier
    `MISMATCH`, so a corrected registry record drives the screening score down."

    Design: Difficulty/dual_variant_calc/fraud_risk_screening_snapshot_versus_adjudication_replay
    """
    world = _screened_case(api)
    case = world["case"]

    # Postal 1500 plus income 2000 over ten thousand: the corrected voter row
    # contributes nothing and the single homestead grant contributes nothing.
    assert case["screening_risk_score"] == 35, (
        f"the snapshot must score 35, got {case['screening_risk_score']}"
    )
    assert case["adjudication_risk_score"] == 0, (
        "a newly opened case has no replayed score, got "
        f"{case['adjudication_risk_score']}"
    )
    assert case["investigation_status"] == "OPEN", (
        f"a case opens on the adjudication axis at OPEN, got {case['investigation_status']}"
    )
    assert case["recovery_status"] == "NONE", (
        f"a case opens on the money axis at NONE, got {case['recovery_status']}"
    )
    assert_recovery_assessment(
        case,
        back_tax_cents=0,
        penalty_cents=0,
        interest_cents=0,
        total_assessed_cents=0,
        recovery_paid_cents=0,
    )


def test_adjudication_replays_the_superseded_mismatch_and_scores_higher(api):
    """PRD §3.8: "The adjudication variant, run at case decision, instead walks
    every check ever recorded in `checked_at` ascending order and latches a
    mismatch permanently, superseded rows included; it therefore yields a strictly
    higher score than the screening variant whenever a mismatch was later
    corrected." PRD §3.8 adds that "**Clearing** a case compensates the suspension
    it caused: the suspended grant returns to `ACTIVE` with `suspension_reason`
    cleared".

    Design: Difficulty/dual_variant_calc/fraud_risk_screening_snapshot_versus_adjudication_replay
    """
    world = _screened_case(api)

    cleared = validate_success(
        api.decide_fraud_case(
            world["case"]["id"],
            f.fraud_decision(
                "CLEAR", "Registry record was corrected before the claim year."
            ),
            INVESTIGATOR,
        )
    )

    # Address 3500 latched, plus postal 1500 and income 2000, over ten thousand.
    assert cleared["adjudication_risk_score"] == 70, (
        f"the replay must score 70, got {cleared['adjudication_risk_score']}"
    )
    assert cleared["screening_risk_score"] == 35, (
        "the snapshot taken at opening is not rewritten by the replay, got "
        f"{cleared['screening_risk_score']}"
    )
    assert cleared["adjudication_risk_score"] > cleared["screening_risk_score"], (
        "a corrected mismatch must make the replay the higher of the two scores: "
        f"{cleared['adjudication_risk_score']} vs {cleared['screening_risk_score']}"
    )
    assert cleared["investigation_status"] == "CLEARED", (
        f"the clearing decision closes the case, got {cleared['investigation_status']}"
    )
    assert cleared["recovery_status"] == "NONE", (
        f"a cleared case never assesses anything, got {cleared['recovery_status']}"
    )
    assert_recovery_assessment(cleared, total_assessed_cents=0)

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(grant, benefit_status="ACTIVE", suspension_reason=None)

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    account = validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK))
    assert account["status"] == "GOOD_STANDING", (
        "clearing the only open investigation restores the account, got "
        f"{account['status']}"
    )


def _prorated_grant_under_investigation(api):
    """A one-third owner's grant, sized so each year's back tax lands on a half cent.

    The parcel's capped basis of 62400000 asks for more relief than the programme
    allows, so the ceiling of 10000000 binds before the 3333 basis-point share is
    applied and the benefit settles at 3333000 — a figure whose statutory back tax
    is exactly 41662.5 cents a year.
    """
    world = fx.approval_world(
        api,
        check_log="damning",
        certification={
            "certification_year": 2026,
            "recertification_due_date": "2026-12-31",
            "household_income_cents": 5000000,
            "countable_asset_cents": 1000000,
            "household_size": 2,
        },
        parcel=f.parcel(
            apn="P-0002",
            situs_address_normalized="202 CEDAR LN EASTWICK ST 10002",
            county_zone="EAST",
            base_year=2024,
            base_year_value_cents=60000000,
            market_value_cents=70000000,
        ),
        taxpayer=f.taxpayer_account(
            full_name="FRANK COOWNER",
            date_of_birth="1960-07-04",
            ssn_last4="1111",
            mailing_address_normalized="202 CEDAR LN EASTWICK ST 10002",
        ),
        ownership={
            "ownership_pct_bps": 3333,
            "deed_recorded_date": "2019-01-01",
            "occupancy_start_date": "2019-01-01",
        },
    )
    world["case"] = fx.open_fraud_case(
        api,
        world["grant_id"],
        world["taxpayer"]["id"],
        improper_start_tax_year=2024,
        improper_end_tax_year=2026,
        assessment_tax_year=2026,
    )
    return world


def test_each_improper_year_is_rounded_before_the_components_are_summed(api):
    """PRD §3.8: "computes three components for each year, in this pinned order and
    with each rounded to whole cents *before* anything is summed. That year's back
    tax is the grant's `benefit_amount_cents` as stored at substantiation,
    multiplied by the county mill rate of 125 basis points, divided by ten thousand,
    rounded half up. That year's penalty is derived from the **already rounded**
    back tax of that same year ... Deriving the penalty from an unrounded back tax,
    or summing exact products and rounding once at the end, produces cent-level
    differences and is wrong."

    Design: Difficulty/combinatorial_formula/recovery_assessment_rounds_per_year_before_summing
    """
    world = _prorated_grant_under_investigation(api)
    assert_money(world["grant"], "benefit_amount_cents", 3333000)

    substantiated = validate_success(
        api.decide_fraud_case(
            world["case"]["id"],
            f.fraud_decision("SUBSTANTIATE", "Three improper years established."),
            INVESTIGATOR,
        )
    )

    assert substantiated["adjudication_risk_score"] == 70, (
        "the replayed log must clear the threshold of 60, got "
        f"{substantiated['adjudication_risk_score']}"
    )
    # 41663 a year over 2024, 2025 and 2026; 4166 of penalty a year; interest of
    # 4166 for 2024, 2083 for 2025 and nothing for the assessment year itself.
    assert_recovery_assessment(
        substantiated,
        back_tax_cents=124989,
        penalty_cents=12498,
        interest_cents=6249,
        total_assessed_cents=143736,
        recovery_paid_cents=0,
    )
    assert substantiated["back_tax_cents"] != 124988, (
        "summing the exact products and rounding once would yield 124988; rounding "
        f"each year first yields 124989, got {substantiated['back_tax_cents']}"
    )
    assert substantiated["penalty_cents"] != 12499, (
        "deriving the penalty from the unrounded back tax would yield 12499, got "
        f"{substantiated['penalty_cents']}"
    )


def test_substantiation_freezes_the_ledger_revokes_the_grant_and_bars_the_account(api):
    """PRD §3.8: "**Substantiating** a case stamps `substantiated_by_user_id` with
    the acting `X-User-ID` ... The recovery ledger opens: ... `recovery_status`
    advances from `NONE` to `ASSESSED`. The alleged grant — already `SUSPENDED`
    since the case was opened — is forced to `REVOKED`. The revoked grant re-runs
    the parcel value decomposition ... The taxpayer's account `status` becomes
    `BARRED`."

    Design: Difficulty/combinatorial_formula/recovery_assessment_rounds_per_year_before_summing
    """
    world = _prorated_grant_under_investigation(api)

    substantiated = validate_success(
        api.decide_fraud_case(
            world["case"]["id"],
            f.fraud_decision("SUBSTANTIATE", "Three improper years established."),
            INVESTIGATOR,
        )
    )

    assert substantiated["investigation_status"] == "SUBSTANTIATED", (
        f"the adjudication axis advances, got {substantiated['investigation_status']}"
    )
    assert substantiated["recovery_status"] == "ASSESSED", (
        f"the money axis opens at ASSESSED, got {substantiated['recovery_status']}"
    )
    assert substantiated["substantiated_by_user_id"] == INVESTIGATOR_USER_ID, (
        "the substantiating investigator is stamped for the later duty bar, got "
        f"{substantiated['substantiated_by_user_id']}"
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(grant, benefit_status="REVOKED", applied_exempt_value_cents=0)

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=62400000,
        exempt_value_cents=0,
        taxable_value_cents=62400000,
        exemption_status="UNEXEMPTED",
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="BARRED",
    )


def _assessed_case(api):
    """A substantiated case whose recovery ledger is frozen at 246750.

    The grant's benefit of 8400000 gives a back tax of 105000 for each of the two
    improper years 2024 and 2025, a penalty of 10500 a year, and interest of 10500
    for 2024 and 5250 for 2025 against an assessment year of 2026.
    """
    world = fx.mismatching_check_world(api)
    world["case"] = fx.substantiated_fraud_case(
        api, world["grant_id"], world["taxpayer"]["id"]
    )
    return world


def test_a_partial_payment_advances_the_money_axis_and_leaves_guilt_alone(api):
    """PRD §3.8: "The two advance on separate axes on the same row: a substantiated
    case keeps that `investigation_status` forever while its `recovery_status` walks
    from `ASSESSED` through `PARTIALLY_PAID` to `PAID`". PRD §3.8 adds: "A payment
    below the outstanding balance raises `recovery_paid_cents` by the `amount_cents`
    paid and leaves `recovery_status` at `PARTIALLY_PAID` ... and
    `investigation_status` is untouched."

    Design: Difficulty/non_linear_state_machine/fraud_case_recovery_dimension_advances_while_investigation_status_frozen
    """
    world = _assessed_case(api)
    assert_recovery_assessment(
        world["case"],
        back_tax_cents=210000,
        penalty_cents=21000,
        interest_cents=15750,
        total_assessed_cents=246750,
    )

    paid = fx.pay_recovery(api, world["case"]["id"], 100000, "First installment")

    assert_recovery_assessment(
        paid, total_assessed_cents=246750, recovery_paid_cents=100000
    )
    assert paid["recovery_status"] == "PARTIALLY_PAID", (
        f"an installment leaves the balance open, got {paid['recovery_status']}"
    )
    assert paid["investigation_status"] == "SUBSTANTIATED", (
        "collecting money never touches the adjudication axis, got "
        f"{paid['investigation_status']}"
    )
    assert paid["adjudication_risk_score"] == 70, (
        "the replayed score belongs to the adjudication axis and does not move, got "
        f"{paid['adjudication_risk_score']}"
    )


def test_the_installment_moves_the_taxpayer_ledger_and_nothing_else(api):
    """PRD §3.8: "Either way the taxpayer's `lifetime_recovery_collected_cents`
    rises by the same amount and `net_relief_cents` is re-derived". PRD §3.8 also
    fixes the grant's fate at substantiation, not at collection: "The alleged
    grant — already `SUSPENDED` since the case was opened — is forced to
    `REVOKED`."

    Design: Difficulty/non_linear_state_machine/fraud_case_recovery_dimension_advances_while_investigation_status_frozen
    """
    world = _assessed_case(api)

    fx.pay_recovery(api, world["case"]["id"], 100000, "First installment")

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=100000,
        net_relief_cents=-100000,
        status="BARRED",
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(grant, benefit_status="REVOKED", applied_exempt_value_cents=0)


def test_a_payment_beyond_the_outstanding_balance_is_refused(api):
    """PRD §3.8: "A payment must not exceed the outstanding balance, which is
    `total_assessed_cents` less `recovery_paid_cents`; an excess is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Difficulty/compensating_invariant/abatement_restores_the_taxpayer_money_ledger_to_its_pre_assessment_value
    """
    world = _assessed_case(api)

    validate_error(
        api.fraud_recovery_action(
            world["case"]["id"],
            f.recovery_action("PAY", 300000, "Attempted overpayment"),
            RECOVERY,
        ),
        ERR_PAYMENT_EXCEEDS_BALANCE,
        expected_status=422,
    )

    case = validate_success(api.get_fraud_case(world["case"]["id"], INVESTIGATOR))
    assert_recovery_assessment(
        case, total_assessed_cents=246750, recovery_paid_cents=0
    )
    assert case["recovery_status"] == "ASSESSED", (
        f"the refused payment collects nothing, got {case['recovery_status']}"
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
    )


def test_abatement_restores_the_ledger_to_exactly_its_pre_assessment_figure(api):
    """PRD §3.8: "An **abatement** writes off the whole assessed balance:
    `recovery_status` becomes `ABATED` and `recovery_paid_cents` is reset to 0. The
    compensation is exact — the taxpayer's `lifetime_recovery_collected_cents` is
    reduced by precisely the amount previously collected on this case, and
    `net_relief_cents` is re-derived back to its pre-assessment figure." PRD §3.8
    adds: "Abatement settles money, not guilt — `investigation_status` remains
    `SUBSTANTIATED` after an abatement".

    Design: Difficulty/compensating_invariant/abatement_restores_the_taxpayer_money_ledger_to_its_pre_assessment_value
    """
    world = _assessed_case(api)

    collected = fx.pay_recovery(api, world["case"]["id"], 46750, "Partial collection")
    assert collected["recovery_status"] == "PARTIALLY_PAID", (
        f"the collection leaves a balance, got {collected['recovery_status']}"
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_recovery_collected_cents=46750,
        net_relief_cents=-46750,
    )

    abated = validate_success(
        api.fraud_recovery_action(
            world["case"]["id"],
            f.recovery_action(
                "ABATE", reason="Hardship abatement granted by the exemptions board."
            ),
            RECOVERY,
        )
    )

    assert abated["recovery_status"] == "ABATED", (
        f"the write-off closes the money axis, got {abated['recovery_status']}"
    )
    assert_recovery_assessment(
        abated, total_assessed_cents=246750, recovery_paid_cents=0
    )
    assert abated["investigation_status"] == "SUBSTANTIATED", (
        f"guilt survives the write-off, got {abated['investigation_status']}"
    )
    assert abated["adjudication_risk_score"] == 70, (
        f"the replayed score is untouched, got {abated['adjudication_risk_score']}"
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="BARRED",
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(grant, benefit_status="REVOKED")


def _approved_claim_then_investigation(api):
    """A refund already paid out, and only then an investigation into the grant.

    Nothing offsets the claim when it is adjudicated, so it settles at its full
    gross plus interest and the household ledger records the whole payout — the
    figure the later substantiation has to unwind.
    """
    world = fx.mismatching_check_world(api)
    filed = fx.pending_claim(api, world["grant_id"])
    world["claim"] = validate_success(
        api.decide_retroactive_claim(
            filed["id"],
            f.claim_decision(
                "APPROVE", "Three eligible years, no outstanding recovery."
            ),
            REVIEWER_2,
        )
    )
    world["case"] = fx.open_fraud_case(
        api, world["grant_id"], world["taxpayer"]["id"]
    )
    return world


def test_substantiation_cascades_from_the_case_down_to_the_paid_refund(api):
    """PRD §3.8: "Substantiation then cascades widely, in order. The recovery ledger
    opens ... The alleged grant ... is forced to `REVOKED`. The revoked grant re-runs
    the parcel value decomposition, rewriting `exempt_value_cents` and
    `taxable_value_cents` and incrementing the parcel's `version` by 1. Every
    `APPROVED` retroactive claim on that grant becomes `REVERSED`, which reduces the
    taxpayer's `lifetime_refund_cents` by that claim's `total_payable_cents` and
    re-derives `net_relief_cents`. The taxpayer's account `status` becomes
    `BARRED`."

    Design: Difficulty/transitive_cascade/substantiation_cascade_revokes_grant_reprices_parcel_and_reverses_approved_claim
    """
    world = _approved_claim_then_investigation(api)

    # Before the trigger the refund has been settled in full and paid.
    assert_claim_amounts(
        world["claim"],
        gross_refund_cents=315000,
        offset_applied_cents=0,
        net_refund_cents=315000,
        refund_interest_cents=25200,
        total_payable_cents=340200,
        status="APPROVED",
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=340200,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=340200,
    )

    substantiated = validate_success(
        api.decide_fraud_case(
            world["case"]["id"],
            f.fraud_decision(
                "SUBSTANTIATE",
                "Voter and postal cross-match establish two improper years.",
            ),
            INVESTIGATOR,
        )
    )

    assert_recovery_assessment(
        substantiated,
        back_tax_cents=210000,
        penalty_cents=21000,
        interest_cents=15750,
        total_assessed_cents=246750,
    )
    assert substantiated["recovery_status"] == "ASSESSED", (
        f"the recovery ledger opens, got {substantiated['recovery_status']}"
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(grant, benefit_status="REVOKED", applied_exempt_value_cents=0)

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    reversed_claim = validate_success(
        api.get_retroactive_claim(world["claim"]["id"], REVIEWER_2)
    )
    assert reversed_claim["status"] == "REVERSED", (
        f"the paid claim must be unwound, got {reversed_claim['status']}"
    )
    assert_claim_amounts(reversed_claim, total_payable_cents=340200)

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="BARRED",
    )

    rows, meta = validate_paginated(
        api.list_grant_retroactive_claims(world["grant_id"], REVIEWER_2)
    )
    assert meta["total_count"] == 1, (
        f"the grant carries exactly one claim, got {meta['total_count']}"
    )
    assert rows[0]["status"] == "REVERSED", (
        f"the grant's only claim reads REVERSED, got {rows[0]['status']}"
    )


def _certified_income_inside_the_improper_years(api):
    """A certification that a corrected revenue row certified, then substantiation.

    The revenue department first reported a contradicting figure, which the replayed
    log latches, and a later corrected row agreed with the certification and moved
    it to `CERTIFIED`; the improper interval 2024 through 2026 therefore closes over
    a certified year.
    """
    world = fx.approval_world(
        api,
        check_log="damning",
        certification={
            "certification_year": 2026,
            "recertification_due_date": "2026-12-31",
            "household_income_cents": 5000000,
            "countable_asset_cents": 1000000,
            "household_size": 2,
        },
        approve=False,
    )
    taxpayer_id = world["taxpayer"]["id"]
    fx.inject_registry(
        api,
        taxpayer_id,
        "INCOME_DOR",
        record_effective_date="2026-03-01",
        reported_income_cents=5000000,
    )
    fx.run_checks(api, world["application_id"], ["INCOME_DOR"])
    world["certification"] = fx.read_certification(
        api, taxpayer_id, world["certification"]["id"]
    )

    determined = validate_success(
        api.determine_application(
            world["application_id"],
            f.approve_determination(world["parcel"]["version"]),
            REVIEWER,
        )
    )
    world["grant_id"] = determined["resulting_grant_id"]
    world["case"] = fx.substantiated_fraud_case(
        api,
        world["grant_id"],
        taxpayer_id,
        improper_start_tax_year=2024,
        improper_end_tax_year=2026,
        assessment_tax_year=2026,
    )
    return world


def test_substantiation_revokes_a_certification_inside_the_improper_years(api):
    """PRD §3.8: "Every `CERTIFIED` income certification of that taxpayer whose
    `certification_year` falls inside the closed improper-year interval becomes
    `REVOKED`, with its `relief_tier` and `relief_multiplier_bps` preserved for
    audit rather than reset." PRD §3.3 is what certified it: "an `INCOME_DOR` check
    whose `result` is `MATCH` certifies income: the very certification the
    comparison selected moves from `PENDING` to `CERTIFIED`".

    Design: Difficulty/transitive_cascade/substantiation_cascade_revokes_grant_reprices_parcel_and_reverses_approved_claim
    """
    world = _certified_income_inside_the_improper_years(api)
    assert world["certification"]["status"] == "CERTIFIED", (
        "the corrected revenue row must certify the income before the case opens, "
        f"got {world['certification']['status']}"
    )

    # Three improper years at 105000 of back tax, 10500 of penalty each, and
    # interest of 10500 for 2024, 5250 for 2025 and nothing for 2026.
    assert_recovery_assessment(
        world["case"],
        back_tax_cents=315000,
        penalty_cents=31500,
        interest_cents=15750,
        total_assessed_cents=362250,
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "REVOKED", (
        "a certified year inside the improper interval is revoked, got "
        f"{certification['status']}"
    )
    assert certification["relief_multiplier_bps"] == world["certification"][
        "relief_multiplier_bps"
    ], (
        "the revocation preserves the multiplier for audit: "
        f"{certification['relief_multiplier_bps']} != "
        f"{world['certification']['relief_multiplier_bps']}"
    )
    assert certification["relief_tier"] == world["certification"]["relief_tier"], (
        "the revocation preserves the tier for audit: "
        f"{certification['relief_tier']} != {world['certification']['relief_tier']}"
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="BARRED",
    )


def test_clearing_a_case_gives_the_parcel_back_exactly_what_it_lost(api):
    """PRD §3.8: "**Clearing** a case compensates the suspension it caused: the
    suspended grant returns to `ACTIVE` with `suspension_reason` cleared, the parcel
    value decomposition re-runs and the parcel's `version` increments by 1, and the
    taxpayer's account returns to `GOOD_STANDING` provided no other case of theirs
    still has an open investigation. `recovery_status` stays at `NONE` — a cleared
    case never assesses anything." PRD §3.8 adds: "Either action recomputes the
    adjudication-variant score and writes it to `adjudication_risk_score`, so even a
    cleared case keeps the replayed figure for the audit record."

    Design: Corner/state_machines/clearing_a_fraud_case_restores_the_grant_and_the_parcel
    """
    world = fx.approved_homestead_world(api)
    taxpayer_id = world["taxpayer"]["id"]

    case = fx.open_fraud_case(
        api,
        world["grant_id"],
        taxpayer_id,
        improper_start_tax_year=2024,
        improper_end_tax_year=2025,
    )
    assert case["screening_risk_score"] == 0, (
        "every cross-match on this log reads MATCH, so the snapshot scores nothing, "
        f"got {case['screening_risk_score']}"
    )

    # What the parcel and the household lost the moment the case was opened.
    assert_grant(
        validate_success(api.get_grant(world["grant_id"], REVIEWER)),
        benefit_status="SUSPENDED",
        suspension_reason="FRAUD_INVESTIGATION",
        applied_exempt_value_cents=0,
    )
    suspended_parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        suspended_parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )
    assert suspended_parcel["version"] == 3, (
        "creation, approval and the suspension are three mutations, got version "
        f"{suspended_parcel['version']}"
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(taxpayer_id, CLERK)),
        status="FLAGGED",
    )

    cleared = validate_success(
        api.decide_fraud_case(
            case["id"],
            f.fraud_decision(
                "CLEAR",
                "Registry addresses agree; the referral was a data-entry artefact.",
            ),
            INVESTIGATOR_2,
        )
    )
    assert cleared["investigation_status"] == "CLEARED", (
        f"the investigation exonerates the household, got {cleared['investigation_status']}"
    )
    assert cleared["recovery_status"] == "NONE", (
        f"a cleared case raises no assessment, got {cleared['recovery_status']}"
    )
    assert cleared["adjudication_risk_score"] == 0, (
        "no check ever read MISMATCH, so the replay scores nothing either, got "
        f"{cleared['adjudication_risk_score']}"
    )
    assert_money(cleared, "total_assessed_cents", 0)

    assert_grant(
        validate_success(api.get_grant(world["grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        suspension_reason=None,
        applied_exempt_value_cents=8400000,
    )
    restored = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        restored,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert restored["version"] == suspended_parcel["version"] + 1, (
        "the restoring repricing is one further mutation, got version "
        f"{restored['version']} from {suspended_parcel['version']}"
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(taxpayer_id, CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
        status="GOOD_STANDING",
    )


def test_one_collection_request_advances_the_case_and_syncs_the_account(api):
    """PRD §3.8: "A payment below the outstanding balance raises
    `recovery_paid_cents` by the `amount_cents` paid and leaves `recovery_status` at
    `PARTIALLY_PAID` ... Either way the taxpayer's
    `lifetime_recovery_collected_cents` rises by the same amount and
    `net_relief_cents` is re-derived." PRD §2.11 fixes that derivation:
    "`net_relief_cents` is `lifetime_refund_cents` minus
    `lifetime_recovery_collected_cents`, and it is re-derived every single time
    either component changes — never stored independently, never patched by hand."

    Design: Corner/state_machines/recovery_payment_syncs_the_taxpayer_money_ledger
    """
    world = _assessed_case(api)
    taxpayer_id = world["taxpayer"]["id"]
    certification_id = world["certification"]["id"]

    before = validate_success(api.get_taxpayer_account(taxpayer_id, CLERK))
    assert_taxpayer_ledger(
        before,
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
    )

    # 100000 of the frozen 246750 assessment, in a single request.
    paid = fx.pay_recovery(
        api, world["case"]["id"], 100000, "First instalment received."
    )

    assert paid["recovery_status"] == "PARTIALLY_PAID", (
        f"the balance is still open, got {paid['recovery_status']}"
    )
    assert_recovery_assessment(
        paid, total_assessed_cents=246750, recovery_paid_cents=100000
    )
    assert paid["investigation_status"] == "SUBSTANTIATED", (
        f"the guilt axis is untouched by collection, got {paid['investigation_status']}"
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(taxpayer_id, CLERK)),
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=100000,
        net_relief_cents=-100000,
        status="BARRED",
    )

    # Collecting money is not an adjudication, so the revoked certification stands.
    certification = fx.read_certification(api, taxpayer_id, certification_id)
    assert certification["status"] != "CERTIFIED", (
        "the contradicted certification was never certified and collection does not "
        f"certify it, got {certification['status']}"
    )


def test_the_two_case_axes_guard_collection_adjudication_and_the_next_claim(api):
    """PRD §3.8: "In both cases the case's `recovery_status` must be `ASSESSED` or
    `PARTIALLY_PAID`; a case still at `NONE` has no assessment to act on and a case
    already `PAID` or `ABATED` has a closed balance, and either is refused with
    `ERR_RECOVERY_NOT_ASSESSED`." PRD §3.8 adds: "The case's `investigation_status`
    must still be `OPEN`, or the decision is refused with
    `ERR_CASE_ALREADY_ADJUDICATED`." PRD §3.2: "The claimant's account must not be
    `BARRED`; both `GOOD_STANDING` and `FLAGGED` accounts may submit, but a barred
    taxpayer is turned away with `ERR_TAXPAYER_BARRED`".

    Design: Corner/errors/recovery_action_before_assessment_and_second_adjudication_return_4xx
    """
    world = fx.mismatching_check_world(api)
    taxpayer_id = world["taxpayer"]["id"]
    case = fx.open_fraud_case(
        api,
        world["grant_id"],
        taxpayer_id,
        improper_start_tax_year=2024,
        improper_end_tax_year=2025,
    )
    assert case["screening_risk_score"] == 35, (
        f"the corrected voter row keeps the snapshot at 35, got {case['screening_risk_score']}"
    )
    assert case["recovery_status"] == "NONE", (
        f"opening a case assesses nothing, got {case['recovery_status']}"
    )

    # The money axis is still at NONE even though the investigation is open.
    validate_error(
        api.fraud_recovery_action(
            case["id"], f.recovery_action("PAY", 100000), RECOVERY
        ),
        ERR_RECOVERY_NOT_ASSESSED,
        expected_status=409,
    )
    untouched = validate_success(api.get_fraud_case(case["id"], INVESTIGATOR))
    assert_money(untouched, "recovery_paid_cents", 0)
    assert untouched["recovery_status"] == "NONE", (
        f"the refused payment leaves the money axis alone, got {untouched['recovery_status']}"
    )

    substantiated = validate_success(
        api.decide_fraud_case(
            case["id"],
            f.fraud_decision(
                "SUBSTANTIATE",
                "Registration and postal records place the claimant elsewhere.",
            ),
            INVESTIGATOR,
        )
    )
    assert substantiated["adjudication_risk_score"] == 70, (
        f"the replay latches the corrected mismatch, got {substantiated['adjudication_risk_score']}"
    )
    assert substantiated["investigation_status"] == "SUBSTANTIATED", (
        f"the adjudication axis advances, got {substantiated['investigation_status']}"
    )
    assert substantiated["recovery_status"] == "ASSESSED", (
        f"and the money axis opens, got {substantiated['recovery_status']}"
    )
    # Two improper years at 105000 back tax each, 1000 bps penalty on each rounded
    # back tax, and 500 bps for two years then one year of simple accrual.
    assert_recovery_assessment(
        substantiated,
        back_tax_cents=210000,
        penalty_cents=21000,
        interest_cents=15750,
        total_assessed_cents=246750,
        recovery_paid_cents=0,
    )

    # A second adjudication, even by a different investigator, is refused.
    validate_error(
        api.decide_fraud_case(
            case["id"],
            f.fraud_decision("SUBSTANTIATE", "Duplicate adjudication attempt."),
            INVESTIGATOR_2,
        ),
        ERR_CASE_ALREADY_ADJUDICATED,
        expected_status=409,
    )
    adjudicated = validate_success(api.get_fraud_case(case["id"], INVESTIGATOR))
    assert adjudicated["substantiated_by_user_id"] == INVESTIGATOR_USER_ID, (
        "the first investigator remains the one who substantiated it, got "
        f"{adjudicated['substantiated_by_user_id']!r}"
    )

    account = validate_success(api.get_taxpayer_account(taxpayer_id, CLERK))
    assert account["status"] == "BARRED", (
        f"a substantiated finding bars the household, got {account['status']}"
    )
    assert_grant(
        validate_success(api.get_grant(world["grant_id"], REVIEWER)),
        benefit_status="REVOKED",
        applied_exempt_value_cents=0,
    )
    assert_parcel_decomposition(
        validate_success(api.get_parcel(world["parcel"]["id"], ANALYST)),
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    # Keying the next year's claim is allowed; submitting it is not.
    next_year = validate_success(
        api.create_application(
            f.application(
                world["parcel"]["id"],
                taxpayer_id,
                world["program"]["id"],
                tax_year=2027,
            ),
            CLERK,
        ),
        expected_status=201,
    )
    validate_error(
        api.submit_application(next_year["id"], CLERK),
        ERR_TAXPAYER_BARRED,
        expected_status=403,
    )
    refused = validate_success(api.get_application(next_year["id"], CLERK))
    assert refused["status"] == "DRAFT", (
        f"the barred submission leaves the claim in draft, got {refused['status']}"
    )


def _corrected_voter_and_income_lie_world(api):
    """A grant approved over a corrected address mismatch and a standing income one.

    The voter row first sits at a foreign address and is cross-matched there, the
    revenue row contradicts the certification, and only then is a corrected voter
    row injected and re-checked, so the latest word on both gating sources reads
    ``MATCH`` while the log still remembers the address lie. No postal row exists
    at all, which is the third factor the case will later gain.
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    fx.add_ownership(api, parcel["id"], taxpayer["id"])
    certification = fx.create_certification(
        api,
        taxpayer["id"],
        certification_year=2026,
        household_income_cents=5000000,
        countable_asset_cents=2000000,
        household_size=2,
        recertification_due_date="2027-06-30",
    )
    fx.inject_registry(
        api, taxpayer["id"], "VOTER_REGISTRY", address_normalized=ADDR_ELM
    )
    fx.inject_registry(api, taxpayer["id"], "DEED_REGISTRY")
    fx.inject_registry(
        api,
        taxpayer["id"],
        "INCOME_DOR",
        record_effective_date="2026-01-15",
        reported_income_cents=9000000,
    )
    application = fx.submitted_application(
        api, parcel["id"], taxpayer["id"], program["id"]
    )
    address_lie, income_lie = fx.run_checks(
        api, application["id"], ["VOTER_REGISTRY", "INCOME_DOR"]
    )
    fx.inject_registry(
        api,
        taxpayer["id"],
        "VOTER_REGISTRY",
        record_effective_date="2026-02-10",
    )
    corrected, _deed = fx.run_checks(
        api, application["id"], ["VOTER_REGISTRY", "DEED_REGISTRY"]
    )
    determined = validate_success(
        api.determine_application(
            application["id"], f.approve_determination(parcel["version"]), REVIEWER_2
        )
    )
    return {
        "program": program,
        "parcel": parcel,
        "taxpayer": taxpayer,
        "certification": certification,
        "application": application,
        "address_lie": address_lie,
        "income_lie": income_lie,
        "corrected": corrected,
        "grant_id": determined["resulting_grant_id"],
    }


def test_a_two_factor_replay_is_one_point_short_and_a_third_factor_carries_it(api):
    """PRD §3.8: "a registration address mismatch against the voter registry or the
    DMV carries 3500 basis points; multiple concurrent homestead claims by the same
    taxpayer on distinct parcels carry 3000; a postal forwarding order carries 1500;
    and income under-reporting against the revenue department record carries 2000."
    PRD §3.8: "The screening variant, run at case opening, collapses the log to the
    latest check per source ... The adjudication variant, run at case decision,
    instead walks every check ever recorded in `checked_at` ascending order and
    latches a mismatch permanently". PRD §3.8: "Substantiation additionally demands
    that the replayed score be at least the substantiation threshold of 60 — below
    that the request is refused with `ERR_RISK_SCORE_BELOW_THRESHOLD`".

    Design: Corner/cross_cutting_complexity_layers/substantiation_risk_threshold_rejects_at_fifty_five_and_passes_at_seventy
    """
    world = _corrected_voter_and_income_lie_world(api)
    taxpayer_id = world["taxpayer"]["id"]
    grant_id = world["grant_id"]
    assert world["address_lie"]["result"] == "MISMATCH", (
        f"the first voter cross-match found a foreign address, got {world['address_lie']['result']}"
    )
    assert world["income_lie"]["result"] == "MISMATCH", (
        "5000000 certified against 9000000 reported is an under-report, got "
        f"{world['income_lie']['result']}"
    )
    assert world["corrected"]["result"] == "MATCH", (
        f"the corrected voter row agrees with the claim, got {world['corrected']['result']}"
    )

    # The snapshot believes the latest word on each source: only the income lie
    # still stands, so 2000 * 100 / 10000 is 20.
    case = fx.open_fraud_case(api, grant_id, taxpayer_id)
    assert case["screening_risk_score"] == 20, (
        "the corrected address mismatch is hidden behind the later match, got "
        f"{case['screening_risk_score']}"
    )
    assert case["adjudication_risk_score"] == 0, (
        f"nothing has been replayed yet, got {case['adjudication_risk_score']!r}"
    )

    # The replay latches the address lie, reaching (3500 + 2000) * 100 / 10000,
    # which is one point short of the threshold.
    validate_error(
        api.decide_fraud_case(
            case["id"], f.fraud_decision("SUBSTANTIATE"), INVESTIGATOR
        ),
        ERR_RISK_SCORE_BELOW_THRESHOLD,
        expected_status=422,
    )

    after_refusal = validate_success(api.get_fraud_case(case["id"], INVESTIGATOR))
    assert after_refusal["investigation_status"] == "OPEN", (
        f"the refused adjudication decided nothing, got {after_refusal['investigation_status']}"
    )
    assert after_refusal["recovery_status"] == "NONE", (
        f"and assessed nothing, got {after_refusal['recovery_status']}"
    )
    assert_money(after_refusal, "total_assessed_cents", 0)
    assert after_refusal["substantiated_by_user_id"] is None, (
        f"and stamped nobody, got {after_refusal['substantiated_by_user_id']!r}"
    )
    assert_grant(
        validate_success(api.get_grant(grant_id, REVIEWER)),
        benefit_status="SUSPENDED",
        suspension_reason="FRAUD_INVESTIGATION",
        benefit_amount_cents=8400000,
    )

    # One postal forwarding order is worth the missing points.
    fx.inject_registry(
        api,
        taxpayer_id,
        "USPS_NCOA",
        record_effective_date="2026-03-01",
        address_normalized=ADDR_ELM,
    )
    postal = fx.run_checks(api, world["application"]["id"], ["USPS_NCOA"])[0]
    assert postal["result"] == "MISMATCH", (
        f"a forwarding order away from the situs address is a mismatch, got {postal['result']}"
    )

    substantiated = validate_success(
        api.decide_fraud_case(
            case["id"], f.fraud_decision("SUBSTANTIATE"), INVESTIGATOR
        )
    )
    assert substantiated["adjudication_risk_score"] == 70, (
        "(3500 + 1500 + 2000) * 100 / 10000 clears the threshold, got "
        f"{substantiated['adjudication_risk_score']}"
    )
    assert substantiated["investigation_status"] == "SUBSTANTIATED", (
        f"the second attempt is honoured, got {substantiated['investigation_status']}"
    )
    assert substantiated["substantiated_by_user_id"] == INVESTIGATOR_USER_ID, (
        f"the acting investigator is stamped, got {substantiated['substantiated_by_user_id']!r}"
    )
    assert substantiated["screening_risk_score"] == 20, (
        "the snapshot taken at opening is not rewritten by the replay, got "
        f"{substantiated['screening_risk_score']}"
    )
    assert_recovery_assessment(
        substantiated,
        back_tax_cents=210000,
        penalty_cents=21000,
        interest_cents=15750,
        total_assessed_cents=246750,
        recovery_paid_cents=0,
    )
    assert substantiated["recovery_status"] == "ASSESSED", (
        f"substantiation raises the assessment, got {substantiated['recovery_status']}"
    )

    assert_grant(
        validate_success(api.get_grant(grant_id, REVIEWER)),
        benefit_status="REVOKED",
        applied_exempt_value_cents=0,
    )
    account = validate_success(api.get_taxpayer_account(taxpayer_id, CLERK))
    assert account["status"] == "BARRED", (
        f"a substantiated case bars the household, got {account['status']}"
    )
    certification = fx.read_certification(
        api, taxpayer_id, world["certification"]["id"]
    )
    assert certification["status"] == "PENDING", (
        "the income cross-match never matched, so the certification was never "
        f"certified: got {certification['status']}"
    )
