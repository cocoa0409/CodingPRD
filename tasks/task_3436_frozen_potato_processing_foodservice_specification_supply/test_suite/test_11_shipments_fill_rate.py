"""Cold-chain shipments: terminal-state lockdown, the excursion threshold,
per-line credit/invoice rounding, fill-rate composition, the SLA-review
cascade, and the credit-hold shipment gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_shipment_payload,
    deliver_lot,
    make_released_run,
    make_shipment,
    setup_full_pipeline,
    setup_released_run,
    validate_error,
    validate_paginated,
    validate_success,
)

QA = TEST_USERS["qa_lead_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


def _two_released_runs(api, price_per_case_cents=299):
    """Full pipeline with R1 and R2 both RELEASED (620 cases each)."""
    world = setup_full_pipeline(api=api, agreement_overrides={
        "weekly_contracted_cases": 10000, "price_per_case_cents": price_per_case_cents,
    })
    lot_b = deliver_lot(world["contract"]["id"], world["facility"]["id"],
                        world["grower"]["id"], api=api)
    run1 = make_released_run(world["line"]["id"], world["spec"]["id"],
                             world["agreement"]["id"], [world["lot"]["id"]], api=api)
    run2 = make_released_run(world["line"]["id"], world["spec"]["id"],
                             world["agreement"]["id"], [lot_b["id"]], api=api,
                             scheduled_start="2026-09-02T10:00:00Z",
                             scheduled_end="2026-09-02T11:00:00Z")
    return world, run1, run2


def test_shipment_deliver_after_rejection_returns_not_in_transit(api):
    """PRD §3.7: "Recording a delivery — allowed only while `IN_TRANSIT`
    (`ERR_SHIPMENT_NOT_IN_TRANSIT`) — captures the cold-chain record".
    PRD §3.7: "`invoice_cents` stays null while the shipment is in transit and
    forever if it is rejected on arrival".

    Design: Corner/state_machines/shipment_deliver_after_rejection_returns_not_in_transit
    """
    world = setup_released_run(api=api)
    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": world["run"]["id"], "cases": 100}], api=api)
    rejected = validate_success(api.reject_shipment_on_arrival(shipment["id"], LOGISTICS))
    assert rejected["status"] == "REJECTED_ON_ARRIVAL"

    resp = api.deliver_shipment(
        shipment["id"], {"max_transit_temp_f": -2.0, "minutes_above_setpoint": 0}, LOGISTICS
    )
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT)
    assert resp.status_code == 409, "REJECTED_ON_ARRIVAL is terminal"

    reread = validate_success(api.get_shipment(shipment["id"], LOGISTICS))
    assert reread["status"] == "REJECTED_ON_ARRIVAL"
    assert reread["invoice_cents"] is None, "no invoice is ever computed for a rejected shipment"


def test_delivery_excursion_threshold_is_thirty_minutes_exclusive(api):
    """PRD §3.7: "the `excursion_flag` is set when the trailer spent strictly
    more than 30 minutes above its setpoint."
    PRD §3.7: "Under the pinned per-line rounding of §2.6, each line bills its
    cases at the agreement's `price_per_case_cents`, discounted by a factor of
    0.90 when the excursion flag is set, with each line rounded half-up to
    whole cents before the lines are summed."

    Design: Corner/calculations/delivery_excursion_threshold_is_thirty_minutes_exclusive
    """
    world = setup_released_run(api=api)  # agreement @299c, 620 released cases
    ship1 = make_shipment(world["agreement"]["id"],
                          [{"run_id": world["run"]["id"], "cases": 100}], api=api)
    ship2 = make_shipment(world["agreement"]["id"],
                          [{"run_id": world["run"]["id"], "cases": 100}], api=api,
                          route_type="DISTRIBUTOR")

    d1 = validate_success(
        api.deliver_shipment(ship1["id"], {"max_transit_temp_f": -1.0,
                                           "minutes_above_setpoint": 30}, LOGISTICS)
    )
    assert d1["excursion_flag"] is False, "exactly 30 minutes is not 'strictly more than 30'"
    assert d1["invoice_cents"] == 29900, f"full price 100 x 299, got {d1['invoice_cents']}"

    d2 = validate_success(
        api.deliver_shipment(ship2["id"], {"max_transit_temp_f": 2.0,
                                           "minutes_above_setpoint": 31}, LOGISTICS)
    )
    assert d2["excursion_flag"] is True, "31 minutes flags the shipment"
    assert d2["invoice_cents"] == 26910, (
        f"excursion discount: round(100 x 299 x 0.90) = 26910, got {d2['invoice_cents']}"
    )


def test_fill_rate_counts_only_terminal_shipments(api):
    """PRD §3.7: "the delivered figure is the sum of `cases_shipped` over the
    chain's `DELIVERED` shipments, the rejected figure the same sum over
    `REJECTED_ON_ARRIVAL` shipments, and `fill_rate_pct` is one hundred times
    delivered divided by the sum of delivered and rejected, rounded half-up to
    one decimal place. `IN_TRANSIT` shipments are excluded, and the rate is
    null whenever the denominator is zero — that is, until the chain's first
    terminal shipment."

    Design: Corner/calculations/fill_rate_counts_only_terminal_shipments
    """
    world = setup_released_run(api=api)
    ship1 = make_shipment(world["agreement"]["id"],
                          [{"run_id": world["run"]["id"], "cases": 100}], api=api)
    validate_success(
        api.deliver_shipment(ship1["id"], {"max_transit_temp_f": -3.0,
                                           "minutes_above_setpoint": 10}, LOGISTICS)
    )
    make_shipment(world["agreement"]["id"],
                  [{"run_id": world["run"]["id"], "cases": 500}], api=api,
                  route_type="DISTRIBUTOR")  # stays IN_TRANSIT

    chain = validate_success(api.get_customer_chain(world["chain"]["id"], ACCOUNT))
    assert chain["fill_rate_pct"] == 100.0, (
        f"only the DELIVERED 100 cases count; the IN_TRANSIT 500 are excluded; got {chain['fill_rate_pct']}"
    )
    agreement = validate_success(api.get_supply_agreement(world["agreement"]["id"], ACCOUNT))
    assert agreement["under_sla_review"] is False


def test_shipment_credit_memo_per_line_round_then_sum(api):
    """PRD §3.7: "This computes a `credit_memo_cents`: each line credits its
    cases at the agreement's `price_per_case_cents` multiplied by 0.85,
    rounded half-up to whole cents per line and summed."
    PRD §2.6: "a shipment's invoice or credit memo computes each shipment
    line's cents and rounds that line to whole cents before summing the
    rounded lines; the raw products are never summed first and rounded once."

    Design: Difficulty/combinatorial_formula/shipment_credit_memo_per_line_round_then_sum
    """
    world, run1, run2 = _two_released_runs(api, price_per_case_cents=299)
    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": run1["id"], "cases": 3},
                              {"run_id": run2["id"], "cases": 2}], api=api)

    rejected = validate_success(api.reject_shipment_on_arrival(shipment["id"], LOGISTICS))
    assert rejected["status"] == "REJECTED_ON_ARRIVAL"
    # Per line: round(3 x 299 x 0.85) = round(762.45) = 762;
    #           round(2 x 299 x 0.85) = round(508.30) = 508. Sum: 1270.
    assert rejected["credit_memo_cents"] == 1270, (
        f"per-line rounding gives 762 + 508 = 1270, got {rejected['credit_memo_cents']}"
    )
    assert rejected["credit_memo_cents"] != 1271, (
        "sum-then-round would give round(1270.75) = 1271 — the pinned order forbids it"
    )


def test_shipment_credit_memo_matches_the_prd_worked_example(api):
    """PRD §2.6: "These orders are observable — for example, two shipment
    lines of 3 and 2 cases at 305 cents per case produce line amounts of 778
    and 519 cents summing to an invoice of 1297 cents, whereas summing before
    rounding would yield 1296."
    PRD §3.7: "each line credits its cases at the agreement's
    `price_per_case_cents` multiplied by 0.85, rounded half-up to whole cents
    per line and summed."

    Design: Difficulty/combinatorial_formula/shipment_credit_memo_per_line_round_then_sum
    """
    world, run1, run2 = _two_released_runs(api, price_per_case_cents=305)
    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": run1["id"], "cases": 3},
                              {"run_id": run2["id"], "cases": 2}], api=api)

    rejected = validate_success(api.reject_shipment_on_arrival(shipment["id"], LOGISTICS))
    # Per line: round(3 x 305 x 0.85) = round(777.75) = 778;
    #           round(2 x 305 x 0.85) = round(518.50) = 519. Sum: 1297.
    assert rejected["credit_memo_cents"] == 1297, (
        f"the PRD's own worked example: 778 + 519 = 1297, got {rejected['credit_memo_cents']}"
    )
    assert rejected["credit_memo_cents"] != 1296, "sum-then-round would give round(1296.25) = 1296"


def test_shipment_create_blocked_when_agreement_suspended_by_credit_hold(api):
    """PRD §3.7: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)
    and must not be under SLA review (`ERR_AGREEMENT_UNDER_SLA_REVIEW`, HTTP
    409)."
    PRD §3.5: "first, every `ACTIVE` supply agreement of the chain moves to
    `SUSPENDED`, releasing its reserved weekly cases back to the plant pool".

    Design: Difficulty/cross_entity_state_dependency/shipment_create_blocked_when_agreement_suspended_by_credit_hold
    """
    world = setup_released_run(api=api)  # 620 cases released and ready
    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )

    resp = api.create_shipment(
        create_shipment_payload(world["agreement"]["id"],
                                [{"run_id": world["run"]["id"], "cases": 100}],
                                route_type="DISTRIBUTOR"),
        LOGISTICS,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert resp.status_code == 409, (
        "state, not inventory, blocks the shipment: 620 cases stand released"
    )
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_UNRELEASED_CASES_EXCEEDED
    rows, _ = validate_paginated(
        api.list_shipments(LOGISTICS, params={"agreement_id": world["agreement"]["id"]})
    )
    assert rows == []


def test_shipment_create_succeeds_after_credit_release_resumes_agreement(api):
    """PRD §3.5: "Returning the chain to `GOOD_STANDING` reverses the first
    link only: every `SUSPENDED` agreement moves back to `ACTIVE` and
    re-reserves its `weekly_contracted_cases` from the pool."
    PRD §3.7: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/shipment_create_blocked_when_agreement_suspended_by_credit_hold
    """
    world = setup_released_run(api=api)
    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "ON_HOLD"}, ACCOUNT)
    )
    validate_success(
        api.set_credit_status(world["chain"]["id"], {"credit_status": "GOOD_STANDING"}, ACCOUNT)
    )

    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": world["run"]["id"], "cases": 100}], api=api)
    assert shipment["status"] == "IN_TRANSIT", "the resumed agreement ships again"
    assert shipment["cases_shipped"] == 100


def test_shipment_rejection_fill_rate_drop_flags_agreements_under_sla_review(api):
    """PRD §3.7: "The rejection also recomputes the chain's `fill_rate_pct`,
    and if the new rate is below 85.0 the system sets `under_sla_review` to
    true on every `ACTIVE` agreement of the chain, which in turn blocks new
    shipments against those agreements until a later delivery lifts the rate
    back to the floor."
    PRD §3.7: "each line credits its cases at the agreement's
    `price_per_case_cents` multiplied by 0.85, rounded half-up to whole cents
    per line and summed."

    Design: Difficulty/transitive_cascade/shipment_rejection_fill_rate_drop_flags_agreements_under_sla_review
    """
    world = setup_released_run(api=api)  # agreement @299c
    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": world["run"]["id"], "cases": 500}], api=api)
    rejected = validate_success(api.reject_shipment_on_arrival(shipment["id"], LOGISTICS))
    assert rejected["status"] == "REJECTED_ON_ARRIVAL"
    assert rejected["credit_memo_cents"] == 127075, "round(500 x 299 x 0.85)"

    chain = validate_success(api.get_customer_chain(world["chain"]["id"], ACCOUNT))
    assert chain["fill_rate_pct"] == 0.0, "0 delivered / 500 terminal -> 0.0, below the 85.0 floor"

    rows, _ = validate_paginated(
        api.list_supply_agreements(ACCOUNT, params={"customer_id": world["chain"]["id"]})
    )
    assert rows[0]["under_sla_review"] is True, (
        "cascade link 2: the fill-rate recompute flags every ACTIVE agreement of the chain"
    )


def test_under_sla_review_blocks_new_shipments(api):
    """PRD §3.7: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)
    and must not be under SLA review (`ERR_AGREEMENT_UNDER_SLA_REVIEW`, HTTP
    409)."
    PRD §3.7: "if the new rate is below 85.0 the system sets
    `under_sla_review` to true on every `ACTIVE` agreement of the chain, which
    in turn blocks new shipments against those agreements until a later
    delivery lifts the rate back to the floor."

    Design: Difficulty/transitive_cascade/shipment_rejection_fill_rate_drop_flags_agreements_under_sla_review
    """
    world = setup_released_run(api=api)
    shipment = make_shipment(world["agreement"]["id"],
                             [{"run_id": world["run"]["id"], "cases": 500}], api=api)
    validate_success(api.reject_shipment_on_arrival(shipment["id"], LOGISTICS))

    resp = api.create_shipment(
        create_shipment_payload(world["agreement"]["id"],
                                [{"run_id": world["run"]["id"], "cases": 100}]),
        LOGISTICS,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_UNDER_SLA_REVIEW)
    assert resp.status_code == 409, "the cascade's gating consequence: no new shipments under review"
