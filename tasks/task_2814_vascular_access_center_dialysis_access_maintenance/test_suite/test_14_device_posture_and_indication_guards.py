"""Inventory postures, headroom arithmetic and the clinical indication for a conversion.

Each refusal here is issued while the units or the rows it names are otherwise perfectly
available, and every rejected request declares the version its target actually carries, so
an optimistic-concurrency refusal can never be mistaken for the guard under test.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

QUARANTINE_REASON = "sterility investigation"
LAPSED_EXPIRES_ON = "2026-07-15"
IN_DATE_EXPIRES_ON = "2027-06-30"
FISTULA_PLACED_ON = "2026-03-01"
TARGET_PLACED_ON = "2026-07-25"
TARGET_CONVERSION_DATE = "2026-10-01"


def _a_quarantined_lot_and_a_lapsed_one(api):
    """Two balloon lots of ten units each: one pulled from circulation, one out of date.

    Neither lot has ever been reserved from, so both still hold their full ten units on
    hand with nothing promised, and the lapsed lot has never been swept — its status is
    still AVAILABLE, which is what makes the expiry check the only thing that can refuse it.
    """
    bundle = fx.seed_scheduled_case(api)

    quarantined = fx.seed_lot(
        api, "BALLOON", received_quantity=10, expires_on=IN_DATE_EXPIRES_ON
    )
    fx.quarantine_lot(api, quarantined["id"], quarantine_reason=QUARANTINE_REASON)
    quarantined = fx.read_lot(api, quarantined["id"])
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == QUARANTINE_REASON
    assert quarantined["quantity_on_hand"] == 10
    assert quarantined["quantity_reserved"] == 0

    lapsed = fx.seed_lot(
        api, "BALLOON", received_quantity=10, expires_on=LAPSED_EXPIRES_ON
    )
    assert lapsed["status"] == "AVAILABLE"
    assert lapsed["expires_on"] == LAPSED_EXPIRES_ON
    assertions.assert_device_lot(lapsed)
    return bundle, quarantined, lapsed


def test_01_a_pulled_lot_and_an_out_of_date_lot_are_refused_for_different_reasons(api):
    """Twenty units on hand, none of them reservable, and two distinct identifiers say why.

    The PRD states: "The named lot must have `status` of `AVAILABLE`; a `QUARANTINED` lot is
    refused with `ERR_DEVICE_LOT_QUARANTINED`."

    It also states: "Its `expires_on` must be **strictly after** the calendar date of the
    procedure's `scheduled_start`, so a lot expiring on the case date is not usable for that
    case; a violation is refused with `ERR_DEVICE_LOT_EXPIRED`."

    Both requests declare the version their lot actually carries, so neither refusal can be
    the optimistic-concurrency check, and both lots are left with their exact prior
    arithmetic.

    Design: Corner/validations/reserving_from_a_quarantined_or_lapsed_lot_is_rejected
    """
    bundle, quarantined, lapsed = _a_quarantined_lot_and_a_lapsed_one(api)

    pulled = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": quarantined["id"],
            "quantity": 2,
            "expected_device_lot_version": quarantined["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(pulled, "ERR_DEVICE_LOT_QUARANTINED", 422)

    out_of_date = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": lapsed["id"],
            "quantity": 2,
            "expected_device_lot_version": lapsed["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(out_of_date, "ERR_DEVICE_LOT_EXPIRED", 422)

    still_pulled = fx.read_lot(api, quarantined["id"])
    assert still_pulled["status"] == "QUARANTINED"
    assert still_pulled["quantity_on_hand"] == 10
    assert still_pulled["quantity_reserved"] == 0
    assert still_pulled["version"] == quarantined["version"]
    assertions.assert_lot_headroom(still_pulled, 10)

    still_lapsed = fx.read_lot(api, lapsed["id"])
    assert still_lapsed["status"] == "AVAILABLE"
    assert still_lapsed["quantity_on_hand"] == 10
    assert still_lapsed["quantity_reserved"] == 0
    assert still_lapsed["version"] == lapsed["version"]

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert usages == []
    assert meta["total_count"] == 0


def test_02_the_server_side_walk_finds_no_candidate_among_the_same_two_lots(api):
    """The allocation excludes both lots before it ever counts a unit.

    The PRD states: "The candidate set is every lot of the requested type whose `status` is
    `AVAILABLE`, whose `expires_on` is strictly after the calendar date of the procedure's
    `scheduled_start`, and whose headroom is strictly positive; quarantined, expired and
    depleted lots are excluded even when they still hold units on hand."

    It also states: "If the candidate set is empty the call reserves nothing and is refused
    with `ERR_NO_ELIGIBLE_LOT`."

    The distinction matters: an empty candidate set is not the same as a short one, and the
    twenty units sitting on these two shelves must not turn this into a stock complaint.

    Design: Corner/validations/reserving_from_a_quarantined_or_lapsed_lot_is_rejected
    """
    bundle, quarantined, lapsed = _a_quarantined_lot_and_a_lapsed_one(api)

    refused = api.create_device_allocation(
        bundle["procedure_id"], {"device_type": "BALLOON", "quantity": 1}, fx.COORDINATOR
    )
    validate_error(refused, "ERR_NO_ELIGIBLE_LOT", 422)

    for lot in (quarantined, lapsed):
        after = fx.read_lot(api, lot["id"])
        assert after["quantity_on_hand"] == 10
        assert after["quantity_reserved"] == 0
        assert after["version"] == lot["version"]

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert usages == []
    assert meta["total_count"] == 0
    assert fx.read_procedure(api, bundle["procedure_id"])["clinical_status"] == "SCHEDULED"


def _a_five_unit_balloon_lot(api):
    """A scheduled case and one balloon lot holding exactly five in-date units."""
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(api, "BALLOON", received_quantity=5, expires_on=IN_DATE_EXPIRES_ON)
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0
    assertions.assert_lot_headroom(lot, 5)
    return bundle, lot


def test_03_six_units_are_refused_and_five_are_taken_on_the_same_declared_version(api):
    """One unit beyond the shelf is a stock refusal; the shelf exactly emptied is a success.

    The PRD states: "Otherwise the headroom — `quantity_on_hand` minus `quantity_reserved` —
    must be at least the requested `quantity`, boundary inclusive, and a request larger than
    that single lot's headroom is refused with `ERR_INSUFFICIENT_DEVICE_STOCK`."

    The accepted request declares the very version the refused one declared, which is only
    possible because the refusal left the lot untouched. On acceptance the PRD pins the
    arithmetic: "the lot's `quantity_reserved` increases by the reserved `quantity`, its
    `quantity_on_hand` is untouched, and its `version` increments."

    Design: Corner/validations/reserving_beyond_headroom_and_from_a_zero_headroom_lot_are_rejected
    """
    bundle, lot = _a_five_unit_balloon_lot(api)

    over = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": lot["id"],
            "quantity": 6,
            "expected_device_lot_version": lot["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(over, "ERR_INSUFFICIENT_DEVICE_STOCK", 409)

    untouched = fx.read_lot(api, lot["id"])
    assert untouched["quantity_on_hand"] == 5
    assert untouched["quantity_reserved"] == 0
    assert untouched["version"] == lot["version"]

    usage = validate_success(
        api.create_device_usage(
            bundle["procedure_id"],
            {
                "device_lot_id": lot["id"],
                "quantity": 5,
                "expected_device_lot_version": lot["version"],
            },
            fx.COORDINATOR,
        ),
        201,
    )
    assertions.assert_device_usage(usage)
    assert usage["state"] == "RESERVED"
    assert usage["quantity"] == 5
    assert usage["wasted_quantity"] == 0
    assert usage["consumed_at"] is None
    assert usage["released_at"] is None

    promised = fx.read_lot(api, lot["id"])
    assert promised["quantity_on_hand"] == 5
    assert promised["quantity_reserved"] == 5
    assert promised["status"] == "AVAILABLE"
    assert promised["version"] == lot["version"] + 1
    assertions.assert_lot_headroom(promised, 0)
    assertions.assert_device_unit_conservation(promised, [usage])


def test_04_a_lot_at_exactly_zero_headroom_reports_depletion_not_a_shortfall(api):
    """Every unit is still on the shelf, and not one of them is available to promise.

    The PRD states: "A lot whose `status` is `DEPLETED`, or whose headroom is exactly 0, is
    refused with `ERR_LOT_DEPLETED`."

    The status is still `AVAILABLE`, because nothing has left the shelf: the PRD reserves the
    move to `DEPLETED` for consumption, stating "If a consumption drives a lot's
    `quantity_on_hand` to 0, that lot moves `AVAILABLE → DEPLETED` in the same request."

    Design: Corner/validations/reserving_beyond_headroom_and_from_a_zero_headroom_lot_are_rejected
    """
    bundle, lot = _a_five_unit_balloon_lot(api)
    usage = fx.reserve_units(api, bundle["procedure_id"], lot, 5)
    assert usage["state"] == "RESERVED"

    full = fx.read_lot(api, lot["id"])
    assertions.assert_lot_headroom(full, 0)

    refused = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": lot["id"],
            "quantity": 1,
            "expected_device_lot_version": full["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(refused, "ERR_LOT_DEPLETED", 409)

    unchanged = fx.read_lot(api, lot["id"])
    assert unchanged["status"] == "AVAILABLE"
    assert unchanged["quantity_on_hand"] == 5
    assert unchanged["quantity_reserved"] == 5
    assert unchanged["version"] == full["version"]

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"device_lot_id": lot["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in usages] == [usage["id"]]
    assert usages[0]["quantity"] == 5


def test_05_a_fistula_carrying_no_burden_cannot_be_planned_out_of_service(api):
    """The plan row is impeccable and the target is convertible; the source is simply well.

    The PRD states: "And conversion must be clinically indicated: either the source access's
    `access_type` is `TUNNELED_CATHETER`, or its `intervention_burden_score` is at least 4,
    boundary inclusive — a burden of exactly 4 qualifies and 3 does not — otherwise
    `ERR_CONVERSION_NOT_INDICATED`."

    The target-state guard that shares this operation provably does not fire, because the
    PRD admits this target: "Its `target_access_id` must be non-null and the target access's
    `status` must be `PLANNED`, `PLACED` or `MATURING`".

    The refusal writes nothing on either row, so the successor chain the PRD attaches to a
    successful activation — "Activation also writes the target access's
    `predecessor_access_id` to the value of `from_access_id`" — has left no trace.

    Design: Corner/validations/activating_a_plan_from_a_low_burden_fistula_is_rejected
    """
    center = fx.seed_center(api)
    source = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="LEFT",
        site="FOREARM",
        placed_on=FISTULA_PLACED_ON,
    )
    assert source["access_type"] == "AVF"
    assert source["intervention_burden_score"] == 0
    assert source["angioplasty_count"] == 0
    assert source["attributable_infection_count"] == 0

    target = fx.seed_access(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=TARGET_PLACED_ON,
    )
    assert target["status"] == "PLANNED"

    plan = fx.seed_draft_plan(
        api,
        center["patient_id"],
        source,
        target["id"],
        target_access_type="AVG",
        target_conversion_date=TARGET_CONVERSION_DATE,
    )
    assertions.assert_access_conversion_plan(plan)
    assert plan["status"] == "DRAFT"

    refused = api.activate_conversion_plan(plan["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_CONVERSION_NOT_INDICATED", 422)

    unchanged = fx.read_plan(api, plan["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == plan["version"]
    assert unchanged["maturation_check_count"] == 0
    assert unchanged["readiness_met"] is False
    assert unchanged["readiness_failure_reasons"] == []
    assert unchanged["converted_at"] is None

    still_planned = fx.read_access(api, target["id"])
    assert still_planned["status"] == "PLANNED"
    assert still_planned["predecessor_access_id"] is None
    assert still_planned["version"] == target["version"]

    still_well = fx.read_access(api, source["id"])
    assert still_well["status"] == "IN_USE"
    assert still_well["intervention_burden_score"] == 0
    assertions.assert_burden_score(still_well)
