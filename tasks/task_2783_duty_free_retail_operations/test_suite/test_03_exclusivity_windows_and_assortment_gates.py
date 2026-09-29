"""Exclusivity grant windows, the observed traveller mix and the four assortment gates."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BRAND_ALREADY_SUSPENDED,
    ERR_BRAND_SUSPENDED,
    ERR_EXCLUSIVITY_CONFLICT,
    ERR_EXCLUSIVITY_WINDOW_OVERLAP,
    ERR_NATIONALITY_MIX_BELOW_THRESHOLD,
)
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    created,
    ids_of,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START, NATIONALITY_MIX_WINDOW_DAYS
from test_helpers.test_users import TERMINAL_ADMIN_HEADERS


def test_a_grant_window_that_intersects_an_active_one_is_refused(api):
    """A rival window starting one day before the incumbent's end intersects it.

    PRD 3.1: "Two `ACTIVE` grants for the same terminal and category may not have intersecting intervals: an intersection exists when the stored grant's `effective_from` is earlier than the new grant's `effective_to` **and** the new grant's `effective_from` is earlier than the stored grant's `effective_to`."

    Design: Difficulty/resource_temporal_overlap/exclusivity_grant_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    aurora = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    northwind = fx.register_brand(api, name="Northwind Distillers", category="LIQUOR")

    incumbent = fx.grant_exclusivity(
        api,
        aurora["id"],
        terminal["id"],
        category="LIQUOR",
        scope="TERMINAL_EXCLUSIVE",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assert incumbent["status"] == "ACTIVE"

    response = api.create_grant(
        f.grant_payload(
            northwind["id"],
            terminal["id"],
            category="LIQUOR",
            scope="TERMINAL_EXCLUSIVE",
            effective_from="2026-08-31T00:00:00Z",
            effective_to="2026-10-01T00:00:00Z",
        ),
        TERMINAL_ADMIN_HEADERS,
    )
    validate_error(response, ERR_EXCLUSIVITY_WINDOW_OVERLAP)

    grants, _ = page(api.list_grants(TERMINAL_ADMIN_HEADERS, {"terminal_id": terminal["id"]}))
    assert ids_of(grants) == [incumbent["id"]]


def test_exact_adjacency_is_accepted_and_a_revoked_window_is_reusable(api):
    """The half-open interval lets the next grant start exactly where the incumbent ends,
    and revocation withdraws the incumbent's own window from the check.

    PRD 3.1: "A new grant whose `effective_from` is exactly the stored grant's `effective_to` therefore abuts it without intersecting and is accepted, while any true overlap is refused with `ERR_EXCLUSIVITY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/exclusivity_grant_half_open_windows_reject_overlap_but_accept_exact_adjacency
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    aurora = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    northwind = fx.register_brand(api, name="Northwind Distillers", category="LIQUOR")

    incumbent = fx.grant_exclusivity(
        api,
        aurora["id"],
        terminal["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )

    abutting = created(
        api.create_grant(
            f.grant_payload(
                northwind["id"],
                terminal["id"],
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            TERMINAL_ADMIN_HEADERS,
        )
    )
    assert_instant(abutting["effective_from"], "2026-09-01T00:00:00Z", "effective_from")
    assert abutting["status"] == "ACTIVE"

    revoked = ok(api.revoke_grant(incumbent["id"], TERMINAL_ADMIN_HEADERS))
    assert revoked["status"] == "REVOKED"
    assert_instant(revoked["revoked_at"], CLOCK_START, "revoked_at")

    reused = created(
        api.create_grant(
            f.grant_payload(
                northwind["id"],
                terminal["id"],
                effective_from="2026-08-05T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z",
            ),
            TERMINAL_ADMIN_HEADERS,
        )
    )
    assert reused["status"] == "ACTIVE"

    active, _ = page(
        api.list_grants(TERMINAL_ADMIN_HEADERS, {"terminal_id": terminal["id"], "status": "ACTIVE"})
    )
    assert sorted(ids_of(active)) == sorted([abutting["id"], reused["id"]])


def _rival_gin_under_exclusivity(api):
    """Terminal SIN where a rival holds the LIQUOR exclusivity and the CN share is 3333 bps."""
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    aurora = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    northwind = fx.register_brand(api, name="Northwind Distillers", category="LIQUOR")
    grant = fx.grant_exclusivity(
        api,
        aurora["id"],
        terminal["id"],
        category="LIQUOR",
        scope="TERMINAL_EXCLUSIVE",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    gin = fx.register_product(
        api,
        northwind["id"],
        sku="NW-GIN-700",
        category="LIQUOR",
        unit_price_cents=6000,
        is_liquid=True,
        liquid_ml=700,
        target_nationality_code="CN",
        required_nationality_share_bps=5000,
    )
    fx.open_ledger(api, terminal["id"], gin["id"])
    for nationality, hour in (("CN", "10"), ("IN", "11"), ("JP", "12")):
        fx.scanned_itinerary(
            api,
            terminal["id"],
            nationality_code=nationality,
            departure_utc="2026-08-25T%s:00:00Z" % hour,
        )
    return terminal, grant, gin


def test_the_exclusivity_conflict_answers_before_the_nationality_mix_shortfall(api):
    """Both governance gates fail; the referential tier is the one that reports.

    PRD 2.8: "**Referential coherence.** `ERR_EXCLUSIVITY_CONFLICT`, `ERR_PRODUCT_CATEGORY_MISMATCH`, `ERR_BRAND_SUSPENDED` and `ERR_TERMINAL_MISMATCH`, followed by the availability of arrival-allowance rules for the categories in play (`ERR_ALLOWANCE_RULE_MISSING`)."

    Design: Difficulty/priority_pair_validation_conflict/exclusivity_referential_error_outranks_nationality_mix_constraint_error
    """
    terminal, _grant, gin = _rival_gin_under_exclusivity(api)

    stored = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert stored["scanned_itinerary_count_30d"] == 3
    assert stored["traveler_nationality_mix"]["CN"] == 3333

    response = api.list_product(gin["id"], TERMINAL_ADMIN_HEADERS)
    validate_error(response, ERR_EXCLUSIVITY_CONFLICT)
    assert response.json()["data"]["error_id"] != ERR_NATIONALITY_MIX_BELOW_THRESHOLD


def test_revoking_the_grant_isolates_the_nationality_mix_shortfall(api):
    """With the referential gate withdrawn, the constraint tier finally speaks.

    PRD 3.2: "A terminal that falls short refuses the admission with `ERR_NATIONALITY_MIX_BELOW_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/exclusivity_referential_error_outranks_nationality_mix_constraint_error
    """
    _terminal, grant, gin = _rival_gin_under_exclusivity(api)

    validate_error(api.list_product(gin["id"], TERMINAL_ADMIN_HEADERS), ERR_EXCLUSIVITY_CONFLICT)

    revoked = ok(api.revoke_grant(grant["id"], TERMINAL_ADMIN_HEADERS))
    assert revoked["status"] == "REVOKED"

    validate_error(api.list_product(gin["id"], TERMINAL_ADMIN_HEADERS), ERR_NATIONALITY_MIX_BELOW_THRESHOLD)

    stored = ok(api.get_product(gin["id"], TERMINAL_ADMIN_HEADERS))
    assert stored["assortment_status"] == "PENDING"
    assert_nulls(stored, "listed_at")


def test_a_share_exactly_equal_to_the_requirement_admits_the_sku(api):
    """One CN traveller out of two gives 5000 bps against a 5000 bps requirement.

    PRD 3.2: "A nationality absent from the mix map counts as 0 basis points, and the comparison is inclusive, so a share exactly equal to the requirement passes."

    Design: Difficulty/boundary_precision_check/nationality_mix_share_exactly_equal_to_requirement_is_accepted
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    whisky = fx.register_product(
        api,
        brand["id"],
        sku="AUR-WHISKY-700",
        category="LIQUOR",
        is_liquid=True,
        liquid_ml=700,
        target_nationality_code="CN",
        required_nationality_share_bps=5000,
    )
    fx.open_ledger(api, terminal["id"], whisky["id"])
    fx.scanned_itinerary(api, terminal["id"], nationality_code="CN", departure_utc="2026-08-25T10:00:00Z")
    fx.scanned_itinerary(api, terminal["id"], nationality_code="IN", departure_utc="2026-08-25T11:00:00Z")

    mix = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert mix["window_days"] == NATIONALITY_MIX_WINDOW_DAYS
    assert mix["scanned_itinerary_count"] == 2
    assert mix["mix_bps"] == {"CN": 5000, "IN": 5000}

    listed = ok(api.list_product(whisky["id"], TERMINAL_ADMIN_HEADERS))
    assert listed["assortment_status"] == "LISTED"
    assert_instant(listed["listed_at"], CLOCK_START, "listed_at")


def test_an_absent_nationality_counts_as_zero_and_only_a_nonzero_floor_bars_the_sku(api):
    """A target nationality nobody flies still clears a 0 bps requirement, and a single
    basis point of requirement is enough to bar it.

    PRD 3.2: "A nationality absent from the mix map counts as 0 basis points, and the comparison is inclusive, so a share exactly equal to the requirement passes."

    Design: Difficulty/boundary_precision_check/nationality_mix_share_exactly_equal_to_requirement_is_accepted
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    tolerant = fx.register_product(
        api,
        brand["id"],
        sku="AUR-WHISKY-700",
        category="LIQUOR",
        target_nationality_code="JP",
        required_nationality_share_bps=0,
    )
    demanding = fx.register_product(
        api,
        brand["id"],
        sku="AUR-RUM-700",
        category="LIQUOR",
        target_nationality_code="JP",
        required_nationality_share_bps=1,
    )
    fx.open_ledger(api, terminal["id"], tolerant["id"])
    fx.open_ledger(api, terminal["id"], demanding["id"])
    fx.scanned_itinerary(api, terminal["id"], nationality_code="CN", departure_utc="2026-08-25T10:00:00Z")
    fx.scanned_itinerary(api, terminal["id"], nationality_code="IN", departure_utc="2026-08-25T11:00:00Z")

    mix = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert "JP" not in mix["mix_bps"]

    admitted = ok(api.list_product(tolerant["id"], TERMINAL_ADMIN_HEADERS))
    assert admitted["assortment_status"] == "LISTED"

    validate_error(
        api.list_product(demanding["id"], TERMINAL_ADMIN_HEADERS),
        ERR_NATIONALITY_MIX_BELOW_THRESHOLD,
    )
    assert ok(api.get_product(demanding["id"], TERMINAL_ADMIN_HEADERS))["assortment_status"] == "PENDING"


def _suspended_brand_with_two_products(api):
    """A brand with one LISTED and one PENDING product, suspended after the first listing."""
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Northwind Distillers", category="LIQUOR")
    gin = fx.register_product(
        api,
        brand["id"],
        sku="NW-GIN-700",
        category="LIQUOR",
        unit_price_cents=6000,
        is_liquid=True,
        liquid_ml=700,
    )
    vodka = fx.register_product(
        api,
        brand["id"],
        sku="NW-VODKA-700",
        category="LIQUOR",
        unit_price_cents=5000,
        is_liquid=True,
        liquid_ml=700,
    )
    listed_gin = ok(api.list_product(gin["id"], TERMINAL_ADMIN_HEADERS))
    assert listed_gin["assortment_status"] == "LISTED"
    suspended = ok(api.suspend_brand(brand["id"], TERMINAL_ADMIN_HEADERS))
    return terminal, brand, gin, vodka, suspended


def test_listing_is_refused_because_the_parent_brand_left_active(api):
    """The vodka is still a perfectly valid PENDING product; its brand is what bars it.

    PRD 3.2: "Its owning brand must be `ACTIVE`, otherwise `ERR_BRAND_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/product_listing_gated_on_brand_suspension_state
    """
    _terminal, _brand, gin, vodka, suspended = _suspended_brand_with_two_products(api)

    assert suspended["status"] == "SUSPENDED"
    assert_instant(suspended["suspended_at"], CLOCK_START, "suspended_at")

    validate_error(api.list_product(vodka["id"], TERMINAL_ADMIN_HEADERS), ERR_BRAND_SUSPENDED)

    stored_vodka = ok(api.get_product(vodka["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_vodka["assortment_status"] == "PENDING"
    assert_nulls(stored_vodka, "listed_at")
    assert ok(api.get_product(gin["id"], TERMINAL_ADMIN_HEADERS))["assortment_status"] == "DELISTED"


def test_the_suspension_cascade_only_delists_listed_siblings(api):
    """The cascade takes the LISTED gin and leaves the PENDING vodka alone, and a repeat
    suspension of the same brand is refused.

    PRD 3.1: "Suspension is not a quiet flag flip: **every** product of that brand whose assortment standing is `LISTED` is delisted as part of the same request, processed in the products' `created_at` ascending order, each moving `LISTED → DELISTED` with its `listed_at` cleared back to null."

    Design: Difficulty/cross_entity_state_dependency/product_listing_gated_on_brand_suspension_state
    """
    _terminal, brand, gin, vodka, _suspended = _suspended_brand_with_two_products(api)

    stored_gin = ok(api.get_product(gin["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_gin["assortment_status"] == "DELISTED"
    assert_nulls(stored_gin, "listed_at")

    stored_vodka = ok(api.get_product(vodka["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_vodka["assortment_status"] == "PENDING"

    validate_error(api.suspend_brand(brand["id"], TERMINAL_ADMIN_HEADERS), ERR_BRAND_ALREADY_SUSPENDED)
    assert ok(api.get_brand(brand["id"], TERMINAL_ADMIN_HEADERS))["status"] == "SUSPENDED"


def test_the_mix_gate_is_re_read_on_every_listing_attempt(api):
    """A CN share of 3333 bars the SKU; a fourth CN scan lifts it to 5000 and admits it.

    PRD 3.2: "Finally, the traveller mix must justify the SKU: at **every** terminal that holds a bonded stock ledger for this product, the share recorded in that terminal's `traveler_nationality_mix` for the product's `target_nationality_code` must be at least `required_nationality_share_bps`."

    Design: Corner/validations/assortment_below_the_required_nationality_share_is_rejected
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    whisky = fx.register_product(
        api,
        brand["id"],
        sku="AUR-WHISKY-700",
        category="LIQUOR",
        is_liquid=True,
        liquid_ml=700,
        target_nationality_code="CN",
        required_nationality_share_bps=5000,
    )
    fx.open_ledger(api, terminal["id"], whisky["id"])
    for nationality, hour in (("CN", "10"), ("IN", "11"), ("JP", "12")):
        fx.scanned_itinerary(
            api,
            terminal["id"],
            nationality_code=nationality,
            departure_utc="2026-08-25T%s:00:00Z" % hour,
        )

    assert ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["traveler_nationality_mix"]["CN"] == 3333
    validate_error(api.list_product(whisky["id"], TERMINAL_ADMIN_HEADERS), ERR_NATIONALITY_MIX_BELOW_THRESHOLD)
    assert ok(api.get_product(whisky["id"], TERMINAL_ADMIN_HEADERS))["assortment_status"] == "PENDING"

    fx.scanned_itinerary(api, terminal["id"], nationality_code="CN", departure_utc="2026-08-25T13:00:00Z")

    stored = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert stored["scanned_itinerary_count_30d"] == 4
    assert stored["traveler_nationality_mix"]["CN"] == 5000

    listed = ok(api.list_product(whisky["id"], TERMINAL_ADMIN_HEADERS))
    assert listed["assortment_status"] == "LISTED"


def test_the_mix_pool_drops_unscanned_travellers_and_stale_scans(api):
    """An empty pool answers with an empty map, an unscanned traveller never counts, and
    the floored shares of three nationalities sum to 9999.

    PRD 3.2: "The pool is every passenger itinerary whose `departure_terminal_id` is that terminal, whose `scan_status` is either `SCANNED` or `AMENDED`, and whose `scanned_at` falls at or after the instant 30 days before the clock and at or before the clock itself — both ends of the window are inclusive."

    Design: Corner/calculations/nationality_mix_window_excludes_stale_and_unscanned_itineraries
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")

    empty = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert empty["scanned_itinerary_count"] == 0
    assert empty["mix_bps"] == {}

    for nationality, hour in (("CN", "10"), ("IN", "11"), ("JP", "12")):
        fx.scanned_itinerary(
            api,
            terminal["id"],
            nationality_code=nationality,
            departure_utc="2026-09-25T%s:00:00Z" % hour,
        )
    fx.record_itinerary(
        api, terminal["id"], nationality_code="CN", departure_utc="2026-09-25T13:00:00Z"
    )

    mix = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert mix["scanned_itinerary_count"] == 3
    assert mix["mix_bps"] == {"CN": 3333, "IN": 3333, "JP": 3333}
    assert sum(mix["mix_bps"].values()) == 9999
    assert ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["scanned_itinerary_count_30d"] == 3

    fx.advance_clock(api, "2026-09-01T00:00:00Z")

    stale = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert stale["scanned_itinerary_count"] == 0
    assert stale["mix_bps"] == {}
