"""Asking for more sustained rate, and the waterfall run that settles those asks.

This file covers upgrade requests against a live entitlement — the delta they compute, the
admissibility bounds that decide whether an ask may be made at all, and the staleness guard
that forces a developer to quote the entitlement it is about to supersede — together with
the product-scoped allocation run that fills the product's remaining sustained capacity in
priority order, granting, partially granting and deferring inside a single walk.
"""
from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.constants import JUSTIFICATION_PARTNER
from test_helpers.test_users import DEV_REL_MANAGER, PLATFORM_ADMIN
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success


def _contested_pool(programme):
    """One product whose spare sustained capacity cannot satisfy the asks standing against it.

    The product declares a 7200 rpm sustained pool. A certified PARTNER entitlement reserves
    3000 rpm and two uncertified STANDARD entitlements reserve 450 rpm each, leaving 3300 rpm
    spare against three asks totalling 4400 rpm. The dearer STANDARD ask is created an hour
    before the cheaper one, so creation order and cost order disagree.
    """
    product = programme.create_product(sustained_rpm_pool=7200, monthly_call_pool=50000000)
    partner = programme.entitlement_chain(certified=True, requested_tier="PARTNER", product=product)
    cheaper = programme.entitlement_chain(requested_tier="STANDARD", product=product)
    dearer = programme.entitlement_chain(requested_tier="STANDARD", product=product)

    partner_request = programme.request_upgrade(
        partner["assignment"],
        partner["developer"],
        6500,
        justification_text=JUSTIFICATION_PARTNER,
    )
    dearer_request = programme.request_upgrade(dearer["assignment"], dearer["developer"], 950)
    programme.set_clock("2026-08-01T01:00:00Z")
    cheaper_request = programme.request_upgrade(cheaper["assignment"], cheaper["developer"], 850)

    return {
        "product": programme.read_product(product["id"]),
        "partner": partner,
        "cheaper": cheaper,
        "dearer": dearer,
        "partner_request": partner_request,
        "cheaper_request": cheaper_request,
        "dearer_request": dearer_request,
    }


# ------------------------------------------------------------------ ordering of the waterfall
def test_allocation_queue_serves_the_higher_tier_then_the_cheapest_ask_in_its_tier(
    api, programme
):
    """The run walks the PARTNER ask first, and inside the STANDARD tier it takes the 400 rpm
    ask before the 500 rpm one even though the dearer ask was created an hour earlier.

    PRD: "The queue is ordered deterministically by three keys in sequence: first by the entitlement's tier rank **descending**, so `PRIVILEGED` requests are served before `PARTNER`, `PARTNER` before `STANDARD`, and `STANDARD` before `SANDBOX`; then, within one tier, by `requested_delta_rpm` **ascending**, so the cheapest ask is filled first; and finally by `created_at` ascending as the tie-break."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)
    assert_fields(scenario["partner_request"], "UpgradeRequest", requested_delta_rpm=3500)
    assert_fields(scenario["dearer_request"], "UpgradeRequest", requested_delta_rpm=500)
    assert_fields(scenario["cheaper_request"], "UpgradeRequest", requested_delta_rpm=400)
    assert scenario["dearer_request"]["created_at"] < scenario["cheaper_request"]["created_at"], (
        "the dearer standard ask must have been created first for this ordering to bite"
    )

    validate_success(api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER))

    assert_fields(
        programme.read_upgrade_request(scenario["partner_request"]["id"]),
        "UpgradeRequest",
        run_sequence=1,
    )
    assert_fields(
        programme.read_upgrade_request(scenario["cheaper_request"]["id"]),
        "UpgradeRequest",
        run_sequence=2,
    )
    assert_fields(
        programme.read_upgrade_request(scenario["dearer_request"]["id"]),
        "UpgradeRequest",
        run_sequence=3,
    )


def test_allocation_run_stamps_every_walked_request_including_the_deferred_one(api, programme):
    """Each request the run touches is stamped with a one-based position and the decision
    instant taken from the logical clock, and the request that ends up deferred is stamped
    just like the ones that received capacity.

    PRD: "Each request in the queue is stamped with a 1-based `run_sequence` in that order, including requests that end up deferred, and with `decided_at` from the logical clock."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)

    summary = validate_success(
        api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER)
    )

    assert_fields(summary, "AllocationRun", run_sequence_count=3)
    positions = []
    for key in ("partner_request", "cheaper_request", "dearer_request"):
        settled = programme.read_upgrade_request(scenario[key]["id"])
        positions.append(settled["run_sequence"])
        assert_instant_equals(settled["decided_at"], "2026-08-01T01:00:00Z", f"{key}.decided_at")
    assert sorted(positions) == [1, 2, 3], (
        f"expected the three walked requests to be stamped 1, 2 and 3, got {positions}"
    )
    assert_fields(
        programme.read_upgrade_request(scenario["dearer_request"]["id"]),
        "UpgradeRequest",
        state="DEFERRED",
        run_sequence=3,
    )


# ------------------------------------------------- the three-way minimum inside a single walk
def test_partner_grant_is_cut_by_its_own_tier_headroom_and_lifts_burst_with_it(api, programme):
    """The PARTNER ask of 3500 rpm is cut to the 3000 rpm of headroom left below its tier
    ceiling of 6000, so it is only partially granted, and the entitlement's burst ceiling is
    recomputed from the new sustained rate rather than left where provisioning put it.

    PRD: "Otherwise the granted amount is the smallest of three numbers: the request's `requested_delta_rpm`, the remaining capacity, and the entitlement's current headroom, being its tier ceiling less its current `sustained_rpm`."

    PRD: "The entitlement's `sustained_rpm` increases by the granted amount, its `burst_rpm` is then recomputed from the new `sustained_rpm` using the same tier burst factor and the same round-up rule as at provisioning, the product's `allocated_sustained_rpm` increases by the granted amount, and the remaining capacity falls by it."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)
    assert_fields(
        programme.read_entitlement(scenario["partner"]["assignment"]["id"]),
        "QuotaAssignment",
        tier="PARTNER",
        sustained_rpm=3000,
        burst_rpm=9000,
    )

    validate_success(api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER))

    assert_fields(
        programme.read_upgrade_request(scenario["partner_request"]["id"]),
        "UpgradeRequest",
        state="PARTIALLY_GRANTED",
        requested_delta_rpm=3500,
        granted_delta_rpm=3000,
        denial_reason=None,
    )
    assert_fields(
        programme.read_entitlement(scenario["partner"]["assignment"]["id"]),
        "QuotaAssignment",
        sustained_rpm=6000,
        burst_rpm=18000,
    )


def test_standard_grant_is_cut_by_the_capacity_the_earlier_grant_left_behind(api, programme):
    """The cheaper STANDARD ask of 400 rpm arrives with only 300 rpm of the pool left after
    the PARTNER grant, so the remaining capacity — not its own ask and not its 750 rpm of tier
    headroom — decides what it gets.

    PRD: "The run starts with a working figure of remaining capacity equal to the product's `available_sustained_rpm` at the moment the run begins, and walks the queue in order."

    PRD: "That amount is stored as `granted_delta_rpm`; the request moves `PENDING → GRANTED` when it equals `requested_delta_rpm` exactly and `PENDING → PARTIALLY_GRANTED` when it is smaller."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)
    assert_fields(
        programme.read_entitlement(scenario["cheaper"]["assignment"]["id"]),
        "QuotaAssignment",
        tier="STANDARD",
        sustained_rpm=450,
        burst_rpm=900,
    )

    validate_success(api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER))

    assert_fields(
        programme.read_upgrade_request(scenario["cheaper_request"]["id"]),
        "UpgradeRequest",
        state="PARTIALLY_GRANTED",
        requested_delta_rpm=400,
        granted_delta_rpm=300,
        denial_reason=None,
    )
    assert_fields(
        programme.read_entitlement(scenario["cheaper"]["assignment"]["id"]),
        "QuotaAssignment",
        sustained_rpm=750,
        burst_rpm=1500,
    )


def test_last_ask_meeting_an_empty_pool_is_deferred_rather_than_granted_nothing(api, programme):
    """When the dearer STANDARD ask's turn arrives the pool is exactly empty, so it is
    deferred with the pool as the recorded reason instead of being granted a delta of zero,
    and its entitlement keeps the rate it was provisioned with.

    PRD: "For each request: if the remaining capacity is exactly 0 when this request's turn arrives, the request moves `PENDING → DEFERRED` with `denial_reason` `POOL_EXHAUSTED` and the run continues to the next one — a deferred request may be re-run later once the pool grows."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)

    validate_success(api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER))

    assert_fields(
        programme.read_upgrade_request(scenario["dearer_request"]["id"]),
        "UpgradeRequest",
        state="DEFERRED",
        requested_delta_rpm=500,
        granted_delta_rpm=0,
        denial_reason="POOL_EXHAUSTED",
    )
    assert_fields(
        programme.read_entitlement(scenario["dearer"]["assignment"]["id"]),
        "QuotaAssignment",
        sustained_rpm=450,
        burst_rpm=900,
    )


def test_allocation_run_reports_the_pool_it_drained_and_leaves_the_product_full(api, programme):
    """The run summary accounts for every request it walked and for the whole 3300 rpm it
    handed out, and the product's own reservation counters agree: the sustained pool is fully
    committed and nothing is left available.

    PRD: "The run reports `run_sequence_count`, the number of requests it walked; `granted_count`, `partially_granted_count` and `deferred_count`; `allocated_sustained_rpm_delta`, the total rate granted across the run; and `available_sustained_rpm_after`, the product's remaining availability once the run has finished."

    PRD: "Two derived read-only figures follow: `available_sustained_rpm` is `sustained_rpm_pool` less `allocated_sustained_rpm`, and `available_monthly_calls` is `monthly_call_pool` less `allocated_monthly_calls`."

    Design: Corner/calculations/upgrade_allocation_fills_the_pool_in_priority_order
    """
    scenario = _contested_pool(programme)
    assert_fields(
        programme.read_product(scenario["product"]["id"]),
        "ApiProduct",
        sustained_rpm_pool=7200,
        allocated_sustained_rpm=3900,
        available_sustained_rpm=3300,
    )

    summary = validate_success(
        api.run_upgrade_allocation(scenario["product"]["id"], {}, DEV_REL_MANAGER)
    )

    assert_fields(
        summary,
        "AllocationRunSummary",
        run_sequence_count=3,
        granted_count=0,
        partially_granted_count=2,
        deferred_count=1,
        allocated_sustained_rpm_delta=3300,
        available_sustained_rpm_after=0,
    )
    assert_fields(
        programme.read_product(scenario["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=7200,
        available_sustained_rpm=0,
    )


# ------------------------------------------------------- what a developer is allowed to ask for
def test_asking_for_the_rate_already_held_is_refused_as_no_increase_at_all(
    api, programme, standard_entitlement
):
    """A standard entitlement running at 450 rpm asks for 450 rpm; because that is not strictly
    more than what it already holds the ask is turned away as not an increase, even though the
    entitlement still has room below its ceiling.

    PRD: "`requested_sustained_rpm` must be strictly greater than the entitlement's current `sustained_rpm` — an upgrade that is not an increase is rejected with `ERR_UPGRADE_NOT_AN_INCREASE` (HTTP 422)."

    Design: Corner/errors/upgrade_request_admissibility_bounds
    """
    assignment = programme.read_entitlement(standard_entitlement["assignment"]["id"])
    assert_fields(assignment, "QuotaAssignment", tier="STANDARD", sustained_rpm=450)

    resp = api.create_upgrade_request(
        assignment["id"],
        f.upgrade_request_payload(450, assignment["version"]),
        standard_entitlement["developer_headers"],
    )

    validate_error(resp, ApiError.UPGRADE_NOT_AN_INCREASE)
    listed, meta = validate_paginated(
        api.list_upgrade_requests(assignment["id"], PLATFORM_ADMIN)
    )
    assert meta["total_count"] == 0, f"the refused ask must not have been stored: {listed}"


def test_asking_for_exactly_the_tier_ceiling_is_admissible_and_records_the_delta(
    api, programme, standard_entitlement
):
    """The standard tier ceiling is twice its 600 rpm base, so an ask for exactly 1200 rpm is
    admissible from 450 rpm, and the request is stored pending with the 750 rpm gap it wants and
    with nothing decided about it yet.

    PRD: "The server computes `requested_delta_rpm` as `requested_sustained_rpm` less the entitlement's `sustained_rpm` at creation time, and creates the request in `state` `PENDING` with `granted_delta_rpm` 0 and with `denial_reason`, `run_sequence` and `decided_at` null."

    PRD: "And the entitlement must have room to grow at all: its `sustained_rpm` must be strictly below its **tier ceiling**, which is exactly **twice** the tier's base sustained rate — 120 for `SANDBOX`, 1,200 for `STANDARD`, 6,000 for `PARTNER` and 24,000 for `PRIVILEGED`."

    Design: Corner/errors/upgrade_request_admissibility_bounds
    """
    assignment = programme.read_entitlement(standard_entitlement["assignment"]["id"])

    created = validate_success(
        api.create_upgrade_request(
            assignment["id"],
            f.upgrade_request_payload(1200, assignment["version"]),
            standard_entitlement["developer_headers"],
        ),
        expected_status=201,
    )

    assert_fields(
        created,
        "UpgradeRequest",
        requested_sustained_rpm=1200,
        requested_delta_rpm=750,
        state="PENDING",
        granted_delta_rpm=0,
        denial_reason=None,
        run_sequence=None,
        decided_at=None,
    )


def test_uncontested_ask_is_granted_whole_and_the_next_run_finds_nothing_to_settle(
    api, programme, standard_entitlement
):
    """Against an ample pool the 750 rpm ask is met in full, lifting the entitlement to its
    ceiling with the burst ceiling recomputed alongside it; a second run launched immediately
    afterwards finds no pending ask left and is refused rather than reported as an empty run.

    PRD: "That amount is stored as `granted_delta_rpm`; the request moves `PENDING → GRANTED` when it equals `requested_delta_rpm` exactly and `PENDING → PARTIALLY_GRANTED` when it is smaller."

    PRD: "The run considers every `PENDING` request whose entitlement is pinned to a version of this product; if there is not at least one such request, the run is refused with `ERR_NO_PENDING_UPGRADE_REQUESTS` (HTTP 409)."

    Design: Corner/errors/upgrade_request_admissibility_bounds
    """
    assignment = standard_entitlement["assignment"]
    request = programme.request_upgrade(assignment, standard_entitlement["developer"], 1200)
    product_id = standard_entitlement["product"]["id"]

    summary = validate_success(api.run_upgrade_allocation(product_id, {}, DEV_REL_MANAGER))

    assert_fields(
        summary,
        "AllocationRunSummary",
        run_sequence_count=1,
        granted_count=1,
        partially_granted_count=0,
        deferred_count=0,
        allocated_sustained_rpm_delta=750,
    )
    assert_fields(
        programme.read_upgrade_request(request["id"]),
        "UpgradeRequest",
        state="GRANTED",
        granted_delta_rpm=750,
        run_sequence=1,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        sustained_rpm=1200,
        burst_rpm=2400,
    )

    validate_error(
        api.run_upgrade_allocation(product_id, {}, DEV_REL_MANAGER),
        ApiError.NO_PENDING_UPGRADE_REQUESTS,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        sustained_rpm=1200,
        burst_rpm=2400,
    )


def test_entitlement_sitting_on_its_ceiling_cannot_ask_for_more_room(
    api, programme, standard_entitlement
):
    """Once the grant has taken the entitlement to 1200 rpm it is no longer strictly below the
    standard ceiling, so the next ask — for 1500 rpm, plainly an increase — is turned away by
    the ceiling rule rather than by the not-an-increase rule.

    PRD: "An entitlement already at or above its ceiling is refused with `ERR_TIER_CEILING_REACHED` (HTTP 422)."

    Design: Corner/errors/upgrade_request_admissibility_bounds
    """
    assignment = standard_entitlement["assignment"]
    programme.request_upgrade(assignment, standard_entitlement["developer"], 1200)
    programme.run_allocation(standard_entitlement["product"]["id"])
    at_ceiling = programme.read_entitlement(assignment["id"])
    assert_fields(at_ceiling, "QuotaAssignment", sustained_rpm=1200)

    resp = api.create_upgrade_request(
        assignment["id"],
        f.upgrade_request_payload(1500, at_ceiling["version"]),
        standard_entitlement["developer_headers"],
    )

    validate_error(resp, ApiError.TIER_CEILING_REACHED)
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        sustained_rpm=1200,
        burst_rpm=2400,
    )


# --------------------------------------------- proving you saw the ask you are about to replace
def test_second_ask_quoting_the_pre_request_version_is_refused_as_stale(
    api, programme, standard_entitlement
):
    """Creating an ask moves the entitlement's version on, so replaying the very same body a
    second time no longer quotes the entitlement as it stands and is refused — which is the only
    thing stopping a developer from silently replacing an ask it never saw.

    PRD: "A successful create increments the entitlement's `version` by one."

    PRD: "If `expected_quota_assignment_version` does not equal the entitlement's current `version`, the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/upgrade_requests_must_quote_the_assignment_they_supersede
    """
    assignment_id = standard_entitlement["assignment"]["id"]
    stale_version = programme.read_entitlement(assignment_id)["version"]

    first = validate_success(
        api.create_upgrade_request(
            assignment_id,
            f.upgrade_request_payload(900, stale_version),
            standard_entitlement["developer_headers"],
        ),
        expected_status=201,
    )
    assert_fields(first, "UpgradeRequest", requested_delta_rpm=450, state="PENDING")
    assert_fields(
        programme.read_entitlement(assignment_id), "QuotaAssignment", version=stale_version + 1
    )

    resp = api.create_upgrade_request(
        assignment_id,
        f.upgrade_request_payload(900, stale_version),
        standard_entitlement["developer_headers"],
    )

    validate_error(resp, ApiError.STALE_ASSIGNMENT_VERSION)
    assert_fields(programme.read_upgrade_request(first["id"]), "UpgradeRequest", state="PENDING")
    listed, meta = validate_paginated(
        api.list_upgrade_requests(assignment_id, PLATFORM_ADMIN)
    )
    assert meta["total_count"] == 1, f"the refused ask must not have been stored: {listed}"


def test_retry_with_the_fresh_version_supersedes_the_earlier_ask_without_moving_capacity(
    api, programme, standard_entitlement
):
    """Quoting the version the first ask left behind, the developer may raise its ask to 1100
    rpm; the earlier pending ask is superseded rather than kept alongside it, and the
    entitlement's own sustained rate is untouched because only an allocation run moves capacity.

    PRD: "Creating a new one moves the entitlement's prior `PENDING` request to `SUPERSEDED`, and increments the entitlement's `version` by one."

    PRD: "The server computes `requested_delta_rpm` as `requested_sustained_rpm` less the entitlement's `sustained_rpm` at creation time, and creates the request in `state` `PENDING` with `granted_delta_rpm` 0 and with `denial_reason`, `run_sequence` and `decided_at` null."

    Design: Corner/cross_cutting_complexity_layers/upgrade_requests_must_quote_the_assignment_they_supersede
    """
    assignment_id = standard_entitlement["assignment"]["id"]
    first = programme.request_upgrade(
        standard_entitlement["assignment"], standard_entitlement["developer"], 900
    )
    fresh_version = programme.read_entitlement(assignment_id)["version"]

    second = validate_success(
        api.create_upgrade_request(
            assignment_id,
            f.upgrade_request_payload(1100, fresh_version),
            standard_entitlement["developer_headers"],
        ),
        expected_status=201,
    )

    assert_fields(
        second, "UpgradeRequest", requested_delta_rpm=650, state="PENDING", granted_delta_rpm=0
    )
    assert_fields(programme.read_upgrade_request(first["id"]), "UpgradeRequest", state="SUPERSEDED")
    assert_fields(
        programme.read_entitlement(assignment_id),
        "QuotaAssignment",
        sustained_rpm=450,
        burst_rpm=900,
        version=fresh_version + 1,
    )
