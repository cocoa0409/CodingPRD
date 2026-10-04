"""Pack formats and channel price lists: production gates, initial-status
stamping, half-open window adjacency/clip, MAP floor, retirement and OCC."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, validate_error, validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
SP = TEST_USERS["supply_planner_headers"]
PA = TEST_USERS["pricing_analyst_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]


def test_price_list_initial_status_stamped_against_clock():
    """PRD §3.7: "Creation stamps the initial status from the current logical time: `EFFECTIVE` when the time already lies inside the window, otherwise `SCHEDULED`."
    PRD §3.7: "The window must be well-ordered — `effective_from` strictly before `effective_to` — and not entirely in the past; either fault is `ERR_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/state_machines/price_list_initial_status_stamped_against_clock
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])

    now_covering = fx.create_price_list_record(
        pack["id"], effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-08-01T00:00:00Z")
    assert now_covering["status"] == "EFFECTIVE", \
        "the window covers the 2026-09-01 logical time"

    future = fx.create_price_list_record(
        pack["id"], list_price_cents=520,
        effective_from="2027-08-01T00:00:00Z",
        effective_to="2028-08-01T00:00:00Z")
    assert future["status"] == "SCHEDULED", \
        "entirely future window, touching the first list's end without overlap"

    past = api_client.create_price_list(
        pack["id"],
        {"channel": "HARDWARE", "list_price_cents": 450, "map_price_cents": 300,
         "effective_from": "2026-01-01T00:00:00Z",
         "effective_to": "2026-02-01T00:00:00Z",
         "expected_pack_format_version":
             fx.get_pack_format_version(pack["id"])}, PA)
    validate_error(past, ApiErrorId.ERR_WINDOW_INVALID)

    rows, meta = validate_paginated(
        api_client.list_price_lists(PA, params={"pack_format_id": pack["id"]}))
    assert len(rows) == 2 and meta["total_count"] == 2, "no third list persisted"


def test_effective_price_boundary_and_missing_price():
    """PRD §2.9: "Channel price lists instead run on **datetimes** interpreted as half-open intervals — a list governs from `effective_from` up to but not including `effective_to` — so two lists on the same pack and channel may touch (one's `effective_from` equal to the other's `effective_to`) but may never overlap in the interior."
    PRD §3.7: "Among non-`SUPERSEDED` lists for the pair whose half-open window contains the instant, the one with the greatest `effective_from` wins; a tie on `effective_from` breaks toward the earliest `created_at`. When no candidate covers the instant, the read fails with `ERR_NO_EFFECTIVE_PRICE` (HTTP 404)."

    Design: Corner/calculations/effective_price_boundary_and_missing_price
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])
    fx.create_price_list_record(pack["id"], list_price_cents=499,
                                effective_from="2026-08-01T00:00:00Z",
                                effective_to="2026-12-01T00:00:00Z")
    l2 = fx.create_price_list_record(pack["id"], list_price_cents=520,
                                     effective_from="2026-12-01T00:00:00Z",
                                     effective_to="2027-04-01T00:00:00Z")

    before = validate_success(api_client.get_effective_price(
        pack["id"], "HARDWARE", PA, at="2026-11-30T23:59:59Z"))
    assert before["list_price_cents"] == 499

    at_boundary = validate_success(api_client.get_effective_price(
        pack["id"], "HARDWARE", PA, at="2026-12-01T00:00:00Z"))
    assert at_boundary["list_price_cents"] == 520
    assert at_boundary["price_list_id"] == l2["id"], \
        "L2's effective_from is inclusive and L1's effective_to exclusive"

    missing = api_client.get_effective_price(pack["id"], "AUTOMOTIVE", PA)
    validate_error(missing, ApiErrorId.ERR_NO_EFFECTIVE_PRICE)


def test_price_list_map_above_list_rejected():
    """PRD §3.7: "a `map_price_cents` minimum advertised price that must be positive and no greater than the list price (`ERR_MAP_ABOVE_LIST`, HTTP 422)".
    PRD §2.7: "Both creates themselves mutate the parent's bookkeeping: a successful coverage-assignment creation increments the distributor's `version` by one, and a successful price-list creation increments the pack format's `version` by one." — a rejected create mutates nothing.

    Design: Corner/validations/price_list_map_above_list_rejected
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])
    pack_version = pack["version"]

    bad = api_client.create_price_list(
        pack["id"],
        {"channel": "HARDWARE", "list_price_cents": 499, "map_price_cents": 600,
         "effective_from": "2026-08-01T00:00:00Z",
         "effective_to": "2027-08-01T00:00:00Z",
         "expected_pack_format_version": pack_version}, PA)
    validate_error(bad, ApiErrorId.ERR_MAP_ABOVE_LIST)

    assert fx.get_pack_format_version(pack["id"]) == pack_version, \
        "the rejected create did not bump the pack version"

    equal = api_client.create_price_list(
        pack["id"],
        {"channel": "HARDWARE", "list_price_cents": 499, "map_price_cents": 499,
         "effective_from": "2026-08-01T00:00:00Z",
         "effective_to": "2027-08-01T00:00:00Z",
         "expected_pack_format_version": pack_version}, PA)
    assert validate_success(equal, 201)["map_price_cents"] == 499, \
        "map equal to list is allowed"


def test_enter_production_requires_price_list():
    """PRD §3.7: "Entering production moves `TOOLED` → `IN_PRODUCTION` and requires both a `COMPARTMENTALIZED` formulation on the owning line (`ERR_FORMULATION_NOT_COMPARTMENTALIZED`, HTTP 409) and at least one price list of the pack in `SCHEDULED` or `EFFECTIVE` (`ERR_NO_PRICE_LIST`, HTTP 409)."

    Design: Corner/errors/enter_production_requires_price_list
    """
    sc = fx.setup_pilot_line()  # formulation already COMPARTMENTALIZED
    pack = fx.create_tooled_pack(sc["line"]["id"])

    resp = api_client.enter_production_pack_format(pack["id"], SP)
    validate_error(resp, ApiErrorId.ERR_NO_PRICE_LIST)
    after = validate_success(api_client.get_pack_format(pack["id"], SP))
    assert after["status"] == "TOOLED"


def test_launch_requires_producible_pack():
    """PRD §3.2: "Three gates guard the launch, evaluated in this order: the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409), the brand's posture must not be `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409), and at least one pack format of the line must be `IN_PRODUCTION` (`ERR_NO_PRODUCIBLE_PACK_FORMAT`, 409)."

    Design: Corner/errors/launch_requires_producible_pack
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])
    fx.create_price_list_record(pack["id"])  # priced, but never IN_PRODUCTION

    resp = api_client.launch_product_line(sc["line"]["id"], BM)
    validate_error(resp, ApiErrorId.ERR_NO_PRODUCIBLE_PACK_FORMAT)
    line = validate_success(api_client.get_product_line(sc["line"]["id"], BM))
    assert line["status"] == "PILOT"


def test_retire_blocked_until_price_lists_terminal():
    """PRD §3.7: "Retirement moves `IN_PRODUCTION` → `RETIRED` and is only possible once every price list of the pack is terminal — `SUPERSEDED` or `EXPIRED` — otherwise `ERR_PRICE_LISTS_OUTSTANDING` (HTTP 409)."
    PRD §2.4: "Channel price lists move `SCHEDULED` → `EFFECTIVE` when the current time enters their window, and on to `EXPIRED` when it reaches `effective_to`; a `SCHEDULED` list whose window is jumped past entirely goes straight to `EXPIRED`."

    Design: Corner/errors/retire_blocked_until_price_lists_terminal
    """
    sc = fx.setup_launched_line()  # pack IN_PRODUCTION, list EFFECTIVE to 2027-08-01
    pack_id = sc["pack"]["id"]

    blocked = api_client.retire_pack_format(pack_id, SP)
    validate_error(blocked, ApiErrorId.ERR_PRICE_LISTS_OUTSTANDING)

    fx.advance_clock("2027-08-02T00:00:00Z")
    retired = api_client.retire_pack_format(pack_id, SP)
    assert validate_success(retired)["status"] == "RETIRED"


def test_line_stage_too_early_for_registration_and_tooling():
    """PRD §3.4: "the line must be `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`, HTTP 409)".
    PRD §3.7: "Tooling moves `DESIGNED` → `TOOLED` and requires the owning line to be `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`, HTTP 409)."

    Design: Corner/errors/line_stage_too_early_for_registration_and_tooling
    """
    sc = fx.setup_line_with_sealed_formulation()  # line stays FORMULATION
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True,
                            allowed_channels=["HARDWARE"])
    pack = fx.create_pack_format_record(sc["line"]["id"])

    reg = api_client.create_market_registration(
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "formulation_id": sc["formulation"]["id"],
         "expires_on": "2027-01-01T00:00:00Z"}, RA)
    validate_error(reg, ApiErrorId.ERR_LINE_STAGE_TOO_EARLY)

    tool = api_client.tool_pack_format(pack["id"], SP)
    validate_error(tool, ApiErrorId.ERR_LINE_STAGE_TOO_EARLY)


def test_pack_production_requires_compartmentalized_formulation():
    """PRD §3.7: "Entering production moves `TOOLED` → `IN_PRODUCTION` and requires both a `COMPARTMENTALIZED` formulation on the owning line (`ERR_FORMULATION_NOT_COMPARTMENTALIZED`, HTTP 409) and at least one price list of the pack in `SCHEDULED` or `EFFECTIVE` (`ERR_NO_PRICE_LIST`, HTTP 409)."
    PRD §3.3: "From `SEALED` the formulation advances to `COMPARTMENTALIZED` automatically — no explicit call exists — at the moment every one of its component codes is covered by at least one confidentiality grant of that formulation in `ACTIVE` status."

    Design: Difficulty/cross_entity_state_dependency/pack_production_requires_compartmentalized_formulation
    """
    sc = fx.setup_line_with_sealed_formulation()
    line = fx.approve_line_to_pilot(sc["line"]["id"])
    pack = fx.create_tooled_pack(line["id"])
    fx.create_price_list_record(pack["id"])  # price-list gate satisfied throughout

    blocked = api_client.enter_production_pack_format(pack["id"], SP)
    validate_error(blocked, ApiErrorId.ERR_FORMULATION_NOT_COMPARTMENTALIZED)

    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    mfr2 = fx.create_qualified_manufacturer(legal_name="Beta Filling Inc",
                                            capabilities=["AEROSOL_FILL"])
    fx.create_active_grant(mfr1["id"], sc["formulation"]["id"],
                           component_scope=["C1", "C2"])
    fx.create_active_grant(mfr2["id"], sc["formulation"]["id"],
                           component_scope=["C3", "C4"])
    form = validate_success(api_client.get_formulation(sc["formulation"]["id"],
                                                       TEST_USERS["trade_secret_officer_headers"]))
    assert form["status"] == "COMPARTMENTALIZED"

    produced = api_client.enter_production_pack_format(pack["id"], SP)
    assert validate_success(produced)["status"] == "IN_PRODUCTION"


def test_price_list_half_open_adjacency_and_clip():
    """PRD §2.9: "Channel price lists instead run on **datetimes** interpreted as half-open intervals — a list governs from `effective_from` up to but not including `effective_to` — so two lists on the same pack and channel may touch (one's `effective_from` equal to the other's `effective_to`) but may never overlap in the interior."
    PRD §3.7: "An overlapped `SCHEDULED` list becomes `SUPERSEDED`. An overlapped `EFFECTIVE` list is treated by where the newcomer starts: when the new list's `effective_from` is at or before the incumbent's `effective_from`, the incumbent is `SUPERSEDED`; when the new list starts strictly inside the incumbent's window, the incumbent is **clipped** — its `effective_to` is set to the new list's `effective_from` and it stays `EFFECTIVE` until that instant."

    Design: Difficulty/resource_temporal_overlap/price_list_half_open_adjacency_and_clip
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])

    l1 = fx.create_price_list_record(pack["id"], list_price_cents=499,
                                     effective_from="2026-08-01T00:00:00Z",
                                     effective_to="2026-12-01T00:00:00Z")
    assert l1["status"] == "EFFECTIVE", "the window covers the 2026-09-01 clock"

    l2 = fx.create_price_list_record(pack["id"], list_price_cents=520,
                                     effective_from="2026-12-01T00:00:00Z",
                                     effective_to="2027-04-01T00:00:00Z")
    assert l2["status"] == "SCHEDULED", \
        "half-open adjacency at 2026-12-01 is not an overlap"

    l3 = fx.create_price_list_record(pack["id"], list_price_cents=549,
                                     effective_from="2026-11-15T00:00:00Z",
                                     effective_to="2027-02-01T00:00:00Z")

    l1_after = validate_success(api_client.get_price_list(l1["id"], PA))
    assert l1_after["status"] == "EFFECTIVE"
    assert l1_after["effective_to"].startswith("2026-11-15"), \
        "the incumbent EFFECTIVE list is clipped to the newcomer's start"

    l2_after = validate_success(api_client.get_price_list(l2["id"], PA))
    assert l2_after["status"] == "SUPERSEDED", \
        "an overlapped SCHEDULED list is wholly superseded"

    resolved = validate_success(api_client.get_effective_price(
        pack["id"], "HARDWARE", PA, at="2026-11-20T00:00:00Z"))
    assert resolved["price_list_id"] == l3["id"]
    assert resolved["list_price_cents"] == 549


def test_occ_stale_version_on_price_list_create():
    """PRD §2.7: "Creating a channel price list requires `expected_pack_format_version`, holding the caller's last observed `version` of the parent pack format. A mismatch with the pack format's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Both creates themselves mutate the parent's bookkeeping: a successful coverage-assignment creation increments the distributor's `version` by one, and a successful price-list creation increments the pack format's `version` by one."

    Design: Corner/complexity_layers/occ_stale_version_on_price_list_create
    """
    sc = fx.setup_pilot_line()
    pack = fx.create_tooled_pack(sc["line"]["id"])
    observed = pack["version"]

    first = api_client.create_price_list(
        pack["id"],
        {"channel": "HARDWARE", "list_price_cents": 499, "map_price_cents": 300,
         "effective_from": "2026-08-01T00:00:00Z",
         "effective_to": "2027-08-01T00:00:00Z",
         "expected_pack_format_version": observed}, PA)
    validate_success(first, 201)
    assert fx.get_pack_format_version(pack["id"]) == observed + 1, \
        "the successful create incremented the pack version by one"

    stale = api_client.create_price_list(
        pack["id"],
        {"channel": "AUTOMOTIVE", "list_price_cents": 520, "map_price_cents": 320,
         "effective_from": "2026-08-01T00:00:00Z",
         "effective_to": "2027-08-01T00:00:00Z",
         "expected_pack_format_version": observed}, PA)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    assert fx.get_pack_format_version(pack["id"]) == observed + 1, \
        "the rejected replay did not mutate the pack"
