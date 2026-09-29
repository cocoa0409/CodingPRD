"""Arithmetic branches: scoring, cell selection, valuation, reporting, cancellation and loss of use."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import (
    ACTUARY,
    ADJUSTER,
    MANAGER,
    MANAGER_USER_ID,
    UNDERWRITER,
)
from test_helpers.types import Ledger


def test_the_guard_is_worth_two_controls_and_every_tier_cutoff_is_inclusive(api):
    """Four control sets score 0, 2, 3 and 5 and land in four different tiers.

    PRD: The `security_score` is the sum of their weights: one point each for fencing, lighting and alarm monitoring, and two points for the guard, because a live guard is worth two controls.
    PRD: The `security_tier` follows from the score by inclusive cutoffs: a score of at least 5 is `TIER_3`, otherwise a score of at least 3 is `TIER_2`, otherwise a score of at least 1 is `TIER_1`, and a score of 0 is `TIER_0`.
    PRD: A new site opens with `status` `UNSURVEYED`, `security_score` 0, `security_tier` `TIER_0`, `active_floater_count` 0 and a null `surveyed_at`.
    Design: Corner/calculations/corner_jobsite_security_tier_weighted_scoring
    """
    bare = fixtures.create_jobsite(api, name="Bare Lot")
    guarded = fixtures.create_jobsite(api, name="Guard Only")
    unweighted = fixtures.create_jobsite(api, name="Three Controls")
    full = fixtures.create_jobsite(api, name="Full Controls")
    for fresh in (bare, guarded, unweighted, full):
        assert fresh["security_score"] == 0
        assert fresh["security_tier"] == "TIER_0"
        assert fresh["status"] == "UNSURVEYED"
        assert fresh["surveyed_at"] is None
        assert fresh["active_floater_count"] == 0

    nothing = validate_success(api.record_security_survey(
        bare["id"], factories.security_survey(), UNDERWRITER))

    assert nothing["security_score"] == 0
    assert nothing["security_tier"] == "TIER_0"
    assert nothing["status"] == "SURVEYED"

    guard_only = fixtures.survey_jobsite(api, guarded["id"],
                                         dict(guarded_24h=True))
    assert guard_only["security_score"] == 2
    assert guard_only["security_tier"] == "TIER_1"

    three = fixtures.survey_jobsite(api, unweighted["id"],
                                    factories.SURVEY_TIER_2)
    assert three["security_score"] == 3
    assert three["security_tier"] == "TIER_2"

    perfect = fixtures.survey_jobsite(api, full["id"], factories.SURVEY_TIER_3)
    assert perfect["security_score"] == 5
    assert perfect["security_tier"] == "TIER_3"
    assert perfect["active_floater_count"] == 0
    assert_instant_equals(perfect["surveyed_at"], "2026-08-01T00:00:00Z")


def test_a_drafted_cell_is_invisible_to_rating_until_the_moment_it_is_published(api):
    """The band that matches is unpublished and the band that is published does not match.

    PRD: `DRAFT` and `RETIRED` cells never enter the candidate set even when their band matches. If the candidate set is empty the rating is rejected with `ERR_NO_PUBLISHED_RATE_RULE`.
    PRD: The part's own derived fields open at their base values: `aggregate_available_cents` equal to `aggregate_limit_cents`, `aggregate_paid_net_cents` at 0, `earned_reported_premium_cents` at 0, `rated_premium_cents` at 0, and `deposit_premium_cents` and `latest_report_period_end_date` both null.
    Design: Corner/calculations/corner_rate_rule_selection_ignores_draft_and_honours_age_band
    """
    fixtures.draft_rate_rule(api, age_band_min_years=0, age_band_max_years=5,
                             base_rate_bp=180, theft_hazard_grade="A")
    fixtures.publish_rate_rule(api, age_band_min_years=6, age_band_max_years=12,
                               base_rate_bp=150, theft_hazard_grade="B")
    policy = fixtures.create_policy(api, policyholder_name="Draft Cell Contracting",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(api, policy["id"],
                               factories.scheduled_equipment_part())
    version = fixtures.policy_version(api, policy["id"])

    refused = api.create_equipment_item(
        part["id"],
        factories.equipment_item(expected_policy_version=version,
                                 description="Mini excavator", model_year=2024,
                                 original_cost_cents=1000000),
        UNDERWRITER)

    validate_error(refused, "ERR_NO_PUBLISHED_RATE_RULE", 422)
    assert get_success_data(api.get_coverage_part(
        part["id"], UNDERWRITER))["rated_premium_cents"] == 0
    _, meta = validate_paginated(api.list_part_equipment_items(
        part["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 0
    assert fixtures.policy_version(api, policy["id"]) == version


def test_publishing_the_matching_cell_makes_the_identical_schedule_add_succeed(api):
    """The age-2 unit rates on the freshly published 0-5 cell at 180 basis points.

    PRD: Publishing a cell moves it `DRAFT` → `PUBLISHED` and stamps `published_at` from the logical clock.
    PRD: Under `ACV`, the unit depreciates 800 basis points — 8 percent — of its original cost for each whole year of `age_years_at_rating`; the retained proportion is ten thousand basis points less that depreciation, but never less than a floor of 2,000 basis points, so a unit that is ten years old or older retains exactly 20 percent; `insured_value_cents` is then the original cost multiplied by the retained proportion, divided by ten thousand, and rounded half-up once.
    Design: Corner/calculations/corner_rate_rule_selection_ignores_draft_and_honours_age_band
    """
    draft = fixtures.draft_rate_rule(api, age_band_min_years=0,
                                     age_band_max_years=5, base_rate_bp=180,
                                     theft_hazard_grade="A")
    fixtures.publish_rate_rule(api, age_band_min_years=6, age_band_max_years=12,
                               base_rate_bp=150, theft_hazard_grade="B")
    policy = fixtures.create_policy(api, policyholder_name="Draft Cell Contracting",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(api, policy["id"],
                               factories.scheduled_equipment_part())
    version = fixtures.policy_version(api, policy["id"])
    validate_error(api.create_equipment_item(
        part["id"],
        factories.equipment_item(expected_policy_version=version,
                                 description="Mini excavator", model_year=2024,
                                 original_cost_cents=1000000),
        UNDERWRITER), "ERR_NO_PUBLISHED_RATE_RULE", 422)

    published = validate_success(api.publish_rate_rule(draft["id"], ACTUARY))

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00Z")

    item = validate_success(api.create_equipment_item(
        part["id"],
        factories.equipment_item(expected_policy_version=version,
                                 description="Mini excavator", model_year=2024,
                                 original_cost_cents=1000000),
        UNDERWRITER), 201)

    assert item["applied_rate_rule_id"] == draft["id"]
    assert item["age_years_at_rating"] == 2
    assert item["applied_base_rate_bp"] == 180
    assert item["insured_value_cents"] == 840000
    assert item["rated_premium_cents"] == 17842
    assert get_success_data(api.get_coverage_part(
        part["id"], UNDERWRITER))["rated_premium_cents"] == 17842


def test_the_actual_cash_value_decay_stops_dead_at_two_thousand_basis_points(api):
    """Ages 5, 10 and 11 on one cost: 2400000, 800000 and 800000 again.

    PRD: Under `ACV`, the unit depreciates 800 basis points — 8 percent — of its original cost for each whole year of `age_years_at_rating`; the retained proportion is ten thousand basis points less that depreciation, but never less than a floor of 2,000 basis points, so a unit that is ten years old or older retains exactly 20 percent; `insured_value_cents` is then the original cost multiplied by the retained proportion, divided by ten thousand, and rounded half-up once.
    PRD: On the scheduled basis a part's `rated_premium_cents` is the plain integer-cent sum of `rated_premium_cents` over the equipment items on the part whose `status` is `RATED` or `ACTIVE`.
    Design: Corner/calculations/corner_equipment_insured_value_depreciation_floor
    """
    young = fixtures.publish_rate_rule(api, age_band_min_years=0,
                                       age_band_max_years=5, base_rate_bp=180,
                                       theft_hazard_grade="A")
    aged = fixtures.publish_rate_rule(api, age_band_min_years=6,
                                      age_band_max_years=30, base_rate_bp=150,
                                      theft_hazard_grade="B")
    policy = fixtures.create_policy(api, policyholder_name="Decay Fleet Services",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())

    five = fixtures.schedule_item(api, part["id"], policy["id"],
                                  description="Excavator age 5", model_year=2021,
                                  original_cost_cents=4000000)
    ten = fixtures.schedule_item(api, part["id"], policy["id"],
                                 description="Excavator age 10", model_year=2016,
                                 original_cost_cents=4000000)
    eleven = fixtures.schedule_item(api, part["id"], policy["id"],
                                    description="Excavator age 11",
                                    model_year=2015, original_cost_cents=4000000)

    assert five["age_years_at_rating"] == 5
    assert five["applied_rate_rule_id"] == young["id"]
    assert five["insured_value_cents"] == 2400000
    assert five["rated_premium_cents"] == 50976
    assert ten["age_years_at_rating"] == 10
    assert ten["applied_rate_rule_id"] == aged["id"]
    assert ten["insured_value_cents"] == 800000
    assert ten["rated_premium_cents"] == 13200
    assert eleven["age_years_at_rating"] == 11
    assert eleven["applied_rate_rule_id"] == aged["id"]
    assert eleven["insured_value_cents"] == 800000
    assert eleven["rated_premium_cents"] == 13200
    assert get_success_data(api.get_coverage_part(
        part["id"], UNDERWRITER))["rated_premium_cents"] == 77376

    quoted = validate_success(api.quote_policy(policy["id"], UNDERWRITER))

    assert quoted["sum_of_part_premiums_cents"] == 77376
    assert quoted["written_premium_cents"] == 80471
    assert quoted["total_insured_value_cents"] == 4000000
    assert quoted["referral_required"] is False


def test_all_four_valuation_bases_run_side_by_side_on_one_schedule(api):
    """Agreed value ignores age, replacement cost indexes up, stated amount takes the lesser.

    PRD: Under `AGREED_VALUE`, `insured_value_cents` is simply `stated_value_cents`, untouched by age and untouched by the rate cell — the only basis immune to both. Under `STATED_AMOUNT`, `insured_value_cents` is the lesser of `stated_value_cents` and the indexed figure computed exactly as in the replacement-cost branch.
    PRD: Where `geo_tracker_installed` is omitted it is false; where `ownership` is omitted it is `OWNED`; where the item-level `valuation_basis` is omitted the parent part's `valuation_basis` is copied onto the item at creation, so the item always carries an explicit basis afterwards.
    PRD: The third is a valuation factor keyed on the effective basis: 10,000 basis points for `ACV`, 11,500 for `REPLACEMENT_COST`, 12,500 for `AGREED_VALUE` and 10,800 for `STATED_AMOUNT`.
    Design: Corner/calculations/corner_valuation_basis_four_branches_diverge_on_one_cost
    """
    fixtures.publish_rate_rule(api, equipment_type="CRANE", age_band_min_years=0,
                               age_band_max_years=5, base_rate_bp=310,
                               theft_hazard_grade="B")
    fixtures.publish_rate_rule(api, equipment_type="LOADER", age_band_min_years=6,
                               age_band_max_years=12, base_rate_bp=205,
                               theft_hazard_grade="B",
                               replacement_cost_index_bp=11000)
    policy = fixtures.create_policy(api, policyholder_name="Four Basis Rigging",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part(
                                    per_item_limit_cents=100000000))

    agreed = fixtures.schedule_item(api, part["id"], policy["id"],
                                    description="Tower crane on agreed value",
                                    equipment_type="CRANE", model_year=2024,
                                    original_cost_cents=30000000,
                                    valuation_basis="AGREED_VALUE",
                                    stated_value_cents=60000000)
    replacement = fixtures.schedule_item(api, part["id"], policy["id"],
                                         description="Loader on replacement cost",
                                         equipment_type="LOADER", model_year=2016,
                                         original_cost_cents=4000000,
                                         valuation_basis="REPLACEMENT_COST")
    stated = fixtures.schedule_item(api, part["id"], policy["id"],
                                    description="Loader on stated amount",
                                    equipment_type="LOADER", model_year=2016,
                                    original_cost_cents=4000000,
                                    valuation_basis="STATED_AMOUNT",
                                    stated_value_cents=3500000)
    inherited = fixtures.schedule_item(api, part["id"], policy["id"],
                                       description="Loader inheriting part basis",
                                       equipment_type="LOADER", model_year=2016,
                                       original_cost_cents=4000000)

    assert agreed["valuation_basis"] == "AGREED_VALUE"
    assert agreed["insured_value_cents"] == 60000000
    assert agreed["applied_base_rate_bp"] == 310
    assert agreed["rated_premium_cents"] == 2557500
    assert replacement["insured_value_cents"] == 4400000
    assert replacement["rated_premium_cents"] == 114103
    assert stated["insured_value_cents"] == 3500000
    assert stated["rated_premium_cents"] == 85239
    assert inherited["valuation_basis"] == "ACV"
    assert inherited["insured_value_cents"] == 800000
    assert inherited["rated_premium_cents"] == 18040

    whole = get_success_data(api.get_coverage_part(part["id"], UNDERWRITER))

    assert whole["rated_premium_cents"] == 2774882
    assert whole["valuation_basis"] == "ACV"
    policy_now = get_success_data(api.get_policy(policy["id"], UNDERWRITER))
    assert policy_now["total_insured_value_cents"] == 68700000
    assert policy_now["referral_required"] is True


def test_a_thirty_day_period_earns_the_annual_rate_pro_rated_and_files_in_time(api):
    """24658 cents on 12000000 declared, and the fifteen-day grace keeps the penalty off.

    PRD: A filed report has `period_days` equal to the whole days from `period_start_date` to `period_end_date` plus one — both endpoints count — and a `due_date` fifteen days after `period_end_date`, that being the reporting grace period.
    PRD: The period premium is `reported_value_cents` multiplied by the part's `reporting_annual_rate_bp` and by `period_days`, divided by ten thousand for the basis points and by 365 for the annualisation, rounded half-up once; a month with more days therefore earns more premium on the same declared value.
    PRD: Lateness is then decided on the calendar date of `submitted_at` against `due_date`: a submission whose date falls on or before the `due_date` is timely, and only a submission strictly after it is late.
    PRD: The timely branch moves the report `SUBMITTED` → `ACCEPTED`, sets `late_penalty_cents` to zero, and appends exactly one ledger entry, a `REPORTING_ADJUSTMENT` for the positive `period_earned_premium_cents`.
    Design: Corner/calculations/corner_reporting_period_earned_premium_timely_filing
    """
    ctx = fixtures.build_reporting_file(
        api, policy_kwargs=dict(policyholder_name="Timely Inventory Co",
                                minimum_premium_cents=100000))
    opening = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert opening["written_premium_cents"] == 100000
    assert opening["premium_balance_cents"] == 100000
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["deposit_premium_cents"] == 0
    fixtures.set_clock(api, "2026-10-10T00:00:00Z")
    version = fixtures.part_version(api, ctx.part_id)

    filed = validate_success(api.create_value_report(
        ctx.part_id,
        factories.value_report("2026-09-01", "2026-09-30", 12000000, version),
        ctx["policyholder"]), 201)

    assert filed["status"] == "SUBMITTED"
    assert filed["period_days"] == 30
    assert filed["due_date"] == "2026-10-15"
    assert filed["period_earned_premium_cents"] == 0
    assert filed["late_penalty_cents"] == 0
    assert_instant_equals(filed["submitted_at"], "2026-10-10T00:00:00Z")

    adjudicated = validate_success(
        api.adjudicate_value_report(filed["id"], UNDERWRITER))

    assert adjudicated["status"] == "ACCEPTED"
    assert adjudicated["period_earned_premium_cents"] == 24658
    assert adjudicated["late_penalty_cents"] == 0
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["earned_reported_premium_cents"] == 24658
    assert part["latest_report_period_end_date"] == "2026-09-30"
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["premium_balance_cents"] == 124658
    assert policy["status"] == "IN_FORCE"

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.PREMIUM))
    assert meta["total_count"] == 2
    booked = find_entry(rows, "REPORTING_ADJUSTMENT")
    assert booked["amount_cents"] == 24658
    assert booked["ledger"] == "PREMIUM"


def two_identical_files_on_risk(api):
    """Two policies priced at 180251 apiece, differing only in the name on the file."""
    fixtures.publish_rate_rule(api)
    files = []
    for name in ("Short Rate Excavating", "Pro Rata Excavating"):
        policy = fixtures.create_policy(api, policyholder_name=name)
        part = fixtures.create_part(api, policy["id"],
                                   factories.scheduled_equipment_part())
        fixtures.schedule_item(api, part["id"], policy["id"],
                               description="Excavator " + name)
        fixtures.quote(api, policy["id"])
        fixtures.bind(api, policy["id"])
        fixtures.activate(api, policy["id"])
        files.append(fixtures.Ctx(policy_id=policy["id"], part_id=part["id"]))
    return files


def test_the_reason_code_alone_decides_whether_the_short_rate_penalty_is_kept(api):
    """One date, one written premium, two returns: 121336 against 134818.

    PRD: The pro-rata return is `written_premium_cents` multiplied by `unearned_days`, divided by `term_days`, rounded half-up once. When the `cancellation_reason` is `INSURED_REQUEST` the insurer keeps a short-rate penalty of 10 percent: the amount actually returned is 9,000 basis points of the already-rounded pro-rata figure, divided by ten thousand and rounded half-up a second time.
    PRD: When the reason is `NON_REPORTING` or `UNDERWRITING` — both insurer-initiated — the full pro-rata figure is returned with no second rounding.
    PRD: The two roundings happen in that pinned order: pro-rata first, short-rate penalty second, applied to the already-rounded pro-rata figure.
    PRD: The returned amount is booked as a `CANCELLATION_RETURN` entry in the premium ledger with a negative `amount_cents`, `premium_balance_cents` is recomputed, and `cancellation_reason` and `cancel_effective_date` are stored on the policy.
    Design: Corner/calculations/corner_cancellation_short_rate_versus_pro_rata
    """
    short_rate, pro_rata = two_identical_files_on_risk(api)
    for one in (short_rate, pro_rata):
        opening = get_success_data(api.get_policy(one.policy_id, UNDERWRITER))
        assert opening["status"] == "IN_FORCE"
        assert opening["term_days"] == 365
        assert opening["written_premium_cents"] == 180251
        assert opening["premium_balance_cents"] == 180251

    kept = validate_success(api.cancel_policy(
        short_rate.policy_id,
        factories.cancellation("INSURED_REQUEST", "2026-11-01"), MANAGER))
    returned = validate_success(api.cancel_policy(
        pro_rata.policy_id,
        factories.cancellation("UNDERWRITING", "2026-11-01"), MANAGER))

    assert kept["status"] == "CANCELLED"
    assert kept["cancellation_reason"] == "INSURED_REQUEST"
    assert kept["cancel_effective_date"] == "2026-11-01"
    assert kept["premium_balance_cents"] == 58915
    assert returned["cancellation_reason"] == "UNDERWRITING"
    assert returned["premium_balance_cents"] == 45433

    kept_row = find_entry(fixtures.premium_ledger(api, short_rate.policy_id),
                          "CANCELLATION_RETURN")
    returned_row = find_entry(fixtures.premium_ledger(api, pro_rata.policy_id),
                              "CANCELLATION_RETURN")
    assert kept_row["amount_cents"] == -121336
    assert returned_row["amount_cents"] == -134818
    assert returned_row["amount_cents"] - kept_row["amount_cents"] == -13482
    assert get_success_data(api.get_coverage_part(
        short_rate.part_id, UNDERWRITER))["status"] == "VOID"
    assert get_success_data(api.get_coverage_part(
        pro_rata.part_id, UNDERWRITER))["status"] == "VOID"


def rented_rig_inspected_at_three_million(api):
    """A RENTED unit on a RENTED_LEASED part, inspected but not yet adjusted."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Rented Fleet Earthworks")
    part = fixtures.create_part(api, policy["id"], factories.rented_leased_part())
    item = fixtures.schedule_item(api, part["id"], policy["id"],
                                  description="Rented excavator R1",
                                  ownership="RENTED")
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, item["id"])
    ctx = fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                       item_id=item["id"], item=item)
    ctx["claim"] = fixtures.build_inspected_claim(api, ctx, 3000000, 8160000,
                                                 loss_type="COLLISION")
    return ctx


def test_the_claimed_days_are_truncated_to_the_part_maximum_before_they_are_paid(api):
    """Twelve days claimed against a maximum of ten pays 500000, never 600000.

    PRD: `loss_of_use_paid_cents` is zero unless the governing part's `part_type` is `RENTED_LEASED` **and** the subject item's `ownership` is `RENTED` or `LEASED`; when both hold, take the smaller of `loss_of_use_days_claimed` and the part's `loss_of_use_max_days`, and multiply that day count by the part's `loss_of_use_daily_limit_cents`. No rounding is involved.
    PRD: At inspection `loss_of_use_days_claimed` is still zero, so both variants are recomputed again at adjustment.
    PRD: The `REPAIR` variant pays the estimate. Multiply `repair_estimate_cents` by `underreporting_factor_bp`, divide by ten thousand and round half-up **once**; take the smaller of that figure and `claim_limit_cents`; subtract the part's `deductible_cents`; if the result is below zero use zero; then add `loss_of_use_paid_cents`. That is `repair_basis_settlement_cents`.
    Design: Corner/calculations/corner_loss_of_use_extension_truncates_at_the_part_max_days
    """
    ctx = rented_rig_inspected_at_three_million(api)
    assert ctx.item["insured_value_cents"] == 8160000
    assert ctx.item["rated_premium_cents"] == 173318

    worksheet = validate_success(
        api.get_settlement_worksheet(ctx.claim["id"], ADJUSTER))

    assert worksheet["valuation_at_loss_cents"] == 8160000
    assert worksheet["constructive_total_loss_threshold_cents"] == 6120000
    assert worksheet["constructive_total_loss_reached"] is False
    assert worksheet["repair_basis_selectable"] is True
    assert worksheet["underreporting_factor_bp"] == 10000
    assert worksheet["claim_limit_cents"] == 20000000
    assert worksheet["deductible_cents"] == 100000
    assert worksheet["aggregate_available_cents"] == 200000000
    assert worksheet["loss_of_use_paid_cents"] == 0
    assert worksheet["repair_basis_settlement_cents"] == 2900000
    assert worksheet["total_loss_basis_settlement_cents"] == 8060000

    approved = validate_success(api.adjust_claim(
        ctx.claim["id"], factories.adjustment("REPAIR", 12), ADJUSTER))

    assert approved["loss_of_use_days_claimed"] == 12
    assert approved["loss_of_use_paid_cents"] == 500000
    assert approved["settlement_amount_cents"] == 3400000
    assert approved["adjustment_basis"] == "REPAIR"
    assert approved["adjustment_status"] == "REPAIR_APPROVED"
    assert approved["salvage_status"] == "NOT_APPLICABLE"


def test_the_loss_of_use_money_consumes_aggregate_capacity_like_indemnity(api):
    """The whole 3400000 crosses into paid capacity and the wreck stays on risk.

    PRD: On the repair branch that is the whole call: because `salvage_status` is `NOT_APPLICABLE`, the adjustment axis advances straight through `SETTLED` to `CLOSED` in the same call, and the response shows `adjustment_status` `CLOSED`.
    PRD: Settlement sets `settlement_paid_cents` to `settlement_amount_cents`, records `settled_by_user_id`, appends a `CLAIM_SETTLEMENT` entry to the **loss** ledger for the positive `settlement_paid_cents` carrying this claim's identifier, refreshes the policy's `incurred_loss_cents`, and moves the part's conserved capacity by adding the paid amount to `aggregate_paid_net_cents` and subtracting it from `aggregate_available_cents`.
    PRD: The `REPAIR` branch stores the supplied `loss_of_use_days_claimed`, recomputes `loss_of_use_paid_cents`, sets `settlement_amount_cents` to `repair_basis_settlement_cents`, moves the claim `INSPECTED` → `REPAIR_APPROVED`, and leaves `salvage_status` dormant at `NOT_APPLICABLE`; the damaged unit stays on risk and the part's premium is untouched.
    Design: Corner/calculations/corner_loss_of_use_extension_truncates_at_the_part_max_days
    """
    ctx = rented_rig_inspected_at_three_million(api)
    validate_success(api.adjust_claim(
        ctx.claim["id"], factories.adjustment("REPAIR", 12), ADJUSTER))

    paid = validate_success(api.settle_claim(ctx.claim["id"], MANAGER))

    assert paid["settlement_paid_cents"] == 3400000
    assert paid["adjustment_status"] == "CLOSED"
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 3400000
    assert part["aggregate_available_cents"] == 196600000
    assert part["rated_premium_cents"] == 173318
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "ACTIVE"
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["written_premium_cents"] == 180251
    assert policy["incurred_loss_cents"] == 3400000

    rows, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=100, offset=0))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "CLAIM_SETTLEMENT"
    assert rows[0]["amount_cents"] == 3400000
    assert rows[0]["claim_id"] == ctx.claim["id"]


def test_the_writing_response_already_carries_every_figure_it_derived(api):
    """No follow-up read is needed: the create prices the unit and the quote rolls it up.

    PRD: The item is rated in the same call that creates it, and the first step is to convert cost into insured value using the effective valuation basis.
    PRD: A newly scheduled item carries `status` `RATED`, a null `removed_at`, and the derived trace `applied_rate_rule_id`, `age_years_at_rating`, `insured_value_cents`, `applied_base_rate_bp`, `applied_credit_bp` and `rated_premium_cents`.
    PRD: Whenever an equipment item is rated or re-rated, the item's own derived fields are rewritten, then its parent coverage part's `rated_premium_cents` is recomputed from the surviving schedule, then the owning policy's `sum_of_part_premiums_cents`, `written_premium_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, `total_insured_value_cents` and `referral_required` are all re-derived.
    Design: Corner/consistency_model/corner_immediate_visibility_of_rating_inside_the_writing_response
    """
    rule = fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Immediate Read Contractors")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    version = fixtures.policy_version(api, policy["id"])

    created = validate_success(api.create_equipment_item(
        part["id"],
        factories.equipment_item(expected_policy_version=version),
        UNDERWRITER), 201)

    assert created["age_years_at_rating"] == 4
    assert created["insured_value_cents"] == 8160000
    assert created["applied_rate_rule_id"] == rule["id"]
    assert created["applied_base_rate_bp"] == 180
    assert created["applied_credit_bp"] == 0
    assert created["rated_premium_cents"] == 173318
    assert created["status"] == "RATED"
    assert created["removed_at"] is None
    reread = get_success_data(api.get_equipment_item(created["id"], UNDERWRITER))
    assert reread["rated_premium_cents"] == created["rated_premium_cents"]
    assert reread["insured_value_cents"] == created["insured_value_cents"]
    assert get_success_data(api.get_coverage_part(
        part["id"], UNDERWRITER))["rated_premium_cents"] == 173318

    quoted = validate_success(api.quote_policy(policy["id"], UNDERWRITER))

    assert quoted["status"] == "QUOTED"
    assert quoted["sum_of_part_premiums_cents"] == 173318
    assert quoted["written_premium_cents"] == 180251
    assert quoted["scheduled_basis_premium_cents"] == 180251
    assert quoted["total_insured_value_cents"] == 8160000
    settled_read = get_success_data(api.get_policy(policy["id"], UNDERWRITER))
    assert settled_read["written_premium_cents"] == quoted["written_premium_cents"]
    assert settled_read["sum_of_part_premiums_cents"] == 173318


def test_the_capacity_drawdown_and_its_restoration_are_both_visible_at_once(api):
    """191940000 inside the settling call, 193440000 inside the recovery call.

    PRD: The identity `aggregate_limit_cents` equals `aggregate_available_cents` plus `aggregate_paid_net_cents` holds at every observable moment.
    PRD: Hop two takes the loss subject off risk: an equipment item becomes `TOTALED`, an `IN_TRANSIT` transit shipment becomes `LOST` with the vehicle's `in_transit_value_cents` recomputed.
    PRD: Proceeds above zero move the salvage axis `PENDING` → `RECOVERED` and set `salvage_credit_cents` to the smaller of `salvage_proceeds_cents` and `settlement_paid_cents`, so a recovery worth more than the cheque credits only what was paid; a `SALVAGE_RECOVERY` entry is appended to the loss ledger for the negative of `salvage_credit_cents`, `incurred_loss_cents` is refreshed, and the conserved capacity is compensated by subtracting `salvage_credit_cents` from `aggregate_paid_net_cents` and adding it back to `aggregate_available_cents`.
    PRD: Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.
    Design: Corner/consistency_model/corner_immediate_visibility_of_the_capacity_drawdown_and_its_restoration
    """
    ctx = fixtures.build_in_force_file(
        api, policy_kwargs=dict(policyholder_name="Drawdown Contractors"))
    claim = fixtures.build_total_loss_claim(api, ctx, loss_type="FIRE")
    assert claim["constructive_total_loss_threshold_cents"] == 6120000
    assert claim["adjustment_status"] == "TOTAL_LOSS_DECLARED"
    assert claim["salvage_status"] == "PENDING"
    assert claim["settlement_amount_cents"] == 8060000

    settled = validate_success(api.settle_claim(claim["id"], MANAGER))

    assert settled["settlement_paid_cents"] == 8060000
    assert settled["settled_by_user_id"] == MANAGER_USER_ID
    assert settled["adjustment_status"] == "SETTLED"
    assert settled["salvage_status"] == "PENDING"
    drawn = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert drawn["aggregate_paid_net_cents"] == 8060000
    assert drawn["aggregate_available_cents"] == 191940000
    assert (drawn["aggregate_available_cents"]
            + drawn["aggregate_paid_net_cents"]) == 200000000
    assert drawn["rated_premium_cents"] == 0
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "TOTALED"
    written_off = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert written_off["incurred_loss_cents"] == 8060000
    assert written_off["written_premium_cents"] == 100000
    assert written_off["total_insured_value_cents"] == 0
    assert written_off["premium_balance_cents"] == 6933

    recovered = validate_success(api.record_salvage_recovery(
        claim["id"], factories.salvage(1500000), ADJUSTER))

    assert recovered["salvage_status"] == "RECOVERED"
    assert recovered["salvage_credit_cents"] == 1500000
    assert recovered["adjustment_status"] == "CLOSED"
    restored = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert restored["aggregate_available_cents"] == 193440000
    assert restored["aggregate_paid_net_cents"] == 6560000
    assert (restored["aggregate_available_cents"]
            + restored["aggregate_paid_net_cents"]) == 200000000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 6560000

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.LOSS))
    assert meta["total_count"] == 2
    assert rows[0]["entry_type"] == "CLAIM_SETTLEMENT"
    assert rows[0]["amount_cents"] == 8060000
    assert rows[1]["entry_type"] == "SALVAGE_RECOVERY"
    assert rows[1]["amount_cents"] == -1500000
    assert [row["claim_id"] for row in rows] == [claim["id"], claim["id"]]
