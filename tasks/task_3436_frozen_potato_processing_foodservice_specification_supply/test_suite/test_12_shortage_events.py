"""Shortage events: the two allocation variants over the same participants,
participant filtering, and the ordered allocation_results payload."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_active_agreement,
    make_chain,
    make_shortage_event,
    make_validated_spec,
    set_clock,
    setup_chain_with_validated_spec,
    validate_success,
    validate_paginated,
)

GRM = TEST_USERS["grower_relations_manager_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]


def _two_tiered_agreements(api, weekly_a=600, weekly_b=600, price_b=310):
    """Chain A (TIER_1) + chain B (TIER_2), each with an ACTIVE agreement."""
    cs_a = setup_chain_with_validated_spec(api=api)
    agr_a = make_active_agreement(cs_a["chain"]["id"], cs_a["spec"]["id"], api=api,
                                  weekly_contracted_cases=weekly_a)
    chain_b = make_chain(api=api, chain_code="CH-BETA", legal_name="Beta Diner Group",
                         priority_tier="TIER_2_PREFERRED")
    spec_b = make_validated_spec(chain_b["id"], api=api, spec_code="SP-B-1",
                                 cut_family="CRINKLE", cut_size_mm=10.0,
                                 coating_type="SEASONED", target_color_units=2.0,
                                 max_cook_time_sec=210)
    agr_b = make_active_agreement(chain_b["id"], spec_b["id"], api=api,
                                  weekly_contracted_cases=weekly_b, price_per_case_cents=price_b)
    return cs_a["chain"], agr_a, chain_b, agr_b


def _allocation_of(api, chain_id):
    rows, _ = validate_paginated(
        api.list_supply_agreements(ACCOUNT, params={"customer_id": chain_id})
    )
    return rows[0]


def test_shortage_allocation_pro_rata_vs_priority_waterfall(api):
    """PRD §3.8: "Under `PRO_RATA`, the system sums the participants'
    `weekly_contracted_cases` into a total weekly figure and gives each
    participant the smaller of its own `weekly_contracted_cases` and D
    multiplied by its share of that total, rounded down to whole cases — the
    cap keeps a thin participant set from being allocated more than its
    contract."
    PRD §3.8: "Higher tiers are thus filled to contract before lower tiers
    receive anything, so for the same participants and pool the two variants
    produce different allocations."

    Design: Difficulty/dual_variant_calc/shortage_allocation_pro_rata_vs_priority_waterfall
    """
    set_clock(api=api)
    chain_a, agr_a, chain_b, agr_b = _two_tiered_agreements(api, weekly_a=600, weekly_b=600)

    pro_rata = make_shortage_event(api=api, available_week_cases=1000, response_mode="PRO_RATA")
    validate_success(api.execute_allocation(pro_rata["id"], GRM))
    alloc_a_pr = _allocation_of(api, chain_a["id"])["current_week_allocation_cases"]
    alloc_b_pr = _allocation_of(api, chain_b["id"])["current_week_allocation_cases"]
    assert alloc_a_pr == 500, f"floor(1000 x 600/1200) = 500, got {alloc_a_pr}"
    assert alloc_b_pr == 500

    waterfall = make_shortage_event(api=api, available_week_cases=1000,
                                    response_mode="PRIORITY_WATERFALL")
    validate_success(api.execute_allocation(waterfall["id"], GRM))
    alloc_a_wf = _allocation_of(api, chain_a["id"])["current_week_allocation_cases"]
    alloc_b_wf = _allocation_of(api, chain_b["id"])["current_week_allocation_cases"]
    assert alloc_a_wf == 600, "TIER_1 is filled to contract first"
    assert alloc_b_wf == 400, "the remaining 400 of the 1000-case pool go to TIER_2"

    assert alloc_a_pr != alloc_a_wf, (
        "identical participants and pool, different variants -> different allocations"
    )


def test_pro_rata_thin_participant_set_is_capped_at_contract(api):
    """PRD §3.8: "the cap keeps a thin participant set from being allocated
    more than its contract. Any leftover, the pool minus the sum of
    allocations, stays unallocated."
    PRD §3.8: "Tier is ignored in this variant."

    Design: Difficulty/dual_variant_calc/shortage_allocation_pro_rata_vs_priority_waterfall
    """
    set_clock(api=api)
    chain_a, agr_a, chain_b, agr_b = _two_tiered_agreements(api, weekly_a=300, weekly_b=300)

    event = make_shortage_event(api=api, available_week_cases=1000, response_mode="PRO_RATA")
    executed = validate_success(api.execute_allocation(event["id"], GRM))
    assert executed["status"] == "EXECUTED"

    alloc_a = _allocation_of(api, chain_a["id"])["current_week_allocation_cases"]
    alloc_b = _allocation_of(api, chain_b["id"])["current_week_allocation_cases"]
    # floor(1000 x 300/600) = 500 would over-allocate; the contract cap binds.
    assert alloc_a == 300 and alloc_b == 300, (
        f"each participant is capped at its 300-case contract (got {alloc_a}/{alloc_b}); "
        "the 400-case leftover stays unallocated"
    )
    results_by_id = {r["agreement_id"]: r["allocated_cases"] for r in executed["allocation_results"]}
    assert results_by_id == {agr_a["id"]: 300, agr_b["id"]: 300}


def test_shortage_allocation_excludes_suspended_agreements_and_caps_at_contract(api):
    """PRD §3.8: "Executing the allocation — an action reserved to the
    `GrowerRelationsManager` and rejected with `ERR_SHORTAGE_EVENT_NOT_OPEN`
    once the event has closed — distributes the available pool across every
    agreement in `ACTIVE` status at execution time; `SUSPENDED` and
    `COMPLETED` agreements do not participate."
    PRD §3.8: "gives each participant the smaller of its own
    `weekly_contracted_cases` and D multiplied by its share of that total,
    rounded down to whole cases".

    Design: Corner/calculations/shortage_allocation_excludes_suspended_agreements_and_caps_at_contract
    """
    set_clock(api=api)
    chain_a, agr_a, chain_b, agr_b = _two_tiered_agreements(api, weekly_a=600, weekly_b=400)
    validate_success(api.set_credit_status(chain_b["id"], {"credit_status": "ON_HOLD"}, ACCOUNT))

    event = make_shortage_event(api=api, available_week_cases=1000, response_mode="PRO_RATA")
    validate_success(api.execute_allocation(event["id"], GRM))

    alloc_a = _allocation_of(api, chain_a["id"])
    assert alloc_a["current_week_allocation_cases"] == 600, (
        "sole ACTIVE participant: min(600, floor(1000 x 600/600)) = 600 — the contract cap, "
        "not the whole pool"
    )
    alloc_b = _allocation_of(api, chain_b["id"])
    assert alloc_b["status"] == "SUSPENDED"
    assert alloc_b["current_week_allocation_cases"] == 400, (
        "a non-participant's stored allocation is not recomputed"
    )


def test_execute_allocation_response_carries_ordered_waterfall_results(api):
    """PRD §3.8: "Under `PRIORITY_WATERFALL`, participants are ordered by
    their customer's `priority_tier`, with `TIER_1_STRATEGIC` first, then
    `TIER_2_PREFERRED`, then `TIER_3_STANDARD`, and ties broken by the
    agreement's `created_at` in ascending order."
    PRD §3.8: "Both variants overwrite each participant's
    `current_week_allocation_cases` and record the event's
    `allocation_results` as a list of per-agreement entries, each naming an
    `agreement_id` and its `allocated_cases`, written in the same
    per-participant order in which they were computed."

    Design: Corner/endpoints/execute_allocation_response_carries_ordered_waterfall_results
    """
    set_clock(api=api)
    chain_a, agr_a, chain_b, agr_b = _two_tiered_agreements(api, weekly_a=600, weekly_b=600)

    event = make_shortage_event(api=api, available_week_cases=1000,
                                response_mode="PRIORITY_WATERFALL")
    executed = validate_success(api.execute_allocation(event["id"], GRM))
    assert executed["status"] == "EXECUTED"
    assert executed["allocation_results"] == [
        {"agreement_id": agr_a["id"], "allocated_cases": 600},
        {"agreement_id": agr_b["id"], "allocated_cases": 400},
    ], "waterfall results arrive in tier order on the execute response itself"
