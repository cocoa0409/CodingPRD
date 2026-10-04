"""Counterfeit adjudication and safety bulletins: evidence threshold,
segregation of duties, and the two cascade families."""
from test_helpers import (
    ApiErrorId,
    activate_listing,
    ce_headers,
    create_account,
    create_certified_pack,
    create_listing,
    create_partner,
    create_platform,
    get_bulletin,
    get_listing,
    get_pack,
    issue_bulletin,
    listing_payload,
    make_account_manager_headers,
    make_channel_manager_headers,
    pack_payload,
    report_counterfeit,
    safety_bulletin_payload,
    set_clock,
    validate_error,
    validate_success,
)


def test_counterfeit_confirm_threshold_is_inclusive(api, compliance_engineer_headers):
    """PRD §3.7: "Confirmation additionally requires evidence — an
    `evidence_score` of at least 70, where 70 itself confirms and anything
    lower rejects the confirmation with `ERR_EVIDENCE_INSUFFICIENT`."

    Design: Corner/validations/counterfeit_confirm_threshold_is_inclusive
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-LST")
    rep1 = create_account(org_name="Reporter One")
    rep2 = create_account(org_name="Reporter Two")
    c69 = report_counterfeit(pk["id"], make_account_manager_headers(rep1["id"]),
                             reported_serial="FAKE-69", detection_method="PHYSICAL_INSPECTION")
    c70 = report_counterfeit(pk["id"], make_account_manager_headers(rep2["id"]),
                             reported_serial="FAKE-70", detection_method="PHYSICAL_INSPECTION")
    low = api.resolve_counterfeit_case(c69["id"], {"verdict": "CONFIRMED", "evidence_score": 69},
                                       compliance_engineer_headers)
    validate_error(low, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT)
    confirmed = validate_success(api.resolve_counterfeit_case(
        c70["id"], {"verdict": "CONFIRMED", "evidence_score": 70}, compliance_engineer_headers))
    assert confirmed["status"] == "CONFIRMED", "70 confirms: the threshold is inclusive"
    assert get_pack(pk["id"])["safety_hold"] is True


def test_counterfeit_resolve_by_reporting_user_returns_forbidden(api):
    """PRD §3.7: "Segregation of duties applies: the resolver's `X-User-ID`
    must differ from the case's `created_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/validations/counterfeit_resolve_by_reporting_user_returns_forbidden
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-LST")
    reporter = create_account(org_name="Dup Reporter")
    case = report_counterfeit(pk["id"], make_account_manager_headers(reporter["id"]),
                              reported_serial="FAKE-DUP")
    resp = api.resolve_counterfeit_case(
        case["id"], {"verdict": "CLEARED", "evidence_score": 10},
        ce_headers(reporter["id"]),  # same X-User-ID string as the reporter
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def _setup_counterfeit_cascade():
    """INDUSTRIAL partner with an ACTIVE listing of a CERTIFIED pack, plus a
    counterfeit case reported by the partner's ChannelManager."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-CF")
    cp = create_partner(name="Midwest Industrial Supply")
    listing = create_listing(cp, battery_pack_id=pk["id"], wholesale_price_cents=12000,
                             allocation_qty=50)
    activate_listing(listing["id"], cp["id"])
    case = report_counterfeit(pk["id"], make_channel_manager_headers(cp["id"]),
                              reported_serial="FAKE-9001", detection_method="SERIAL_MISMATCH")
    return pf, pk, cp, listing, case


def test_counterfeit_confirm_cascade_holds_pack_and_suspends_listing(api,
                                                                     compliance_engineer_headers):
    """PRD §2.9: "Hop 1 sets the implicated pack's `safety_hold` to true and
    bumps the pack's `version`. Hop 2, caused by hop 1, moves every `ACTIVE`
    distribution listing referencing that pack to `SUSPENDED` with
    `requires_relist_ack` set true."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_three_hop_cascade
    """
    pf, pk, cp, listing, case = _setup_counterfeit_cascade()
    resolved = validate_success(api.resolve_counterfeit_case(
        case["id"], {"verdict": "CONFIRMED", "evidence_score": 80},
        compliance_engineer_headers))
    assert resolved["status"] == "CONFIRMED"
    pack = get_pack(pk["id"])
    assert pack["safety_hold"] is True
    assert pack["certification_status"] == "CERTIFIED", "the hold is orthogonal to certification"
    held_listing = get_listing(listing["id"])
    assert held_listing["status"] == "SUSPENDED"
    assert held_listing["requires_relist_ack"] is True


def test_counterfeit_confirm_cascade_engages_partner_gate(api, compliance_engineer_headers):
    """PRD §2.9: "Hop 3, caused by hop 2, recomputes each affected partner's
    `has_suspended_listings` to true, which engages the partner gate that
    rejects subsequent listing creation with
    `ERR_PARTNER_HAS_SUSPENDED_LISTINGS` until every suspended listing is
    re-listed or ended."
    PRD §3.7: "Both verdicts stamp `resolved_by_user_id` and increment the
    case's `version`"

    Design: Difficulty/transitive_cascade/counterfeit_confirm_three_hop_cascade
    """
    pf, pk, cp, listing, case = _setup_counterfeit_cascade()
    resolved = validate_success(api.resolve_counterfeit_case(
        case["id"], {"verdict": "CONFIRMED", "evidence_score": 80},
        compliance_engineer_headers))
    assert resolved["resolved_by_user_id"] == "ce-bob"
    fresh_version = get_listing(listing["id"])["channel_partner_version"]
    gated = api.create_listing(
        listing_payload(cp["id"], fresh_version, battery_pack_id=pk["id"],
                        wholesale_price_cents=12500, allocation_qty=10),
        make_channel_manager_headers(cp["id"]),
    )
    validate_error(gated, ApiErrorId.ERR_PARTNER_HAS_SUSPENDED_LISTINGS)


def _setup_recall_cascade():
    """INDUSTRIAL partner with an ACTIVE listing of a CERTIFIED pack."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-RC")
    cp = create_partner(name="Midwest Industrial Supply")
    listing = create_listing(cp, battery_pack_id=pk["id"], wholesale_price_cents=12000,
                             allocation_qty=25)
    activate_listing(listing["id"], cp["id"])
    return pf, pk, cp, listing


def test_recall_bulletin_recalls_pack_and_ends_listing(api):
    """PRD §2.9: "A `RECALL`-severity bulletin moves each targeted `CERTIFIED`
    pack to `RECALLED` (hop 1), and each pack's own recall transition then ends
    its `ACTIVE` listings (hop 2) while the platform's `current_generation` is
    recomputed with the platform `version` bumped."

    Design: Difficulty/transitive_cascade/recall_bulletin_two_hop_cascade
    """
    pf, pk, cp, listing = _setup_recall_cascade()
    bulletin = issue_bulletin(pf["id"], battery_pack_ids=[pk["id"]], severity="RECALL",
                              title="Thermal runaway risk in P-RC",
                              effective_from="2026-09-01T00:00:00Z")
    assert bulletin["status"] == "ISSUED"
    assert bulletin["severity"] == "RECALL"
    assert get_pack(pk["id"])["certification_status"] == "RECALLED"
    ended = get_listing(listing["id"])
    assert ended["status"] == "ENDED", "recall end is terminal, not a suspension"


def test_recall_bulletin_recomputes_platform_current_generation(api, product_engineer_headers):
    """PRD §3.1: "The aggregate is recomputed, and the platform's `version`
    bumped by 1, whenever a certification decision certifies a pack and
    whenever the recall cascade removes a certified pack."
    PRD §3.1: "A new pack's `pack_generation` must be at least 1 and at most
    the platform's `current_generation` plus 1"

    Design: Difficulty/transitive_cascade/recall_bulletin_two_hop_cascade
    """
    pf, pk, cp, listing = _setup_recall_cascade()
    issue_bulletin(pf["id"], battery_pack_ids=[pk["id"]], severity="RECALL",
                   title="Thermal runaway risk in P-RC",
                   effective_from="2026-09-01T00:00:00Z")
    # current_generation fell back to 0: gen-1 is allowed, gen-2 is not.
    gen1 = api.create_pack(pack_payload(pf["id"], sku="P-RC-G1", pack_generation=1),
                           product_engineer_headers)
    validate_success(gen1, 201)
    gen2 = api.create_pack(pack_payload(pf["id"], sku="P-RC-G2", pack_generation=2),
                           product_engineer_headers)
    validate_error(gen2, ApiErrorId.ERR_PACK_GENERATION_VIOLATION)


def test_bulletin_window_adjacency_allowed_overlap_rejected(api, compliance_engineer_headers):
    """PRD §3.7: "Bulletin windows are half-open: the start instant is inside
    the window and the end instant is outside it. On the same platform, a new
    bulletin's window may not intersect any `ISSUED` bulletin's window —
    adjacency is allowed, so a new window beginning exactly at an existing
    window's `effective_to` does NOT overlap"

    Design: Difficulty/resource_temporal_overlap/bulletin_window_half_open_adjacency_vs_overlap
    """
    set_clock()
    pf = create_platform(code="MX18")
    b1 = issue_bulletin(pf["id"], severity="ADVISORY", title="B1",
                        effective_from="2026-10-01T00:00:00Z",
                        effective_to="2026-11-01T00:00:00Z")
    b2 = issue_bulletin(pf["id"], severity="ADVISORY", title="B2 adjacent-before",
                        effective_from="2026-09-01T00:00:00Z",
                        effective_to="2026-10-01T00:00:00Z")
    assert b2["status"] == "ISSUED", "touching at one endpoint is not an overlap"
    overlapping = api.create_safety_bulletin(
        safety_bulletin_payload(pf["id"], severity="URGENT", title="B3 overlapping",
                                effective_from="2026-10-15T00:00:00Z",
                                effective_to="2026-12-01T00:00:00Z"),
        compliance_engineer_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_BULLETIN_WINDOW_OVERLAP)


def test_bulletin_window_overlap_allowed_with_supersession(api, compliance_engineer_headers):
    """PRD §3.7: "unless `supersedes_bulletin_id` names an overlapping `ISSUED`
    bulletin, in which case creation succeeds and the named bulletin moves to
    `SUPERSEDED` with its `version` incremented; any other intersection is
    rejected with `ERR_BULLETIN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bulletin_window_half_open_adjacency_vs_overlap
    """
    set_clock()
    pf = create_platform(code="MX18")
    b1 = issue_bulletin(pf["id"], severity="ADVISORY", title="B1",
                        effective_from="2026-10-01T00:00:00Z",
                        effective_to="2026-11-01T00:00:00Z")
    b3 = validate_success(api.create_safety_bulletin(
        safety_bulletin_payload(pf["id"], severity="URGENT", title="B3 superseding",
                                effective_from="2026-10-15T00:00:00Z",
                                effective_to="2026-12-01T00:00:00Z",
                                supersedes_bulletin_id=b1["id"]),
        compliance_engineer_headers,
    ), 201)
    assert b3["status"] == "ISSUED"
    superseded = get_bulletin(b1["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == b1["version"] + 1
