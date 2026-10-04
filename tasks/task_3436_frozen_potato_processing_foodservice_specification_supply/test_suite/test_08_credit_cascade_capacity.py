"""The plant weekly case pool and the chain credit cascade: inclusive pool
boundary, depth-4 hold cascade, pool conservation across suspend/resume, and
the atomic re-reservation rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_active_agreement,
    make_agreement,
    make_chain,
    make_run,
    make_validated_spec,
    set_clock,
    setup_chain_with_validated_spec,
    setup_full_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCOUNT = TEST_USERS["account_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]


def _activate(api, agreement_id):
    return api.activate_supply_agreement(agreement_id, ACCOUNT)


def test_weekly_capacity_exactly_at_pool_limit_succeeds(api):
    """PRD §2.7: "Activating an agreement succeeds only when the remaining
    pool is at least the agreement's `weekly_contracted_cases`; the boundary
    is inclusive, so a reservation that draws the pool down to exactly zero is
    allowed. A request that would oversubscribe the pool is rejected with
    `ERR_WEEK_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/weekly_capacity_reservation_exactly_at_pool_limit_succeeds
    """
    cs = setup_chain_with_validated_spec(api=api)
    chain_id, spec_id = cs["chain"]["id"], cs["spec"]["id"]
    a1 = make_agreement(chain_id, spec_id, api=api, weekly_contracted_cases=60000)
    a2 = make_agreement(chain_id, spec_id, api=api, weekly_contracted_cases=40000)
    a3 = make_agreement(chain_id, spec_id, api=api, weekly_contracted_cases=1)

    ok1 = validate_success(_activate(api, a1["id"]))
    assert ok1["status"] == "ACTIVE", "60000 of 100000 reserved"
    ok2 = validate_success(_activate(api, a2["id"]))
    assert ok2["status"] == "ACTIVE", "the pool drawn to exactly zero is allowed"

    resp = _activate(api, a3["id"])
    validate_error(resp, ApiErrorId.ERR_WEEK_CAPACITY_EXCEEDED)
    assert resp.status_code == 422, "one case over an empty pool oversubscribes"
    still_draft = validate_success(api.get_supply_agreement(a3["id"], ACCOUNT))
    assert still_draft["status"] == "DRAFT"


def test_weekly_capacity_full_pool_single_agreement_then_overflow(api):
    """PRD §2.7: "The plant can ship at most 100,000 finished cases per week
    across all customers."
    PRD §2.7: "the boundary is inclusive, so a reservation that draws the pool
    down to exactly zero is allowed. A request that would oversubscribe the
    pool is rejected with `ERR_WEEK_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/weekly_capacity_reservation_exactly_at_pool_limit_succeeds
    """
    cs = setup_chain_with_validated_spec(api=api)
    chain_id, spec_id = cs["chain"]["id"], cs["spec"]["id"]
    big = make_agreement(chain_id, spec_id, api=api, weekly_contracted_cases=100000)
    extra = make_agreement(chain_id, spec_id, api=api, weekly_contracted_cases=1)

    ok = validate_success(_activate(api, big["id"]))
    assert ok["status"] == "ACTIVE", "a single agreement may take the whole pool"

    resp = _activate(api, extra["id"])
    validate_error(resp, ApiErrorId.ERR_WEEK_CAPACITY_EXCEEDED)
    assert resp.status_code == 422
    assert validate_success(api.get_supply_agreement(extra["id"], ACCOUNT))["status"] == "DRAFT"


def test_credit_hold_cascade_suspends_agreement_cancels_run_releases_lot(api):
    """PRD §3.5: "Placing a chain `ON_HOLD` triggers the deepest cascade in
    the system, applied immediately within the same response: first, every
    `ACTIVE` supply agreement of the chain moves to `SUSPENDED`, releasing its
    reserved weekly cases back to the plant pool; second, for each suspended
    agreement, every production run still in `SCHEDULED` moves to `CANCELLED`;
    third, for each cancelled run, every input lot that was `ALLOCATED` to it
    returns to `IN_STORAGE`, and each lot's facility regains the lot's
    `net_weight_cwt` in its `current_stock_cwt`."

    Design: Difficulty/transitive_cascade/credit_hold_cascade_suspends_agreement_cancels_run_releases_lot
    """
    world = setup_full_pipeline(api=api)
    run = make_run(world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
                   [world["lot"]["id"]], api=api)
    assert validate_success(api.get_storage_facility(world["facility"]["id"], ACCOUNT))[
        "current_stock_cwt"
    ] == 0.0, "the scheduled run holds the lot ALLOCATED, out of the stock sum"

    # A second chain whose agreement will absorb the whole pool after the hold.
    chain_g = make_chain(api=api, chain_code="CH-GAMMA", legal_name="Gamma QSR Holdings",
                         priority_tier="TIER_3_STANDARD")
    spec_g = make_validated_spec(chain_g["id"], api=api, spec_code="SP-G-1",
                                 cut_family="WEDGE", cut_size_mm=12.0, coating_type="NONE",
                                 target_color_units=3.0, max_cook_time_sec=240)

    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )

    chain = validate_success(api.get_customer_chain(world["chain"]["id"], ACCOUNT))
    assert chain["credit_status"] == "ON_HOLD"

    rows, _ = validate_paginated(
        api.list_supply_agreements(ACCOUNT, params={"customer_id": world["chain"]["id"]})
    )
    assert rows[0]["status"] == "SUSPENDED", "cascade link 1: agreement suspended"

    runs, _ = validate_paginated(
        api.list_production_runs(ACCOUNT, params={"agreement_id": world["agreement"]["id"]})
    )
    assert runs[0]["status"] == "CANCELLED", "cascade link 2: the scheduled run is cancelled"

    lots, _ = validate_paginated(
        api.list_potato_lots(ACCOUNT, params={"contract_id": world["contract"]["id"]})
    )
    assert lots[0]["status"] == "IN_STORAGE", "cascade link 3: the lot returns to storage"

    facility = validate_success(api.get_storage_facility(world["facility"]["id"], ACCOUNT))
    assert facility["current_stock_cwt"] == 1000.0, "cascade link 3: the stock is restored"

    agr_g = make_agreement(chain_g["id"], spec_g["id"], api=api,
                           weekly_contracted_cases=100000, price_per_case_cents=290)
    activated = validate_success(_activate(api, agr_g["id"]))
    assert activated["status"] == "ACTIVE", (
        "the released reservation is real: a 100000-case agreement fits the freed pool"
    )


def test_credit_resume_reactivates_agreement_but_not_run_or_lot(api):
    """PRD §3.5: "Returning the chain to `GOOD_STANDING` reverses the first
    link only: every `SUSPENDED` agreement moves back to `ACTIVE` and
    re-reserves its `weekly_contracted_cases` from the pool."
    PRD §3.5: "Cancelled runs and the lots they deallocated are not
    resurrected."

    Design: Difficulty/transitive_cascade/credit_hold_cascade_suspends_agreement_cancels_run_releases_lot
    """
    world = setup_full_pipeline(api=api)
    run = make_run(world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
                   [world["lot"]["id"]], api=api)

    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )
    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "GOOD_STANDING"}, ACCOUNT)
    )

    agreement = validate_success(api.get_supply_agreement(world["agreement"]["id"], ACCOUNT))
    assert agreement["status"] == "ACTIVE", "resume reverses the first link"

    reread_run = validate_success(api.get_production_run(run["id"], ACCOUNT))
    assert reread_run["status"] == "CANCELLED", "the cancelled run is not resurrected"

    lot = validate_success(api.get_potato_lot(world["lot"]["id"], ACCOUNT))
    assert lot["status"] == "IN_STORAGE", "the deallocated lot is not re-allocated"


def test_weekly_capacity_reserve_then_credit_suspend_restores_pool(api):
    """PRD §2.7: "This capacity is a single shared pool, reserved
    incrementally by supply agreements: the reserved amount is the sum of
    `weekly_contracted_cases` over every agreement currently in `ACTIVE`
    status, and the remaining pool is 100,000 minus that sum."
    PRD §2.7: "Suspension releases an agreement's weekly cases back into the
    pool; resumption re-reserves them; completion via the term-end sweep
    releases them permanently."

    Design: Difficulty/compensating_invariant/weekly_capacity_reserve_then_credit_suspend_restores_pool
    """
    cs_a = setup_chain_with_validated_spec(api=api)
    agr_a = make_agreement(cs_a["chain"]["id"], cs_a["spec"]["id"], api=api,
                           weekly_contracted_cases=60000)
    chain_b = make_chain(api=api, chain_code="CH-BETA", legal_name="Beta Diner Group",
                         priority_tier="TIER_2_PREFERRED")
    spec_b = make_validated_spec(chain_b["id"], api=api, spec_code="SP-B-1",
                                 cut_family="CRINKLE", cut_size_mm=10.0,
                                 coating_type="SEASONED", target_color_units=2.0,
                                 max_cook_time_sec=210)
    agr_b1 = make_agreement(chain_b["id"], spec_b["id"], api=api,
                            weekly_contracted_cases=40000, price_per_case_cents=310)
    agr_b2 = make_agreement(chain_b["id"], spec_b["id"], api=api,
                            weekly_contracted_cases=40000, price_per_case_cents=310)

    validate_success(_activate(api, agr_a["id"]))
    validate_success(_activate(api, agr_b1["id"]))  # pool now exactly 0

    resp_full = _activate(api, agr_b2["id"])
    validate_error(resp_full, ApiErrorId.ERR_WEEK_CAPACITY_EXCEEDED)
    assert resp_full.status_code == 422, "nothing left for B2 while A holds 60000"

    validate_success(
        api.set_credit_status(cs_a["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )
    resumed_b2 = validate_success(_activate(api, agr_b2["id"]))
    assert resumed_b2["status"] == "ACTIVE", (
        "the hold released exactly A's 60000-case reservation, so B2 now fits"
    )


def test_credit_resume_is_atomic_when_pool_cannot_refit(api):
    """PRD §2.7: "Re-reservation is atomic across the whole set being resumed:
    if the pool cannot refit every agreement being restored, the operation
    that triggered the resumption fails outright with
    `ERR_WEEK_CAPACITY_EXCEEDED` and nothing changes."

    Design: Difficulty/compensating_invariant/weekly_capacity_reserve_then_credit_suspend_restores_pool
    """
    cs_a = setup_chain_with_validated_spec(api=api)
    agr_a = make_agreement(cs_a["chain"]["id"], cs_a["spec"]["id"], api=api,
                           weekly_contracted_cases=60000)
    chain_b = make_chain(api=api, chain_code="CH-BETA", legal_name="Beta Diner Group",
                         priority_tier="TIER_2_PREFERRED")
    spec_b = make_validated_spec(chain_b["id"], api=api, spec_code="SP-B-1",
                                 cut_family="CRINKLE", cut_size_mm=10.0,
                                 coating_type="SEASONED", target_color_units=2.0,
                                 max_cook_time_sec=210)
    agr_b = make_agreement(chain_b["id"], spec_b["id"], api=api,
                           weekly_contracted_cases=40000, price_per_case_cents=310)

    validate_success(_activate(api, agr_a["id"]))
    validate_success(_activate(api, agr_b["id"]))  # pool 0
    # Hold A: releases 60000 (pool 60000). Take 40000 of it with a new B
    # agreement so the pool cannot refit A on resume.
    validate_success(
        api.set_credit_status(cs_a["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )
    agr_b2 = make_agreement(chain_b["id"], spec_b["id"], api=api,
                            weekly_contracted_cases=40000, price_per_case_cents=310)
    validate_success(_activate(api, agr_b2["id"]))  # pool 20000

    resp = api.set_credit_status(cs_a["chain"]["id"], {"credit_status": "GOOD_STANDING"}, ACCOUNT)
    validate_error(resp, ApiErrorId.ERR_WEEK_CAPACITY_EXCEEDED)
    assert resp.status_code == 422, "20000 free cannot refit A's 60000"

    chain = validate_success(api.get_customer_chain(cs_a["chain"]["id"], ACCOUNT))
    assert chain["credit_status"] == "ON_HOLD", "nothing changes when re-reservation fails"
    agreement = validate_success(api.get_supply_agreement(agr_a["id"], ACCOUNT))
    assert agreement["status"] == "SUSPENDED", "the agreement is not half-resumed"
