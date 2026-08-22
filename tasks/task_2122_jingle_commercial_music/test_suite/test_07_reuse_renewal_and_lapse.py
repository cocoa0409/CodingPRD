"""Re-use extensions into new markets, the renewal loop and the lapse sweep."""
from test_helpers import (
    ApiErrorId,
    RIGHTS_ADMIN_ISSUER_ID,
    assert_instant_equals,
    assert_reuse_extension,
    create_reuse_extension,
    get_license_deal,
    make_producer_headers,
    make_rights_admin_headers,
    set_clock,
    setup_engagement_in_production,
    setup_license_deal,
    validate_error,
    validate_paginated,
    validate_success,
)


def _active_term_deal(target_markets=("US_NATIONAL",), market_codes=("US_NATIONAL",),
                      term_months=12, creative_fee_cents=800_000):
    """An ACTIVE TERM licence issued at the 2026-09-01 logical clock."""
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(
        budget_cents=4_000_000, target_markets=list(target_markets),
        required_lengths=[30], demo_fee_cents=100_000)
    setup_license_deal(env, stage="ACTIVE", license_structure="TERM",
                       term_months=term_months, market_codes=list(market_codes),
                       creative_fee_cents=creative_fee_cents)
    return env


def test_reuse_fee_bands_the_admin_percentage_on_the_pre_admin_subtotal(api):
    """PRD §3.7: "Step one resolves `market_tier` from the requested code through the
    tier map of §2.9 and sets `reuse_base_cents` to that tier's per-market charge
    multiplied by 60 percent, rounded half-up to whole cents."
    PRD §3.7: "Step two selects `admin_pct` by banding **`reuse_base_cents`, the
    pre-administration subtotal**: a base of 100,000 cents or less takes 10 percent, a
    base above 100,000 cents and up to and including 200,000 cents takes 7 percent, and
    a base strictly above 200,000 cents takes 5 percent."
    PRD §3.7: "Worked through for a `TIER_1` market: the base is 195,000 cents, which
    lands in the 7 percent band, giving an administration fee of 13,650 cents and a
    total of 208,650 cents — banding on the total instead would have picked the 5
    percent band and produced a different, incorrect number."

    Design: Difficulty/combinatorial_formula/reuse_admin_band_keyed_on_pre_admin_subtotal_not_on_total
    """
    env = _active_term_deal(target_markets=("US_NATIONAL", "US_REGIONAL"))
    deal_version = get_license_deal(env["deal"]["id"])["version"]

    extension = validate_success(api.create_reuse_extension(
        env["deal"]["id"],
        {"market_code": "DIGITAL_GLOBAL", "expected_license_deal_version": deal_version},
        make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)), 201)
    assert_reuse_extension(extension)
    assert extension["market_tier"] == "TIER_1", (
        f"DIGITAL_GLOBAL is a TIER_1 market; got {extension['market_tier']}")
    assert extension["reuse_base_cents"] == 195_000, (
        f"round(325000 * 0.60) = 195000; got {extension['reuse_base_cents']}")
    assert extension["admin_pct"] == 7, (
        "195000 sits above 100000 and at or below 200000, so the band is 7 percent; "
        f"got {extension['admin_pct']}")
    assert extension["admin_fee_cents"] == 13_650, (
        f"round(195000 * 0.07) = 13650; got {extension['admin_fee_cents']}")
    assert extension["reuse_total_cents"] == 208_650, (
        f"195000 + 13650 = 208650; got {extension['reuse_total_cents']}")
    assert extension["reuse_total_cents"] != 204_750, (
        "204750 is the forbidden band-on-the-total answer")


def test_reuse_extension_recomputes_the_invoice_over_the_enlarged_market_set(api):
    """PRD §3.7: "Once the fee is recorded, the new code is appended to the deal's
    `market_codes`, the deal's `version` increases by one, and
    `license_fee_invoiced_cents` is recomputed over the enlarged granted set."
    PRD §3.6: "The invoice is priced over the deal's own `market_codes` **as they stand
    at that instant**, including every market a re-use extension has since added, and it
    is written at issuance and rewritten after each re-use extension and at each
    renewal."

    Design: Difficulty/combinatorial_formula/reuse_admin_band_keyed_on_pre_admin_subtotal_not_on_total
    """
    env = _active_term_deal(target_markets=("US_NATIONAL", "US_REGIONAL"))
    before = get_license_deal(env["deal"]["id"])
    assert before["license_fee_invoiced_cents"] == 645_000, (
        f"Expected the issued invoice 645000, got {before['license_fee_invoiced_cents']}")

    create_reuse_extension(env["deal"]["id"], "DIGITAL_GLOBAL",
                           expected_license_deal_version=before["version"])

    after = get_license_deal(env["deal"]["id"])
    assert after["license_fee_invoiced_cents"] == 970_000, (
        "Structure 320000 plus two TIER_1 markets at 325000 each is 970000; "
        f"got {after['license_fee_invoiced_cents']}")
    assert after["market_codes"] == ["US_NATIONAL", "DIGITAL_GLOBAL"], (
        f"The new code must be appended; got {after['market_codes']}")
    assert after["version"] == before["version"] + 1, (
        f"Expected version {before['version'] + 1}, got {after['version']}")


def test_reuse_extension_for_an_already_granted_market_is_rejected(api):
    """PRD §3.7: "The code must be one of the seven recognised territories and must not
    already appear in the deal's `market_codes`, otherwise the request is refused with
    `ERR_MARKET_ALREADY_LICENSED`."

    Design: Corner/validations/corner_reuse_extension_for_an_already_granted_market_is_rejected
    """
    env = _active_term_deal()
    deal_version = get_license_deal(env["deal"]["id"])["version"]

    validate_error(
        api.create_reuse_extension(
            env["deal"]["id"],
            {"market_code": "US_NATIONAL", "expected_license_deal_version": deal_version},
            make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_MARKET_ALREADY_LICENSED.value, 409)

    _, meta = validate_paginated(api.list_reuse_extensions(
        env["deal"]["id"], make_producer_headers()))
    assert meta["total_count"] == 0, (
        f"No extension may be stored; got {meta['total_count']}")
    deal = get_license_deal(env["deal"]["id"])
    assert deal["license_fee_invoiced_cents"] == 645_000, (
        f"The invoice must be untouched; got {deal['license_fee_invoiced_cents']}")
    assert deal["market_codes"] == ["US_NATIONAL"], (
        f"The granted set must be untouched; got {deal['market_codes']}")


def test_stale_licence_version_blocks_a_second_reuse_extension(api):
    """PRD §2.8: "Adding a re-use extension (`POST /license-deals/{id}/reuse-extensions`)
    requires a non-optional `expected_license_deal_version` field carrying the client's
    last observed `version` of the target licence deal."
    PRD §2.8: "If `expected_license_deal_version` does not equal the deal's current
    `version`, the request is rejected with `ERR_STALE_LICENSE_DEAL_VERSION` and HTTP
    412."
    PRD §2.8: "A successful extension increments the licence deal's `version` by 1."

    Design: Corner/cross_cutting_layers/corner_stale_license_deal_version_on_a_second_reuse_extension_is_rejected
    """
    env = _active_term_deal()
    observed_version = get_license_deal(env["deal"]["id"])["version"]
    first = create_reuse_extension(env["deal"]["id"], "EU_NATIONAL",
                                   expected_license_deal_version=observed_version)
    assert first["reuse_base_cents"] == 90_000, (
        f"round(150000 * 0.60) = 90000; got {first['reuse_base_cents']}")
    assert first["admin_pct"] == 10, (
        f"A base of 100000 or less takes 10 percent; got {first['admin_pct']}")
    assert first["reuse_total_cents"] == 99_000, (
        f"90000 + 9000 = 99000; got {first['reuse_total_cents']}")

    validate_error(
        api.create_reuse_extension(
            env["deal"]["id"],
            {"market_code": "CA_NATIONAL", "expected_license_deal_version": observed_version},
            make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_STALE_LICENSE_DEAL_VERSION.value, 412)

    _, meta = validate_paginated(api.list_reuse_extensions(
        env["deal"]["id"], make_producer_headers()))
    assert meta["total_count"] == 1, (
        f"Only the first extension may exist; got {meta['total_count']}")
    deal = get_license_deal(env["deal"]["id"])
    assert deal["license_fee_invoiced_cents"] == 795_000, (
        "Structure 320000 plus TIER_1 325000 plus TIER_2 150000 is 795000; "
        f"got {deal['license_fee_invoiced_cents']}")
    assert deal["market_codes"] == ["US_NATIONAL", "EU_NATIONAL"], (
        f"Expected the first extension's market appended; got {deal['market_codes']}")


def test_clock_sweep_moves_a_term_deal_to_renewal_due_then_lapsed(api):
    """PRD §3.7: "Each `ACTIVE` deal whose `license_structure` is `TERM` and whose
    `effective_end_utc` less the thirty-day notice period falls at or before the new
    clock moves `ACTIVE → RENEWAL_DUE`; then, in that same sweep, each `RENEWAL_DUE`
    deal whose `effective_end_utc` falls at or before the new clock moves
    `RENEWAL_DUE → LAPSED`."
    PRD §3.7: "The response reports the resulting `current_utc` along with
    `licenses_moved_to_renewal_due` and `licenses_lapsed` counting the deals moved on
    each edge."

    Design: Corner/state_machines/corner_clock_sweep_moves_term_deal_to_renewal_due_then_lapsed
    """
    env = _active_term_deal()
    deal = get_license_deal(env["deal"]["id"])
    assert_instant_equals(deal["effective_end_utc"], "2027-08-27T00:00:00Z",
                          "effective_end_utc")

    first_sweep = validate_success(api.set_clock(
        {"to_iso8601": "2027-07-28T00:00:00Z"},
        make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert first_sweep["licenses_moved_to_renewal_due"] == 1, (
        "Exactly thirty days before the end the deal becomes renewable; "
        f"got {first_sweep['licenses_moved_to_renewal_due']}")
    assert get_license_deal(deal["id"])["status"] == "RENEWAL_DUE"

    second_sweep = validate_success(api.set_clock(
        {"to_iso8601": "2027-08-27T00:00:00Z"},
        make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert second_sweep["licenses_lapsed"] == 1, (
        f"The deal must lapse on its end instant; got {second_sweep['licenses_lapsed']}")
    assert get_license_deal(deal["id"])["status"] == "LAPSED", (
        "Expected LAPSED after the clock reached effective_end_utc")


def test_renewal_rolls_the_window_and_charges_the_eighty_five_percent_uplift(api):
    """PRD §3.7: "The price of a renewal escalates with each round: the uplift
    percentage is the lesser of 120 percent and the sum of a base of 85 percent plus 10
    percentage points for each renewal already completed, where the deal's
    `renewal_count` is read **before** it is incremented — so the first renewal charges
    85 percent, the second 95 percent, the third 105 percent, and every renewal from the
    fourth onward is capped at 120 percent."
    PRD §3.7: "`renewal_fee_cents` is set to `license_fee_invoiced_cents` — read before
    any recomputation — multiplied by that uplift percentage and rounded half-up to
    whole cents."
    PRD §3.7: "Only then does `renewal_count` increase by one, `effective_start_utc`
    move to the logical clock, `effective_end_utc` move to the logical clock advanced by
    `term_months` multiplied by thirty days, and `license_fee_invoiced_cents` get
    recomputed over the unchanged granted market set."

    Design: Corner/state_machines/corner_renew_rolls_the_window_and_charges_the_eighty_five_percent_uplift
    """
    env = _active_term_deal()
    set_clock("2027-07-28T00:00:00Z")
    assert get_license_deal(env["deal"]["id"])["status"] == "RENEWAL_DUE"

    renewed = validate_success(api.renew_license_deal(
        env["deal"]["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert renewed["status"] == "ACTIVE", f"Expected ACTIVE, got {renewed['status']}"
    assert renewed["renewal_count"] == 1, (
        f"Expected renewal_count 1, got {renewed['renewal_count']}")
    assert renewed["renewal_fee_cents"] == 548_250, (
        f"round(645000 * 0.85) = 548250; got {renewed['renewal_fee_cents']}")
    assert renewed["license_fee_invoiced_cents"] == 645_000, (
        "The unchanged market set reprices to the same 645000; "
        f"got {renewed['license_fee_invoiced_cents']}")
    assert_instant_equals(renewed["effective_start_utc"], "2027-07-28T00:00:00Z",
                          "effective_start_utc")
    assert_instant_equals(renewed["effective_end_utc"], "2028-07-22T00:00:00Z",
                          "effective_end_utc")


def test_buyout_deal_never_enters_renewal_due(api):
    """PRD §3.6: "On success the acting operator is recorded in `activated_by_user_id`,
    `effective_start_utc` is stamped from the logical clock, and `effective_end_utc` is
    set to `effective_start_utc` advanced by `term_months` multiplied by thirty days for
    a `TERM` grant, or left null for a `BUYOUT` grant, which is perpetual."
    PRD §3.7: "Each `ACTIVE` deal whose `license_structure` is `TERM` and whose
    `effective_end_utc` less the thirty-day notice period falls at or before the new
    clock moves `ACTIVE → RENEWAL_DUE`; then, in that same sweep, each `RENEWAL_DUE`
    deal whose `effective_end_utc` falls at or before the new clock moves
    `RENEWAL_DUE → LAPSED`."
    PRD §3.6: "For a `BUYOUT` deal the structure component is `creative_fee_cents`
    multiplied by 2.5 and rounded half-up to whole cents."

    Design: Corner/state_machines/corner_buyout_deal_never_enters_renewal_due
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    deal = setup_license_deal(env, stage="ACTIVE", license_structure="BUYOUT",
                              market_codes=["US_NATIONAL"], creative_fee_cents=800_000)
    assert deal["effective_end_utc"] is None, (
        f"A BUYOUT grant is perpetual; got {deal['effective_end_utc']}")

    sweep = validate_success(api.set_clock(
        {"to_iso8601": "2029-09-01T00:00:00Z"},
        make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert sweep["licenses_moved_to_renewal_due"] == 0, (
        f"A BUYOUT deal can never become renewable; got {sweep['licenses_moved_to_renewal_due']}")
    assert sweep["licenses_lapsed"] == 0, (
        f"A BUYOUT deal can never lapse; got {sweep['licenses_lapsed']}")

    after = get_license_deal(deal["id"])
    assert after["status"] == "ACTIVE", f"Expected ACTIVE three years on, got {after['status']}"
    assert after["effective_end_utc"] is None
    assert after["license_fee_invoiced_cents"] == 2_325_000, (
        "round(800000 * 2.5) plus the TIER_1 325000 is 2325000; "
        f"got {after['license_fee_invoiced_cents']}")
