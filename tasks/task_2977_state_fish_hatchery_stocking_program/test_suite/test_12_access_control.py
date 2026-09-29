"""
Who may do what, and in which order the refusals arrive.

The five roles are exclusive in both directions: the administrator who owns the
reference data may not schedule production, and the manager who runs the station may
not run the allocation selector. Above every role check sits the authentication
header, and immediately below it sit the two scope rules — station scope for the
manager, request ownership for a requester — each of which must answer before the
server admits whether the addressed row even exists or parses.
"""

from test_helpers import (
    ADMIN_HEADERS,
    BIO_CARLA_HEADERS,
    NON_EXISTENT_UUID,
    PUB_DANA_HEADERS,
    PUB_EVE_HEADERS,
    VET_ANNA_HEADERS,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    headers_blank_user_id,
    make_hatchery_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# A public request for a modest number of fish, authored by pub-dana.
PUBLIC_REQUEST = {
    "requested_count": 500,
    "justification": "Family fishing access at the marina",
}


def test_a_program_admin_may_not_schedule_a_stocking_trip(api):
    """
    Production belongs to the station manager even for the administrator who registered
    the water, the plan and the truck. The role gate sits at level 2, so the refusal
    arrives even though the request is only `SUBMITTED` and would fail on state and on the
    allocation ceiling much further down the ladder.

    PRD 2.1: "Production writes — opening a spawning window, planning and recording an
    egg take, recording a feeding, advancing a rearing stage, scheduling a trip, loading
    it and releasing it — belong to `HatcheryManager` alone, and a `ProgramAdmin`
    attempting one is refused."

    Design: Corner/rbac/program_admin_cannot_schedule_a_stocking_event
    """
    ctx = fx.yearling_lot(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water)
    unit = fx.create_transport_unit(api, ctx["hatchery"])
    assert request["status"] == k.REQUEST_SUBMITTED, request["status"]

    response = api.create_stocking_event(
        f.stocking_event_payload(
            request["id"],
            ctx["lot"]["id"],
            unit["id"],
            fx.lot_version(api, ctx["hatchery"], ctx["lot"]["id"]),
            fish_count=100,
        ),
        ADMIN_HEADERS,
    )

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)

    _, meta = validate_paginated(
        api.list_stocking_events(ADMIN_HEADERS, {"lot_id": ctx["lot"]["id"]})
    )
    assert meta["total_count"] == 0, meta


def test_a_hatchery_manager_may_not_run_an_allocation_plan(api):
    """
    The allocation selector is the administrator's alone, and the manager here holds both
    the station the plan belongs to and the exact plan version an OCC check would want —
    so nothing but the role gate can be producing the refusal.

    PRD 2.1: "Registering a station, registering or retiring a water, creating an
    allocation plan, running one, and advancing the logical clock belong to `ProgramAdmin`
    alone."

    Design: Corner/rbac/hatchery_manager_cannot_run_an_allocation_plan
    """
    ctx = fx.station_at_rest(api)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert plan["status"] == k.PLAN_DRAFT, plan["status"]
    assert_integer_equals(plan["version"], 1, "version")

    response = api.run_allocation_plan(
        plan["id"], f.run_plan_payload(plan["version"]), ctx["manager"]
    )

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)

    after = fx.read_plan(api, plan["id"])
    assert after["status"] == k.PLAN_DRAFT, after["status"]
    assert_integer_equals(after["run_count"], 0, "run_count")
    assert_integer_equals(after["version"], 1, "version")


def test_a_veterinarian_may_not_record_a_feeding(api):
    """
    The veterinarian's authority stops at the inspection: husbandry is a production write,
    so the health role can never move biomass, density or the feed conversion ratio.

    PRD 2.1: "The role boundaries are strict in both directions."

    PRD 2.1: "Production writes — opening a spawning window, planning and recording an
    egg take, recording a feeding, advancing a rearing stage, scheduling a trip, loading
    it and releasing it — belong to `HatcheryManager` alone, and a `ProgramAdmin`
    attempting one is refused."

    Design: Corner/rbac/veterinarian_cannot_record_a_feeding
    """
    ctx = fx.lot_at_egg(api)
    before = ctx["lot"]
    assert_integer_equals(before["count_on_hand"], 20000, "count_on_hand")

    response = api.record_feeding(
        before["id"],
        f.feeding_payload(f.instant(2026, 8, 10, 12), 100.0, 3.99),
        VET_ANNA_HEADERS,
    )

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)

    lot = fx.read_lot(api, ctx["hatchery"], before["id"])
    assert_number_equals(lot["avg_weight_g"], 0.1, 5, "avg_weight_g")
    assert_number_equals(lot["cumulative_feed_lbs"], 0.0, 2, "cumulative_feed_lbs")
    assert_integer_equals(lot["version"], before["version"], "version")


def test_a_regional_biologist_may_not_record_an_egg_take(api):
    """
    The biologist authors demand and evaluates recoveries but touches no production row.
    The refusal must arrive before the water-right ledger is consulted, so the station's
    3.0000 reserved acre-feet are still merely reserved and the group's females are still
    merely committed.

    PRD 2.1: "A `RegionalBiologist` authors stocking requests on behalf of the waters in
    a region and evaluates tag recoveries."

    PRD 2.1: "Production writes — opening a spawning window, planning and recording an
    egg take, recording a feeding, advancing a rearing stage, scheduling a trip, loading
    it and releasing it — belong to `HatcheryManager` alone, and a `ProgramAdmin`
    attempting one is refused."

    Design: Corner/rbac/regional_biologist_cannot_record_an_egg_take
    """
    ctx = fx.spawning_group(api)
    spawn = fx.create_spawn_event(api, ctx["hatchery"], ctx["brood_stock"])
    fx.set_clock(api, f.instant(2026, 8, 10))
    assert spawn["status"] == k.SPAWN_PLANNED, spawn["status"]
    assert_number_equals(spawn["water_reserved_af"], 3.0, 4, "water_reserved_af")

    response = api.record_take(
        spawn["id"],
        f.record_take_payload(taken_at=f.instant(2026, 8, 10)),
        BIO_CARLA_HEADERS,
    )

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)

    after = validate_success(api.get_spawn_event(spawn["id"], ctx["manager"]), 200)
    assert after["status"] == k.SPAWN_PLANNED, after["status"]

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_used_af"], 0.0, 4, "water_used_af")
    assert_number_equals(station["water_reserved_af"], 3.0, 4, "water_reserved_af")

    brood = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood["females_spent"], 0, "females_spent")
    assert_integer_equals(brood["females_reserved"], 20, "females_reserved")


def test_a_public_requester_may_not_attach_her_own_request_to_a_plan(api):
    """
    pub-dana authored this request herself, so the ownership rule at level 3 would let her
    through; queueing demand onto a production pool is nevertheless a program decision, and
    the role gate at level 2 answers first. The refusal must be `ERR_FORBIDDEN_ROLE`, never
    `ERR_NOT_REQUEST_OWNER`.

    PRD 2.1: "A `PublicRequester` also may not attach a request to a plan, because queueing
    demand onto a production pool is a program decision rather than a requester's."

    PRD 2.1: "Ownership of a request is decided against that recorded value: withdrawing a
    request, and attaching a request to an allocation plan, act only on requests whose
    `requested_by_user_id` equals the caller's `X-User-ID`, and otherwise return
    `ERR_NOT_REQUEST_OWNER` (HTTP 403)."

    Design: Corner/rbac/public_requester_cannot_attach_a_request_to_a_plan
    """
    ctx = fx.station_at_rest(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water, PUB_DANA_HEADERS, **PUBLIC_REQUEST)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])

    assert request["requester_kind"] == k.REQUESTER_KIND_PUBLIC, request[
        "requester_kind"
    ]
    # 0.8 * (0.45*80 + 0.35*90 + 0.20*100.00) + 10 = 0.8 * 87.50 + 10.
    assert_number_equals(request["priority_score"], 80.0, 2, "priority_score")

    response = api.attach_to_plan(
        request["id"],
        f.attach_to_plan_payload(plan["id"], plan["version"]),
        PUB_DANA_HEADERS,
    )

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)

    after = fx.read_request(api, request["id"])
    assert after["status"] == k.REQUEST_SUBMITTED, after["status"]
    assert_is_none(after["allocation_plan_id"], "allocation_plan_id")
    assert_number_equals(after["priority_score"], 80.0, 2, "priority_score")


def test_a_public_requester_may_not_read_a_rearing_lot(api):
    """
    Production data is closed to the public entirely — not filtered and not redacted but
    refused — while the same caller's reads of the waters she requests fish for keep
    working.

    PRD 2.1: "A `PublicRequester` may read waters and stocking requests and nothing else —
    reads of stations, brood groups, spawn events, rearing lots, inspections, allocation
    plans, transport units and stocking events all return `ERR_FORBIDDEN_ROLE` for that
    role."

    Design: Corner/rbac/public_requester_cannot_read_a_rearing_lot
    """
    ctx = fx.lot_at_egg(api)
    water = fx.create_water(api)

    validate_error(
        api.get_rearing_lot(ctx["lot"]["id"], PUB_DANA_HEADERS),
        err.ERR_FORBIDDEN_ROLE,
        403,
    )

    readable = validate_success(api.get_water(water["id"], PUB_DANA_HEADERS), 200)
    assert readable["id"] == water["id"], readable["id"]
    assert readable["status"] == k.WATER_ACTIVE, readable["status"]


def test_a_blank_user_id_header_is_refused_before_the_role_is_considered(api):
    """
    The authentication gate sits at level 1, above the role gate, so an empty `X-User-ID`
    is refused with 401 even on an endpoint the named role is perfectly entitled to call —
    and nothing is written.

    PRD 2.1: "A request whose `X-User-ID` header is absent, empty, or consists only of
    whitespace is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.1: "This is the very first thing the server checks — it precedes role
    authorisation, existence lookups, and request-shape validation alike."

    Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
    """
    blank = headers_blank_user_id(k.ROLE_PROGRAM_ADMIN)
    assert blank["X-User-ID"] == "", blank

    response = api.create_water(
        f.water_payload(
            name="Eleven Mile Reservoir",
            county="Park",
            habitat_suitability_score=75,
            angler_demand_index=85,
            plan_target_count=3000,
        ),
        blank,
    )

    validate_error(response, err.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(api.list_waters(ADMIN_HEADERS))
    assert meta["total_count"] == 0, meta


def test_a_manager_reading_another_stations_row_is_refused_on_scope(api):
    """
    The manager's identity *is* his station's id, so the scope rule applies to the station
    read itself. The other station exists, and scope at level 3 precedes existence at level
    4, so the answer is a 403 and never a 404 that would confirm or deny the row.

    PRD 2.1: "A manager who addresses an existing record belonging to another station is
    refused with `ERR_HATCHERY_SCOPE_VIOLATION` (HTTP 403)."

    PRD 2.1: "Scope applies to every `HatcheryManager` write, and additionally to two
    reads: reading a station, and listing a station's discharge samples."

    Design: Corner/rbac/hatchery_manager_cannot_read_another_stations_row
    """
    first = fx.create_hatchery(api)
    second = fx.create_hatchery(api, name="Golden Springs Hatchery")
    assert second["id"] != first["id"]

    response = api.get_hatchery(second["id"], make_hatchery_manager_headers(first["id"]))

    validate_error(response, err.ERR_HATCHERY_SCOPE_VIOLATION, 403)

    own = validate_success(
        api.get_hatchery(first["id"], make_hatchery_manager_headers(first["id"])), 200
    )
    assert own["id"] == first["id"], own["id"]
    assert own["station_code"] == first["station_code"], own["station_code"]


def test_a_requester_may_not_withdraw_another_requesters_request(api):
    """
    Withdrawal is open to the `PublicRequester` role, so the role gate passes and the
    ownership rule is the one that must fire: pub-eve is refused on pub-dana's row, and
    pub-dana withdraws it herself without difficulty.

    PRD 2.1: "Ownership of a request is decided against that recorded value: withdrawing a
    request, and attaching a request to an allocation plan, act only on requests whose
    `requested_by_user_id` equals the caller's `X-User-ID`, and otherwise return
    `ERR_NOT_REQUEST_OWNER` (HTTP 403)."

    Design: Corner/rbac/public_requester_cannot_withdraw_another_requesters_request
    """
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water, PUB_DANA_HEADERS, **PUBLIC_REQUEST)

    validate_error(
        api.withdraw_stocking_request(request["id"], PUB_EVE_HEADERS),
        err.ERR_NOT_REQUEST_OWNER,
        403,
    )

    still_open = fx.read_request(api, request["id"])
    assert still_open["status"] == k.REQUEST_SUBMITTED, still_open["status"]

    withdrawn = validate_success(
        api.withdraw_stocking_request(request["id"], PUB_DANA_HEADERS), 200
    )
    assert withdrawn["status"] == k.REQUEST_WITHDRAWN, withdrawn["status"]


def test_the_role_gate_answers_before_the_path_row_is_looked_up(api):
    """
    A caller the role gate excludes learns nothing about which identifiers exist: reading a
    rearing lot that does not exist answers 403 on the role, not the lot collection's 404.

    PRD 2.10: "**Role authorisation** — the acting role may invoke this operation at all."

    PRD 2.10: "**Path record existence** — the identifier in the URL resolves to a record
    of the addressed collection."

    PRD 2.1: "A `PublicRequester` may read waters and stocking requests and nothing else —
    reads of stations, brood groups, spawn events, rearing lots, inspections, allocation
    plans, transport units and stocking events all return `ERR_FORBIDDEN_ROLE` for that
    role."

    Design: Corner/validations/role_gate_is_checked_before_the_path_row_and_returns_forbidden_not_found_free
    """
    response = api.get_rearing_lot(NON_EXISTENT_UUID, PUB_DANA_HEADERS)

    validate_error(response, err.ERR_FORBIDDEN_ROLE, 403)


FEEDING_AT = f.instant(2026, 8, 20)


def _malformed_feeding():
    """A feeding body with `avg_weight_g_after` missing altogether."""
    payload = f.feeding_payload(FEEDING_AT, -50.0, 45.3592, 0)
    payload.pop("avg_weight_g_after")
    return payload


def _fed_lot_and_a_foreign_manager(api):
    """
    Silver Creek's lot after its first feeding, plus a second station's manager.

    The lot has taken 300.0 lb of feed and stands at 4.53592 g, so any write that
    actually landed would be visible in either figure.
    """
    ctx = fx.lot_at_egg(api)
    lot_id = ctx["lot"]["id"]
    fx.record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10), 300.0, 4.53592, 2000
    )
    fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FRY)
    ctx["lot"] = fx.advance_stage(api, ctx["hatchery"], lot_id, k.STAGE_FINGERLING)
    fx.set_clock(api, FEEDING_AT)
    ctx["other_station"] = fx.create_hatchery(api, name="Pine Creek Hatchery")
    ctx["foreign_manager"] = make_hatchery_manager_headers(ctx["other_station"]["id"])
    return ctx


def test_station_scope_answers_before_the_body_is_parsed_at_all(api):
    """
    Pine Creek's manager posts a structurally invalid feeding — no `avg_weight_g_after` and
    a negative `feed_lbs` — against Silver Creek's lot. Scope sits at level 3 and request
    shape at level 6, so the answer is the 403 and never the 400: a validator that parses
    the body before it resolves the actor leaks the shape of another station's row.

    PRD 2.10: "**Ownership and station scope** — the acting principal may touch this
    particular record. This is where `ERR_HATCHERY_SCOPE_VIOLATION` and
    `ERR_NOT_REQUEST_OWNER` live."

    PRD 2.10: "**Request shape** — required fields present and non-null, types correct,
    enum values recognised, numbers inside their declared ranges, strings matching their
    declared patterns, and interval field pairs not inverted."

    PRD 2.1: "Scope is evaluated only on a record that was actually found, so an identifier
    in the URL that resolves to nothing yields that collection's 404 instead; and a manager
    acting on another station's existing record always sees `ERR_HATCHERY_SCOPE_VIOLATION` —
    never a 404, and never a request-shape complaint."

    Design: Difficulty/priority_pair_validation_conflict/hatchery_scope_beats_request_shape_on_foreign_feeding
    """
    ctx = _fed_lot_and_a_foreign_manager(api)

    response = api.record_feeding(
        ctx["lot"]["id"], _malformed_feeding(), ctx["foreign_manager"]
    )

    validate_error(response, err.ERR_HATCHERY_SCOPE_VIOLATION, 403)


def test_the_same_malformed_feeding_from_the_owning_manager_is_a_shape_failure(api):
    """
    Both rules are live: the identical body from Silver Creek's own manager is refused on
    its shape, which is what makes the ordering in the foreign case falsifiable. Neither
    attempt writes anything — the lot keeps the 300.0 lb it has been fed and the 4.53592 g
    it grew to.

    PRD 3.4: "The station's own manager records a feeding period by supplying the `fed_at`
    instant the period ended, the `feed_lbs` of feed delivered during it, the new mean
    individual weight `avg_weight_g_after`, and optionally the `mortality_count` observed
    since the previous feeding."

    PRD 2.10: "**Request shape** — required fields present and non-null, types correct,
    enum values recognised, numbers inside their declared ranges, strings matching their
    declared patterns, and interval field pairs not inverted."

    Design: Difficulty/priority_pair_validation_conflict/hatchery_scope_beats_request_shape_on_foreign_feeding
    """
    ctx = _fed_lot_and_a_foreign_manager(api)
    lot_id = ctx["lot"]["id"]
    version_before = ctx["lot"]["version"]

    validate_error(
        api.record_feeding(lot_id, _malformed_feeding(), ctx["foreign_manager"]),
        err.ERR_HATCHERY_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.record_feeding(lot_id, _malformed_feeding(), ctx["manager"]),
        err.ERR_INVALID_REQUEST,
        400,
    )

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_number_equals(lot["cumulative_feed_lbs"], 300.0, 2, "cumulative_feed_lbs")
    assert_number_equals(lot["avg_weight_g"], 4.53592, 5, "avg_weight_g")
    assert_integer_equals(lot["version"], version_before, "version")
