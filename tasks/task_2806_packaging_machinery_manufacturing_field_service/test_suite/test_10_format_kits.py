"""Aftermarket change parts: quoting, accepting and fitting a format kit.

Both derived commercial figures are cut at the quote, and their rounding and
clamping order is pinned by the contract.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    draft_kit,
    kit_component,
    move_clock,
    read_kit,
    read_machine,
    setup_accepted_machine,
    setup_ordered_kit,
    setup_quoted_kit,
    setup_reference_data,
)

PET_ROUND_KIT = [
    kit_component("CHG-STAR-95", lead_time_days=40, unit_price_cents=250_000, qty=2),
    kit_component("CHG-GUIDE-95", lead_time_days=30, unit_price_cents=175_000, qty=3),
]

GLASS_SQUARE_KIT = [
    kit_component("CP-INFEED-STAR", lead_time_days=200, unit_price_cents=250_000, qty=6),
    kit_component("CP-CHANGE-GUIDE", lead_time_days=55, unit_price_cents=180_000, qty=10),
]


def _accepted_machine():
    return setup_accepted_machine(setup_reference_data(line={}))


def test_the_kit_price_marks_up_each_line_then_adds_the_engineering_fee_last():
    """Each component line is marked up and rounded on its own before the lines are
    summed, and the flat engineering fee joins only at the end.

    PRD: "The rounded line amounts are then summed as integers, and a flat
    engineering fee of 120,000 cents is added last to produce `price_cents`."

    Design: Corner/calculations/format_kit_price_rounds_each_line_then_adds_engineering_fee
    """
    env = draft_kit(
        _accepted_machine(),
        [
            kit_component("CP-NECK-82", lead_time_days=40, unit_price_cents=250_000, qty=2),
            kit_component("CP-STAR-82", lead_time_days=30, unit_price_cents=175_000, qty=3),
        ],
        container_family="PET_ROUND",
        container_diameter_mm=82,
    )

    data = validate_success(api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER))

    assert data["status"] == "QUOTED"
    assert data["component_count"] == 2
    assert data["price_cents"] == 1_324_375
    assert data["quoted_lead_time_days"] == 43
    assert read_machine(env["machine"]["id"])["current_format_family"] == "PET_ROUND"


def test_the_quoted_lead_time_is_clamped_at_one_hundred_and_eighty_days():
    """The inner comparison picks the two-hundred-day component branch over the
    assembly branch, and the outer cap then clamps that winner rather than either
    raw candidate.

    PRD: "The quote is then the **larger** of two candidates — the largest component
    lead time plus the family-change allowance, or the assembly days plus the
    out-of-range allowance plus a five-day minimum kit lead — and that larger value
    is finally **capped at 180 days**."

    Design: Difficulty/combinatorial_formula/format_kit_lead_time_outer_cap_beats_inner_max
    """
    env = draft_kit(
        _accepted_machine(),
        GLASS_SQUARE_KIT,
        container_family="GLASS_SQUARE",
        container_diameter_mm=82,
    )

    data = validate_success(api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER))

    assert data["quoted_lead_time_days"] == 180
    assert data["component_count"] == 2
    assert data["status"] == "QUOTED"


def test_the_clamped_quote_still_prices_every_component_line_in_full():
    """Capping the calendar does not cap the money: the price of the same kit is the
    marked-up sum of both lines plus the engineering fee.

    PRD: "Walking the components in the array order they were supplied at drafting,
    each line contributes its `unit_price_cents` multiplied by its `qty`, marked up
    by 17.50 percent — that is, multiplied by one plus 17.50 divided by one hundred —
    and rounded half up to whole cents **for that line**."

    Design: Difficulty/combinatorial_formula/format_kit_lead_time_outer_cap_beats_inner_max
    """
    env = draft_kit(
        _accepted_machine(),
        GLASS_SQUARE_KIT,
        container_family="GLASS_SQUARE",
        container_diameter_mm=82,
    )

    data = validate_success(api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER))

    assert data["price_cents"] == 3_997_500
    assert read_machine(env["machine"]["id"])["current_format_family"] == "PET_ROUND"


def test_a_kit_cannot_be_quoted_twice_and_the_first_figures_stand():
    """The second quote does not re-cut the commercial figures: the price and lead time
    recorded by the first one survive untouched.

    PRD: "`DELIVERED` is terminal, and any transition addressed to a kit in the wrong
    state is refused with `ERR_INVALID_KIT_STATE`."

    Design: Corner/errors/format_kit_quote_twice_returns_409_invalid_kit_state
    """
    env = setup_quoted_kit(
        _accepted_machine(),
        PET_ROUND_KIT,
        kit_overrides={"container_family": "PET_ROUND", "container_diameter_mm": 95},
    )

    response = api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_INVALID_KIT_STATE.value, 409)
    kit = read_kit(env["kit"]["id"])
    assert kit["status"] == "QUOTED"
    assert kit["price_cents"] == 1_324_375
    assert kit["quoted_lead_time_days"] == 43
    assert kit["component_count"] == 2


def test_an_empty_kit_may_be_drafted_but_never_quoted():
    """Drafting tolerates a kit with nothing in it; quoting is where the OEM insists on
    at least one change part, and the refused kit keeps its zeroed price.

    PRD: "The kit must have at least one component (`ERR_KIT_HAS_NO_COMPONENTS`) and
    the covered machine must be `ACCEPTED` (`ERR_MACHINE_NOT_ACCEPTED`)."

    Design: Corner/errors/format_kit_quote_with_empty_components_returns_422_kit_has_no_components
    """
    env = draft_kit(
        _accepted_machine(),
        [],
        container_family="GLASS_ROUND",
        container_diameter_mm=70,
    )
    assert env["kit"]["component_count"] == 0

    response = api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_KIT_HAS_NO_COMPONENTS.value, 422)
    kit = read_kit(env["kit"]["id"])
    assert kit["status"] == "DRAFT"
    assert kit["component_count"] == 0
    assert kit["price_cents"] == 0


def test_a_kit_cannot_be_fitted_before_its_quoted_lead_time_has_run():
    """Delivery waits on the clock reaching the ordering date advanced by the quoted
    lead time, and until then the machine keeps its old format.

    PRD: "Delivery and fitting is a `ServiceManager` act taking the kit from `ORDERED`
    to `DELIVERED`, permitted only once the logical clock's UTC date has reached the
    date the kit entered `ORDERED` advanced by `quoted_lead_time_days` days; an early
    delivery is refused with `ERR_KIT_LEAD_TIME_NOT_ELAPSED`."

    Design: Corner/errors/format_kit_deliver_before_lead_time_returns_422_kit_lead_time_not_elapsed
    """
    env = setup_ordered_kit(
        _accepted_machine(),
        components=PET_ROUND_KIT,
        kit_overrides={"container_family": "PET_ROUND", "container_diameter_mm": 95},
    )
    assert env["kit"]["quoted_lead_time_days"] == 43

    response = api_client.deliver_format_kit(env["kit"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_KIT_LEAD_TIME_NOT_ELAPSED.value, 422)
    assert read_kit(env["kit"]["id"])["status"] == "ORDERED"
    assert read_machine(env["machine"]["id"])["current_format_family"] == "PET_ROUND"

    move_clock("2026-09-13T00:00:00.000Z")
    delivered = validate_success(api_client.deliver_format_kit(env["kit"]["id"], SERVICE_MANAGER))
    assert delivered["status"] == "DELIVERED"


def test_fitting_the_kit_rewrites_the_machines_current_format_family():
    """Delivery is the only moment the asset's format changes, and it also moves the
    asset's version on.

    PRD: "Delivery rewrites the machine's `current_format_family` to the kit's
    `container_family` and increments the machine's `version` by 1 — which is exactly
    why a client holding an older machine version can no longer publish a stocking
    recommendation without re-reading the asset."

    Design: Corner/errors/format_kit_deliver_before_lead_time_returns_422_kit_lead_time_not_elapsed
    """
    env = setup_ordered_kit(
        _accepted_machine(),
        components=GLASS_SQUARE_KIT,
        kit_overrides={"container_family": "GLASS_SQUARE", "container_diameter_mm": 82},
    )
    before = read_machine(env["machine"]["id"])
    assert before["current_format_family"] == "PET_ROUND"

    move_clock("2027-01-28T00:00:00.000Z")
    validate_success(api_client.deliver_format_kit(env["kit"]["id"], SERVICE_MANAGER))

    after = read_machine(env["machine"]["id"])
    assert after["current_format_family"] == "GLASS_SQUARE"
    assert after["version"] == before["version"] + 1


def test_format_kit_read_with_unknown_id_reports_the_kit_not_found_code():
    """The aftermarket read reports the kit's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/format_kit_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_format_kit("99999999-9999-4999-8999-999999999999", SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_FORMAT_KIT_NOT_FOUND.value, 404)
