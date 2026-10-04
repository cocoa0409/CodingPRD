"""Write-down proposal evidence gates: forecast actualization, miss truth,
product/channel match, expiry proximity, recall flag, quantity bound, and
batch writability (PRD section 3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    create_write_down_payload, make_demand_planner_headers,
    setup_completed_batch, setup_recalled_batch,
    create_locked_forecast, create_actualized_forecast, actualize_forecast,
    propose_write_down, post_write_down,
    fetch_batch, fetch_forecast,
)

_PLANNER = "planner-1"


def _propose_raw(api, batch_id, quantity_cases, reason,
                 demand_forecast_id=None):
    return api.create_inventory_write_down(
        create_write_down_payload(batch_id, quantity_cases, reason,
                                  demand_forecast_id=demand_forecast_id),
        make_demand_planner_headers(_PLANNER))


def test_forecast_miss_proposal_rejected_while_forecast_locked(api):
    """PRD section 3.8: "`FORECAST_MISS` requires a `demand_forecast_id` ...
    pointing at an `ACTUALIZED` forecast (`ERR_FORECAST_NOT_ACTUALIZED`)" —
    a merely LOCKED forecast cannot evidence a miss.

    Design: Difficulty/cross_entity_state_dependency/cesd_forecast_miss_writedown_requires_actualized
    """
    ctx = setup_completed_batch(invoiced_unit_cost_cents=465,
                                product_overrides={
                                    "product_code": "PROD-CE-2"})
    forecast = create_locked_forecast(ctx["product"]["id"],
                                      channel="RETAIL_FROZEN",
                                      week_start="2026-09-07T00:00:00Z",
                                      forecast_cases=200)
    resp = _propose_raw(api, ctx["batch"]["id"], 2, "FORECAST_MISS",
                        demand_forecast_id=forecast["id"])
    validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_ACTUALIZED)


def test_forecast_miss_proposal_accepted_after_actualized_miss(api):
    """PRD section 3.8: after ACTUALIZED with actual 150 against forecast 200
    the variance is -25.00 percent, so "`is_miss` is true when that variance
    reaches negative 20.00 percent or worse" holds, and "A valid proposal
    lands in `PROPOSED` ... valued provisionally at full cost:
    `provisional_amount_cents` is the quantity multiplied by the batch's
    `unit_cost_cents_per_case`" (2 x 4250 = 8500).

    Design: Difficulty/cross_entity_state_dependency/cesd_forecast_miss_writedown_requires_actualized
    """
    ctx = setup_completed_batch(invoiced_unit_cost_cents=465,
                                product_overrides={
                                    "product_code": "PROD-CE-2"})
    forecast = create_locked_forecast(ctx["product"]["id"],
                                      channel="RETAIL_FROZEN",
                                      week_start="2026-09-07T00:00:00Z",
                                      forecast_cases=200)
    forecast = actualize_forecast(forecast["id"], 150)
    assert forecast["variance_pct"] == pytest.approx(-25.00, abs=1e-9)
    assert forecast["is_miss"] is True
    wd = propose_write_down(ctx["batch"]["id"], quantity_cases=2,
                            reason="FORECAST_MISS",
                            demand_forecast_id=forecast["id"],
                            proposer_user_id=_PLANNER)
    assert wd["status"] == "PROPOSED"
    assert wd["provisional_amount_cents"] == 8500


def test_forecast_miss_requires_an_actual_miss(api):
    """PRD section 3.8: the evidence forecast must be one "whose `is_miss` is
    true (`ERR_FORECAST_NO_MISS`)" — an ACTUALIZED forecast at variance
    -5.00 (190 vs 200) is not a miss.

    Design: Corner/validations/cn_val_forecast_no_miss
    """
    ctx = setup_completed_batch(product_overrides={
        "product_code": "PROD-K-34"})
    forecast = create_actualized_forecast(
        ctx["product"]["id"], 190, channel="RETAIL_FROZEN",
        week_start="2026-09-07T00:00:00Z", forecast_cases=200)
    resp = _propose_raw(api, ctx["batch"]["id"], 2, "FORECAST_MISS",
                        demand_forecast_id=forecast["id"])
    validate_error(resp, ApiErrorId.ERR_FORECAST_NO_MISS)


def test_forecast_miss_requires_matching_channel(api):
    """PRD section 3.8: the evidence forecast must be one "whose product and
    channel match the batch's (`ERR_FORECAST_MISMATCH`)" — a FOODSERVICE
    forecast cannot justify writing down a RETAIL_FROZEN batch.

    Design: Corner/validations/cn_val_forecast_mismatch_channel
    """
    ctx = setup_completed_batch(product_overrides={
        "product_code": "PROD-K-35"})
    forecast = create_actualized_forecast(
        ctx["product"]["id"], 150, channel="FOODSERVICE",
        week_start="2026-09-07T00:00:00Z", forecast_cases=200)
    resp = _propose_raw(api, ctx["batch"]["id"], 2, "FORECAST_MISS",
                        demand_forecast_id=forecast["id"])
    validate_error(resp, ApiErrorId.ERR_FORECAST_MISMATCH)


def test_expiry_risk_requires_proximity_to_expiry(api):
    """PRD section 3.8: "`EXPIRY_RISK` requires the batch to be at most 15
    days from expiry, or already past it (`ERR_NOT_EXPIRY_RISK`)" — a
    RETAIL_FROZEN batch 270 days from expiry is not at risk.

    Design: Corner/validations/cn_val_not_expiry_risk
    """
    ctx = setup_completed_batch()
    resp = _propose_raw(api, ctx["batch"]["id"], 2, "EXPIRY_RISK")
    validate_error(resp, ApiErrorId.ERR_NOT_EXPIRY_RISK)


def test_recall_writedown_requires_recall_flag(api):
    """PRD section 3.8: "`RECALL` requires the batch's `recall_flag` to be
    raised (`ERR_RUN_NOT_RECALLED`)" — a batch from a merely COMPLETED run
    carries a clear flag.

    Design: Corner/validations/cn_val_run_not_recalled
    """
    ctx = setup_completed_batch()
    resp = _propose_raw(api, ctx["batch"]["id"], 2, "RECALL")
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_RECALLED)


def test_writedown_quantity_bounded_by_available_cases(api):
    """PRD section 3.8: "the quantity may not exceed the batch's
    `available_cases` (`ERR_WRITEDOWN_EXCEEDS_AVAILABLE`)" — 11 of 10
    available fails even when the RECALL gate itself passes.

    Design: Corner/validations/cn_val_writedown_exceeds_available
    """
    ctx = setup_recalled_batch()
    resp = _propose_raw(api, ctx["batch"]["id"], 11, "RECALL")
    validate_error(resp, ApiErrorId.ERR_WRITEDOWN_EXCEEDS_AVAILABLE)


def test_fully_written_off_batch_is_not_writable(api):
    """PRD section 3.8: "The batch must be writable — a `WRITTEN_OFF` or
    `DEPLETED` batch is refused with `ERR_BATCH_NOT_WRITABLE`, a gate
    evaluated ahead of the quantity bound (§2.8)". PRD section 3.7:
    "`WRITTEN_OFF` when `written_off_cases` equals `quantity_cases`".

    Design: Corner/validations/cn_val_batch_not_writable_after_full_writedown
    """
    ctx = setup_recalled_batch()
    wd = propose_write_down(ctx["batch"]["id"], quantity_cases=10,
                            reason="RECALL", proposer_user_id=_PLANNER)
    post_write_down(wd["id"], "fin-1")
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["derived_status"] == "WRITTEN_OFF"
    resp = _propose_raw(api, batch["id"], 1, "RECALL")
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_WRITABLE)
