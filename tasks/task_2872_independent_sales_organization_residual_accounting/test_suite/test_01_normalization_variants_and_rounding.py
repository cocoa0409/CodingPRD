"""Normalization: the two split modes and the pinned rounding order."""

from test_helpers import (
    add_line,
    fetch_batch,
    fetch_line,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    validate_success,
    api_client,
    ANALYST,
)

CANONICAL_LINE = {
    "transaction_count": 1240,
    "sales_volume_cents": 4812355,
    "interchange_cents": 92140,
    "assessments_cents": 6255,
    "gross_income_cents": 168430,
}

HALF_CENT_LINE = {
    "transaction_count": 250,
    "sales_volume_cents": 101000,
    "interchange_cents": 3000,
    "assessments_cents": 200,
    "gross_income_cents": 8000,
}


def _two_mode_scenario() -> dict:
    """Two programs identical but for normalization_mode, one line of identical file data each."""
    p_net = make_program(name="FirstAtlantic Net", normalization_mode="NET_REVENUE_SPLIT")
    p_gross = make_program(name="FirstAtlantic Gross", normalization_mode="GROSS_SPLIT")
    agent = make_agent()
    m_net = make_active_merchant(agent["id"], p_net["id"])
    m_gross = make_active_merchant(agent["id"], p_gross["id"])
    b_net = make_batch(p_net["id"], file_checksum="sha256:net-0001")
    l_net = add_line(b_net["id"], m_net["id"], **CANONICAL_LINE)
    b_gross = make_batch(p_gross["id"], file_checksum="sha256:gross-0001")
    l_gross = add_line(b_gross["id"], m_gross["id"], **CANONICAL_LINE)
    return {
        "p_net": p_net,
        "p_gross": p_gross,
        "b_net": b_net,
        "b_gross": b_gross,
        "l_net": l_net,
        "l_gross": l_gross,
    }


def _three_line_batch() -> dict:
    """One agent, three merchants, three lines whose buy-rate product is exactly 454.5 cents."""
    program = make_program()
    agent = make_agent()
    lines = []
    batch = make_batch(program["id"], file_checksum="sha256:round-0001")
    for _ in range(3):
        merchant = make_active_merchant(
            agent["id"],
            program["id"],
            monthly_minimum_cents=0,
            per_transaction_fee_cents=15,
            equipment_lease_monthly_cents=0,
            boarded_on="2026-01-05",
        )
        lines.append(add_line(batch["id"], merchant["id"], **HALF_CENT_LINE))
    return {"program": program, "agent": agent, "batch": batch, "lines": lines}


def test_net_and_gross_normalization_diverge_by_exactly_the_processor_cost():
    """Identical file data under the two split modes: 40939 net vs 70035 gross.

    Both lines compute the same processor cost of 29096 cents
    (round_half_up(4812355 * 45 / 10000) = 21656, plus 6 * 1240 = 7440); the
    NET program deducts it and the GROSS program does not.

    PRD: "for identical file data the normalized net revenue under `GROSS_SPLIT`
    is higher than under `NET_REVENUE_SPLIT` by exactly `processor_cost_cents`"

    Design: Difficulty/dual_variant_calc/normalize_variant_divergence_net_vs_gross
    """
    scenario = _two_mode_scenario()

    validate_success(api_client.normalize_residual_batch(scenario["b_net"]["id"], ANALYST))
    validate_success(api_client.normalize_residual_batch(scenario["b_gross"]["id"], ANALYST))

    net_line = fetch_line(scenario["l_net"]["id"])
    gross_line = fetch_line(scenario["l_gross"]["id"])

    assert net_line["processor_cost_cents"] == 29096
    assert gross_line["processor_cost_cents"] == 29096, (
        "the GROSS_SPLIT program still computes and stores the processor cost"
    )
    assert net_line["normalized_net_revenue_cents"] == 40939
    assert gross_line["normalized_net_revenue_cents"] == 70035
    assert (
        gross_line["normalized_net_revenue_cents"]
        - net_line["normalized_net_revenue_cents"]
        == 29096
    )


def test_each_line_records_its_program_mode_and_the_batch_total_follows():
    """The mode actually applied is stamped on the line and rolled into the batch total.

    PRD: "Under `GROSS_SPLIT`, `normalized_net_revenue_cents` is the line's
    `gross_income_cents` less its `interchange_cents`, less its
    `assessments_cents`, and the processor cost is **not** deducted."

    Design: Difficulty/dual_variant_calc/normalize_variant_divergence_net_vs_gross
    """
    scenario = _two_mode_scenario()

    validate_success(api_client.normalize_residual_batch(scenario["b_net"]["id"], ANALYST))
    validate_success(api_client.normalize_residual_batch(scenario["b_gross"]["id"], ANALYST))

    net_line = fetch_line(scenario["l_net"]["id"])
    gross_line = fetch_line(scenario["l_gross"]["id"])
    assert net_line["normalization_mode_applied"] == "NET_REVENUE_SPLIT"
    assert gross_line["normalization_mode_applied"] == "GROSS_SPLIT"

    net_batch = fetch_batch(scenario["b_net"]["id"])
    gross_batch = fetch_batch(scenario["b_gross"]["id"])
    assert net_batch["total_normalized_net_revenue_cents"] == 40939
    assert gross_batch["total_normalized_net_revenue_cents"] == 70035
    assert net_batch["state"] == "NORMALIZED"
    assert gross_batch["state"] == "NORMALIZED"


def test_buy_rate_product_is_rounded_once_per_line_before_the_per_item_term():
    """Three lines of 101000 cents each: 454.5 rounds to 455 on every line.

    Per line the processor cost is 455 + 250 * 6 = 1955 and the normalized net
    revenue is 8000 - 3000 - 200 - 1955 = 2845.

    PRD: "the volume term is rounded per line, before the per-item term is added
    and before any batch-level summation"

    Design: Difficulty/combinatorial_formula/normalization_rounding_order_per_line_then_sum
    """
    scenario = _three_line_batch()

    validate_success(api_client.normalize_residual_batch(scenario["batch"]["id"], ANALYST))

    for line in scenario["lines"]:
        stored = fetch_line(line["id"])
        assert stored["processor_cost_cents"] == 1955, (
            "455 rounded per line plus the 1500-cent per-item term"
        )
        assert stored["normalized_net_revenue_cents"] == 2845


def test_batch_total_sums_already_rounded_lines_and_never_the_reverse():
    """The rollup is 3 * 2845 = 8535; summing volume first would report 8536.

    Applying the buy rate once to the 303000-cent grand total gives
    round_half_up(1363.5) = 1364, a processor cost of 5864 and a total of 8536 —
    the one-cent fingerprint of the wrong evaluation order.

    PRD: "That last total sums the already-rounded per-line results — round
    first, then add, never the reverse."

    Design: Difficulty/combinatorial_formula/normalization_rounding_order_per_line_then_sum
    """
    scenario = _three_line_batch()

    validate_success(api_client.normalize_residual_batch(scenario["batch"]["id"], ANALYST))

    batch = fetch_batch(scenario["batch"]["id"])
    assert batch["line_count"] == 3
    assert batch["gross_volume_cents"] == 303000
    assert batch["total_normalized_net_revenue_cents"] == 8535
    assert batch["total_normalized_net_revenue_cents"] != 8536, (
        "8536 is the sum-then-round result and is explicitly excluded"
    )
    assert batch["state"] == "NORMALIZED"
