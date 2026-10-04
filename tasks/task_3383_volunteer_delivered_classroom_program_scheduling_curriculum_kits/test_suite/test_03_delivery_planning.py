"""Delivery creation and planning gates (PRD §2.6, §3.4, §3.6)."""
from test_helpers import (
    COORDINATOR,
    LOGISTICS,
    ApiErrorId,
    TUESDAYS_4,
    add_session,
    api_client,
    assert_delivery,
    assert_kit_ledger_invariant,
    base_world,
    delivery_payload,
    get_agreement,
    get_delivery,
    get_inventory,
    make_delivery,
    plan_delivery,
    planned_delivery,
    schedule_delivery,
    transition_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_delivery_create_missing_required_enrolled_count_returns_validation(api):
    """PRD §3.4: "A `ProgramCoordinator` opens a classroom delivery by supplying
    `agreement_id`, `lead_volunteer_id`, a `classroom_label` such as Room 12 -
    Ms. Alvarez, the coordinating `teacher_email`, the planned
    `enrolled_count`, and `expected_agreement_version`."
    PRD §2.7: "Body shape: required fields are present, no undeclared fields
    appear, enum and `action` values are recognized, and scalar ranges are sane
    — minutes in range, dates parseable — else `ERR_VALIDATION`."

    Design: Corner/entities/corner_delivery_create_missing_required_enrolled_count_returns_validation
    """
    world = base_world()
    payload = delivery_payload(
        world["agreement"]["id"], world["volunteer"]["id"], world["agreement"]["version"]
    )
    del payload["enrolled_count"]
    resp = api_client.create_delivery(payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _ = validate_paginated(api_client.list_deliveries(COORDINATOR))
    assert len(rows) == 0, "no delivery may be created from a malformed body"


def test_delivery_create_extra_computed_field_rejected(api):
    """PRD §2.7: "Body shape: required fields are present, no undeclared fields
    appear, enum and `action` values are recognized, and scalar ranges are sane
    — minutes in range, dates parseable — else `ERR_VALIDATION`."
    PRD §3.4: "Creation snapshots the agreement's current program into the
    delivery's own `program_catalog_id` — later amendments never retro-change
    an existing delivery — computes the immutable `required_kits`"

    Design: Corner/entities/corner_delivery_create_extra_computed_field_rejected
    """
    world = base_world()
    payload = delivery_payload(
        world["agreement"]["id"], world["volunteer"]["id"], world["agreement"]["version"]
    )
    payload["required_kits"] = 1  # computed server-side; not a declared input
    resp = api_client.create_delivery(payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _ = validate_paginated(api_client.list_deliveries(COORDINATOR))
    assert len(rows) == 0


def test_logistics_create_delivery_forbidden(api):
    """PRD §2.1: "A `ProgramCoordinator` runs program delivery: classroom
    deliveries, sessions and substitution, capstone events, rosters, and
    surveys. A `LogisticsCoordinator` owns kit inventory rows and stock
    movements."
    PRD §2.1: "Once authenticated, a role may invoke only the operations
    assigned to it; any other attempt is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/corner_logistics_create_delivery_forbidden
    """
    world = base_world()
    version_before = world["agreement"]["version"]
    payload = delivery_payload(
        world["agreement"]["id"], world["volunteer"]["id"], version_before
    )
    resp = api_client.create_delivery(payload, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_agreement(world["agreement"]["id"])["version"] == version_before, (
        "a rejected create must not mutate the agreement"
    )


def test_delivery_create_stale_agreement_version_rejected(api):
    """PRD §2.6: "Creating a classroom delivery requires the client to supply
    `expected_agreement_version`, carrying the parent partnership agreement's
    `version` as the client last observed it. If the agreement's current
    `version` no longer matches — for example because the agreement was just
    amended, or another delivery was just created under it — the create is
    rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), preventing a
    delivery from being built on superseded terms."

    Design: Corner/cross_cutting_layers/corner_delivery_create_stale_agreement_version_rejected
    """
    world = base_world()
    stale_version = world["agreement"]["version"]
    first = api_client.create_delivery(
        delivery_payload(world["agreement"]["id"], world["volunteer"]["id"], stale_version,
                         classroom_label="Room AP", teacher_email="tap@rv.example"),
        COORDINATOR,
    )
    validate_success(first, 201)
    resp = api_client.create_delivery(
        delivery_payload(world["agreement"]["id"], world["volunteer"]["id"], stale_version,
                         classroom_label="Room AQ", teacher_email="taq@rv.example"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
    rows, _ = validate_paginated(
        api_client.list_deliveries(COORDINATOR, params={"agreement_id": world["agreement"]["id"]})
    )
    assert len(rows) == 1, "only the first delivery exists"


def test_enrollment_outside_program_band_rejected_at_plan(api):
    """PRD §3.4: "Planning the delivery — DRAFT to PLANNED — enforces four
    gates: the agreement is ACTIVE, else `ERR_INVALID_STATE`; `enrolled_count`
    lies within the program's `min_students` to `max_students` inclusive, else
    `ERR_ENROLLMENT_OUT_OF_RANGE`"

    Design: Corner/validations/corner_enrollment_outside_program_band_rejected_at_plan
    """
    world = base_world(program_code="JA-BIZHM", min_students=10, max_students=30)
    d_low = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=5)
    d_high = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=31)

    resp_low = api_client.transition_delivery(d_low["id"], {"action": "PLAN"}, COORDINATOR)
    validate_error(resp_low, ApiErrorId.ERR_ENROLLMENT_OUT_OF_RANGE)
    resp_high = api_client.transition_delivery(d_high["id"], {"action": "PLAN"}, COORDINATOR)
    validate_error(resp_high, ApiErrorId.ERR_ENROLLMENT_OUT_OF_RANGE)
    assert get_delivery(d_low["id"])["status"] == "DRAFT"
    assert get_delivery(d_high["id"])["status"] == "DRAFT"


def test_grade_bands_disjoint_rejected_at_plan(api):
    """PRD §3.4: "the school's grade band overlaps the program's, meaning the
    school's `grade_band_low` does not exceed the program's `grade_band_high`
    and the program's `grade_band_low` does not exceed the school's
    `grade_band_high`, else `ERR_PROGRAM_GRADE_MISMATCH`"

    Design: Corner/validations/corner_grade_bands_disjoint_rejected_at_plan
    """
    world = base_world(program_code="JA-HIGH", program_grade_band=(6, 8))
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=10)
    resp = api_client.transition_delivery(delivery["id"], {"action": "PLAN"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_GRADE_MISMATCH)
    assert get_delivery(delivery["id"])["status"] == "DRAFT"


def test_schedule_without_teacher_confirm_rejected(api):
    """PRD §3.4: "SCHEDULE moves PLANNED to SCHEDULED when four conditions hold
    together: `teacher_confirmed` is true, else `ERR_TEACHER_NOT_CONFIRMED`"

    Design: Corner/validations/corner_schedule_without_teacher_confirm_rejected
    """
    world = base_world(assemble=20)
    delivery = planned_delivery(world, enrolled_count=10)
    for date in TUESDAYS_4:
        add_session(delivery["id"], world["volunteer"]["id"], date, confirm=True)
    transition_delivery(delivery["id"], "RESERVE_KITS")

    resp = api_client.transition_delivery(delivery["id"], {"action": "SCHEDULE"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_TEACHER_NOT_CONFIRMED)
    assert get_delivery(delivery["id"])["status"] == "PLANNED"


def test_schedule_with_insufficient_sessions_rejected(api):
    """PRD §3.4: "the count of the delivery's sessions in SCHEDULED equals the
    program's `session_count`, else `ERR_SESSIONS_INCOMPLETE`"

    Design: Corner/validations/corner_schedule_with_insufficient_sessions_rejected
    """
    world = base_world(assemble=20)
    delivery = planned_delivery(world, enrolled_count=10)
    for date in TUESDAYS_4[:3]:
        add_session(delivery["id"], world["volunteer"]["id"], date, confirm=True)
    add_session(delivery["id"], world["volunteer"]["id"], TUESDAYS_4[3], confirm=False)  # TENTATIVE
    transition_delivery(delivery["id"], "CONFIRM_TEACHER")
    transition_delivery(delivery["id"], "RESERVE_KITS")

    resp = api_client.transition_delivery(delivery["id"], {"action": "SCHEDULE"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SESSIONS_INCOMPLETE)
    assert get_delivery(delivery["id"])["status"] == "PLANNED"


def test_schedule_without_kit_reservation_rejected(api):
    """PRD §3.4: "SCHEDULE moves PLANNED to SCHEDULED when four conditions hold
    together: `teacher_confirmed` is true, else `ERR_TEACHER_NOT_CONFIRMED`;
    the count of the delivery's sessions in SCHEDULED equals the program's
    `session_count`, else `ERR_SESSIONS_INCOMPLETE`; `kit_status` is RESERVED
    or DISTRIBUTED, else `ERR_KITS_NOT_RESERVED`"

    Design: Corner/validations/corner_schedule_without_kit_reservation_rejected
    """
    world = base_world(assemble=20)
    delivery = planned_delivery(world, enrolled_count=10)
    for date in TUESDAYS_4:
        add_session(delivery["id"], world["volunteer"]["id"], date, confirm=True)
    transition_delivery(delivery["id"], "CONFIRM_TEACHER")

    resp = api_client.transition_delivery(delivery["id"], {"action": "SCHEDULE"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_KITS_NOT_RESERVED)
    assert get_delivery(delivery["id"])["status"] == "PLANNED"


def test_delivery_cancel_compensates_kit_reservation(api):
    """PRD §3.6: "When a delivery is cancelled, a `kit_status` of RESERVED
    becomes RELEASED and `required_kits` move from `reserved_count` back to
    `available_count`"
    PRD §2.9: "one invariant holds at all times: the lifetime `assembled_count`
    always equals the sum of the other five counters."

    Design: Corner/state_machines/corner_delivery_cancel_compensates_kit_reservation
    """
    world = base_world(assemble=11)
    delivery = planned_delivery(world, enrolled_count=10)  # required_kits == 11
    reserved = transition_delivery(delivery["id"], "RESERVE_KITS")
    assert reserved["kit_status"] == "RESERVED"
    inv_mid = get_inventory(world["inventory"]["id"])
    assert inv_mid["reserved_count"] == 11 and inv_mid["available_count"] == 0

    cancelled = transition_delivery(delivery["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["kit_status"] == "RELEASED"
    inv_after = get_inventory(world["inventory"]["id"])
    assert inv_after["reserved_count"] == 0
    assert inv_after["available_count"] == 11
    assert_kit_ledger_invariant(inv_after)
