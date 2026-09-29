"""Inclusive rebate thresholds, the surge expiry cap and the allocation residual."""
import pytest

from test_helpers import (
    add_line,
    assert_instant_equals,
    create_quote,
    open_revrec,
    read_pricing_preview,
    read_quote,
    set_clock,
    submit_quote,
)


def test_the_tier_one_rebate_threshold_is_inclusive_on_the_net_subtotal(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.3: "The rebate rate is the pinned revision's `volume_rebate_tier2_pct` when the
    net subtotal is at or above `volume_rebate_tier2_min_cents`; otherwise it is
    `volume_rebate_tier1_pct` when the net subtotal is at or above
    `volume_rebate_tier1_min_cents`; otherwise it is zero."
    PRD §3.3: "The order total is then the net subtotal, less `volume_rebate_cents`, plus
    `payment_terms_uplift_cents`."

    Design: Corner/calculations/volume_rebate_tier_one_applies_at_the_exact_threshold_and_not_below
    """
    at_threshold = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Rebate At Threshold", payment_terms_days=30,
    )
    line_a = add_line(api, at_threshold["id"], base["service"]["id"], 25, 0.00, rep_headers)
    assert line_a["final_net_cents"] == 5000000, "the net subtotal sits exactly on the threshold"

    below = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Rebate Below Threshold", payment_terms_days=30,
    )
    line_b = add_line(api, below["id"], base["service"]["id"], 24, 0.00, rep_headers)
    assert line_b["final_net_cents"] == 4800000

    preview_a = read_pricing_preview(api, at_threshold["id"], analyst_headers)
    assert preview_a["volume_rebate_cents"] == 100000
    assert preview_a["payment_terms_uplift_cents"] == 0
    assert preview_a["final_net_total_cents"] == 4900000
    assert preview_a["final_blended_discount_pct"] == pytest.approx(0.020000, abs=1e-9)
    assert preview_a["final_margin_pct"] == pytest.approx(0.234694, abs=1e-9)

    preview_b = read_pricing_preview(api, below["id"], analyst_headers)
    assert preview_b["volume_rebate_cents"] == 0
    assert preview_b["payment_terms_uplift_cents"] == 0
    assert preview_b["final_net_total_cents"] == 4800000
    assert preview_b["final_blended_discount_pct"] == pytest.approx(0.000000, abs=1e-9)
    assert preview_b["final_margin_pct"] == pytest.approx(0.250000, abs=1e-9)

    assert read_quote(api, at_threshold["id"], rep_headers)["volume_rebate_cents"] == 100000
    assert read_quote(api, below["id"], rep_headers)["volume_rebate_cents"] == 0


def test_an_approval_inside_the_surge_window_truncates_expiry_at_quarter_end(
    api, base, rep_headers
):
    """PRD §3.8: "At approval it is re-based: `expires_at` becomes `approved_at` advanced by
    the same `quote_validity_days` days, except that when `approved_at` itself falls inside the
    surge window the result is truncated to the quarter-end instant — a deal approved in the
    closing days of a quarter cannot carry a price into the next one."
    PRD §2.5: "An instant is inside the surge window when it is at or after the surge window's
    start and strictly before the quarter-end instant; the start boundary is inside the window
    and the quarter-end instant itself is not."

    Design: Corner/calculations/approval_inside_the_surge_window_caps_quote_expiry_at_quarter_end
    """
    set_clock(api, "2026-09-25T00:00:00Z")
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Quarter End Push", payment_terms_days=30,
    )
    assert_instant_equals(quote["created_at"], "2026-09-25T00:00:00.000Z", "created_at")
    assert_instant_equals(quote["expires_at"], "2026-10-25T00:00:00.000Z", "expires_at")

    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)

    submitted = submit_quote(api, quote["id"], rep_headers)
    assert submitted["required_approval_level"] == 0
    assert submitted["status"] == "APPROVED"
    assert_instant_equals(submitted["approved_at"], "2026-09-25T00:00:00.000Z", "approved_at")
    assert_instant_equals(submitted["expires_at"], "2026-10-01T00:00:00.000Z", "expires_at")

    assert_instant_equals(
        read_quote(api, quote["id"], rep_headers)["expires_at"],
        "2026-10-01T00:00:00.000Z",
        "expires_at",
    )


def test_the_allocation_residual_lands_entirely_on_the_last_allocable_line(
    api, base, rep_headers, analyst_headers, accountant_headers
):
    """PRD §3.6: "Every allocable line except the last then takes its proportional share
    **floored** to a whole cent — the allocable amount multiplied by that line's standalone
    price, divided by the standalone-price total, with any fraction of a cent discarded rather
    than rounded."
    PRD §3.6: "`allocation_residual_cents` records how much extra the last line absorbed,
    namely its allocated amount less the floored share it would have received under the
    proportional rule."

    Design: Corner/calculations/revrec_waterfall_puts_the_rounding_residual_on_the_last_allocable_line
    """
    quote = create_quote(
        api, base["account"]["id"], 24, rep_headers,
        title="Northwind Multi Element Program", payment_terms_days=30,
    )
    core_line = add_line(api, quote["id"], base["core"]["id"], 60, 0.15, rep_headers)
    assert core_line["final_net_cents"] == 5688600
    assert core_line["extended_list_cents"] == 7200000

    set_clock(api, "2026-08-01T01:00:00Z")
    service_line = add_line(api, quote["id"], base["service"]["id"], 4, 0.10, rep_headers)
    assert service_line["final_net_cents"] == 684000
    assert service_line["extended_list_cents"] == 800000

    rolled = read_quote(api, quote["id"], analyst_headers)
    assert rolled["volume_rebate_cents"] == 127452
    assert rolled["final_net_total_cents"] == 6245148

    assessment = open_revrec(api, quote["id"], accountant_headers)
    assert assessment["arrangement_type"] == "MULTI_ELEMENT"
    assert assessment["status"] == "ASSESSED"
    assert assessment["allocable_amount_cents"] == 6245148
    assert assessment["usage_excluded_cents"] == 0
    assert assessment["allocation_residual_cents"] == 1
    assert assessment["snapshot_quote_version"] == rolled["version"]

    assert assessment["allocation_lines"] == [
        {"quote_line_id": core_line["id"], "ssp_cents": 7200000, "allocated_cents": 5620633},
        {"quote_line_id": service_line["id"], "ssp_cents": 800000, "allocated_cents": 624515},
    ]
