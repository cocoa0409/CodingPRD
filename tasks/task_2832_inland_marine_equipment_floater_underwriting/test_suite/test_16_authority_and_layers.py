"""Who may act, on whose policy, and the layers that cut across every write."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import (
    ACTUARY,
    ADJUSTER,
    ADJUSTER_2,
    ADJUSTER_USER_ID,
    MANAGER,
    MANAGER_USER_ID,
    UNDERWRITER,
    UNDERWRITER_USER_ID,
    make_headers,
    make_policyholder_headers,
)
from test_helpers.types import Ledger, LedgerEntryType, Role


def test_only_the_actuary_develops_rates_while_two_more_roles_may_read_them(api):
    """The same draft and publish bodies are Actuary-only; the read is shared with two.

    PRD: Once the headers are accepted, the caller's role must appear in the authorised-role list published for the endpoint in §4; a caller whose role is not listed there is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
    PRD: An `Actuary` owns rate development: building and publishing the contractors-equipment rate cells that rating selects from, plus reading those cells and querying the equipment they have priced.
    PRD: | GET | `/inland-marine/rate-rules/{id}` | Read one rate rule. | `Actuary`, `Underwriter`, `UnderwritingManager` |
    PRD: Publishing a cell moves it `DRAFT` → `PUBLISHED` and stamps `published_at` from the logical clock.
    Design: Corner/rbac/corner_rate_development_is_actuary_exclusive
    """
    cell = fixtures.draft_rate_rule(api)
    generator = factories.rate_rule(equipment_type="GENERATOR",
                                    age_band_min_years=6, age_band_max_years=12,
                                    base_rate_bp=120, theft_hazard_grade="C")

    validate_error(api.create_rate_rule(generator, UNDERWRITER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.create_rate_rule(generator, MANAGER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.publish_rate_rule(cell["id"], UNDERWRITER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    assert get_success_data(api.get_rate_rule(cell["id"], ACTUARY))["status"] == "DRAFT"

    published = validate_success(api.publish_rate_rule(cell["id"], ACTUARY))
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00Z")

    assert validate_success(api.get_rate_rule(
        cell["id"], UNDERWRITER))["status"] == "PUBLISHED"
    assert validate_success(api.get_rate_rule(
        cell["id"], MANAGER))["status"] == "PUBLISHED"
    validate_error(api.get_rate_rule(cell["id"], ADJUSTER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)


def collision_claim_awaiting_adjustment(api):
    """The canonical on-risk file with one OPEN collision claim on its unit."""
    ctx = fixtures.build_in_force_file(api)
    ctx["claim"] = fixtures.build_claim_on_item(api, ctx, loss_type="COLLISION")
    return ctx


def test_the_role_that_adjusts_the_loss_may_not_authorise_the_cheque(api):
    """Inspect and adjust are the adjuster's alone; settling is the manager's alone.

    PRD: A `ClaimsAdjuster` owns loss adjustment — inspection, the choice between repair and total loss, and the salvage disposition — but cannot authorise the payment it recommends.
    PRD: **Inspection.** Only a `ClaimsAdjuster` inspects, and only a claim whose `adjustment_status` is `OPEN`, else `ERR_CLAIM_NOT_IN_REQUIRED_STATE`.
    PRD: **Authorising payment.** Only an `UnderwritingManager` settles, and only a claim whose `adjustment_status` is `REPAIR_APPROVED` or `TOTAL_LOSS_DECLARED`, else `ERR_CLAIM_NOT_IN_REQUIRED_STATE`.
    PRD: 3. **Role permitted.** The caller's role appears in the endpoint's authorised-role list, else `ERR_ROLE_NOT_PERMITTED` (403).
    Design: Corner/rbac/corner_adjustment_authority_and_payment_authority_are_disjoint_roles
    """
    ctx = collision_claim_awaiting_adjustment(api)
    claim_id = ctx["claim"]["id"]
    survey = factories.inspection(3000000, 8160000)

    validate_error(api.inspect_claim(claim_id, survey, MANAGER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.inspect_claim(claim_id, survey, UNDERWRITER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    assert get_success_data(api.get_claim(
        claim_id, ADJUSTER))["adjustment_status"] == "OPEN"

    inspected = validate_success(api.inspect_claim(claim_id, survey, ADJUSTER))
    assert inspected["adjustment_status"] == "INSPECTED"
    assert inspected["inspected_by_user_id"] == ADJUSTER_USER_ID

    approved = validate_success(api.adjust_claim(
        claim_id, factories.adjustment("REPAIR"), ADJUSTER))
    assert approved["adjustment_status"] == "REPAIR_APPROVED"
    assert approved["declared_by_user_id"] == ADJUSTER_USER_ID
    assert approved["settlement_amount_cents"] == 2900000

    validate_error(api.settle_claim(claim_id, ADJUSTER_2),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.settle_claim(claim_id, UNDERWRITER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    assert get_success_data(api.get_claim(
        claim_id, ADJUSTER))["adjustment_status"] == "REPAIR_APPROVED"

    settled = validate_success(api.settle_claim(claim_id, MANAGER))
    assert settled["adjustment_status"] == "CLOSED"
    assert settled["settlement_paid_cents"] == 2900000
    assert settled["settled_by_user_id"] == MANAGER_USER_ID

    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 2900000
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["aggregate_available_cents"] == 197100000
    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.LOSS))
    assert meta["total_count"] == 1
    assert find_entry(rows, LedgerEntryType.CLAIM_SETTLEMENT)["amount_cents"] == 2900000


def live_reporting_policy(api, policyholder_name):
    """An IN_FORCE policy whose only part is a monthly reporting form."""
    policy = fixtures.create_policy(api, policyholder_name=policyholder_name)
    part = fixtures.create_part(api, policy["id"], factories.reporting_form_part())
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    return policy, part


def test_the_named_insured_reaches_its_own_file_and_no_other(api):
    """The identity IS the policy, and the ownership test reaches through the part.

    PRD: The fifth role is entity-backed: when `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting policy, and ownership checks on any resource that references a policy compare the resource's policy — directly, or transitively through its coverage part — to `X-User-ID`.
    PRD: A `Policyholder` acting on a resource that belongs to some other policy is rejected with `ERR_NOT_POLICY_OWNER` (HTTP 403).
    PRD: That ownership check guards exactly seven operations: filing a value report on a coverage part, reporting a loss on a policy, reading a policy, reading a policy's premium summary, listing a policy's coverage parts, listing a policy's ledger entries, and reading a claim.
    PRD: A `Policyholder` is the named insured itself: it files periodic value reports, reports losses on its own policy, and reads its own premium picture.
    Design: Corner/rbac/corner_policyholder_is_scoped_to_the_policy_that_is_its_own_identity
    """
    policy_a, part_a = live_reporting_policy(api, "Owner A Logistics")
    policy_b, part_b = live_reporting_policy(api, "Owner B Logistics")
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    holder_a = make_policyholder_headers(policy_a["id"])
    token_b = fixtures.part_version(api, part_b["id"])
    token_a = fixtures.part_version(api, part_a["id"])

    own = validate_success(api.get_premium_summary(policy_a["id"], holder_a))
    assert own["written_premium_cents"] == 100000
    assert own["minimum_premium_applied"] is True

    validate_error(api.get_premium_summary(policy_b["id"], holder_a),
                   api_errors.ERR_NOT_POLICY_OWNER, 403)
    validate_error(api.create_value_report(
        part_b["id"],
        factories.value_report("2026-08-01", "2026-08-31", 9000000, token_b),
        holder_a), api_errors.ERR_NOT_POLICY_OWNER, 403)
    assert fixtures.part_version(api, part_b["id"]) == token_b

    filed = validate_success(api.create_value_report(
        part_a["id"],
        factories.value_report("2026-08-01", "2026-08-31", 9000000, token_a),
        holder_a), 201)
    assert filed["status"] == "SUBMITTED"
    assert filed["period_days"] == 31
    assert filed["due_date"] == "2026-09-15"

    validate_error(api.list_ledger_entries(policy_b["id"], holder_a,
                                           limit=10, offset=0),
                   api_errors.ERR_NOT_POLICY_OWNER, 403)
    validate_error(api.quote_policy(policy_a["id"], holder_a),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)

    assert validate_paginated(api.list_value_reports(
        part_b["id"], UNDERWRITER, limit=10, offset=0))[1]["total_count"] == 0
    assert validate_paginated(api.list_value_reports(
        part_a["id"], UNDERWRITER, limit=10, offset=0))[1]["total_count"] == 1


def referred_crane_file(api):
    """A quoted crane file whose insured value pushed it over the referral threshold."""
    fixtures.publish_rate_rule(api, equipment_type="CRANE", age_band_min_years=0,
                               age_band_max_years=5, base_rate_bp=310,
                               theft_hazard_grade="B")
    policy = fixtures.create_policy(api,
                                    policyholder_name="Segregated Referral Cranes")
    part = fixtures.create_part(api, policy["id"], factories.scheduled_equipment_part(
        valuation_basis="AGREED_VALUE", per_item_limit_cents=100000000))
    fixtures.schedule_item(api, part["id"], policy["id"],
                           description="Crawler Crane C1", equipment_type="CRANE",
                           model_year=2024, original_cost_cents=60000000,
                           stated_value_cents=60000000)
    fixtures.quote(api, policy["id"])
    referred = get_success_data(api.refer_policy(
        policy["id"], UNDERWRITER,
        factories.referral("TIV above the 50000000 threshold")))
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"], referred=referred)


def test_the_underwriter_who_referred_the_file_may_not_decide_it(api):
    """The manager role is not enough: the deciding identity must differ from the referring one.

    PRD: The policy must be `REFERRED` with `referral_status` `PENDING`, else `ERR_REFERRAL_NOT_PENDING`, and the deciding manager must not be the referring underwriter, else `ERR_SEGREGATION_OF_DUTIES`.
    PRD: The exposure test trips when `total_insured_value_cents` goes above $500,000 (50,000,000 cents) — strictly above, so exactly 50,000,000 cents does not trip it.
    PRD: An approval sets `referral_status` to `APPROVED` and returns the policy `REFERRED` → `QUOTED`, closing the `QUOTED` → `REFERRED` → `QUOTED` loop so that the file can be re-priced or bound.
    Design: Corner/rbac/corner_referral_decision_cannot_be_made_by_the_referring_user
    """
    ctx = referred_crane_file(api)
    assert ctx.referred["referral_required"] is True
    assert ctx.referred["total_insured_value_cents"] == 60000000
    assert ctx.referred["written_premium_cents"] == 2659800
    assert ctx.referred["status"] == "REFERRED"
    assert ctx.referred["referral_status"] == "PENDING"
    assert ctx.referred["referred_by_user_id"] == UNDERWRITER_USER_ID

    validate_error(api.decide_referral(
        ctx.policy_id, factories.referral_decision("APPROVE"),
        make_headers(UNDERWRITER_USER_ID, Role.UNDERWRITING_MANAGER)),
        api_errors.ERR_SEGREGATION_OF_DUTIES, 403)

    held = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert held["status"] == "REFERRED"
    assert held["referral_status"] == "PENDING"
    assert held["referral_decided_by_user_id"] is None

    decided = validate_success(api.decide_referral(
        ctx.policy_id, factories.referral_decision("APPROVE"), MANAGER))
    assert decided["status"] == "QUOTED"
    assert decided["referral_status"] == "APPROVED"
    assert decided["referral_decided_by_user_id"] == MANAGER_USER_ID

    bound = validate_success(api.bind_policy(ctx.policy_id, UNDERWRITER))
    assert bound["status"] == "BOUND"
    assert bound["premium_balance_cents"] == 2659800
    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=10, offset=0, ledger=Ledger.PREMIUM))
    assert meta["total_count"] == 1
    assert find_entry(rows, LedgerEntryType.INITIAL_PREMIUM)["amount_cents"] == 2659800


def drafted_schedule_awaiting_a_second_unit(api):
    """A drafted file whose single accepted unit has already moved the policy token."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Stale Token Contractors")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    token = fixtures.policy_version(api, policy["id"])
    first = validate_success(api.create_equipment_item(
        part["id"], factories.equipment_item(token), UNDERWRITER), 201)
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        opened_version=policy["version"], token=token,
                        first_id=first["id"])


def test_the_token_that_authorised_one_schedule_add_will_not_authorise_the_next(api):
    """Each accepted create consumes the token; each rejected one leaves it alone.

    PRD: `POST /inland-marine/coverage-parts/{id}/equipment-items` requires `expected_policy_version` in its request body, carrying the client's last observed `version` of the owning policy.
    PRD: If that value does not equal the policy's current `version`, the create is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412).
    PRD: - Scheduling a new equipment item onto a coverage part increments the owning **policy's** `version` by 1, because the item re-develops the part premium and therefore rewrites the policy's premium roll-ups, its total insured value and its referral flag.
    PRD: Adding a coverage part to a policy explicitly does **not** bump the policy's `version`.
    Design: Corner/cross_cutting_complexity_layers/corner_occ_policy_version_guards_the_second_schedule_add
    """
    ctx = drafted_schedule_awaiting_a_second_unit(api)
    assert ctx.token == ctx.opened_version
    assert fixtures.policy_version(api, ctx.policy_id) == ctx.token + 1
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 173318

    validate_error(api.create_equipment_item(
        ctx.part_id, factories.equipment_item(ctx.token, description="Excavator E2"),
        UNDERWRITER), api_errors.ERR_STALE_POLICY_VERSION, 412)

    assert fixtures.policy_version(api, ctx.policy_id) == ctx.token + 1
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 173318
    items, meta = validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=10, offset=0))
    assert meta["total_count"] == 1
    assert [row["id"] for row in items] == [ctx.first_id]

    second = validate_success(api.create_equipment_item(
        ctx.part_id,
        factories.equipment_item(ctx.token + 1, description="Excavator E2"),
        UNDERWRITER), 201)
    assert second["rated_premium_cents"] == 173318
    assert fixtures.policy_version(api, ctx.policy_id) == ctx.token + 2
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 346636
    rolled = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert rolled["written_premium_cents"] == 360501
    assert rolled["total_insured_value_cents"] == 16320000

    validate_error(api.create_equipment_item(
        ctx.part_id,
        factories.equipment_item(ctx.token + 1, description="Excavator E3"),
        UNDERWRITER), api_errors.ERR_STALE_POLICY_VERSION, 412)
    assert validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=10, offset=0))[1]["total_count"] == 2


def test_both_a_filing_and_an_endorsement_invalidate_an_outstanding_report_token(api):
    """The restatement needs the token the part carries now, not the one it carried before.

    PRD: `POST /inland-marine/coverage-parts/{id}/value-reports` requires `expected_coverage_part_version` in its request body, carrying the client's last observed `version` of the target coverage part.
    PRD: If that value does not equal the part's current `version`, the filing is rejected with `ERR_STALE_COVERAGE_PART_VERSION` (HTTP 412).
    PRD: - Endorsing a coverage part's terms increments that **coverage part's** `version` by 1.
    PRD: - Filing a value report on a coverage part, and running the delinquency sweep on one, each increment that **coverage part's** `version` by 1.
    Design: Corner/cross_cutting_complexity_layers/corner_occ_coverage_part_version_guards_the_restatement
    """
    policy, part = live_reporting_policy(api, "Stale Restatement Warehousing")
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    holder = make_policyholder_headers(policy["id"])
    token = fixtures.part_version(api, part["id"])
    first = validate_success(api.create_value_report(
        part["id"],
        factories.value_report("2026-08-01", "2026-08-31", 9000000, token),
        holder), 201)
    assert first["status"] == "SUBMITTED"
    assert fixtures.part_version(api, part["id"]) == token + 1

    def restate(version):
        return api.create_value_report(
            part["id"],
            factories.value_report("2026-08-01", "2026-08-31", 12000000, version),
            holder)

    validate_error(restate(token), api_errors.ERR_STALE_COVERAGE_PART_VERSION, 412)
    held = get_success_data(api.get_value_report(first["id"], UNDERWRITER))
    assert held["status"] == "SUBMITTED"
    assert held["superseded_by_report_id"] is None
    assert fixtures.part_version(api, part["id"]) == token + 1
    assert validate_paginated(api.list_value_reports(
        part["id"], UNDERWRITER, limit=10, offset=0))[1]["total_count"] == 1

    endorsed = validate_success(api.patch_coverage_part(
        part["id"], factories.part_endorsement(reporting_annual_rate_bp=300),
        UNDERWRITER))
    assert endorsed["version"] == token + 2

    validate_error(restate(token + 1), api_errors.ERR_STALE_COVERAGE_PART_VERSION, 412)

    second = validate_success(restate(token + 2), 201)
    assert second["status"] == "SUBMITTED"
    superseded = get_success_data(api.get_value_report(first["id"], UNDERWRITER))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_report_id"] == second["id"]
    assert fixtures.part_version(api, part["id"]) == token + 3

    rows, meta = validate_paginated(api.list_ledger_entries(
        policy["id"], UNDERWRITER, limit=10, offset=0))
    assert meta["total_count"] == 1
    assert find_entry(rows, LedgerEntryType.INITIAL_PREMIUM)["amount_cents"] == 100000
    assert get_success_data(api.get_policy(
        policy["id"], UNDERWRITER))["premium_balance_cents"] == 100000


def tracked_unit_on_an_unsurveyed_yard(api):
    """A quoted file whose only unit stands, geo-tracked, on an unscored site."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Cascade Contractors")
    part = fixtures.create_part(api, policy["id"],
                               factories.scheduled_equipment_part())
    yard = fixtures.create_jobsite(api, name="Cascade Yard")
    item = fixtures.schedule_item(api, part["id"], policy["id"],
                                  geo_tracker_installed=True,
                                  assigned_jobsite_id=yard["id"])
    fixtures.quote(api, policy["id"])
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        jobsite_id=yard["id"], item_id=item["id"])


def assert_the_untiered_shape(api, ctx):
    """The figures that hold whenever the yard scores zero and only the tracker pays."""
    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["security_score"] == 0
    assert site["security_tier"] == "TIER_0"
    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["applied_credit_bp"] == 1500
    assert item["rated_premium_cents"] == 147321
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 147321
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["written_premium_cents"] == 153214


def test_one_security_survey_walks_four_levels_up_to_the_policy(api):
    """Site, unit, part and policy all move on the survey's own response cycle.

    PRD: | POST | `/inland-marine/jobsites/{id}/security-survey` | Record the jobsite security survey; re-scores the site and re-prices every item standing on it. | `Underwriter` |
    PRD: The `security_score` is the sum of their weights: one point each for fencing, lighting and alarm monitoring, and two points for the guard, because a live guard is worth two controls.
    PRD: A unit standing on a jobsite earns a jobsite security credit keyed on that site's `security_tier`: nothing at `TIER_0`, 300 basis points at `TIER_1`, 700 at `TIER_2` and 1,200 at `TIER_3`; a unit with no `assigned_jobsite_id` earns no security credit at all.
    PRD: Whenever an equipment item is rated or re-rated, the item's own derived fields are rewritten, then its parent coverage part's `rated_premium_cents` is recomputed from the surviving schedule, then the owning policy's `sum_of_part_premiums_cents`, `written_premium_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, `total_insured_value_cents` and `referral_required` are all re-derived.
    Design: Corner/cross_cutting_complexity_layers/corner_jobsite_resurvey_cascades_four_levels_to_the_policy
    """
    ctx = tracked_unit_on_an_unsurveyed_yard(api)
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["status"] == "UNSURVEYED"
    assert_the_untiered_shape(api, ctx)

    surveyed = validate_success(api.record_security_survey(
        ctx.jobsite_id, factories.security_survey(**factories.SURVEY_TIER_2),
        UNDERWRITER))

    assert surveyed["security_score"] == 3
    assert surveyed["security_tier"] == "TIER_2"
    assert surveyed["status"] == "SURVEYED"
    assert_instant_equals(surveyed["surveyed_at"], "2026-08-01T00:00:00Z")

    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["applied_credit_bp"] == 2200
    assert item["rated_premium_cents"] == 135188
    assert item["insured_value_cents"] == 8160000
    assert item["applied_base_rate_bp"] == 180

    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 135188
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["sum_of_part_premiums_cents"] == 135188
    assert policy["written_premium_cents"] == 140596
    assert policy["total_insured_value_cents"] == 8160000


def test_stripping_the_controls_back_out_walks_the_same_four_hops_downward(api):
    """A tracked unit keeps the site scoreable in both directions, and the money follows.

    PRD: The survey stamps `surveyed_at` from the logical clock and moves the site's `status` to `SURVEYED`, whether it was `UNSURVEYED`, already `SURVEYED` (a re-survey), or `RELEASED` (a re-survey of a released site).
    PRD: Concretely: if the rate cell selected for a unit carries `theft_hazard_grade` `A`, and the site the unit would stand on has a `security_tier` of `TIER_0` or `TIER_1`, and the unit's `geo_tracker_installed` is false, the operation is refused with `ERR_GEO_TRACKING_REQUIRED`.
    PRD: The item's `applied_credit_bp` is the lesser of 2,500 basis points and the sum of the two credits, so the cap binds exactly when a tracker on a high-hazard unit (1,500) meets a perfect site (1,200) and the uncapped sum of 2,700 is trimmed to 2,500.
    Design: Corner/cross_cutting_complexity_layers/corner_jobsite_resurvey_cascades_four_levels_to_the_policy
    """
    ctx = tracked_unit_on_an_unsurveyed_yard(api)
    validate_success(api.record_security_survey(
        ctx.jobsite_id, factories.security_survey(**factories.SURVEY_TIER_2),
        UNDERWRITER))
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["rated_premium_cents"] == 135188

    stripped = validate_success(api.record_security_survey(
        ctx.jobsite_id, factories.security_survey(**factories.SURVEY_TIER_0),
        UNDERWRITER))

    assert stripped["security_score"] == 0
    assert stripped["security_tier"] == "TIER_0"
    assert stripped["status"] == "SURVEYED"
    assert_the_untiered_shape(api, ctx)
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["sum_of_part_premiums_cents"] == 147321


def two_identical_parts_each_carrying_one_unit(api):
    """One policy, two indistinguishable scheduled parts, one canonical unit on each."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Rounding Order Contractors")
    first = fixtures.create_part(api, policy["id"],
                                 factories.scheduled_equipment_part())
    second = fixtures.create_part(api, policy["id"],
                                  factories.scheduled_equipment_part())
    unit_a = fixtures.schedule_item(api, first["id"], policy["id"],
                                    description="Excavator A")
    unit_b = fixtures.schedule_item(api, second["id"], policy["id"],
                                    description="Excavator B")
    return fixtures.Ctx(policy_id=policy["id"], first_part_id=first["id"],
                        second_part_id=second["id"], unit_a=unit_a, unit_b=unit_b)


def test_the_expense_load_is_applied_to_the_sum_and_not_to_each_part(api):
    """Two parts of 173318 roll up to 360501, one cent below the per-part order.

    PRD: The territory expense load is then applied **once, to that single sum** — never per part: multiply `sum_of_part_premiums_cents` by the expense load of the policy's `territory_code`, divide by ten thousand, and round half-up once.
    PRD: Because the load is applied to the sum rather than per part, two identical `T2_URBAN` parts of 173,318 cents each roll up to 360,501 cents and not 360,502.
    PRD: Rolling a policy premium up, for instance, means summing the unloaded part premiums exactly, applying the territory expense load to that single sum, and rounding once; loading each part separately and rounding per part is wrong and diverges by whole cents.
    Design: Corner/cross_cutting_complexity_layers/corner_aggregation_rounding_order_is_observable_across_two_parts
    """
    ctx = two_identical_parts_each_carrying_one_unit(api)
    assert ctx.unit_a["rated_premium_cents"] == 173318
    assert ctx.unit_b["rated_premium_cents"] == 173318
    assert get_success_data(api.get_coverage_part(
        ctx.first_part_id, UNDERWRITER))["rated_premium_cents"] == 173318
    assert get_success_data(api.get_coverage_part(
        ctx.second_part_id, UNDERWRITER))["rated_premium_cents"] == 173318

    quoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))
    assert quoted["sum_of_part_premiums_cents"] == 346636
    assert quoted["written_premium_cents"] == 360501

    summary = validate_success(api.get_premium_summary(ctx.policy_id, UNDERWRITER))
    assert summary["sum_of_part_premiums_cents"] == 346636
    assert summary["expense_load_bp"] == 10400
    assert summary["written_premium_cents"] == 360501
    assert summary["total_insured_value_cents"] == 16320000
    assert summary["minimum_premium_applied"] is False


def crane_file_at(api, policyholder_name, stated_value_cents):
    """A drafted crane file whose single unit is stated at the value under test."""
    policy = fixtures.create_policy(api, policyholder_name=policyholder_name)
    part = fixtures.create_part(api, policy["id"], factories.scheduled_equipment_part(
        valuation_basis="AGREED_VALUE", per_item_limit_cents=100000000))
    item = fixtures.schedule_item(api, part["id"], policy["id"],
                                  description="Crane Under Test",
                                  equipment_type="CRANE", model_year=2024,
                                  original_cost_cents=stated_value_cents,
                                  stated_value_cents=stated_value_cents)
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        item_id=item["id"])


def test_one_cent_of_insured_value_trips_the_referral_without_moving_the_premium(api):
    """Exactly fifty million does not trip the exposure test; fifty million and one does.

    PRD: The exposure test trips when `total_insured_value_cents` goes above $500,000 (50,000,000 cents) — strictly above, so exactly 50,000,000 cents does not trip it.
    PRD: `referral_required` is recomputed on every quote and is true when either of two tests trips, and the two deliberately differ in strictness.
    PRD: It also requires referral clearance: if `referral_required` is true then `referral_status` must be `APPROVED`, and otherwise the bind is refused with `ERR_REFERRAL_REQUIRED`.
    Design: Corner/cross_cutting_complexity_layers/corner_referral_tiv_threshold_is_strict_and_resets
    """
    fixtures.publish_rate_rule(api, equipment_type="CRANE", age_band_min_years=0,
                               age_band_max_years=5, base_rate_bp=310,
                               theft_hazard_grade="B")
    at_threshold = crane_file_at(api, "At Threshold Cranes", 50000000)
    over_threshold = crane_file_at(api, "One Cent Over Cranes", 50000001)

    inside = validate_success(api.quote_policy(at_threshold.policy_id, UNDERWRITER))
    assert inside["total_insured_value_cents"] == 50000000
    assert inside["sum_of_part_premiums_cents"] == 2131250
    assert inside["written_premium_cents"] == 2216500
    assert inside["referral_required"] is False

    outside = validate_success(api.quote_policy(over_threshold.policy_id, UNDERWRITER))
    assert outside["total_insured_value_cents"] == 50000001
    assert outside["sum_of_part_premiums_cents"] == 2131250
    assert outside["written_premium_cents"] == 2216500
    assert outside["referral_required"] is True

    validate_error(api.bind_policy(over_threshold.policy_id, UNDERWRITER),
                   api_errors.ERR_REFERRAL_REQUIRED, 422)


def test_the_exposure_trigger_resets_when_the_value_that_raised_it_leaves(api):
    """Removing the crane and re-quoting clears the flag instead of latching it.

    PRD: `referral_required` is recomputed on every quote and is true when either of two tests trips, and the two deliberately differ in strictness.
    PRD: **Mid-term endorsement money.** Adding or removing a unit while the owning policy is `IN_FORCE` or `SUSPENDED` books a prorated premium movement.
    PRD: Finally the minimum premium floor is applied, strictly **after** the load: `written_premium_cents` is the greater of the loaded figure and the policy's `minimum_premium_cents`.
    Design: Corner/cross_cutting_complexity_layers/corner_referral_tiv_threshold_is_strict_and_resets
    """
    fixtures.publish_rate_rule(api, equipment_type="CRANE", age_band_min_years=0,
                               age_band_max_years=5, base_rate_bp=310,
                               theft_hazard_grade="B")
    ctx = crane_file_at(api, "One Cent Over Cranes", 50000001)
    quoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))
    assert quoted["referral_required"] is True

    removed = validate_success(api.delete_equipment_item(ctx.item_id, UNDERWRITER))
    assert removed["status"] == "REMOVED"
    assert validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=10, offset=0))[1]["total_count"] == 0

    requoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))
    assert requoted["total_insured_value_cents"] == 0
    assert requoted["sum_of_part_premiums_cents"] == 0
    assert requoted["written_premium_cents"] == 100000
    assert requoted["referral_required"] is False


def test_the_minimum_premium_alone_can_trip_the_inclusive_premium_threshold(api):
    """The trigger reads the floored figure, so an itemless file can still refer.

    PRD: The premium test trips when `written_premium_cents` reaches $50,000 (5,000,000 cents) — at or above, inclusive.
    PRD: Finally the minimum premium floor is applied, strictly **after** the load: `written_premium_cents` is the greater of the loaded figure and the policy's `minimum_premium_cents`.
    PRD: Referral is permitted only when the policy is `QUOTED`, only when `referral_required` is true, and only when `referral_status` is `NOT_REQUIRED` or `DECLINED`; a referral that is already `PENDING` or `APPROVED`, a policy that is not `QUOTED`, or a policy whose thresholds never tripped is refused with `ERR_POLICY_NOT_REFERRABLE`.
    Design: Corner/cross_cutting_complexity_layers/corner_referral_premium_threshold_is_inclusive_and_can_be_tripped_by_the_minimum
    """
    at_threshold = fixtures.create_policy(
        api, policyholder_name="Minimum At Threshold Co",
        minimum_premium_cents=5000000)
    fixtures.create_part(api, at_threshold["id"],
                         factories.scheduled_equipment_part())
    one_under = fixtures.create_policy(
        api, policyholder_name="Minimum One Cent Under Co",
        minimum_premium_cents=4999999)
    fixtures.create_part(api, one_under["id"],
                         factories.scheduled_equipment_part())

    floored = validate_success(api.quote_policy(at_threshold["id"], UNDERWRITER))
    assert floored["sum_of_part_premiums_cents"] == 0
    assert floored["written_premium_cents"] == 5000000
    assert floored["total_insured_value_cents"] == 0
    assert floored["referral_required"] is True

    just_under = validate_success(api.quote_policy(one_under["id"], UNDERWRITER))
    assert just_under["sum_of_part_premiums_cents"] == 0
    assert just_under["written_premium_cents"] == 4999999
    assert just_under["referral_required"] is False

    summary = validate_success(api.get_premium_summary(at_threshold["id"],
                                                       UNDERWRITER))
    assert summary["minimum_premium_applied"] is True
    assert summary["written_premium_cents"] == 5000000

    assert validate_success(api.refer_policy(
        at_threshold["id"], UNDERWRITER,
        factories.referral("Floored at the referral threshold")))["status"] == "REFERRED"
    validate_error(api.refer_policy(one_under["id"], UNDERWRITER,
                                    factories.referral("Should not be referrable")),
                   api_errors.ERR_POLICY_NOT_REFERRABLE, 409)


def test_the_underwriter_drives_the_file_and_only_the_manager_can_end_it(api):
    """Neither lifecycle authority subsumes the other: both directions are 403.

    PRD: **Quoting.** An `Underwriter` quotes a policy that is `DRAFT` or `QUOTED`; any other status is refused with `ERR_POLICY_NOT_QUOTABLE`.
    PRD: **Cancellation.** Only an `UnderwritingManager` cancels, and only from `BOUND`, `IN_FORCE` or `SUSPENDED`; from `DRAFT`, `QUOTED`, `REFERRED` or from any terminal status the attempt is refused with `ERR_POLICY_ALREADY_TERMINAL`.
    PRD: An `UnderwritingManager` holds the authorities the underwriter must not hold: deciding referrals, cancelling policies, authorising claim payments, and setting the service's logical clock.
    PRD: When the `cancellation_reason` is `INSURED_REQUEST` the insurer keeps a short-rate penalty of 10 percent: the amount actually returned is 9,000 basis points of the already-rounded pro-rata figure, divided by ten thousand and rounded half-up a second time.
    PRD: Finally every coverage part still `ACTIVE` becomes `VOID`.
    Design: Corner/rbac/corner_policy_lifecycle_authority_splits_between_underwriter_and_manager
    """
    policy = fixtures.create_policy(api, policyholder_name="Split Authority Co")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    surrender = factories.cancellation("INSURED_REQUEST", "2026-11-01")

    validate_error(api.quote_policy(policy["id"], MANAGER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    assert get_success_data(api.get_policy(
        policy["id"], UNDERWRITER))["status"] == "DRAFT"

    quoted = validate_success(api.quote_policy(policy["id"], UNDERWRITER))
    assert quoted["status"] == "QUOTED"
    assert quoted["written_premium_cents"] == 100000
    bound = validate_success(api.bind_policy(policy["id"], UNDERWRITER))
    assert bound["status"] == "BOUND"
    assert bound["premium_balance_cents"] == 100000
    assert validate_success(api.activate_policy(
        policy["id"], UNDERWRITER))["status"] == "IN_FORCE"

    validate_error(api.cancel_policy(policy["id"], surrender, UNDERWRITER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.cancel_policy(policy["id"], surrender, ADJUSTER),
                   api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    held, held_meta = validate_paginated(api.list_ledger_entries(
        policy["id"], UNDERWRITER, limit=10, offset=0, ledger=Ledger.PREMIUM))
    assert get_success_data(api.get_policy(
        policy["id"], UNDERWRITER))["status"] == "IN_FORCE"
    assert held_meta["total_count"] == 1
    assert find_entry(held, LedgerEntryType.CANCELLATION_RETURN) is None

    cancelled = validate_success(api.cancel_policy(policy["id"], surrender, MANAGER))
    assert cancelled["status"] == "CANCELLED"
    assert get_success_data(api.get_coverage_part(
        part["id"], UNDERWRITER))["status"] == "VOID"

    rows, meta = validate_paginated(api.list_ledger_entries(
        policy["id"], UNDERWRITER, limit=10, offset=0, ledger=Ledger.PREMIUM))
    assert meta["total_count"] == 2
    assert find_entry(rows, LedgerEntryType.CANCELLATION_RETURN)["amount_cents"] == -67316
    assert get_success_data(api.get_policy(
        policy["id"], UNDERWRITER))["premium_balance_cents"] == 32684
