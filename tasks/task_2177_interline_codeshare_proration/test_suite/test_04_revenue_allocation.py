"""Coupon-level revenue allocation: the two run variants, the waterfall and its rounding."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_fare_conservation,
    assert_proration_run,
    assert_specificity_score,
    create_factor_payload,
    fly,
    make_accountant_headers,
    new_ticket,
    prorate_payload,
    read_agreement,
    read_coupon,
    read_ticket,
    run_proration,
    set_clock,
    setup_agreement,
    setup_ticket_with_coupons,
    setup_three_carriers,
    setup_three_sector_ticket,
    setup_two_carriers,
    ticket_version,
    validate_error,
    validate_paginated,
    validate_success,
    void_allocation,
    void_coupon,
)

SPA_FLAT_FACTOR = create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=12000)


def _three_sector_scenario(agreement_type=None, factors=(), activate=True, suspend=False,
                           fly_all=True, ticket_number="0011234567890"):
    """AA/BB/CC, an optional bilateral agreement on the LHR-CDG sector, and the canonical
    three-sector ticket (JFK-LHR/AA/ECONOMY/3451, LHR-CDG/BB/ECONOMY/216, CDG-FCO/CC/BUSINESS/693)."""
    aa, bb, cc = setup_three_carriers()
    agreement = None
    created_factors = []
    if agreement_type is not None:
        agreement, created_factors = setup_agreement(
            aa["id"],
            bb["id"],
            agreement_type,
            factors=factors,
            activate=activate,
            suspend_after_activate=suspend,
        )
    ticket, coupons = setup_three_sector_ticket(
        aa["id"], bb["id"], cc["id"], ticket_number=ticket_number, fly_all=fly_all
    )
    return {
        "aa": aa, "bb": bb, "cc": cc,
        "agreement": agreement, "factors": created_factors,
        "ticket": ticket, "coupons": coupons,
    }


# --------------------------------------------------------------------------- #
# The two variants over one identical ticket
# --------------------------------------------------------------------------- #
def test_provisional_run_ignores_the_special_prorate_agreement(api):
    """PRD §3.5: "`PROVISIONAL` is the straight-rate settlement taken at ticketing time,
    before any sector has flown: its input set is the coupons whose `coupon_status` is `OPEN`
    or `FLOWN`, and it skips special prorate agreements entirely — even active ones — so
    nothing is taken off the top and every included coupon settles on `STRAIGHT_RATE` with a
    weight multiplier of exactly 10000 basis points."
    PRD §3.5: "Each one's `weight_units` is its `tpm_miles`, multiplied by its cabin's weight
    in basis points, multiplied by the applicable factor in basis points, divided by 10000,
    and rounded half up. The cabin weights are 10000 basis points for `ECONOMY`, 12500 for
    `PREMIUM`, 16000 for `BUSINESS` and 20000 for `FIRST`, so a business-class mile counts for
    1.6 economy miles and a first-class mile for double."

    Design: Difficulty/dual_variant_calc/provisional_straight_rate_vs_final_spa_allocation
    """
    set_clock("2026-08-02T00:00:00Z")
    ctx = _three_sector_scenario("SPA_FLAT", [SPA_FLAT_FACTOR], fly_all=False)
    c1, c2, c3 = ctx["coupons"]

    run_proration(ctx["ticket"]["id"], ctx["aa"]["id"], "PROVISIONAL")

    assert read_coupon(c1["id"])["allocated_amount_minor"] == 72260
    assert read_coupon(c2["id"])["allocated_amount_minor"] == 4523, (
        "the SPA_FLAT agreement is invisible to a PROVISIONAL run"
    )
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 23217
    for coupon in (c1, c2, c3):
        assert read_coupon(coupon["id"])["allocation_basis"] == "STRAIGHT_RATE"


def test_final_run_takes_the_spa_flat_amount_off_the_top(api):
    """PRD §3.5: "A coupon whose matched agreement has an `agreement_type` of `SPA_FLAT` takes
    the factor's `flat_amount_minor` as its `allocated_amount_minor` and records an
    `allocation_basis` of `SPA_FLAT`."
    PRD §3.5: "Every such amount accumulates into `spa_total_minor`, which is always zero for
    a `PROVISIONAL` run. If `spa_total_minor` ends up larger than the pool, the whole run is
    refused with `ERR_SPA_OVERALLOCATION` (HTTP 422). What remains, the pool less
    `spa_total_minor`, is recorded as `straight_rate_pool_minor` and is what the remaining
    coupons share."
    PRD §3.5: "The ticket's `last_run_type` is set to the variant just executed, its
    `proration_status` moves to `PROVISIONAL` or `FINAL` accordingly, and its `version` bumps."

    Design: Difficulty/dual_variant_calc/provisional_straight_rate_vs_final_spa_allocation
    """
    set_clock("2026-08-02T00:00:00Z")
    ctx = _three_sector_scenario("SPA_FLAT", [SPA_FLAT_FACTOR], fly_all=False)
    c1, c2, c3 = ctx["coupons"]
    run_proration(ctx["ticket"]["id"], ctx["aa"]["id"], "PROVISIONAL")
    for coupon in (c1, c2, c3):
        fly(coupon["id"], ctx["aa"]["id"])

    run = validate_success(
        api.prorate_ticket(
            ctx["ticket"]["id"],
            prorate_payload("FINAL", ticket_version(ctx["ticket"]["id"])),
            make_accountant_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert_proration_run(run)
    assert run["spa_total_minor"] == 12000
    assert run["straight_rate_pool_minor"] == 88000
    assert run["total_weight_units"] == 45598000

    assert read_coupon(c2["id"])["allocated_amount_minor"] == 12000
    assert read_coupon(c2["id"])["allocation_basis"] == "SPA_FLAT"
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 66601
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 21399
    assert read_coupon(c1["id"])["allocation_basis"] == "STRAIGHT_RATE"
    assert read_coupon(c3["id"])["allocation_basis"] == "STRAIGHT_RATE"

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["proration_status"] == "FINAL"
    assert ticket["unallocated_residual_minor"] == 0


# --------------------------------------------------------------------------- #
# Per-coupon rounding, then the residual
# --------------------------------------------------------------------------- #
def _rounding_scenario():
    aa, bb, cc = setup_three_carriers()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": aa["id"], "origin": "JFK", "destination": "BOS",
             "class_of_service": "ECONOMY", "tpm_miles": 100},
            {"operating_carrier_id": bb["id"], "origin": "BOS", "destination": "YUL",
             "class_of_service": "ECONOMY", "tpm_miles": 100},
            {"operating_carrier_id": cc["id"], "origin": "YUL", "destination": "CDG",
             "class_of_service": "BUSINESS", "tpm_miles": 333},
        ],
        ticket_number="0013000000001",
    )
    return aa, ticket, coupons


def test_each_coupon_share_is_rounded_on_its_own_before_any_summing(api):
    """PRD §3.5: "Walking the sharing coupons in ascending `coupon_number`, each coupon's
    `allocated_amount_minor` is `straight_rate_pool_minor` multiplied by that coupon's
    `weight_units`, divided by `total_weight_units`, and rounded half up **on its own, before
    any summing**, with `allocation_basis` set to `STRAIGHT_RATE`."
    PRD §3.5: "Each one's `weight_units` is its `tpm_miles`, multiplied by its cabin's weight
    in basis points, multiplied by the applicable factor in basis points, divided by 10000,
    and rounded half up. The cabin weights are 10000 basis points for `ECONOMY`, 12500 for
    `PREMIUM`, 16000 for `BUSINESS` and 20000 for `FIRST`, so a business-class mile counts for
    1.6 economy miles and a first-class mile for double."

    Design: Difficulty/combinatorial_formula/round_per_coupon_then_grant_residual_to_heaviest
    """
    set_clock("2026-08-02T00:00:00Z")
    aa, ticket, coupons = _rounding_scenario()
    c1, c2, c3 = coupons

    run = validate_success(
        api.prorate_ticket(
            ticket["id"],
            prorate_payload("PROVISIONAL", ticket_version(ticket["id"])),
            make_accountant_headers(aa["id"]),
        ),
        201,
    )
    assert run["total_weight_units"] == 7328000

    assert read_coupon(c1["id"])["weight_units"] == 1000000
    assert read_coupon(c2["id"])["weight_units"] == 1000000
    assert read_coupon(c3["id"])["weight_units"] == 5328000
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 13646
    assert read_coupon(c2["id"])["allocated_amount_minor"] == 13646


def test_rounding_residual_is_granted_whole_to_the_heaviest_coupon(api):
    """PRD §3.5: "Because per-coupon rounding cannot be expected to reconstitute the pool, the
    difference is measured: `rounding_residual_minor` is `straight_rate_pool_minor` less the
    sum of those rounded shares, and it may be positive or negative."
    PRD §3.5: "That entire residual is then granted to exactly one coupon — the one with the
    highest `weight_units`, with the lowest `coupon_number` breaking a tie — by adding it to
    that coupon's `allocated_amount_minor`. No other coupon is touched by the residual."

    Design: Difficulty/combinatorial_formula/round_per_coupon_then_grant_residual_to_heaviest
    """
    set_clock("2026-08-02T00:00:00Z")
    aa, ticket, coupons = _rounding_scenario()
    c1, c2, c3 = coupons

    run = validate_success(
        api.prorate_ticket(
            ticket["id"],
            prorate_payload("PROVISIONAL", ticket_version(ticket["id"])),
            make_accountant_headers(aa["id"]),
        ),
        201,
    )
    assert run["rounding_residual_minor"] == 1

    heaviest = read_coupon(c3["id"])
    assert heaviest["allocated_amount_minor"] == 72708, (
        "the pre-residual 72707 plus the whole one-unit residual"
    )
    allocations = [read_coupon(c["id"]) for c in (c1, c2, c3)]
    assert sum(c["allocated_amount_minor"] for c in allocations) == 100000
    final_ticket = read_ticket(ticket["id"])
    assert final_ticket["unallocated_residual_minor"] == 0
    assert_fare_conservation(final_ticket, allocations)


# --------------------------------------------------------------------------- #
# Empty FINAL input set
# --------------------------------------------------------------------------- #
def _two_open_coupons_provisionally_prorated():
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": bb["id"], "origin": "JFK", "destination": "LHR"},
            {"operating_carrier_id": bb["id"], "origin": "LHR", "destination": "JFK"},
        ],
        ticket_number="0024000000001",
    )
    run_proration(ticket["id"], aa["id"], "PROVISIONAL")
    return aa, ticket, coupons


def test_final_run_over_no_flown_coupons_is_refused(api):
    """PRD §3.5: "`FINAL` is the basis actually billed through the clearing house: its input
    set is the coupons whose `coupon_status` is `FLOWN` or `ADJUSTED`, so unflown coupons drop
    out and the surviving coupons share a differently-shaped pool, and it does honour special
    prorate agreements and does bend straight-rate weights by the matched factor."
    PRD §3.5: "Voided coupons are excluded by both variants. Whichever variant is requested,
    if its input set is empty the run fails with `ERR_NO_PRORATABLE_COUPONS` (HTTP 422) and
    nothing is written."

    Design: Difficulty/boundary_precision_check/final_proration_over_empty_flown_coupon_set
    """
    aa, ticket, _coupons = _two_open_coupons_provisionally_prorated()

    resp = api.prorate_ticket(
        ticket["id"],
        prorate_payload("FINAL", ticket_version(ticket["id"])),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_PRORATABLE_COUPONS.value)


def test_refused_final_run_leaves_the_provisional_allocation_intact(api):
    """PRD §2.7: "**Non-empty run input.** The requested run variant's coupon input set is
    non-empty — otherwise `ERR_NO_PRORATABLE_COUPONS` (422). Applies to proration runs."
    PRD §3.5: "The runs of one ticket can be read back as a list, ordered oldest first."

    Design: Difficulty/boundary_precision_check/final_proration_over_empty_flown_coupon_set
    """
    aa, ticket, coupons = _two_open_coupons_provisionally_prorated()
    before = read_ticket(ticket["id"])

    validate_error(
        api.prorate_ticket(
            ticket["id"],
            prorate_payload("FINAL", before["version"]),
            make_accountant_headers(aa["id"]),
        ),
        ApiErrorId.ERR_NO_PRORATABLE_COUPONS.value,
    )

    after = read_ticket(ticket["id"])
    assert after["proration_status"] == "PROVISIONAL", "the failed run left the axis untouched"
    assert after["version"] == before["version"], "a rejected run bumps nothing"
    assert after["unallocated_residual_minor"] == 0
    for coupon in coupons:
        fresh = read_coupon(coupon["id"])
        assert fresh["allocated_amount_minor"] == 50000
        assert fresh["allocation_basis"] == "STRAIGHT_RATE"

    rows, meta = validate_paginated(api.list_proration_runs(ticket["id"], OPERATOR))
    assert meta["total_count"] == 1, f"only the PROVISIONAL run exists, got {meta['total_count']}"
    assert rows[0]["run_type"] == "PROVISIONAL"


# --------------------------------------------------------------------------- #
# Fare conservation across the compensating void
# --------------------------------------------------------------------------- #
def _final_prorated_spa_ticket():
    set_clock("2026-08-10T00:00:00Z")
    ctx = _three_sector_scenario(
        "SPA_FLAT", [SPA_FLAT_FACTOR], fly_all=True, ticket_number="0028000000001"
    )
    run_proration(ctx["ticket"]["id"], ctx["aa"]["id"], "FINAL")
    return ctx


def test_final_allocation_satisfies_the_fare_conservation_identity(api):
    """PRD §3.5: "The run records `allocated_total_minor` as the sum of every
    `allocated_amount_minor` it wrote, and the ticket's `unallocated_residual_minor` is
    recomputed as the pool less the sum of `allocated_amount_minor` across *all* the ticket's
    coupons."
    PRD §1: "First, **conservation**: the sum of every coupon's allocation plus the ticket's
    residual slack always equals the fare, and the sum of every carrier's net clearing-house
    position across the whole membership is always zero."

    Design: Difficulty/compensating_invariant/void_proration_conserves_the_ticket_fare_identity
    """
    ctx = _final_prorated_spa_ticket()
    c1, c2, c3 = ctx["coupons"]

    ticket = read_ticket(ctx["ticket"]["id"])
    coupons = [read_coupon(c["id"]) for c in (c1, c2, c3)]
    assert coupons[0]["allocated_amount_minor"] == 66601
    assert coupons[1]["allocated_amount_minor"] == 12000
    assert coupons[2]["allocated_amount_minor"] == 21399
    assert ticket["unallocated_residual_minor"] == 0
    assert_fare_conservation(ticket, coupons)


def test_void_proration_returns_the_whole_fare_to_the_slack_bucket(api):
    """PRD §3.5: "It sets `allocated_amount_minor` to 0 and `allocation_basis` to
    `UNALLOCATED` on every coupon of the ticket regardless of status, restores
    `unallocated_residual_minor` to the full `total_fare_minor`, resets `last_run_type` to
    `NONE`, moves `proration_status` back to `UNPRORATED` and bumps the ticket's `version`."

    Design: Difficulty/compensating_invariant/void_proration_conserves_the_ticket_fare_identity
    """
    ctx = _final_prorated_spa_ticket()
    c1, c2, c3 = ctx["coupons"]

    void_allocation(ctx["ticket"]["id"], ctx["aa"]["id"])

    ticket = read_ticket(ctx["ticket"]["id"])
    coupons = [read_coupon(c["id"]) for c in (c1, c2, c3)]
    for coupon in coupons:
        assert coupon["allocated_amount_minor"] == 0
        assert coupon["allocation_basis"] == "UNALLOCATED"
        assert coupon["coupon_status"] == "FLOWN", "voiding the allocation is not voiding the coupon"
    assert ticket["unallocated_residual_minor"] == 100000
    assert ticket["proration_status"] == "UNPRORATED"
    assert ticket["last_run_type"] == "NONE"
    assert_fare_conservation(ticket, coupons)


# --------------------------------------------------------------------------- #
# Factor selection and the straight-rate fallback
# --------------------------------------------------------------------------- #
def test_spa_percent_takes_a_basis_point_share_of_the_whole_fare(api):
    """PRD §3.5: "A coupon whose matched agreement has an `agreement_type` of `SPA_PERCENT`
    takes the pool multiplied by the factor's `percent_bp` and divided by 10000, rounded half
    up, and records an `allocation_basis` of `SPA_PERCENT`."
    PRD §3.5: "The pool entering the run, recorded as `pool_minor`, is always the ticket's
    full `total_fare_minor` — both variants start from the whole fare, never from a remainder."

    Design: Corner/calculations/spa_percent_agreement_takes_a_basis_point_share_off_the_top
    """
    set_clock("2026-08-10T00:00:00Z")
    ctx = _three_sector_scenario(
        "SPA_PERCENT",
        [create_factor_payload("LHR", "CDG", "ECONOMY", percent_bp=1500)],
        ticket_number="0038000000001",
    )
    c1, c2, c3 = ctx["coupons"]

    run = validate_success(
        api.prorate_ticket(
            ctx["ticket"]["id"],
            prorate_payload("FINAL", ticket_version(ctx["ticket"]["id"])),
            make_accountant_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert run["spa_total_minor"] == 15000, "1500 bp of the whole 100000 fare"
    assert run["straight_rate_pool_minor"] == 85000

    assert read_coupon(c2["id"])["allocated_amount_minor"] == 15000
    assert read_coupon(c2["id"])["allocation_basis"] == "SPA_PERCENT"
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 64331
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 20669
    assert read_ticket(ctx["ticket"]["id"])["unallocated_residual_minor"] == 0


def test_rounding_residual_tie_break_goes_to_the_lowest_coupon_number(api):
    """PRD §3.5: "That entire residual is then granted to exactly one coupon — the one with
    the highest `weight_units`, with the lowest `coupon_number` breaking a tie — by adding it
    to that coupon's `allocated_amount_minor`. No other coupon is touched by the residual."

    Design: Corner/calculations/rounding_residual_tie_break_goes_to_the_lowest_coupon_number
    """
    aa, bb, cc = setup_three_carriers()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": bb["id"], "origin": "JFK", "destination": "BOS",
             "class_of_service": "ECONOMY", "tpm_miles": 333},
            {"operating_carrier_id": cc["id"], "origin": "BOS", "destination": "YUL",
             "class_of_service": "ECONOMY", "tpm_miles": 333},
            {"operating_carrier_id": bb["id"], "origin": "YUL", "destination": "YYZ",
             "class_of_service": "ECONOMY", "tpm_miles": 50},
        ],
        ticket_number="0039000000001",
    )
    c1, c2, c3 = coupons

    run = validate_success(
        api.prorate_ticket(
            ticket["id"],
            prorate_payload("PROVISIONAL", ticket_version(ticket["id"])),
            make_accountant_headers(aa["id"]),
        ),
        201,
    )
    assert run["total_weight_units"] == 7160000
    assert run["rounding_residual_minor"] == 1

    assert read_coupon(c1["id"])["allocated_amount_minor"] == 46509, (
        "coupon_number 1 wins the weight tie and takes the residual"
    )
    assert read_coupon(c2["id"])["allocated_amount_minor"] == 46508
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 6983


def test_exact_sector_factor_outranks_the_double_wildcard_factor(api):
    """PRD §3.2: "The surviving candidates are ranked by `specificity_score` from highest to
    lowest, so a fully concrete sector beats a half-wildcarded one and a half-wildcarded one
    beats a fully wildcarded one."
    PRD §3.2: "It counts how many of the two station fields are concrete rather than
    wildcarded: 2 when neither `origin` nor `destination` is `*`, 1 when exactly one of them
    is, and 0 when both are."

    Design: Corner/calculations/exact_sector_factor_outranks_the_wildcard_factor
    """
    set_clock("2026-08-10T00:00:00Z")
    ctx = _three_sector_scenario(
        "SPA_FLAT",
        [
            create_factor_payload("*", "*", "ECONOMY", flat_amount_minor=5000),
            create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=12000),
        ],
        ticket_number="0040000000001",
    )
    wildcard, exact = ctx["factors"]
    c1, c2, c3 = ctx["coupons"]

    assert_specificity_score(exact)
    assert_specificity_score(wildcard)
    assert exact["specificity_score"] == 2
    assert wildcard["specificity_score"] == 0
    assert read_agreement(ctx["agreement"]["id"])["factor_count"] == 2

    run_proration(ctx["ticket"]["id"], ctx["aa"]["id"], "FINAL")

    assert read_coupon(c2["id"])["allocated_amount_minor"] == 12000, (
        "the concrete LHR-CDG factor outranks the double wildcard"
    )
    assert read_coupon(c2["id"])["allocation_basis"] == "SPA_FLAT"
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 66601
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 21399


def test_suspended_agreement_falls_back_to_the_straight_rate_default(api):
    """PRD §3.2: "Operator suspension of an `ACTIVE` agreement is the mirror image: `status`
    becomes `SUSPENDED`, `suspension_reason` becomes `OPERATOR_SUSPENDED` — distinct from the
    `CARRIER_SUSPENDED` value written by the membership sweep, so the clearing house can tell
    a commercial suspension from a collateral one — and `version` bumps."
    PRD §3.2: "The operational consequence is immediate: because the factor selector only ever
    considers agreements whose `status` is `ACTIVE`, coupons prorated after this point
    silently fall back to the straight-rate default rather than failing."

    Design: Corner/calculations/suspended_agreement_falls_back_to_the_straight_rate_default
    """
    set_clock("2026-08-10T00:00:00Z")
    ctx = _three_sector_scenario(
        "SPA_FLAT", [SPA_FLAT_FACTOR], suspend=True, ticket_number="0041000000001"
    )
    c1, c2, c3 = ctx["coupons"]

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "SUSPENDED"
    assert agreement["suspension_reason"] == "OPERATOR_SUSPENDED"

    run = validate_success(
        api.prorate_ticket(
            ctx["ticket"]["id"],
            prorate_payload("FINAL", ticket_version(ctx["ticket"]["id"])),
            make_accountant_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert run["spa_total_minor"] == 0
    assert run["total_weight_units"] == 47758000

    assert read_coupon(c2["id"])["allocated_amount_minor"] == 4523
    assert read_coupon(c2["id"])["allocation_basis"] == "STRAIGHT_RATE"
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 72260
    assert read_coupon(c3["id"])["allocated_amount_minor"] == 23217


def test_voided_coupon_drops_out_of_the_provisional_input_set(api):
    """PRD §3.4: "Voiding is available only from `OPEN`, is restricted to the
    `RevenueAccountant` whose `X-User-ID` is the owning ticket's `validating_carrier_id`, and
    does three things: it sets `coupon_status` to `VOID`, zeroes `allocated_amount_minor` and
    resets `allocation_basis` to `UNALLOCATED`, then recomputes the ticket's
    `unallocated_residual_minor` so the fare stays conserved."
    PRD §3.5: "Voided coupons are excluded by both variants. Whichever variant is requested,
    if its input set is empty the run fails with `ERR_NO_PRORATABLE_COUPONS` (HTTP 422) and
    nothing is written."

    Design: Corner/calculations/voided_coupon_leaves_the_provisional_input_set
    """
    ctx = _three_sector_scenario(fly_all=False, ticket_number="0042000000001")
    c1, c2, c3 = ctx["coupons"]
    void_coupon(c3["id"], ctx["aa"]["id"])

    run = validate_success(
        api.prorate_ticket(
            ctx["ticket"]["id"],
            prorate_payload("PROVISIONAL", ticket_version(ctx["ticket"]["id"])),
            make_accountant_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert run["included_coupon_count"] == 2
    assert run["total_weight_units"] == 36670000

    voided = read_coupon(c3["id"])
    assert voided["coupon_status"] == "VOID"
    assert voided["allocated_amount_minor"] == 0
    assert voided["allocation_basis"] == "UNALLOCATED"
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 94110
    assert read_coupon(c2["id"])["allocated_amount_minor"] == 5890

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["unallocated_residual_minor"] == 0
    assert_fare_conservation(ticket, [read_coupon(c["id"]) for c in (c1, c2, c3)])


def test_special_prorate_amounts_above_the_fare_are_refused(api):
    """PRD §3.5: "Every such amount accumulates into `spa_total_minor`, which is always zero
    for a `PROVISIONAL` run. If `spa_total_minor` ends up larger than the pool, the whole run
    is refused with `ERR_SPA_OVERALLOCATION` (HTTP 422). What remains, the pool less
    `spa_total_minor`, is recorded as `straight_rate_pool_minor` and is what the remaining
    coupons share."

    Design: Corner/validations/special_prorate_amounts_above_the_fare_return_spa_overallocation
    """
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_FLAT",
        factors=[create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=200000)],
        activate=True,
    )
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [{"operating_carrier_id": bb["id"], "origin": "LHR", "destination": "CDG",
          "class_of_service": "ECONOMY", "tpm_miles": 216}],
        ticket_number="0051000000001",
        fly_all=True,
    )

    resp = api.prorate_ticket(
        ticket["id"],
        prorate_payload("FINAL", ticket_version(ticket["id"])),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPA_OVERALLOCATION.value)

    unchanged = read_ticket(ticket["id"])
    assert unchanged["proration_status"] == "UNPRORATED"
    assert unchanged["unallocated_residual_minor"] == 100000
    coupon = read_coupon(coupons[0]["id"])
    assert coupon["allocated_amount_minor"] == 0
    assert coupon["allocation_basis"] == "UNALLOCATED"
    _rows, meta = validate_paginated(api.list_proration_runs(ticket["id"], OPERATOR))
    assert meta["total_count"] == 0, "a refused run writes no ledger entry"


def test_void_proration_on_an_unprorated_ticket_is_refused(api):
    """PRD §3.5: "It is available to the `RevenueAccountant` of the ticket's
    `validating_carrier_id` when `proration_status` is `PROVISIONAL`, `FINAL` or
    `REPRORATION_REQUIRED` — never from `UNPRORATED`, which is refused with
    `ERR_TICKET_NOT_PRORATED` — and requires `expected_ticket_version`."

    Design: Corner/validations/void_proration_on_an_unprorated_ticket_returns_ticket_not_prorated
    """
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    ticket, _coupons = setup_ticket_with_coupons(
        aa["id"], [{"operating_carrier_id": bb["id"]}], ticket_number="0046000000001"
    )
    version = ticket_version(ticket["id"])

    resp = api.void_proration(
        ticket["id"],
        {"expected_ticket_version": version},
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_PRORATED.value)

    unchanged = read_ticket(ticket["id"])
    assert unchanged["proration_status"] == "UNPRORATED"
    assert unchanged["unallocated_residual_minor"] == 100000
    assert unchanged["version"] == version, "the rejected call bumped nothing"


def test_proration_over_a_stale_ticket_version_is_rejected(api):
    """PRD §2.8: "A `POST /interline/tickets/{id}/prorate` request must carry
    `expected_ticket_version` holding the `version` of the target `Ticket` as the client last
    read it. If that value does not equal the ticket's current `version`, no run is created
    and the request is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412)."
    PRD §3.4: "Appending bumps the ticket's `coupon_count` and its `version`."

    Design: Corner/cross_cutting_layers/prorate_with_stale_ticket_version_returns_412
    """
    aa, bb = setup_two_carriers()
    ticket = new_ticket(aa["id"], "0071000000001")
    c1 = validate_success(
        api.create_coupon(
            ticket["id"],
            {"coupon_number": 1, "origin": "JFK", "destination": "LHR",
             "operating_carrier_id": bb["id"], "class_of_service": "ECONOMY", "tpm_miles": 1000},
            make_accountant_headers(aa["id"]),
        ),
        201,
    )
    stale_version = ticket_version(ticket["id"])
    c2 = validate_success(
        api.create_coupon(
            ticket["id"],
            {"coupon_number": 2, "origin": "LHR", "destination": "JFK",
             "operating_carrier_id": bb["id"], "class_of_service": "ECONOMY", "tpm_miles": 1000},
            make_accountant_headers(aa["id"]),
        ),
        201,
    )

    resp = api.prorate_ticket(
        ticket["id"],
        prorate_payload("PROVISIONAL", stale_version),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TICKET_VERSION.value)

    unchanged = read_ticket(ticket["id"])
    assert unchanged["proration_status"] == "UNPRORATED"
    assert unchanged["unallocated_residual_minor"] == 100000
    assert read_coupon(c1["id"])["allocated_amount_minor"] == 0
    assert read_coupon(c2["id"])["allocated_amount_minor"] == 0
    _rows, meta = validate_paginated(api.list_proration_runs(ticket["id"], OPERATOR))
    assert meta["total_count"] == 0


def test_proration_runs_accumulate_as_an_append_only_log(api):
    """PRD §3.5: "The runs of one ticket can be read back as a list, ordered oldest first."
    PRD §2.4: "Two record types are append-only ledger entries and are never mutated after
    they are written: `ExchangeRate` and `ProrationRun`. These two carry `id` and `created_at`
    only — they have no `updated_at` field and no `version` field at all, and neither field
    should appear in their representations."

    Design: Corner/entities/proration_runs_accumulate_as_an_append_only_log_per_ticket
    """
    aa, bb = setup_two_carriers()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"], [{"operating_carrier_id": bb["id"]}], ticket_number="0033000000001"
    )
    run_proration(ticket["id"], aa["id"], "PROVISIONAL")
    fly(coupons[0]["id"], aa["id"])
    run_proration(ticket["id"], aa["id"], "FINAL")

    rows, meta = validate_paginated(api.list_proration_runs(ticket["id"], OPERATOR))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    for row in rows:
        assert_proration_run(row)

    first, second = rows
    assert first["run_type"] == "PROVISIONAL"
    assert first["included_coupon_count"] == 1
    assert first["pool_minor"] == 100000
    assert first["spa_total_minor"] == 0
    assert second["run_type"] == "FINAL"
    assert second["included_coupon_count"] == 1
    assert second["straight_rate_pool_minor"] == 100000

    assert read_ticket(ticket["id"])["last_run_type"] == "FINAL"
