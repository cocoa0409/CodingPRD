"""Difficulty coverage (queue A): the reproduction fee's pinned rounding
order — per-tier academic discount first, then the rush multiplier."""

import test_helpers as th


def _setup_ada_and_collection():
    th.set_clock()
    bundle = th.setup_public_described_collection()
    ada = th.create_active_researcher()  # ACADEMIC by default
    return bundle["collection"], ada


def test_reproduction_fee_rounding_order_divergence_canonical(api):
    """PRD §3.8: "For an `ACADEMIC` researcher, the affiliation discount
    applies **per tier**: each tier's subtotal is multiplied by 0.85 and
    rounded half up to whole cents, and the discounted tiers are then summed."
    PRD §3.8: "Rush handling applies **last**: the summed amount is multiplied
    by 1.5 and rounded half up to whole cents. This order is canonical —
    discount per tier first, rush multiplier after — and the rush multiplier is
    never applied to a tier before the discount, because the two orders diverge
    whenever a discounted-and-rushed tier lands on a fractional cent. Worked
    through precisely: 25 pages for an `ACADEMIC` researcher with rush handling
    gives a first tier of 1600 cents discounted to 1360, a second tier of 250
    cents discounted to 213 (250 times 0.85 is 212.5, rounding half up), a
    discounted sum of 1573, and a final fee of 2360 cents (1573 times 1.5 is
    2359.5, rounding half up)."

    Design: Difficulty/dual_variant_calc/reproduction_fee_rounding_order_divergence
    """
    collection, ada = _setup_ada_and_collection()
    resp = api.create_reproduction_request(
        th.reproduction_payload(ada["id"], collection["id"], 25, "DIGITAL_SCAN",
                                rush=True),
        headers=th.make_researcher_headers(ada["id"]),
    )
    repro = th.validate_success(resp, 201)
    assert repro["fee_cents"] == 2360
    assert repro["fee_cents"] != 2359  # the rush-before-discount reading
    assert repro["fee_cents"] == th.expected_fee_cents(25, "ACADEMIC", True)
    assert repro["status"] == "QUOTED"


def test_reproduction_fee_rounding_order_divergence_discount_leg(api):
    """PRD §3.8: "25 pages for an `ACADEMIC` researcher with rush handling
    gives a first tier of 1600 cents discounted to 1360, a second tier of 250
    cents discounted to 213 (250 times 0.85 is 212.5, rounding half up), a
    discounted sum of 1573, and a final fee of 2360 cents (1573 times 1.5 is
    2359.5, rounding half up)."
    PRD §2.10: "Rounding is round half up, and it occurs at exactly two points
    in the fee computation and nowhere else: once per tier when the academic
    affiliation discount is applied, and once after the rush multiplier is
    applied to the discounted sum."

    Design: Difficulty/dual_variant_calc/reproduction_fee_rounding_order_divergence
    """
    collection, ada = _setup_ada_and_collection()
    resp = api.create_reproduction_request(
        th.reproduction_payload(ada["id"], collection["id"], 25, "DIGITAL_SCAN",
                                rush=False),
        headers=th.make_researcher_headers(ada["id"]),
    )
    repro = th.validate_success(resp, 201)
    # Without rush, only the per-tier discount leg remains: 1360 + 213 == 1573,
    # which pins the 212.5 -> 213 round-half-up inside tier 2.
    assert repro["fee_cents"] == 1573
    assert repro["fee_cents"] == th.expected_fee_cents(25, "ACADEMIC", False)
    assert repro["status"] == "QUOTED"


def test_reproduction_fee_nested_rounding_order_canonical(api):
    """PRD §3.8: "For an `ACADEMIC` researcher, the affiliation discount
    applies **per tier**: each tier's subtotal is multiplied by 0.85 and
    rounded half up to whole cents, and the discounted tiers are then summed."
    PRD §3.8: "Rush handling applies **last**: the summed amount is multiplied
    by 1.5 and rounded half up to whole cents. This order is canonical —
    discount per tier first, rush multiplier after"

    Design: Difficulty/combinatorial_formula/reproduction_fee_nested_rounding_order
    """
    collection, ada = _setup_ada_and_collection()
    resp = api.create_reproduction_request(
        th.reproduction_payload(ada["id"], collection["id"], 45, "CERTIFIED_COPY",
                                rush=True),
        headers=th.make_researcher_headers(ada["id"]),
    )
    repro = th.validate_success(resp, 201)
    # tier1 1600 -> 1360; tier2 1250 -> round_half_up(1062.5) = 1063;
    # sum 2423; rush 2423 * 1.5 = 3634.5 -> round_half_up 3635.
    assert repro["fee_cents"] == 3635
    assert repro["fee_cents"] != 3634  # the rush-before-discount reading
    assert repro["fee_cents"] == th.expected_fee_cents(45, "ACADEMIC", True)


def test_reproduction_fee_nested_rounding_order_discount_leg(api):
    """PRD §3.8: "The fee is computed once, at creation, and stored on
    `fee_cents` in integer cents; it never drifts afterward."
    PRD §2.10: "Reproduction fees are integer numbers of cents, never
    fractional. Rounding is round half up, and it occurs at exactly two points
    in the fee computation and nowhere else: once per tier when the academic
    affiliation discount is applied, and once after the rush multiplier is
    applied to the discounted sum."

    Design: Difficulty/combinatorial_formula/reproduction_fee_nested_rounding_order
    """
    collection, ada = _setup_ada_and_collection()
    resp = api.create_reproduction_request(
        th.reproduction_payload(ada["id"], collection["id"], 45, "CERTIFIED_COPY",
                                rush=False),
        headers=th.make_researcher_headers(ada["id"]),
    )
    repro = th.validate_success(resp, 201)
    # tier1 1600 -> 1360; tier2 1250 -> round_half_up(1062.5) = 1063;
    # discounted sum 2423 — the nested per-tier rounding shows without rush.
    assert repro["fee_cents"] == 2423
    assert repro["fee_cents"] == th.expected_fee_cents(45, "ACADEMIC", False)
