"""Exhibit designs: the dual-variant quote run, the revision cycle, the venue
hanging-sign permission, and the release that mints the exhibit asset."""
from test_helpers import (
    ApiErrorId,
    BASE_CLOCK,
    MAX_DESIGN_REVISIONS,
    TEST_USERS,
    assert_exhibit_asset,
    assert_exhibit_design,
    create_approved_design,
    create_design_with_revisions,
    create_exhibit_design_payload,
    create_exhibitor,
    create_quoted_design,
    decide_design,
    get_asset,
    get_design,
    make_exhibitor_headers,
    quote_design,
    register_asset,
    release_design,
    set_clock,
    setup_show_ground,
    validate_error,
    validate_paginated,
)

OPS = TEST_USERS["show_operations_headers"]

# The geometry every quote scenario below prices: a 400 sqft ISLAND booth with
# 40 linear feet of wall, a hanging sign, and three projected reuses.
SIGNED_ISLAND_DESIGN = {"has_hanging_sign": True, "expected_show_count": 3}


def _quoted_island_design():
    """Show ground at OPEN_FOR_ORDERS plus the signed ISLAND design, quoted once."""
    ground = setup_show_ground()
    design = create_quoted_design(ground["exhibitor"]["id"], ground["booth"]["id"],
                                  **SIGNED_ISLAND_DESIGN)
    return ground, design


class TestDualVariantQuoteRun:
    """One quote run prices the same geometry under both algorithms."""

    def test_quote_run_stores_the_rental_variant_and_its_per_show_figure(self, api):
        """PRD §3.3: "Quoting is the exhibitor's own action and advances the design `DRAFT → QUOTED`."
        PRD §3.3: "A rental base is assembled as `sqft` multiplied by 2400 cents per square foot, plus `linear_feet` multiplied by 15000 cents per linear foot, plus a flat 85000 cents when `has_hanging_sign` is true and nothing when it is false."
        PRD §3.3: "`rental_quote_cents` is that base multiplied by one plus a twelve percent refurbishment load — that is, multiplied by 1.12 — and rounded half up to a whole cent."
        PRD §3.3: "`rental_per_show_cents` equals `rental_quote_cents` exactly, because a rental is re-rented in full for every show and carries neither residual value nor an amortisation denominator."

        Design: Difficulty/dual_variant_calc/design_rental_vs_purchase_quote_divergence
        """
        _, design = _quoted_island_design()

        assert_exhibit_design(design)
        assert design["status"] == "QUOTED", \
            f"Quoting advances DRAFT -> QUOTED, got {design['status']}"
        assert design["rental_quote_cents"] == 1842400, \
            f"rental_quote_cents must be 1842400, got {design['rental_quote_cents']}"
        assert design["rental_per_show_cents"] == 1842400, \
            ("rental_per_show_cents equals rental_quote_cents exactly, got "
             f"{design['rental_per_show_cents']}")

    def test_quote_run_stores_the_purchase_variant_amortised_over_three_shows(self, api):
        """PRD §3.3: "A build cost is assembled as `sqft` multiplied by 7800 cents per square foot, plus `linear_feet` multiplied by 38000 cents per linear foot, plus a flat 210000 cents when `has_hanging_sign` is true."
        PRD §3.3: "`purchase_quote_cents` is that build cost multiplied by one plus a fifteen percent design fee — multiplied by 1.15 — and rounded half up."
        PRD §3.3: "A residual is then taken as `purchase_quote_cents` multiplied by 0.20 and rounded half up."
        PRD §3.3: "`purchase_per_show_cents` is the difference between `purchase_quote_cents` and that residual, divided by `expected_show_count` and rounded half up, with a flat 45000 cents of per-show storage-and-refurbishment carry added on afterwards — the carry is added after the division has been rounded, never folded in before it."

        Design: Difficulty/dual_variant_calc/design_rental_vs_purchase_quote_divergence
        """
        _, design = _quoted_island_design()

        assert design["purchase_quote_cents"] == 5577500, \
            f"purchase_quote_cents must be 5577500, got {design['purchase_quote_cents']}"
        assert design["purchase_per_show_cents"] == 1532333, \
            ("purchase_per_show_cents amortises the residual-net build over three shows "
             f"and adds the carry afterwards, expected 1532333, got "
             f"{design['purchase_per_show_cents']}")

    def test_quote_run_reports_the_breakeven_reuse_count_and_the_selected_price(self, api):
        """PRD §3.3: "The quote run always prices **both** variants and stores both, so the exhibitor can see the road not taken."
        PRD §3.3: "`breakeven_show_count` is the smallest whole number of reuses at which purchasing beats renting on a per-show basis."
        PRD §3.3: "Candidate reuse counts are scanned in ascending order from 1 through 20 inclusive; for each candidate, the difference between `purchase_quote_cents` and the residual is divided by that candidate and rounded half up, then 45000 cents of carry is added, and the first candidate whose result is less than or equal to `rental_per_show_cents` is the answer."
        PRD §3.3: "Finally, `quoted_price_cents` takes the value of `rental_quote_cents` when `selected_acquisition_mode` is `RENTAL` and of `purchase_quote_cents` when it is `PURCHASE`."

        Design: Difficulty/dual_variant_calc/design_rental_vs_purchase_quote_divergence
        """
        _, design = _quoted_island_design()

        assert design["breakeven_show_count"] == 3, \
            f"breakeven_show_count must be 3, got {design['breakeven_show_count']}"
        assert design["selected_acquisition_mode"] == "RENTAL", \
            "The design under test selects RENTAL"
        assert design["quoted_price_cents"] == 1842400, \
            ("quoted_price_cents takes rental_quote_cents under RENTAL, expected "
             f"1842400, got {design['quoted_price_cents']}")
        assert design["rental_quote_cents"] != design["purchase_quote_cents"], \
            ("Both variants are stored and they diverge: rental "
             f"{design['rental_quote_cents']} vs purchase "
             f"{design['purchase_quote_cents']}")


class TestQuoteRevisionCycle:
    """DRAFT -> QUOTED -> DRAFT -> QUOTED is a true cycle, not a forward pipeline."""

    def test_request_revision_returns_a_quoted_design_to_draft_and_clears_every_figure(self, api):
        """PRD §3.3: "`REQUEST_REVISION` sends a `QUOTED` design back to `DRAFT`."
        PRD §3.3: "On success `revision_count` increases by one and all six computed figures — `rental_quote_cents`, `purchase_quote_cents`, `rental_per_show_cents`, `purchase_per_show_cents`, `breakeven_show_count` and `quoted_price_cents` — are cleared back to null, so a re-quote starts from a clean slate."

        Design: Difficulty/non_linear_state_machine/exhibit_design_quote_revision_cycle
        """
        _, design = _quoted_island_design()
        assert design["rental_quote_cents"] == 1842400, \
            "Precondition: the first quote run stored the rental figure"

        returned = decide_design(design["id"], "REQUEST_REVISION",
                                 note="Reduce the sign package")

        assert returned["status"] == "DRAFT", \
            f"REQUEST_REVISION sends a QUOTED design back to DRAFT, got {returned['status']}"
        assert returned["revision_count"] == 1, \
            f"revision_count increases by one, got {returned['revision_count']}"
        for field in ("rental_quote_cents", "purchase_quote_cents",
                      "rental_per_show_cents", "purchase_per_show_cents",
                      "breakeven_show_count", "quoted_price_cents"):
            assert returned[field] is None, \
                f"{field} must be cleared back to null on the return edge, got {returned[field]}"

    def test_requoting_after_a_revision_restores_both_variants_and_keeps_the_count(self, api):
        """PRD §3.3: "Quoting is the exhibitor's own action and advances the design `DRAFT → QUOTED`."
        PRD §3.3: "The quote run always prices **both** variants and stores both, so the exhibitor can see the road not taken."
        PRD §3.3: "It is permitted only while `revision_count` is strictly below 3; a fourth request against a design that has already cycled three times is refused with `ERR_DESIGN_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/exhibit_design_quote_revision_cycle
        """
        ground = setup_show_ground()
        design = create_design_with_revisions(ground["exhibitor"]["id"],
                                              ground["booth"]["id"], 1,
                                              **SIGNED_ISLAND_DESIGN)

        assert design["status"] == "QUOTED", \
            f"The re-quote lands the design back in QUOTED, got {design['status']}"
        assert design["revision_count"] == 1, \
            f"One completed revision cycle leaves revision_count at 1, got {design['revision_count']}"
        assert design["rental_quote_cents"] == 1842400, \
            f"The re-quote restores rental_quote_cents to 1842400, got {design['rental_quote_cents']}"
        assert design["purchase_quote_cents"] == 5577500, \
            ("The re-quote restores purchase_quote_cents to 5577500, got "
             f"{design['purchase_quote_cents']}")

        persisted = get_design(design["id"])
        assert persisted["status"] == "QUOTED", "The cycled design persists as QUOTED"
        assert persisted["revision_count"] == 1, \
            f"The persisted revision_count is 1, got {persisted['revision_count']}"


def test_fourth_revision_request_is_refused_by_the_exhausted_revision_budget(api):
    """PRD §3.3: "It is permitted only while `revision_count` is strictly below 3; a fourth request against a design that has already cycled three times is refused with `ERR_DESIGN_REVISION_LIMIT`."

    Design: Corner/state_machines/design_revision_limit_blocks_the_fourth_cycle
    """
    ground = setup_show_ground()
    design = create_design_with_revisions(ground["exhibitor"]["id"],
                                          ground["booth"]["id"], MAX_DESIGN_REVISIONS,
                                          **SIGNED_ISLAND_DESIGN)
    assert design["revision_count"] == MAX_DESIGN_REVISIONS, \
        f"Precondition: three completed cycles leave revision_count at 3, got {design['revision_count']}"
    assert design["status"] == "QUOTED", \
        "Precondition: the design has just been quoted a fourth time"

    resp = api.decide_design(design["id"],
                             {"decision": "REQUEST_REVISION", "note": "r4"}, OPS)

    validate_error(resp, ApiErrorId.ERR_DESIGN_REVISION_LIMIT)

    unchanged = get_design(design["id"])
    assert unchanged["status"] == "QUOTED", \
        f"The refused fourth request leaves the design QUOTED, got {unchanged['status']}"
    assert unchanged["revision_count"] == MAX_DESIGN_REVISIONS, \
        f"The refused fourth request leaves revision_count at 3, got {unchanged['revision_count']}"


def test_hanging_sign_on_an_inline_booth_is_refused_at_design_creation(api):
    """PRD §3.3: "If `has_hanging_sign` is true, the `booth_type` of the design's booth must appear in the `hanging_sign_booth_types` list of the venue hosting that booth's show; otherwise the request is refused with `ERR_HANGING_SIGN_NOT_PERMITTED`."
    PRD §3.3: "This check runs both when the design is created and again when it is quoted, because a venue's policy may have been edited in between."

    Design: Corner/validations/hanging_sign_on_inline_booth_rejected
    """
    ground = setup_show_ground(
        booth_number="1099",
        booth_type="INLINE",
        venue_overrides={"hanging_sign_booth_types": ["ISLAND", "PENINSULA"]},
    )
    exhibitor_id = ground["exhibitor"]["id"]
    booth_id = ground["booth"]["id"]

    payload = create_exhibit_design_payload(
        exhibitor_id, booth_id, sqft=100, linear_feet=10,
        selected_acquisition_mode="RENTAL", has_hanging_sign=True,
        expected_show_count=1,
    )
    resp = api.create_exhibit_design(payload, make_exhibitor_headers(exhibitor_id))

    validate_error(resp, ApiErrorId.ERR_HANGING_SIGN_NOT_PERMITTED)

    rows, meta = validate_paginated(
        api.list_exhibit_designs(make_exhibitor_headers(exhibitor_id),
                                 params={"booth_id": booth_id}))
    assert meta["total_count"] == 0, \
        f"The refused design was never written, expected 0 rows, got {meta['total_count']}"
    assert rows == [], f"No design may exist on the INLINE booth, got {rows}"


def test_releasing_an_approved_design_mints_and_links_the_exhibit_asset(api):
    """PRD §3.3: "It moves the design `APPROVED → RELEASED_TO_FAB`, requires the booth's posture to be anything other than `FROZEN`, and mints a brand-new exhibit asset in the same transaction: the asset's `exhibitor_id` is copied from the design, its `acquisition_mode` from the design's `selected_acquisition_mode`, its `list_value_cents` from the design's `quoted_price_cents`, and its `shipping_weight_lbs` from the design's `sqft` multiplied by 12 pounds per square foot."
    PRD §3.3: "The new asset starts in `IN_DESIGN` with `condition_grade` `A`, and the design's `asset_id` is set to point at it."
    PRD §3.3: "Designs may be listed and filtered by `exhibitor_id`, `booth_id`, `asset_id` and `status`."

    Design: Corner/endpoints/design_release_mints_and_links_the_exhibit_asset
    """
    ground = setup_show_ground()
    exhibitor_id = ground["exhibitor"]["id"]
    approved = create_approved_design(exhibitor_id, ground["booth"]["id"],
                                      **SIGNED_ISLAND_DESIGN)
    assert approved["quoted_price_cents"] == 1842400, \
        f"Precondition: the approved design is pinned at 1842400, got {approved['quoted_price_cents']}"

    released = release_design(approved["id"])

    assert released["status"] == "RELEASED_TO_FAB", \
        f"Release moves APPROVED -> RELEASED_TO_FAB, got {released['status']}"
    asset_id = released["asset_id"]
    assert asset_id, "Release sets the design's asset_id to point at the minted asset"
    assert get_design(approved["id"])["asset_id"] == asset_id, \
        "The persisted design carries the minted asset's id"

    asset = get_asset(asset_id)
    assert_exhibit_asset(asset)
    assert asset["exhibitor_id"] == exhibitor_id, \
        f"The asset's exhibitor_id is copied from the design, got {asset['exhibitor_id']}"
    assert asset["acquisition_mode"] == "RENTAL", \
        f"The asset's acquisition_mode is copied from the design, got {asset['acquisition_mode']}"
    assert asset["list_value_cents"] == 1842400, \
        f"list_value_cents comes from quoted_price_cents, expected 1842400, got {asset['list_value_cents']}"
    assert asset["shipping_weight_lbs"] == 4800, \
        f"shipping_weight_lbs is 400 sqft times 12 lbs, expected 4800, got {asset['shipping_weight_lbs']}"
    assert asset["status"] == "IN_DESIGN", \
        f"The new asset starts in IN_DESIGN, got {asset['status']}"
    assert asset["condition_grade"] == "A", \
        f"The new asset starts at condition_grade A, got {asset['condition_grade']}"

    rows, meta = validate_paginated(
        api.list_exhibit_designs(OPS, params={"asset_id": asset_id}))
    assert meta["total_count"] == 1, \
        f"Exactly one design names the minted asset, got {meta['total_count']}"
    assert rows[0]["id"] == approved["id"], \
        f"The design filtered by asset_id is the released one, got {rows[0]['id']}"


def test_asset_lineage_is_reverse_reachable_from_its_predecessor(api):
    """PRD §3.4: "An optional `derived_from_asset_id` points back at a predecessor asset when this one was split out of a refurbished parent — a self-reference that the asset listing can filter on, alongside `exhibitor_id`, `current_warehouse_id` and `status`."

    Design: Corner/entities/self_referential_asset_lineage_is_queryable
    """
    set_clock(BASE_CLOCK)
    exhibitor = create_exhibitor(credit_limit_cents=5000000)
    exhibitor_id = exhibitor["id"]
    headers = make_exhibitor_headers(exhibitor_id)

    parent = register_asset(exhibitor_id, acquisition_mode="PURCHASE",
                            list_value_cents=1500000, shipping_weight_lbs=1400)
    child = register_asset(exhibitor_id, acquisition_mode="PURCHASE",
                           list_value_cents=400000, shipping_weight_lbs=300,
                           derived_from_asset_id=parent["id"])

    assert_exhibit_asset(child)
    assert child["derived_from_asset_id"] == parent["id"], \
        ("The descendant points back at its predecessor, expected "
         f"{parent['id']}, got {child['derived_from_asset_id']}")

    rows, meta = validate_paginated(
        api.list_exhibit_assets(headers,
                                params={"derived_from_asset_id": parent["id"]}))
    assert meta["total_count"] == 1, \
        f"Exactly one asset descends from the parent, got {meta['total_count']}"
    assert rows[0]["id"] == child["id"], \
        f"The descendant returned is the child asset, got {rows[0]['id']}"

    owned, owned_meta = validate_paginated(
        api.list_exhibit_assets(headers, params={"exhibitor_id": exhibitor_id}))
    assert owned_meta["total_count"] == 2, \
        f"The exhibitor owns both the parent and the descendant, got {owned_meta['total_count']}"
    assert {row["id"] for row in owned} == {parent["id"], child["id"]}, \
        "Filtering by exhibitor_id returns exactly the parent and the descendant"
