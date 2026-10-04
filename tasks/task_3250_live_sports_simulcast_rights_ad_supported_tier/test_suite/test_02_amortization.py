"""Amortization variants and the property-economics report (PRD §3.9)."""
from test_helpers import (
    RM,
    assert_property,
    create_active_property,
    create_property,
    create_window,
    get_success_data,
    make_completed_window,
    make_live_window,
    provision_window_capacity,
    set_clock,
    validate_success,
)


def _report(api, property_id):
    resp = api.get_property_economics(RM, params={"property_id": property_id})
    return validate_success(resp)


def test_amortization_straight_line_two_elapsed_months(api):
    """PRD §3.9: "The per-period fee is the floor of `rights_fee_cents`
    divided by `periods` — the floor is applied to the per-period figure
    **first**. The amortized fee is then the per-period fee multiplied by
    the number of elapsed periods at the current logical time, capped at
    `rights_fee_cents`."

    With fee 120000 over a 4-month term and the clock at the start of the
    third month (2 elapsed periods), amortized = floor(120000/4) * 2 = 60000.

    Design: Difficulty/dual_variant_calc/amortization_straight_line_vs_event_weighted_same_property_data
    """
    prop = create_active_property(
        rights_fee_cents=120000,
        term_start="2026-09-01T00:00:00Z",
        term_end="2027-01-01T00:00:00Z",
        amortization_method="STRAIGHT_LINE",
    )
    set_clock("2026-11-01T00:00:00Z")
    data = _report(api, prop["id"])
    assert data["amortized_fee_cents"] == 60000, (
        f"STRAIGHT_LINE amortized_fee_cents expected 60000, got {data['amortized_fee_cents']}"
    )


def test_amortization_event_weighted_single_completed_simulcast(api):
    """PRD §3.9: "Each window carries a weight: an `EXCLUSIVE` window weighs
    3, a `SIMULCAST` window weighs 1. The total weight is the sum of weights
    over all windows of the property whose status is neither `CANCELLED` nor
    `REPLACED`. The done weight is the sum of weights over the `COMPLETE`
    subset. The amortized fee is the floor of `rights_fee_cents` times the
    done weight divided by the maximum of the total weight and 1."

    One SIMULCAST window, COMPLETE: floor(120000 * 1/1) = 120000.

    Design: Difficulty/dual_variant_calc/amortization_straight_line_vs_event_weighted_same_property_data
    """
    prop, window = make_completed_window(
        property_overrides={
            "rights_fee_cents": 120000,
            "term_start": "2026-09-01T00:00:00Z",
            "term_end": "2027-01-01T00:00:00Z",
            "amortization_method": "EVENT_WEIGHTED",
        },
        window_overrides={
            "rights_mode": "SIMULCAST",
            "scheduled_start": "2026-09-10T17:00:00Z",
            "scheduled_end": "2026-09-10T20:00:00Z",
            "replay_hours": 24,
        },
    )
    set_clock("2026-11-01T00:00:00Z")
    data = _report(api, prop["id"])
    assert data["amortized_fee_cents"] == 120000, (
        f"EVENT_WEIGHTED amortized_fee_cents expected 120000, got {data['amortized_fee_cents']}"
    )


def test_amortization_variants_diverge_on_same_inputs(api):
    """PRD §3.9: "The computation has two variants selected by the property's
    `amortization_method`." plus the straight-line and event-weighted
    formulas quoted in the sibling tests.

    Same fee (120000), same 4-month term, same single completed SIMULCAST
    window, same logical date: STRAIGHT_LINE yields 60000 while
    EVENT_WEIGHTED yields 120000.

    Design: Difficulty/dual_variant_calc/amortization_straight_line_vs_event_weighted_same_property_data
    """
    prop_str, _ = make_completed_window(
        property_overrides={
            "rights_fee_cents": 120000,
            "term_start": "2026-09-01T00:00:00Z",
            "term_end": "2027-01-01T00:00:00Z",
            "amortization_method": "STRAIGHT_LINE",
        },
        window_overrides={
            "rights_mode": "SIMULCAST",
            "scheduled_start": "2026-09-10T17:00:00Z",
            "scheduled_end": "2026-09-10T20:00:00Z",
        },
    )
    prop_wgt, _ = make_completed_window(
        property_overrides={
            "rights_fee_cents": 120000,
            "term_start": "2026-09-01T00:00:00Z",
            "term_end": "2027-01-01T00:00:00Z",
            "amortization_method": "EVENT_WEIGHTED",
        },
        window_overrides={
            "rights_mode": "SIMULCAST",
            "scheduled_start": "2026-09-10T17:00:00Z",
            "scheduled_end": "2026-09-10T20:00:00Z",
        },
    )
    set_clock("2026-11-01T00:00:00Z")
    amort_str = _report(api, prop_str["id"])["amortized_fee_cents"]
    amort_wgt = _report(api, prop_wgt["id"])["amortized_fee_cents"]
    assert amort_str == 60000
    assert amort_wgt == 120000
    assert amort_str != amort_wgt


def test_amortization_event_weighted_exclusive_weight_three(api):
    """PRD §3.9: "an `EXCLUSIVE` window weighs 3, a `SIMULCAST` window weighs
    1 ... The amortized fee is the floor of `rights_fee_cents` times the
    done weight divided by the maximum of the total weight and 1."

    Fee 80000; one COMPLETE EXCLUSIVE (weight 3) plus one SCHEDULED
    SIMULCAST (weight 1): floor(80000 * 3/4) = 60000.

    Design: Corner/calculations/amortization_constants_applied_exclusive_weight_three
    """
    prop, _ = make_completed_window(
        property_overrides={
            "rights_fee_cents": 80000,
            "amortization_method": "EVENT_WEIGHTED",
        },
        window_overrides={
            "rights_mode": "EXCLUSIVE",
            "scheduled_start": "2026-09-27T18:00:00Z",
            "scheduled_end": "2026-09-27T21:00:00Z",
        },
    )
    create_window(
        prop["id"],
        rights_mode="SIMULCAST",
        scheduled_start="2026-10-27T18:00:00Z",
        scheduled_end="2026-10-27T21:00:00Z",
    )
    data = _report(api, prop["id"])
    assert data["amortized_fee_cents"] == 60000, (
        f"expected floor(80000*3/4)=60000, got {data['amortized_fee_cents']}"
    )
