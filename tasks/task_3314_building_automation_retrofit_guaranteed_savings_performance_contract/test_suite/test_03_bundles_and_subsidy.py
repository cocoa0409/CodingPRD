"""Bundle derived figures and the subsidy waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_contract,
    create_measure_payload,
    eng_headers,
    make_actor_ids,
    own_headers,
    reset_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_bundle_payload

WF_MEASURES = [
    dict(measure_type="LIGHTING", installed_cost_cents=100000,
         annual_savings_cents=50000),
    dict(measure_type="CONTROLS", installed_cost_cents=400000,
         annual_savings_cents=100000),
    dict(measure_type="ENVELOPE", installed_cost_cents=800000,
         annual_savings_cents=80000),
]


def _waterfall_bundle(api, eng_id, owner_id):
    """Contract in AUDIT with the A/B/C mixed-payback bundle PROPOSED then
    APPROVED. Returns (contract_id, bundle, [mA, mB, mC])."""
    contract = create_contract(eng_id, guaranteed_annual_savings_cents=300000,
                               contract_value_cents=3000000)
    cid = contract["id"]
    bundle = validate_success(
        api.create_bundle(cid, create_bundle_payload(name="Mixed Payback"),
                          eng_headers(eng_id)),
        201,
    )
    measures = [
        validate_success(
            api.create_measure(cid, bundle["id"], create_measure_payload(**m),
                               eng_headers(eng_id)),
            201,
        )
        for m in WF_MEASURES
    ]
    validate_success(api.propose_bundle(cid, bundle["id"], eng_headers(eng_id)))
    bundle = validate_success(
        api.approve_bundle(cid, bundle["id"], own_headers(owner_id))
    )
    return cid, bundle, measures


def test_blended_payback_null_when_bundle_savings_sum_zero(api):
    """PRD §3.2: "If the summed annual savings are zero the blended payback
    is `null` — the platform never divides by zero."
    PRD §3.2: "a bundle whose blended payback outlasts the guarantee is
    rejected with `ERR_BUNDLE_PAYBACK_EXCEEDS_TERM` (HTTP 422)"

    Design: Corner/calculations/blended_payback_null_when_bundle_savings_sum_zero
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = create_contract(eng_id)
    cid = contract["id"]
    bundle = validate_success(
        api.create_bundle(cid, create_bundle_payload(name="ZeroSaver"),
                          eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.create_measure(
            cid, bundle["id"],
            create_measure_payload(measure_type="OTHER",
                                   installed_cost_cents=100000,
                                   annual_savings_cents=0),
            eng_headers(eng_id),
        ),
        201,
    )
    bundle = validate_success(
        api.propose_bundle(cid, bundle["id"], eng_headers(eng_id))
    )
    assert bundle["blended_payback_years"] is None
    response = api.approve_bundle(cid, bundle["id"], own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_BUNDLE_PAYBACK_EXCEEDS_TERM.value, 422)
    reread = validate_success(api.get_bundle(cid, bundle["id"], own_headers(owner_id)))
    assert reread["status"] == "PROPOSED"


def test_excluded_measure_contributes_nothing_to_blended_payback(api):
    """PRD §3.2: "Excluding a measure recomputes the bundle's
    `blended_payback_years` and `subsidy_pool_cents`"
    PRD §3.2: "while the bundle is `DRAFT` or `PROPOSED` the counted set is
    measures in `PROPOSED` or `INCLUDED`"

    Design: Corner/calculations/excluded_measure_contributes_nothing_to_blended_payback
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = create_contract(eng_id)
    cid = contract["id"]
    bundle = validate_success(
        api.create_bundle(cid, create_bundle_payload(), eng_headers(eng_id)), 201
    )
    validate_success(
        api.create_measure(cid, bundle["id"], create_measure_payload(
            measure_type="LIGHTING", installed_cost_cents=100000,
            annual_savings_cents=50000), eng_headers(eng_id)),
        201,
    )
    mb = validate_success(
        api.create_measure(cid, bundle["id"], create_measure_payload(
            measure_type="CONTROLS", installed_cost_cents=400000,
            annual_savings_cents=100000), eng_headers(eng_id)),
        201,
    )
    validate_success(api.propose_bundle(cid, bundle["id"], eng_headers(eng_id)))
    validate_success(
        api.exclude_measure(cid, bundle["id"], mb["id"], eng_headers(eng_id))
    )
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    assert bundle["blended_payback_years"] == pytest.approx(2.0)
    assert bundle["subsidy_pool_cents"] == 50000


def test_subsidy_waterfall_assigns_draws_by_payback_order(api):
    """PRD §3.2: "The `subsidy_pool_cents` is the bundle's cross-subsidy
    capacity: for each counted measure whose `simple_payback_years` is at most
    3 years, the pool accrues the larger of zero and the measure's
    `annual_savings_cents` multiplied by 3 minus its `installed_cost_cents`."
    PRD §3.2: "Walking that order, each measure whose simple payback exceeds 7
    years may draw from the pool: its need is its `installed_cost_cents` minus
    its `annual_savings_cents` multiplied by 7, and its `subsidy_draw_cents`
    becomes the smaller of that need and the remaining pool, which is then
    decremented by the draw."

    Design: Difficulty/combinatorial_formula/subsidy_waterfall_rounding_and_order_mode_b
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    cid, bundle, measures = _waterfall_bundle(api, eng_id, owner_id)
    assert bundle["subsidy_pool_cents"] == 50000
    assert bundle["blended_payback_years"] == pytest.approx(5.65)
    ma, mb, mc = [
        validate_success(api.get_measure(cid, bundle["id"], m["id"],
                                         eng_headers(eng_id)))
        for m in measures
    ]
    assert ma["subsidy_draw_cents"] == 0
    assert mb["subsidy_draw_cents"] == 0
    assert mc["subsidy_draw_cents"] == 50000
    assert ma["status"] == "INCLUDED"
    assert mc["status"] == "INCLUDED"


def test_subsidy_waterfall_includes_proposed_measures_on_approve(api):
    """PRD §3.2: "On approval, every `PROPOSED` measure in the bundle moves
    to `INCLUDED`, the subsidy waterfall runs, and the bundle's `version`
    increments."
    PRD §3.2: "Every other `INCLUDED` measure receives a `subsidy_draw_cents`
    of zero, and measures start at a default draw of zero. `EXCLUDED` measures
    never draw."

    Design: Difficulty/combinatorial_formula/subsidy_waterfall_rounding_and_order_mode_b
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    cid, bundle, measures = _waterfall_bundle(api, eng_id, owner_id)
    # All three PROPOSED measures became INCLUDED; only the payback-10
    # measure drew from the pool, and only up to the pool size.
    statuses = {}
    draws = {}
    for m in measures:
        current = validate_success(
            api.get_measure(cid, bundle["id"], m["id"], eng_headers(eng_id))
        )
        statuses[m["measure_type"]] = current["status"]
        draws[m["measure_type"]] = current["subsidy_draw_cents"]
    assert statuses == {"LIGHTING": "INCLUDED", "CONTROLS": "INCLUDED",
                        "ENVELOPE": "INCLUDED"}
    assert draws["LIGHTING"] == 0       # payback 2.0 feeds the pool, never draws
    assert draws["CONTROLS"] == 0       # payback 4.0 not eligible to draw
    assert draws["ENVELOPE"] == 50000   # need 240000 capped by pool 50000


def test_subsidy_pool_conserved_across_measure_exclusion(api):
    """PRD §3.2: "Excluding a subsidized measure returns its draw to the
    bundle's pool and re-runs the subsidy waterfall over the remaining
    included measures."

    Design: Difficulty/compensating_invariant/subsidy_pool_conserved_across_measure_exclusion
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    cid, bundle, measures = _waterfall_bundle(api, eng_id, owner_id)
    mc = measures[2]
    excluded = validate_success(
        api.exclude_measure(cid, bundle["id"], mc["id"], eng_headers(eng_id))
    )
    assert excluded["status"] == "EXCLUDED"
    assert excluded["subsidy_draw_cents"] == 0
    ma = validate_success(
        api.get_measure(cid, bundle["id"], measures[0]["id"], eng_headers(eng_id))
    )
    mb = validate_success(
        api.get_measure(cid, bundle["id"], measures[1]["id"], eng_headers(eng_id))
    )
    assert ma["subsidy_draw_cents"] + mb["subsidy_draw_cents"] == 0
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    assert bundle["subsidy_pool_cents"] == 50000


def test_subsidy_pool_undrawn_after_exclusion_recomputes_blended_payback(api):
    """PRD §3.2: "if the excluded measure had a `subsidy_draw_cents` greater
    than zero, that draw returns to the pool and the waterfall re-runs over
    the remaining `INCLUDED` measures."
    PRD §3.2: "The `blended_payback_years` is the sum of
    `installed_cost_cents` over the counted measures divided by the sum of
    their `annual_savings_cents`, reported at 2 decimal places rounded
    half-up"

    Design: Difficulty/compensating_invariant/subsidy_pool_conserved_across_measure_exclusion
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    cid, bundle, measures = _waterfall_bundle(api, eng_id, owner_id)
    validate_success(
        api.exclude_measure(cid, bundle["id"], measures[2]["id"],
                            eng_headers(eng_id))
    )
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    # surviving INCLUDED measures: 100000/50000 and 400000/100000
    assert bundle["blended_payback_years"] == pytest.approx(3.33)
    ma = validate_success(
        api.get_measure(cid, bundle["id"], measures[0]["id"], eng_headers(eng_id))
    )
    mb = validate_success(
        api.get_measure(cid, bundle["id"], measures[1]["id"], eng_headers(eng_id))
    )
    assert ma["status"] == "INCLUDED"
    assert mb["status"] == "INCLUDED"
    assert ma["subsidy_draw_cents"] == 0
    assert mb["subsidy_draw_cents"] == 0
