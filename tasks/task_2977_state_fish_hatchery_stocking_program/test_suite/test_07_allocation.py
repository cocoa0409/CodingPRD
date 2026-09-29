"""
The distribution pool, the queue that feeds it and the selector that empties it.

Covers the plan's one optional input, the link endpoint that queues a request and
bumps the plan, the exactness of the candidate set, the all-or-nothing refusal of
an empty run, the two shape gates on a link, and then the selector itself in both
of its modes — the waterfall that rounds before it decrements and the
proportional share that leaves its remainder on the table — followed by the
backward edge a late attach drives.
"""

from test_helpers import (
    ADMIN_HEADERS,
    BIO_CARLA_HEADERS,
    BIO_FRANK_HEADERS,
    assert_common_fields,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# A syntactically valid UUID that no allocation plan ever holds.
UNKNOWN_PLAN_ID = "44444444-4444-4444-8444-444444444444"


def test_allocation_plan_mode_defaults_to_priority_waterfall(api):
    """
    The selector mode is the plan's only optional input, and omitting it persists
    the declared default rather than a null.

    PRD 3.7: "`allocation_mode` is either `PRIORITY_WATERFALL` or `PROPORTIONAL`,
    and it defaults to `PRIORITY_WATERFALL` when omitted."

    Design: Corner/entities/allocation_plan_mode_defaults_to_priority_waterfall
    """
    ctx = fx.station_at_rest(api)
    payload = f.allocation_plan_payload(ctx["hatchery"]["id"], allocation_mode=f.OMIT)
    assert "allocation_mode" not in payload

    plan = validate_success(api.create_allocation_plan(payload, ADMIN_HEADERS), 201)

    assert plan["allocation_mode"] == k.MODE_PRIORITY_WATERFALL
    assert plan["status"] == k.PLAN_DRAFT
    assert_common_fields(plan, expected_version=1)
    assert_integer_equals(plan["allocated_total_count"], 0, "allocated_total_count")
    assert_integer_equals(plan["unmet_demand_count"], 0, "unmet_demand_count")
    assert_integer_equals(plan["public_allocated_count"], 0, "public_allocated_count")
    assert_integer_equals(plan["run_count"], 0, "run_count")


def test_attach_to_plan_links_the_request_and_bumps_the_plan_version(api):
    """
    The link touches both sides: the request is queued onto the plan and the
    plan's own revision advances, while the request's frozen score is left alone.

    PRD 3.7: "On success the request moves to `QUEUED`, its `allocation_plan_id` is
    set to the target plan, its `deferral_reason` is cleared to null, its `version`
    advances, and the plan's `version` advances too."

    Design: Corner/endpoints/attach_to_plan_links_the_request_and_bumps_the_plan_version
    """
    ctx = fx.station_at_rest(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert_number_equals(request["priority_score"], 97.50, 2, "priority_score")
    assert_integer_equals(plan["version"], 1, "version")

    queued = validate_success(
        api.attach_to_plan(
            request["id"], f.attach_to_plan_payload(plan["id"], 1), BIO_CARLA_HEADERS
        ),
        200,
    )

    assert queued["status"] == k.REQUEST_QUEUED
    assert queued["allocation_plan_id"] == plan["id"]
    assert_is_none(queued["deferral_reason"], "deferral_reason")
    assert_number_equals(queued["priority_score"], 97.50, 2, "priority_score")
    assert_integer_equals(queued["version"], 2, "version")

    plan_after = fx.read_plan(api, plan["id"])
    assert plan_after["status"] == k.PLAN_DRAFT
    assert_integer_equals(plan_after["version"], 2, "version")
    assert_integer_equals(
        plan_after["allocated_total_count"], 0, "allocated_total_count"
    )
    assert_integer_equals(plan_after["run_count"], 0, "run_count")

    on_the_plan, meta = validate_paginated(
        api.list_stocking_requests(ADMIN_HEADERS, {"allocation_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert ids_of(on_the_plan) == [request["id"]]


def test_allocation_run_ignores_requests_that_were_never_attached(api):
    """
    The candidate set is exactly what was attached. A compatible request that
    never entered the queue is left entirely alone and consumes none of the pool.

    PRD 3.7: "The run considers exactly the requests attached to this plan that are
    currently in `QUEUED` status."

    Design: Corner/calculations/allocation_run_ignores_requests_that_were_never_attached
    """
    ctx = fx.station_at_rest(api)
    blue_mesa = fx.create_water(api)
    taylor_park = fx.create_water(
        api,
        name="Taylor Park Reservoir",
        habitat_suitability_score=70,
        angler_demand_index=60,
        plan_target_count=4000,
        access_type=k.ACCESS_SHORE_ONLY,
    )
    attached = fx.create_stocking_request(api, blue_mesa)
    bystander = fx.create_stocking_request(
        api,
        taylor_park,
        requested_count=1000,
        justification="Taylor Park yearling supplement",
    )
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    fx.attach_request(api, attached, plan, ADMIN_HEADERS)

    ran = fx.run_plan(api, plan)

    assert ran["status"] == k.PLAN_ALLOCATED
    assert_integer_equals(ran["allocated_total_count"], 2400, "allocated_total_count")
    assert_integer_equals(ran["unmet_demand_count"], 0, "unmet_demand_count")
    assert_integer_equals(ran["public_allocated_count"], 0, "public_allocated_count")
    assert_integer_equals(ran["run_count"], 1, "run_count")

    served = fx.read_request(api, attached["id"])
    assert served["status"] == k.REQUEST_ALLOCATED
    assert_integer_equals(served["allocated_count"], 2400, "allocated_count")

    untouched = fx.read_request(api, bystander["id"])
    assert untouched["status"] == k.REQUEST_SUBMITTED
    assert_is_none(untouched["allocation_plan_id"], "allocation_plan_id")
    assert_integer_equals(untouched["allocated_count"], 0, "allocated_count")
    assert_is_none(untouched["allocated_at"], "allocated_at")

    quiet_water = fx.read_water(api, taylor_park["id"])
    assert_integer_equals(quiet_water["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_integer_equals(
        quiet_water["plan_shortfall_count"], 4000, "plan_shortfall_count"
    )


def test_run_with_nothing_queued_returns_no_eligible_requests_and_mutates_nothing(api):
    """
    An empty run is refused outright and writes nothing at all, so the version the
    caller quoted is still good for the retry.

    PRD 3.7: "If no queued request survives eligibility at all — whether because
    none is queued, or because every queued one is ineligible on species or on a
    closed water — the whole run is refused with `ERR_NO_ELIGIBLE_REQUESTS` (HTTP
    422), and nothing at all is written: the plan stays `DRAFT`, its `version` does
    not advance, and no request changes status."

    Design: Corner/endpoints/run_with_nothing_queued_returns_no_eligible_requests_and_mutates_nothing
    """
    ctx = fx.station_at_rest(api)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert_integer_equals(plan["version"], 1, "version")

    response = api.run_allocation_plan(
        plan["id"], f.run_plan_payload(1), ADMIN_HEADERS
    )

    validate_error(response, err.ERR_NO_ELIGIBLE_REQUESTS, 422)

    after = fx.read_plan(api, plan["id"])
    assert after["status"] == k.PLAN_DRAFT
    assert_integer_equals(after["version"], 1, "version")
    assert_integer_equals(after["run_count"], 0, "run_count")
    assert_integer_equals(after["allocated_total_count"], 0, "allocated_total_count")
    assert_integer_equals(after["unmet_demand_count"], 0, "unmet_demand_count")


def test_attaching_a_fry_request_to_a_yearling_plan_reports_size_class_mismatch(api):
    """
    Size class is enforced at the link rather than at the run, and a refused link
    leaves both the request and the plan exactly as they were.

    PRD 3.7: "in both cases the request's `size_class` must equal the plan's
    `size_class` or the attach is refused with `ERR_SIZE_CLASS_MISMATCH` (HTTP 422)"

    Design: Corner/errors/attaching_a_fry_request_to_a_yearling_plan_reports_size_class_mismatch
    """
    ctx = fx.station_at_rest(api)
    water = fx.create_water(api)
    fry_request = fx.create_stocking_request(
        api,
        water,
        requested_count=1000,
        size_class=k.SIZE_CLASS_FRY,
        justification="Fry plant in the upper arm",
    )
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert plan["size_class"] == k.SIZE_CLASS_YEARLING

    response = api.attach_to_plan(
        fry_request["id"], f.attach_to_plan_payload(plan["id"], 1), BIO_CARLA_HEADERS
    )

    validate_error(response, err.ERR_SIZE_CLASS_MISMATCH, 422)

    after = fx.read_request(api, fry_request["id"])
    assert after["status"] == k.REQUEST_SUBMITTED
    assert_is_none(after["allocation_plan_id"], "allocation_plan_id")

    plan_after = fx.read_plan(api, plan["id"])
    assert_integer_equals(plan_after["version"], 1, "version")


def test_unknown_plan_id_in_the_body_returns_plan_not_found(api):
    """
    The plan named in the body is resolved before the revision it quotes is
    compared, so a body pointing at no plan at all is a 404 rather than a 412.

    PRD 2.11: "Identifiers carried in a request body are resolved the same way,
    against the collection each one names, and they too report the referenced
    collection's own 404."

    Design: Corner/errors/unknown_plan_id_in_the_body_returns_plan_not_found
    """
    ctx = fx.station_at_rest(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water)
    real_plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert_integer_equals(real_plan["version"], 1, "version")

    # The quoted version belongs to the real plan, so only the missing plan can
    # explain the refusal.
    response = api.attach_to_plan(
        request["id"], f.attach_to_plan_payload(UNKNOWN_PLAN_ID, 1), BIO_CARLA_HEADERS
    )

    validate_error(response, err.ERR_PLAN_NOT_FOUND, 404)

    after = fx.read_request(api, request["id"])
    assert after["status"] == k.REQUEST_SUBMITTED
    assert_is_none(after["allocation_plan_id"], "allocation_plan_id")
    assert_integer_equals(fx.plan_version(api, real_plan["id"]), 1, "version")


def test_the_waterfall_rounds_each_grant_to_a_whole_unit_before_it_decrements(api):
    """
    Three grants are resolved against one shrinking pool. The whole-unit floor is
    applied before the decrement, so the fifteen fish rounded away from the first
    request stay in the pool and the last request can still be granted 175.

    PRD 3.7: "The order of the third and fourth steps matters and is the single
    most consequential detail of this algorithm: the unit rounding happens
    **before** the remainder is decremented, so the fish rounded away stay
    available to the next request in line. A request asking for 640 fish against a
    1000-fish pool is granted 625 and leaves 375 behind, not 360."

    Design: Difficulty/combinatorial_formula/allocation_waterfall_rounds_to_unit_before_decrementing_pool
    """
    ctx = fx.three_request_pool(api)

    fx.run_plan(api, ctx["plan"])

    first = fx.read_request(api, ctx["request_a"]["id"])
    assert_number_equals(first["priority_score"], 97.50, 2, "priority_score")
    assert first["status"] == k.REQUEST_ALLOCATED
    # min(640, 1000) floored to a whole 25-fish unit.
    assert_integer_equals(first["allocated_count"], 625, "allocated_count")

    second = fx.read_request(api, ctx["request_b"]["id"])
    assert_number_equals(second["priority_score"], 70.60, 2, "priority_score")
    assert second["status"] == k.REQUEST_ALLOCATED
    # min(300, 375) capped at the 200-fish public sub-pool.
    assert_integer_equals(second["allocated_count"], 200, "allocated_count")

    third = fx.read_request(api, ctx["request_c"]["id"])
    assert_number_equals(third["priority_score"], 68.75, 2, "priority_score")
    assert third["status"] == k.REQUEST_ALLOCATED
    # 175 of the 210 asked for: the remainder is 175, not the 160 an unrounded
    # decrement of 640 would have left.
    assert_integer_equals(third["allocated_count"], 175, "allocated_count")


def test_the_waterfall_totals_count_the_shortfall_of_every_served_request(api):
    """
    The plan's three totals settle from the same walk: the pool is exhausted, the
    unmet demand counts the shortfall of granted requests as well, and only the
    public grant lands in the public total.

    PRD 3.7: "Its `allocated_total_count` is the `available_count` less whatever
    remains of the running remainder. Its `unmet_demand_count` is the total, across
    the whole eligible set, of each request's `requested_count` less its
    `allocated_count` — so it counts the shortfall of granted requests as well as
    the whole ask of deferred ones. Its `public_allocated_count` is the total
    `allocated_count` across the eligible requests whose `requester_kind` is
    `PUBLIC`."

    Design: Difficulty/combinatorial_formula/allocation_waterfall_rounds_to_unit_before_decrementing_pool
    """
    ctx = fx.three_request_pool(api)
    assert_integer_equals(ctx["plan"]["version"], 4, "version")

    ran = fx.run_plan(api, ctx["plan"])

    assert ran["status"] == k.PLAN_ALLOCATED
    assert_integer_equals(ran["allocated_total_count"], 1000, "allocated_total_count")
    # (640 - 625) + (300 - 200) + (210 - 175)
    assert_integer_equals(ran["unmet_demand_count"], 150, "unmet_demand_count")
    assert_integer_equals(ran["public_allocated_count"], 200, "public_allocated_count")
    assert_integer_equals(ran["run_count"], 1, "run_count")
    assert_integer_equals(ran["version"], 5, "version")

    antero = fx.read_water(api, ctx["water_p1"]["id"])
    assert_integer_equals(antero["allocated_count_ytd"], 625, "allocated_count_ytd")
    assert_integer_equals(antero["released_count_ytd"], 0, "released_count_ytd")
    assert_integer_equals(antero["plan_shortfall_count"], 1375, "plan_shortfall_count")
    assert_number_equals(antero["plan_fill_pct"], 31.25, 2, "plan_fill_pct")


def test_proportional_mode_caps_each_grant_at_its_share_of_the_original_pool(api):
    """
    The same three requests against the same pool are served differently once the
    selector is proportional: each grant is capped at its pro-rata share of the
    original pool rather than taking what the shrinking remainder allows.

    PRD 3.7: "Under `PROPORTIONAL` the raw entitlement is the smallest of three
    quantities: the request's `requested_count`; the plan's `available_count`
    multiplied by this request's `requested_count` and divided by the total
    `requested_count` across the whole eligible set, rounded down to a whole fish;
    and the running remainder."

    Design: Difficulty/combinatorial_formula/proportional_mode_leaves_rounding_remainder_unallocated
    """
    ctx = fx.three_request_pool(api, allocation_mode=k.MODE_PROPORTIONAL)
    assert ctx["plan"]["allocation_mode"] == k.MODE_PROPORTIONAL

    fx.run_plan(api, ctx["plan"])

    # floor(1000 * 640 / 1150) = 556, floored to a whole unit.
    assert_integer_equals(
        fx.read_request(api, ctx["request_a"]["id"])["allocated_count"],
        550,
        "allocated_count",
    )
    # floor(1000 * 300 / 1150) = 260, then capped at the 200-fish public sub-pool.
    assert_integer_equals(
        fx.read_request(api, ctx["request_b"]["id"])["allocated_count"],
        200,
        "allocated_count",
    )
    # floor(1000 * 210 / 1150) = 182, floored to a whole unit.
    assert_integer_equals(
        fx.read_request(api, ctx["request_c"]["id"])["allocated_count"],
        175,
        "allocated_count",
    )


def test_proportional_mode_leaves_its_rounding_remainder_on_the_table(api):
    """
    Because no second pass redistributes what the pro-rata shares did not reach,
    the plan's allocated total falls 75 fish short of its own pool.

    PRD 3.7: "`PROPORTIONAL` mode deliberately leaves its rounding remainder
    unallocated — it is a fair-share mode rather than a fill mode, and no second
    pass redistributes what the pro-rata shares did not reach."

    Design: Difficulty/combinatorial_formula/proportional_mode_leaves_rounding_remainder_unallocated
    """
    ctx = fx.three_request_pool(api, allocation_mode=k.MODE_PROPORTIONAL)

    ran = fx.run_plan(api, ctx["plan"])

    assert ran["status"] == k.PLAN_ALLOCATED
    # 550 + 200 + 175, so 75 of the 1000 fish are never handed out.
    assert_integer_equals(ran["allocated_total_count"], 925, "allocated_total_count")
    # (640 - 550) + (300 - 200) + (210 - 175)
    assert_integer_equals(ran["unmet_demand_count"], 225, "unmet_demand_count")
    assert_integer_equals(ran["public_allocated_count"], 200, "public_allocated_count")

    assert_integer_equals(
        fx.read_water(api, ctx["water_p1"]["id"])["allocated_count_ytd"],
        550,
        "allocated_count_ytd",
    )
    assert_integer_equals(
        fx.read_water(api, ctx["water_p3"]["id"])["allocated_count_ytd"],
        175,
        "allocated_count_ytd",
    )


def test_a_late_attach_rewinds_the_plan_to_draft_but_keeps_its_run_history(api):
    """
    Attaching a late request to a plan that has already resolved is a backward
    edge: the plan returns to `DRAFT` with its three totals zeroed, while the
    number of runs it has performed is kept as history.

    PRD 3.7: "Such an attach sends the plan from `ALLOCATED` back to `DRAFT`,
    resets `allocated_total_count`, `unmet_demand_count` and `public_allocated_count`
    to zero while `run_count` keeps its historical value, advances the plan's
    `version`, and returns every request the plan had previously resolved to
    `ALLOCATED` or `DEFERRED` back to `QUEUED` with `allocated_count` reset to zero
    — releasing the corresponding `allocated_count_ytd` on each of those requests'
    waters."

    Design: Difficulty/non_linear_state_machine/allocation_plan_reverts_to_draft_on_late_attach
    """
    ctx = fx.three_request_pool(api)
    plan_id = ctx["plan"]["id"]
    resolved = fx.run_plan(api, ctx["plan"])
    assert resolved["status"] == k.PLAN_ALLOCATED
    assert_integer_equals(
        resolved["allocated_total_count"], 1000, "allocated_total_count"
    )
    assert_integer_equals(resolved["run_count"], 1, "run_count")
    assert_integer_equals(resolved["version"], 5, "version")

    late = fx.create_stocking_request(
        api,
        ctx["water_p3"],
        BIO_FRANK_HEADERS,
        requested_count=100,
        justification="Late request from the district biologist",
    )

    rewound_request = validate_success(
        api.attach_to_plan(
            late["id"], f.attach_to_plan_payload(plan_id, 5), ADMIN_HEADERS
        ),
        200,
    )
    assert rewound_request["status"] == k.REQUEST_QUEUED

    plan = fx.read_plan(api, plan_id)
    assert plan["status"] == k.PLAN_DRAFT
    assert_integer_equals(plan["allocated_total_count"], 0, "allocated_total_count")
    assert_integer_equals(plan["unmet_demand_count"], 0, "unmet_demand_count")
    assert_integer_equals(plan["public_allocated_count"], 0, "public_allocated_count")
    assert_integer_equals(plan["run_count"], 1, "run_count")
    assert_integer_equals(plan["version"], 6, "version")


def test_a_late_attach_returns_every_resolved_request_and_releases_the_waters(api):
    """
    The far end of the rewind: all three previously granted requests are back in
    the queue with nothing allocated, and every destination water has given its
    grant back.

    PRD 3.7: "returns every request the plan had previously resolved to `ALLOCATED`
    or `DEFERRED` back to `QUEUED` with `allocated_count` reset to zero — releasing
    the corresponding `allocated_count_ytd` on each of those requests' waters."

    Design: Difficulty/non_linear_state_machine/allocation_plan_reverts_to_draft_on_late_attach
    """
    ctx = fx.three_request_pool(api)
    plan_id = ctx["plan"]["id"]
    fx.run_plan(api, ctx["plan"])
    assert_integer_equals(
        fx.read_water(api, ctx["water_p1"]["id"])["allocated_count_ytd"],
        625,
        "allocated_count_ytd",
    )

    late = fx.create_stocking_request(
        api,
        ctx["water_p3"],
        BIO_FRANK_HEADERS,
        requested_count=100,
        justification="Late request from the district biologist",
    )
    fx.attach_request(api, late, ctx["plan"], ADMIN_HEADERS)

    for key in ("request_a", "request_b", "request_c"):
        back_in_line = fx.read_request(api, ctx[key]["id"])
        assert back_in_line["status"] == k.REQUEST_QUEUED, key
        assert_integer_equals(back_in_line["allocated_count"], 0, "allocated_count")
        assert back_in_line["allocation_plan_id"] == plan_id, key

    assert fx.read_request(api, late["id"])["status"] == k.REQUEST_QUEUED

    antero = fx.read_water(api, ctx["water_p1"]["id"])
    assert_integer_equals(antero["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_integer_equals(antero["plan_shortfall_count"], 2000, "plan_shortfall_count")
    assert_number_equals(antero["plan_fill_pct"], 0.0, 2, "plan_fill_pct")

    for water_key in ("water_p2", "water_p3"):
        water = fx.read_water(api, ctx[water_key]["id"])
        assert_integer_equals(
            water["allocated_count_ytd"], 0, "allocated_count_ytd"
        )
        assert_integer_equals(
            water["plan_shortfall_count"], 2000, "plan_shortfall_count"
        )
