"""The three declared-version guards, each fired by a lawful change the client did not see.

In every scenario the row moves between the client's read and its write for a reason the
PRD calls out as ordinary, so the 412 is the only thing standing between a stale view and
a silently superseded one. Each refusal is followed by the identical request carrying the
refreshed version.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

CATHETER_PLACED_ON = "2026-06-01"
TARGET_PLACED_ON = "2026-07-25"
TARGET_CONVERSION_DATE = "2026-10-01"


def test_01_a_missed_treatment_update_between_the_read_and_the_booking_forces_a_412(api):
    """The referral never left TRIAGED, and the version it left behind is no longer current.

    The PRD states: "**Case booking** requires `expected_referral_version`, carrying the
    client's last observed `version` of the target `Referral`. If it does not equal the
    referral's current `version`, the booking is rejected with `ERR_STALE_REFERRAL_VERSION`
    (HTTP 412)."

    It names this precise interleaving as the reason: "This matters because a `TRIAGED`
    referral legitimately keeps moving: a missed-treatment update overwrites
    `missed_treatment_count` and rescores the referring facility, and a facility-posture drop
    can push the very same referral into `INFO_REQUESTED`."

    Two missed treatments cost the facility eight points, so no posture drop fires and the
    referral is still bookable — the refusal is purely about the counter, and the PRD pins
    the counter: `version` "increases by exactly one on every mutation of the row".

    Design: Corner/cross_cutting_complexity_layers/stale_referral_version_on_booking_returns_412
    """
    center = fx.seed_center(api)
    triaged = fx.seed_triaged_referral(api, center)
    stale_version = triaged["referral"]["version"]

    updated = fx.update_missed_treatments(api, triaged["referral_id"], 2)
    assert updated["status"] == "TRIAGED"
    assert updated["missed_treatment_count"] == 2
    assert updated["version"] == stale_version + 1

    scored = fx.read_facility(api, center["facility_id"])
    assert scored["referral_volume_window"] == 1
    assert scored["raw_missed_count_window"] == 2
    assert scored["grace_credit_window"] == 0
    assert scored["adjusted_missed_count_window"] == 2
    assert scored["partnership_score"] == 92
    assert scored["partnership_tier"] == "GOLD"
    assert scored["contract_status"] == "ACTIVE"

    def booking(expected_version):
        return api.create_procedure(
            {
                "referral_id": triaged["referral_id"],
                "room_id": center["room_id"],
                "primary_operator_id": center["operator_id"],
                "procedure_type": "ANGIOPLASTY",
                "sedation_level": "NONE",
                "scheduled_start": fx.DEFAULT_SLOT_START,
                "scheduled_end": fx.DEFAULT_SLOT_END,
                "expected_referral_version": expected_version,
            },
            fx.COORDINATOR,
        )

    validate_error(booking(stale_version), "ERR_STALE_REFERRAL_VERSION", 412)

    nothing_booked, empty_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": triaged["referral_id"]})
    )
    assert nothing_booked == []
    assert empty_meta["total_count"] == 0

    fresh = fx.read_referral(api, triaged["referral_id"])
    assert fresh["version"] == stale_version + 1
    assert fresh["status"] == "TRIAGED"

    booked = validate_success(booking(fresh["version"]), 201)
    assertions.assert_procedure(booked)
    assert booked["clinical_status"] == "SCHEDULED"
    assert fx.read_referral(api, triaged["referral_id"])["status"] == "SCHEDULED"


def test_02_a_replayed_reservation_is_refused_while_six_units_remain_free(api):
    """The lot has ample headroom; the request is simply computed from a superseded read.

    The PRD states: "**Explicit device reservation** requires `expected_device_lot_version`,
    carrying the client's last observed `version` of the named `DeviceLot`. A mismatch with
    the lot's current `version` is rejected with `ERR_STALE_DEVICE_LOT_VERSION` (HTTP 412)."

    The reason it cannot be softened into a stock check is that the reservation arithmetic
    itself depends on the read: "Another reservation, a quarantine, a release or an expiry
    sweep all legitimately change the lot's headroom, so a reservation computed from a stale
    `quantity_on_hand` and `quantity_reserved` pair would over-commit the lot."

    Design: Corner/cross_cutting_complexity_layers/stale_device_lot_version_on_reservation_returns_412
    """
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(api, "BALLOON", received_quantity=8)
    stale_version = lot["version"]

    first = fx.reserve_units(api, bundle["procedure_id"], lot, 2)
    assert first["state"] == "RESERVED"

    replay = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": lot["id"],
            "quantity": 2,
            "expected_device_lot_version": stale_version,
        },
        fx.COORDINATOR,
    )
    validate_error(replay, "ERR_STALE_DEVICE_LOT_VERSION", 412)

    fresh = fx.read_lot(api, lot["id"])
    assert fresh["version"] == stale_version + 1
    assert fresh["quantity_reserved"] == 2
    assert fresh["quantity_on_hand"] == 8
    assertions.assert_lot_headroom(fresh, 6)

    second = validate_success(
        api.create_device_usage(
            bundle["procedure_id"],
            {
                "device_lot_id": lot["id"],
                "quantity": 2,
                "expected_device_lot_version": fresh["version"],
            },
            fx.COORDINATOR,
        ),
        201,
    )
    assertions.assert_device_usage(second)

    after = fx.read_lot(api, lot["id"])
    assert after["quantity_reserved"] == 4
    assert after["quantity_on_hand"] == 8
    assert after["version"] == fresh["version"] + 1

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in usages} == {first["id"], second["id"]}
    assertions.assert_device_unit_conservation(after, usages)


def test_03_a_catheter_that_came_into_use_invalidates_the_plan_built_on_its_old_read(api):
    """Nothing about the source's status would have caught this; only its version does.

    The PRD states: "**Conversion-plan creation** requires `expected_access_version`,
    carrying the client's last observed `version` of the `VascularAccess` named as
    `from_access_id`. A mismatch with that access's current `version` is rejected with
    `ERR_STALE_ACCESS_VERSION` (HTTP 412)."

    The guard is load-bearing here precisely because the operation itself is permissive about
    the source: "Creating a plan supersedes any existing `DRAFT` plan on the same source
    access, and the source access's own `status` may meanwhile have moved to `DYSFUNCTIONAL`
    or `ABANDONED`, so planning from a stale view would retire the wrong access."

    The refreshed creation is then activated without any burden at all, because the PRD
    admits a catheter on the strength of its type alone: "either the source access's
    `access_type` is `TUNNELED_CATHETER`, or its `intervention_burden_score` is at least 4".

    Design: Corner/cross_cutting_complexity_layers/stale_access_version_on_conversion_plan_create_returns_412
    """
    center = fx.seed_center(api)
    catheter = fx.seed_catheter_access(
        api, center["patient_id"], placed_on=CATHETER_PLACED_ON
    )
    at_placed = fx.move_access(api, catheter["id"], "PLACED")
    stale_version = at_placed["version"]
    assert at_placed["status"] == "PLACED"

    in_use = fx.move_access(api, catheter["id"], "IN_USE")
    assert in_use["status"] == "IN_USE"
    assert in_use["version"] == stale_version + 1
    assert in_use["intervention_burden_score"] == 0

    target = fx.seed_access(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=TARGET_PLACED_ON,
    )
    assert target["status"] == "PLANNED"

    def plan(expected_version):
        return api.create_conversion_plan(
            {
                "patient_id": center["patient_id"],
                "from_access_id": catheter["id"],
                "target_access_id": target["id"],
                "target_access_type": "AVF",
                "target_conversion_date": TARGET_CONVERSION_DATE,
                "expected_access_version": expected_version,
            },
            fx.COORDINATOR,
        )

    validate_error(plan(stale_version), "ERR_STALE_ACCESS_VERSION", 412)

    nothing, empty_meta = validate_paginated(
        api.list_conversion_plans(fx.ADMIN, {"from_access_id": catheter["id"]})
    )
    assert nothing == []
    assert empty_meta["total_count"] == 0

    fresh = fx.read_access(api, catheter["id"])
    assert fresh["status"] == "IN_USE"
    assert fresh["version"] == stale_version + 1

    draft = validate_success(plan(fresh["version"]), 201)
    assertions.assert_access_conversion_plan(draft)
    assert draft["status"] == "DRAFT"
    assert draft["readiness_met"] is False
    assert draft["maturation_check_count"] == 0
    assert draft["converted_at"] is None

    activated = fx.activate_plan(api, draft["id"])
    assert activated["status"] == "ACTIVE"
    assert fx.read_access(api, target["id"])["predecessor_access_id"] == catheter["id"]
