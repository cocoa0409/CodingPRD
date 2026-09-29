"""Claiming a facing: item creation, tier agreement and the shelf-slot quota."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_item_state,
    assert_money_cents,
    assert_shelf_slots,
    assert_status,
    assert_two_decimal_value,
)
from test_helpers.constants import (
    GAP_ANALYZED,
    GAP_TIER_APPROVED,
    ITEM_CONCEPT,
    ITEM_LAUNCHED,
    POSTURE_GREEN,
    PROGRAM_CLOSED,
    PROGRAM_RELAUNCH_FREEZE,
    TIER_PREMIUM,
)
from test_helpers.fixtures import close_program, start_relaunch
from test_helpers.test_users import DIRECTOR_HEADERS, SOURCING_HEADERS


def test_new_item_opens_concept_on_development_and_green_on_quality(
    api, tier_approved_gap
):
    """The two item dimensions open independently and the item takes one slot.

    PRD 3.3: "A successful creation opens the item at `development_status`
    `CONCEPT` and `quality_posture` `GREEN`, with `supplier_id` and
    `retail_price_cents` null, `replacement_item_id` null, `complaint_ppm_90d` at
    0.00 and `spec_revision_count` at zero."

    PRD 3.3: "It also takes the slot: the gap's `slots_consumed` and
    `slots_consumed_lifetime` each increase by 1, `slots_open` decreases by 1, and
    the program's `active_item_count` increases by 1."

    Design: Corner/state_machines/item_initial_state_is_concept_and_green
    """
    gap_id = tier_approved_gap["gap_id"]

    item = validate_success(
        api.create_item(
            f.item_payload(gap_id, trailing_90d_units=None), SOURCING_HEADERS
        ),
        expected_status=201,
    )

    assert_item_state(item, ITEM_CONCEPT, POSTURE_GREEN)
    assert item["supplier_id"] is None
    assert item["retail_price_cents"] is None
    assert item["replacement_item_id"] is None
    assert item["trailing_90d_units"] == 0, "an omitted shipment seed starts at zero"
    assert_two_decimal_value(item["complaint_ppm_90d"], 0.00, "complaint_ppm_90d")
    assert item["spec_revision_count"] == 0

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_shelf_slots(
        gap, slots_consumed=1, slots_open=1, slots_consumed_lifetime=1
    )
    program = validate_success(
        api.get_program(tier_approved_gap["program_id"], DIRECTOR_HEADERS)
    )
    assert program["active_item_count"] == 1


def test_item_whose_tier_differs_from_the_approved_tier_is_rejected(
    api, tier_approved_gap
):
    """A PREMIUM item on an NBE-approved gap is a tier mismatch, not a new strategy.

    PRD 3.3: "if the item's `tier` is a valid member of `OPENING_PRICE`, `NBE` or
    `PREMIUM` but is not the same tier the director approved on the gap, it is
    refused with `ERR_TIER_MISMATCH` (HTTP 409)."

    Design: Corner/validations/item_tier_disagreeing_with_approved_tier_rejected
    """
    gap_id = tier_approved_gap["gap_id"]

    response = api.create_item(
        f.item_payload(
            gap_id,
            item_name="Harvest Lane Reserve Crackers",
            tier=TIER_PREMIUM,
            pack_size_desc="8 oz box",
            trailing_90d_units=None,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_TIER_MISMATCH.value, 409)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_shelf_slots(gap, slots_consumed=0, slots_open=2)
    _, meta = validate_paginated(
        api.list_items(SOURCING_HEADERS, params={"gap_id": gap_id})
    )
    assert meta["total_count"] == 0, "a refused create claims no facing"


def test_item_creation_on_an_analyzed_but_unapproved_gap_is_rejected(
    api, analyzed_gap
):
    """Without a tier decision there is no approved strategy to build against.

    PRD 3.3: "If the gap is anything other than `TIER_APPROVED`, creation is
    refused with `ERR_GAP_NOT_TIER_APPROVED` (HTTP 409)"

    Design: Corner/validations/item_creation_on_analyzed_but_unapproved_gap_rejected
    """
    gap_id = analyzed_gap["gap_id"]

    response = api.create_item(
        f.item_payload(gap_id, trailing_90d_units=None), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_GAP_NOT_TIER_APPROVED.value, 409)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_status(gap, GAP_ANALYZED, "gap")
    assert gap["approved_tier"] is None
    assert_shelf_slots(gap, slots_consumed=0)


def test_third_item_against_a_two_slot_quota_is_rejected(api, tier_approved_gap):
    """The quota is enforced on derived slots_open, which has fallen to zero.

    PRD 3.3: "Because the retailer authorises a finite number of facings, creation
    also requires the gap to have at least one open slot; when `slots_open` has
    fallen to zero the attempt is refused with `ERR_SHELF_SLOT_QUOTA_EXCEEDED`
    (HTTP 409)."

    Design: Corner/validations/third_item_beyond_shelf_slot_quota_rejected
    """
    gap_id = tier_approved_gap["gap_id"]
    first = validate_success(
        api.create_item(
            f.item_payload(gap_id, trailing_90d_units=None), SOURCING_HEADERS
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_item(
            f.item_payload(
                gap_id,
                item_name="Harvest Lane Sesame Crackers",
                pack_size_desc="10 oz carton",
                trailing_90d_units=None,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    response = api.create_item(
        f.item_payload(
            gap_id,
            item_name="Harvest Lane Rye Crackers",
            pack_size_desc="9 oz carton",
            trailing_90d_units=None,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SHELF_SLOT_QUOTA_EXCEEDED.value, 409)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_shelf_slots(
        gap,
        shelf_slots_quota=2,
        slots_consumed=2,
        slots_open=0,
        slots_consumed_lifetime=2,
    )
    rows, meta = validate_paginated(
        api.list_items(SOURCING_HEADERS, params={"gap_id": gap_id})
    )
    assert meta["total_count"] == 2, "the quota must not drift past two facings"
    statuses = {row["id"]: row["development_status"] for row in rows}
    assert statuses[first["id"]] == ITEM_CONCEPT
    assert statuses[second["id"]] == ITEM_CONCEPT


def test_item_creation_under_a_closed_program_is_rejected(api, tier_approved_gap):
    """The program-closed gate sits above the gap-state and quota checks.

    PRD 2.9: "Any mutating request whose resource resolves to a program that is
    `CLOSED` is refused with `ERR_PROGRAM_CLOSED` (HTTP 409)."

    Design: Corner/validations/item_creation_while_program_closed_rejected
    """
    program_id = tier_approved_gap["program_id"]
    gap_id = tier_approved_gap["gap_id"]
    close_program(api, program_id)

    response = api.create_item(
        f.item_payload(gap_id, trailing_90d_units=None), SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_CLOSED.value, 409)

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert_status(program, PROGRAM_CLOSED, "program")
    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_status(gap, GAP_TIER_APPROVED, "gap")
    assert_shelf_slots(gap, slots_open=2)


def test_item_creation_during_a_relaunch_freeze_is_rejected(api, launched_item):
    """A freeze blocks exactly new items and new locks, leaving commitments intact.

    PRD 2.9: "While a program is in `RELAUNCH_FREEZE`, exactly two operations are
    refused with `ERR_PROGRAM_RELAUNCH_FROZEN` (HTTP 409): creating a new item,
    and locking a specification."

    Design: Corner/validations/item_creation_during_relaunch_freeze_rejected
    """
    program_id = launched_item["program_id"]
    gap_id = launched_item["gap_id"]
    start_relaunch(api, program_id)

    response = api.create_item(
        f.item_payload(
            gap_id,
            item_name="Harvest Lane Sesame Crackers",
            pack_size_desc="10 oz carton",
            trailing_90d_units=None,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_RELAUNCH_FROZEN.value, 409)

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert_status(program, PROGRAM_RELAUNCH_FREEZE, "program")
    assert_money_cents(
        program["committed_budget_cents"], 666980, "committed_budget_cents"
    )
    item = validate_success(api.get_item(launched_item["item_id"], SOURCING_HEADERS))
    assert item["development_status"] == ITEM_LAUNCHED
    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_shelf_slots(gap, slots_consumed=1, slots_open=1)
