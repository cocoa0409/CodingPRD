"""Booking the auditors: half-open audit windows, aggregate capacity and the
suspension cascade that an audit-backed decision can trigger."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_item_state,
    assert_landed_costs,
    assert_money_cents,
    assert_status,
    assert_supplier_status,
    assert_version_is,
)
from test_helpers.constants import (
    AUDIT_FINALIZED,
    AUDIT_ONGOING_QUALITY,
    AUDIT_RESULT_PASS,
    AUDIT_SCHEDULED,
    COST_MODEL_ACCEPTED,
    COST_MODEL_SUBMITTED,
    ITEM_SOURCED,
    POSTURE_SUSPENDED,
    SUPPLIER_PROSPECT,
    SUPPLIER_SUSPENDED,
)
from test_helpers.fixtures import (
    add_ongoing_audit,
    build_chain,
    read_cost_model,
    read_item,
    read_supplier,
    suspend_supplier,
)
from test_helpers.test_users import QUALITY_HEADERS, SOURCING_HEADERS


def _two_overlapping_audits(api):
    """A supplier already covered by two audits over 2026-09-11T12:00Z."""
    ctx = build_chain(api, upto=5)
    first = add_ongoing_audit(
        api,
        ctx["supplier_id"],
        "2026-09-10T08:00:00Z",
        "2026-09-12T08:00:00Z",
    )
    second = add_ongoing_audit(
        api,
        ctx["supplier_id"],
        "2026-09-11T00:00:00Z",
        "2026-09-13T00:00:00Z",
    )
    return ctx, first, second


def test_third_audit_covering_a_shared_instant_is_rejected(api):
    """Two audits may overlap; a third covering the same instant may not.

    PRD 3.2: "Audit windows are half-open, and no more than two audits of the
    same supplier may cover any single instant; a third overlapping audit is
    refused with `ERR_AUDIT_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/supplier_audit_half_open_aggregate_capacity_two
    """
    ctx, first, second = _two_overlapping_audits(api)

    response = api.create_plant_audit(
        f.plant_audit_payload(
            ctx["supplier_id"],
            audit_type=AUDIT_ONGOING_QUALITY,
            window_start="2026-09-11T12:00:00Z",
            window_end="2026-09-11T18:00:00Z",
        ),
        QUALITY_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_CAPACITY_EXCEEDED.value, 409)

    rows, meta = validate_paginated(
        api.list_plant_audits(QUALITY_HEADERS, params={"supplier_id": ctx["supplier_id"]})
    )
    assert meta["total_count"] == 2, "the refused third booking left no row behind"
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_audit_beginning_exactly_when_another_ends_is_accepted(api):
    """The excluded end instant means a touching audit shares no instant.

    PRD 3.2: "Because the interval excludes its end instant, an audit beginning
    exactly when another ends does not count as covering a shared instant, and no
    changeover buffer is applied to audit windows."

    PRD 3.2: "A newly scheduled audit sits at `SCHEDULED` with `result` and all
    four pillar scores null."

    Design: Difficulty/resource_temporal_overlap/supplier_audit_half_open_aggregate_capacity_two
    """
    ctx, _first, _second = _two_overlapping_audits(api)

    booked = validate_success(
        api.create_plant_audit(
            f.plant_audit_payload(
                ctx["supplier_id"],
                audit_type=AUDIT_ONGOING_QUALITY,
                window_start="2026-09-12T08:00:00Z",
                window_end="2026-09-12T20:00:00Z",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )

    assert_status(booked, AUDIT_SCHEDULED, "plant audit")
    assert booked["result"] is None
    for pillar in (
        "food_safety_score",
        "sanitation_score",
        "capacity_score",
        "traceability_score",
    ):
        assert booked[pillar] is None, f"{pillar} is null until finalization"
    _rows, meta = validate_paginated(
        api.list_plant_audits(QUALITY_HEADERS, params={"supplier_id": ctx["supplier_id"]})
    )
    assert meta["total_count"] == 3


def test_audit_with_a_zero_length_window_is_rejected(api):
    """An audit that ends exactly where it starts covers nothing at all.

    PRD 3.2: "`window_end` must be strictly after `window_start` — an inverted or
    zero-length window is refused with `ERR_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/plant_audit_with_zero_length_window_rejected
    """
    ctx = build_chain(api, upto=5)

    response = api.create_plant_audit(
        f.plant_audit_payload(
            ctx["supplier_id"],
            window_start="2026-07-20T08:00:00Z",
            window_end="2026-07-20T08:00:00Z",
        ),
        QUALITY_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_INVALID.value, 422)

    _rows, meta = validate_paginated(
        api.list_plant_audits(QUALITY_HEADERS, params={"supplier_id": ctx["supplier_id"]})
    )
    assert meta["total_count"] == 0, "a refused window creates no audit"
    assert_supplier_status(read_supplier(api, ctx["supplier_id"]), SUPPLIER_PROSPECT)


def test_suspending_a_supplier_suspends_the_posture_of_its_awarded_items(
    api, sourced_item
):
    """Suspension reaches through the award to every item still in development.

    PRD 3.2: "every item awarded to that supplier whose `development_status` is
    neither `RATIONALIZED` nor `DISCONTINUED` has its `quality_posture` set to
    `SUSPENDED`; every production run of those items whose status is `SCHEDULED`
    or `APPROVED` transitions to `HOLD` with `hold_reason` recorded as
    `SUPPLIER_SUSPENDED`; and every one of those touched rows has its `version`
    incremented."

    Design: Corner/state_machines/supplier_suspend_cascades_posture_suspended_to_active_items
    """
    supplier = suspend_supplier(api, sourced_item["supplier_id"])

    assert_supplier_status(supplier, SUPPLIER_SUSPENDED)
    item = read_item(api, sourced_item["item_id"])
    assert_item_state(item, ITEM_SOURCED, POSTURE_SUSPENDED)
    cost_model = read_cost_model(api, sourced_item["cost_model_id"])
    assert_status(cost_model, COST_MODEL_ACCEPTED, "cost model")


def test_audited_landed_cost_follows_the_latest_finalized_audit_window_end(api):
    """Two finalized audits compete and the later window_end supplies the yield.

    PRD 3.3: "The audit chosen is the supplier's finalized plant audit with the
    greatest `window_end`, tie-broken by the greater `created_at`; audits still
    `SCHEDULED` never participate."

    PRD 3.3: "The **audited-actual** variant selects the `audited_yield_pct`
    measured by an audit and a scrap allowance of zero cents when that audit's
    `result` is `PASS` or 3 cents when the result is `CONDITIONAL`; its result is
    stored in `landed_unit_cost_cents_audited`"

    Design: Corner/calculations/landed_cost_audited_variant_selects_latest_finalized_audit_window_end
    """
    ctx = build_chain(api, upto=10)
    later = validate_success(
        api.create_plant_audit(
            f.plant_audit_payload(
                ctx["supplier_id"],
                window_start="2026-07-25T08:00:00Z",
                window_end="2026-07-26T17:00:00Z",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )
    later = validate_success(
        api.finalize_plant_audit(
            later["id"],
            f.audit_finalize_payload(
                food_safety_score=95,
                sanitation_score=90,
                capacity_score=88,
                traceability_score=92,
                audited_yield_pct=88.0,
            ),
            QUALITY_HEADERS,
        )
    )
    pending = validate_success(
        api.create_plant_audit(
            f.plant_audit_payload(
                ctx["supplier_id"],
                window_start="2026-08-10T08:00:00Z",
                window_end="2026-08-11T17:00:00Z",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )

    cost_model = validate_success(
        api.create_cost_model(
            f.cost_model_payload(ctx["item_id"], ctx["supplier_id"]),
            ctx["supplier_headers"],
        ),
        expected_status=201,
    )

    assert_money_cents(cost_model["effective_base_cents"], 221, "effective_base_cents")
    assert_landed_costs(cost_model, as_quoted=269, audited=291)
    assert_status(cost_model, COST_MODEL_SUBMITTED, "cost model")
    assert_version_is(cost_model, 1, "cost model")
    assert_status(later, AUDIT_FINALIZED, "plant audit")
    assert later["result"] == AUDIT_RESULT_PASS
    assert_status(pending, AUDIT_SCHEDULED, "plant audit")
    assert pending["result"] is None, "a scheduled audit never supplies a yield"
