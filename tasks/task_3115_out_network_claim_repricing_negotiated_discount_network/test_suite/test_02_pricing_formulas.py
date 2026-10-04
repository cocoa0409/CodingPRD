"""Difficulty queue: combinatorial formula — RBP pinned evaluation order and
the PER_LINE_THEN_SUM rounding order."""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    create_payer, create_provider, create_medicare_entry, create_ucr_rate,
    create_policy, create_claim, add_line, reprice,
    make_payer_admin_headers, make_payer_rep_headers,
)

RBP_DEFENSIBILITY = (
    "RBP defensibility: benchmark p80 UCR, markup 1.20, "
    "allowed floor from Medicare x1.50"
)


def _setup_rbp_world():
    """Payer + provider + Medicare rows (99283, 99284) + UCR rows + RBP policy."""
    payer = create_payer()
    provider = create_provider(npi="1000000003")
    create_medicare_entry(procedure_code="99283", region_code="R1")
    create_medicare_entry(procedure_code="99284", region_code="R1")
    create_ucr_rate(procedure_code="99283", region_code="R1",
                    percentile_50_cents=18000, percentile_80_cents=25000)
    create_ucr_rate(procedure_code="99284", region_code="R1",
                    percentile_50_cents=30000, percentile_80_cents=40000)
    create_ucr_rate(procedure_code="99285", region_code="R1",
                    percentile_50_cents=800, percentile_80_cents=1000)
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(
        payer, ctx,
        claim_type="PROFESSIONAL", network_status="OUT_OF_NETWORK",
        methodology="REFERENCE_BASED", percent_of_medicare=1.50,
        rbp_markup_percent=1.20, priority=1)
    return payer, provider, ctx


def _claim_with_line(payer, provider, ctx, ref, code, qty, unit, region="R1"):
    claim = create_claim(payer, provider, ctx, external_claim_ref=ref,
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx, procedure_code=code, quantity_units=qty,
             unit_charge_cents=unit, region_code=region)
    return claim


def test_rbp_gap_term_zero_when_benchmark_below_allowed():
    """PRD §3.4: "The `rbp_amount_cents` value is the lesser of the claim's
    `billed_amount_cents` and the claim's `allowed_amount_cents` plus the
    policy's `rbp_markup_percent` multiplied by the gap between the benchmark
    and the allowed amount — the gap taken as zero when the benchmark does not
    exceed the allowed amount — with the markup-over-gap term rounded half-up to
    whole cents."

    Design: Difficulty/combinatorial_formula/rbp_circular_dependency_pinned_evaluation_order
    """
    payer, provider, ctx = _setup_rbp_world()
    # 99283 qty 2 @ 40000: gross 80000; allowed = min(80000, 1.20*25000*2)
    # = min(80000, 60000) = 60000.
    claim = _claim_with_line(payer, provider, ctx, "D1", "99283", 2, 40000)
    validate_success(
        reprice(claim["id"], claim["version"] + 1, ctx,
                defensibility_notes=RBP_DEFENSIBILITY), 200)
    claim = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    assert claim["allowed_amount_cents"] == 60000
    # benchmark 25000 < allowed 60000 -> gap 0 -> rbp = min(80000, 60000) = 60000
    assert claim["rbp_amount_cents"] == 60000
    assert claim["methodology_used"] == "REFERENCE_BASED"


def test_rbp_markup_applies_to_gap_when_benchmark_exceeds_allowed():
    """PRD §3.4: "The evaluation order is pinned: `allowed_amount_cents` is fully
    computed first, then `rbp_amount_cents` reads it. The reference benchmark is
    the 80th-percentile UCR figure for the claim's primary (first-created)
    line's `procedure_code` and `region_code`."
    PRD §3.4: "The `rbp_amount_cents` value is the lesser of the claim's
    `billed_amount_cents` and the claim's `allowed_amount_cents` plus the
    policy's `rbp_markup_percent` multiplied by the gap between the benchmark
    and the allowed amount — the gap taken as zero when the benchmark does not
    exceed the allowed amount — with the markup-over-gap term rounded half-up to
    whole cents."

    Design: Difficulty/combinatorial_formula/rbp_circular_dependency_pinned_evaluation_order
    """
    payer, provider, ctx = _setup_rbp_world()
    # Primary line 99284 qty 1 @ 30000: gross 30000, allowed 30000
    # (min(30000, 1.20*40000)). Second line 99285 qty 1 @ 50000: allowed
    # min(50000, 1.20*1000) = 1200. Claim: billed 80000, allowed 31200.
    claim = _claim_with_line(payer, provider, ctx, "E1", "99284", 1, 30000)
    add_line(claim["id"], ctx, procedure_code="99285", quantity_units=1,
             unit_charge_cents=50000, region_code="R1")
    validate_success(
        reprice(claim["id"], claim["version"] + 2, ctx,
                defensibility_notes=RBP_DEFENSIBILITY), 200)
    claim = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    assert claim["allowed_amount_cents"] == 31200
    # primary-line benchmark 40000 > allowed 31200 -> gap 8800 ->
    # rbp = min(80000, 31200 + round(1.20 * 8800)) = 31200 + 10560 = 41760
    assert claim["rbp_amount_cents"] == 41760
    assert claim["methodology_used"] == "REFERENCE_BASED"


def _setup_rounding_world():
    """Payer + provider + Medicare 97110/R2 @ 9779 gaf 1.00 + x1.50 policy."""
    payer = create_payer()
    provider = create_provider(npi="1000000004")
    create_medicare_entry(procedure_code="97110", region_code="R2",
                          base_rate_cents=9779, geographic_adjustment_factor=1.00)
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, claim_type="ANCILLARY",
                  network_status="OUT_OF_NETWORK",
                  methodology="PERCENT_OF_MEDICARE", percent_of_medicare=1.50,
                  priority=1)
    return payer, provider, ctx


def test_per_line_allowed_rounded_individually():
    """PRD §2.6: "each claim line's allowed amount is rounded half-up to whole
    cents first, and only then are the per-line allowed amounts summed into the
    claim-level `allowed_amount_cents`."

    Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order_is_pinned
    """
    payer, provider, ctx = _setup_rounding_world()
    claim = create_claim(payer, provider, ctx, external_claim_ref="F1",
                         claim_type="ANCILLARY", patient_responsibility_cents=0)
    add_line(claim["id"], ctx, procedure_code="97110", quantity_units=1,
             unit_charge_cents=9779, region_code="R2")
    add_line(claim["id"], ctx, procedure_code="97110", quantity_units=1,
             unit_charge_cents=9779, region_code="R2")
    validate_success(reprice(claim["id"], claim["version"] + 2, ctx), 200)

    lines, _ = validate_paginated(
        api_client.list_claim_lines(claim["id"], ctx["payer_rep"]))
    assert len(lines) == 2
    for line in lines:
        # round_half_up(9779 * 1.5) = 14669 per line
        assert line["allowed_amount_cents"] == 14669
        assert line["status"] == "PRICED"


def test_claim_allowed_is_sum_of_per_line_rounded_amounts():
    """PRD §2.6: "The rounding order for repricing is pinned: each claim line's
    allowed amount is rounded half-up to whole cents first, and only then are
    the per-line allowed amounts summed into the claim-level
    `allowed_amount_cents`. This ordering is the `PER_LINE_THEN_SUM` value of
    the `rounding_order` policy field, which is fixed at that value across the
    system; the alternative of summing raw values and rounding once at the end
    is explicitly not used."
    PRD §3.4: "`savings_cents` is `billed_amount_cents` minus
    `allowed_amount_cents` plus `patient_responsibility_cents`"

    Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order_is_pinned
    """
    payer, provider, ctx = _setup_rounding_world()
    claim = create_claim(payer, provider, ctx, external_claim_ref="F1",
                         claim_type="ANCILLARY", patient_responsibility_cents=0)
    add_line(claim["id"], ctx, procedure_code="97110", quantity_units=1,
             unit_charge_cents=9779, region_code="R2")
    add_line(claim["id"], ctx, procedure_code="97110", quantity_units=1,
             unit_charge_cents=9779, region_code="R2")
    validate_success(reprice(claim["id"], claim["version"] + 2, ctx), 200)

    claim = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    assert claim["billed_amount_cents"] == 19558
    # PER_LINE_THEN_SUM: 14669 + 14669 = 29338 (aggregate-then-round gives 29337)
    assert claim["allowed_amount_cents"] == 29338
    assert claim["savings_cents"] == 19558 - 29338 + 0
