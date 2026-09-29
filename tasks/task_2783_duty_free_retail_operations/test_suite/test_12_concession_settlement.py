"""Concession settlement: the mid-period projection, the close and the marketing tiers."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_GRANT_NOT_ACTIVE,
    ERR_PERIOD_NOT_ENDED,
    ERR_PRODUCT_NOT_PENDING,
)
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    ok,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import TERMINAL_ADMIN_HEADERS

PERIOD_END = "2026-09-01T00:00:00Z"


def _picked_up_liquor_turnover(api):
    """A fully exempt three-bottle basket handed over, worth 24000 cents of turnover."""
    estate = fx.liquor_estate(api, allowance_units=3)
    basket = fx.till_ready_basket(
        api, estate, qty=3, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )
    fx.clear_basket(api, basket.sale["id"])
    picked = fx.hand_over(api, basket.sale["id"])
    assert picked["fulfillment_status"] == "PICKED_UP"
    assert picked["gross_amount_cents"] == 24000
    return estate


def _picked_up_watch_turnover(api, minimum_guarantee_cents=2000000):
    """A five-watch basket handed over, worth 100000 cents against a high guarantee."""
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    fx.stocked_ledger(api, terminal["id"], watch["id"], 20)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="ELECTRONICS",
        allowance_units=5,
        advisory_text="Australia: AUD 900 general goods allowance per adult.",
    )
    agreement = fx.active_agreement(
        api,
        terminal["id"],
        rent_pct_bps=1000,
        minimum_guarantee_cents=minimum_guarantee_cents,
    )
    itinerary = fx.scanned_itinerary(api, terminal["id"], departure_utc="2026-08-25T10:00:00Z")
    sale = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, sale["id"], watch["id"], 5)
    fx.clear_basket(api, sale["id"])
    picked = fx.hand_over(api, sale["id"])
    assert picked["gross_amount_cents"] == 100000
    return terminal, agreement


def test_the_mid_period_projection_prorates_the_guarantee_and_reports_the_percentage_basis(api):
    """Five days into a thirty-one day period the guarantee is worth only 1613 cents, which
    the 2880 cents of percentage rent beats.

    PRD 3.10: "The minimum guarantee is prorated across that fraction of the period — `minimum_guarantee_cents` multiplied by `elapsed_days`, divided by `period_days`, rounded half up to whole cents — and reported as `prorated_minimum_guarantee_cents`."

    Design: Difficulty/dual_variant_calc/concession_rent_provisional_proration_versus_final_full_minimum_guarantee
    """
    estate = _picked_up_liquor_turnover(api)
    fx.advance_clock(api, "2026-08-05T00:00:00Z")

    projection = ok(api.get_rent_projection(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))

    assert projection["gross_sales_cents"] == 24000
    assert projection["percentage_rent_cents"] == 2880
    assert projection["period_days"] == 31
    assert projection["elapsed_days"] == 5
    assert projection["prorated_minimum_guarantee_cents"] == 1613
    assert projection["provisional_rent_cents"] == 2880
    assert projection["rent_basis"] == "PERCENTAGE"

    stored = ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert stored["status"] == "ACTIVE"
    assert stored["percentage_rent_cents"] == 2880
    assert_nulls(stored, "final_rent_cents", "closed_at")


def test_the_close_drops_the_proration_and_flips_the_basis_on_the_same_turnover(api):
    """No input field changes between the projection and the close, yet the settlement pins
    the rent to the full 10000-cent guarantee and reports the other basis.

    PRD 3.10: "The final rent, written to `final_rent_cents`, is the greater of `percentage_rent_cents` and the **full** `minimum_guarantee_cents`, with `rent_basis` re-derived as `PERCENTAGE` when `percentage_rent_cents` is greater than or equal to the full `minimum_guarantee_cents` and `MINIMUM_GUARANTEE` otherwise."

    Design: Difficulty/dual_variant_calc/concession_rent_provisional_proration_versus_final_full_minimum_guarantee
    """
    estate = _picked_up_liquor_turnover(api)
    fx.advance_clock(api, "2026-08-05T00:00:00Z")

    projection = ok(api.get_rent_projection(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert projection["rent_basis"] == "PERCENTAGE"
    assert projection["provisional_rent_cents"] == 2880

    fx.advance_clock(api, PERIOD_END)
    closed = fx.close_agreement(api, estate.agreement["id"])

    assert closed["status"] == "CLOSED"
    assert closed["gross_sales_cents"] == 24000
    assert closed["percentage_rent_cents"] == 2880
    assert closed["final_rent_cents"] == 10000
    assert closed["rent_basis"] == "MINIMUM_GUARANTEE"
    assert closed["marketing_credit_cents"] == 100
    assert closed["net_rent_cents"] == 9900
    assert_instant(closed["closed_at"], PERIOD_END, "closed_at")


def test_the_marketing_tier_is_keyed_on_the_gross_rent_at_the_tier_boundary(api):
    """A final rent sitting exactly on the 2,000,000-cent floor earns 250 basis points, and
    the credit is not re-keyed on the 1,950,000 cents left after it.

    PRD 3.10: "Re-evaluating the tier against `net_rent_cents` after the subtraction is forbidden, however circular the dependency looks from the outside."

    Design: Difficulty/combinatorial_formula/marketing_credit_tier_keyed_on_gross_rent_not_net_rent
    """
    _terminal, agreement = _picked_up_watch_turnover(api)
    fx.advance_clock(api, PERIOD_END)

    closed = fx.close_agreement(api, agreement["id"])

    assert closed["gross_sales_cents"] == 100000
    assert closed["percentage_rent_cents"] == 10000
    assert closed["final_rent_cents"] == 2000000
    assert closed["rent_basis"] == "MINIMUM_GUARANTEE"
    assert closed["marketing_credit_cents"] == 50000
    assert closed["marketing_credit_cents"] != 19500
    assert closed["net_rent_cents"] == 1950000
    assert closed["status"] == "CLOSED"


def test_one_cent_below_the_boundary_earns_the_lowest_tier_instead(api):
    """The tier floors are inclusive, so a final rent of 1999999 cents falls to 100 basis
    points and its credit rounds half up to 20000.

    PRD 3.10: "`marketing_credit_cents` is `final_rent_cents` multiplied by the tier rate, divided by 10000 and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/marketing_credit_tier_keyed_on_gross_rent_not_net_rent
    """
    _terminal, agreement = _picked_up_watch_turnover(api, minimum_guarantee_cents=1999999)
    fx.advance_clock(api, PERIOD_END)

    closed = fx.close_agreement(api, agreement["id"])

    assert closed["final_rent_cents"] == 1999999
    assert closed["rent_basis"] == "MINIMUM_GUARANTEE"
    assert closed["marketing_credit_cents"] == 20000
    assert closed["marketing_credit_cents"] != 49999
    assert closed["net_rent_cents"] == 1979999


def _empty_active_agreement(api):
    """A terminal whose 2026-08 agreement is ACTIVE and has taken no turnover at all."""
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    agreement = fx.active_agreement(api, terminal["id"])
    assert agreement["gross_sales_cents"] == 0
    assert agreement["percentage_rent_cents"] == 0
    return terminal, agreement


def test_the_opening_day_counts_as_one_elapsed_day_and_the_period_cannot_close_early(api):
    """At the very first instant of the period the elapsed count is clamped up to one day,
    which is worth 323 cents of prorated guarantee, and the period refuses to settle.

    PRD 3.10: "It then establishes how much of the period has run: the difference between the logical clock and `period_start_utc` in seconds, divided by 86400 and floored, plus 1, so that the opening day counts as one elapsed day; that figure is raised to a minimum of 1 and then capped at `period_days`, and is reported as `elapsed_days`."

    Design: Difficulty/boundary_precision_check/zero_sales_period_close_floors_rent_at_minimum_guarantee_with_single_elapsed_day
    """
    _terminal, agreement = _empty_active_agreement(api)

    projection = ok(api.get_rent_projection(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert projection["gross_sales_cents"] == 0
    assert projection["period_days"] == 31
    assert projection["elapsed_days"] == 1
    assert projection["percentage_rent_cents"] == 0
    assert projection["prorated_minimum_guarantee_cents"] == 323
    assert projection["provisional_rent_cents"] == 323
    assert projection["rent_basis"] == "MINIMUM_GUARANTEE"

    validate_error(
        api.close_agreement_period(agreement["id"], TERMINAL_ADMIN_HEADERS), ERR_PERIOD_NOT_ENDED
    )

    stored = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert stored["status"] == "ACTIVE"
    assert_nulls(stored, "final_rent_cents", "marketing_credit_cents", "net_rent_cents", "closed_at")


def test_a_period_without_any_sales_settles_at_the_full_guarantee(api):
    """With no turnover the percentage rent is zero, so the floor is the whole rent and the
    lowest marketing tier applies to it.

    PRD 3.10: "a final rent of at least 5,000,000 cents (50,000 in major currency units) earns 400 basis points, a final rent of at least 2,000,000 cents (20,000 in major currency units) but below the higher floor earns 250 basis points, and anything below that earns 100 basis points, each tier boundary being inclusive."

    Design: Difficulty/boundary_precision_check/zero_sales_period_close_floors_rent_at_minimum_guarantee_with_single_elapsed_day
    """
    _terminal, agreement = _empty_active_agreement(api)
    version_when_active = agreement["version"]

    validate_error(
        api.close_agreement_period(agreement["id"], TERMINAL_ADMIN_HEADERS), ERR_PERIOD_NOT_ENDED
    )

    fx.advance_clock(api, PERIOD_END)
    closed = fx.close_agreement(api, agreement["id"])

    assert closed["status"] == "CLOSED"
    assert closed["gross_sales_cents"] == 0
    assert closed["percentage_rent_cents"] == 0
    assert closed["final_rent_cents"] == 10000
    assert closed["rent_basis"] == "MINIMUM_GUARANTEE"
    assert closed["marketing_credit_cents"] == 100
    assert closed["net_rent_cents"] == 9900
    assert closed["version"] == version_when_active + 1
    assert_instant(closed["closed_at"], PERIOD_END, "closed_at")


def test_the_projection_and_the_mix_read_leave_their_parents_untouched(api):
    """Both computed reads answer the same body twice over and neither bumps a version,
    writes a final rent nor closes the period.

    PRD 3.10: "The projection is computed at the current logical clock and mutates nothing."

    Design: Corner/endpoints/rent_projection_and_nationality_mix_reads_never_mutate_state
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    fx.scanned_itinerary(api, terminal["id"], nationality_code="CN", departure_utc="2026-08-25T10:00:00Z")
    agreement = fx.active_agreement(api, terminal["id"])

    agreement_version = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))["version"]
    terminal_version = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["version"]

    first_projection = ok(api.get_rent_projection(agreement["id"], TERMINAL_ADMIN_HEADERS))
    second_projection = ok(api.get_rent_projection(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert first_projection == second_projection
    assert first_projection["provisional_rent_cents"] == 323
    assert first_projection["rent_basis"] == "MINIMUM_GUARANTEE"

    first_mix = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    second_mix = ok(api.get_nationality_mix(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert first_mix == second_mix
    assert first_mix["scanned_itinerary_count"] == 1
    assert first_mix["mix_bps"]["CN"] == 10000

    stored_agreement = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_agreement["version"] == agreement_version
    assert stored_agreement["status"] == "ACTIVE"
    assert stored_agreement["percentage_rent_cents"] == 0
    assert_nulls(stored_agreement, "final_rent_cents", "closed_at")

    stored_terminal = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_terminal["version"] == terminal_version


def test_a_second_listing_and_a_second_revocation_are_refused_without_re_stamping(api):
    """Neither lifecycle trigger is idempotent, and the refusals leave the first call's
    timestamps and versions exactly where they were.

    PRD 3.2: "The product must still be `PENDING`, otherwise `ERR_PRODUCT_NOT_PENDING`."

    Design: Corner/state_machines/repeating_a_completed_lifecycle_trigger_is_refused_per_entity
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
    )
    grant = fx.grant_exclusivity(
        api,
        brand["id"],
        terminal["id"],
        category="LIQUOR",
        scope="CATEGORY_PREFERRED",
        effective_from=CLOCK_START,
        effective_to=PERIOD_END,
    )

    listed = ok(api.list_product(whisky["id"], TERMINAL_ADMIN_HEADERS))
    assert listed["assortment_status"] == "LISTED"
    assert_instant(listed["listed_at"], CLOCK_START, "listed_at")
    revoked = ok(api.revoke_grant(grant["id"], TERMINAL_ADMIN_HEADERS))
    assert revoked["status"] == "REVOKED"
    assert_instant(revoked["revoked_at"], CLOCK_START, "revoked_at")

    fx.advance_clock(api, "2026-08-02T00:00:00Z")

    validate_error(api.list_product(whisky["id"], TERMINAL_ADMIN_HEADERS), ERR_PRODUCT_NOT_PENDING)
    validate_error(api.revoke_grant(grant["id"], TERMINAL_ADMIN_HEADERS), ERR_GRANT_NOT_ACTIVE)

    stored_product = ok(api.get_product(whisky["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_product["assortment_status"] == "LISTED"
    assert_instant(stored_product["listed_at"], CLOCK_START, "listed_at")
    assert stored_product["version"] == listed["version"]

    stored_grant = ok(api.get_grant(grant["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_grant["status"] == "REVOKED"
    assert_instant(stored_grant["revoked_at"], CLOCK_START, "revoked_at")
    assert stored_grant["version"] == revoked["version"]
