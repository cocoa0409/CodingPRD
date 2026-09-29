"""Walks along the declared state machines: the openings, the legal hops and the refusals."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_common_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_zero_fields,
)
from test_helpers.test_users import ACTUARY, ADJUSTER, MANAGER, UNDERWRITER
from test_helpers.types import Ledger


def test_a_freshly_opened_policy_sits_in_draft_with_every_derived_field_at_rest(api):
    """Nothing is priced, nothing is stamped, nothing is referred: the opening state.

    PRD: The new policy opens in `status` `DRAFT` with `referral_status` `NOT_REQUIRED`, `referral_required` false, `referred_by_user_id` and `referral_decided_by_user_id` both null, `cancellation_reason` and `cancel_effective_date` both null, `quoted_at`, `bound_at` and `in_force_at` all null, `occupancy_termination_count` at 0, and every money roll-up — `sum_of_part_premiums_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, `written_premium_cents`, `premium_balance_cents`, `incurred_loss_cents` and `total_insured_value_cents` — at 0.
    PRD: A policy moves through the states `DRAFT`, `QUOTED`, `REFERRED`, `DECLINED`, `BOUND`, `IN_FORCE`, `SUSPENDED`, `CANCELLED` and `EXPIRED`, of which `DECLINED`, `CANCELLED` and `EXPIRED` are terminal.
    Design: Corner/state_machines/corner_policy_starts_in_initial_state_draft
    """
    created = validate_success(
        api.create_policy(factories.policy(policyholder_name="Opening Day Co"),
                          UNDERWRITER), 201)

    assert_common_fields(created)
    assert created["status"] == "DRAFT"
    assert created["referral_status"] == "NOT_REQUIRED"
    assert created["referral_required"] is False
    assert created["term_days"] == 365
    assert_null_fields(created, ["referred_by_user_id", "referral_decided_by_user_id",
                                 "cancellation_reason", "cancel_effective_date",
                                 "quoted_at", "bound_at", "in_force_at"])
    assert_zero_fields(created, ["occupancy_termination_count",
                                 "sum_of_part_premiums_cents",
                                 "scheduled_basis_premium_cents",
                                 "blanket_basis_premium_cents",
                                 "written_premium_cents", "premium_balance_cents",
                                 "incurred_loss_cents", "total_insured_value_cents"])

    stored = get_success_data(api.get_policy(created["id"], UNDERWRITER))
    assert stored["status"] == "DRAFT"
    assert stored["version"] == created["version"]


def test_quoting_the_draft_stamps_the_clock_and_prices_both_variants(api):
    """One hop DRAFT to QUOTED prices the file without moving a cent of ledger money.

    PRD: A `DRAFT` policy becomes `QUOTED`; a `QUOTED` policy re-quotes to `QUOTED` again, which is how a policy is re-priced after a schedule or limit endorsement without leaving the quoted state.
    PRD: The two comparison roll-ups run the identical load-then-floor pipeline over the corresponding variant premiums, producing `scheduled_basis_premium_cents` and `blanket_basis_premium_cents`.
    PRD: While the policy is still `DRAFT`, `QUOTED`, `REFERRED` or `BOUND`, no endorsement entry is written at all — the unit is simply folded into the quote.
    Design: Corner/state_machines/corner_policy_quote_transition_stamps_and_prices
    """
    ctx = fixtures.build_scheduled_file(api)
    assert ctx.policy["status"] == "DRAFT"
    assert ctx.item["rated_premium_cents"] == 173318

    quoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))

    assert quoted["status"] == "QUOTED"
    assert_instant_equals(quoted["quoted_at"], "2026-08-01T00:00:00Z")
    assert quoted["sum_of_part_premiums_cents"] == 173318
    assert quoted["written_premium_cents"] == 180251
    assert quoted["scheduled_basis_premium_cents"] == 180251
    assert quoted["total_insured_value_cents"] == 8160000
    assert quoted["referral_required"] is False
    assert quoted["premium_balance_cents"] == 0
    assert quoted["bound_at"] is None
    assert quoted["in_force_at"] is None

    _, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0, ledger=Ledger.ALL))
    assert meta["total_count"] == 0


def test_binding_a_policy_that_was_never_quoted_is_refused(api):
    """The bind hop starts at QUOTED, so a DRAFT file has no edge to travel.

    PRD: Binding requires the policy to be `QUOTED`, else `ERR_POLICY_NOT_BINDABLE`, and requires a `written_premium_cents` above zero.
    PRD: The part's own derived fields open at their base values: `aggregate_available_cents` equal to `aggregate_limit_cents`, `aggregate_paid_net_cents` at 0, `earned_reported_premium_cents` at 0, `rated_premium_cents` at 0, and `deposit_premium_cents` and `latest_report_period_end_date` both null.
    Design: Corner/state_machines/corner_policy_bind_from_draft_rejected
    """
    ctx = fixtures.build_transit_file(
        api, part_kwargs=dict(transit_owned_limit_cents=10000000,
                              transit_hired_limit_cents=0,
                              catastrophe_limit_cents=5000000))
    assert ctx.part["status"] == "ACTIVE"
    assert ctx.part["rated_premium_cents"] == 0
    assert ctx.part["deposit_premium_cents"] is None

    refused = api.bind_policy(ctx.policy_id, UNDERWRITER)

    validate_error(refused, "ERR_POLICY_NOT_BINDABLE", 409)
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "DRAFT"
    assert policy["bound_at"] is None
    assert policy["written_premium_cents"] == 0
    assert policy["premium_balance_cents"] == 0
    _, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0, ledger=Ledger.ALL))
    assert meta["total_count"] == 0


def test_activating_an_already_in_force_policy_is_refused_and_changes_nothing(api):
    """IN_FORCE has no self-loop on activation, and the first stamp survives the refusal.

    PRD: A policy that is not `BOUND`, or one whose effective date the clock has not yet reached, is refused with `ERR_POLICY_NOT_ACTIVATABLE`.
    PRD: On success the policy moves `BOUND` → `IN_FORCE` and `in_force_at` is stamped from the logical clock.
    Design: Corner/state_machines/corner_policy_activate_twice_rejected
    """
    ctx = fixtures.build_in_force_transit_file(
        api, part_kwargs=dict(transit_owned_limit_cents=10000000,
                              transit_hired_limit_cents=0,
                              catastrophe_limit_cents=5000000))
    assert ctx.in_force["status"] == "IN_FORCE"
    assert_instant_equals(ctx.in_force["in_force_at"], "2026-08-01T00:00:00Z")

    refused = api.activate_policy(ctx.policy_id, UNDERWRITER)

    validate_error(refused, "ERR_POLICY_NOT_ACTIVATABLE", 409)
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "IN_FORCE"
    assert_instant_equals(policy["in_force_at"], "2026-08-01T00:00:00Z")
    assert policy["written_premium_cents"] == 535600
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 515000
    _, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0, ledger=Ledger.ALL))
    assert meta["total_count"] == 1


def test_a_cancelled_policy_accepts_no_further_transition_of_any_kind(api):
    """CANCELLED is terminal three ways over: no re-cancel, no re-quote, no new exposure.

    PRD: Only an `UnderwritingManager` cancels, and only from `BOUND`, `IN_FORCE` or `SUSPENDED`; from `DRAFT`, `QUOTED`, `REFERRED` or from any terminal status the attempt is refused with `ERR_POLICY_ALREADY_TERMINAL`.
    PRD: An `Underwriter` quotes a policy that is `DRAFT` or `QUOTED`; any other status is refused with `ERR_POLICY_NOT_QUOTABLE`.
    PRD: The one request that has no part target — adding a coverage part to a policy — yields `ERR_POLICY_NOT_MUTABLE` on all three terminal policy statuses.
    Design: Corner/state_machines/corner_policy_cancelled_is_terminal_lockdown
    """
    ctx = fixtures.build_in_force_file(api)
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")

    cancelled = validate_success(api.cancel_policy(
        ctx.policy_id,
        factories.cancellation("UNDERWRITING", "2026-11-01"), MANAGER))

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "UNDERWRITING"
    assert cancelled["cancel_effective_date"] == "2026-11-01"
    assert cancelled["premium_balance_cents"] == 45433

    validate_error(api.cancel_policy(
        ctx.policy_id,
        factories.cancellation("INSURED_REQUEST", "2026-11-15"), MANAGER),
        "ERR_POLICY_ALREADY_TERMINAL", 409)
    validate_error(api.quote_policy(ctx.policy_id, UNDERWRITER),
                   "ERR_POLICY_NOT_QUOTABLE", 409)
    validate_error(api.create_coverage_part(
        ctx.policy_id, factories.transit_part(), UNDERWRITER),
        "ERR_POLICY_NOT_MUTABLE", 409)

    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "CANCELLED"
    assert policy["cancellation_reason"] == "UNDERWRITING"
    assert policy["premium_balance_cents"] == 45433
    parts, meta = validate_paginated(api.list_coverage_parts(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
    assert parts[0]["status"] == "VOID"
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "REMOVED"


def test_publishing_a_second_cell_on_the_same_key_retires_the_first(api):
    """Two cells share one key, so publication moves the loser out of the candidate set.

    PRD: Publication also retires competition: any other cell already `PUBLISHED` with the identical `equipment_type`, `territory_code`, `age_band_min_years` and `age_band_max_years` is moved to `RETIRED`.
    PRD: `DRAFT` and `RETIRED` cells never enter the candidate set even when their band matches.
    Design: Corner/state_machines/corner_rate_rule_publish_retires_prior_identical_cell
    """
    incumbent = fixtures.publish_rate_rule(api)
    challenger = fixtures.draft_rate_rule(api, base_rate_bp=200)
    assert incumbent["status"] == "PUBLISHED"
    assert challenger["status"] == "DRAFT"
    assert challenger["published_at"] is None

    published = validate_success(
        api.publish_rate_rule(challenger["id"], ACTUARY))

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00Z")
    assert get_success_data(api.get_rate_rule(
        incumbent["id"], ACTUARY))["status"] == "RETIRED"

    # Build the file without publishing a further cell on the same key, so the
    # challenger is the newest PUBLISHED candidate rating selects.
    policy = fixtures.create_policy(api)
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    item = fixtures.schedule_item(api, part["id"], policy["id"])
    assert item["applied_rate_rule_id"] == challenger["id"]
    assert item["applied_base_rate_bp"] == 200
    assert item["age_years_at_rating"] == 4
    assert item["insured_value_cents"] == 8160000
    assert item["rated_premium_cents"] == 192576

    _, retired_page = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=50, offset=0, applied_rate_rule_id=incumbent["id"]))
    assert retired_page["total_count"] == 0
    _, live_page = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=50, offset=0, applied_rate_rule_id=challenger["id"]))
    assert live_page["total_count"] == 1


def test_publishing_an_already_published_cell_is_refused_without_restamping_it(api):
    """PUBLISHED has no self-loop, and the refusal leaves the original stamp alone.

    PRD: Publishing a cell that is already `PUBLISHED` or `RETIRED` is refused with `ERR_RATE_RULE_NOT_DRAFT`, and only `DRAFT` cells may be published — the three statuses a cell can hold are `DRAFT`, `PUBLISHED` and `RETIRED`.
    PRD: Publishing a cell moves it `DRAFT` → `PUBLISHED` and stamps `published_at` from the logical clock.
    Design: Corner/state_machines/corner_rate_rule_publish_twice_rejected
    """
    cell = fixtures.publish_rate_rule(api, equipment_type="CRANE",
                                     territory_code="T3_INLAND",
                                     base_rate_bp=310, theft_hazard_grade="B")
    assert cell["status"] == "PUBLISHED"
    assert_instant_equals(cell["published_at"], "2026-08-01T00:00:00Z")
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    refused = api.publish_rate_rule(cell["id"], ACTUARY)

    validate_error(refused, "ERR_RATE_RULE_NOT_DRAFT", 409)
    unchanged = get_success_data(api.get_rate_rule(cell["id"], ACTUARY))
    assert unchanged["status"] == "PUBLISHED"
    assert_instant_equals(unchanged["published_at"], "2026-08-01T00:00:00Z")
    assert unchanged["base_rate_bp"] == 310
    assert unchanged["theft_hazard_grade"] == "B"


def site_with_two_live_floaters(api):
    """One TIER_2 site carrying two ACTIVE floaters over adjacent closed intervals."""
    site = fixtures.create_jobsite(api, name="Twin Project Yard")
    site = fixtures.survey_jobsite(api, site["id"], factories.SURVEY_TIER_2)
    policy = fixtures.create_policy(api, policyholder_name="Twin Project Builders",
                                    minimum_premium_cents=50000)
    part = fixtures.create_part(api, policy["id"],
                               factories.installation_floater_part())
    autumn = fixtures.open_floater(
        api, part["id"], site["id"], project_name="Autumn fit-out",
        installed_value_limit_cents=20000000,
        coverage_start_date="2026-09-01", coverage_end_date="2026-12-01")
    winter = fixtures.open_floater(
        api, part["id"], site["id"], project_name="Winter fit-out",
        installed_value_limit_cents=15000000,
        coverage_start_date="2026-12-02", coverage_end_date="2027-03-02")
    quoted = fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_floater(api, autumn["id"])
    fixtures.activate_floater(api, winter["id"])
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        jobsite_id=site["id"], autumn_id=autumn["id"],
                        winter_id=winter["id"], autumn=autumn, winter=winter,
                        quoted=quoted)


def test_the_site_stays_surveyed_until_the_second_floater_leaves_the_live_set(api):
    """Two down to one is not a release; one down to zero is.

    PRD: A jobsite's `active_floater_count` is the number of installation floaters attached to it whose status is `PENDING` or `ACTIVE`.
    PRD: When the count falls to 0 from a positive value on a site that is `SURVEYED`, the site transitions `SURVEYED` → `RELEASED`, and the release is not cosmetic: a released site is no longer treated as secured, so every equipment item still assigned to it whose status is `RATED` or `ACTIVE` is re-rated with a jobsite security credit of zero.
    Design: Corner/state_machines/corner_jobsite_releases_only_when_last_floater_leaves
    """
    ctx = site_with_two_live_floaters(api)
    assert ctx.autumn["rated_premium_cents"] == 70575
    assert ctx.winter["rated_premium_cents"] == 52356
    before = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert before["active_floater_count"] == 2
    assert before["status"] == "SURVEYED"
    assert before["security_score"] == 3
    assert before["security_tier"] == "TIER_2"
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 122931
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["written_premium_cents"] == 127848

    validate_success(api.terminate_installation_floater(
        ctx.autumn_id, factories.floater_termination("OCCUPANCY", "2026-11-15"),
        UNDERWRITER))

    midway = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert midway["active_floater_count"] == 1
    assert midway["status"] == "SURVEYED"
    assert get_success_data(api.get_installation_floater(
        ctx.autumn_id, UNDERWRITER))["status"] == "TERMINATED_OCCUPANCY"

    validate_success(api.terminate_installation_floater(
        ctx.winter_id, factories.floater_termination("OCCUPANCY", "2026-12-20"),
        UNDERWRITER))

    after = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert after["active_floater_count"] == 0
    assert after["status"] == "RELEASED"
    assert get_success_data(api.get_installation_floater(
        ctx.winter_id, UNDERWRITER))["status"] == "TERMINATED_OCCUPANCY"
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["occupancy_termination_count"] == 2


def occupied_tower_floater(api):
    """One ACTIVE floater of 70575 on a TIER_2 site, on a policy floored at 50000."""
    return fixtures.build_in_force_installation_file(
        api, jobsite_controls=factories.SURVEY_TIER_2,
        policy_kwargs=dict(policyholder_name="Tower Occupancy Builders",
                           minimum_premium_cents=50000),
        floater_kwargs=dict(project_name="Tower A fit-out",
                            installed_value_limit_cents=20000000,
                            coverage_start_date="2026-09-01",
                            coverage_end_date="2026-12-01"))


def test_occupancy_termination_keeps_the_whole_premium_and_writes_no_ledger_row(api):
    """Seventy-six unexpired days are earned anyway, so the balance never moves.

    PRD: On `OCCUPANCY` — the structure has been occupied, which ends installation coverage on its own terms — the floater moves to `TERMINATED_OCCUPANCY`, `earned_premium_cents` is set to the whole `rated_premium_cents`, `unearned_return_cents` is zero, **no ledger entry is written at all**, and the policy's `occupancy_termination_count` is incremented by one.
    PRD: The `INSTALLATION_FLOATER` part's `rated_premium_cents` is the sum, over **every** floater on the part in **any** status, of that floater's `rated_premium_cents` minus its `unearned_return_cents`.
    Design: Corner/state_machines/corner_floater_occupancy_termination_earns_full_term
    """
    ctx = occupied_tower_floater(api)
    live = get_success_data(api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert live["term_days"] == 92
    assert live["rated_premium_cents"] == 70575
    assert live["status"] == "ACTIVE"
    before = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert before["written_premium_cents"] == 73398
    assert before["premium_balance_cents"] == 73398

    terminated = validate_success(api.terminate_installation_floater(
        ctx.floater_id, factories.floater_termination("OCCUPANCY", "2026-09-16"),
        UNDERWRITER))

    assert terminated["status"] == "TERMINATED_OCCUPANCY"
    assert terminated["termination_trigger"] == "OCCUPANCY"
    assert terminated["termination_date"] == "2026-09-16"
    assert terminated["earned_premium_cents"] == 70575
    assert terminated["unearned_return_cents"] == 0

    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 70575
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["written_premium_cents"] == 73398
    assert policy["premium_balance_cents"] == 73398
    assert policy["occupancy_termination_count"] == 1

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0, ledger=Ledger.ALL))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_PREMIUM"
    assert rows[0]["amount_cents"] == 73398
    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["active_floater_count"] == 0
    assert site["status"] == "RELEASED"


def test_approving_a_conveyance_twice_is_refused_and_the_first_stamp_stands(api):
    """APPROVED is not re-enterable, so neither the stamp nor the paperwork date moves.

    PRD: Approval is permitted from `PENDING_APPROVAL` or from `SUSPENDED`; a vehicle already `APPROVED` is refused with `ERR_VEHICLE_ALREADY_APPROVED`.
    PRD: It is created with status `PENDING_APPROVAL` and `in_transit_value_cents` of zero, and `approved_at` null.
    Design: Corner/state_machines/corner_vehicle_approve_when_already_approved_rejected
    """
    registered = fixtures.create_vehicle(api, unit_label="OWNED-12",
                                        approval_expires_on="2026-12-31")
    assert registered["status"] == "PENDING_APPROVAL"
    assert registered["in_transit_value_cents"] == 0
    assert registered["approved_at"] is None

    approved = fixtures.approve_vehicle(api, registered["id"])
    assert approved["status"] == "APPROVED"
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00Z")
    assert approved["approval_expires_on"] == "2026-12-31"
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    refused = api.approve_vehicle(registered["id"], UNDERWRITER,
                                  factories.vehicle_approval("2027-06-30"))

    validate_error(refused, "ERR_VEHICLE_ALREADY_APPROVED", 409)
    unchanged = get_success_data(api.get_vehicle(registered["id"], UNDERWRITER))
    assert unchanged["status"] == "APPROVED"
    assert unchanged["approval_expires_on"] == "2026-12-31"
    assert_instant_equals(unchanged["approved_at"], "2026-08-01T00:00:00Z")


def test_delivering_a_shipment_that_never_departed_is_refused(api):
    """Delivery reads IN_TRANSIT, so a PLANNED movement has no edge into DELIVERED.

    PRD: Delivery requires the shipment to be `IN_TRANSIT`, else `ERR_SHIPMENT_NOT_IN_REQUIRED_STATE`.
    PRD: It is created with status `PLANNED` and null `departed_at` and `delivered_at`.
    Design: Corner/state_machines/corner_shipment_deliver_before_departure_rejected
    """
    ctx = fixtures.build_in_force_transit_file(api)
    conveyance = fixtures.approve_vehicle(
        api, fixtures.create_vehicle(api, unit_label="OWNED-31")["id"])
    shipment = fixtures.plan_shipment(api, ctx.part_id, conveyance["id"],
                                     declared_value_cents=1000000)
    assert shipment["status"] == "PLANNED"
    assert shipment["departed_at"] is None
    assert shipment["delivered_at"] is None

    refused = api.deliver_shipment(shipment["id"], UNDERWRITER)

    validate_error(refused, "ERR_SHIPMENT_NOT_IN_REQUIRED_STATE", 409)
    still_planned = get_success_data(
        api.get_transit_shipment(shipment["id"], UNDERWRITER))
    assert still_planned["status"] == "PLANNED"
    assert still_planned["departed_at"] is None
    assert still_planned["delivered_at"] is None
    assert get_success_data(api.get_vehicle(
        conveyance["id"], UNDERWRITER))["in_transit_value_cents"] == 0


def test_the_clock_expires_the_floater_first_and_the_policy_nine_months_later(api):
    """Two moves of one clock, two discovered expiries, and no money returned by either.

    PRD: A floater that is `ACTIVE` when the logical clock passes its `coverage_end_date` — or when its owning policy expires in the same clock call — becomes `EXPIRED` with `termination_trigger` `EXPIRY`, `termination_date` set to `coverage_end_date`, `earned_premium_cents` equal to the full `rated_premium_cents`, `unearned_return_cents` zero and no ledger entry; the jobsite decrement and its release consequence still apply.
    PRD: When an `UnderwritingManager` advances the logical clock to a date at or past a policy's `expiration_date`, a policy that is `IN_FORCE` or `SUSPENDED` transitions to `EXPIRED` and its identifier is reported in the clock response's `expired_policy_ids`.
    Design: Corner/state_machines/corner_clock_advance_expires_floater_then_policy
    """
    ctx = occupied_tower_floater(api)

    first_move = fixtures.set_clock(api, "2026-12-02T00:00:00Z")

    assert first_move["expired_floater_ids"] == [ctx.floater_id]
    assert first_move["expired_policy_ids"] == []
    expired = get_success_data(
        api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert expired["status"] == "EXPIRED"
    assert expired["termination_trigger"] == "EXPIRY"
    assert expired["termination_date"] == "2026-12-01"
    assert expired["earned_premium_cents"] == 70575
    assert expired["unearned_return_cents"] == 0
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["status"] == "IN_FORCE"
    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["active_floater_count"] == 0
    assert site["status"] == "RELEASED"

    second_move = fixtures.set_clock(api, "2027-08-02T00:00:00Z")

    assert second_move["expired_policy_ids"] == [ctx.policy_id]
    assert ctx.floater_id not in second_move["expired_floater_ids"]
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "EXPIRED"
    assert policy["written_premium_cents"] == 73398
    assert policy["premium_balance_cents"] == 73398
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["status"] == "ACTIVE"


def referred_crane_file(api):
    """A quoted crane-and-floater file whose exposure has tripped the referral test."""
    fixtures.publish_rate_rule(api, equipment_type="CRANE", base_rate_bp=310,
                               theft_hazard_grade="B")
    site = fixtures.create_jobsite(api, name="Harbour Crane Yard")
    site = fixtures.survey_jobsite(api, site["id"], factories.SURVEY_TIER_2)
    policy = fixtures.create_policy(api, policyholder_name="Harbour Heavy Lift")
    equipment = fixtures.create_part(api, policy["id"],
                                    factories.scheduled_equipment_part(
                                        valuation_basis="AGREED_VALUE",
                                        per_item_limit_cents=None))
    floater_part = fixtures.create_part(api, policy["id"],
                                       factories.installation_floater_part())
    crane = fixtures.schedule_item(api, equipment["id"], policy["id"],
                                   description="Harbour crane",
                                   equipment_type="CRANE",
                                   original_cost_cents=60000000,
                                   stated_value_cents=60000000)
    floater = fixtures.open_floater(
        api, floater_part["id"], site["id"], project_name="Quay fit-out",
        installed_value_limit_cents=20000000,
        coverage_start_date="2026-09-01", coverage_end_date="2026-12-01")
    quoted = fixtures.quote(api, policy["id"])
    referred = get_success_data(api.refer_policy(policy["id"], UNDERWRITER))
    return fixtures.Ctx(policy_id=policy["id"], equipment_part_id=equipment["id"],
                        floater_part_id=floater_part["id"], jobsite_id=site["id"],
                        item_id=crane["id"], floater_id=floater["id"],
                        item=crane, floater=floater, quoted=quoted,
                        referred=referred)


def test_declining_the_referral_voids_both_parts_and_the_pending_floater(api):
    """One manager's DECLINE resolves every child and shuts the file to new exposure.

    PRD: A decline sets `referral_status` to `DECLINED`, moves the policy `REFERRED` → `DECLINED`, and cascades downward: every coverage part on the policy whose `status` is `ACTIVE` becomes `VOID`, and every installation floater on those parts whose status is `PENDING` or `ACTIVE` becomes `VOIDED` with `termination_trigger` `CANCELLATION`.
    PRD: The exposure test trips when `total_insured_value_cents` goes above $500,000 (50,000,000 cents) — strictly above, so exactly 50,000,000 cents does not trip it.
    PRD: So a child create or a part endorsement aimed at a part belonging to a cancelled or declined policy returns `ERR_PART_VOID`, not `ERR_POLICY_NOT_MUTABLE`.
    Design: Corner/state_machines/corner_referral_decline_voids_parts_and_pending_floaters
    """
    ctx = referred_crane_file(api)
    assert ctx.item["insured_value_cents"] == 60000000
    assert ctx.item["rated_premium_cents"] == 2557500
    assert ctx.floater["rated_premium_cents"] == 70575
    assert ctx.quoted["sum_of_part_premiums_cents"] == 2628075
    assert ctx.quoted["written_premium_cents"] == 2733198
    assert ctx.quoted["total_insured_value_cents"] == 60000000
    assert ctx.quoted["referral_required"] is True
    assert ctx.referred["status"] == "REFERRED"
    assert ctx.referred["referral_status"] == "PENDING"
    assert ctx.referred["referred_by_user_id"] == "uw-1"

    declined = validate_success(api.decide_referral(
        ctx.policy_id, factories.referral_decision("DECLINE"), MANAGER))

    assert declined["status"] == "DECLINED"
    assert declined["referral_status"] == "DECLINED"
    assert declined["referral_decided_by_user_id"] == "mgr-1"
    assert declined["premium_balance_cents"] == 0

    voided = get_success_data(
        api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert voided["status"] == "VOIDED"
    assert voided["termination_trigger"] == "CANCELLATION"
    assert voided["unearned_return_cents"] == 0
    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["active_floater_count"] == 0
    assert site["status"] == "RELEASED"
    assert site["security_score"] == 3
    assert site["security_tier"] == "TIER_2"

    parts, meta = validate_paginated(api.list_coverage_parts(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 2
    assert [part["status"] for part in parts] == ["VOID", "VOID"]
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "RATED"
    _, ledger = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=50, offset=0, ledger=Ledger.ALL))
    assert ledger["total_count"] == 0

    validate_error(api.bind_policy(ctx.policy_id, UNDERWRITER),
                   "ERR_POLICY_NOT_BINDABLE", 409)
    validate_error(api.create_equipment_item(
        ctx.equipment_part_id,
        factories.equipment_item(expected_policy_version=0,
                                 description="Second crane",
                                 equipment_type="CRANE",
                                 original_cost_cents=60000000,
                                 stated_value_cents=60000000),
        UNDERWRITER), "ERR_PART_VOID", 409)


def waived_salvage_claim(api):
    """The canonical file with its unit totalled, paid, and the salvage axis armed."""
    ctx = fixtures.build_in_force_file(api)
    ctx["claim"] = fixtures.build_total_loss_claim(api, ctx, loss_type="FIRE")
    ctx["settled"] = fixtures.settle(api, ctx.claim["id"])
    return ctx


def test_waiving_the_salvage_credits_nothing_and_still_closes_the_claim(api):
    """Zero proceeds is a disposition, not a no-op: the join closes with no money moved.

    PRD: Proceeds of exactly zero move the axis `PENDING` → `WAIVED` with `salvage_credit_cents` zero, no ledger entry at all, and both conserved quantities untouched — the capacity consumed by the loss stays consumed.
    PRD: Either branch closes the join: `adjustment_status` advances `SETTLED` → `CLOSED`, `CLOSED` is terminal on the adjustment axis, and `RECOVERED` and `WAIVED` are terminal on the salvage axis.
    PRD: Only a `ClaimsAdjuster` records the salvage outcome, and only on a claim whose `adjustment_status` is `SETTLED` and whose `salvage_status` is `PENDING`, else `ERR_CLAIM_NOT_SETTLED` — the wording is exact, because only a declared total loss ever arms the salvage axis, so a settled repair claim can never take this call.
    Design: Corner/state_machines/corner_salvage_waived_branch_credits_nothing_and_still_closes
    """
    ctx = waived_salvage_claim(api)
    assert ctx.settled["adjustment_status"] == "SETTLED"
    assert ctx.settled["salvage_status"] == "PENDING"
    assert ctx.settled["settlement_paid_cents"] == 8060000

    waived = validate_success(api.record_salvage_recovery(
        ctx.claim["id"], factories.salvage(0), ADJUSTER))

    assert waived["salvage_proceeds_cents"] == 0
    assert waived["salvage_credit_cents"] == 0
    assert waived["salvage_status"] == "WAIVED"
    assert waived["adjustment_status"] == "CLOSED"

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 8060000
    assert part["aggregate_available_cents"] == 191940000
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["incurred_loss_cents"] == 8060000
    assert policy["written_premium_cents"] == 100000
    assert policy["total_insured_value_cents"] == 0
    rows, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "CLAIM_SETTLEMENT"
    assert rows[0]["amount_cents"] == 8060000

    refused = api.record_salvage_recovery(
        ctx.claim["id"], factories.salvage(1500000), ADJUSTER)

    validate_error(refused, "ERR_CLAIM_NOT_SETTLED", 409)
    unchanged = get_success_data(api.get_claim(ctx.claim["id"], ADJUSTER))
    assert unchanged["salvage_status"] == "WAIVED"
    assert unchanged["salvage_credit_cents"] == 0
    assert unchanged["adjustment_status"] == "CLOSED"
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["aggregate_paid_net_cents"] == 8060000
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "TOTALED"
