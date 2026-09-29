"""Multi-input formulas whose factors interact non-linearly and whose evaluation
order is pinned by the PRD."""
from test_helpers import assert_aums
from test_helpers.fixtures import (
    accept_use_report,
    add_use_record,
    report_actual_use,
    bill_trespass_incident,
    create_allotment,
    create_aoi,
    create_pasture,
    create_permittee,
    create_trespass_incident,
    get_allotment,
    get_aoi,
    get_permittee,
    get_trespass_incident,
    get_use_record,
    issue_aoi,
    issued_permit_setup,
    list_bills,
)


def _trespass_history_setup(second_willfulness):
    """One allotment, one permittee, one already-billed NON_WILLFUL incident of 10 head
    for 10 days, then a fresh 47-head 11-day incident detected later."""
    allotment = create_allotment(total_permitted_aums=600, acres=20000)
    permittee = create_permittee()
    first = create_trespass_incident(
        allotment["id"], permittee["id"], detected_at="2026-06-15T14:00:00Z",
        head_count=10, livestock_kind="CATTLE", unauthorized_days=10,
        willfulness="NON_WILLFUL")
    first = bill_trespass_incident(first["id"])
    second = create_trespass_incident(
        allotment["id"], permittee["id"], detected_at="2026-07-20T09:00:00Z",
        head_count=47, livestock_kind="CATTLE", unauthorized_days=11,
        willfulness=second_willfulness)
    return {"allotment": allotment, "permittee": permittee,
            "first_incident": first, "second_incident": second}


def test_trespass_charge_composes_ceiling_willfulness_and_repeat_factor():
    """47 head for 11 days is 17.23 unauthorized AUMs, billed up to 18 whole AUMs at 2,340
    cents = 42,120 of base; REPEATED_WILLFUL contributes (3.0 - 1.0) and one prior billed
    incident contributes 1.25, so the penalty is 42,120 x 2.0 x 1.25 = 105,300 and the
    total is 147,420 cents with no administrative fee.

    PRD 3.11: "Step two sets `billed_aums` to `unauthorized_aums` rounded **up** to the next
    whole AUM, so 12.01 unauthorized AUMs are billed as 13; unlike a use bill, an
    unauthorized-use charge is never billed in fractional AUMs."
    PRD 3.11: "Step four selects the willfulness multiplier: 1.0 for `NON_WILLFUL`, 2.0 for
    `WILLFUL` and 3.0 for `REPEATED_WILLFUL`."
    PRD 3.11: "Step six sets `penalty_amount_cents` to `base_amount_cents` multiplied by the
    willfulness multiplier less 1.0, multiplied by the repeat factor, rounded half-up to a
    whole cent."
    PRD 3.11: "Step seven sets `total_amount_cents` to `base_amount_cents` plus
    `penalty_amount_cents`, and sets `admin_fee_cents` to exactly 0"

    Design: Difficulty/combinatorial_formula/trespass_penalty_three_factor_composition
    """
    setup = _trespass_history_setup("REPEATED_WILLFUL")
    incident = setup["second_incident"]

    assert incident["prior_billed_incident_count"] == 1, (
        "the snapshot counts the earlier incident, which was billed before this detection")
    assert_aums(incident["unauthorized_aums"], 17.23)

    billed = bill_trespass_incident(incident["id"])
    assert billed["billed_aums"] == 18, "17.23 AUMs round up to 18 whole AUMs"
    assert billed["incident_status"] == "BILLED"

    bills = list_bills(trespass_incident_id=incident["id"])
    assert len(bills) == 1
    bill = bills[0]
    assert bill["bill_type"] == "UNAUTHORIZED_USE"
    assert bill["fee_rate_cents_per_aum"] == 2340
    assert bill["base_amount_cents"] == 42120
    assert bill["penalty_amount_cents"] == 105300
    assert bill["admin_fee_cents"] == 0
    assert bill["total_amount_cents"] == 147420
    assert bill["aoi_id"] is None and bill["project_id"] is None

    first = get_trespass_incident(setup["first_incident"]["id"])
    assert first["billed_aums"] == 4, "3.33 unauthorized AUMs round up to 4"

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["billed_trespass_incident_count"] == 2
    assert permittee["outstanding_balance_cents"] == 156780, (
        "9,360 cents for the first incident plus 147,420 for the second")


def test_non_willful_trespass_is_penalty_free_despite_a_prior_billed_incident():
    """The same 47-head 11-day forage quantity recorded as NON_WILLFUL yields a penalty of
    exactly 0 because the multiplier less 1.0 is 0, so the 1.25 repeat factor has nothing
    to inflate and the total collapses to the 42,120-cent base.

    PRD 3.11: "Subtracting 1.0 from the multiplier before applying the repeat factor is what
    makes a `NON_WILLFUL` incident penalty-free: its multiplier is exactly 1.0, so the
    penalty is 0 no matter how many prior incidents the permittee has, and an implementation
    that multiplies the base by the multiplier and treats the excess as the penalty will levy
    a repeat-factor-inflated charge on an unwilful trespasser."
    PRD 3.11: "Step five computes the repeat factor as 1.0 plus 0.25 for each prior billed
    incident recorded in `prior_billed_incident_count`, capped at 2.0"

    Design: Difficulty/combinatorial_formula/trespass_penalty_three_factor_composition
    """
    setup = _trespass_history_setup("NON_WILLFUL")
    incident = setup["second_incident"]
    assert incident["prior_billed_incident_count"] == 1

    billed = bill_trespass_incident(incident["id"])
    assert billed["billed_aums"] == 18

    bill = list_bills(trespass_incident_id=incident["id"])[0]
    assert bill["base_amount_cents"] == 42120
    assert bill["penalty_amount_cents"] == 0
    assert bill["total_amount_cents"] == 42120
    assert bill["admin_fee_cents"] == 0

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 51480, "9,360 plus 42,120 cents"


def _rounding_draw_setup():
    """Two 300-AUM pastures under a 1200-AUM allotment, an ISSUED 300-AUM permit and an
    ISSUED 2026 instruction with two scheduled legs on separate pastures."""
    setup = issued_permit_setup(
        total_permitted_aums=1200, pasture_aum_capacity=300,
        required_pasture_rotation_count=2, carrying_capacity_aums=400,
        requested_aums=300, allotment_overrides={"acres": 40000})
    setup["pasture_2"] = create_pasture(
        setup["allotment"]["id"], pasture_aum_capacity=300, sequence_order=2)
    aoi = create_aoi(setup["permit"]["id"], grazing_year=2026, authorized_aums=300,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    setup["use_record_1"] = add_use_record(
        aoi["id"], setup["pasture"]["id"], planned_entry_date="2026-04-01",
        planned_exit_date="2026-05-02", planned_head_count=100, livestock_kind="CATTLE")
    setup["use_record_2"] = add_use_record(
        aoi["id"], setup["pasture_2"]["id"], planned_entry_date="2026-05-02",
        planned_exit_date="2026-06-01", planned_head_count=100, livestock_kind="CATTLE")
    setup["aoi"] = issue_aoi(aoi["id"])
    return setup


def _report_leg(record_id, entry_date, exit_date, head_count=100):
    """A RangeSpecialist reports a leg on the rancher's behalf (PRD 3.5)."""
    return report_actual_use(record_id, actual_entry_date=entry_date,
                             actual_exit_date=exit_date, actual_head_count=head_count)


def test_actual_use_rounds_each_leg_to_two_places_before_summing():
    """Two legs of 100 head over 23 days each give the raw quotient 76.6666..., and the PRD
    rounds per record first: 76.67 + 76.67 = 153.34 AUMs and a final base of 26,374 cents,
    where summing raw quotients first would bill 26,373.

    PRD 3.5: "the leg's `actual_aums` is computed by exactly the same forage arithmetic as
    `planned_aums` — head count times animal-unit equivalent times whole days in the half-open
    window, divided by 30, rounded half-up to 2 decimal places once"
    PRD 3.5: "The rounding order here is pinned: each record's quantity is rounded to 2 decimal
    places first and the already-rounded values are then added, because summing raw quotients
    and rounding once at the end produces a different figure and therefore a different bill."

    Design: Difficulty/combinatorial_formula/actual_use_per_record_rounding_order
    """
    setup = _rounding_draw_setup()

    _report_leg(setup["use_record_1"]["id"], "2026-04-01", "2026-04-24")
    _report_leg(setup["use_record_2"]["id"], "2026-05-02", "2026-05-25")

    assert_aums(get_use_record(setup["use_record_1"]["id"])["actual_aums"], 76.67)
    assert_aums(get_use_record(setup["use_record_2"]["id"])["actual_aums"], 76.67)

    accepted = accept_use_report(setup["aoi"]["id"])
    assert_aums(accepted["actual_aums_total"], 153.34)

    final_bill = list_bills(aoi_id=setup["aoi"]["id"], bill_type="FINAL_USE")[0]
    assert final_bill["base_amount_cents"] == 26374, (
        "153.34 AUMs x 172 cents = 26,374 cents exactly")
    assert final_bill["base_amount_cents"] != 26373, (
        "26,373 is the figure produced by summing the raw quotients before rounding")
    assert final_bill["total_amount_cents"] == 26374

    assert get_use_record(setup["use_record_1"]["id"])["record_status"] == "ACCEPTED"
    assert get_use_record(setup["use_record_2"]["id"])["record_status"] == "ACCEPTED"


def test_instruction_total_accumulates_reported_legs_and_ignores_scheduled_ones():
    """Reporting only the first leg puts 76.67 into actual_aums_total and leaves the second
    leg's actual_aums null, proving the aggregate is a sum over already-rounded reported legs
    rather than a recomputation from the plan.

    PRD 3.5: "The instruction's `actual_aums_total` is then recomputed as the sum of
    `actual_aums` over its records whose `record_status` is `ACTUAL_REPORTED` or `ACCEPTED`;
    records still `SCHEDULED` contribute nothing, and `actual_aums` is null until the leg is
    reported."
    PRD 3.5: "Reporting a leg does **not** move the instruction's own `aoi_status`; the
    officer's acceptance does that."

    Design: Difficulty/combinatorial_formula/actual_use_per_record_rounding_order
    """
    setup = _rounding_draw_setup()

    reported = _report_leg(setup["use_record_1"]["id"], "2026-04-01", "2026-04-24")
    assert reported["record_status"] == "ACTUAL_REPORTED"
    assert_aums(reported["actual_aums"], 76.67)

    aoi = get_aoi(setup["aoi"]["id"])
    assert_aums(aoi["actual_aums_total"], 76.67)
    assert aoi["aoi_status"] == "ISSUED", "reporting a leg does not move the instruction"

    still_scheduled = get_use_record(setup["use_record_2"]["id"])
    assert still_scheduled["record_status"] == "SCHEDULED"
    assert still_scheduled["actual_aums"] is None

    _report_leg(setup["use_record_2"]["id"], "2026-05-02", "2026-05-25")
    assert_aums(get_aoi(setup["aoi"]["id"])["actual_aums_total"], 153.34)


def _tier_edge_setup(authorized_aums):
    """A 1200-AUM allotment with one pasture, an ISSUED 300-AUM permit and a DRAFT 2026
    instruction authorized at exactly the given figure with one scheduled leg."""
    setup = issued_permit_setup(
        total_permitted_aums=1200, pasture_aum_capacity=300,
        required_pasture_rotation_count=1, carrying_capacity_aums=400,
        requested_aums=300, allotment_overrides={"acres": 25000})
    aoi = create_aoi(setup["permit"]["id"], grazing_year=2026,
                     authorized_aums=authorized_aums,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    setup["use_record"] = add_use_record(
        aoi["id"], setup["pasture"]["id"], planned_entry_date="2026-04-01",
        planned_exit_date="2026-05-02", planned_head_count=100, livestock_kind="CATTLE")
    setup["aoi"] = aoi
    return setup


def test_admin_fee_stays_zero_when_the_base_is_just_under_the_first_tier_boundary():
    """290 authorized AUMs produce a base of 49,880 cents, 120 short of the 50,000-cent
    boundary, so the administrative fee is 0 and the total is 49,880 — an implementation that
    tests the boundary against the total after adding a fee returns 52,380.

    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`,
    never from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000
    cents, 2,500 cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and
    6,000 cents when `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Reading the tier off the total is the circular reading and produces the wrong
    fee, because the total already contains the fee."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_base_not_total
    """
    setup = _tier_edge_setup(290)

    issue_aoi(setup["aoi"]["id"])
    bill = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")[0]

    assert bill["billed_aums"] == 290
    assert bill["base_amount_cents"] == 49880
    assert bill["admin_fee_cents"] == 0
    assert bill["total_amount_cents"] == 49880
    assert bill["total_amount_cents"] != 52380, (
        "52,380 is the figure produced by keying the tier on the fee-inclusive total")

    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 49880
    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 290
    assert allotment["open_aums"] == 910


def test_admin_fee_appears_once_the_base_itself_reaches_the_first_tier_boundary():
    """One more authorized AUM lifts the base to 50,052 cents, at the boundary, so the middle
    tier applies and the total becomes 52,552 — the fee is a step function of the base alone.

    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`,
    never from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000
    cents, 2,500 cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and
    6,000 cents when `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Step four sets `total_amount_cents` to `base_amount_cents` plus
    `admin_fee_cents`; `penalty_amount_cents` is 0 on every use bill."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_base_not_total
    """
    setup = _tier_edge_setup(291)

    issue_aoi(setup["aoi"]["id"])
    bill = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")[0]

    assert bill["billed_aums"] == 291
    assert bill["base_amount_cents"] == 50052
    assert bill["admin_fee_cents"] == 2500
    assert bill["total_amount_cents"] == 52552

    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 52552
    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 291
    assert allotment["open_aums"] == 909
