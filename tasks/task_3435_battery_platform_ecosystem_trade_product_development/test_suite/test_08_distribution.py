"""Distribution listings: supersession, partner OCC, ownership, activation
gates, allocation cap, and validation priority."""
from test_helpers import (
    ApiErrorId,
    activate_listing,
    create_certified_pack,
    create_listing,
    create_pack,
    create_partner,
    create_platform,
    get_listing,
    listing_payload,
    make_channel_manager_headers,
    report_counterfeit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_partner_with_certified_pack(channel_type="INDUSTRIAL_DISTRIBUTOR",
                                       name="Midwest Industrial Supply"):
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-LST")
    cp = create_partner(name=name, channel_type=channel_type)
    return pf, pk, cp


def test_listing_create_supersedes_prior_listing(api, channel_manager_headers):
    """PRD §3.6: "Creation supersedes any prior non-`ENDED` listing of the same
    partner and product: the prior listing moves to `ENDED` with its
    `superseded_by_listing_id` set to the new listing, and the partner's
    `version` increments by 1."
    PRD §3.6: "the listings collection filters by `channel_partner_id`,
    `tool_model_id`, `battery_pack_id`, `charger_id`, and
    `superseded_by_listing_id`."

    Design: Corner/state_machines/listing_create_supersedes_prior_listing
    """
    pf, pk, cp = _setup_partner_with_certified_pack()
    l1 = create_listing(cp, battery_pack_id=pk["id"], wholesale_price_cents=12000,
                        allocation_qty=10)
    l2 = create_listing(cp, l1["channel_partner_version"], battery_pack_id=pk["id"],
                        wholesale_price_cents=11500, allocation_qty=20)
    prior = get_listing(l1["id"])
    assert prior["status"] == "ENDED"
    assert prior["superseded_by_listing_id"] == l2["id"]
    assert l2["status"] == "PROPOSED"
    assert l2["wholesale_price_cents"] == 11500
    rows, meta = validate_paginated(api.list_listings(
        channel_manager_headers, params={"superseded_by_listing_id": l2["id"]}))
    assert [r["id"] for r in rows] == [l1["id"]] and meta["total_count"] == 1


def test_listing_create_with_stale_partner_version_returns_412(api):
    """PRD §2.7: "Creating a `DistributionListing` requires
    `expected_channel_partner_version`, matching the target `ChannelPartner`'s
    current `version`. Listing creation legitimately supersedes any prior
    non-`ENDED` listing of the same partner and product, so a writer holding a
    stale partner view must re-read before its create is accepted; if the
    partner's version has advanced since the client last observed it, the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "every `DistributionListing` response echoes
    `channel_partner_version`, the owning partner's `version` at response time"

    Design: Corner/cross_cutting_complexity_layers/listing_create_with_stale_partner_version_returns_412
    """
    pf, pk, cp = _setup_partner_with_certified_pack()
    headers = make_channel_manager_headers(cp["id"])
    l1 = create_listing(cp, battery_pack_id=pk["id"], allocation_qty=10)
    assert l1["channel_partner_version"] == cp["version"] + 1
    stale = api.create_listing(
        listing_payload(cp["id"], cp["version"], battery_pack_id=pk["id"],
                        wholesale_price_cents=11500, allocation_qty=20),
        headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    l2 = create_listing(cp, l1["channel_partner_version"], battery_pack_id=pk["id"],
                        wholesale_price_cents=11500, allocation_qty=20)
    assert l2["status"] == "PROPOSED"
    assert get_listing(l1["id"])["status"] == "ENDED", "superseded by the accepted create"


def test_channel_manager_cannot_create_listing_for_other_partner(api):
    """PRD §3.6: "A `ChannelManager` creates a listing for its own partner —
    `X-User-ID` must equal `channel_partner_id` (`ERR_FORBIDDEN`)"

    Design: Corner/rbac/channel_manager_cannot_create_listing_for_other_partner
    """
    pf, pk, cp = _setup_partner_with_certified_pack()
    cpq = create_partner(name="Other Industrial", region="NE")
    resp = api.create_listing(
        listing_payload(cp["id"], cp["version"], battery_pack_id=pk["id"],
                        wholesale_price_cents=12000, allocation_qty=10),
        make_channel_manager_headers(cpq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(api.list_listings(
        make_channel_manager_headers(cp["id"]), params={"channel_partner_id": cp["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_listing_activation_blocked_while_pack_not_certified(api):
    """PRD §3.6: "a pack listing requires the pack `CERTIFIED`
    (`ERR_CERTIFICATION_REQUIRED`) and not on `safety_hold` (`ERR_SAFETY_HOLD`)"

    Design: Difficulty/cross_entity_state_dependency/listing_activation_gated_by_pack_certification_state
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LG")  # stays in DESIGN
    cp = create_partner(name="Midwest Industrial Supply")
    listing = create_listing(cp, battery_pack_id=pk["id"], allocation_qty=40)
    resp = api.transition_listing(listing["id"], {"to_status": "ACTIVE"},
                                  make_channel_manager_headers(cp["id"]))
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
    assert get_listing(listing["id"])["status"] == "PROPOSED"


def test_listing_activation_succeeds_after_pack_certified(api):
    """PRD §3.6: "a pack listing requires the pack `CERTIFIED`
    (`ERR_CERTIFICATION_REQUIRED`) and not on `safety_hold` (`ERR_SAFETY_HOLD`);
    a tool listing requires the tool `LAUNCHED` (`ERR_INVALID_STATE`); a
    charger listing has no readiness gate."
    PRD §3.2: "A `ProductEngineer` submits a pack in `DESIGN` — or resubmits
    one in `REJECTED` — moving it to `SUBMITTED`"

    Design: Difficulty/cross_entity_state_dependency/listing_activation_gated_by_pack_certification_state
    """
    from test_helpers import certify_pack
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LG")
    cp = create_partner(name="Midwest Industrial Supply")
    listing = create_listing(cp, battery_pack_id=pk["id"], allocation_qty=40)
    first = api.transition_listing(listing["id"], {"to_status": "ACTIVE"},
                                   make_channel_manager_headers(cp["id"]))
    validate_error(first, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
    certify_pack(pk["id"])
    activated = activate_listing(listing["id"], cp["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["requires_relist_ack"] is False


def _setup_allocation_world():
    """HOME_CENTER partner (cap 500) with three PROPOSED listings of three
    CERTIFIED 100 Wh packs: L1 qty 200, L2 qty 300, L3 qty 200."""
    set_clock()
    pf = create_platform(code="MX18")
    packs = [create_certified_pack(pf["id"], sku=f"P-INV2-{g}", pack_generation=g,
                                   rated_capacity_wh=100) for g in (1, 2, 3)]
    cp = create_partner(name="HomeCap", channel_type="HOME_CENTER", region="SE")
    l1 = create_listing(cp, battery_pack_id=packs[0]["id"], allocation_qty=200)
    l2 = create_listing(cp, l1["channel_partner_version"],
                        battery_pack_id=packs[1]["id"], allocation_qty=300)
    l3 = create_listing(cp, l2["channel_partner_version"],
                        battery_pack_id=packs[2]["id"], allocation_qty=200)
    return cp, l1, l2, l3


def test_allocation_cap_inclusive_boundary_lands_exactly_on_cap(api):
    """PRD §3.6: "the allocation cap, which is inclusive: the partner's
    `active_allocation_total` plus this listing's `allocation_qty` must be at
    most 500 for a `HOME_CENTER` partner or at most 10000 for an
    `INDUSTRIAL_DISTRIBUTOR` partner, and exceeding the cap is
    `ERR_ALLOCATION_CAP_EXCEEDED`; an activation landing exactly on the cap
    succeeds."

    Design: Difficulty/compensating_invariant/listing_end_restores_partner_allocation_total
    """
    cp, l1, l2, l3 = _setup_allocation_world()
    a1 = activate_listing(l1["id"], cp["id"])
    assert a1["status"] == "ACTIVE"
    a2 = activate_listing(l2["id"], cp["id"])
    assert a2["status"] == "ACTIVE"  # 200 + 300 == 500 == cap: inclusive
    resp = api.transition_listing(l3["id"], {"to_status": "ACTIVE"},
                                  make_channel_manager_headers(cp["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED)  # 500 + 200 > 500


def test_listing_end_restores_partner_allocation_total(api, channel_manager_headers):
    """PRD §3.6: "Ending is available from `PROPOSED`, `ACTIVE`, or `SUSPENDED`
    to the terminal `ENDED` state"
    PRD §3.6: "Fourth, every successful activation recomputes the partner's
    `active_allocation_total` and increments the listing's `version`."

    Design: Difficulty/compensating_invariant/listing_end_restores_partner_allocation_total
    """
    cp, l1, l2, l3 = _setup_allocation_world()
    activate_listing(l1["id"], cp["id"])
    activate_listing(l2["id"], cp["id"])
    blocked = api.transition_listing(l3["id"], {"to_status": "ACTIVE"},
                                     make_channel_manager_headers(cp["id"]))
    validate_error(blocked, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED)
    ended = api.transition_listing(l1["id"], {"to_status": "ENDED"},
                                   make_channel_manager_headers(cp["id"]))
    validate_success(ended, 200)
    a3 = activate_listing(l3["id"], cp["id"])
    assert a3["status"] == "ACTIVE"  # 300 + 200 == 500 again, zero drift
    rows, meta = validate_paginated(api.list_listings(
        channel_manager_headers, params={"channel_partner_id": cp["id"]}))
    by_id = {r["id"]: r["status"] for r in rows}
    assert by_id[l1["id"]] == "ENDED"
    assert by_id[l2["id"]] == "ACTIVE"
    assert by_id[l3["id"]] == "ACTIVE"


def _setup_hold_vs_segmentation():
    """HOME_CENTER partner with a PROPOSED listing of a CERTIFIED 300 Wh pack,
    then a CONFIRMED counterfeit case sets the pack's safety_hold."""
    from test_helpers import api_client, ce_headers
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-PR2", rated_capacity_wh=300,
                               max_charge_rate_w=400, replacement_price_cents=30000)
    cp = create_partner(name="HomeMega", channel_type="HOME_CENTER", region="SE")
    listing = create_listing(cp, battery_pack_id=pk["id"], wholesale_price_cents=18000,
                             allocation_qty=100)
    case = report_counterfeit(pk["id"], make_channel_manager_headers(cp["id"]),
                              reported_serial="FAKE-3000", detection_method="CHARGE_ANOMALY")
    resolved = validate_success(api_client.resolve_counterfeit_case(
        case["id"], {"verdict": "CONFIRMED", "evidence_score": 95}, ce_headers()))
    assert resolved["status"] == "CONFIRMED"
    return cp, listing


def test_listing_activate_safety_hold_beats_segmentation(api):
    """PRD §2.8: "the server evaluates the following checks in the fixed
    priority order below and reports the violation with the LOWEST priority
    number — earlier checks mask later ones."
    PRD §2.8: "9. Safety hold and evidence: a pack listing cannot activate or
    relist while the pack's `safety_hold` is true, reported as `ERR_SAFETY_HOLD`
    (409)"

    Design: Difficulty/priority_pair_validation_conflict/listing_activate_safety_hold_beats_segmentation
    """
    cp, listing = _setup_hold_vs_segmentation()
    resp = api.transition_listing(listing["id"], {"to_status": "ACTIVE"},
                                  make_channel_manager_headers(cp["id"]))
    # 300 Wh > 216 also violates HOME_CENTER segmentation (priority 14), but
    # the safety hold (priority 9) is reported.
    validate_error(resp, ApiErrorId.ERR_SAFETY_HOLD)


def test_listing_activate_safety_hold_leaves_listing_proposed(api):
    """PRD §2.8: "14. Channel segmentation: a `HOME_CENTER` partner may not
    activate `TRADE_SPECIALIST` tools or packs rated above 216 watt-hours;
    otherwise `ERR_SEGMENT_NOT_ALLOWED` (409)."
    PRD §3.6: "The new listing starts with `status` `PROPOSED`."

    Design: Difficulty/priority_pair_validation_conflict/listing_activate_safety_hold_beats_segmentation
    """
    cp, listing = _setup_hold_vs_segmentation()
    resp = api.transition_listing(listing["id"], {"to_status": "ACTIVE"},
                                  make_channel_manager_headers(cp["id"]))
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_SEGMENT_NOT_ALLOWED
    assert get_listing(listing["id"])["status"] == "PROPOSED"
