"""The entitlement's two state dimensions and the conservation of the product's finite pools.

This file covers the suspend / reinstate round trip: that the entitlement dimension moves while
the throttle dimension is left where consumption put it, that a suspension returns both
reservations to the product and a reinstatement re-deducts them exactly once, that a spent pool
refuses further provisioning on whichever dimension ran out first, and that a lifecycle conflict
is reported ahead of any complaint about capacity.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_entitlement_dimensions,
    assert_fields,
    assert_nulls,
    assert_pool_availability,
)
from test_helpers.test_users import DEV_REL_MANAGER, PLATFORM_ADMIN


def _soft_throttled_partner(programme):
    """An activated certified partner entitlement driven to `SOFT_THROTTLED` by one hour of traffic.

    The entitlement holds 3000 sustained rpm, 9000 burst rpm and a 500,000 monthly allowance, and a
    single 400,000-call window puts consumption at exactly 0.80 of that allowance.
    """
    bundle = programme.entitlement_chain(certified=True)
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(bundle["assignment"], "2026-08-02T00:00:00Z", 400000)
    bundle["assignment"] = programme.read_entitlement(bundle["assignment"]["id"])
    return bundle


# ------------------------------------------------- the two dimensions move independently
def test_suspension_moves_the_entitlement_dimension_and_leaves_throttling_where_it_was(
    api, programme
):
    """An administrative suspension is an entitlement-dimension event only: the soft-throttled
    verdict that the hour of traffic wrote survives untouched, and so does the consumption ledger
    that produced it.

    PRD: "`throttle_state` is a second, fully independent dimension of the entitlement: it moves without regard to `entitlement_state`, and vice versa."

    PRD: "Either way `suspended_at` is set, the entitlement's `sustained_rpm` is subtracted from the product's `allocated_sustained_rpm` and its `monthly_call_allowance` from `allocated_monthly_calls`, and every `PENDING` upgrade request on this entitlement becomes `VOIDED`."

    Design: Difficulty/non_linear_state_machine/quota_assignment_parallel_dimensions_independent
    """
    bundle = _soft_throttled_partner(programme)
    assert_entitlement_dimensions(
        bundle["assignment"], entitlement_state="ACTIVE", throttle_state="SOFT_THROTTLED"
    )

    response = api.suspend_quota_assignment(
        bundle["assignment"]["id"], f.suspend_payload(), PLATFORM_ADMIN
    )

    assignment = validate_success(response, expected_status=200)
    assert_entitlement_dimensions(
        assignment, entitlement_state="SUSPENDED", throttle_state="SOFT_THROTTLED"
    )
    assert_fields(assignment, "QuotaAssignment", monthly_calls_consumed=400000)


def test_reinstatement_restores_the_entitlement_dimension_without_rescoring_throttling(
    api, programme
):
    """Coming back from suspension clears the suspension stamps and returns the entitlement to
    `ACTIVE`, but it neither re-reads the throttle dimension nor charges the developer a second
    throttled window: only an ingested window can move those.

    PRD: "On success `suspended_at` and `suspension_reason` are cleared and both reservations are re-deducted from the product's counters."

    PRD: "Finally the developer's traffic-quality counters are updated exactly once per window: when `resulting_throttle_state` is `NORMAL` **and** `rate_limit_breach` is false, `clean_window_count` increments by one; in every other case `throttled_window_count` increments by one and `clean_window_count` is reset to 0."

    Design: Difficulty/non_linear_state_machine/quota_assignment_parallel_dimensions_independent
    """
    bundle = _soft_throttled_partner(programme)
    programme.suspend_entitlement(bundle["assignment"])

    response = api.reinstate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)

    assignment = validate_success(response, expected_status=200)
    assert_entitlement_dimensions(
        assignment, entitlement_state="ACTIVE", throttle_state="SOFT_THROTTLED"
    )
    assert_nulls(assignment, ["suspended_at", "suspension_reason"], "QuotaAssignment")
    assert_fields(
        programme.read_developer(bundle["developer"]["id"]),
        "Developer",
        throttled_window_count=1,
        clean_window_count=0,
    )


# ------------------------------------------------------ conservation of the two pools
def test_suspension_returns_both_reservations_to_the_product_it_drew_them_from(api, programme):
    """Suspending the only entitlement on the product hands both of its reservations back, restoring
    the product's declared pools in full, while the entitlement keeps the quota figures it was
    provisioned with so that a later reinstatement can re-deduct exactly the same amounts.

    PRD: "Suspension returns both of an entitlement's reservations to its product by decrementing the two allocated counters; reinstatement re-deducts them by incrementing the counters again, and is only permitted when the product can still cover them."

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_sustained_rpm_pool
    """
    bundle = programme.entitlement_chain(certified=True)
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        allocated_sustained_rpm=3000,
        available_sustained_rpm=17000,
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )

    response = api.suspend_quota_assignment(
        bundle["assignment"]["id"], f.suspend_payload(), PLATFORM_ADMIN
    )

    assignment = validate_success(response, expected_status=200)
    assert_fields(
        assignment,
        "QuotaAssignment",
        sustained_rpm=3000,
        burst_rpm=9000,
        burst_credit_balance=90000,
        monthly_call_allowance=500000,
    )
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        allocated_sustained_rpm=0,
        available_sustained_rpm=20000,
        allocated_monthly_calls=0,
        available_monthly_calls=50000000,
    )


def test_a_second_suspension_is_refused_and_does_not_release_the_reservations_twice(
    api, programme
):
    """A suspension may only be requested against an entitlement that is still serving, so the
    repeat attempt is refused — which is what keeps the release from being applied a second time and
    inflating the product's availability past its declared pool.

    PRD: "It may be requested administratively with a `suspension_reason`, in which case the entitlement must be `ACTIVE` or the request fails with `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409); or it may arrive as a standing cascade, in which case `suspension_reason` is recorded as `STANDING_RESTRICTION`."

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_sustained_rpm_pool
    """
    bundle = programme.entitlement_chain(certified=True)
    programme.suspend_entitlement(bundle["assignment"])

    response = api.suspend_quota_assignment(
        bundle["assignment"]["id"], f.suspend_payload(), PLATFORM_ADMIN
    )

    validate_error(response, ApiError.ASSIGNMENT_NOT_ACTIVE)
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        allocated_sustained_rpm=0,
        available_sustained_rpm=20000,
        allocated_monthly_calls=0,
        available_monthly_calls=50000000,
    )


def test_the_round_trip_leaves_both_product_ledgers_exactly_where_they_started(api, programme):
    """After suspend, a refused repeat suspend and a reinstatement, both allocated counters read the
    same figures they held before the round trip began: the compensation is exact, not approximate.

    PRD: "Reinstatement moves `SUSPENDED → ACTIVE`."

    PRD: "Getting this wrong inflates a product's availability beyond its declared pool, which is the single most damaging accounting error the service can make."

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_sustained_rpm_pool
    """
    bundle = programme.entitlement_chain(certified=True)
    programme.suspend_entitlement(bundle["assignment"])
    repeat = api.suspend_quota_assignment(
        bundle["assignment"]["id"], f.suspend_payload(), PLATFORM_ADMIN
    )
    validate_error(repeat, ApiError.ASSIGNMENT_NOT_ACTIVE)

    response = api.reinstate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)

    assignment = validate_success(response, expected_status=200)
    assert_fields(assignment, "QuotaAssignment", entitlement_state="ACTIVE")
    assert_nulls(assignment, ["suspended_at", "suspension_reason"], "QuotaAssignment")
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        allocated_sustained_rpm=3000,
        available_sustained_rpm=17000,
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )


# ------------------------------------- a lifecycle conflict outranks a capacity complaint
def _fully_committed_partner(programme):
    """A certified partner entitlement whose 3000 rpm and 500,000 calls exhaust both pools."""
    return programme.entitlement_chain(
        certified=True,
        product_kwargs={"sustained_rpm_pool": 3000, "monthly_call_pool": 500000},
    )


def test_reinstating_a_serving_entitlement_reports_the_lifecycle_conflict_not_the_spent_pool(
    api, programme
):
    """Reinstatement of an entitlement that never left service is answered with the lifecycle
    conflict, even though the product it draws on has nothing left to cover a re-deduction: the
    lifecycle check is reached first and no capacity complaint is ever formed.

    PRD: "The server evaluates checks in the fixed order below, from the top, and returns the first failure it finds."

    PRD: "(13) The target entitlement is in the state its lifecycle action requires, namely `PROVISIONED` for activation, `SUSPENDED` for reinstatement, and not `RETIRED` for any write — `ERR_ASSIGNMENT_STATE_INVALID`, 409, on activation and reinstatement."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reinstate_with_exhausted_pool
    """
    bundle = _fully_committed_partner(programme)
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        available_sustained_rpm=0,
        available_monthly_calls=0,
    )

    response = api.reinstate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)

    validate_error(response, ApiError.ASSIGNMENT_STATE_INVALID)


def test_the_refused_reinstatement_leaves_the_entitlement_and_both_ledgers_untouched(
    api, programme
):
    """The refused reinstatement is not a mutation: the entitlement is still serving with no
    suspension stamps, the product's two reservation counters still reflect exactly the one live
    entitlement, and the product's revision counter has not moved.

    PRD: "Reinstatement moves `SUSPENDED → ACTIVE`. It requires `entitlement_state` `SUSPENDED` (otherwise `ERR_ASSIGNMENT_STATE_INVALID`), the developer at `GOOD_STANDING`, the pinned version not `SUNSET`, and enough room in both pools — the product's `available_sustained_rpm` must be at least this entitlement's `sustained_rpm` and its `available_monthly_calls` at least this entitlement's `monthly_call_allowance`, failing with `ERR_SUSTAINED_POOL_EXHAUSTED` or `ERR_MONTHLY_POOL_EXHAUSTED` respectively."

    PRD: "Against these the product maintains two reservation counters, `allocated_sustained_rpm` and `allocated_monthly_calls`, each defined as the sum over the product's entitlements in `entitlement_state` `PROVISIONED` or `ACTIVE` of that entitlement's `sustained_rpm` and `monthly_call_allowance` respectively; both counters start at 0."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reinstate_with_exhausted_pool
    """
    bundle = _fully_committed_partner(programme)
    version_before = programme.read_product(bundle["product"]["id"])["version"]

    response = api.reinstate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)

    validate_error(response, ApiError.ASSIGNMENT_STATE_INVALID)
    assignment = programme.read_entitlement(bundle["assignment"]["id"])
    assert_fields(assignment, "QuotaAssignment", entitlement_state="ACTIVE", sustained_rpm=3000)
    assert_nulls(assignment, ["suspended_at", "suspension_reason"], "QuotaAssignment")
    product = programme.read_product(bundle["product"]["id"])
    assert_fields(product, "ApiProduct", version=version_before)
    assert_pool_availability(
        product,
        allocated_sustained_rpm=3000,
        available_sustained_rpm=0,
        allocated_monthly_calls=500000,
        available_monthly_calls=0,
    )


# ------------------------------------------- the two pools run out independently of each other
def _tight_product(programme):
    """A product whose pools cover exactly one uncertified partner grant on the rate dimension."""
    product = programme.create_product(sustained_rpm_pool=3000, monthly_call_pool=500000)
    return product, programme.grantable_version(product["id"])


def _approved_partner_application(programme, version):
    """A fresh developer holding an approved partner application against that version."""
    developer = programme.onboarded_developer()
    return programme.approved_application(developer, version)


def _provision(api, programme, application, product_id):
    payload = f.quota_assignment_payload(
        application["id"], programme.product_version_counter(product_id)
    )
    return api.create_quota_assignment(payload, PLATFORM_ADMIN)


def test_a_spent_monthly_pool_refuses_provisioning_while_the_rate_pool_still_has_room(
    api, programme
):
    """The first grant takes the whole monthly pool but only three quarters of the rate pool, so the
    second applicant is refused on the monthly dimension alone — and because no entitlement is
    created, the product's rate reservation still counts only the one grant that succeeded.

    PRD: "If that figure is 0 or less, provisioning is refused with `ERR_MONTHLY_POOL_EXHAUSTED` (HTTP 422)."

    PRD: "Against these the product maintains two reservation counters, `allocated_sustained_rpm` and `allocated_monthly_calls`, each defined as the sum over the product's entitlements in `entitlement_state` `PROVISIONED` or `ACTIVE` of that entitlement's `sustained_rpm` and `monthly_call_allowance` respectively; both counters start at 0."

    Design: Corner/errors/both_pool_dimensions_can_exhaust_independently
    """
    product, version = _tight_product(programme)
    first_application = _approved_partner_application(programme, version)
    second_application = _approved_partner_application(programme, version)

    first = validate_success(
        _provision(api, programme, first_application, product["id"]), expected_status=201
    )
    assert_fields(
        first,
        "QuotaAssignment",
        sustained_rpm=2250,
        burst_rpm=6750,
        monthly_call_allowance=500000,
    )
    assert_pool_availability(
        programme.read_product(product["id"]),
        available_sustained_rpm=750,
        available_monthly_calls=0,
    )

    response = _provision(api, programme, second_application, product["id"])

    validate_error(response, ApiError.MONTHLY_POOL_EXHAUSTED)
    assert_pool_availability(
        programme.read_product(product["id"]),
        allocated_sustained_rpm=2250,
        available_sustained_rpm=750,
        allocated_monthly_calls=500000,
        available_monthly_calls=0,
    )


def test_a_spent_rate_pool_refuses_provisioning_before_the_monthly_dimension_is_consulted(
    api, programme
):
    """Once the monthly pool is enlarged, the second applicant provisions at the clamped remainder of
    the rate pool and drains it to nothing; the third applicant is then refused on the rate
    dimension, which is the dimension the pinned order reaches first.

    PRD: "*Step two: clamp against the pool and reserve.* The entitlement's `sustained_rpm` is the smaller of the desired sustained rate and the product's current `available_sustained_rpm`. If that clamped value is 0 or less, provisioning is refused with `ERR_SUSTAINED_POOL_EXHAUSTED` (HTTP 422)."

    PRD: "**The provisioning calculation** runs in a pinned, observable order — sustained rate, then pool deduction, then burst, then monthly allowance — and no later step ever revises an earlier one."

    Design: Corner/errors/both_pool_dimensions_can_exhaust_independently
    """
    product, version = _tight_product(programme)
    first_application = _approved_partner_application(programme, version)
    second_application = _approved_partner_application(programme, version)
    third_application = _approved_partner_application(programme, version)
    validate_success(
        _provision(api, programme, first_application, product["id"]), expected_status=201
    )
    programme.adjust_product(product["id"], monthly_call_pool=1000000)

    second = validate_success(
        _provision(api, programme, second_application, product["id"]), expected_status=201
    )
    assert_fields(
        second,
        "QuotaAssignment",
        sustained_rpm=750,
        burst_rpm=2250,
        monthly_call_allowance=500000,
    )
    assert_pool_availability(
        programme.read_product(product["id"]),
        allocated_sustained_rpm=3000,
        available_sustained_rpm=0,
        allocated_monthly_calls=1000000,
        available_monthly_calls=0,
    )

    response = _provision(api, programme, third_application, product["id"])

    validate_error(response, ApiError.SUSTAINED_POOL_EXHAUSTED)


# --------------------------------------------------- terminal states accept nothing further
def test_a_decided_application_refuses_both_a_second_decision_and_a_change_request(
    api, programme
):
    """An approved application is finished: neither a rejection nor a request for changes can move it
    again, and the refusals leave the recorded decision and the revision count exactly as the
    approval left them.

    PRD: "An approval requires the application to be in `UNDER_REVIEW`."

    PRD: "Both `APPROVED` and `REJECTED` are terminal."

    Design: Corner/state_machines/terminal_states_reject_every_further_action
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)

    second_decision = api.decide_access_application(
        application["id"],
        f.decide_application_payload(
            decision="REJECT", decision_reason="Commercial terms were not agreed."
        ),
        PLATFORM_ADMIN,
    )
    change_request = api.request_application_changes(
        application["id"], f.request_changes_payload(), DEV_REL_MANAGER
    )

    validate_error(second_decision, ApiError.APPLICATION_STATE_INVALID)
    validate_error(change_request, ApiError.APPLICATION_STATE_INVALID)
    assert_fields(
        programme.read_application(application["id"]),
        "AccessApplication",
        state="APPROVED",
        approved_tier="PARTNER",
        revision_round=1,
    )


def test_a_dismissed_violation_case_refuses_an_appeal_and_records_none(api, programme):
    """A dismissal ends the case, so the developer cannot appeal what was already decided in its
    favour: the attempt is refused as a case-state conflict, the case still shows no appeal on
    record, and the developer keeps the clean standing the dismissal restored.

    PRD: "Dismissing a case from `INVESTIGATING` moves it `INVESTIGATING → DISMISSED`, a terminal state, and applies no points."

    PRD: "The case must be in `UPHELD`, otherwise `ERR_CASE_STATE_INVALID`; the logical clock must be at or before the case's `appeal_deadline`, otherwise `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422); and `appeal_count` must still be 0, otherwise `ERR_APPEAL_ALREADY_FILED` (HTTP 409)."

    Design: Corner/state_machines/terminal_states_reject_every_further_action
    """
    programme.create_product()
    developer = programme.onboarded_developer()
    case = programme.open_case(developer, category="RATE_ABUSE", severity="LOW")
    programme.investigate_case(case)
    programme.adjudicate_case(case, outcome="DISMISSED")

    response = api.appeal_violation_case(
        case["id"], f.appeal_payload(), programme.headers_for(developer)
    )

    validate_error(response, ApiError.CASE_STATE_INVALID)
    settled = programme.read_case(case["id"])
    assert_fields(settled, "ViolationCase", state="DISMISSED", appeal_count=0)
    assert_nulls(settled, ["appeal_reason"], "ViolationCase")
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        standing="GOOD_STANDING",
        violation_points=0,
    )
