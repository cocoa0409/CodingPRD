"""Gates a row cannot see: another entity's state decides whether the call may proceed."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals
from test_helpers.test_users import ADJUSTER, MANAGER, UNDERWRITER


def test_a_bound_policy_will_not_let_its_rated_unit_go_on_risk(api):
    """The item is ready but the file is not: activation reads the parent's state.

    PRD: Activation moves it `RATED` → `ACTIVE`, and is possible only while the owning policy is `IN_FORCE` and the parent part is still `ACTIVE`; a void part rejects the activation with `ERR_PART_VOID`.
    PRD: Putting exposure on risk is stricter: activating an equipment item, activating an installation floater, dispatching a shipment and running the reporting sweep all require the owning policy to be exactly `IN_FORCE`, and any other status — including `BOUND` and `SUSPENDED` — is rejected with `ERR_POLICY_NOT_IN_FORCE`.
    Design: Difficulty/cross_entity_state_dependency/item_activation_gated_on_policy_in_force
    """
    ctx = fixtures.build_bound_file(api)
    assert ctx.bound["status"] == "BOUND"
    assert ctx.item["status"] == "RATED"
    assert ctx.item["insured_value_cents"] == 8160000
    assert ctx.item["rated_premium_cents"] == 173318

    refused = api.activate_equipment_item(ctx.item_id, UNDERWRITER)

    validate_error(refused, "ERR_POLICY_NOT_IN_FORCE", 409)
    still_rated = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert still_rated["status"] == "RATED"
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["written_premium_cents"] == 180251


def test_putting_the_policy_on_risk_opens_the_gate_without_re_rating_the_unit(api):
    """The identical call now succeeds, and activation is not a pricing event.

    PRD: On success the policy moves `BOUND` → `IN_FORCE` and `in_force_at` is stamped from the logical clock.
    PRD: A newly scheduled item carries `status` `RATED`, a null `removed_at`, and the derived trace `applied_rate_rule_id`, `age_years_at_rating`, `insured_value_cents`, `applied_base_rate_bp`, `applied_credit_bp` and `rated_premium_cents`.
    Design: Difficulty/cross_entity_state_dependency/item_activation_gated_on_policy_in_force
    """
    ctx = fixtures.build_bound_file(api)
    validate_error(api.activate_equipment_item(ctx.item_id, UNDERWRITER),
                   "ERR_POLICY_NOT_IN_FORCE", 409)

    on_risk = fixtures.activate(api, ctx.policy_id)
    assert on_risk["status"] == "IN_FORCE"
    assert on_risk["in_force_at"] is not None

    activated = validate_success(
        api.activate_equipment_item(ctx.item_id, UNDERWRITER))

    assert activated["status"] == "ACTIVE"
    assert activated["rated_premium_cents"] == 173318
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["written_premium_cents"] == 180251


def hired_conveyance_with_a_planned_run(api):
    """A hired truck approved only to the tenth, carrying one planned shipment."""
    ctx = fixtures.build_in_force_transit_file(
        api, part_kwargs=dict(transit_owned_limit_cents=10000000,
                              transit_hired_limit_cents=4000000,
                              catastrophe_limit_cents=5000000))
    vehicle = fixtures.create_vehicle(
        api, unit_label="HIRED-77", ownership="HIRED",
        carrier_name="Blue Ridge Cartage", per_conveyance_limit_cents=5000000,
        approval_expires_on="2026-08-10")
    vehicle = fixtures.approve_vehicle(api, vehicle["id"])
    fixtures.set_clock(api, "2026-08-04T00:00:00Z")
    shipment = fixtures.plan_shipment(
        api, ctx.part_id, vehicle["id"],
        origin_territory_code="T2_URBAN", destination_territory_code="T3_INLAND",
        departure_at="2026-08-05T08:00:00Z", arrival_at="2026-08-05T14:00:00Z",
        declared_value_cents=1000000)
    ctx["vehicle_id"] = vehicle["id"]
    ctx["shipment"] = shipment
    return ctx


def test_a_lapsed_carrier_approval_suspends_the_truck_and_refuses_the_dispatch(api):
    """The clock reaching the expiry date is itself the lapse, in the departure call.

    PRD: For a `HIRED` conveyance the carrier approval must still be current, meaning the logical clock's date is strictly before `approval_expires_on`; a clock date on or after that date is a lapse, and the lapse has two effects in the same call — the vehicle is set to `SUSPENDED`, and the departure itself is rejected with `ERR_VEHICLE_APPROVAL_EXPIRED`.
    PRD: The shipment's `applicable_limit_cents` is then the smallest of three quantities: that conveyance limit, the vehicle's own `per_conveyance_limit_cents`, and — only when `catastrophe_zone` is true — the part's `catastrophe_limit_cents`.
    Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_on_current_carrier_approval
    """
    ctx = hired_conveyance_with_a_planned_run(api)
    assert ctx.shipment["catastrophe_zone"] is False
    assert ctx.shipment["applicable_limit_cents"] == 4000000
    assert get_success_data(
        api.get_vehicle(ctx.vehicle_id, UNDERWRITER))["status"] == "APPROVED"

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    refused = api.depart_shipment(ctx.shipment["id"], UNDERWRITER)

    validate_error(refused, "ERR_VEHICLE_APPROVAL_EXPIRED", 422)
    vehicle = get_success_data(api.get_vehicle(ctx.vehicle_id, UNDERWRITER))
    assert vehicle["status"] == "SUSPENDED"
    assert vehicle["in_transit_value_cents"] == 0
    shipment = get_success_data(
        api.get_transit_shipment(ctx.shipment["id"], UNDERWRITER))
    assert shipment["status"] == "PLANNED"
    assert shipment["departed_at"] is None


def test_re_approving_the_carrier_lets_the_same_shipment_depart(api):
    """The suspension persists until fresh paperwork is supplied, then dispatch works.

    PRD: The vehicle's suspension persists after the rejection, so the operator must re-approve the conveyance with a fresh `approval_expires_on` before any shipment on it can depart.
    PRD: On a successful departure the shipment moves `PLANNED` → `IN_TRANSIT`, `departed_at` is stamped from the logical clock, and the vehicle's `in_transit_value_cents` is recomputed to include the shipment's `declared_value_cents`.
    Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_on_current_carrier_approval
    """
    ctx = hired_conveyance_with_a_planned_run(api)
    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    validate_error(api.depart_shipment(ctx.shipment["id"], UNDERWRITER),
                   "ERR_VEHICLE_APPROVAL_EXPIRED", 422)

    reapproved = fixtures.approve_vehicle(api, ctx.vehicle_id,
                                          approval_expires_on="2026-12-31")
    assert reapproved["status"] == "APPROVED"

    departed = validate_success(api.depart_shipment(ctx.shipment["id"], UNDERWRITER))

    assert departed["status"] == "IN_TRANSIT"
    assert_instant_equals(departed["departed_at"], "2026-08-10T00:00:00Z")
    assert get_success_data(api.get_vehicle(
        ctx.vehicle_id, UNDERWRITER))["in_transit_value_cents"] == 1000000
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 553000


AUGUST = ("2026-08-01", "2026-08-31")


def delinquent_reporting_file_with_an_approved_repair(api):
    """A swept, suspended reporting file whose only claim is ready to be paid."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Silent Insured Co")
    part = fixtures.create_part(api, policy["id"],
                                factories.reporting_form_part(
                                    per_item_limit_cents=20000000))
    item = fixtures.schedule_item(api, part["id"], policy["id"],
                                  description="Stock rig")
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, item["id"])
    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    swept = validate_success(api.run_reporting_sweep(part["id"], UNDERWRITER))

    claim = get_success_data(api.create_claim(
        policy["id"],
        factories.claim(part["id"], loss_date="2026-08-20", loss_type="FIRE",
                        equipment_item_id=item["id"]),
        UNDERWRITER))
    get_success_data(api.inspect_claim(
        claim["id"], factories.inspection(3000000, 8160000), ADJUSTER))
    approved = get_success_data(api.adjust_claim(
        claim["id"], factories.adjustment("REPAIR"), ADJUSTER))

    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        item_id=item["id"], swept=swept, claim=approved,
                        delinquent_id=swept["delinquent_report_ids"][0])


def test_a_delinquent_report_on_the_part_bars_payment_of_its_claim(api):
    """The claim is in order; a sibling report is not, and that decides the call.

    PRD: Delinquency also has a claims consequence: settlement of any claim on a part carrying a `DELINQUENT` report is barred, as §3.9 sets out.
    PRD: Reports in status `SUBMITTED`, `DELINQUENT` or `SUPERSEDED` are ignored entirely.
    Design: Difficulty/cross_entity_state_dependency/settlement_gated_on_reporting_form_delinquency
    """
    ctx = delinquent_reporting_file_with_an_approved_repair(api)
    assert ctx.swept["swept_period_count"] == 1
    assert ctx.swept["policy_status"] == "SUSPENDED"
    assert ctx.claim["underreporting_factor_bp"] == 10000
    assert ctx.claim["settlement_amount_cents"] == 2900000

    refused = api.settle_claim(ctx.claim["id"], MANAGER)

    validate_error(refused, "ERR_REPORTING_DELINQUENT", 409)
    unpaid = get_success_data(api.get_claim(ctx.claim["id"], UNDERWRITER))
    assert unpaid["adjustment_status"] == "REPAIR_APPROVED"
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 0
    assert part["aggregate_available_cents"] == 200000000
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "SUSPENDED"
    assert policy["incurred_loss_cents"] == 0
    assert policy["cancellation_reason"] is None


def test_curing_the_delinquency_lets_the_identical_settlement_through(api):
    """Filing and adjudicating the missing period lifts the bar the claim never broke.

    PRD: Settlement sets `settlement_paid_cents` to `settlement_amount_cents`, records `settled_by_user_id`, appends a `CLAIM_SETTLEMENT` entry to the **loss** ledger for the positive `settlement_paid_cents` carrying this claim's identifier, refreshes the policy's `incurred_loss_cents`, and moves the part's conserved capacity by adding the paid amount to `aggregate_paid_net_cents` and subtracting it from `aggregate_available_cents`.
    PRD: Both branches then run the same two follow-on hops: any other report on the same part with the identical `period_start_date` and `period_end_date` whose status is `SUBMITTED` or `DELINQUENT` becomes `SUPERSEDED` with `superseded_by_report_id` set to the adjudicated report's `id`, and if no report in status `DELINQUENT` remains on any coverage part of the policy while the policy is `SUSPENDED`, the policy returns `SUSPENDED` → `IN_FORCE`.
    Design: Difficulty/cross_entity_state_dependency/settlement_gated_on_reporting_form_delinquency
    """
    ctx = delinquent_reporting_file_with_an_approved_repair(api)
    validate_error(api.settle_claim(ctx.claim["id"], MANAGER),
                   "ERR_REPORTING_DELINQUENT", 409)

    filed = fixtures.file_value_report(api, ctx.part_id, AUGUST[0], AUGUST[1],
                                       9000000)
    superseded = get_success_data(
        api.get_value_report(ctx.delinquent_id, UNDERWRITER))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_report_id"] == filed["id"]
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["status"] == "IN_FORCE"

    adjudicated = validate_success(
        api.adjudicate_value_report(filed["id"], UNDERWRITER))
    assert adjudicated["status"] == "PENALIZED"
    assert adjudicated["period_earned_premium_cents"] == 19110
    assert adjudicated["late_penalty_cents"] == 1911

    paid = validate_success(api.settle_claim(ctx.claim["id"], MANAGER))

    assert paid["adjustment_status"] == "CLOSED"
    assert paid["settlement_paid_cents"] == 2900000
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 2900000
    assert part["aggregate_available_cents"] == 197100000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 2900000
    _, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
