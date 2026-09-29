"""Renegotiating cost: the ten settlement steps in their pinned order, the bounded
negotiation loop and the authority that a tier decides."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_money_cents,
    assert_settlement,
    assert_status,
    assert_two_decimal_value,
)
from test_helpers.constants import (
    CCR_COUNTERED,
    CCR_SUBMITTED,
    CCR_WITHDRAWN,
    DECISION_ACCEPT,
    SCOPE_INGREDIENT,
    TIER_T1,
    TIER_T2,
    TIER_T3,
)
from test_helpers.fixtures import (
    build_chain,
    open_change_request,
    read_change_request,
    read_cost_model,
)
from test_helpers.test_users import (
    DIRECTOR_1,
    DIRECTOR_HEADERS,
    SOURCING_HEADERS,
    make_supplier_headers,
)


def _requests_for(api, cost_model_id):
    rows, meta = validate_paginated(
        api.list_change_requests(
            SOURCING_HEADERS, params={"cost_model_id": cost_model_id}
        )
    )
    return rows, meta


def _negotiate(api, ctx, request_id, counter_base_cents, ingredient, packaging, conversion):
    """Counter the live round, then let the supplier revise into the next one."""
    supplier_headers = make_supplier_headers(ctx["supplier_id"])
    countered = validate_success(
        api.counter_change_request(
            request_id, f.counter_payload(counter_base_cents), SOURCING_HEADERS
        )
    )
    assert_status(countered, CCR_COUNTERED, "cost change request")
    return validate_success(
        api.revise_change_request(
            request_id,
            f.revise_payload(ingredient, packaging, conversion),
            supplier_headers,
        )
    )


def test_the_tier_cap_is_applied_before_the_offset_fee(api):
    """Raw 30 tiers T3, floors to a 19-cent cap, then pays a 2-cent fee: net 17.

    PRD 3.9: "Sixth, a tier cap in cents is derived from the old base and the tier's
    cap percentage — 3.00 percent for `T1`, 6.50 percent for `T2`, 9.00 percent for
    `T3` — as the old base multiplied by that percentage, divided by 100, and
    **floored** to a whole cent. Seventh, `capped_increase_cents` is the smaller of the
    raw increase and that cap. Eighth, `offset_fee_cents` is the capped increase
    multiplied by 12.50, divided by 100, and rounded half up to a whole cent — an
    agency offset charged on the capped increase, not on the raw one. Ninth,
    `net_increase_cents` is the capped increase minus that offset fee."

    PRD 3.9: "Against an old base of 221 cents with requested components of 168, 33 and
    50, the raw increase is 30, the percentage is 13.57, the tier is `T3`, the cap
    floors to 19, the capped increase is 19, the fee rounds to 2, the net increase is 17
    and the accepted base becomes 238 — where charging the fee before the cap would have
    given a net of 19 and a base of 240."

    Design: Difficulty/combinatorial_formula/cost_change_settlement_pinned_order
    """
    ctx = build_chain(api, upto=12)
    assert_money_cents(
        read_cost_model(api, ctx["cost_model_id"])["effective_base_cents"],
        221,
        "effective_base_cents",
    )

    request = open_change_request(
        api,
        ctx,
        factory=f.ingredient_substitution_payload,
        substitution_material_desc="Sunflower oil replaces palm oil",
    )

    assert_settlement(
        request,
        raw_increase_cents=30,
        increase_pct=13.57,
        escalation_tier=TIER_T3,
        capped_increase_cents=19,
        offset_fee_cents=2,
        net_increase_cents=17,
    )
    assert request["net_increase_cents"] != 19, (
        "charging the fee before the cap would leave a net of 19"
    )
    assert request["round_number"] == 1
    assert_status(request, CCR_SUBMITTED, "cost change request")
    assert request["substitution_scope"] == SCOPE_INGREDIENT


def test_only_acceptance_moves_the_base_the_settlement_computed(api):
    """The tenth step is conditional: filing the request re-prices nothing.

    PRD 3.9: "A successful create opens the request at `SUBMITTED` with `round_number`
    at 1, `counter_base_cents` and `decided_by_user_id` null, increases the cost model's
    `open_change_request_count` by 1 and increments that cost model's `version`."

    PRD 3.9: "Tenth, and only when the request is accepted, the new base is the old base
    plus the net increase."

    PRD 3.9: "**Hop one**: the cost model's `effective_base_cents` increases by
    `net_increase_cents`, both `landed_unit_cost_cents_as_quoted` and
    `landed_unit_cost_cents_audited` are recomputed from the new base, and the cost
    model's `version` increments."

    Design: Difficulty/combinatorial_formula/cost_change_settlement_pinned_order
    """
    ctx = build_chain(api, upto=12)
    before = read_cost_model(api, ctx["cost_model_id"])

    request = open_change_request(
        api,
        ctx,
        factory=f.ingredient_substitution_payload,
        substitution_material_desc="Sunflower oil replaces palm oil",
    )

    filed = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(filed["effective_base_cents"], 221, "effective_base_cents")
    assert filed["open_change_request_count"] == 1
    assert filed["version"] == before["version"] + 1
    assert request["counter_base_cents"] is None
    assert request["decided_by_user_id"] is None
    assert_settlement(request, net_increase_cents=17)

    accepted = validate_success(
        api.decide_change_request(
            request["id"], f.decision_payload(DECISION_ACCEPT), DIRECTOR_HEADERS
        )
    )

    assert accepted["decided_by_user_id"] == DIRECTOR_1
    settled = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(settled["effective_base_cents"], 238, "effective_base_cents")
    assert settled["open_change_request_count"] == 0


def test_every_revision_recomputes_the_whole_settlement_from_the_new_amounts(api):
    """Three rounds, three settlements, and the same 221 base underneath each.

    PRD 3.9: "The supplier may then revise, which moves the request `COUNTERED →
    SUBMITTED`, replaces the three requested component costs with fresh payload values,
    optionally restates `substitution_scope` and `substitution_material_desc`, increases
    `round_number` by 1 and recomputes every settlement output from the revised
    amounts."

    PRD 3.9: "All ten steps are recomputed from scratch on every revision, and
    `counter_base_cents` never enters the arithmetic: it is a negotiating position
    only."

    PRD 3.9: "Fifth, `escalation_tier` is `T1` when that percentage is at most 3.00,
    `T2` when it is at most 8.00, and `T3` above that."

    Design: Difficulty/non_linear_state_machine/cost_change_negotiation_round_cycle
    """
    ctx = build_chain(api, upto=12)
    opened = open_change_request(api, ctx)
    assert opened["round_number"] == 1
    assert_settlement(opened, escalation_tier=TIER_T3, net_increase_cents=17)

    second = _negotiate(api, ctx, opened["id"], 230, 160, 33, 50)
    assert_status(second, CCR_SUBMITTED, "cost change request")
    assert second["round_number"] == 2
    assert_settlement(
        second,
        raw_increase_cents=22,
        increase_pct=9.95,
        escalation_tier=TIER_T3,
        capped_increase_cents=19,
        offset_fee_cents=2,
        net_increase_cents=17,
    )

    third = _negotiate(api, ctx, opened["id"], 228, 150, 31, 48)

    assert_status(third, CCR_SUBMITTED, "cost change request")
    assert third["round_number"] == 3
    assert_settlement(
        third,
        raw_increase_cents=8,
        increase_pct=3.62,
        escalation_tier=TIER_T2,
        capped_increase_cents=8,
        offset_fee_cents=1,
        net_increase_cents=7,
    )
    assert_money_cents(
        read_cost_model(api, ctx["cost_model_id"])["effective_base_cents"],
        221,
        "effective_base_cents",
    )


def test_a_fourth_submission_is_refused_and_the_row_stays_countered(api):
    """The loop is bounded by round_number, and the refusal freezes the third round.

    PRD 3.9: "`SUBMITTED → COUNTERED → SUBMITTED` is the negotiation cycle, and it is
    bounded: a revision is accepted only while `round_number` is still below 3, so the
    fourth submission is refused with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 409)."

    PRD 3.9: "Second, the old base is the cost model's **current**
    `effective_base_cents` — not the three component fields captured when the model was
    created."

    Design: Difficulty/non_linear_state_machine/cost_change_negotiation_round_cycle
    """
    ctx = build_chain(api, upto=12)
    opened = open_change_request(api, ctx)
    _negotiate(api, ctx, opened["id"], 230, 160, 33, 50)
    _negotiate(api, ctx, opened["id"], 228, 150, 31, 48)
    validate_success(
        api.counter_change_request(
            opened["id"], f.counter_payload(226), SOURCING_HEADERS
        )
    )

    response = api.revise_change_request(
        opened["id"],
        f.revise_payload(147, 31, 48),
        make_supplier_headers(ctx["supplier_id"]),
    )
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value, 409)

    request = read_change_request(api, opened["id"])
    assert request["round_number"] == 3, "the refused revision opens no fourth round"
    assert_status(request, CCR_COUNTERED, "cost change request")
    assert_settlement(
        request,
        escalation_tier=TIER_T2,
        capped_increase_cents=8,
        offset_fee_cents=1,
        net_increase_cents=7,
    )
    assert request["requested_ingredient_cost_cents_per_unit"] == 150, (
        "the third round's amounts stand"
    )
    assert_money_cents(
        read_cost_model(api, ctx["cost_model_id"])["effective_base_cents"],
        221,
        "effective_base_cents",
    )


def test_a_substitution_scope_without_a_material_description_is_rejected(api):
    """The material change is what later invalidates the panel, so it must be named.

    PRD 3.9: "When the scope is anything other than `NONE`, a non-empty
    `substitution_material_desc` must describe the substituted material; omitting it is
    refused with `ERR_SUBSTITUTION_DESC_REQUIRED` (HTTP 422)."

    Design: Corner/validations/ingredient_substitution_without_material_description_rejected
    """
    ctx = build_chain(api, upto=12)
    cost_model = read_cost_model(api, ctx["cost_model_id"])

    response = api.create_change_request(
        f.ingredient_substitution_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            cost_model["version"],
            substitution_material_desc=None,
        ),
        make_supplier_headers(ctx["supplier_id"]),
    )
    validate_error(response, ApiErrorId.ERR_SUBSTITUTION_DESC_REQUIRED.value, 422)

    _rows, meta = _requests_for(api, ctx["cost_model_id"])
    assert meta["total_count"] == 0, "a refused create persists no request row"
    settled = read_cost_model(api, ctx["cost_model_id"])
    assert settled["open_change_request_count"] == 0
    assert_money_cents(settled["effective_base_cents"], 221, "effective_base_cents")


def test_a_second_live_negotiation_on_the_same_cost_model_is_rejected(api):
    """One negotiation at a time, and the pin handed in is deliberately current.

    PRD 3.9: "Only one negotiation may be live per cost model: when the model's
    `open_change_request_count` is not zero, a further request is refused with
    `ERR_OPEN_CHANGE_REQUEST_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_open_change_request_on_same_cost_model_rejected
    """
    ctx = build_chain(api, upto=12)
    first = open_change_request(
        api,
        ctx,
        requested_ingredient_cost_cents_per_unit=147,
        requested_packaging_cost_cents_per_unit=31,
        requested_conversion_cost_cents_per_unit=48,
    )
    current = read_cost_model(api, ctx["cost_model_id"])

    response = api.create_change_request(
        f.change_request_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            current["version"],
            requested_ingredient_cost_cents_per_unit=152,
            requested_packaging_cost_cents_per_unit=31,
            requested_conversion_cost_cents_per_unit=48,
        ),
        make_supplier_headers(ctx["supplier_id"]),
    )
    validate_error(response, ApiErrorId.ERR_OPEN_CHANGE_REQUEST_EXISTS.value, 409)

    settled = read_cost_model(api, ctx["cost_model_id"])
    assert settled["open_change_request_count"] == 1
    assert_money_cents(settled["effective_base_cents"], 221, "effective_base_cents")
    _rows, meta = _requests_for(api, ctx["cost_model_id"])
    assert meta["total_count"] == 1
    live = read_change_request(api, first["id"])
    assert_status(live, CCR_SUBMITTED, "cost change request")
    assert_settlement(live, escalation_tier=TIER_T1, net_increase_cents=4)


def test_a_sourcing_manager_may_not_accept_a_t3_request(api):
    """Authority follows the data: the same desk may settle T1 but not T3.

    PRD 3.9: "Deciding a request is open to a `SourcingManager` or a `ProgramDirector`,
    subject to the escalation authority of §2.1: a `T1` request may be decided by
    either, while `T2` and `T3` requests are the `ProgramDirector`'s alone and a
    `SourcingManager` attempting them is refused with `ERR_ESCALATION_ROLE_INSUFFICIENT`
    (HTTP 403)."

    PRD 3.9: "Fourth, `increase_pct` is the raw increase multiplied by 100, divided by
    the old base, and rounded half up to two decimals."

    Design: Corner/rbac/sourcing_manager_cannot_accept_a_t3_cost_change
    """
    ctx = build_chain(api, upto=12)
    request = open_change_request(
        api,
        ctx,
        factory=f.ingredient_substitution_payload,
        substitution_material_desc="Alternate wheat flour blend WF-22",
    )

    response = api.decide_change_request(
        request["id"], f.decision_payload(DECISION_ACCEPT), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_ROLE_INSUFFICIENT.value, 403)

    refused = read_change_request(api, request["id"])
    assert_status(refused, CCR_SUBMITTED, "cost change request")
    assert refused["escalation_tier"] == TIER_T3
    assert_two_decimal_value(refused["increase_pct"], 13.57, "increase_pct")
    assert refused["decided_by_user_id"] is None
    settled = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(settled["effective_base_cents"], 221, "effective_base_cents")
    assert settled["open_change_request_count"] == 1, (
        "an unauthorised decision neither settles nor closes the negotiation"
    )


def test_countering_a_withdrawn_request_is_rejected(api):
    """WITHDRAWN is terminal, and the withdrawal already freed the negotiation slot.

    PRD 3.9: "The owning supplier may also withdraw its request from either `SUBMITTED`
    or `COUNTERED`, moving it to the terminal `WITHDRAWN`, which decreases the cost
    model's `open_change_request_count` by 1 and increments that model's `version`.
    Countering from anything but `SUBMITTED`, revising from anything but `COUNTERED`,
    deciding from anything but `SUBMITTED`, or withdrawing from a terminal status, are
    all refused with `ERR_CHANGE_REQUEST_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/change_request_counter_after_withdraw_rejected
    """
    ctx = build_chain(api, upto=12)
    request = open_change_request(
        api,
        ctx,
        requested_ingredient_cost_cents_per_unit=147,
        requested_packaging_cost_cents_per_unit=31,
        requested_conversion_cost_cents_per_unit=48,
    )
    withdrawn = validate_success(
        api.withdraw_change_request(
            request["id"], make_supplier_headers(ctx["supplier_id"])
        )
    )
    assert_status(withdrawn, CCR_WITHDRAWN, "cost change request")

    response = api.counter_change_request(
        request["id"], f.counter_payload(223), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_CHANGE_REQUEST_STATE_INVALID.value, 409)

    terminal = read_change_request(api, request["id"])
    assert_status(terminal, CCR_WITHDRAWN, "cost change request")
    assert terminal["counter_base_cents"] is None, (
        "a refused counter records no negotiating position"
    )
    assert_settlement(terminal, escalation_tier=TIER_T1, net_increase_cents=4)
    assert read_cost_model(api, ctx["cost_model_id"])["open_change_request_count"] == 0
