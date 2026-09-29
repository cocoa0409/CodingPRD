"""Pricing the quote: the two landed-cost variants and the award decision."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_landed_costs,
    assert_money_cents,
    assert_status,
)
from test_helpers.constants import (
    AUDIT_RESULT_PASS,
    COST_MODEL_ACCEPTED,
    COST_MODEL_SUBMITTED,
    COST_MODEL_SUPERSEDED,
    DECISION_REJECT,
    ITEM_SOURCED,
    SCOPE_NONE,
)
from test_helpers.fixtures import (
    build_chain,
    read_cost_model,
    read_item,
)
from test_helpers.test_users import (
    QUALITY_HEADERS,
    SOURCING_HEADERS,
    make_supplier_headers,
)


def test_as_quoted_landed_cost_uses_the_quoted_yield_and_no_scrap(
    api, submitted_cost_model
):
    """The commercial variant is always computed from the yield the supplier offered.

    PRD 3.3: "At create, the three component costs are summed into
    `effective_base_cents`, and **the three components are immutable thereafter**"

    PRD 3.3: "The **as-quoted** variant selects `quoted_yield_pct` as the yield and
    a scrap allowance of zero cents regardless of any audit finding; it is always
    computed, it is the number the supplier is held to commercially, and it is the
    fallback whenever the supplier has no finalized audit at all."

    PRD 3.3: "a base of 221 cents at a quoted yield of 96.50% with freight of
    48,000 cents over 1,200 units per pallet lands at 269 cents"

    Design: Difficulty/dual_variant_calc/landed_cost_as_quoted_vs_audited_yield
    """
    cost_model = submitted_cost_model["cost_model"]

    assert_money_cents(cost_model["effective_base_cents"], 221, "effective_base_cents")
    assert cost_model["quoted_yield_pct"] == 96.5
    assert_landed_costs(cost_model, as_quoted=269)
    assert_status(cost_model, COST_MODEL_SUBMITTED, "cost model")
    assert cost_model["open_change_request_count"] == 0


def test_audited_landed_cost_diverges_from_the_as_quoted_figure(
    api, submitted_cost_model
):
    """One set of stored inputs, two yields, two answers fourteen cents apart.

    PRD 3.3: "The **audited-actual** variant selects the `audited_yield_pct`
    measured by an audit and a scrap allowance of zero cents when that audit's
    `result` is `PASS` or 3 cents when the result is `CONDITIONAL`; its result is
    stored in `landed_unit_cost_cents_audited`, and it is this variant that
    ultimately drives the item's pricing."

    PRD 3.3: "Identical stored inputs therefore yield two different answers: a
    base of 221 cents at a quoted yield of 96.50% with freight of 48,000 cents
    over 1,200 units per pallet lands at 269 cents, while the same model measured
    by a `PASS` audit at 91.00% yield lands at 283 — or 286, had that audit come
    back `CONDITIONAL`."

    Design: Difficulty/dual_variant_calc/landed_cost_as_quoted_vs_audited_yield
    """
    audit = validate_success(
        api.get_plant_audit(submitted_cost_model["audit_id"], QUALITY_HEADERS)
    )
    assert audit["result"] == AUDIT_RESULT_PASS
    assert audit["audited_yield_pct"] == 91.0

    cost_model = read_cost_model(api, submitted_cost_model["cost_model_id"])
    assert_landed_costs(cost_model, as_quoted=269, audited=283)
    assert (
        cost_model["landed_unit_cost_cents_audited"]
        - cost_model["landed_unit_cost_cents_as_quoted"]
        == 14
    ), "the audited yield is the worse yield, so its landed cost is higher"


def test_accepting_a_quote_awards_the_supplier_and_supersedes_the_rival(api):
    """One decision fires three side effects at once.

    PRD 3.3: "With `decision` set to `ACCEPT` the quote moves `SUBMITTED →
    ACCEPTED`, and three things happen together: the item's `supplier_id` is set
    to the quoting supplier, the item advances `CONCEPT → SOURCED`, and every
    **other** cost model for the same item still standing at `SUBMITTED`
    transitions to `SUPERSEDED` — each of those siblings having its own `version`
    incremented, alongside the accepted model's and the item's."

    PRD 3.3: "Acceptance requires the item to be at `CONCEPT` and the quoting
    supplier to stand at `QUALIFIED` or `CONDITIONAL`; a quote from a supplier
    that is `PROSPECT`, `SUSPENDED` or `DISQUALIFIED` cannot be awarded and is
    refused with `ERR_SUPPLIER_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/cost_model_accept_awards_supplier_and_supersedes_rival_quote
    """
    ctx = build_chain(api, upto=10)
    rival_supplier = validate_success(
        api.create_supplier(
            f.supplier_payload(
                ctx["program_id"],
                legal_name="Ridgeway Snack Co",
                gfsi_certificate_expiry="2027-09-30T00:00:00Z",
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )
    winning = validate_success(
        api.create_cost_model(
            f.cost_model_payload(ctx["item_id"], ctx["supplier_id"]), SOURCING_HEADERS
        ),
        expected_status=201,
    )
    losing = validate_success(
        api.create_cost_model(
            f.rival_cost_model_payload(ctx["item_id"], rival_supplier["id"]),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    awarded = validate_success(
        api.decide_cost_model(
            winning["id"], f.cost_model_decision_payload(), SOURCING_HEADERS
        )
    )

    assert_status(awarded, COST_MODEL_ACCEPTED, "cost model")
    assert_status(
        read_cost_model(api, losing["id"]), COST_MODEL_SUPERSEDED, "rival cost model"
    )
    item = read_item(api, ctx["item_id"])
    assert item["supplier_id"] == ctx["supplier_id"]
    assert item["development_status"] == ITEM_SOURCED
    assert_money_cents(awarded["effective_base_cents"], 221, "effective_base_cents")
    assert_landed_costs(awarded, as_quoted=269)


def test_a_second_decision_on_an_accepted_quote_is_rejected(api, sourced_item):
    """A REJECT cannot un-award a supplier the ACCEPT already awarded.

    PRD 3.3: "A decision addressed at a quote that is already `ACCEPTED`,
    `REJECTED` or `SUPERSEDED` is refused with `ERR_COST_MODEL_NOT_SUBMITTED`
    (HTTP 409)."

    Design: Corner/state_machines/cost_model_decision_twice_rejected
    """
    cost_model_id = sourced_item["cost_model_id"]

    response = api.decide_cost_model(
        cost_model_id,
        f.cost_model_decision_payload(DECISION_REJECT),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_COST_MODEL_NOT_SUBMITTED.value, 409)

    cost_model = read_cost_model(api, cost_model_id)
    assert_status(cost_model, COST_MODEL_ACCEPTED, "cost model")
    item = read_item(api, sourced_item["item_id"])
    assert item["supplier_id"] == sourced_item["supplier_id"]
    assert item["development_status"] == ITEM_SOURCED


def test_change_request_against_a_still_submitted_quote_is_rejected(api, sourced_item):
    """Only the ACCEPTED model that governs the item may be re-priced.

    PRD 3.9: "The named cost model must be `ACCEPTED` and its `item_id` must match
    the request's `item_id`, or the request is refused with
    `ERR_COST_MODEL_NOT_ACCEPTED` (HTTP 409)."

    Design: Corner/validations/cost_change_request_on_submitted_cost_model_rejected
    """
    other_supplier = validate_success(
        api.create_supplier(
            f.supplier_payload(
                sourced_item["program_id"], legal_name="Eastvale Snack Works"
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )
    other_headers = make_supplier_headers(other_supplier["id"])
    unawarded = validate_success(
        api.create_cost_model(
            f.rival_cost_model_payload(sourced_item["item_id"], other_supplier["id"]),
            other_headers,
        ),
        expected_status=201,
    )

    response = api.create_change_request(
        f.change_request_payload(
            sourced_item["item_id"],
            unawarded["id"],
            unawarded["version"],
            requested_ingredient_cost_cents_per_unit=155,
            requested_packaging_cost_cents_per_unit=30,
            requested_conversion_cost_cents_per_unit=52,
            substitution_scope=SCOPE_NONE,
        ),
        other_headers,
    )
    validate_error(response, ApiErrorId.ERR_COST_MODEL_NOT_ACCEPTED.value, 409)

    still_submitted = read_cost_model(api, unawarded["id"])
    assert_status(still_submitted, COST_MODEL_SUBMITTED, "cost model")
    assert still_submitted["open_change_request_count"] == 0
    assert_status(
        read_cost_model(api, sourced_item["cost_model_id"]),
        COST_MODEL_ACCEPTED,
        "awarded cost model",
    )
    _rows, meta = validate_paginated(
        api.list_change_requests(
            SOURCING_HEADERS, params={"cost_model_id": unawarded["id"]}
        )
    )
    assert meta["total_count"] == 0, "a refused request creates no negotiation row"
    assert read_item(api, sourced_item["item_id"])["supplier_id"] == sourced_item[
        "supplier_id"
    ]
