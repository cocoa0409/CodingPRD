"""Formulas whose evaluation order changes the answer.

The savings match rounds per entry before summing, the duration allowance pins
its consumption ratio against the base allowance, and the admission priority
score saturates at three separate points.
"""

from test_helpers import (
    assert_savings_identity,
    assert_savings_ledger_entry,
    assert_tlp_placement,
    clear_screening,
    credit_life_skills,
    fetch_placement,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    log_outreach_contact,
    request_admission,
    setup_placement_at_days_elapsed,
    setup_placement_with_deposits,
)

TLP_PROGRAM = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
AVA = {
    "legal_first_name": "Ava",
    "legal_last_name": "Reyes",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}
MONTHLY_INCOME_CENTS = 120000


# ─── Instance: the savings match rounds per entry before summing ───


def _three_ten_ten_deposits():
    """A placement at a 2500 basis-point match rate carrying three deposits of
    1010 cents each, posted one at a time."""
    return setup_placement_with_deposits(
        [1010, 1010, 1010],
        documented_monthly_income_cents=MONTHLY_INCOME_CENTS,
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(AVA),
    )


def test_each_savings_entry_rounds_its_own_match_half_up(api):
    """PRD §3.8: "`match_component_cents` is the per-entry program match: for a
    `DEPOSIT` it is the entry's `amount_cents` multiplied by the program's
    `savings_match_rate_bp`, divided by 10000 and rounded **half up** to whole
    cents; for a `REVERSAL` it is the exact negation of that same quantity; and
    for a `WITHDRAWAL` it is 0."
    PRD §3.8: "`balance_after_cents` is the placement's `savings_balance_cents` as
    it stands immediately after this entry posted."

    Design: Difficulty/combinatorial_formula/savings_match_rounds_per_entry_before_summing
    """
    setup = _three_ten_ten_deposits()
    entries = setup["entries"]

    assert len(entries) == 3, f"Expected three posted deposits, got {len(entries)}"
    for index, entry in enumerate(entries, start=1):
        assert_savings_ledger_entry(entry)
        assert entry["match_component_cents"] == 253, (
            "1010 cents at 2500 basis points is 252.5 cents, which rounds half up "
            f"to 253 on entry {index}, got {entry['match_component_cents']}"
        )
        assert entry["signed_amount_cents"] == 1010, (
            f"a deposit carries its positive magnitude, got {entry['signed_amount_cents']}"
        )
    assert [entry["balance_after_cents"] for entry in entries] == [1263, 2526, 3789], (
        "the running balance is 1263, 2526 and 3789 cents, got "
        f"{[entry['balance_after_cents'] for entry in entries]}"
    )


def test_placement_match_total_sums_rounded_per_entry_components(api):
    """PRD §3.8: "**The rounding order is pinned and it is the crux of the
    calculation**: each entry's match is rounded to whole cents *first*, and only
    then are the per-entry matches summed."
    PRD §3.8: "with a match rate of 2500 basis points and three deposits of 1010
    cents each, the pinned per-entry order yields 253 plus 253 plus 253 for a total
    of 759 cents, while the rejected order yields a single rounding of 757.5 to 758
    cents."
    PRD §3.8: "The placement's `savings_balance_cents` is the sum of
    `signed_amount_cents` over every entry plus the capped `match_awarded_cents` —
    that identity is the conserved quantity of the account and must hold after
    every posting."

    Design: Difficulty/combinatorial_formula/savings_match_rounds_per_entry_before_summing
    """
    setup = _three_ten_ten_deposits()
    placement = setup["placement"]

    assert_tlp_placement(placement)
    assert placement["match_awarded_cents"] == 759, (
        "three per-entry matches of 253 sum to 759 cents; 758 is the rejected "
        f"sum-then-round order, got {placement['match_awarded_cents']}"
    )
    assert placement["savings_balance_cents"] == 3789, (
        "3030 deposited cents plus 759 matched cents is 3789, got "
        f"{placement['savings_balance_cents']}"
    )
    assert_savings_identity(placement, setup["entries"])


def test_deposits_accumulate_onto_the_youth_lifetime_figure(api):
    """PRD §3.8: "Posting an entry also recomputes the youth's
    `lifetime_savings_deposited_cents`, which is the sum of `amount_cents` over the
    youth's `DEPOSIT` entries minus the sum of `amount_cents` over the youth's
    `REVERSAL` entries, taken across every placement that youth has ever held; and
    it increments the placement's `version` by one."

    Design: Difficulty/combinatorial_formula/savings_match_rounds_per_entry_before_summing
    """
    setup = _three_ten_ten_deposits()

    youth = fetch_youth(setup["youth"]["id"])
    assert youth["lifetime_savings_deposited_cents"] == 3030, (
        "three deposits of 1010 cents accumulate to 3030 cents with no match "
        f"included, got {youth['lifetime_savings_deposited_cents']}"
    )
    placement = fetch_placement(setup["placement"]["id"])
    assert placement["version"] >= 4, (
        "the placement's version starts at 1 and rises by one per posting, so "
        f"three postings leave it at 4 or more, got {placement['version']}"
    )


# ─── Instance: the duration allowance divides by the base allowance only ───


def _placement_at_420_days():
    """A placement whose base allowance is 540 days, read 420 days after it was
    opened."""
    return setup_placement_at_days_elapsed(
        420,
        documented_monthly_income_cents=MONTHLY_INCOME_CENTS,
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(AVA),
    )


def test_consumed_ratio_divides_elapsed_days_by_the_base_allowance(api):
    """PRD §3.7: "Step one computes `consumed_ratio_bp` as `days_elapsed`
    multiplied by 10000, divided by `base_allowance_days`, floored to whole basis
    points — and the divisor is always the **base** allowance copied from the
    program at placement time, never the final allowance."
    PRD §3.7: "`days_elapsed` is the whole number of twenty-four-hour days between
    `placed_at` and the current logical clock, floored, and it is recomputed on
    every read of the placement and on every census run."
    PRD §3.7: "the milestone bonus is 90 days at 60 or more credited hours, 60 days
    at 40 or more hours, 30 days at 20 or more hours, and 0 days below 20 hours"

    Design: Difficulty/combinatorial_formula/tlp_duration_allowance_pins_ratio_against_base_allowance_only
    """
    setup = _placement_at_420_days()
    placement = setup["placement"]

    assert_tlp_placement(placement)
    assert placement["days_elapsed"] == 420, (
        f"420 whole days have elapsed since placement, got {placement['days_elapsed']}"
    )
    assert placement["base_allowance_days"] == 540, (
        "the base allowance is copied from the program's max_placement_days of "
        f"540, got {placement['base_allowance_days']}"
    )
    assert placement["consumed_ratio_bp"] == 7777, (
        "420 times 10000 divided by 540 floors to 7777 basis points, got "
        f"{placement['consumed_ratio_bp']}"
    )
    assert placement["life_skills_credit_hours"] == 0, (
        f"no curriculum hours are credited yet, got {placement['life_skills_credit_hours']}"
    )
    assert placement["earned_bonus_days"] == 0, (
        "below twenty credited hours the milestone bonus is zero days, got "
        f"{placement['earned_bonus_days']}"
    )
    assert placement["allowance_days"] == 540, (
        f"the allowance is the base allowance alone, got {placement['allowance_days']}"
    )


def test_late_stage_haircut_halves_the_milestone_bonus(api):
    """PRD §3.7: "that milestone bonus is then subjected to a late-stage haircut,
    so `earned_bonus_days` is the milestone bonus halved and floored to whole days
    when step one's `consumed_ratio_bp` has reached or passed 7500 — three quarters
    of the base allowance consumed — and is the full milestone bonus otherwise."
    PRD §3.7: "A placement with a base allowance of 540 days, 420 days elapsed and
    40 credited hours therefore has a consumed ratio of 7777 basis points, takes
    the haircut, earns 30 bonus days and reaches an allowance of 570 days, rather
    than earning 60 bonus days for an allowance of 600."

    Design: Difficulty/combinatorial_formula/tlp_duration_allowance_pins_ratio_against_base_allowance_only
    """
    setup = _placement_at_420_days()

    completion = credit_life_skills(setup["placement"]["id"], 40, "BUDGETING")
    assert completion["credit_hours"] == 40, (
        f"the completion carries the credited hours, got {completion['credit_hours']}"
    )

    placement = fetch_placement(setup["placement"]["id"])
    assert placement["life_skills_credit_hours"] == 40, (
        f"the placement accumulates 40 credited hours, got {placement['life_skills_credit_hours']}"
    )
    assert placement["consumed_ratio_bp"] == 7777, (
        "the consumption ratio is never recomputed against the post-bonus "
        f"allowance, got {placement['consumed_ratio_bp']}"
    )
    assert placement["earned_bonus_days"] == 30, (
        "the 60-day milestone bonus is halved by the haircut to 30 days, got "
        f"{placement['earned_bonus_days']}"
    )
    assert placement["allowance_days"] == 570, (
        "540 base days plus 30 earned days is 570; 600 is the rejected order, got "
        f"{placement['allowance_days']}"
    )
    assert placement["tenancy_status"] == "PLACED", (
        f"crediting curriculum hours never moves the tenancy, got {placement['tenancy_status']}"
    )


# ─── Instance: the priority score saturates at three points ───

BO = {
    "legal_first_name": "Bo",
    "legal_last_name": "Nakamura",
    "date_of_birth": "2012-06-10",
    "unaccompanied": True,
}
CRITICAL_INDICATORS = ["COMMERCIAL_SEX", "THIRD_PARTY_CONTROL"]
STAGES = ["FIRST_CONTACT", "RAPPORT_BUILDING", "RAPPORT_BUILDING", "SERVICE_OFFER",
          "TRUST_ESTABLISHED"]
NEEDS = ["FOOD", "HYGIENE_KIT", "CLOTHING", "TRANSIT_PASS", "MEDICAL_REFERRAL"]


def _critical_tier_youth_with_five_contacts():
    """A youth aged 14 carrying five same-day outreach encounters, each worth 70
    undecayed indicator points, and a cleared screening."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=2,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    youth = intake_youth(**dict(BO))
    for stage, need in zip(STAGES, NEEDS):
        log_outreach_contact(
            youth["id"],
            engagement_stage=stage,
            basic_needs_provided=[need],
            indicator_flags=list(CRITICAL_INDICATORS),
        )
    clear_screening(youth["id"])
    return program, youth


def test_youth_history_score_saturates_at_one_hundred(api):
    """PRD §3.1: "That contact's contribution is its raw indicator value multiplied
    by the retained percentage, divided by one hundred, and **floored to a whole
    point before being added to the running total**."
    PRD §3.1: "`trafficking_risk_score` is the running total, capped at 100."
    PRD §3.1: "`engagement_contact_count` rises by one, `basic_needs_provision_count`
    rises by the number of items in the `basic_needs_provided` list of this
    encounter, the youth's standing trafficking risk is recomputed and re-tiered
    against the current clock, the youth's `risk_posture` is recomputed,
    `governance_vote_eligible` is recomputed, and the youth's `version` increments
    by one."

    Design: Difficulty/combinatorial_formula/admission_priority_score_nested_caps_and_critical_bump_clamp
    """
    _program, youth = _critical_tier_youth_with_five_contacts()

    current = fetch_youth(youth["id"])
    assert current["engagement_contact_count"] == 5, (
        f"five encounters were logged, got {current['engagement_contact_count']}"
    )
    assert current["basic_needs_provision_count"] == 5, (
        "each encounter handed over one item, got "
        f"{current['basic_needs_provision_count']}"
    )
    assert current["trafficking_risk_score"] == 100, (
        "five same-day contributions of 70 points sum to 350 and cap at 100, got "
        f"{current['trafficking_risk_score']}"
    )
    assert current["trafficking_risk_tier"] == "CRITICAL", (
        f"a score of 100 tiers as CRITICAL, got {current['trafficking_risk_tier']}"
    )


def test_priority_score_clamps_after_the_critical_tier_bump(api):
    """PRD §3.3: "The age component is eighteen minus the youth's `age_years`, held
    at a floor of zero so that a youth aged eighteen or older contributes nothing,
    multiplied by four — so a fourteen-year-old contributes sixteen points."
    PRD §3.3: "The risk component is the youth's `trafficking_risk_score`, capped
    at 40."
    PRD §3.3: "The engagement component is the youth's `engagement_contact_count`
    multiplied by five, capped at 20, so a fourth and later encounter adds nothing
    further."
    PRD §3.3: "Those four are summed; then, if and only if the youth's
    `trafficking_risk_tier` is `CRITICAL`, a further 10 points are added; and the
    result is finally capped at 100."
    PRD §3.3: "Nested caps and floors are evaluated innermost first, and the
    critical-tier bump is applied **before** the final cap at 100, never after it."

    Design: Difficulty/combinatorial_formula/admission_priority_score_nested_caps_and_critical_bump_clamp
    """
    program, youth = _critical_tier_youth_with_five_contacts()

    admission = request_admission(youth["id"], program["id"], instant("2026-08-12"))

    assert admission["priority_score"] == 100, (
        "sixteen age points plus forty risk points plus twenty engagement points "
        "plus fifteen exposure points is ninety-one, the critical bump makes it "
        f"one hundred and one, and the final cap clamps it to 100, got "
        f"{admission['priority_score']}"
    )
    assert admission["status"] == "ACTIVE", (
        f"a cleared screening at an open program admits straight away, got {admission['status']}"
    )
    assert admission["projected_billable_nights"] == 11, (
        "2026-08-01 to 2026-08-12 is eleven whole calendar days, got "
        f"{admission['projected_billable_nights']}"
    )


def test_active_admission_shelters_the_youth_under_a_restricted_posture(api):
    """PRD §3.3: "the existence of that pending obligation recomputes the youth's
    `risk_posture` to `RESTRICTED` — which blocks that youth's transitional-living
    placement with `ERR_YOUTH_POSTURE_RESTRICTED` until the obligation is resolved
    — and the youth's `status` becomes `SHELTERED` with the youth's `version`
    incremented by one."
    PRD §3.3: "The exposure component is 15 for a youth whose
    `cumulative_shelter_nights` is exactly zero — a first-time entrant to the
    system — and otherwise 15 minus the youth's `cumulative_shelter_nights`, held
    at a floor of zero."

    Design: Difficulty/combinatorial_formula/admission_priority_score_nested_caps_and_critical_bump_clamp
    """
    program, youth = _critical_tier_youth_with_five_contacts()
    before = fetch_youth(youth["id"])
    assert before["cumulative_shelter_nights"] == 0, (
        "the youth has never been sheltered before, got "
        f"{before['cumulative_shelter_nights']}"
    )

    request_admission(youth["id"], program["id"], instant("2026-08-12"))

    after = fetch_youth(youth["id"])
    assert after["status"] == "SHELTERED", (
        f"an active stay shelters the youth, got {after['status']}"
    )
    assert after["risk_posture"] == "RESTRICTED", (
        "the pending notification obligation restricts the youth, got "
        f"{after['risk_posture']}"
    )
