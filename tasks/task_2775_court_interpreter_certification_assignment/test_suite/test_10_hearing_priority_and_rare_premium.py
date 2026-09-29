"""Combinatorial formulas: frozen hearing priority and the rare-language premium.

One priority score combines a type weight, a custody bonus, a language rarity bonus
and a clamped urgency term before the sum is capped (PRD §3.5), and the rare branch
of the tier floor then overrides what a class A hearing demands (PRD §3.6). The
rare-language premium bracket is keyed on the rounded service component alone, never
on a running total that includes travel (PRD §3.8).
"""

import test_helpers.fixtures as fixtures
from test_helpers import validate_paginated

CLOCK = "2026-08-01T00:00:00Z"

# Class A exactly at the floor: TRIAL 40 + custody 25 + NON_DESIGNATED 5 + urgency 10.
KOR_HEARING = {
    "case_number": "CR-2026-0080",
    "hearing_type": "TRIAL",
    "in_custody": True,
    "scheduled_start": "2026-08-06T09:00:00.000Z",
    "scheduled_end": "2026-08-06T11:00:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}
# Class A with the urgency term clamped to 0: ARRAIGNMENT 50 + custody 25 + RARE 15.
RARE_HEARING = {
    "case_number": "CR-2026-0090",
    "hearing_type": "ARRAIGNMENT",
    "in_custody": True,
    "scheduled_start": "2026-09-11T08:30:00.000Z",
    "scheduled_end": "2026-09-11T09:30:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}
# Class B: TRIAL 40 + custody 25 + DESIGNATED 0 + urgency 0.
SPANISH_TRIAL_HEARING = {
    "case_number": "CR-2026-0065",
    "hearing_type": "TRIAL",
    "in_custody": True,
    "scheduled_start": "2026-09-10T09:00:00.000Z",
    "scheduled_end": "2026-09-10T11:00:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}
# Class C: CIVIL_MOTION 10 and nothing else.
CIVIL_MOTION_HEARING = {
    "case_number": "CV-2026-0010",
    "hearing_type": "CIVIL_MOTION",
    "in_custody": False,
    "scheduled_start": "2026-09-11T08:30:00.000Z",
    "scheduled_end": "2026-09-11T09:30:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}

# The rare-premium claim: a 5.00 h scheduled window and a 5h55m served window at the
# PROVISIONAL hourly rate of 4900 cents, with 40.0 one-way miles.
PREMIUM_HEARING = {
    "case_number": "CR-2026-0091",
    "hearing_type": "MOTION",
    "in_custody": False,
    "scheduled_start": "2026-09-11T08:30:00.000Z",
    "scheduled_end": "2026-09-11T13:30:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}
PREMIUM_CHECK_IN_CLOCK = "2026-09-11T08:30:00Z"
PREMIUM_ACTUAL_END_UTC = "2026-09-11T14:25:00.000Z"
PREMIUM_ONE_WAY_MILES = 40.0

PROVISIONAL_BILLABLE_HOURS = 5.00
PROVISIONAL_SERVICE_CENTS = 24500
PROVISIONAL_PREMIUM_CENTS = 2450
PROVISIONAL_TRAVEL_CENTS = 5400
PROVISIONAL_TOTAL_CENTS = 32350

FINAL_BILLABLE_HOURS = 6.00
FINAL_SERVICE_CENTS = 29400
FINAL_PREMIUM_CENTS = 2940
FINAL_TRAVEL_CENTS = 5400
FINAL_TOTAL_CENTS = 37740
# What a running total including travel would have produced: 34800 >= 30000 -> 15 pct.
RUNNING_TOTAL_PREMIUM_CENTS = 5220
WRONG_FINAL_TOTAL_CENTS = 40020

PAY_BUDGET_CENTS = 5_000_000
BO_LIM = {"full_name": "Bo Lim", "email": "bo.lim@courts.example.gov"}


def _priority_world():
    """Clock + spa, kor and mix languages + the main courthouse."""
    config = fixtures.setup_program_config(
        with_rate_schedule=False, with_rare_language=True, clock=CLOCK
    )
    config["kor_language"] = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED"
    )
    return config


def _rare_provisional_interpreter(rare_language_id):
    """Bo Lim with ethics training complete and an ACTIVE PROVISIONAL rare credential."""
    return fixtures.setup_active_interpreter(
        rare_language_id, target_tier="PROVISIONAL", interpreter_overrides=dict(BO_LIM)
    )


def _rare_premium_bundle(served):
    """Config + rare-language interpreter + the 5-hour MOTION hearing, confirmed.

    With served=True the assignment is also checked in and completed, so the claim
    carries the FINAL variant's figures.
    """
    config = fixtures.setup_program_config(with_rare_language=True, clock=CLOCK)
    bundle = _rare_provisional_interpreter(config["rare_language"]["id"])
    hearing_overrides = dict(PREMIUM_HEARING)
    hearing_overrides["language_id"] = config["rare_language"]["id"]
    kwargs = {
        "hearing_overrides": hearing_overrides,
        "assignment_overrides": {"estimated_one_way_miles": PREMIUM_ONE_WAY_MILES},
        "config": config,
        "interpreter_bundle": bundle,
    }
    if not served:
        return fixtures.setup_confirmed_assignment(**kwargs)
    return fixtures.setup_served_assignment(
        PREMIUM_CHECK_IN_CLOCK, PREMIUM_ACTUAL_END_UTC, PREMIUM_ONE_WAY_MILES, **kwargs
    )


def test_priority_score_combines_five_factors_and_lands_exactly_on_the_class_a_floor():
    """PRD §3.5: "First, a **type weight** taken from the event type: an arraignment
    scores 50, a detention review 45, a trial 40, a plea 30, a sentencing 30, a motion 20,
    and a civil motion 10."
    PRD §3.5: "Second, a **custody bonus** of 25 points added when `in_custody` is true and
    nothing added when it is false."
    PRD §3.5: "Third, a **rarity bonus** taken from the needed language's `tier_class`: 15
    points for a `RARE` language, 5 points for a `NON_DESIGNATED` one, and 0 for a
    `DESIGNATED` one."
    PRD §3.5: "Fourth, a **lead-time figure** stored on the row as `lead_time_days`: take
    the difference between `scheduled_start` and the logical clock at the moment of
    creation, express it in whole days by discarding any remaining fraction of a day, and
    then treat any negative result as 0."
    PRD §3.5: "Fifth, an **urgency term**: start from 20 points, subtract 2 points for each
    whole day of `lead_time_days`, and treat any negative result as 0 — so a hearing 10 or
    more days out contributes no urgency at all while one starting the same day contributes
    the full 20."
    PRD §3.5: "Both boundaries are inclusive at the floor, so a score of exactly 80 is
    class `A` and a score of exactly 55 is class `B`."

    Design: Difficulty/combinatorial_formula/hearing_priority_score_five_factor_combination_and_rare_tier_override
    """
    config = _priority_world()

    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["kor_language"]["id"], **KOR_HEARING
    )

    assert hearing["lead_time_days"] == 5, (
        f"expected lead_time_days 5 for a 2026-08-06T09:00Z start on a 2026-08-01T00:00Z "
        f"clock, got {hearing['lead_time_days']}"
    )
    assert hearing["priority_score"] == 80, (
        f"expected priority_score 80 (40 trial + 25 custody + 5 non-designated + 10 "
        f"urgency), got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "A", (
        f"expected priority_class A at exactly the 80 floor, got "
        f"{hearing['priority_class']}"
    )


def test_urgency_term_clamps_to_zero_and_the_rare_bonus_lifts_the_score_to_ninety():
    """PRD §3.5: "Fifth, an **urgency term**: start from 20 points, subtract 2 points for
    each whole day of `lead_time_days`, and treat any negative result as 0 — so a hearing
    10 or more days out contributes no urgency at all while one starting the same day
    contributes the full 20."
    PRD §3.5: "Third, a **rarity bonus** taken from the needed language's `tier_class`: 15
    points for a `RARE` language, 5 points for a `NON_DESIGNATED` one, and 0 for a
    `DESIGNATED` one."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency
    term, then cap the sum at 100; the result is `priority_score`."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is
    80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."

    Design: Difficulty/combinatorial_formula/hearing_priority_score_five_factor_combination_and_rare_tier_override
    """
    config = _priority_world()

    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["rare_language"]["id"], **RARE_HEARING
    )

    assert hearing["lead_time_days"] == 41, (
        f"expected lead_time_days 41 for a 2026-09-11T08:30Z start, got "
        f"{hearing['lead_time_days']}"
    )
    assert hearing["priority_score"] == 90, (
        f"expected priority_score 90 (50 arraignment + 25 custody + 15 rare + 0 urgency), "
        f"got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "A", (
        f"expected priority_class A for a score of 90, got {hearing['priority_class']}"
    )


def test_priority_class_falls_to_b_then_c_as_the_factor_combination_thins_out():
    """PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency
    term, then cap the sum at 100; the result is `priority_score`."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is
    80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."
    PRD §3.5: "Second, a **custody bonus** of 25 points added when `in_custody` is true and
    nothing added when it is false."
    PRD §3.5: "`lead_time_days`, `priority_score` and `priority_class` are all computed
    once and never recomputed; a hearing created a month out stays class `C` even on the
    morning it is heard."

    Design: Difficulty/combinatorial_formula/hearing_priority_score_five_factor_combination_and_rare_tier_override
    """
    config = _priority_world()

    class_b = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["language"]["id"], **SPANISH_TRIAL_HEARING
    )
    class_c = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["language"]["id"], **CIVIL_MOTION_HEARING
    )

    assert class_b["priority_score"] == 65, (
        f"expected priority_score 65 (40 trial + 25 custody + 0 designated + 0 urgency), "
        f"got {class_b['priority_score']}"
    )
    assert class_b["priority_class"] == "B", (
        f"expected priority_class B for a score of 65, got {class_b['priority_class']}"
    )
    assert class_c["priority_score"] == 10, (
        f"expected priority_score 10 (10 civil motion, no custody, no rarity, no urgency), "
        f"got {class_c['priority_score']}"
    )
    assert class_c["priority_class"] == "C", (
        f"expected priority_class C for a score of 10, got {class_c['priority_class']}"
    )


def test_rare_language_overrides_the_class_a_certified_tier_requirement(
        api, scheduling_coordinator_headers):
    """PRD §3.6: "If the needed language's `tier_class` is `RARE`, the required minimum
    tier is `PROVISIONAL`, because no certification examination exists in that language and
    demanding a certified interpreter would guarantee an unmet hearing."
    PRD §3.6: "Otherwise, a class `A` hearing requires `CERTIFIED`, a class `B` hearing
    requires `REGISTERED`, and a class `C` hearing requires `PROVISIONAL`."
    PRD §3.6: "They must hold a credential in the hearing's `language_id` whose `status` is
    `ACTIVE` and whose tier rank reaches the required minimum tier derived above."
    PRD §3.6: "If the hearing's `priority_class` is `A`, their `rolling_12_month_score` must
    be at least 60; for class `B` and class `C` hearings no quality threshold applies."

    Design: Difficulty/combinatorial_formula/hearing_priority_score_five_factor_combination_and_rare_tier_override
    """
    config = _priority_world()
    bundle = _rare_provisional_interpreter(config["rare_language"]["id"])
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["rare_language"]["id"], **RARE_HEARING
    )

    assert hearing["priority_class"] == "A", (
        f"the fixture hearing must be class A for this override to matter, got "
        f"{hearing['priority_class']}"
    )
    assert bundle["interpreter"]["credential_tier"] == "PROVISIONAL", (
        f"expected credential_tier PROVISIONAL (rank 0, below the class A CERTIFIED "
        f"requirement), got {bundle['interpreter']['credential_tier']}"
    )

    pool, meta = validate_paginated(
        api.list_eligible_interpreters(hearing["id"], scheduling_coordinator_headers)
    )
    assert len(pool) == 1, (
        f"expected the PROVISIONAL rare-language interpreter to qualify for the class A "
        f"rare hearing, got a pool of {len(pool)}"
    )
    assert pool[0]["id"] == bundle["interpreter"]["id"], (
        f"expected interpreter {bundle['interpreter']['id']} in the pool, got "
        f"{pool[0]['id']}"
    )
    assert meta["total_count"] == 1, (
        f"expected meta.total_count 1, got {meta['total_count']}"
    )


def test_rare_provisional_credential_activates_without_examination_on_a_one_year_cycle():
    """PRD §3.3: "When the target tier is `PROVISIONAL` and the language's `tier_class` is
    `RARE`, the create call itself performs `PENDING_WRITTEN → PENDING_ETHICS` before
    returning, so the resource the client receives is already sitting in `PENDING_ETHICS`
    with its `version` incremented for that auto-transition."
    PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier` is set to
    `target_tier`; `issued_on` records the logical-clock date of this first activation;
    `expires_on` is set 730 days — two full years — after that date for a `MASTER`,
    `CERTIFIED`, or `REGISTERED` credential, and 365 days after it for a `PROVISIONAL` one,
    whose shorter cycle reflects that it rests on no examination; and `grace_through` is set
    90 days after `expires_on`."
    PRD §3.3: "A `PROVISIONAL` target is the program's rare-language and no-instrument
    escape hatch, and it is permitted only when the language's `tier_class` is `RARE` or the
    language's `oral_exam_available` is false; requesting `PROVISIONAL` for a fully
    examinable designated language is refused with `ERR_PROVISIONAL_TIER_NOT_PERMITTED`
    (HTTP 422)."

    Design: Difficulty/combinatorial_formula/hearing_priority_score_five_factor_combination_and_rare_tier_override
    """
    config = _priority_world()
    interpreter = fixtures.enrol_interpreter(**BO_LIM)
    interpreter = fixtures.complete_ethics_training(interpreter["id"])

    credential = fixtures.open_credential(
        interpreter["id"], config["rare_language"]["id"], target_tier="PROVISIONAL",
        expected_interpreter_version=interpreter["version"],
    )
    assert credential["status"] == "PENDING_ETHICS", (
        f"expected the create call to auto-transition a RARE PROVISIONAL credential to "
        f"PENDING_ETHICS, got {credential['status']}"
    )
    assert credential["written_best_score"] is None, (
        f"expected written_best_score null — there is nothing to examine — got "
        f"{credential['written_best_score']}"
    )

    activated = fixtures.advance_credential(credential["id"])
    assert activated["status"] == "ACTIVE", (
        f"expected status ACTIVE after the single PENDING_ETHICS advance, got "
        f"{activated['status']}"
    )
    assert activated["tier"] == "PROVISIONAL", (
        f"expected tier PROVISIONAL to mirror target_tier on activation, got "
        f"{activated['tier']}"
    )
    assert activated["issued_on"] == "2026-08-01", (
        f"expected issued_on 2026-08-01 from the logical clock, got "
        f"{activated['issued_on']}"
    )
    assert activated["expires_on"] == "2027-08-01", (
        f"expected expires_on 2027-08-01 (issued + 365 days for a PROVISIONAL cycle), got "
        f"{activated['expires_on']}"
    )
    assert activated["grace_through"] == "2027-10-30", (
        f"expected grace_through 2027-10-30 (expires_on + 90 days), got "
        f"{activated['grace_through']}"
    )


def test_provisional_claim_takes_the_low_rare_premium_below_the_bracket():
    """PRD §3.8: "When the hearing's language has `tier_class` `RARE`, compare the
    already-rounded `service_cents` against the schedule's `rare_premium_bracket_cents`: a
    service component at or above the breakpoint takes `rare_premium_high_pct` and one below
    it takes `rare_premium_low_pct`."
    PRD §3.8: "Multiply `service_cents` by the selected rate and round to whole cents half
    up; that is `rare_premium_cents`."
    PRD §3.8: "Select the hourly rate by the assignment's `credential_tier_snapshot`:
    `master_hourly_cents` for a `MASTER` snapshot, `certified_hourly_cents` for `CERTIFIED`,
    `registered_hourly_cents` for `REGISTERED`, and `provisional_hourly_cents` for
    `PROVISIONAL`."
    PRD §3.8: "Otherwise the reimbursable mileage is twice the one-way figure, because the
    interpreter drives there and back once past the radius."

    Design: Difficulty/combinatorial_formula/rare_premium_bracket_keyed_on_rounded_service_component_only
    """
    bundle = _rare_premium_bundle(served=False)
    claim = bundle["pay_claim"]

    assert bundle["assignment"]["credential_tier_snapshot"] == "PROVISIONAL", (
        f"expected credential_tier_snapshot PROVISIONAL, got "
        f"{bundle['assignment']['credential_tier_snapshot']}"
    )
    assert claim["billable_hours"] == PROVISIONAL_BILLABLE_HOURS, (
        f"expected billable_hours {PROVISIONAL_BILLABLE_HOURS} for the 08:30-13:30 "
        f"scheduled window, got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == PROVISIONAL_SERVICE_CENTS, (
        f"expected service_cents {PROVISIONAL_SERVICE_CENTS} (5.00 h at 4900 cents), got "
        f"{claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == PROVISIONAL_PREMIUM_CENTS, (
        f"expected rare_premium_cents {PROVISIONAL_PREMIUM_CENTS} — 24500 is below the "
        f"30000 bracket so the low rate applies — got {claim['rare_premium_cents']}"
    )
    assert claim["travel_cents"] == PROVISIONAL_TRAVEL_CENTS, (
        f"expected travel_cents {PROVISIONAL_TRAVEL_CENTS} for 40.0 one-way miles past the "
        f"30.0 free radius, got {claim['travel_cents']}"
    )
    assert claim["provisional_total_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected provisional_total_cents {PROVISIONAL_TOTAL_CENTS}, got "
        f"{claim['provisional_total_cents']}"
    )


def test_final_rare_premium_is_keyed_on_the_rounded_service_component_alone():
    """PRD §3.8: "The bracket test is keyed on the rounded service component alone and never
    on a running total — adding travel before the bracket test would select the higher rate
    on some claims and is explicitly not the rule."
    PRD §3.8: "Multiply that figure by four, round the product *up* to the next whole
    number, and divide by four again — the effect is that any part-used quarter hour is
    billed as a whole quarter hour."
    PRD §3.8: "When the hearing's language has `tier_class` `RARE`, compare the
    already-rounded `service_cents` against the schedule's `rare_premium_bracket_cents`: a
    service component at or above the breakpoint takes `rare_premium_high_pct` and one below
    it takes `rare_premium_low_pct`."

    Design: Difficulty/combinatorial_formula/rare_premium_bracket_keyed_on_rounded_service_component_only
    """
    bundle = _rare_premium_bundle(served=True)
    claim = bundle["pay_claim"]

    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL after completion, got {claim['variant']}"
    )
    assert claim["billable_hours"] == FINAL_BILLABLE_HOURS, (
        f"expected billable_hours {FINAL_BILLABLE_HOURS} for the 5h55m served window, got "
        f"{claim['billable_hours']}"
    )
    assert claim["service_cents"] == FINAL_SERVICE_CENTS, (
        f"expected service_cents {FINAL_SERVICE_CENTS} (6.00 h at 4900 cents), got "
        f"{claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == FINAL_PREMIUM_CENTS, (
        f"expected rare_premium_cents {FINAL_PREMIUM_CENTS} — 29400 alone is still below "
        f"the 30000 bracket — got {claim['rare_premium_cents']}"
    )
    assert claim["rare_premium_cents"] != RUNNING_TOTAL_PREMIUM_CENTS, (
        f"rare_premium_cents {claim['rare_premium_cents']} equals the figure a running "
        f"total of service plus travel (34800) would have produced; the bracket test must "
        f"read the service component alone"
    )
    assert claim["final_total_cents"] == FINAL_TOTAL_CENTS, (
        f"expected final_total_cents {FINAL_TOTAL_CENTS}, got {claim['final_total_cents']}"
    )
    assert claim["final_total_cents"] != WRONG_FINAL_TOTAL_CENTS, (
        f"final_total_cents {claim['final_total_cents']} matches the running-total bracket "
        f"error ({WRONG_FINAL_TOTAL_CENTS})"
    )


def test_rare_premium_components_are_rounded_before_the_sum_and_then_obligated():
    """PRD §3.8: "Add the three already-rounded components — `service_cents`,
    `rare_premium_cents`, and `travel_cents` — to obtain the total."
    PRD §3.8: "As §2.8 insists, each component is rounded before the addition; summing three
    unrounded components and rounding once at the end is a different number and is not the
    rule."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay claim
    whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`, reached through
    the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less
    `obligated_pay_cents`."

    Design: Difficulty/combinatorial_formula/rare_premium_bracket_keyed_on_rounded_service_component_only
    """
    bundle = _rare_premium_bundle(served=True)
    claim = bundle["pay_claim"]

    component_sum = (
        claim["service_cents"] + claim["rare_premium_cents"] + claim["travel_cents"]
    )
    assert component_sum == FINAL_TOTAL_CENTS, (
        f"expected the three rounded components to sum to {FINAL_TOTAL_CENTS}, got "
        f"{component_sum}"
    )
    assert claim["final_total_cents"] == component_sum, (
        f"expected final_total_cents {component_sum} to equal the component sum, got "
        f"{claim['final_total_cents']}"
    )

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents 0 once the claim finalized, got "
        f"{courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == FINAL_TOTAL_CENTS, (
        f"expected obligated_pay_cents {FINAL_TOTAL_CENTS}, got "
        f"{courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == PAY_BUDGET_CENTS - FINAL_TOTAL_CENTS, (
        f"expected available_pay_cents {PAY_BUDGET_CENTS - FINAL_TOTAL_CENTS}, got "
        f"{courthouse['available_pay_cents']}"
    )
