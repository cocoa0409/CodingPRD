"""Contract price quote variants, tier breakpoints, and rebooking fee brackets."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_mission,
    create_signed_contract,
    get_contract,
    payload_entry,
    rebook_contract,
    set_clock,
    validate_success,
    api_client,
)
from test_helpers.test_users import make_customer_headers

QUOTE_250_MARGINAL = 126_250_000  # 50x600000 + 150x500000 + 50x425000
QUOTE_250_FLAT = 106_250_000      # 250 x 425000
QUOTE_200_MARGINAL = 105_000_000  # 50x600000 + 150x500000
QUOTE_201_MARGINAL = 105_425_000  # + 1x425000
QUOTE_50_KG = 30_000_000          # 50 x 600000


def _signed_quote(customer_id, pricing_mode, mass_kg):
    contract, _ = create_signed_contract(
        customer_id,
        [payload_entry(payload_name=f"HeavySat-{pricing_mode}", mass_kg=mass_kg, volume_m3=3.0)],
        pricing_mode=pricing_mode,
    )
    return get_contract(contract["id"])


def test_marginal_quote_250kg_waterfalls_across_all_tiers(api):
    """PRD §3.2: "Under `MARGINAL`, the aggregate mass waterfalls across three
    tiers: the first 50 kilograms bill at 600,000 cents per kilogram; the next
    150 kilograms — aggregate mass above 50 kilograms, up to a cumulative ceiling
    of 200 kilograms — bill at 500,000 cents per kilogram; and any mass beyond
    200 kilograms bills at 425,000 cents per kilogram."

    Design: Difficulty/dual_variant_calc/contract_quote_marginal_vs_flat_diverge_at_250kg
    """
    set_clock()
    customer = create_customer()
    contract = _signed_quote(customer["id"], "MARGINAL", 250)
    assert contract["quoted_price_cents"] == QUOTE_250_MARGINAL, (
        f"MARGINAL 250 kg must quote {QUOTE_250_MARGINAL}, got {contract['quoted_price_cents']}"
    )


def test_flat_quote_250kg_bills_entire_mass_at_tier3_rate(api):
    """PRD §3.2: "Under `FLAT`, the entire aggregate bills at the single rate of
    the highest tier reached: 600,000 cents per kilogram when the aggregate is at
    most 50 kilograms, 500,000 cents per kilogram when it is above 50 and at most
    200 kilograms, and 425,000 cents per kilogram when it exceeds 200 kilograms,
    with the single multiplication rounded half up to a whole cent once."

    Design: Difficulty/dual_variant_calc/contract_quote_marginal_vs_flat_diverge_at_250kg
    """
    set_clock()
    customer = create_customer()
    flat = _signed_quote(customer["id"], "FLAT", 250)
    marginal = _signed_quote(customer["id"], "MARGINAL", 250)
    assert flat["quoted_price_cents"] == QUOTE_250_FLAT, (
        f"FLAT 250 kg must quote {QUOTE_250_FLAT}, got {flat['quoted_price_cents']}"
    )
    assert flat["quoted_price_cents"] != marginal["quoted_price_cents"], (
        "MARGINAL and FLAT must diverge on identical 250 kg input"
    )


def test_marginal_quote_at_200kg_fills_tiers_one_and_two_only(api):
    """PRD §3.2: "The tier boundaries belong to the lower tier in both modes: an
    aggregate of exactly 50 kilograms bills entirely within the first tier, and an
    aggregate of exactly 200 kilograms bills across the first two tiers with zero
    mass in the third."

    Design: Difficulty/combinatorial_formula/tiered_marginal_quote_breakpoint_straddle_200_vs_201kg
    """
    set_clock()
    customer = create_customer()
    contract = _signed_quote(customer["id"], "MARGINAL", 200)
    assert contract["quoted_price_cents"] == QUOTE_200_MARGINAL, (
        f"200 kg MARGINAL must quote {QUOTE_200_MARGINAL} (zero tier-3 mass), "
        f"got {contract['quoted_price_cents']}"
    )


def test_marginal_quote_at_201kg_spills_one_kg_into_tier3(api):
    """PRD §3.2: "any mass beyond 200 kilograms bills at 425,000 cents per
    kilogram."

    Design: Difficulty/combinatorial_formula/tiered_marginal_quote_breakpoint_straddle_200_vs_201kg
    """
    set_clock()
    customer = create_customer()
    c200 = _signed_quote(customer["id"], "MARGINAL", 200)
    c201 = _signed_quote(customer["id"], "MARGINAL", 201)
    assert c201["quoted_price_cents"] == QUOTE_201_MARGINAL, (
        f"201 kg MARGINAL must quote {QUOTE_201_MARGINAL}, got {c201['quoted_price_cents']}"
    )
    assert c201["quoted_price_cents"] - c200["quoted_price_cents"] == 425_000, (
        "the 1 kg difference between the contracts adds exactly 425000 cents, the tier-3 rate"
    )


def test_rebooking_consumes_free_right_then_charges_25_percent_bracket(api):
    """PRD §3.7: "Otherwise, if `rebookings_remaining` is greater than zero, the
    rebooking consumes one right: no fee is charged and `rebookings_remaining`
    decreases by 1. Otherwise the fee is a bracketed percentage of
    `quoted_price_cents`, rounded half up to a whole cent: 10 percent when the
    target mission's `window_open_utc` is at least 61 days away, 25 percent when
    it is between 31 and 60 days away inclusive, and 50 percent when it is 30
    days away or fewer — the day count being the whole-day floor of the gap
    between the current logical time and the target mission's `window_open_utc`,
    measured in 86,400-second days."

    Design: Corner/calculations/rebooking_fee_consumes_right_first_then_charges_25_percent_bracket
    """
    set_clock()
    customer = create_customer()
    m2 = create_mission(
        mission_name="Transporter-B2",
        window_open_utc="2026-10-16T00:00:00Z",
        window_close_utc="2026-10-26T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    m3 = create_mission(
        mission_name="Transporter-C3",
        window_open_utc="2026-10-20T00:00:00Z",
        window_close_utc="2026-10-30T00:00:00Z",
        mass_capacity_kg=100,
        volume_capacity_m3=2.0,
    )
    contract, _ = create_signed_contract(
        customer["id"],
        [payload_entry(payload_name="PL50", mass_kg=50, volume_m3=1.0)],
    )
    assert contract["quoted_price_cents"] == QUOTE_50_KG
    assert contract["rebookings_remaining"] == 1

    # Rebook 1 (clock 2026-09-01): consumes the free right, no fee.
    after1 = rebook_contract(contract["id"], customer["id"], m2["id"], contract["version"])
    assert after1["rebookings_remaining"] == 0
    assert after1["total_rebooking_fees_cents"] == 0
    assert after1["target_mission_id"] == m2["id"]

    # Rebook 2: rights exhausted; 49 days to 2026-10-20 -> 25% bracket.
    after2 = rebook_contract(contract["id"], customer["id"], m3["id"], after1["version"])
    assert after2["total_rebooking_fees_cents"] == 7_500_000, (
        f"25% of 30000000 must be 7500000, got {after2['total_rebooking_fees_cents']}"
    )
    assert after2["rebookings_remaining"] == 0
    assert after2["target_mission_id"] == m3["id"]
    assert after2["quoted_price_cents"] == QUOTE_50_KG, (
        "rebooking never re-quotes the contract"
    )
