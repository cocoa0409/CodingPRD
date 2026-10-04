"""Dual-variant calculations: the booking guarantee ceiling and the settlement split.

Both calculations live in two genuinely different variants; the variant, not the
inputs, decides the cents.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, first_screening, report_screening, get_line,
    setup_two_circuit_settlement_scene, create_settlement_payload,
    validate_error, make_distributor_headers, make_theater_headers, make_exhibitor_headers,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _ceiling_scene():
    """B-rated circuit, 60 committed screens, 1500-cent title, guarantee 1500000."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=2000)
    theater = create_theater(circuit["id"], seats_total=60)
    title = create_title(distributor["id"], duration_minutes=90,
                         ticket_price_cents=1500, max_screen_commitment=60,
                         rights_end_utc="2027-03-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1500000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=70)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": booking, "line": line}


def test_guarantee_ceiling_uses_uncapped_variant_while_negotiating(ctx=None):
    """PRD §3.2: "While the booking is `DRAFT`, `PENDING_APPROVAL`, `COUNTERED`, or
    `APPROVED`, the provisional variant applies and the ceiling is simply the
    per-screen loaded figure with no aggregate cap — deliberately uncapped so that
    an expensive title does not make the negotiation unworkable by suppressing the
    ceiling mid-conversation."

    Design: Difficulty/dual_variant_calc/guarantee_ceiling_dual_variant_on_booking
    """
    scene = _ceiling_scene()
    booking = get_booking(scene["booking"]["id"])
    assert booking["status"] == "APPROVED"
    assert booking["guarantee_ceiling_cents"] == 1890000, (
        "60 screens x 35000 (B base) x 0.90 (51-150 tier) = 1890000 while negotiating"
    )


def test_guarantee_ceiling_flips_to_aggregate_capped_variant_on_sale():
    """PRD §3.2: "Once the booking reaches `ON_SALE`, `ON_HOLD`, `CONFIRMED`, or
    `SETTLED`, the capped variant applies instead, and the ceiling becomes the
    smaller of the per-screen loaded figure and a box-office aggregate computed as
    the admission price multiplied by the committed screen total and then by
    twelve."
    PRD §3.2: "an `A`-rated circuit committing 60 screens against a title priced at
    1500 cents has a per-screen loaded ceiling of 2430000 cents, while the aggregate
    arm for the same booking is 1080000 cents, so the same booking's ceiling halves
    when it goes on sale."

    Design: Difficulty/dual_variant_calc/guarantee_ceiling_dual_variant_on_booking
    """
    scene = _ceiling_scene()
    before = get_booking(scene["booking"]["id"])["guarantee_ceiling_cents"]
    set_clock(scene["booking"]["on_sale_at"])
    swept = get_success_data(api_client.run_on_sale_sweep(OPS))
    booking = get_booking(scene["booking"]["id"])
    assert booking["status"] == "ON_SALE"
    assert swept["advanced_count"] == 1
    assert before == 1890000
    assert booking["guarantee_ceiling_cents"] == 1080000, (
        "the aggregate arm 1500 x 60 x 12 = 1080000 caps the per-screen arm on sale"
    )
    assert before - booking["guarantee_ceiling_cents"] == 810000


def test_settlement_split_uses_allocation_order_variant_on_net_terms():
    """PRD §3.6: "Circuits on `NET_30` or `NET_60` use the allocation-order variant;
    circuits on `GROSS_ON_GROSS` or `FOUR_WALL` use the net-off-top variant."
    PRD §3.6: "For a booking reporting 3000000 cents of gross with a guarantee of
    1000000, a top-up of 200000, a revenue share of 0.40, no adjustment, and a
    make-good credit of 100000, the net-off-top variant yields a distributor position
    of 1180000 cents while the allocation-order variant yields 1900000 cents"

    Design: Difficulty/dual_variant_calc/settlement_split_dual_variant_on_settlement
    """
    scene = setup_two_circuit_settlement_scene()
    side = scene["sides"][0]
    assert side["terms"] == "NET_30"
    settlement = side["settlement"]
    assert settlement["distributor_net_cents"] == 1800000
    assert settlement["exhibitor_net_cents"] == 1200000
    assert settlement["invariant_drift_cents"] == 0


def test_settlement_split_uses_net_off_top_variant_on_gross_terms():
    """PRD §3.6: "Under the net-off-top variant no guarantee is paid off the top at
    all. The distributor's net position is the sum of the gross and the top-up paid,
    multiplied by the booking's revenue share and rounded half up to a whole cent,
    plus the adjustment, minus the make-good credit."

    Design: Difficulty/dual_variant_calc/settlement_split_dual_variant_on_settlement
    """
    scene = setup_two_circuit_settlement_scene()
    side = scene["sides"][1]
    assert side["terms"] == "GROSS_ON_GROSS"
    settlement = side["settlement"]
    assert settlement["distributor_net_cents"] == 1200000, (
        "round_half_up(3000000 x 0.40) = 1200000 under the net-off-top variant"
    )
    assert settlement["exhibitor_net_cents"] == 1800000
    assert settlement["invariant_drift_cents"] == 0


def test_settlement_variants_diverge_on_identical_reported_attendance():
    """PRD §3.6: "The divergence is large. For a booking reporting 3000000 cents of
    gross with a guarantee of 1000000, a top-up of 200000, a revenue share of 0.40,
    no adjustment, and a make-good credit of 100000, the net-off-top variant yields a
    distributor position of 1180000 cents while the allocation-order variant yields
    1900000 cents — a 720000-cent difference from the same settlement inputs."

    Design: Difficulty/dual_variant_calc/settlement_split_dual_variant_on_settlement
    """
    scene = setup_two_circuit_settlement_scene()
    allocation_side, net_off_side = scene["sides"]
    assert allocation_side["booking"]["guarantee_cents"] == (
        net_off_side["booking"]["guarantee_cents"])
    divergence = (allocation_side["settlement"]["distributor_net_cents"]
                  - net_off_side["settlement"]["distributor_net_cents"])
    assert divergence == 600000, "the same settlement inputs yield a 600000-cent gap"


def test_settlement_payment_rate_gate_reads_the_guarantee_not_the_covered_amount():
    """PRD §3.6: "The payment-rate gate is expressed as the gross divided by the
    guarantee, but the covered amount is itself derived from the guarantee and the
    rate, so the tier cannot be chosen until the guarantee is known and the
    guarantee's effective coverage cannot be described until the tier is known."
    PRD §3.6: "read the booking's guarantee first, then select the payment rate, then
    compute the covered amount, then compute the distributor's position, and finally
    take the exhibitor's position as the residual."

    Design: Difficulty/combinatorial_formula/settlement_payment_rate_gate_evaluation_order
    """
    scene = setup_two_circuit_settlement_scene()
    settlement = scene["sides"][0]["settlement"]
    # gate ratio 3000000 / 1000000 == 3.0 >= 1.5 -> full rate; covered = min(1e6, 3e6)
    assert 3000000 / scene["sides"][0]["booking"]["guarantee_cents"] == 3.0
    assert settlement["distributor_net_cents"] == 1800000
    assert settlement["invariant_drift_cents"] == 0


def test_settlement_payment_rate_gate_straddling_booking_selects_the_mid_tier():
    """PRD §3.6: "First a payment rate is selected by comparing the reported gross
    against the booking's guarantee: a gross at or above one and a half times the
    guarantee selects the full rate; a gross at or above the guarantee but below one
    and a half times it selects three quarters; and a gross below the guarantee
    selects one half."
    PRD §3.6: "Evaluating the gate against the already-covered amount instead of the
    gross changes the selected tier for any booking that straddles a gate boundary,
    so the order is a contract rather than an implementer's choice."

    Design: Difficulty/combinatorial_formula/settlement_payment_rate_gate_evaluation_order
    """
    scene = setup_two_circuit_settlement_scene(gross_box_office_cents=1400000)
    settlement = scene["sides"][0]["settlement"]
    # 1400000 / 1000000 == 1.4 -> the 0.75 tier; covered = 750000; residual 650000
    assert 1400000 / scene["sides"][0]["booking"]["guarantee_cents"] == 1.4
    assert settlement["distributor_net_cents"] == 750000 + 260000
    assert settlement["exhibitor_net_cents"] == 1400000 - 1010000
    assert settlement["invariant_drift_cents"] == 0