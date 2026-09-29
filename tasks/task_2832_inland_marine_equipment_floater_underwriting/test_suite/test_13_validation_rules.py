"""Refusals with money attached: referral authority, telematics, and the four fiscal limits."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import (
    MANAGER,
    MANAGER_USER_ID,
    UNDERWRITER,
    UNDERWRITER_USER_ID,
)


def crane_file_over_the_exposure_line(api):
    """A single agreed-value tower crane priced above the referral threshold."""
    fixtures.publish_rate_rule(api, equipment_type="CRANE", base_rate_bp=310,
                               theft_hazard_grade="B")
    policy = fixtures.create_policy(api, policyholder_name="Tower Crane Rentals",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(
        api, policy["id"],
        factories.scheduled_equipment_part(per_item_limit_cents=100000000))
    item = fixtures.schedule_item(api, part["id"], policy["id"],
                                  description="Tower crane TC-1",
                                  equipment_type="CRANE",
                                  valuation_basis="AGREED_VALUE",
                                  stated_value_cents=60000000)
    ctx = fixtures.Ctx(policy_id=policy["id"], part_id=part["id"], item=item)
    ctx["quoted"] = fixtures.quote(api, policy["id"])
    return ctx


def test_the_exposure_flag_alone_bars_the_bind_while_no_one_has_decided(api):
    """Sixty million of agreed value trips the flag, and the flag stops the bind.

    PRD: The exposure test trips when `total_insured_value_cents` goes above $500,000 (50,000,000 cents) — strictly above, so exactly 50,000,000 cents does not trip it.
    PRD: It also requires referral clearance: if `referral_required` is true then `referral_status` must be `APPROVED`, and otherwise the bind is refused with `ERR_REFERRAL_REQUIRED`.
    Design: Corner/validations/corner_bind_requires_referral_clearance
    """
    ctx = crane_file_over_the_exposure_line(api)
    assert ctx.item["insured_value_cents"] == 60000000
    assert ctx.item["rated_premium_cents"] == 2557500
    assert ctx.quoted["status"] == "QUOTED"
    assert ctx.quoted["total_insured_value_cents"] == 60000000
    assert ctx.quoted["written_premium_cents"] == 2659800
    assert ctx.quoted["referral_required"] is True
    assert ctx.quoted["referral_status"] == "NOT_REQUIRED"

    refused = api.bind_policy(ctx.policy_id, UNDERWRITER)

    validate_error(refused, "ERR_REFERRAL_REQUIRED", 422)
    still_quoted = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert still_quoted["status"] == "QUOTED"
    assert still_quoted["bound_at"] is None
    assert still_quoted["referral_status"] == "NOT_REQUIRED"
    assert still_quoted["referred_by_user_id"] is None
    assert still_quoted["premium_balance_cents"] == 0


def test_the_referral_loop_returns_the_file_to_quoted_and_lets_it_bind(api):
    """Two operators and one round trip turn the same refused bind into a bound policy.

    PRD: A successful referral moves the policy `QUOTED` → `REFERRED`, sets `referral_status` to `PENDING`, and records the calling underwriter's `X-User-ID` in `referred_by_user_id`.
    PRD: An approval sets `referral_status` to `APPROVED` and returns the policy `REFERRED` → `QUOTED`, closing the `QUOTED` → `REFERRED` → `QUOTED` loop so that the file can be re-priced or bound.
    Design: Corner/validations/corner_bind_requires_referral_clearance
    """
    ctx = crane_file_over_the_exposure_line(api)
    validate_error(api.bind_policy(ctx.policy_id, UNDERWRITER),
                   "ERR_REFERRAL_REQUIRED", 422)

    referred = validate_success(api.refer_policy(ctx.policy_id, UNDERWRITER,
                                                 factories.referral()))
    assert referred["status"] == "REFERRED"
    assert referred["referral_status"] == "PENDING"
    assert referred["referred_by_user_id"] == UNDERWRITER_USER_ID

    approved = validate_success(api.decide_referral(
        ctx.policy_id, factories.referral_decision("APPROVE"), MANAGER))
    assert approved["status"] == "QUOTED"
    assert approved["referral_status"] == "APPROVED"
    assert approved["referral_decided_by_user_id"] == MANAGER_USER_ID

    bound = validate_success(api.bind_policy(ctx.policy_id, UNDERWRITER))

    assert bound["status"] == "BOUND"
    assert_instant_equals(bound["bound_at"], "2026-08-01T00:00:00Z")
    assert bound["written_premium_cents"] == 2659800
    assert bound["referral_required"] is True
    booked = find_entry(fixtures.premium_ledger(api, ctx.policy_id),
                        "INITIAL_PREMIUM")
    assert booked is not None
    assert booked["amount_cents"] == 2659800


def two_yards_astride_the_telematics_line(api):
    """A fenced-only yard at TIER_1, an alarmed yard at TIER_2, and an empty schedule."""
    fixtures.publish_rate_rule(api)
    lightly = fixtures.create_jobsite(api, name="Fenced Only Yard")
    fixtures.survey_jobsite(api, lightly["id"], dict(fenced=True))
    well = fixtures.create_jobsite(api, name="Alarmed Yard")
    fixtures.survey_jobsite(api, well["id"], factories.SURVEY_TIER_2)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Untracked Digging Co")
    part = fixtures.create_part(api, policy["id"],
                               factories.scheduled_equipment_part())
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        low_id=lightly["id"], high_id=well["id"])


def sited_grade_a_unit(api, ctx):
    """Schedule an untracked grade-A unit and re-site it onto the alarmed yard."""
    item = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                  description="Excavator without telematics")
    return validate_success(api.assign_jobsite(
        item["id"], factories.jobsite_assignment(ctx.high_id), UNDERWRITER))


def test_an_untracked_grade_a_unit_is_refused_by_the_lightly_controlled_yard(api):
    """The same three-way test guards the create and the re-siting alike.

    PRD: Concretely: if the rate cell selected for a unit carries `theft_hazard_grade` `A`, and the site the unit would stand on has a `security_tier` of `TIER_0` or `TIER_1`, and the unit's `geo_tracker_installed` is false, the operation is refused with `ERR_GEO_TRACKING_REQUIRED`.
    PRD: That control guards three distinct operations, not one: scheduling a new equipment item (when the create names an `assigned_jobsite_id`), re-siting an existing item, and recording a jobsite security survey.
    PRD: A unit standing on a jobsite earns a jobsite security credit keyed on that site's `security_tier`: nothing at `TIER_0`, 300 basis points at `TIER_1`, 700 at `TIER_2` and 1,200 at `TIER_3`; a unit with no `assigned_jobsite_id` earns no security credit at all.
    Design: Corner/validations/corner_geo_tracking_required_on_low_tier_jobsite
    """
    ctx = two_yards_astride_the_telematics_line(api)
    low = get_success_data(api.get_jobsite(ctx.low_id, UNDERWRITER))
    high = get_success_data(api.get_jobsite(ctx.high_id, UNDERWRITER))
    assert (low["security_score"], low["security_tier"]) == (1, "TIER_1")
    assert (high["security_score"], high["security_tier"]) == (3, "TIER_2")

    born_on_the_low_yard = api.create_equipment_item(
        ctx.part_id,
        factories.equipment_item(fixtures.policy_version(api, ctx.policy_id),
                                 description="Excavator born on the fenced yard",
                                 assigned_jobsite_id=ctx.low_id),
        UNDERWRITER)

    validate_error(born_on_the_low_yard, "ERR_GEO_TRACKING_REQUIRED", 422)
    empty = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert empty["rated_premium_cents"] == 0
    _, meta = validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=20, offset=0))
    assert meta["total_count"] == 0

    unsited = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                     description="Excavator without telematics")
    assert unsited["geo_tracker_installed"] is False
    assert unsited["assigned_jobsite_id"] is None
    assert unsited["applied_credit_bp"] == 0
    assert unsited["rated_premium_cents"] == 173318

    validate_error(api.assign_jobsite(unsited["id"],
                                      factories.jobsite_assignment(ctx.low_id),
                                      UNDERWRITER),
                   "ERR_GEO_TRACKING_REQUIRED", 422)
    unmoved = get_success_data(api.get_equipment_item(unsited["id"], UNDERWRITER))
    assert unmoved["assigned_jobsite_id"] is None
    assert unmoved["applied_credit_bp"] == 0
    assert unmoved["rated_premium_cents"] == 173318

    resited = validate_success(api.assign_jobsite(
        unsited["id"], factories.jobsite_assignment(ctx.high_id), UNDERWRITER))
    assert resited["status"] == "RATED"
    assert resited["assigned_jobsite_id"] == ctx.high_id
    assert resited["applied_credit_bp"] == 700
    assert resited["rated_premium_cents"] == 161186


def test_a_survey_that_would_drop_the_tier_under_a_standing_unit_is_rolled_back(api):
    """The site is already occupied, so the downgrade is refused in full, not in part.

    PRD: The third is the subtle one — a re-survey that *drops* a site's tier can put a standing grade-A unit into violation, and in that case the whole survey is rejected with `ERR_GEO_TRACKING_REQUIRED` and nothing at all changes: the site keeps its previous `security_score`, `security_tier` and `surveyed_at`, and no item is re-rated.
    PRD: The survey stamps `surveyed_at` from the logical clock and moves the site's `status` to `SURVEYED`, whether it was `UNSURVEYED`, already `SURVEYED` (a re-survey), or `RELEASED` (a re-survey of a released site).
    Design: Corner/validations/corner_geo_tracking_required_on_low_tier_jobsite
    """
    ctx = two_yards_astride_the_telematics_line(api)
    standing = sited_grade_a_unit(api, ctx)
    assert standing["rated_premium_cents"] == 161186

    downgrade = api.record_security_survey(
        ctx.high_id, factories.security_survey(fenced=True), UNDERWRITER)

    validate_error(downgrade, "ERR_GEO_TRACKING_REQUIRED", 422)
    intact = get_success_data(api.get_jobsite(ctx.high_id, UNDERWRITER))
    assert intact["security_score"] == 3
    assert intact["security_tier"] == "TIER_2"
    assert intact["status"] == "SURVEYED"
    assert intact["lighting"] is True
    assert intact["alarm_monitored"] is True
    assert_instant_equals(intact["surveyed_at"], "2026-08-01T00:00:00Z")
    unchanged = get_success_data(api.get_equipment_item(standing["id"], UNDERWRITER))
    assert unchanged["applied_credit_bp"] == 700
    assert unchanged["rated_premium_cents"] == 161186
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 161186


def test_the_per_item_limit_is_tested_against_the_derived_value_not_the_cost(api):
    """Two units of identical cost, one model year apart, land either side of the limit.

    PRD: Under `ACV`, the unit depreciates 800 basis points — 8 percent — of its original cost for each whole year of `age_years_at_rating`; the retained proportion is ten thousand basis points less that depreciation, but never less than a floor of 2,000 basis points, so a unit that is ten years old or older retains exactly 20 percent; `insured_value_cents` is then the original cost multiplied by the retained proportion, divided by ten thousand, and rounded half-up once.
    PRD: If the resulting `insured_value_cents` exceeds a `per_item_limit_cents` declared on the part, the item is refused with `ERR_ITEM_VALUE_EXCEEDS_PER_ITEM_LIMIT`; where the part declares no such limit the check does not apply.
    Design: Corner/validations/corner_item_insured_value_versus_per_item_limit
    """
    ctx = fixtures.build_scheduled_file(
        api, policy_kwargs=dict(policyholder_name="Tight Limit Excavating"),
        part_kwargs=dict(per_item_limit_cents=8160000), with_item=False)

    exactly_at_the_limit = fixtures.schedule_item(
        api, ctx.part_id, ctx.policy_id, description="Four year old excavator",
        model_year=2022, original_cost_cents=12000000)

    assert exactly_at_the_limit["age_years_at_rating"] == 4
    assert exactly_at_the_limit["insured_value_cents"] == 8160000
    assert exactly_at_the_limit["rated_premium_cents"] == 173318

    one_year_newer = api.create_equipment_item(
        ctx.part_id,
        factories.equipment_item(fixtures.policy_version(api, ctx.policy_id),
                                 description="Three year old excavator",
                                 model_year=2023,
                                 original_cost_cents=12000000),
        UNDERWRITER)

    validate_error(one_year_newer, "ERR_ITEM_VALUE_EXCEEDS_PER_ITEM_LIMIT", 422)
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["per_item_limit_cents"] == 8160000
    assert part["rated_premium_cents"] == 173318
    _, meta = validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=20, offset=0))
    assert meta["total_count"] == 1

    quoted = fixtures.quote(api, ctx.policy_id)
    assert quoted["total_insured_value_cents"] == 8160000
    assert quoted["written_premium_cents"] == 180251


def lowboy_and_three_competing_limits(api):
    """A DRAFT transit part with 4000000 owned, 2000000 catastrophe, and one owned truck."""
    ctx = fixtures.build_transit_file(
        api, policy_kwargs=dict(policyholder_name="Lowboy Logistics"),
        part_kwargs=dict(transit_owned_limit_cents=4000000,
                         transit_hired_limit_cents=3000000,
                         catastrophe_limit_cents=2000000))
    vehicle = fixtures.create_vehicle(api, unit_label="LOWBOY-1",
                                      ownership="OWNED",
                                      per_conveyance_limit_cents=10000000)
    ctx["vehicle_id"] = vehicle["id"]
    return ctx


def plan(api, ctx, destination, declared,
         departure_at="2026-08-05T08:00:00Z", arrival_at="2026-08-05T18:00:00Z"):
    """Attempt one run out of T2_URBAN, returning the raw response.

    The occupation window is half-open and carries a four-hour turnaround, so
    each run this test plans is given its own window; otherwise the conveyance
    window check (an earlier rung) would answer before the limit test.
    """
    return api.create_transit_shipment(
        ctx.part_id,
        factories.transit_shipment(ctx.vehicle_id,
                                   origin_territory_code="T2_URBAN",
                                   destination_territory_code=destination,
                                   departure_at=departure_at,
                                   arrival_at=arrival_at,
                                   declared_value_cents=declared),
        UNDERWRITER)


def test_one_coastal_endpoint_shrinks_the_limit_the_same_declared_value_must_clear(api):
    """The vehicle's own ten million never binds; the tightest of the part's limits does.

    PRD: `catastrophe_zone` is true when the `origin_territory_code` is `T1_COASTAL` **or** the `destination_territory_code` is `T1_COASTAL`; one coastal endpoint is enough, so an inland-to-coastal run is a catastrophe-zone run even though it starts inland.
    PRD: The shipment's `applicable_limit_cents` is then the smallest of three quantities: that conveyance limit, the vehicle's own `per_conveyance_limit_cents`, and — only when `catastrophe_zone` is true — the part's `catastrophe_limit_cents`.
    PRD: The shipment's `declared_value_cents` must not exceed the resulting `applicable_limit_cents`, else `ERR_TRANSIT_VALUE_EXCEEDS_LIMIT`.
    PRD: The `in_transit_value_cents` field is at all times the sum of `declared_value_cents` over the shipments on this vehicle whose status is `IN_TRANSIT`.
    Design: Corner/validations/corner_transit_declared_value_versus_applicable_limit
    """
    ctx = lowboy_and_three_competing_limits(api)

    validate_error(plan(api, ctx, "T3_INLAND", 5000000),
                   "ERR_TRANSIT_VALUE_EXCEEDS_LIMIT", 422)
    assert get_success_data(api.get_vehicle(
        ctx.vehicle_id, UNDERWRITER))["in_transit_value_cents"] == 0
    _, empty = validate_paginated(api.list_transit_shipments(
        UNDERWRITER, limit=20, offset=0, coverage_part_id=ctx.part_id))
    assert empty["total_count"] == 0

    inland = validate_success(plan(api, ctx, "T3_INLAND", 4000000), 201)
    assert inland["catastrophe_zone"] is False
    assert inland["applicable_limit_cents"] == 4000000
    assert inland["status"] == "PLANNED"

    validate_error(plan(api, ctx, "T1_COASTAL", 2500000,
                        departure_at="2026-08-05T22:00:00Z",
                        arrival_at="2026-08-05T23:00:00Z"),
                   "ERR_TRANSIT_VALUE_EXCEEDS_LIMIT", 422)

    coastal = validate_success(plan(api, ctx, "T1_COASTAL", 2000000,
                                    departure_at="2026-08-05T22:00:00Z",
                                    arrival_at="2026-08-05T23:00:00Z"), 201)
    assert coastal["catastrophe_zone"] is True
    assert coastal["applicable_limit_cents"] == 2000000
    assert coastal["status"] == "PLANNED"
    assert get_success_data(api.get_vehicle(
        ctx.vehicle_id, UNDERWRITER))["in_transit_value_cents"] == 0


AUGUST = ("2026-08-01", "2026-08-31")
SEPTEMBER = ("2026-09-01", "2026-09-30")


def test_a_declared_value_one_cent_over_the_reporting_limit_is_refused(api):
    """The refused filing leaves no watermark and does not consume the version token.

    PRD: Finally `reported_value_cents` must not exceed the part's `reporting_limit_cents`, else `ERR_REPORTED_VALUE_EXCEEDS_LIMIT`.
    PRD: A filed report has `period_days` equal to the whole days from `period_start_date` to `period_end_date` plus one — both endpoints count — and a `due_date` fifteen days after `period_end_date`, that being the reporting grace period.
    PRD: The field `latest_report_period_end_date` is the greatest `period_end_date` among the reports on the part whose status is `SUBMITTED`, `ACCEPTED`, `PENALIZED` or `DELINQUENT`, with ties broken by the greatest `created_at`, and is null when the part has no such report.
    PRD: The filing increments the part's `version` by one.
    Design: Corner/validations/corner_reported_value_versus_reporting_limit
    """
    ctx = fixtures.build_reporting_file(
        api, policy_kwargs=dict(policyholder_name="Over Declared Stock Co"))
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    opening = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert opening["reporting_limit_cents"] == 20000000
    assert opening["latest_report_period_end_date"] is None
    token = opening["version"]

    over = api.create_value_report(
        ctx.part_id,
        factories.value_report(AUGUST[0], AUGUST[1], 20000001, token),
        UNDERWRITER)

    validate_error(over, "ERR_REPORTED_VALUE_EXCEEDS_LIMIT", 422)
    untouched = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert untouched["version"] == token
    assert untouched["latest_report_period_end_date"] is None
    assert untouched["earned_reported_premium_cents"] == 0

    exactly_at_the_limit = validate_success(api.create_value_report(
        ctx.part_id,
        factories.value_report(AUGUST[0], AUGUST[1], 20000000, token),
        UNDERWRITER), 201)

    assert exactly_at_the_limit["status"] == "SUBMITTED"
    assert exactly_at_the_limit["reported_value_cents"] == 20000000
    assert exactly_at_the_limit["period_days"] == 31
    assert exactly_at_the_limit["due_date"] == "2026-09-15"
    assert exactly_at_the_limit["period_earned_premium_cents"] == 0
    assert exactly_at_the_limit["late_penalty_cents"] == 0
    filed_on = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert filed_on["version"] == token + 1
    assert filed_on["latest_report_period_end_date"] == "2026-08-31"
    assert filed_on["earned_reported_premium_cents"] == 0
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == 100000


def reporting_file_with_september_accepted(api):
    """A reporting part whose frontier has been pushed to the end of September."""
    ctx = fixtures.build_reporting_file(
        api, policy_kwargs=dict(policyholder_name="Frontier Reporting Co"))
    fixtures.set_clock(api, "2026-10-10T00:00:00Z")
    filed = fixtures.file_value_report(api, ctx.part_id, SEPTEMBER[0],
                                       SEPTEMBER[1], 12000000)
    ctx["september"] = get_success_data(
        api.adjudicate_value_report(filed["id"], UNDERWRITER))
    return ctx


def test_a_period_reaching_past_the_expiration_is_refused_before_its_placement(api):
    """Two filings share a misaligned start; only the out-of-term end changes the answer.

    PRD: Checks are evaluated in one strict, service-wide order, and the **first** check that fails decides the response; no later check is evaluated and no partial mutation is retained.
    PRD: The period must sit inside the policy term, else `ERR_REPORT_PERIOD_OUTSIDE_TERM`.
    PRD: Any other placement — a partial overlap, a period that starts on or before the latest reported period's end without matching it exactly, a gap-filling period behind the frontier — is `ERR_REPORT_PERIOD_MISALIGNED`.
    Design: Corner/validations/corner_report_period_outside_term_beats_misalignment
    """
    ctx = reporting_file_with_september_accepted(api)
    assert ctx.september["status"] == "ACCEPTED"
    assert ctx.september["period_days"] == 30
    assert ctx.september["period_earned_premium_cents"] == 24658
    frontier = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert frontier["latest_report_period_end_date"] == "2026-09-30"
    assert frontier["earned_reported_premium_cents"] == 24658
    token = frontier["version"]

    behind_the_frontier = api.create_value_report(
        ctx.part_id,
        factories.value_report(AUGUST[0], AUGUST[1], 9000000, token),
        UNDERWRITER)
    validate_error(behind_the_frontier, "ERR_REPORT_PERIOD_MISALIGNED", 422)

    same_start_but_out_of_term = api.create_value_report(
        ctx.part_id,
        factories.value_report(AUGUST[0], "2027-08-31", 9000000, token),
        UNDERWRITER)

    validate_error(same_start_but_out_of_term, "ERR_REPORT_PERIOD_OUTSIDE_TERM", 422)
    unmoved = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert unmoved["version"] == token
    assert unmoved["latest_report_period_end_date"] == "2026-09-30"
    assert unmoved["earned_reported_premium_cents"] == 24658
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == 124658


def test_an_exact_restatement_supersedes_the_predecessor_and_undoes_its_money(api):
    """The one placement that may sit on the frontier also has to unwind what it replaces.

    PRD: Its placement must then be one of exactly two shapes: either it restates a period already on the part, meaning both its `period_start_date` **and** its `period_end_date` are identical to those of an existing report on the part, or it starts strictly after the part's `latest_report_period_end_date`.
    PRD: Every prior report on the same part for the identical period whose status is not already `SUPERSEDED` moves to `SUPERSEDED`, with its `superseded_by_report_id` set to the new report's `id`.
    PRD: When a superseded predecessor was `ACCEPTED` or `PENALIZED` its money must be undone: its `period_earned_premium_cents` is subtracted from the part's `earned_reported_premium_cents` and a compensating `REPORTING_ADJUSTMENT` entry is appended to the premium ledger for the negative of that amount, after which `premium_balance_cents` is recomputed.
    Design: Corner/validations/corner_report_period_outside_term_beats_misalignment
    """
    ctx = reporting_file_with_september_accepted(api)

    restated = validate_success(api.create_value_report(
        ctx.part_id,
        factories.value_report(SEPTEMBER[0], SEPTEMBER[1], 15000000,
                               fixtures.part_version(api, ctx.part_id)),
        UNDERWRITER), 201)

    assert restated["status"] == "SUBMITTED"
    assert restated["period_start_date"] == SEPTEMBER[0]
    assert restated["period_end_date"] == SEPTEMBER[1]
    predecessor = get_success_data(
        api.get_value_report(ctx.september["id"], UNDERWRITER))
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by_report_id"] == restated["id"]
    assert predecessor["period_earned_premium_cents"] == 24658

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["earned_reported_premium_cents"] == 0
    assert part["latest_report_period_end_date"] == "2026-09-30"
    rows = fixtures.premium_ledger(api, ctx.policy_id)
    adjustments = [row["amount_cents"] for row in rows
                   if row["entry_type"] == "REPORTING_ADJUSTMENT"]
    assert sorted(adjustments) == [-24658, 24658]
    assert sum(row["amount_cents"] for row in rows) == 100000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == 100000


def test_the_cancel_effective_date_must_sit_inside_the_term_on_both_ends(api):
    """The expiration date itself is out of bounds; the effective date itself is in.

    PRD: The submission carries a `cancellation_reason` of `INSURED_REQUEST`, `NON_REPORTING` or `UNDERWRITING`, and a `cancel_effective_date` which must fall on or after the policy's `effective_date` and strictly before its `expiration_date`, else `ERR_CANCEL_DATE_OUTSIDE_TERM`.
    PRD: When the reason is `NON_REPORTING` or `UNDERWRITING` — both insurer-initiated — the full pro-rata figure is returned with no second rounding.
    PRD: Finally every coverage part still `ACTIVE` becomes `VOID`.
    Design: Corner/validations/corner_cancel_effective_date_must_lie_inside_term
    """
    ctx = fixtures.build_reporting_file(
        api, policy_kwargs=dict(policyholder_name="Day One Exit Stock Co"))
    opening = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert opening["status"] == "IN_FORCE"
    assert opening["effective_date"] == "2026-08-01"
    assert opening["expiration_date"] == "2027-08-01"
    assert opening["written_premium_cents"] == 100000
    assert opening["premium_balance_cents"] == 100000

    for outside in ("2027-09-01", "2026-07-31", "2027-08-01"):
        validate_error(api.cancel_policy(
            ctx.policy_id, factories.cancellation("UNDERWRITING", outside),
            MANAGER), "ERR_CANCEL_DATE_OUTSIDE_TERM", 422)
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["status"] == "IN_FORCE"

    cancelled = validate_success(api.cancel_policy(
        ctx.policy_id, factories.cancellation("UNDERWRITING", "2026-08-01"),
        MANAGER))

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "UNDERWRITING"
    assert cancelled["cancel_effective_date"] == "2026-08-01"
    assert cancelled["premium_balance_cents"] == 0
    returned = find_entry(fixtures.premium_ledger(api, ctx.policy_id),
                          "CANCELLATION_RETURN")
    assert returned is not None
    assert returned["amount_cents"] == -100000
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["status"] == "VOID"
