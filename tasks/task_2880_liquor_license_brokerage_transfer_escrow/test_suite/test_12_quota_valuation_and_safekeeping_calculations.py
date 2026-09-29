"""Derived figures recomputed from scratch: quota counters, comparable sets, chained fees.

Three calculations own their own input sets. The county quota position is
recomputed on every license create, the comparable set is filtered down to the
same county and the priced peers, and a safekeeping extension both doubles its
fee and chains its window off the license rather than off the clock.
"""

from test_helpers import (
    ADMIN,
    api_client,
    assert_instant_equals,
    assert_license,
    assert_safekeeping_filing,
    create_brokerage,
    create_county,
    create_license,
    create_listing,
    create_seller,
    activate_listing,
    decide_safekeeping,
    file_safekeeping,
    preview_valuation,
    read_county,
    read_filing,
    read_license,
    validate_paginated,
)


def test_the_quota_position_is_recomputed_on_every_license_create():
    """Three licenses into an eight-slot county give 3 counted, 5 available, 3750 bps.

    The county's version advances once per recomputation, so a county that has
    absorbed three creates sits at version 4 — proof the position is rebuilt on
    each create rather than only on the first.

    PRD: "A county's quota position is the platform's most widely read derived
    figure, and it is recomputed from scratch whenever a license is added to the
    county's inventory and whenever any license in the county changes status —
    that is, on execution, on the approval cascade, on the refund or forfeiture
    cascade, and on a granted safekeeping decision. Each recomputation writes
    four counters onto the `County` record and advances the county's `version`
    by one."

    PRD: "`quota_licenses_counted` is the number of licenses in the county whose
    `counts_against_quota` flag is set and whose `status` is one of `ACTIVE`,
    `IN_ESCROW`, `SAFEKEEPING` or `TRANSFERRED`. `quota_available` is
    `quota_licenses_total` minus that count, floored at zero so it is never
    negative. `quota_utilization_bps` is the counted figure multiplied by ten
    thousand, divided by `quota_licenses_total`, and rounded half up to an
    integer basis-point value; when `quota_licenses_total` is zero the
    utilization is reported as 10000 rather than attempting the division.
    `escrow_committed_count` is the number of licenses in the county whose
    `status` is `IN_ESCROW`, and unlike the other three it ignores the
    `counts_against_quota` flag entirely — grandfathered non-quota licenses are
    excluded from the counted, available and utilization figures but are still
    counted when they sit in escrow."

    Design: Corner/calculations/county_quota_position_recomputed_on_each_license_create
    """
    county = create_county(quota_licenses_total=8)
    seller = create_seller()
    assert county["quota_licenses_counted"] == 0
    assert county["version"] == 1

    for number in ("Q-1", "Q-2", "Q-3"):
        create_license(
            county["id"], seller["id"],
            license_number=number,
            license_class="CLASS_41_ONSALE_BEER_WINE",
            annual_gross_receipts_cents=20000000,
            last_active_date="2026-07-01",
        )

    position = read_county(county["id"])
    assert position["quota_licenses_counted"] == 3
    assert position["quota_available"] == 5
    assert position["quota_utilization_bps"] == 3750
    assert position["escrow_committed_count"] == 0
    assert position["version"] == 4


def test_the_comparable_set_drops_foreign_counties_and_unpriced_peers():
    """Two priced SON peers price the listing; a NAP sale and an unpriced SON row are out.

    A 100000000-cent comparable sits in another county and a same-county license
    carries no transfer price at all. Neither may enter the set, so the count is
    2 and the median is the mean of 16000000 and 21000000.

    PRD: "The valuation itself is built from a **comparable set** assembled as
    follows. Every license in the same county as the subject, of the same
    `license_class` as the subject, whose `last_transfer_price_cents` is not
    null, whose `status` is one of `ACTIVE`, `IN_ESCROW`, `SAFEKEEPING` or
    `TRANSFERRED`, and which is not the subject license itself, contributes its
    `last_transfer_price_cents` to the set."

    PRD: "Those prices are then sorted into ascending numeric order and their
    count is the comparable count."

    PRD: "When the count is even, the median is the sum of the two middle prices
    divided by two, rounded half up to whole cents."

    PRD: "Its response reports the `listing_id` and `license_id` under
    examination, the `default_valuation_basis` configured on the county, the live
    `comp_count` and `comp_median_cents`, the live `scarcity_bps`, both
    `comparable_sales_price_cents` and `income_multiple_price_cents`, and
    `divergence_cents`, which is exactly the income-multiple price minus the
    comparable-sales price and is therefore signed — negative when the
    comparable market values the license more highly than its own revenue does."

    Design: Corner/calculations/valuation_input_set_excludes_other_counties_and_unpriced_licenses
    """
    sonoma = create_county(county_code="SON", name="Sonoma", quota_licenses_total=100)
    napa = create_county(county_code="NAP", name="Napa", quota_licenses_total=100)
    seller = create_seller()
    brokerage = create_brokerage()

    create_license(sonoma["id"], seller["id"], license_number="SON-COMP-1",
                   annual_gross_receipts_cents=40000000,
                   last_transfer_price_cents=16000000)
    create_license(sonoma["id"], seller["id"], license_number="SON-COMP-2",
                   annual_gross_receipts_cents=40000000,
                   last_transfer_price_cents=21000000)
    create_license(sonoma["id"], seller["id"], license_number="SON-UNPRICED",
                   annual_gross_receipts_cents=40000000)
    create_license(napa["id"], seller["id"], license_number="NAP-COMP-1",
                   annual_gross_receipts_cents=40000000,
                   last_transfer_price_cents=100000000)
    subject = create_license(sonoma["id"], seller["id"], license_number="SON-SUBJ",
                            annual_gross_receipts_cents=120000000)
    listing = create_listing(subject["id"], brokerage["id"])

    preview = preview_valuation(listing["id"])
    assert preview["listing_id"] == listing["id"]
    assert preview["license_id"] == subject["id"]
    assert preview["comp_count"] == 2
    assert preview["comp_median_cents"] == 18500000
    assert preview["scarcity_bps"] == 0
    assert preview["comparable_sales_price_cents"] == 18500000
    assert preview["income_multiple_price_cents"] == 21600000
    assert preview["divergence_cents"] == 3100000

    activated = activate_listing(listing["id"], brokerage["id"])
    assert activated["market_price_cents"] == 18500000
    assert activated["comp_count_at_activation"] == 2
    assert activated["scarcity_bps_at_activation"] == 0
    assert activated["valuation_basis"] == "COMPARABLE_SALES"

    position = read_county(sonoma["id"])
    assert position["quota_licenses_counted"] == 4
    assert position["quota_utilization_bps"] == 400


def test_the_first_extension_doubles_the_fee_and_chains_off_the_license_window():
    """20000 then 40000 cents, and 2027-08-01 -> 2028-02-01 after 9 months clamps to 6.

    The extension begins where the initial window ended rather than at the filing
    instant, even though the logical clock still reads 2026-08-01.

    PRD: "For an initial filing, `extension_index` is 0, `granted_months` is the
    requested figure capped at 12 months, and `effective_from` is the current
    logical instant."

    PRD: "For an extension, `extension_index` is the license's current
    `safekeeping_extensions_count` plus one, `granted_months` is the requested
    figure capped at 6 months, and `effective_from` is the license's current
    `safekeeping_expires_at` — windows are **chained, never overlapped**, so an
    extension begins exactly where the prior window ended rather than at the
    filing instant."

    PRD: "The filing fee doubles with each step: `fee_cents` is a base of 20000
    cents multiplied by two raised to the power of `extension_index`, giving
    20000 cents for an initial filing, 40000 cents for a first extension and
    80000 cents for a second."

    PRD: "Granting stamps `decided_at` with the current logical instant and
    applies the computed window to the license: `safekeeping_expires_at` becomes
    the filing's `expires_at` and `safekeeping_extensions_count` becomes the
    filing's `extension_index`."

    Design: Corner/calculations/safekeeping_extension_fee_doubles_and_window_chains
    """
    county = create_county(quota_licenses_total=100)
    seller = create_seller()
    license_row = create_license(
        county["id"], seller["id"],
        license_number="SAFE-1",
        license_class="CLASS_41_ONSALE_BEER_WINE",
        annual_gross_receipts_cents=20000000,
        last_active_date="2026-02-02",
    )

    initial = file_safekeeping(license_row["id"], license_row["version"],
                              filing_type="INITIAL", requested_months=12,
                              seller_id=seller["id"])
    assert_safekeeping_filing(initial)
    assert initial["extension_index"] == 0
    assert initial["granted_months"] == 12
    assert initial["fee_cents"] == 20000
    assert_instant_equals(initial["effective_from"], "2026-08-01T00:00:00Z",
                          "initial filing effective_from")
    assert_instant_equals(initial["expires_at"], "2027-08-01T00:00:00Z",
                          "initial filing expires_at")
    decide_safekeeping(initial["id"], "GRANT")

    in_safekeeping = read_license(license_row["id"])
    assert_license(in_safekeeping)
    assert in_safekeeping["status"] == "SAFEKEEPING"
    assert_instant_equals(in_safekeeping["safekeeping_expires_at"],
                          "2027-08-01T00:00:00Z", "license safekeeping_expires_at")
    assert in_safekeeping["safekeeping_extensions_count"] == 0

    extension = file_safekeeping(license_row["id"], in_safekeeping["version"],
                                 filing_type="EXTENSION", requested_months=9,
                                 seller_id=seller["id"])
    assert extension["extension_index"] == 1
    assert extension["granted_months"] == 6
    assert extension["fee_cents"] == 40000
    assert_instant_equals(extension["effective_from"], "2027-08-01T00:00:00Z",
                          "extension effective_from")
    assert_instant_equals(extension["expires_at"], "2028-02-01T00:00:00Z",
                          "extension expires_at")
    decide_safekeeping(extension["id"], "GRANT")

    granted = read_filing(extension["id"])
    assert granted["status"] == "GRANTED"
    assert granted["fee_cents"] == 40000

    prolonged = read_license(license_row["id"])
    assert prolonged["status"] == "SAFEKEEPING"
    assert prolonged["safekeeping_extensions_count"] == 1
    assert prolonged["safekeeping_filing_pending"] is False
    assert_instant_equals(prolonged["safekeeping_expires_at"],
                          "2028-02-01T00:00:00Z", "license safekeeping_expires_at")

    rows, meta = validate_paginated(
        api_client.list_safekeeping_filings(ADMIN, params={"license_id": license_row["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["filing_type"] for row in rows} == {"INITIAL", "EXTENSION"}
