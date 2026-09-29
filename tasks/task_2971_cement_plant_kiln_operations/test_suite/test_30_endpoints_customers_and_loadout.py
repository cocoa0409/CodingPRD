"""Breadth coverage of three endpoint contracts on the commercial side of the plant: the
partial-update semantics of a customer amendment, the half-open appointment window that gates
loading, and the computed distribution-plan read that is not a list.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_amount,
    assert_instant_equals,
    assert_int,
    validate_unpaginated,
)
from test_helpers.test_users import ADMIN_HEADERS, LOGISTICS_HEADERS


def _plan_response(api, plant_id, headers=LOGISTICS_HEADERS, **params):
    return api.get_distribution_plan(plant_id, headers, params=params or None)


def _plan(api, plant_id, as_of_month, headers=LOGISTICS_HEADERS):
    return validate_success(
        _plan_response(api, plant_id, headers=headers, as_of_month=as_of_month)
    )


# ---------------------------------------------------------------------------
# endpoints: every input of the customer amendment is optional
# ---------------------------------------------------------------------------
def test_amending_only_the_credit_hold_leaves_every_other_contract_term_standing(api):
    """The body names one field, so the other four amendable terms and the untouchable
    `required_cement_type` must all survive verbatim while the version still advances — an
    implementation that reads absent keys as null would wipe the contract on a credit decision.

    PRD: "Amendments may change `contract_state`, `credit_hold`, `contract_priority`,
    `contract_monthly_tonnes` or `max_so3_pct`, and each amendment increments the customer's
    `version`."

    Design: Corner/endpoints/customer_patch_is_a_partial_update
    """
    fx.reset_clock(api)
    customer = fx.create_customer(api)
    assert customer["credit_hold"] is False
    assert customer["contract_state"] == "ACTIVE"
    assert_int(customer["version"], 1, "version")

    patched = validate_success(
        api.patch_customer(customer["id"], {"credit_hold": True}, LOGISTICS_HEADERS)
    )
    assert patched["credit_hold"] is True
    assert patched["contract_state"] == "ACTIVE"
    assert patched["required_cement_type"] == "TYPE_IL"
    assert_int(patched["contract_priority"], 10, "contract_priority")
    assert_amount(
        patched["contract_monthly_tonnes"], 4000.00, "contract_monthly_tonnes"
    )
    assert_amount(patched["max_so3_pct"], 3.00, "max_so3_pct")
    assert_int(patched["version"], 2, "version")

    # The two derived tonnages are never writable and have nothing to report yet.
    assert_amount(patched["open_reserved_tonnes"], 0.00, "open_reserved_tonnes")
    assert_amount(patched["lifetime_loaded_tonnes"], 0.00, "lifetime_loaded_tonnes")

    reread = validate_success(api.get_customer(customer["id"], LOGISTICS_HEADERS))
    assert reread == patched


def test_suspending_a_customer_keeps_its_terms_and_its_open_appointment(api):
    """Suspension is a planning decision, not a cancellation: the order it already holds stays
    `RESERVED` with its 120.00 tonnes still reserved against the customer, while the plan that
    had exactly one eligible buyer now has none at all.

    PRD: "A customer moved to `SUSPENDED`, or placed on `credit_hold`, drops out of distribution
    planning immediately but keeps its existing loadout orders untouched."

    Design: Corner/endpoints/customer_patch_is_a_partial_update
    """
    env = fx.certificate_chain(api)
    before = validate_success(
        api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(before["open_reserved_tonnes"], 120.00, "open_reserved_tonnes")
    assert_amount(_plan(api, env["plant_id"], 8)["available_pool_tonnes"], 454.72,
                  "available_pool_tonnes")

    suspended = validate_success(
        api.patch_customer(
            env["customer"]["id"], {"contract_state": "SUSPENDED"}, ADMIN_HEADERS
        )
    )
    assert suspended["contract_state"] == "SUSPENDED"
    assert suspended["credit_hold"] is False
    assert suspended["required_cement_type"] == "TYPE_IL"
    assert_int(suspended["contract_priority"], 10, "contract_priority")
    assert_amount(
        suspended["contract_monthly_tonnes"], 4000.00, "contract_monthly_tonnes"
    )
    assert_amount(suspended["max_so3_pct"], 3.00, "max_so3_pct")
    assert suspended["version"] == before["version"] + 1
    assert_amount(suspended["open_reserved_tonnes"], 120.00, "open_reserved_tonnes")

    order = validate_success(
        api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS)
    )
    assert order["status"] == "RESERVED"
    assert_amount(order["tonnes"], 120.00, "tonnes")

    validate_error(
        _plan_response(api, env["plant_id"], as_of_month=8),
        ApiErrorId.ERR_NO_ELIGIBLE_CUSTOMERS.value,
        422,
    )


# ---------------------------------------------------------------------------
# endpoints: the appointment window is half-open at both ends
# ---------------------------------------------------------------------------
def test_the_appointment_window_opens_at_its_very_first_instant(api):
    """Before the window there is nothing to load and the order does not move; at exactly
    06:00:00Z — the opening instant itself — the same call succeeds and stamps that instant.
    Loading occupies a spout without moving a tonne, so the silo's stock figures stand still.

    PRD: "It requires the order to be `RESERVED`, else `ERR_INVALID_ORDER_STATE`; the
    certificate still to be `ISSUED`, else `ERR_CERTIFICATE_NOT_ISSUED`; the silo still to be
    `OPEN`, else `ERR_SILO_BLOCKED`; the logical clock to be inside the half-open appointment
    window, at or after `window_start` and strictly before `window_end`, else
    `ERR_LOADOUT_WINDOW_NOT_ACTIVE`; and the number of orders on the same silo already in
    `LOADING` to be strictly below the silo's `loadout_spouts`, else
    `ERR_SILO_SPOUT_CAPACITY`."

    Design: Corner/endpoints/start_loading_is_gated_on_the_half_open_appointment_window
    """
    env = fx.certificate_chain(api)
    order_id = env["order"]["id"]

    validate_error(
        api.start_loading(order_id, LOGISTICS_HEADERS),
        ApiErrorId.ERR_LOADOUT_WINDOW_NOT_ACTIVE.value,
        422,
    )
    waiting = validate_success(api.get_loadout_order(order_id, LOGISTICS_HEADERS))
    assert waiting["status"] == "RESERVED"
    assert waiting["loading_started_at"] is None

    fx.set_clock(api, "2026-08-05T06:00:00Z")
    loading = validate_success(api.start_loading(order_id, LOGISTICS_HEADERS))
    assert loading["status"] == "LOADING"
    assert_instant_equals(
        loading["loading_started_at"], "2026-08-05T06:00:00Z", "loading_started_at"
    )
    assert_amount(loading["loaded_tonnes"], 0.00, "loaded_tonnes")

    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(silo["reserved_tonnes"], 120.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 454.72, "available_tonnes")


def test_the_appointment_window_closes_before_its_last_instant(api):
    """One clock reading, two orders and two answers: at 08:00:00Z the appointment that ends
    then is already over and refuses, while the appointment that starts then is live and
    accepts. A closed-interval reading of the window — the rule kiln runs use — would have let
    the first one load.

    PRD: "Starting loading requires the clock to be at or after `window_start` and strictly
    before `window_end`, else `ERR_LOADOUT_WINDOW_NOT_ACTIVE` (422)."

    Design: Corner/endpoints/start_loading_is_gated_on_the_half_open_appointment_window
    """
    env = fx.certificate_chain(api)
    later = fx.create_reserved_order(
        api,
        env["customer"]["id"],
        env["cement_silo"]["id"],
        env["certificate"]["id"],
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T10:00:00Z",
    )
    assert later["status"] == "RESERVED"

    fx.set_clock(api, "2026-08-05T08:00:00Z")
    validate_error(
        api.start_loading(env["order"]["id"], LOGISTICS_HEADERS),
        ApiErrorId.ERR_LOADOUT_WINDOW_NOT_ACTIVE.value,
        422,
    )
    expired = validate_success(
        api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS)
    )
    assert expired["status"] == "RESERVED"
    assert expired["loading_started_at"] is None

    opening = validate_success(api.start_loading(later["id"], LOGISTICS_HEADERS))
    assert opening["status"] == "LOADING"
    assert_instant_equals(
        opening["loading_started_at"], "2026-08-05T08:00:00Z", "loading_started_at"
    )


def test_completion_takes_a_positive_load_no_greater_than_the_reservation(api):
    """Zero tonnes is not a shipment and 120.01 is more than was promised, so both are shape
    errors that leave the order in `LOADING`; the honest 120.00 then completes and moves the
    mass out of the silo.

    PRD: "Completing advances the order `LOADING → COMPLETED`, requires a `loaded_tonnes` that
    is strictly greater than zero and no greater than the reserved `tonnes` — anything else is
    refused with `ERR_INVALID_REQUEST` — and stamps `completed_at`."

    Design: Corner/endpoints/start_loading_is_gated_on_the_half_open_appointment_window
    """
    env = fx.certificate_chain(api)
    order_id = env["order"]["id"]
    fx.set_clock(api, "2026-08-05T06:00:00Z")
    validate_success(api.start_loading(order_id, LOGISTICS_HEADERS))

    for refused in (0.00, 120.01):
        validate_error(
            api.complete_loadout_order(
                order_id, {"loaded_tonnes": refused}, LOGISTICS_HEADERS
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    still_loading = validate_success(api.get_loadout_order(order_id, LOGISTICS_HEADERS))
    assert still_loading["status"] == "LOADING"
    assert_amount(still_loading["loaded_tonnes"], 0.00, "loaded_tonnes")

    completed = validate_success(
        api.complete_loadout_order(
            order_id, {"loaded_tonnes": 120.00}, LOGISTICS_HEADERS
        )
    )
    assert completed["status"] == "COMPLETED"
    assert_amount(completed["loaded_tonnes"], 120.00, "loaded_tonnes")
    assert_instant_equals(
        completed["completed_at"], "2026-08-05T06:00:00Z", "completed_at"
    )

    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 454.72, "tonnes_on_hand")
    assert_amount(silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 454.72, "available_tonnes")


# ---------------------------------------------------------------------------
# endpoints: the plan is a computed read, not a stored one and not a page
# ---------------------------------------------------------------------------
def test_two_authorised_callers_receive_the_identical_plan_body(api):
    """The plan is a function of the plant, the month and the current rows, so the planner and
    the administrator must be handed the same seven figures — nothing about it is per-caller.

    PRD: "The response also echoes the `plant_id` and the `as_of_month`, and reports
    `total_allocated_tonnes` as the sum of all allocations and `total_shortfall_tonnes` as the
    sum of all shortfalls, each rounded half up to two decimals."

    Design: Corner/endpoints/distribution_plan_is_a_pure_computed_read
    """
    env = fx.certificate_chain(api)

    planner = _plan(api, env["plant_id"], 8)
    administrator = _plan(api, env["plant_id"], 8, headers=ADMIN_HEADERS)
    assert planner == administrator

    assert planner["plant_id"] == env["plant_id"]
    assert_int(planner["as_of_month"], 8, "as_of_month")
    assert_amount(planner["seasonal_factor"], 1.25, "seasonal_factor")
    assert_amount(planner["available_pool_tonnes"], 454.72, "available_pool_tonnes")
    assert_amount(planner["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")
    assert_amount(planner["total_shortfall_tonnes"], 4545.28, "total_shortfall_tonnes")

    assert len(planner["allocations"]) == 1
    only = planner["allocations"][0]
    assert only["customer_id"] == env["customer"]["id"]
    assert_amount(only["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(only["shortfall_tonnes"], 4545.28, "shortfall_tonnes")


def test_the_plan_read_is_one_object_and_carries_no_pagination_meta(api):
    """`allocations` is an array inside one computed object rather than a page of rows, so the
    envelope must declare `object` and its `meta` must stay free of the four pagination fields
    a list endpoint would carry.

    PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are
    included for list endpoints."

    Design: Corner/endpoints/distribution_plan_is_a_pure_computed_read
    """
    env = fx.certificate_chain(api)

    response = _plan_response(api, env["plant_id"], as_of_month=8)
    plan = validate_unpaginated(response)
    body = response.json()

    for paginated_only in ("limit", "offset", "total_count", "has_more"):
        assert paginated_only not in body["meta"], (
            f"{paginated_only} belongs to list endpoints, not to the plan read"
        )

    assert "items" not in plan
    assert isinstance(plan["allocations"], list)
    assert set(plan) == {
        "plant_id",
        "as_of_month",
        "seasonal_factor",
        "available_pool_tonnes",
        "allocations",
        "total_allocated_tonnes",
        "total_shortfall_tonnes",
    }


def test_the_plan_month_is_required_and_never_taken_from_the_clock(api):
    """With the clock standing in November, omitting `as_of_month` is refused rather than
    quietly answered for November: the difference is visible in the factor, 1.00 for the month
    the clock is in against 1.25 for the August the caller actually asks about.

    PRD: "A `PlantAdmin` or `LogisticsPlanner` asks the plant for a plan for a given
    `as_of_month`, an integer from 1 to 12 inclusive — anything else is refused with
    `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/distribution_plan_is_a_pure_computed_read
    """
    env = fx.certificate_chain(api)
    fx.set_clock(api, "2026-11-15T00:00:00Z")

    validate_error(
        _plan_response(api, env["plant_id"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    november = _plan(api, env["plant_id"], 11)
    assert_amount(november["seasonal_factor"], 1.00, "seasonal_factor")
    assert_amount(
        november["allocations"][0]["demand_tonnes"], 4000.00, "demand_tonnes"
    )

    august = _plan(api, env["plant_id"], 8)
    assert_amount(august["seasonal_factor"], 1.25, "seasonal_factor")
    assert_amount(august["allocations"][0]["demand_tonnes"], 5000.00, "demand_tonnes")
