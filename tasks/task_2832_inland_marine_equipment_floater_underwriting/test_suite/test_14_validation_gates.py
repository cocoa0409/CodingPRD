"""Nested windows, wrong parents, missing paperwork and the bounds of a page."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import (
    ADJUSTER,
    ADJUSTER_USER_ID,
    MANAGER,
    UNDERWRITER,
    make_policyholder_headers,
)

GLAZING = dict(project_name="Glazing package",
               installed_value_limit_cents=20000000,
               coverage_start_date="2026-09-01",
               coverage_end_date="2026-12-01")


def test_a_floater_running_past_the_expiration_is_refused_and_leaves_the_part_empty(api):
    """The policy window bounds the whole closed interval, both dates included.

    PRD: First, the whole closed interval must sit inside the policy term — `coverage_start_date` on or after the policy's `effective_date` and `coverage_end_date` on or before the policy's `expiration_date` — else `ERR_FLOATER_OUTSIDE_POLICY_TERM`.
    PRD: `term_days` counts both endpoints: take the whole days from `coverage_start_date` to `coverage_end_date` and add one.
    PRD: A newly created floater has status `PENDING`, `earned_premium_cents` zero, `unearned_return_cents` zero, and a null `termination_trigger` and `termination_date`.
    Design: Corner/validations/corner_floater_dates_bounded_by_term_and_own_coverage
    """
    ctx = fixtures.build_installation_file(
        api, jobsite_controls=factories.SURVEY_TIER_2,
        policy_kwargs=dict(policyholder_name="Nested Window Installers",
                           minimum_premium_cents=50000),
        with_floater=False)

    overrunning = api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Overrunning glazing package",
            installed_value_limit_cents=20000000,
            coverage_start_date="2026-09-01",
            coverage_end_date="2027-08-02"),
        UNDERWRITER)

    validate_error(overrunning, "ERR_FLOATER_OUTSIDE_POLICY_TERM", 422)
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 0
    _, meta = validate_paginated(api.list_installation_floaters(
        UNDERWRITER, limit=20, offset=0, coverage_part_id=ctx.part_id))
    assert meta["total_count"] == 0
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["active_floater_count"] == 0

    inside = fixtures.open_floater(api, ctx.part_id, ctx.jobsite_id, **GLAZING)

    assert inside["term_days"] == 92
    assert inside["status"] == "PENDING"
    assert inside["rated_premium_cents"] == 70575
    assert inside["earned_premium_cents"] == 0
    assert inside["unearned_return_cents"] == 0
    assert inside["termination_trigger"] is None
    assert inside["termination_date"] is None
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["active_floater_count"] == 1

    quoted = fixtures.quote(api, ctx.policy_id)
    assert quoted["written_premium_cents"] == 73398
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 70575


def test_a_termination_before_the_floater_s_own_start_is_refused_though_it_is_in_term(api):
    """The second window is the floater's own, so an in-term August date is still outside.

    PRD: **Terminating at acceptance or at occupancy.** Termination requires the floater to be `ACTIVE`, else `ERR_FLOATER_NOT_IN_REQUIRED_STATE`, and carries a `termination_reason` of either `ACCEPTANCE` or `OCCUPANCY` together with a `termination_date` that must lie within the floater's own closed coverage interval, else `ERR_TERMINATION_DATE_OUTSIDE_COVERAGE`.
    PRD: On `ACCEPTANCE` — the owner has accepted the completed work — the floater moves to `TERMINATED_ACCEPTANCE`, `earned_premium_cents` is `rated_premium_cents` multiplied by `elapsed_days`, divided by `term_days`, rounded half-up once, `unearned_return_cents` is `rated_premium_cents` minus that earned figure, and an `ENDORSEMENT_RETURN` entry is appended to the premium ledger for the negative of `unearned_return_cents`.
    PRD: When the count falls to 0 from a positive value on a site that is `SURVEYED`, the site transitions `SURVEYED` → `RELEASED`, and the release is not cosmetic: a released site is no longer treated as secured, so every equipment item still assigned to it whose status is `RATED` or `ACTIVE` is re-rated with a jobsite security credit of zero.
    Design: Corner/validations/corner_floater_dates_bounded_by_term_and_own_coverage
    """
    ctx = fixtures.build_in_force_installation_file(
        api, jobsite_controls=factories.SURVEY_TIER_2,
        policy_kwargs=dict(policyholder_name="Nested Window Installers",
                           minimum_premium_cents=50000),
        floater_kwargs=dict(**GLAZING))
    assert ctx["active_floater"]["status"] == "ACTIVE"
    assert ctx["active_floater"]["rated_premium_cents"] == 70575
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == 73398

    too_early = api.terminate_installation_floater(
        ctx["floater_id"],
        factories.floater_termination("ACCEPTANCE", "2026-08-15"), UNDERWRITER)

    validate_error(too_early, "ERR_TERMINATION_DATE_OUTSIDE_COVERAGE", 422)
    still_on_risk = get_success_data(
        api.get_installation_floater(ctx["floater_id"], UNDERWRITER))
    assert still_on_risk["status"] == "ACTIVE"
    assert still_on_risk["termination_trigger"] is None
    assert still_on_risk["termination_date"] is None
    assert still_on_risk["earned_premium_cents"] == 0

    accepted = validate_success(api.terminate_installation_floater(
        ctx["floater_id"],
        factories.floater_termination("ACCEPTANCE", "2026-10-01"), UNDERWRITER))

    assert accepted["status"] == "TERMINATED_ACCEPTANCE"
    assert accepted["termination_trigger"] == "ACCEPTANCE"
    assert accepted["termination_date"] == "2026-10-01"
    assert accepted["earned_premium_cents"] == 23781
    assert accepted["unearned_return_cents"] == 46794
    assert (accepted["earned_premium_cents"]
            + accepted["unearned_return_cents"]) == 70575
    returned = find_entry(fixtures.premium_ledger(api, ctx.policy_id),
                          "ENDORSEMENT_RETURN")
    assert returned is not None
    assert returned["amount_cents"] == -46794
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == 26604
    released = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert released["active_floater_count"] == 0
    assert released["status"] == "RELEASED"


def test_both_ends_of_the_policy_term_bound_the_loss_date(api):
    """Inception day is insurable, the day before is not, and expiration day is not either.

    PRD: The `loss_date` must fall on or after the policy's `effective_date` and strictly before its `expiration_date`, and on a cancelled policy it must additionally fall on or before the `cancel_effective_date`; otherwise `ERR_LOSS_DATE_OUTSIDE_TERM`.
    PRD: Its inspection and settlement figures — `repair_estimate_cents`, `actual_value_at_loss_cents`, `valuation_at_loss_cents`, `constructive_total_loss_threshold_cents`, `repair_basis_settlement_cents`, `total_loss_basis_settlement_cents`, `adjustment_basis`, `settlement_amount_cents`, `settlement_paid_cents` and `salvage_proceeds_cents` — are all null until the calls that produce them, while `underreporting_factor_bp` starts at 10000 and `loss_of_use_days_claimed`, `loss_of_use_paid_cents` and `salvage_credit_cents` all start at zero.
    PRD: Then `constructive_total_loss_threshold_cents` is 7,500 basis points — seventy-five percent — of `valuation_at_loss_cents`, divided by ten thousand and rounded half-up once.
    Design: Corner/validations/corner_loss_date_must_lie_inside_policy_term
    """
    ctx = fixtures.build_in_force_file(
        api, policy_kwargs=dict(policyholder_name="Loss Date Excavating"))

    for outside in ("2026-07-31", "2027-08-01", "2027-08-02"):
        validate_error(api.create_claim(
            ctx.policy_id,
            factories.claim(ctx.part_id, loss_date=outside, loss_type="THEFT",
                            equipment_item_id=ctx.item_id),
            UNDERWRITER), "ERR_LOSS_DATE_OUTSIDE_TERM", 422)

    _, empty = validate_paginated(api.list_claims(UNDERWRITER, limit=20, offset=0,
                                                 policy_id=ctx.policy_id))
    assert empty["total_count"] == 0
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 0

    on_inception_day = validate_success(api.create_claim(
        ctx.policy_id,
        factories.claim(ctx.part_id, loss_date="2026-08-01", loss_type="THEFT",
                        equipment_item_id=ctx.item_id),
        UNDERWRITER), 201)

    assert on_inception_day["loss_date"] == "2026-08-01"
    assert on_inception_day["adjustment_status"] == "OPEN"
    assert on_inception_day["salvage_status"] == "NOT_APPLICABLE"
    assert on_inception_day["repair_estimate_cents"] is None
    assert on_inception_day["settlement_amount_cents"] is None
    assert on_inception_day["valuation_at_loss_cents"] is None
    inspected = get_success_data(api.inspect_claim(
        on_inception_day["id"], factories.inspection(3000000, 8160000), ADJUSTER))
    assert inspected["valuation_at_loss_cents"] == 8160000
    assert inspected["constructive_total_loss_threshold_cents"] == 6120000
    assert inspected["underreporting_factor_bp"] == 10000


def wrong_bucket_hauling(api):
    """One IN_FORCE policy carrying both a SCHEDULED_EQUIPMENT and a TRANSIT part."""
    site = fixtures.create_jobsite(api, name="Mismatch Yard")
    fixtures.survey_jobsite(api, site["id"], factories.SURVEY_TIER_2)
    vehicle = fixtures.create_vehicle(api, unit_label="FLATBED-9",
                                      ownership="OWNED",
                                      per_conveyance_limit_cents=10000000)
    policy = fixtures.create_policy(api, policyholder_name="Wrong Bucket Hauling",
                                    minimum_premium_cents=50000)
    scheduled = fixtures.create_part(api, policy["id"],
                                     factories.scheduled_equipment_part())
    transit = fixtures.create_part(api, policy["id"], factories.transit_part())
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    return fixtures.Ctx(policy_id=policy["id"], scheduled_id=scheduled["id"],
                        transit_id=transit["id"], jobsite_id=site["id"],
                        vehicle_id=vehicle["id"])


def test_every_child_attachment_refuses_a_parent_of_the_wrong_part_type(api):
    """Five payloads, each valid for some part on this very policy, all refused.

    PRD: Equipment items may be scheduled only on parts whose `part_type` is `SCHEDULED_EQUIPMENT`, `BLANKET_EQUIPMENT`, `RENTED_LEASED` or `REPORTING_FORM`; anywhere else the create fails with `ERR_PART_TYPE_MISMATCH`.
    PRD: An installation floater is opened on an `INSTALLATION_FLOATER` coverage part — any other `part_type` is rejected with `ERR_PART_TYPE_MISMATCH` — and names a `jobsite_id`, a `project_name` of one to one hundred twenty non-blank characters, an `installed_value_limit_cents` above zero, and the two dates `coverage_start_date` and `coverage_end_date`, the end strictly after the start.
    PRD: A transit shipment is planned on a `TRANSIT` coverage part — any other `part_type` is `ERR_PART_TYPE_MISMATCH` — and names a `vehicle_id` that must resolve, else `ERR_VEHICLE_NOT_FOUND`.
    PRD: It runs on a `REPORTING_FORM` part — any other `part_type` is `ERR_PART_TYPE_MISMATCH` — and requires the owning policy to be `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`.
    Design: Corner/validations/corner_child_rows_must_match_parent_part_type
    """
    ctx = wrong_bucket_hauling(api)
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["status"] == "IN_FORCE"
    policyholder = make_policyholder_headers(ctx.policy_id)

    validate_error(api.create_equipment_item(
        ctx.transit_id,
        factories.equipment_item(fixtures.policy_version(api, ctx.policy_id),
                                 description="Excavator on the transit part"),
        UNDERWRITER), "ERR_PART_TYPE_MISMATCH", 422)
    validate_error(api.create_transit_shipment(
        ctx.scheduled_id, factories.transit_shipment(ctx.vehicle_id),
        UNDERWRITER), "ERR_PART_TYPE_MISMATCH", 422)
    validate_error(api.create_installation_floater(
        ctx.scheduled_id,
        factories.installation_floater(ctx.jobsite_id,
                                      project_name="Floater on the schedule part"),
        UNDERWRITER), "ERR_PART_TYPE_MISMATCH", 422)
    validate_error(api.create_value_report(
        ctx.scheduled_id,
        factories.value_report("2026-08-01", "2026-08-31", 9000000,
                               fixtures.part_version(api, ctx.scheduled_id)),
        policyholder), "ERR_PART_TYPE_MISMATCH", 422)
    validate_error(api.run_reporting_sweep(ctx.scheduled_id, UNDERWRITER),
                   "ERR_PART_TYPE_MISMATCH", 422)

    assert get_success_data(api.get_coverage_part(
        ctx.scheduled_id, UNDERWRITER))["rated_premium_cents"] == 0
    for counted in (
            api.list_part_equipment_items(ctx.transit_id, UNDERWRITER,
                                          limit=20, offset=0),
            api.list_transit_shipments(UNDERWRITER, limit=20, offset=0,
                                       coverage_part_id=ctx.scheduled_id),
            api.list_installation_floaters(UNDERWRITER, limit=20, offset=0,
                                           coverage_part_id=ctx.scheduled_id),
            api.list_value_reports(ctx.scheduled_id, UNDERWRITER, limit=20,
                                   offset=0)):
        _, meta = validate_paginated(counted)
        assert meta["total_count"] == 0


def owned_unit_with_an_inspected_claim(api):
    """A SCHEDULED_EQUIPMENT part that carries loss-of-use limits it may never use."""
    ctx = fixtures.build_in_force_file(
        api, policy_kwargs=dict(policyholder_name="Owned Fleet Repairs"),
        part_kwargs=dict(loss_of_use_daily_limit_cents=50000,
                         loss_of_use_max_days=10))
    ctx["claim"] = fixtures.build_inspected_claim(api, ctx, 3000000, 8160000,
                                                 loss_type="COLLISION")
    return ctx


def test_the_loss_of_use_extension_needs_the_part_type_and_the_ownership_together(api):
    """The limits are on the part, so only the part type and the ownership can refuse.

    PRD: A `loss_of_use_days_claimed` above zero is accepted only when the governing part's `part_type` is `RENTED_LEASED` and the subject item's `ownership` is `RENTED` or `LEASED`, else `ERR_LOSS_OF_USE_NOT_COVERED`.
    PRD: `loss_of_use_paid_cents` is zero unless the governing part's `part_type` is `RENTED_LEASED` **and** the subject item's `ownership` is `RENTED` or `LEASED`; when both hold, take the smaller of `loss_of_use_days_claimed` and the part's `loss_of_use_max_days`, and multiply that day count by the part's `loss_of_use_daily_limit_cents`.
    PRD: The `REPAIR` branch stores the supplied `loss_of_use_days_claimed`, recomputes `loss_of_use_paid_cents`, sets `settlement_amount_cents` to `repair_basis_settlement_cents`, moves the claim `INSPECTED` → `REPAIR_APPROVED`, and leaves `salvage_status` dormant at `NOT_APPLICABLE`; the damaged unit stays on risk and the part's premium is untouched.
    Design: Corner/validations/corner_loss_of_use_only_on_rented_leased_parts
    """
    ctx = owned_unit_with_an_inspected_claim(api)
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["part_type"] == "SCHEDULED_EQUIPMENT"
    assert part["loss_of_use_daily_limit_cents"] == 50000
    assert part["loss_of_use_max_days"] == 10
    assert ctx.item["ownership"] == "OWNED"
    assert ctx["claim"]["adjustment_status"] == "INSPECTED"
    assert ctx["claim"]["valuation_at_loss_cents"] == 8160000

    with_days = api.adjust_claim(ctx["claim"]["id"],
                                factories.adjustment("REPAIR", 3), ADJUSTER)

    validate_error(with_days, "ERR_LOSS_OF_USE_NOT_COVERED", 422)
    unadjusted = get_success_data(api.get_claim(ctx["claim"]["id"], ADJUSTER))
    assert unadjusted["adjustment_status"] == "INSPECTED"
    assert unadjusted["adjustment_basis"] is None
    assert unadjusted["loss_of_use_days_claimed"] == 0
    assert unadjusted["loss_of_use_paid_cents"] == 0

    without_days = validate_success(api.adjust_claim(
        ctx["claim"]["id"], factories.adjustment("REPAIR"), ADJUSTER))

    assert without_days["adjustment_status"] == "REPAIR_APPROVED"
    assert without_days["adjustment_basis"] == "REPAIR"
    assert without_days["loss_of_use_paid_cents"] == 0
    assert without_days["settlement_amount_cents"] == 2900000
    assert without_days["declared_by_user_id"] == ADJUSTER_USER_ID
    assert without_days["salvage_status"] == "NOT_APPLICABLE"


def test_the_settlement_is_tested_against_remaining_aggregate_not_the_item_limit(api):
    """The loss clears the per-item limit easily and still exhausts the aggregate.

    PRD: Three further gates apply in order: the settling manager's `X-User-ID` must differ from `declared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; no report on the claim's coverage part may be in status `DELINQUENT`, else `ERR_REPORTING_DELINQUENT`; and `settlement_amount_cents` must not exceed the part's `aggregate_available_cents`, else `ERR_AGGREGATE_LIMIT_EXHAUSTED`.
    PRD: The identity `aggregate_limit_cents` equals `aggregate_available_cents` plus `aggregate_paid_net_cents` holds at every observable moment.
    Design: Corner/validations/corner_settlement_capped_by_part_aggregate_capacity
    """
    ctx = fixtures.build_in_force_file(
        api, policy_kwargs=dict(policyholder_name="Thin Aggregate Excavating"),
        part_kwargs=dict(aggregate_limit_cents=2000000))
    claim = fixtures.build_repair_claim(api, ctx, 3000000, 8160000)
    assert claim["adjustment_status"] == "REPAIR_APPROVED"
    assert claim["settlement_amount_cents"] == 2900000
    thin = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert thin["aggregate_limit_cents"] == 2000000
    assert thin["aggregate_available_cents"] == 2000000
    assert thin["aggregate_paid_net_cents"] == 0

    refused = api.settle_claim(claim["id"], MANAGER)

    validate_error(refused, "ERR_AGGREGATE_LIMIT_EXHAUSTED", 422)
    unpaid = get_success_data(api.get_claim(claim["id"], MANAGER))
    assert unpaid["adjustment_status"] == "REPAIR_APPROVED"
    assert unpaid["settlement_paid_cents"] is None
    assert unpaid["settled_by_user_id"] is None
    after = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert after["aggregate_available_cents"] == 2000000
    assert after["aggregate_paid_net_cents"] == 0
    _, meta = validate_paginated(api.list_claim_ledger_entries(
        claim["id"], UNDERWRITER, limit=20, offset=0))
    assert meta["total_count"] == 0
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 0

    worksheet = validate_success(api.get_settlement_worksheet(claim["id"], MANAGER))
    assert worksheet["repair_basis_settlement_cents"] == 2900000
    assert worksheet["claim_limit_cents"] == 20000000
    assert worksheet["aggregate_available_cents"] == 2000000


def two_hired_trucks_and_a_loaded_run(api):
    """One hired unit with no carrier at all, one named, and a run planned on the first."""
    ctx = fixtures.build_in_force_transit_file(
        api, policy_kwargs=dict(policyholder_name="Hired Haul Co",
                                minimum_premium_cents=50000),
        part_kwargs=dict(transit_owned_limit_cents=4000000,
                         transit_hired_limit_cents=3000000,
                         catastrophe_limit_cents=2000000))
    nameless = fixtures.create_vehicle(api, unit_label="HIRE-NONAME",
                                       ownership="HIRED",
                                       per_conveyance_limit_cents=10000000)
    named = fixtures.create_vehicle(api, unit_label="HIRE-BLUELINE",
                                    ownership="HIRED",
                                    carrier_name="Blue Line Trucking",
                                    per_conveyance_limit_cents=10000000)
    ctx["nameless_id"] = nameless["id"]
    ctx["named_id"] = named["id"]
    ctx["shipment"] = fixtures.plan_shipment(
        api, ctx.part_id, nameless["id"],
        origin_territory_code="T2_URBAN", destination_territory_code="T3_INLAND",
        declared_value_cents=1000000)
    return ctx


def test_approving_a_hired_conveyance_needs_a_carrier_and_a_strictly_future_expiry(api):
    """An expiry equal to the clock date is already lapsed, and an unapproved truck stays put.

    PRD: A `HIRED` conveyance is a third party's truck and needs paperwork: it must have a `carrier_name` and an `approval_expires_on` that is strictly after the logical clock's current date, and re-approving a `SUSPENDED` hired conveyance requires the request itself to supply that fresh date; failing either, the approval is refused with `ERR_CARRIER_APPROVAL_MISSING`.
    PRD: Departure requires the shipment to be `PLANNED`, else `ERR_SHIPMENT_NOT_IN_REQUIRED_STATE`; requires the owning policy to be `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`; and requires the vehicle to be `APPROVED`, else `ERR_VEHICLE_NOT_APPROVED`.
    PRD: The conveyance limit is the part's `transit_owned_limit_cents` when the vehicle's `ownership` is `OWNED` and its `transit_hired_limit_cents` when the `ownership` is `HIRED`.
    Design: Corner/validations/corner_hired_vehicle_approval_requires_carrier_and_future_expiry
    """
    ctx = two_hired_trucks_and_a_loaded_run(api)
    assert ctx["shipment"]["status"] == "PLANNED"
    assert ctx["shipment"]["applicable_limit_cents"] == 3000000
    assert ctx["shipment"]["catastrophe_zone"] is False
    for pending in (ctx["nameless_id"], ctx["named_id"]):
        opening = get_success_data(api.get_vehicle(pending, UNDERWRITER))
        assert opening["status"] == "PENDING_APPROVAL"
        assert opening["approved_at"] is None

    validate_error(api.approve_vehicle(ctx["nameless_id"], UNDERWRITER),
                   "ERR_CARRIER_APPROVAL_MISSING", 422)
    validate_error(api.approve_vehicle(
        ctx["named_id"], UNDERWRITER,
        factories.vehicle_approval(approval_expires_on="2026-08-01")),
        "ERR_CARRIER_APPROVAL_MISSING", 422)
    still_pending = get_success_data(api.get_vehicle(ctx["named_id"], UNDERWRITER))
    assert still_pending["status"] == "PENDING_APPROVAL"
    assert still_pending["approval_expires_on"] is None

    grounded = api.depart_shipment(ctx["shipment"]["id"], UNDERWRITER)

    validate_error(grounded, "ERR_VEHICLE_NOT_APPROVED", 409)
    unmoved = get_success_data(
        api.get_transit_shipment(ctx["shipment"]["id"], UNDERWRITER))
    assert unmoved["status"] == "PLANNED"
    assert unmoved["departed_at"] is None
    assert get_success_data(api.get_vehicle(
        ctx["nameless_id"], UNDERWRITER))["in_transit_value_cents"] == 0

    approved = validate_success(api.approve_vehicle(
        ctx["named_id"], UNDERWRITER,
        factories.vehicle_approval(approval_expires_on="2026-12-31")))

    assert approved["status"] == "APPROVED"
    assert approved["approval_expires_on"] == "2026-12-31"
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00Z")


def test_the_page_window_is_inclusive_at_one_hundred_and_rejects_everything_outside(api):
    """Zero, one hundred and one, and a negative offset all fail at 400, not 422.

    PRD: A `limit` outside the inclusive range 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).
    PRD: Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.
    Design: Corner/validations/corner_pagination_bounds_rejected_on_list_endpoints
    """
    ctx = fixtures.build_scheduled_file(
        api, policy_kwargs=dict(policyholder_name="Page Bounds Contracting",
                                minimum_premium_cents=50000),
        item_kwargs=dict(description="Item 1"))
    second = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                    description="Item 2")

    for limit, offset in ((0, 0), (101, 0), (10, -1)):
        validate_error(api.list_equipment_items(
            UNDERWRITER, limit=limit, offset=offset,
            coverage_part_id=ctx.part_id), "ERR_INVALID_PAGINATION", 400)
    validate_error(api.list_claims(UNDERWRITER, limit=101, offset=0,
                                   policy_id=ctx.policy_id),
                   "ERR_INVALID_PAGINATION", 400)

    rows, meta = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=100, offset=0, coverage_part_id=ctx.part_id))

    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [ctx.item_id, second["id"]]
    assert [row["description"] for row in rows] == ["Item 1", "Item 2"]
