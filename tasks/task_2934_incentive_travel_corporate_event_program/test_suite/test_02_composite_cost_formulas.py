"""Composite cost formulas: committed cost, air cost, full gross-up (PRD §3.2, §3.7, §3.9)."""
from test_helpers import *  # noqa: F401,F403

# ─── Shared scenario literals (PRD §3.2 worked example, basis 431757) ─────────

LISBON_PROGRAM = {
    "name": "FY26 Presidents Circle",
    "fiscal_year": 2026,
    "qualification_metric": "NET_REVENUE_CENTS",
    "sales_period_start": "2026-01-01T00:00:00Z",
    "sales_period_end": "2026-06-30T00:00:00Z",
    "budget_total_cents": 5_000_000,
}

PLATINUM_TIER = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150_000,
    "service_load_bp": 1275,
}

GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150_000_000,
    "budget_per_qualifier_cents": 1_600_000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40_000,
    "service_load_bp": 800,
}

LISBON_DESTINATION = {
    "city": "Lisbon",
    "country_code": "PT",
    "per_person_cost_cents": 431_757,
    "risk_score": 35,
    "air_gateway_code": "LIS",
}

SEVILLE_DESTINATION = {
    "city": "Seville",
    "country_code": "ES",
    "per_person_cost_cents": 388_000,
    "risk_score": 28,
    "air_gateway_code": "SVQ",
}

LISBON_CONTRACT = {
    "supplier_name": "Estoril Palace",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38_500,
    "attrition_allowance_bp": 2000,
    "force_majeure_clause": "STANDARD",
    "exposure_basis": "ATTRITION_BASIS",
}

STAY_ARRIVAL = "2026-11-08T00:00:00Z"
STAY_DEPARTURE = "2026-11-13T00:00:00Z"


def _build_lisbon_contracted(with_deposit_schedule=False):
    """CONTRACTED program: per_person_cost_basis_cents == 431757.

    Qualifiers A (PLATINUM, guest_count 1) and B (GOLD, guest_count 0) are both
    adjudicated while the basis is still 0, so the contract-execution cascade of
    PRD §3.4 level 4 recomputes their committed cost against the known basis.
    """
    program = create_program(**LISBON_PROGRAM)
    platinum = create_award_tier(program["id"], **PLATINUM_TIER)
    gold = create_award_tier(program["id"], **GOLD_TIER)
    lisbon = create_destination(program["id"], **LISBON_DESTINATION)
    seville = create_destination(program["id"], **SEVILLE_DESTINATION)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])
    qualifier_a = create_qualifier(
        program["id"], employee_code="S-1001", full_name="Ana Reyes",
        baseline_metric=180_000_000, actual_metric=260_000_000, guest_count=1,
    )
    review_qualifier(qualifier_a["id"])
    qualifier_b = create_qualifier(
        program["id"], employee_code="S-2001", full_name="Ben Ortiz",
        baseline_metric=120_000_000, actual_metric=155_000_000, guest_count=0,
    )
    review_qualifier(qualifier_b["id"])
    advance_program(program["id"], "SOURCING")
    contract = create_contract(program["id"], lisbon["id"], **LISBON_CONTRACT)
    if with_deposit_schedule:
        create_milestone(contract["id"], sequence=1, due_at="2026-08-15T00:00:00Z",
                         amount_cents=577_500, refundable_bp=10000)
        create_milestone(contract["id"], sequence=2, due_at="2026-09-15T00:00:00Z",
                         amount_cents=577_500, refundable_bp=5000)
        create_milestone(contract["id"], sequence=3, due_at="2026-10-15T00:00:00Z",
                         amount_cents=1_155_000, refundable_bp=0)
    propose_contract(contract["id"])
    execute_contract(contract["id"])
    return {
        "program": read_program(program["id"]),
        "platinum": platinum,
        "gold": gold,
        "destination": lisbon,
        "loser_destination": seville,
        "contract": read_contract(contract["id"]),
        "qualifier_a": read_qualifier(qualifier_a["id"]),
        "qualifier_b": read_qualifier(qualifier_b["id"]),
    }


def _build_lisbon_registration_open():
    """The same program walked on to REGISTRATION_OPEN with both winners NOTIFIED."""
    base = _build_lisbon_contracted()
    notify_qualifiers(base["program"]["id"])
    lock_gross_up_policy(base["program"]["id"], "FULL_GROSS_UP")
    advance_program(base["program"]["id"], "REGISTRATION_OPEN")
    base["program"] = read_program(base["program"]["id"])
    base["qualifier_a"] = read_qualifier(base["qualifier_a"]["id"])
    base["qualifier_b"] = read_qualifier(base["qualifier_b"]["id"])
    return base


def _invited_seat(base, qualifier):
    """A WINNER seat left INVITED, so the air ledger never enters the budget rollup."""
    return create_registration(
        qualifier["id"],
        program_id=base["program"]["id"],
        arrival_date=STAY_ARRIVAL,
        departure_date=STAY_DEPARTURE,
        rooms=1,
    )


# ─── committed_cost_rounds_each_rate_component_before_summation ───────────────

def test_committed_cost_rounds_each_of_three_components_before_summing():
    """Review stamps 921765: each rate component is rounded before the sum.

    PRD §3.2: "**The evaluation order is pinned**: each of the three rate-driven
    components is rounded to a whole cent *before* anything is summed."

    Design: Difficulty/combinatorial_formula/committed_cost_rounds_each_rate_component_before_summation
    """
    base = _build_lisbon_contracted(with_deposit_schedule=True)
    assert base["program"]["per_person_cost_basis_cents"] == 431757

    qualifier_c = create_qualifier(
        base["program"]["id"], employee_code="S-3001", full_name="Cara Lund",
        baseline_metric=200_000_000, actual_metric=300_000_000, guest_count=1,
    )
    reviewed = review_qualifier(qualifier_c["id"])
    assert_qualifier(reviewed)

    assert reviewed["assigned_tier_id"] == base["platinum"]["id"]
    assert reviewed["award_status"] == "QUALIFIED"
    # winner 486806 = round_half_up(431757 * 11275 / 10000)
    # guest  269848 = round_half_up(431757 * 6250 / 10000), applied once (guest_count 1)
    # gratuity 15111 = round_half_up(431757 * 350 / 10000)
    assert reviewed["committed_cost_cents"] == 486806 + 269848 + 15111 + 150_000
    assert reviewed["committed_cost_cents"] == 921765


def test_committed_cost_rejects_the_single_composite_rate_rounding():
    """921765, never the 921766 produced by one composite rate rounded once.

    PRD §3.2: "Adding the three rates together into one composite basis-point
    figure and rounding once at the end yields a different number and is wrong —
    with a per-person basis of 431757 cents, a `service_load_bp` of 1275 and a
    `guest_count` of 1, the pinned order gives 921765 cents while the naive
    single-rounding gives 921766."

    Design: Difficulty/combinatorial_formula/committed_cost_rounds_each_rate_component_before_summation
    """
    base = _build_lisbon_contracted()

    qualifier_c = create_qualifier(
        base["program"]["id"], employee_code="S-3001", full_name="Cara Lund",
        baseline_metric=200_000_000, actual_metric=300_000_000, guest_count=1,
    )
    reviewed = review_qualifier(qualifier_c["id"])

    pinned_component_order = 921765
    naive_single_composite_rate = 921766  # round_half_up(431757 * 17875 / 10000) + 150000
    assert reviewed["committed_cost_cents"] == pinned_component_order
    assert reviewed["committed_cost_cents"] != naive_single_composite_rate

    # The stamp survives the read, and the tier budget ceiling was cleared
    # against the pinned figure rather than the naive one.
    stored = read_qualifier(qualifier_c["id"])
    assert stored["committed_cost_cents"] == pinned_component_order
    assert stored["committed_cost_cents"] <= base["platinum"]["budget_per_qualifier_cents"]


def test_budget_rollup_sums_per_component_rounded_award_commitments():
    """The award side of the rollup is 2364939, not a re-rounded aggregate.

    PRD §3.7: "Its award side is the sum of `committed_cost_cents` over the
    program's qualifiers whose `award_status` is `QUALIFIED`, `NOTIFIED`,
    `REGISTERED` or `TRAVELLED`; qualifiers who are `PENDING_REVIEW`,
    `DISQUALIFIED` or `WITHDRAWN` are excluded."

    Design: Difficulty/combinatorial_formula/committed_cost_rounds_each_rate_component_before_summation
    """
    base = _build_lisbon_contracted()

    # Level 4 of the execution cascade recomputed both pre-existing winners
    # against the now-known 431757 basis.
    assert base["qualifier_a"]["committed_cost_cents"] == 921765
    assert base["qualifier_b"]["committed_cost_cents"] == 521409

    qualifier_c = create_qualifier(
        base["program"]["id"], employee_code="S-3001", full_name="Cara Lund",
        baseline_metric=200_000_000, actual_metric=300_000_000, guest_count=1,
    )
    review_qualifier(qualifier_c["id"])

    program = read_program(base["program"]["id"])
    assert_program(program)
    assert program["committed_budget_cents"] == 921765 + 921765 + 521409
    assert program["committed_budget_cents"] == 2364939
    assert program["budget_headroom_cents"] == 2635061
    assert program["budget_posture"] == "OK"  # utilization_bp 4729
    assert_budget_conserved(program)


# ─── air_cost_combines_nested_upgrade_clamps_deviation_step_and_capped_escalator ──

def test_air_cost_composes_upgrade_deviation_and_capped_change_fee():
    """cost_cents 191100 = 77000 upgrade + 28500 deviation + 85600 capped fees.

    PRD §3.7: "Three figures are derived from those inputs against the tier
    stamped on the seat's qualifier, and their sum is the seat's `cost_cents`."

    Design: Difficulty/combinatorial_formula/air_cost_combines_nested_upgrade_clamps_deviation_step_and_capped_escalator
    """
    base = _build_lisbon_registration_open()
    seat = _invited_seat(base, base["qualifier_b"])

    air_action(seat["id"], "REQUEST", cabin_class="BUSINESS", deviation_pre_days=3,
               deviation_post_days=2, base_fare_cents=214_000)
    air_action(seat["id"], "TICKET")
    for _ in range(4):
        air_action(seat["id"], "CHANGE")
        air_action(seat["id"], "TICKET")

    reticketed = read_registration(seat["id"])
    assert_registration(reticketed)
    assert reticketed["air_status"] == "TICKETED"
    assert reticketed["air_change_count"] == 4
    # inner max(0, 165000 - 48000) == 117000, outer max(0, 117000 - 40000) == 77000
    assert reticketed["air_upgrade_cost_cents"] == 77000
    # max(0, (3 + 2) - 2) == 3 chargeable days at 9500
    assert reticketed["air_deviation_fee_cents"] == 28500
    # round_half_up(214000 * 4000 / 10000) == 85600, the cap on the accumulated total
    assert reticketed["air_change_fee_total_cents"] == 85600
    assert reticketed["cost_cents"] == 77000 + 28500 + 85600
    assert reticketed["cost_cents"] == 191100

    # The seat is INVITED, so its air cost has not joined the budget rollup.
    program = read_program(base["program"]["id"])
    assert reticketed["attendance_status"] == "INVITED"
    assert program["committed_budget_cents"] == 1443174
    assert_budget_conserved(program)


def test_air_upgrade_cost_applies_both_clamps_and_never_credits_the_winner():
    """A cabin below entitlement earns no credit and an unused allowance no rebate.

    PRD §3.7: "`air_upgrade_cost_cents` is then that billable step less the tier's
    `upgrade_allowance_cents`, again floored at 0 so that an unused allowance
    produces no rebate. Both clamps are required; either one alone yields a
    negative figure somewhere."

    Design: Difficulty/combinatorial_formula/air_cost_combines_nested_upgrade_clamps_deviation_step_and_capped_escalator
    """
    base = _build_lisbon_registration_open()

    # PLATINUM entitles BUSINESS (165000); flying ECONOMY (0) is a negative step.
    platinum_seat = _invited_seat(base, base["qualifier_a"])
    air_action(platinum_seat["id"], "REQUEST", cabin_class="ECONOMY",
               deviation_pre_days=0, deviation_post_days=0, base_fare_cents=214_000)
    air_action(platinum_seat["id"], "TICKET")
    flown_below = read_registration(platinum_seat["id"])
    assert flown_below["air_cabin_class"] == "ECONOMY"
    assert flown_below["air_upgrade_cost_cents"] == 0  # inner max(0, 0 - 165000)
    assert flown_below["cost_cents"] == 0

    # GOLD entitles PREMIUM_ECONOMY, so the billable step is 0 while the tier
    # still carries a 40000 allowance: the outer clamp must not pay it back.
    gold_seat = _invited_seat(base, base["qualifier_b"])
    air_action(gold_seat["id"], "REQUEST", cabin_class="PREMIUM_ECONOMY",
               deviation_pre_days=0, deviation_post_days=0, base_fare_cents=214_000)
    air_action(gold_seat["id"], "TICKET")
    at_entitlement = read_registration(gold_seat["id"])
    assert at_entitlement["air_upgrade_cost_cents"] == 0  # outer max(0, 0 - 40000)
    assert at_entitlement["cost_cents"] == 0


def test_air_deviation_fee_charges_only_days_beyond_the_two_free_ones():
    """Two deviation days cost nothing; five cost three days at 9500.

    PRD §3.7: "The **deviation surcharge** gives the first 2 deviation days away
    free. Chargeable days are the sum of `air_deviation_pre_days` and
    `air_deviation_post_days` less 2, floored at 0, and `air_deviation_fee_cents`
    is that count multiplied by 9500 cents per day."

    Design: Difficulty/combinatorial_formula/air_cost_combines_nested_upgrade_clamps_deviation_step_and_capped_escalator
    """
    base = _build_lisbon_registration_open()

    # PLATINUM winner in their entitled BUSINESS cabin: upgrade 0, so cost_cents
    # is the deviation surcharge alone. 1 + 1 == 2 days are inside the free step.
    free_seat = _invited_seat(base, base["qualifier_a"])
    air_action(free_seat["id"], "REQUEST", cabin_class="BUSINESS", deviation_pre_days=1,
               deviation_post_days=1, base_fare_cents=214_000)
    air_action(free_seat["id"], "TICKET")
    inside_free_days = read_registration(free_seat["id"])
    assert inside_free_days["air_deviation_pre_days"] == 1
    assert inside_free_days["air_deviation_post_days"] == 1
    assert inside_free_days["air_upgrade_cost_cents"] == 0
    assert inside_free_days["air_deviation_fee_cents"] == 0  # max(0, 2 - 2) == 0 days
    assert inside_free_days["cost_cents"] == 0

    # GOLD winner at their entitled cabin: 3 + 2 == 5 days, 3 of them chargeable.
    charged_seat = _invited_seat(base, base["qualifier_b"])
    air_action(charged_seat["id"], "REQUEST", cabin_class="PREMIUM_ECONOMY",
               deviation_pre_days=3, deviation_post_days=2, base_fare_cents=214_000)
    air_action(charged_seat["id"], "TICKET")
    beyond_free_days = read_registration(charged_seat["id"])
    assert beyond_free_days["air_deviation_fee_cents"] == 28500  # 3 * 9500
    assert beyond_free_days["air_deviation_fee_cents"] != 5 * 9500  # the free step applies
    assert beyond_free_days["cost_cents"] == 28500


def test_air_change_fee_cap_binds_once_on_the_accumulated_total():
    """Totals run 12500 / 31250 / 59375 / 85600 / 85600 — capped, never per round.

    PRD §3.7: "`air_change_fee_total_cents` is the smaller of the cap and the
    accumulated total, so the cap is applied **once to the accumulated total and
    never per round**. With an `air_base_fare_cents` of 214000 the cap is 85600,
    and the running totals across five loops are 12500, 31250, 59375, then 85600
    where the uncapped 101563 is clamped, and 85600 again."

    Design: Difficulty/combinatorial_formula/air_cost_combines_nested_upgrade_clamps_deviation_step_and_capped_escalator
    """
    base = _build_lisbon_registration_open()
    seat = _invited_seat(base, base["qualifier_b"])

    air_action(seat["id"], "REQUEST", cabin_class="BUSINESS", deviation_pre_days=3,
               deviation_post_days=2, base_fare_cents=214_000)
    first_issue = air_action(seat["id"], "TICKET")
    # The initial REQUESTED -> TICKETED move is not a change.
    assert first_issue["air_change_count"] == 0
    assert first_issue["air_change_fee_total_cents"] == 0
    assert first_issue["cost_cents"] == 77000 + 28500

    running_totals = []
    for _ in range(5):
        air_action(seat["id"], "CHANGE")
        air_action(seat["id"], "TICKET")
        running_totals.append(read_registration(seat["id"])["air_change_fee_total_cents"])

    assert running_totals == [12500, 31250, 59375, 85600, 85600]
    # Per-round fees 12500 / 18750 / 28125 / 42188 accumulate to 101563 uncapped.
    assert running_totals[3] != 101563
    assert running_totals[3] != 42188
    assert running_totals[4] == running_totals[3]  # a further escalation cannot exceed the cap

    final = read_registration(seat["id"])
    assert final["air_change_count"] == 5
    assert final["cost_cents"] == 77000 + 28500 + 85600
    assert final["cost_cents"] == 191100


# ─── full_gross_up_state_tier_keyed_on_pre_gross_up_award_value ────────────────

KYOTO_TIER = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 200_000,
    "service_load_bp": 1000,
}

KYOTO_DESTINATION = {
    "city": "Kyoto",
    "country_code": "JP",
    "per_person_cost_cents": 800_000,
    "risk_score": 30,
    "air_gateway_code": "KIX",
}

KYOTO_CONTRACT = {
    "supplier_name": "Kyoto Grand",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38_500,
}

KYOTO_QUALIFIER = {
    "employee_code": "S-9001",
    "full_name": "Gita Nair",
    "baseline_metric": 150_000_000,
    "actual_metric": 260_000_000,
    "guest_count": 1,
}


def _kyoto_reconciled_full_gross_up():
    """RECONCILED FULL_GROSS_UP program whose traveller carries a 1366800 base.

    committed_cost_cents is 880000 + 500000 + 28000 + 200000 == 1608000, so the
    taxable base is 1608000 - round_half_up(1608000 * 1500 / 10000) == 1366800 —
    a value that only crosses the 1500000 state-tier floor after grossing up.
    """
    return setup_reconciled_program(
        num_qualifiers=1,
        gross_up_policy="FULL_GROSS_UP",
        qualifier_specs=[dict(KYOTO_QUALIFIER)],
        registration_overrides={
            "arrival_date": STAY_ARRIVAL,
            "departure_date": STAY_DEPARTURE,
            "rooms": 1,
        },
        program_overrides={"name": "FY26 Chairman Circle", "budget_total_cents": 20_000_000},
        tier_overrides=dict(KYOTO_TIER),
        destination_overrides=dict(KYOTO_DESTINATION),
        contract_overrides=dict(KYOTO_CONTRACT),
    )


def test_full_gross_up_keys_the_state_tier_on_the_pre_gross_up_award_value():
    """A 1366800 base selects the 500 bp tier and reports 2091507.

    PRD §3.9: "`combined_rate_bp` is the sum of the federal supplemental 2200
    basis points, the social-insurance 765 basis points, and the tiered state rate
    — **and the state tier is keyed on the pre-gross-up `award_value_cents`, not
    on the grossed-up result**."

    Design: Difficulty/combinatorial_formula/full_gross_up_state_tier_keyed_on_pre_gross_up_award_value
    """
    base = _kyoto_reconciled_full_gross_up()
    assert base["qualifier"]["committed_cost_cents"] == 1608000
    assert base["qualifier"]["taxable_award_cents"] == 1366800
    assert base["qualifier"]["award_status"] == "TRAVELLED"

    report = draft_tax_report(base["qualifier"]["id"], 2026)
    assert_tax_award_report(report)

    assert report["gross_up_method"] == "FULL_GROSS_UP"
    assert report["award_value_cents"] == 1366800
    # 500 bp because 500000 <= 1366800 < 1500000
    assert report["combined_rate_bp"] == 2200 + 765 + 500
    assert report["combined_rate_bp"] == 3465
    assert report["reported_value_cents"] == 2091507  # round_half_up(1366800 * 10000 / 6535)
    assert report["gross_up_cents"] == 724707  # 2091507 - 1366800
    assert_reported_value_identity(report)

    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1608000
    assert program["budget_posture"] == "OK"  # utilization_bp 804 of 20000000


def test_full_gross_up_never_re_derives_the_state_tier_from_the_reported_figure():
    """The 2091507 result must not pull the tier up to 700 bp and report 2157537.

    PRD §3.9: "Re-deriving the state tier from the grossed-up figure is a circular
    ordering and is wrong: for an award value of 443198 cents the pinned order
    selects 300 basis points and reports 658052, whereas keying the tier on 658052
    would select 500 basis points and report 678191."

    Design: Difficulty/combinatorial_formula/full_gross_up_state_tier_keyed_on_pre_gross_up_award_value
    """
    base = _kyoto_reconciled_full_gross_up()
    report = draft_tax_report(base["qualifier"]["id"], 2026)

    # The award value sits below the 1500000 high floor; the reported value is
    # above it, so the two keyings genuinely disagree.
    assert report["award_value_cents"] == 1366800
    assert report["award_value_cents"] < 1500000
    assert report["reported_value_cents"] >= 1500000

    state_component_bp = report["combined_rate_bp"] - 2200 - 765
    assert state_component_bp == 500
    assert state_component_bp != 700
    assert report["combined_rate_bp"] != 3665  # 2200 + 765 + 700, keyed on the result
    assert report["reported_value_cents"] != 2157537  # round_half_up(1366800 * 10000 / 6335)
    assert report["gross_up_cents"] != 2157537 - 1366800

    stored = read_tax_report(report["id"])
    assert stored["combined_rate_bp"] == 3465
    assert stored["reported_value_cents"] == 2091507
    assert_reported_value_identity(stored)


def test_full_gross_up_low_state_tier_holds_for_the_prd_worked_example():
    """An award value of 443198 selects 300 bp and reports 658052, never 678191.

    PRD §3.9: "A tiered state supplemental rate underlies it: 300 basis points when
    the award value is below 500000 cents, 500 basis points when it is at least
    500000 but below 1500000 cents, and 700 basis points when it is at or above
    1500000 cents."

    Design: Difficulty/combinatorial_formula/full_gross_up_state_tier_keyed_on_pre_gross_up_award_value
    """
    # committed_cost_cents 500000 + 17500 + 3910 == 521410, whose taxable base is
    # 521410 - round_half_up(521410 * 1500 / 10000) == 521410 - 78212 == 443198.
    base = setup_reconciled_program(
        num_qualifiers=1,
        gross_up_policy="FULL_GROSS_UP",
        tier_overrides={
            "qualification_threshold": 0,
            "guest_allowance": 0,
            "air_cabin_class": "BUSINESS",
            "upgrade_allowance_cents": 3910,
            "service_load_bp": 0,
        },
        destination_overrides={"per_person_cost_cents": 500_000},
    )
    assert base["qualifier"]["committed_cost_cents"] == 521410
    assert base["qualifier"]["taxable_award_cents"] == 443198

    report = draft_tax_report(base["qualifier"]["id"], 2026)
    assert report["award_value_cents"] == 443198
    assert report["combined_rate_bp"] == 2200 + 765 + 300
    assert report["combined_rate_bp"] == 3265
    assert report["reported_value_cents"] == 658052  # round_half_up(443198 * 10000 / 6735)
    assert report["gross_up_cents"] == 214854  # 658052 - 443198
    assert_reported_value_identity(report)

    # Keying the tier on 658052 would select 500 bp and report 678191.
    assert report["combined_rate_bp"] != 3465
    assert report["reported_value_cents"] != 678191
