"""Requests that break two rules at once, and the identifier that must win.

Each scenario deliberately violates a lower-priority rule and a higher-priority one
in the same call, then repairs only the winner so that the loser surfaces on an
otherwise identical request -- which is what proves the second violation was real
and merely outranked.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

BENIGN_READING_AT = "2026-07-28T08:00:00Z"
LAPSED_CREDENTIAL_ON = "2026-07-31"


def _benign_reading(api, center, access_id):
    """Flow 900, venous pressure 120, recirculation 5.0 -- a referral scoring 0."""
    return fx.seed_reading(
        api,
        access_id,
        center["facility_id"],
        BENIGN_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=120,
        recirculation_pct=5.0,
    )


def _routine_referral(api, center, access_id, triaged=True):
    referral = fx.seed_referral(
        api, access_id, center["facility_id"], missed_treatment_count=0
    )
    if not triaged:
        return referral
    scored = fx.triage(api, referral["id"])
    assert scored["urgency"] == "ROUTINE"
    return scored


def _held_referral_and_lapsed_nurse(api):
    """A referral parked in INFO_REQUESTED and a nurse whose credential expired yesterday."""
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    _benign_reading(api, center, access["id"])
    referral = _routine_referral(api, center, access["id"], triaged=False)
    held = fx.request_info(api, referral["id"])
    lapsed_nurse = fx.seed_sedation_rn(
        api,
        moderate_sedation_credentialed=True,
        credential_expires_on=LAPSED_CREDENTIAL_ON,
        max_concurrent_sedation_cases=2,
    )
    return center, access, held, lapsed_nurse


def _moderate_booking(api, referral, room_id, center, nurse_id, start, end, version=None):
    return api.create_procedure(
        {
            "referral_id": referral["id"],
            "room_id": room_id,
            "primary_operator_id": center["operator_id"],
            "sedation_rn_id": nurse_id,
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "MODERATE",
            "scheduled_start": start,
            "scheduled_end": end,
            "expected_referral_version": referral["version"] if version is None else version,
        },
        fx.COORDINATOR,
    )


def test_01_the_referral_state_conflict_outranks_the_lapsed_sedation_credential(api):
    """One booking breaks two rules and reports only the state one.

    The PRD states: "A booking against a referral in `SUBMITTED`, `INFO_REQUESTED`,
    `SCHEDULED`, `COMPLETED` or `DECLINED` is refused with `ERR_REFERRAL_NOT_TRIAGED`."

    The nurse named in that same body is credentialed but her
    `credential_expires_on` of 2026-07-31 lies before the clock's calendar date, so
    the credential rule is broken too and is not the identifier reported.

    Design: Difficulty/priority_pair_validation_conflict/referral_state_409_outranks_sedation_credential_422_on_booking
    """
    center, _access, held, lapsed_nurse = _held_referral_and_lapsed_nurse(api)
    assert held["status"] == "INFO_REQUESTED"

    refused = _moderate_booking(
        api, held, center["room_id"], center, lapsed_nurse["id"],
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    validate_error(refused, "ERR_REFERRAL_NOT_TRIAGED", 409)

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": held["id"]})
    )
    assert meta["total_count"] == 0

    unchanged = fx.read_referral(api, held["id"])
    assert unchanged["status"] == "INFO_REQUESTED"
    assert unchanged["info_request_count"] == 1
    assert unchanged["version"] == held["version"]


def test_02_repairing_the_referral_state_exposes_the_credential_violation(api):
    """The identical body, differing only in the declared version, now reports the 422.

    The PRD states: "For a `MODERATE` case the sedation nurse must additionally hold
    `moderate_sedation_credentialed` as `true` and a `credential_expires_on` falling on
    or after the clock's current calendar date, otherwise
    `ERR_SEDATION_CREDENTIAL_INVALID`."

    The role-fit rule never fires on either attempt: the named operator is an
    `INTERVENTIONALIST` and the named nurse is a `SEDATION_RN`, so only the credential
    date is stale.

    Design: Difficulty/priority_pair_validation_conflict/referral_state_409_outranks_sedation_credential_422_on_booking
    """
    center, _access, held, lapsed_nurse = _held_referral_and_lapsed_nurse(api)

    validate_error(
        _moderate_booking(
            api, held, center["room_id"], center, lapsed_nurse["id"],
            "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        ),
        "ERR_REFERRAL_NOT_TRIAGED",
        409,
    )

    fx.resubmit(
        api,
        held["id"],
        center["facility_headers"],
        clinical_narrative="fistulogram attached",
        missed_treatment_count=0,
    )
    triaged = fx.triage(api, held["id"])
    assert triaged["status"] == "TRIAGED"

    refused = _moderate_booking(
        api, triaged, center["room_id"], center, lapsed_nurse["id"],
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    validate_error(refused, "ERR_SEDATION_CREDENTIAL_INVALID", 422)

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": triaged["id"]})
    )
    assert meta["total_count"] == 0

    settled = fx.read_referral(api, triaged["id"])
    assert settled["status"] == "TRIAGED"
    assert settled["version"] == triaged["version"]
    assert settled["info_request_count"] == 1

    nurse = validate_success(api.get_clinician(lapsed_nurse["id"], fx.ADMIN))
    assert nurse["clinician_role"] == "SEDATION_RN"
    assert nurse["moderate_sedation_credentialed"] is True
    assert nurse["credential_expires_on"] == LAPSED_CREDENTIAL_ON


def _occupied_room_and_lapsed_nurse(api):
    """A buffered room holding a 13:00 moderate case, plus a nurse whose credential lapsed."""
    center = fx.seed_center(api)
    room = fx.seed_room(api, turnover_buffer_min=30, daily_case_cap=6, recovery_bay_count=3)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    _benign_reading(api, center, access["id"])
    first = _routine_referral(api, center, access["id"])
    second = _routine_referral(api, center, access["id"])
    lapsed_nurse = fx.seed_sedation_rn(
        api,
        moderate_sedation_credentialed=True,
        credential_expires_on=LAPSED_CREDENTIAL_ON,
        max_concurrent_sedation_cases=2,
    )
    incumbent = validate_success(
        _moderate_booking(
            api, first, room["id"], center, center["nurse_id"],
            "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        ),
        201,
    )
    return center, room, second, lapsed_nurse, incumbent


def test_03_the_credential_check_outranks_the_room_occupancy_conflict(api):
    """The same overlapping slot yields two different identifiers, decided by the nurse.

    The PRD states: "An intersection is refused with `ERR_ROOM_OCCUPIED`."

    The first attempt names the lapsed nurse on a slot whose buffered span
    [14:15, 15:45) intersects the incumbent's [13:00, 14:30); it reports the credential
    violation. Swapping in the credentialed nurse and changing nothing else makes the
    room conflict the reported failure, so the slot really was occupied all along.

    Design: Difficulty/priority_pair_validation_conflict/sedation_credential_422_outranks_room_occupancy_409_on_the_same_slot
    """
    center, room, referral, lapsed_nurse, _incumbent = _occupied_room_and_lapsed_nurse(api)

    with_lapsed_nurse = _moderate_booking(
        api, referral, room["id"], center, lapsed_nurse["id"],
        "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z",
    )
    validate_error(with_lapsed_nurse, "ERR_SEDATION_CREDENTIAL_INVALID", 422)

    with_good_nurse = _moderate_booking(
        api, referral, room["id"], center, center["nurse_id"],
        "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z",
    )
    validate_error(with_good_nurse, "ERR_ROOM_OCCUPIED", 409)

    unchanged = fx.read_referral(api, referral["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["version"] == referral["version"]

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 1


def test_04_the_same_referral_books_once_both_violations_are_repaired(api):
    """Adjacency at 14:30 with the credentialed nurse clears every gate at once.

    The PRD states: "Bay headroom is the room's `recovery_bay_count` divided by one bay
    per case, taken to its floor, minus that count, and the count must remain strictly
    below the bay count."

    With three bays the touching recovery windows [14:00, 15:30] and [15:30, 17:00]
    leave a headroom of two, and the clinical spans [13:00, 14:00) and [14:30, 15:30)
    do not overlap, so the nurse ceiling of two is untouched as well.

    Design: Difficulty/priority_pair_validation_conflict/sedation_credential_422_outranks_room_occupancy_409_on_the_same_slot
    """
    center, room, referral, lapsed_nurse, _incumbent = _occupied_room_and_lapsed_nurse(api)

    validate_error(
        _moderate_booking(
            api, referral, room["id"], center, lapsed_nurse["id"],
            "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z",
        ),
        "ERR_SEDATION_CREDENTIAL_INVALID",
        422,
    )
    validate_error(
        _moderate_booking(
            api, referral, room["id"], center, center["nurse_id"],
            "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z",
        ),
        "ERR_ROOM_OCCUPIED",
        409,
    )

    accepted = validate_success(
        _moderate_booking(
            api, referral, room["id"], center, center["nurse_id"],
            "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z",
        ),
        201,
    )
    assert accepted["clinical_status"] == "SCHEDULED"
    assert accepted["sedation_rn_id"] == center["nurse_id"]
    assert fx.read_referral(api, referral["id"])["status"] == "SCHEDULED"

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 2


def _two_attested_aborted_cases(api):
    """Two aborted fee-for-service cases, each carrying one 500000-cent angioplasty line.

    Case A consumed two balloons on its way out of the room; case B reserved no device
    at all. Both allowed amounts land on 500000 cents, which is above the session cap,
    so each billing attempt breaks the fiscal rule and only A satisfies the device rule.
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    reading = _benign_reading(api, center, access["id"])
    referral_a = _routine_referral(api, center, access["id"])
    referral_b = _routine_referral(api, center, access["id"])

    procedure_a = fx.book_case(
        api, referral_a["id"], center["room_id"], center["operator_id"],
        referral_a["version"], "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z",
    )
    procedure_b = fx.book_case(
        api, referral_b["id"], center["room_id"], center["operator_id"],
        referral_b["version"], "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
    )

    lot = fx.seed_lot(api, "BALLOON", received_quantity=10)
    usage = fx.reserve_units(api, procedure_a["id"], lot, 2)

    bundles = {}
    for key, procedure in (("a", procedure_a), ("b", procedure_b)):
        bundle = dict(center)
        bundle["procedure_id"] = procedure["id"]
        bundle["reading_id"] = reading["id"]
        bundle["procedure"] = fx.start_case(api, bundle)
        bundle["procedure"] = fx.abort(api, bundle, abort_reason="Patient became hypotensive.")
        bundle["code"] = fx.file_code_line(
            api,
            bundle,
            hcpcs_code="35476",
            code_family="ANGIOPLASTY",
            base_allowed_cents=500000,
            rank=1,
        )
        bundle["procedure"] = fx.attest(api, bundle)
        assert bundle["procedure"]["coding_status"] == "ATTESTED"
        assert bundle["procedure"]["allowed_amount_cents"] == 500000
        bundles[key] = bundle
    return center, bundles, lot, usage


def test_05_the_code_to_device_gate_outranks_the_session_cap(api):
    """The case with no consumed balloon reports the device mismatch, not the cap.

    The PRD states: "A request that violates both must report
    `ERR_CODE_DEVICE_MISMATCH`."

    It also states: "Lines whose `is_bundled` is true are exempt, as are the `IMAGING`
    and `ACCESS_MAINTENANCE_BUNDLE` families, and a `RESERVED` or `RELEASED` usage does
    not satisfy the requirement — only `CONSUMED` does."

    Case B holds no device usage of any state, and its single unbundled ANGIOPLASTY
    line of 500000 cents also exceeds the 480000-cent cap; only the first identifier is
    reported and no transition is performed.

    Design: Difficulty/priority_pair_validation_conflict/code_device_mismatch_422_outranks_session_cap_409_at_billing
    """
    _center, bundles, _lot, _usage = _two_attested_aborted_cases(api)

    refused = api.bill_procedure(bundles["b"]["procedure_id"], fx.ADMIN)
    validate_error(refused, "ERR_CODE_DEVICE_MISMATCH", 422)

    _items, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundles["b"]["procedure_id"]})
    )
    assert meta["total_count"] == 0

    unchanged = fx.read_procedure(api, bundles["b"]["procedure_id"])
    assert unchanged["coding_status"] == "ATTESTED"
    assert unchanged["clinical_status"] == "ABORTED"
    assert unchanged["allowed_amount_cents"] == 500000
    assert unchanged["billed_amount_cents"] == 0
    assert unchanged["net_receivable_cents"] == 0


def test_06_with_the_device_present_the_same_money_reports_the_session_cap(api):
    """Case A satisfies the device gate, so the fiscal gate becomes the failure.

    The PRD states: "Second, and **only after** the consistency gate has passed, the
    per-session cap: `allowed_amount_cents` must be at most 480000, boundary inclusive,
    and an amount above it is refused with `ERR_SESSION_CAP_EXCEEDED`."

    The abort consumed the reservation and recorded the waste, so two units left the
    shelf and none stayed reserved; that consumption is exactly what promotes the
    reported failure from the device identifier to the fiscal one at an identical
    allowed amount.

    Design: Difficulty/priority_pair_validation_conflict/code_device_mismatch_422_outranks_session_cap_409_at_billing
    """
    _center, bundles, lot, usage = _two_attested_aborted_cases(api)

    consumed = fx.read_usage(api, usage["id"])
    assert consumed["state"] == "CONSUMED"
    assert consumed["wasted_quantity"] == 2

    refused = api.bill_procedure(bundles["a"]["procedure_id"], fx.ADMIN)
    validate_error(refused, "ERR_SESSION_CAP_EXCEEDED", 409)

    unchanged = fx.read_procedure(api, bundles["a"]["procedure_id"])
    assert unchanged["coding_status"] == "ATTESTED"
    assert unchanged["allowed_amount_cents"] == 500000
    assert unchanged["billed_amount_cents"] == 0
    assert unchanged["denied_amount_cents"] == 0
    assert unchanged["net_receivable_cents"] == 0

    settled_lot = fx.read_lot(api, lot["id"])
    assert settled_lot["quantity_on_hand"] == 8
    assert settled_lot["quantity_reserved"] == 0
    assert settled_lot["status"] == "AVAILABLE"
