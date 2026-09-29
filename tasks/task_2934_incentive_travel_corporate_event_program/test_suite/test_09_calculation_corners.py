"""Calculation corners: measurement, rollup posture, named rates, gross-up snapshots (PRD §2.6, §3.7, §3.9)."""
from test_helpers import *  # noqa: F401,F403

# ── The canonical scaffold cohort ────────────────────────────────────────────
# One 5000000-cent program, a two-rung ladder, the Lisbon destination at a
# per-person land cost of 431757 cents and a 12-room / 5-night hotel block.

PLATINUM_TIER = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250000000,
    "budget_per_qualifier_cents": 2500000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150000,
    "service_load_bp": 1275,
}

GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150000000,
    "budget_per_qualifier_cents": 1600000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40000,
    "service_load_bp": 800,
}

ANA = {
    "employee_code": "S-1001",
    "full_name": "Ana Reyes",
    "baseline_metric": 180000000,
    "actual_metric": 260000000,
    "guest_count": 1,
}

BEN = {
    "employee_code": "S-2001",
    "full_name": "Ben Ortiz",
    "baseline_metric": 120000000,
    "actual_metric": 155000000,
    "guest_count": 0,
}

ZANE = {
    "employee_code": "S-5003",
    "full_name": "Zane Holt",
    "baseline_metric": 100000000,
    "actual_metric": 149999999,
    "guest_count": 0,
}

LISBON = {
    "city": "Lisbon",
    "country_code": "PT",
    "per_person_cost_cents": 431757,
    "risk_score": 35,
    "air_gateway_code": "LIS",
}

HOTEL_FIVE_NIGHTS = {
    "supplier_name": "Estoril Palace",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38500,
    "attrition_allowance_bp": 2000,
    "force_majeure_clause": "STANDARD",
    "exposure_basis": "ATTRITION_BASIS",
}

STAY = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}

DEPOSIT_SCHEDULE = [
    {"sequence": 1, "due_at": "2026-08-15T00:00:00Z", "amount_cents": 577500, "refundable_bp": 10000},
    {"sequence": 2, "due_at": "2026-09-15T00:00:00Z", "amount_cents": 577500, "refundable_bp": 5000},
    {"sequence": 3, "due_at": "2026-10-15T00:00:00Z", "amount_cents": 1155000, "refundable_bp": 0},
]

ANALYST = TEST_USERS["sales_ops_analyst_headers"]
DIRECTOR = TEST_USERS["program_director_headers"]
DESK = TEST_USERS["travel_desk_headers"]
APPROVER = TEST_USERS["contract_approver_headers"]


def _canonical_program_kwargs(budget_total_cents=5000000):
    """Program / ladder / destination / contract overrides for the scaffold cohort."""
    return {
        "program_overrides": {"budget_total_cents": budget_total_cents},
        "tier_specs": [dict(PLATINUM_TIER), dict(GOLD_TIER)],
        "destination_overrides": dict(LISBON),
        "contract_overrides": dict(HOTEL_FIVE_NIGHTS),
    }


def _registration_open_cohort(qualifier_specs, gross_up_policy="FULL_GROSS_UP",
                              budget_total_cents=5000000):
    """REGISTRATION_OPEN program with every supplied qualifier adjudicated."""
    return setup_registration_open_program(
        qualifier_specs=[dict(spec) for spec in qualifier_specs],
        gross_up_policy=gross_up_policy,
        **_canonical_program_kwargs(budget_total_cents),
    )


def _reconciled_cohort(qualifier_specs, survey_scores=None,
                       gross_up_policy="FULL_GROSS_UP", budget_total_cents=5000000):
    """RECONCILED program: every supplied qualifier enrolled, confirmed and travelled."""
    return setup_reconciled_program(
        qualifier_specs=[dict(spec) for spec in qualifier_specs],
        survey_scores=list(survey_scores or []),
        gross_up_policy=gross_up_policy,
        registration_overrides=dict(STAY),
        **_canonical_program_kwargs(budget_total_cents),
    )


def test_measurement_sums_the_travelling_cohort_before_it_rates_the_lift():
    """The lift of a two-winner cohort comes from the summed metrics, giving 38.33.

    PRD §3.9: "Two travellers with baselines of 180000000 and 120000000 against
    actuals of 260000000 and 155000000 give 3833 basis points and therefore a
    `sales_lift_pct` of 38.33."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])
    program = base["program"]

    measurement = read_measurement(program["id"])

    assert measurement["program_id"] == program["id"]
    assert measurement["baseline_metric_total"] == 300000000
    assert measurement["actual_metric_total"] == 415000000
    assert measurement["sales_lift_pct"] == 38.33


def test_measurement_satisfaction_index_is_the_mean_of_the_surveyed_scores():
    """Two surveyed seats scoring 9 and 8 give a satisfaction index of exactly 8.5.

    PRD §3.9: "Otherwise it is the sum of those scores multiplied by 100, divided
    by the number of surveyed seats, rounded half up to a whole centi-point, and
    then divided by 100 — again exact to two decimal places. Scores of 9 and 8
    give a `satisfaction_index` of 8.5."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])

    measurement = read_measurement(base["program"]["id"])

    assert measurement["survey_count"] == 2
    assert measurement["satisfaction_index"] == 8.5


def test_measurement_counts_and_budget_side_of_a_fully_travelled_cohort():
    """Both winners count as qualified and travelled, and the rollup reads OK.

    PRD §3.2: "The program's `qualified_count` is the number of its qualifiers
    whose `award_status` is `QUALIFIED`, `NOTIFIED`, `REGISTERED` or `TRAVELLED`;
    its `travelled_count` is the number whose `award_status` is exactly
    `TRAVELLED`."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])

    measurement = read_measurement(base["program"]["id"])

    assert measurement["qualified_count"] == 2
    assert measurement["travelled_count"] == 2
    assert measurement["committed_budget_cents"] == 1443174
    assert measurement["budget_headroom_cents"] == 3556826
    assert measurement["budget_posture"] == "OK"
    assert measurement["reported_award_total_cents"] == 0


def test_attrition_exposure_of_the_travelled_cohort_prices_the_unfilled_block():
    """Ten travelled room-nights against a 48-night floor expose 1463000 cents.

    PRD §3.5: "Its figure, `attrition_basis_cents`, is the `shortfall_room_nights`
    from the room-night ledger of §3.7 multiplied by the contract's
    `nightly_rate_cents`."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])

    projection = read_exposure_projection(base["contract"]["id"])

    assert projection["room_nights_blocked"] == 60
    assert projection["room_nights_confirmed"] == 10
    assert projection["attrition_floor_room_nights"] == 48
    assert projection["shortfall_room_nights"] == 38
    assert projection["attrition_basis_cents"] == 1463000
    assert projection["binding_basis"] == "ATTRITION_BASIS"
    assert projection["binding_exposure_cents"] == 1463000


def test_measurement_read_is_identical_for_the_analyst_and_the_director():
    """The computed measurement read is byte-identical across both permitted roles.

    PRD §4: "Computed read: program measurement against sales lift and participant
    satisfaction, plus the live budget and exposure posture."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])
    program_id = base["program"]["id"]

    director_view = validate_success(
        api_client.get_program_measurement(program_id, DIRECTOR)
    )
    analyst_view = validate_success(
        api_client.get_program_measurement(program_id, ANALYST)
    )

    assert analyst_view == director_view
    assert analyst_view["sales_lift_pct"] == 38.33
    assert analyst_view["satisfaction_index"] == 8.5


def test_reconciliation_stamps_the_lift_and_index_onto_the_program_row():
    """Advancing to RECONCILED stamps 38.33 and 8.5 onto the program itself.

    PRD §3.9: "and the program's `sales_lift_pct` and `satisfaction_index` are
    computed and stamped."

    Design: Corner/calculations/measurement_lift_and_satisfaction_from_a_known_two_winner_cohort
    """
    base = _reconciled_cohort([ANA, BEN], survey_scores=[9, 8])

    program = read_program(base["program"]["id"])

    assert_program(program)
    assert program["status"] == "RECONCILED"
    assert program["sales_lift_pct"] == 38.33
    assert program["satisfaction_index"] == 8.5
    assert program["committed_budget_cents"] == 1443174
    assert_budget_conserved(program)


def _exclusion_scenario():
    """RECONCILED program holding one disqualified qualifier, one window-closed
    seat with air spend, one travelled winner and one cancelled activity signup."""
    base = _registration_open_cohort([ANA, BEN, ZANE])
    program_id = base["program"]["id"]
    ana, ben, zane = base["qualifiers"]

    ana_seat = create_registration(ana["id"], program_id=program_id, **STAY)
    air_action(
        ana_seat["id"], "REQUEST", cabin_class="BUSINESS",
        deviation_pre_days=4, deviation_post_days=3, base_fare_cents=214000,
    )

    ben_seat = create_registration(ben["id"], program_id=program_id, **STAY)
    air_action(
        ben_seat["id"], "REQUEST", cabin_class="BUSINESS",
        deviation_pre_days=3, deviation_post_days=2, base_fare_cents=214000,
    )
    respond_registration(ben_seat["id"], ben["id"], "ACCEPT", waiver_signed=True)
    confirm_registration(ben_seat["id"])

    advance_program(program_id, "ONSITE")

    activity = create_activity(
        program_id, name="Douro Valley Wine Tour",
        start_at="2026-11-10T10:00:00Z", end_at="2026-11-10T13:00:00Z",
        capacity=5, risk_level="LOW",
    )
    signup = create_signup(activity["id"], ben_seat["id"])
    cancel_signup(signup["id"])
    close_activity(activity["id"])

    advance_program(program_id, "RECONCILED")

    return {
        "program": read_program(program_id),
        "contract": read_contract(base["contract"]["id"]),
        "ana": read_qualifier(ana["id"]),
        "ben": read_qualifier(ben["id"]),
        "zane": read_qualifier(zane["id"]),
        "ana_seat": read_registration(ana_seat["id"]),
        "ben_seat": read_registration(ben_seat["id"]),
        "activity": read_activity(activity["id"]),
        "signup": read_signup(signup["id"]),
    }


def test_disqualified_qualifier_stays_outside_the_award_rollup_and_the_cohort():
    """A qualifier one unit below the lowest rung commits nothing and is not counted.

    PRD §3.2: "If the eligible pool is empty, because the `actual_metric` fell
    below every rung on the ladder, the qualifier moves `PENDING_REVIEW →
    DISQUALIFIED`, `assigned_tier_id` stays null and `committed_cost_cents` stays
    0."

    Design: Corner/calculations/rollup_and_measurement_exclude_disqualified_uninvited_and_cancelled_rows
    """
    scenario = _exclusion_scenario()
    zane = scenario["zane"]

    assert_qualifier(zane)
    assert zane["award_status"] == "DISQUALIFIED"
    assert zane["assigned_tier_id"] is None
    assert zane["committed_cost_cents"] == 0
    assert zane["taxable_award_cents"] == 0
    assert read_measurement(scenario["program"]["id"])["qualified_count"] == 2


def test_window_closed_seat_contributes_neither_budget_nor_room_nights():
    """The auto-cancelled seat keeps its 47500 air cost but leaves the rollup and ledger.

    PRD §3.7: "Its air side is the sum of `cost_cents` over the program's seats
    whose `attendance_status` is `CONFIRMED` or `TRAVELLED`; all other seats are
    excluded."

    Design: Corner/calculations/rollup_and_measurement_exclude_disqualified_uninvited_and_cancelled_rows
    """
    scenario = _exclusion_scenario()
    program = scenario["program"]

    assert scenario["ana_seat"]["attendance_status"] == "CANCELLED"
    assert scenario["ana_seat"]["cancellation_reason"] == "REGISTRATION_WINDOW_CLOSED"
    assert scenario["ana_seat"]["cost_cents"] == 47500
    assert scenario["ana"]["award_status"] == "NOTIFIED"
    assert program["committed_budget_cents"] == 1548674
    assert program["budget_headroom_cents"] == 3451326
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)

    projection = read_exposure_projection(scenario["contract"]["id"])
    assert projection["room_nights_confirmed"] == 5
    assert projection["shortfall_room_nights"] == 43
    assert projection["binding_exposure_cents"] == 1655500
    assert_room_nights_conserved(scenario["contract"])


def test_lift_and_satisfaction_read_only_the_travelled_and_surveyed_rows():
    """One traveller and no survey give a 29.17 lift and a null satisfaction index.

    PRD §3.9: "Sales lift is measured over the **travelling cohort only**: the
    qualifiers of the program whose `award_status` is exactly `TRAVELLED`,
    excluding anyone `DISQUALIFIED`, `WITHDRAWN` or merely `NOTIFIED`."

    Design: Corner/calculations/rollup_and_measurement_exclude_disqualified_uninvited_and_cancelled_rows
    """
    scenario = _exclusion_scenario()

    measurement = read_measurement(scenario["program"]["id"])

    assert measurement["travelled_count"] == 1
    assert measurement["baseline_metric_total"] == 120000000
    assert measurement["actual_metric_total"] == 155000000
    assert measurement["sales_lift_pct"] == 29.17
    assert measurement["survey_count"] == 0
    assert measurement["satisfaction_index"] is None


def test_cancelled_signup_counts_towards_neither_activity_counter():
    """A cancelled signup is still listed but drops out of both agenda counters.

    PRD §3.8: "`booked_count` is always the number of the activity's signups
    whose `status` is `BOOKED` and `waitlist_count` the number whose `status` is
    `WAITLISTED`; cancelled signups count towards neither."

    Design: Corner/calculations/rollup_and_measurement_exclude_disqualified_uninvited_and_cancelled_rows
    """
    scenario = _exclusion_scenario()

    assert_signup_counters(scenario["activity"], 0, 0)
    assert scenario["signup"]["status"] == "CANCELLED"

    rows, meta = validate_paginated(
        api_client.list_activity_signups(
            DESK, params={"activity_id": scenario["activity"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "CANCELLED"


def test_taxable_base_of_the_travelled_winner_ignores_air_spend():
    """The traveller's taxable base comes off the award alone, not off his 105500 air cost.

    PRD §3.9: "The air-side variance carried on a seat's `cost_cents` — cabin
    upgrades, deviation surcharges and change fees — is treated as business
    travel and is deliberately **not** part of the taxable base."

    Design: Corner/calculations/rollup_and_measurement_exclude_disqualified_uninvited_and_cancelled_rows
    """
    scenario = _exclusion_scenario()

    assert scenario["ben_seat"]["cost_cents"] == 105500
    assert scenario["ben"]["award_status"] == "TRAVELLED"
    assert scenario["ben"]["committed_cost_cents"] == 521409
    assert scenario["ben"]["taxable_award_cents"] == 443198


def _named_constants_scenario():
    """RECONCILED program with one travelled PLATINUM winner carrying a 7-day
    deviation on a BUSINESS fare, and a second winner left NOTIFIED."""
    base = _registration_open_cohort([ANA, BEN])
    program_id = base["program"]["id"]
    ana, ben = base["qualifiers"]

    seat = create_registration(ana["id"], program_id=program_id, **STAY)
    air_action(
        seat["id"], "REQUEST", cabin_class="BUSINESS",
        deviation_pre_days=4, deviation_post_days=3, base_fare_cents=214000,
    )
    respond_registration(seat["id"], ana["id"], "ACCEPT", waiver_signed=True)
    confirm_registration(seat["id"])

    advance_program(program_id, "ONSITE")
    advance_program(program_id, "RECONCILED")

    return {
        "program": read_program(program_id),
        "ana": read_qualifier(ana["id"]),
        "ben": read_qualifier(ben["id"]),
        "seat": read_registration(seat["id"]),
    }


def test_guest_share_and_gratuity_rates_drive_the_award_commitment():
    """A guest at 6250 bp and gratuity at 350 bp of 431757 make the award 921765.

    PRD §3.2: "The **guest component** is the per-person basis multiplied by 6250
    and divided by 10000 — a guest is costed at 62.5 percent of a winner's land
    cost — rounded half up to a whole cent."

    Design: Corner/calculations/named_constants_drive_committed_cost_exclusion_deviation_and_gross_up_rates
    """
    scenario = _named_constants_scenario()

    assert scenario["program"]["per_person_cost_basis_cents"] == 431757
    assert scenario["ana"]["committed_cost_cents"] == 921765
    assert scenario["ben"]["committed_cost_cents"] == 521409


def test_business_purpose_exclusion_rate_sets_the_taxable_base():
    """The 1500 bp exclusion of 921765 rounds to 138265, leaving 783500 taxable.

    PRD §3.9: "A qualifier's business-purpose exclusion is its
    `committed_cost_cents` multiplied by 1500 and divided by 10000 — 15 percent
    of the committed award, recognised as legitimate business purpose — rounded
    half up to a whole cent."

    Design: Corner/calculations/named_constants_drive_committed_cost_exclusion_deviation_and_gross_up_rates
    """
    scenario = _named_constants_scenario()

    assert scenario["ana"]["taxable_award_cents"] == 783500
    assert scenario["ana"]["committed_cost_cents"] - 138265 == 783500
    assert scenario["ana"]["tax_status"] == "PENDING_REPORT"


def test_free_deviation_days_and_the_daily_fee_price_the_surcharge():
    """Seven deviation days less the 2 free ones cost 5 x 9500 = 47500 cents.

    PRD §3.7: "The **deviation surcharge** gives the first 2 deviation days away
    free. Chargeable days are the sum of `air_deviation_pre_days` and
    `air_deviation_post_days` less 2, floored at 0, and `air_deviation_fee_cents`
    is that count multiplied by 9500 cents per day."

    Design: Corner/calculations/named_constants_drive_committed_cost_exclusion_deviation_and_gross_up_rates
    """
    scenario = _named_constants_scenario()
    seat = scenario["seat"]

    assert_registration(seat)
    assert seat["air_deviation_pre_days"] == 4
    assert seat["air_deviation_post_days"] == 3
    assert seat["air_deviation_fee_cents"] == 47500
    assert seat["air_upgrade_cost_cents"] == 0
    assert seat["air_change_fee_total_cents"] == 0
    assert seat["cost_cents"] == 47500


def test_full_gross_up_rate_stack_is_keyed_on_the_snapshotted_award_value():
    """An award of 783500 stacks 2200 + 765 + 500 bp and reports 1198929 cents.

    PRD §3.9: "`combined_rate_bp` is the sum of the federal supplemental 2200
    basis points, the social-insurance 765 basis points, and the tiered state
    rate — **and the state tier is keyed on the pre-gross-up `award_value_cents`,
    not on the grossed-up result**."

    Design: Corner/calculations/named_constants_drive_committed_cost_exclusion_deviation_and_gross_up_rates
    """
    scenario = _named_constants_scenario()

    report = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(scenario["ana"]["id"], 2026),
            TEST_USERS["tax_officer_headers"],
        ),
        201,
    )

    assert_tax_award_report(report)
    assert report["award_value_cents"] == 783500
    assert report["gross_up_method"] == "FULL_GROSS_UP"
    assert report["combined_rate_bp"] == 3465
    assert report["gross_up_cents"] == 415429
    assert report["reported_value_cents"] == 1198929
    assert_reported_value_identity(report)


def test_named_rates_leave_the_rollup_conserved_and_the_posture_ok():
    """The award side, the notified winner and the 47500 air cost roll up to 1490674.

    PRD §3.7: "`committed_budget_cents` is the award side plus the air side, and
    `budget_headroom_cents` is `budget_total_cents` less `committed_budget_cents`
    — a figure that may legitimately be negative."

    Design: Corner/calculations/named_constants_drive_committed_cost_exclusion_deviation_and_gross_up_rates
    """
    scenario = _named_constants_scenario()
    program = scenario["program"]

    assert program["committed_budget_cents"] == 1490674
    assert program["budget_headroom_cents"] == 3509326
    assert program["budget_posture"] == "OK"
    assert program["budget_total_cents"] == 5000000
    assert_budget_conserved(program)


def _posture_boundary_scenario():
    """A 921765-cent program whose single adjudicated winner was reviewed before
    any cost basis existed, with a proposed contract and its full deposit schedule."""
    program = create_program(budget_total_cents=921765)
    program_id = program["id"]
    create_award_tier(program_id, **PLATINUM_TIER)
    create_award_tier(program_id, **GOLD_TIER)
    destination = setup_shortlisted_destination(program_id, dict(LISBON))

    ana = create_qualifier(program_id, **ANA)
    review_qualifier(ana["id"])
    ben = create_qualifier(program_id, **BEN)  # deliberately left PENDING_REVIEW

    advance_program(program_id, "SOURCING")
    contract = create_contract(program_id, destination["id"], **HOTEL_FIVE_NIGHTS)
    for spec in DEPOSIT_SCHEDULE:
        create_milestone(contract["id"], **spec)
    propose_contract(contract["id"])

    return {
        "program": read_program(program_id),
        "program_id": program_id,
        "contract": contract,
        "ana": ana,
        "ben": ben,
    }


def test_rollup_before_execution_carries_only_the_upgrade_allowance():
    """With no cost basis yet, the award commitment is the bare 150000 allowance.

    PRD §3.2: "Its per-person basis is the program's
    `per_person_cost_basis_cents`, which is 0 until a hotel contract has been
    executed (§3.4) and is the selected destination's per-person land cost
    thereafter."

    Design: Corner/calculations/budget_rollup_running_total_crosses_the_posture_boundary_on_each_add
    """
    scenario = _posture_boundary_scenario()
    program = scenario["program"]

    assert program["per_person_cost_basis_cents"] == 0
    assert program["committed_budget_cents"] == 150000
    assert program["budget_headroom_cents"] == 771765
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)


def test_utilization_at_exact_parity_still_reads_watch_and_flags_no_milestone():
    """The recomputed award hits the budget exactly: 10000 bp is WATCH, not OVERCOMMITTED.

    PRD §3.7: "`budget_posture` is `OK` when utilization is at most 8500 basis
    points (85 percent), `WATCH` when it is above that but at most 10000 basis
    points, and `OVERCOMMITTED` above 10000."

    Design: Corner/calculations/budget_rollup_running_total_crosses_the_posture_boundary_on_each_add
    """
    scenario = _posture_boundary_scenario()
    execute_contract(scenario["contract"]["id"])

    program = read_program(scenario["program_id"])

    assert program["per_person_cost_basis_cents"] == 431757
    assert program["committed_budget_cents"] == 921765
    assert program["budget_headroom_cents"] == 0
    assert program["budget_posture"] == "WATCH"
    assert_budget_conserved(program)

    rows, meta = validate_paginated(
        api_client.list_deposit_milestones(
            APPROVER, params={"contract_id": scenario["contract"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert [row["requires_finance_review"] for row in rows] == [False, False, False]


def test_second_adjudication_tips_the_running_total_to_overcommitted():
    """Adding a second winner drives the headroom negative and the posture over.

    PRD §2.10: "The program's `committed_budget_cents` plus its
    `budget_headroom_cents` always equals its `budget_total_cents`, even when the
    headroom is negative."

    Design: Corner/calculations/budget_rollup_running_total_crosses_the_posture_boundary_on_each_add
    """
    scenario = _posture_boundary_scenario()
    execute_contract(scenario["contract"]["id"])

    ben = validate_success(api_client.review_qualifier(scenario["ben"]["id"], ANALYST))

    assert ben["award_status"] == "QUALIFIED"
    assert ben["committed_cost_cents"] == 521409

    program = read_program(scenario["program_id"])
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == -521409
    assert program["budget_posture"] == "OVERCOMMITTED"
    assert_budget_conserved(program)

    rows, _ = validate_paginated(
        api_client.list_deposit_milestones(
            APPROVER, params={"contract_id": scenario["contract"]["id"]}
        )
    )
    assert [row["requires_finance_review"] for row in rows] == [False, False, False]


def test_utilization_truncates_a_fractional_boundary_down_into_ok():
    """A utilization of 8500.5 basis points floors to 8500 and stays OK.

    PRD §3.7: "Utilization is then measured in basis points: it is 0 when
    `budget_total_cents` is 0, and otherwise `committed_budget_cents` multiplied
    by 10000, divided by `budget_total_cents`, using **integer floor division**
    so that the 10000-basis-point mark is reached only at or beyond exact parity."

    Design: Corner/calculations/budget_rollup_running_total_crosses_the_posture_boundary_on_each_add
    """
    base = setup_qualified_qualifier(
        qualifier_overrides=dict(ANA),
        **_canonical_program_kwargs(1084365),
    )

    program = base["program"]

    assert base["qualifier"]["committed_cost_cents"] == 921765
    assert program["budget_total_cents"] == 1084365
    assert program["committed_budget_cents"] == 921765
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)


def test_utilization_one_basis_point_above_the_watch_threshold_reads_watch():
    """A utilization of 8501 basis points is above 8500 and reads WATCH.

    PRD §3.7: "`budget_posture` is `OK` when utilization is at most 8500 basis
    points (85 percent), `WATCH` when it is above that but at most 10000 basis
    points, and `OVERCOMMITTED` above 10000."

    Design: Corner/calculations/budget_rollup_running_total_crosses_the_posture_boundary_on_each_add
    """
    base = setup_qualified_qualifier(
        qualifier_overrides=dict(ANA),
        **_canonical_program_kwargs(1084300),
    )

    program = base["program"]

    assert base["qualifier"]["committed_cost_cents"] == 921765
    assert program["budget_total_cents"] == 1084300
    assert program["committed_budget_cents"] == 921765
    assert program["budget_posture"] == "WATCH"
    assert_budget_conserved(program)


def _every_registration_kind_scenario():
    """RECONCILED program with two winner seats and one linked guest seat, all
    travelled and all surveyed, and no air spend anywhere."""
    base = _registration_open_cohort([ANA, BEN])
    program_id = base["program"]["id"]
    ana, ben = base["qualifiers"]

    ana_seat = create_registration(ana["id"], program_id=program_id, **STAY)
    guest_seat = create_registration(
        ana["id"], program_id=program_id, registration_kind="GUEST",
        guest_of_registration_id=ana_seat["id"], **STAY
    )
    ben_seat = create_registration(ben["id"], program_id=program_id, **STAY)

    for seat, qualifier in ((ana_seat, ana), (guest_seat, ana), (ben_seat, ben)):
        respond_registration(seat["id"], qualifier["id"], "ACCEPT", waiver_signed=True)
        confirm_registration(seat["id"])

    advance_program(program_id, "ONSITE")
    survey_registration(ana_seat["id"], 9)
    survey_registration(ben_seat["id"], 8)
    survey_registration(guest_seat["id"], 10)
    advance_program(program_id, "RECONCILED")

    return {
        "program": read_program(program_id),
        "contract": read_contract(base["contract"]["id"]),
        "ana": read_qualifier(ana["id"]),
        "ben": read_qualifier(ben["id"]),
        "ana_seat": read_registration(ana_seat["id"]),
        "guest_seat": read_registration(guest_seat["id"]),
        "ben_seat": read_registration(ben_seat["id"]),
    }


def test_satisfaction_index_counts_the_guest_seat_alongside_the_winners():
    """Scores of 9, 8 and 10 across two winners and a guest average to exactly 9.0.

    PRD §3.9: "Satisfaction is measured over every registration of the program
    carrying a non-null `satisfaction_score`, regardless of `registration_kind`,
    so a guest's opinion counts as much as a winner's."

    Design: Corner/calculations/measurement_aggregates_then_rates_and_scores_every_registration_kind
    """
    scenario = _every_registration_kind_scenario()

    measurement = read_measurement(scenario["program"]["id"])

    assert measurement["survey_count"] == 3
    assert measurement["satisfaction_index"] == 9.0


def test_lift_is_the_aggregate_rate_and_never_the_mean_of_per_winner_rates():
    """Summed metrics give 38.33; averaging the two per-winner rates would give 36.81.

    PRD §3.9: "The rule is **aggregate then rate, never rate then average**: the
    lift comes from the summed metrics of the cohort, not from the mean of
    per-qualifier lift percentages."

    Design: Corner/calculations/measurement_aggregates_then_rates_and_scores_every_registration_kind
    """
    scenario = _every_registration_kind_scenario()

    measurement = read_measurement(scenario["program"]["id"])

    assert measurement["baseline_metric_total"] == 300000000
    assert measurement["actual_metric_total"] == 415000000
    assert measurement["sales_lift_pct"] == 38.33
    assert measurement["sales_lift_pct"] != 36.81
    assert scenario["program"]["sales_lift_pct"] == 38.33


def test_guest_seat_adds_nothing_to_the_travelling_cohort():
    """The guest travels and is surveyed, but the cohort is still the two winners.

    PRD §3.9: "Sales lift is measured over the **travelling cohort only**: the
    qualifiers of the program whose `award_status` is exactly `TRAVELLED`,
    excluding anyone `DISQUALIFIED`, `WITHDRAWN` or merely `NOTIFIED`."

    Design: Corner/calculations/measurement_aggregates_then_rates_and_scores_every_registration_kind
    """
    scenario = _every_registration_kind_scenario()
    measurement = read_measurement(scenario["program"]["id"])

    assert measurement["travelled_count"] == 2
    assert measurement["qualified_count"] == 2

    guest_rows, guest_meta = validate_paginated(
        api_client.list_registrations(
            DESK,
            params={"program_id": scenario["program"]["id"], "registration_kind": "GUEST"},
        )
    )
    assert guest_meta["total_count"] == 1
    assert guest_rows[0]["attendance_status"] == "TRAVELLED"
    assert guest_rows[0]["guest_of_registration_id"] == scenario["ana_seat"]["id"]
    assert guest_rows[0]["qualifier_id"] == scenario["ana"]["id"]
    assert guest_rows[0]["room_nights"] == 5
    assert guest_rows[0]["satisfaction_score"] == 10

    travelled_rows, travelled_meta = validate_paginated(
        api_client.list_qualifiers(
            ANALYST,
            params={"program_id": scenario["program"]["id"], "award_status": "TRAVELLED"},
        )
    )
    assert travelled_meta["total_count"] == 2
    assert sorted(row["employee_code"] for row in travelled_rows) == ["S-1001", "S-2001"]


def test_three_travelled_rooms_leave_the_award_side_alone_and_price_the_shortfall():
    """No air spend keeps the rollup at 1443174 while 15 room-nights expose 1270500.

    PRD §3.7: "Its award side is the sum of `committed_cost_cents` over the
    program's qualifiers whose `award_status` is `QUALIFIED`, `NOTIFIED`,
    `REGISTERED` or `TRAVELLED`; qualifiers who are `PENDING_REVIEW`,
    `DISQUALIFIED` or `WITHDRAWN` are excluded."

    Design: Corner/calculations/measurement_aggregates_then_rates_and_scores_every_registration_kind
    """
    scenario = _every_registration_kind_scenario()
    program = scenario["program"]

    assert scenario["guest_seat"]["cost_cents"] == 0
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == 3556826
    assert_budget_conserved(program)

    projection = read_exposure_projection(scenario["contract"]["id"])
    assert projection["room_nights_confirmed"] == 15
    assert projection["shortfall_room_nights"] == 33
    assert projection["binding_exposure_cents"] == 1270500
    assert_room_nights_conserved(scenario["contract"])


def _none_policy_scenario():
    """RECONCILED program under a locked NONE gross-up policy with one traveller."""
    return _reconciled_cohort([BEN], gross_up_policy="NONE")


def test_policy_none_is_recorded_and_locked_like_any_other_decision():
    """Choosing NONE is a decision, not an absence: the lock is set all the same.

    PRD §3.1: "A `ProgramDirector` records the decision by supplying
    `gross_up_policy` as `NONE`, `FLAT_SUPPLEMENTAL` or `FULL_GROSS_UP`; the value
    is stored and `gross_up_policy_locked` is set to true in the same step, and
    the program's `version` increments."

    Design: Corner/calculations/no_gross_up_variant_is_selected_and_snapshotted_when_policy_is_none
    """
    base = _none_policy_scenario()
    program = base["program"]

    assert program["gross_up_policy"] == "NONE"
    assert program["gross_up_policy_locked"] is True
    assert base["qualifier"]["taxable_award_cents"] == 443198


def test_draft_snapshots_the_none_method_and_reports_the_bare_award():
    """Under NONE the employer adds nothing, so the reported value is the award itself.

    PRD §3.9: "With a `gross_up_method` of `NONE`, the employer contributes
    nothing: `combined_rate_bp` and `gross_up_cents` are both 0 and
    `reported_value_cents` equals `award_value_cents`."

    Design: Corner/calculations/no_gross_up_variant_is_selected_and_snapshotted_when_policy_is_none
    """
    base = _none_policy_scenario()

    report = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(base["qualifier"]["id"], 2026),
            TEST_USERS["tax_officer_headers"],
        ),
        201,
    )

    assert report["status"] == "DRAFT"
    assert report["award_value_cents"] == 443198
    assert report["gross_up_method"] == "NONE"
    assert report["combined_rate_bp"] == 0
    assert report["gross_up_cents"] == 0
    assert report["reported_value_cents"] == 443198
    assert report["reported_value_cents"] != 540702
    assert report["reported_value_cents"] != 658052
    assert_reported_value_identity(report)


def test_report_list_filters_on_the_snapshotted_gross_up_method():
    """The snapshotted method is a first-class filter on the report collection.

    PRD §2.3: "Tax award reports may be filtered by `qualifier_id`, `tax_year`,
    `status` and `gross_up_method`."

    Design: Corner/calculations/no_gross_up_variant_is_selected_and_snapshotted_when_policy_is_none
    """
    base = _none_policy_scenario()
    report = draft_tax_report(base["qualifier"]["id"], 2026)

    rows, meta = validate_paginated(
        api_client.list_tax_award_reports(
            TEST_USERS["tax_officer_headers"],
            params={"qualifier_id": base["qualifier"]["id"], "gross_up_method": "NONE"},
        )
    )

    assert meta["total_count"] == 1
    assert rows[0]["id"] == report["id"]
    assert rows[0]["gross_up_method"] == "NONE"


def test_drafting_leaves_the_tax_dimension_and_the_program_total_untouched():
    """Only filing moves money and status; a draft on its own changes neither.

    PRD §3.9: "The report lands in `DRAFT` with a null `filed_by_user_id`,
    `filed_at`, `voided_by_user_id` and `void_reason`."

    Design: Corner/calculations/no_gross_up_variant_is_selected_and_snapshotted_when_policy_is_none
    """
    base = _none_policy_scenario()
    report = draft_tax_report(base["qualifier"]["id"], 2026)

    assert report["filed_by_user_id"] is None
    assert report["filed_at"] is None
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "PENDING_REPORT"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0


def _flat_filed_scenario():
    """RECONCILED program under FLAT_SUPPLEMENTAL whose one traveller has a FILED report."""
    return setup_filed_tax_report(
        gross_up_policy="FLAT_SUPPLEMENTAL",
        qualifier_specs=[dict(BEN)],
        registration_overrides=dict(STAY),
        **_canonical_program_kwargs(),
    )


def test_filed_flat_supplemental_report_adds_its_snapshot_to_the_program_total():
    """The flat policy grosses 443198 up by 2200 bp to 540702, which filing adds.

    PRD §3.9: "`combined_rate_bp` is 2200, and `gross_up_cents` is
    `award_value_cents` multiplied by 2200, divided by 10000, rounded half up to a
    whole cent."

    Design: Corner/calculations/gross_up_variant_cannot_switch_so_the_reconciliation_delta_is_always_zero
    """
    base = _flat_filed_scenario()
    report = base["report"]

    assert report["status"] == "FILED"
    assert report["award_value_cents"] == 443198
    assert report["gross_up_method"] == "FLAT_SUPPLEMENTAL"
    assert report["combined_rate_bp"] == 2200
    assert report["gross_up_cents"] == 97504
    assert report["reported_value_cents"] == 540702
    assert report["filed_by_user_id"] == USER_IDS["TAX_OFFICER"]
    assert_reported_value_identity(report)
    assert base["qualifier"]["tax_status"] == "REPORTED"
    assert base["program"]["reported_award_total_cents"] == 540702


def test_a_locked_gross_up_policy_refuses_to_switch_variant():
    """A second policy submission is refused, so no report can straddle two variants.

    PRD §3.1: "The decision is accepted exactly once — a second submission,
    whatever value it carries, is rejected with `ERR_GROSS_UP_POLICY_LOCKED`."

    Design: Corner/calculations/gross_up_variant_cannot_switch_so_the_reconciliation_delta_is_always_zero
    """
    base = setup_contracted_program(**_canonical_program_kwargs())
    program_id = base["program"]["id"]
    lock_gross_up_policy(program_id, "FLAT_SUPPLEMENTAL")

    response = api_client.set_gross_up_policy(
        program_id, gross_up_policy_payload("FULL_GROSS_UP"), DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_GROSS_UP_POLICY_LOCKED)
    program = read_program(program_id)
    assert program["gross_up_policy"] == "FLAT_SUPPLEMENTAL"
    assert program["gross_up_policy_locked"] is True


def test_voiding_subtracts_exactly_what_filing_added():
    """The void takes 540702 straight back out and leaves the snapshot untouched.

    PRD §3.9: "Voiding stamps `voided_by_user_id` and `void_reason`, moves the
    qualifier's `tax_status` `REPORTED → VOIDED`, and subtracts the report's
    `reported_value_cents` from the program's `reported_award_total_cents` — an
    exact compensation, so that `reported_award_total_cents` always equals the sum
    of `reported_value_cents` over the program's reports that are currently
    `FILED`."

    Design: Corner/calculations/gross_up_variant_cannot_switch_so_the_reconciliation_delta_is_always_zero
    """
    base = _flat_filed_scenario()

    voided = void_tax_report(base["report"]["id"], reason="Filed against the wrong tax year")

    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == USER_IDS["TAX_OFFICER_ALT"]
    assert voided["voided_by_user_id"] != base["report"]["filed_by_user_id"]
    assert voided["reported_value_cents"] == 540702
    assert voided["award_value_cents"] == 443198
    assert voided["gross_up_method"] == "FLAT_SUPPLEMENTAL"

    qualifier = read_qualifier(base["qualifier"]["id"])
    assert qualifier["tax_status"] == "VOIDED"
    assert qualifier["award_status"] == "TRAVELLED"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0


def test_replacement_draft_reproduces_the_identical_variant_snapshot():
    """The redraft snapshots the same locked policy, so the reconciliation delta is 0.

    PRD §3.9: "If the qualifier's `tax_status` was `VOIDED` at that moment,
    drafting a replacement moves it `VOIDED → PENDING_REPORT`, which is what
    closes the tax cycle and lets a mis-filed award be corrected before the
    program is closed."

    Design: Corner/calculations/gross_up_variant_cannot_switch_so_the_reconciliation_delta_is_always_zero
    """
    base = _flat_filed_scenario()
    void_tax_report(base["report"]["id"])

    replacement = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(base["qualifier"]["id"], 2026),
            TEST_USERS["tax_officer_headers"],
        ),
        201,
    )

    assert replacement["id"] != base["report"]["id"]
    assert replacement["status"] == "DRAFT"
    assert replacement["award_value_cents"] == 443198
    assert replacement["gross_up_method"] == "FLAT_SUPPLEMENTAL"
    assert replacement["combined_rate_bp"] == 2200
    assert replacement["gross_up_cents"] == 97504
    assert replacement["reported_value_cents"] == 540702
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "PENDING_REPORT"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0
