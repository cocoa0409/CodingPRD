"""Disease events: derived biosecurity posture thresholds, the
confirm-vs-dismiss fork, and the three-link confirmation cascade.
"""

from test_helpers import (
    ADMIN,
    HEALTH,
    PLANNER,
    api_client,
    assert_disease_event,
    book_order,
    allocate_order,
    confirm_disease_event,
    create_active_commitment,
    create_and_place_flock,
    create_complex,
    create_customer,
    create_disease_event,
    create_house,
    create_planned_flock,
    dismiss_disease_event,
    read_commitment,
    read_complex,
    read_flock,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_empty_scope_rejected_and_posture_normal_at_zero_events(api):
    """An empty scope_house_ids is a payload-shape failure; with zero open
    events both region-mate complexes read NORMAL.

    PRD §3.3: "A `HealthOfficial` reports a suspected disease event on a
    complex with a `pathogen` of `HPAI`, `LPAI`, `NEWCASTLE`, or `SALMONELLA`,
    a `detection_date`, and a non-empty `scope_house_ids` listing the houses
    under suspicion."
    PRD §2.7: "Otherwise its posture is `NORMAL`."

    Design: Difficulty/boundary_precision_check/posture_elevates_at_exactly_one_suspected_event
    """
    set_clock("2026-09-01T00:00:00Z")
    north = create_complex(name="North Farm")
    south = create_complex(name="South Farm")

    response = api.create_disease_event(
        north["id"],
        {
            "pathogen": "SALMONELLA",
            "detection_date": "2026-09-01T00:00:00Z",
            "scope_house_ids": [],
        },
        HEALTH,
    )
    validate_error(response, ERR.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_disease_events(north["id"], HEALTH))
    assert rows == [] and meta["total_count"] == 0

    assert read_complex(north["id"])["biosecurity_posture"] == "NORMAL"
    assert read_complex(south["id"])["biosecurity_posture"] == "NORMAL"


def test_posture_elevates_at_exactly_one_suspected_event(api):
    """One SUSPECTED event meets the >= 1 threshold: the owning complex rises
    to ELEVATED while a region-mate with no CONFIRMED event stays NORMAL.

    PRD §2.7: "if the complex itself has at least one disease event in
    `CONFIRMED` status, its posture is `QUARANTINE`. Otherwise, if the
    complex has at least one event in `SUSPECTED` status, or at least one
    *other* complex in the same region carries an event in `CONFIRMED`
    status, its posture is `ELEVATED`. Otherwise its posture is `NORMAL`."
    PRD §3.3: "the mere report already recomputes posture region-wide —
    under §2.7's rule the owning complex rises to `ELEVATED`."

    Design: Difficulty/boundary_precision_check/posture_elevates_at_exactly_one_suspected_event
    """
    set_clock("2026-09-01T00:00:00Z")
    north = create_complex(name="North Farm")
    south = create_complex(name="South Farm")
    house = create_house(north["id"], capacity_hens=50_000)

    event = create_disease_event(
        north["id"], [house["id"]], pathogen="SALMONELLA"
    )
    assert event["status"] == "SUSPECTED"

    assert read_complex(north["id"])["biosecurity_posture"] == "ELEVATED"
    # A region-mate SUSPECTED event alone does not elevate neighbours.
    assert read_complex(south["id"])["biosecurity_posture"] == "NORMAL"


def _setup_riverbend(api):
    """Complex with one PLANNED flock; one event reported then dismissed."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Riverbend", region_code="SOUTHEAST")
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], placement_date="2026-12-01T00:00:00Z",
        placed_hen_count=40_000,
    )
    event1 = create_disease_event(
        complex_["id"], [house["id"]], pathogen="LPAI"
    )
    dismissed = dismiss_disease_event(event1["id"])
    return complex_, house, flock, dismissed


def test_dismiss_branch_relaxes_posture_and_leaves_flocks_untouched(api):
    """The DISMISSED branch only recomputes posture: ELEVATED relaxes back to
    NORMAL and the PLANNED flock is untouched.

    PRD §3.3: "Dismissal is the deliberately lighter sibling branch: from
    `SUSPECTED` it moves the event to `DISMISSED`, bumps the event's
    `version`, and recomputes posture region-wide — a complex with no other
    open events relaxes from `ELEVATED` back to `NORMAL` — with no flock,
    order, or commitment effects whatsoever."

    Design: Difficulty/non_linear_state_machine/disease_confirm_vs_dismiss_branching_fork
    """
    complex_, _, flock, dismissed = _setup_riverbend(api)

    assert dismissed["status"] == "DISMISSED"
    assert dismissed["confirmed_at"] is None
    assert read_complex(complex_["id"])["biosecurity_posture"] == "NORMAL"
    assert read_flock(flock["id"])["status"] == "PLANNED"


def test_confirm_branch_fires_quarantine_cascade(api):
    """The CONFIRMED branch — from the same SUSPECTED fork — drives the
    complex to QUARANTINE and cancels the PLANNED flock.

    PRD §3.3: "Link one: posture is recomputed for every complex in the
    region, and the event's own complex becomes `QUARANTINE`. Link two:
    every `PLANNED` flock of the complex is cancelled to `CANCELLED`".

    Design: Difficulty/non_linear_state_machine/disease_confirm_vs_dismiss_branching_fork
    """
    complex_, house, flock, dismissed = _setup_riverbend(api)
    # The fork: a second event on the same house takes the other branch.
    event2 = create_disease_event(
        complex_["id"], [house["id"]], pathogen="HPAI",
        detection_date="2026-09-02T00:00:00Z",
    )
    confirmed = confirm_disease_event(event2["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_at"] is not None
    assert read_complex(complex_["id"])["biosecurity_posture"] == "QUARANTINE"
    assert read_flock(flock["id"])["status"] == "CANCELLED"
    # The dismissed sibling stays DISMISSED — the branches diverge.
    assert dismissed["status"] == "DISMISSED"


def _setup_delta_cascade(api):
    """Complex with a LAYING flock (H1) and a PLANNED flock (H2); an order
    ALLOCATED to the complex; a SUSPECTED event scoping H1."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Delta Eggs", region_code="SOUTHEAST")
    house1 = create_house(complex_["id"], house_code="H1", capacity_hens=100_000)
    house2 = create_house(complex_["id"], house_code="H2", capacity_hens=50_000)
    laying = create_and_place_flock(
        house1["id"], flock_code="F1",
        placement_date="2026-04-28T00:00:00Z", placed_hen_count=80_000,
    )
    planned = create_planned_flock(
        house2["id"], flock_code="F2", ownership="CONTRACT",
        grower_name="Ozark Pullet Farms",
        placement_date="2026-12-01T00:00:00Z", placed_hen_count=40_000,
    )
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], region_code="SOUTHEAST",
        price_adjustment_cents_per_dozen=0,
    )
    order = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=10_000,
    )
    order = allocate_order(order["id"])
    assert order["status"] == "ALLOCATED"
    assert order["allocated_complex_id"] == complex_["id"]
    event = create_disease_event(complex_["id"], [house1["id"]])
    return complex_, house1, house2, laying, planned, customer, commitment, order, event


def test_disease_confirm_cascade_mutates_complex_flocks_and_order(api):
    """Confirmation links 1 and 2: posture QUARANTINE, the PLANNED flock is
    CANCELLED, and the ALLOCATED order with an open ship window is forced to
    BLOCKED with its allocation cleared.

    PRD §3.3: "confirmation stamps `confirmed_at` with the logical clock,
    increments the event's `version`, and fires a three-link cascade. Link
    one: posture is recomputed for every complex in the region, and the
    event's own complex becomes `QUARANTINE`. Link two: every `PLANNED` flock
    of the complex is cancelled to `CANCELLED` (a planned flock contributes
    no hens, so `hen_inventory` is untouched), and every order currently
    `ALLOCATED` to this complex whose ship week has not yet closed — that is,
    whose `ship_week_start` is fewer than seven days behind the clock — is
    forced back to `BLOCKED` with its `allocated_complex_id` and
    `allocated_dozen` cleared to null."

    Design: Difficulty/transitive_cascade/disease_confirm_three_link_cascade
    """
    (complex_, _, _, laying, planned, _, _, order, event) = (
        _setup_delta_cascade(api)
    )

    confirmed = confirm_disease_event(event["id"])
    assert_disease_event(confirmed)
    assert confirmed["status"] == "CONFIRMED"

    # Link 1: the posture mutation.
    assert read_complex(complex_["id"])["biosecurity_posture"] == "QUARANTINE"
    # Link 2: downstream mutations caused by the posture flip.
    assert read_flock(planned["id"])["status"] == "CANCELLED"
    blocked = read_order(order["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["allocated_complex_id"] is None
    assert blocked["allocated_dozen"] is None
    # The LAYING flock is NOT depopulated by confirmation alone.
    assert read_flock(laying["id"])["status"] == "LAYING"


def test_disease_confirm_increments_commitment_blocked_order_count(api):
    """Link 3: each blocked order's mutation increments its commitment's
    blocked_order_count — the commitment change is caused by the order's
    BLOCKED transition, not directly by the confirm.

    PRD §3.3: "Link three: each order so blocked increments its commitment's
    `blocked_order_count` by one, mutating the commitment."
    PRD §3.6: "The counter is maintained symmetrically: it increments when an
    order enters `BLOCKED` and decrements when a `BLOCKED` order leaves it
    for `ALLOCATED` or `CANCELLED`."

    Design: Difficulty/transitive_cascade/disease_confirm_three_link_cascade
    """
    (complex_, _, _, laying, _, _, commitment, order, event) = (
        _setup_delta_cascade(api)
    )
    assert read_commitment(commitment["id"])["blocked_order_count"] == 0

    confirm_disease_event(event["id"])

    commitment_after = read_commitment(commitment["id"])
    assert commitment_after["blocked_order_count"] == 1
    assert read_order(order["id"])["status"] == "BLOCKED"
    assert read_flock(laying["id"])["status"] == "LAYING"


def test_confirm_twice_returns_invalid_state(api):
    """Re-sending confirm against a CONFIRMED event is rejected and the side
    effects do not fire a second time.

    PRD §3.3: "From `SUSPECTED` (else `ERR_INVALID_STATE`), confirmation
    stamps `confirmed_at` with the logical clock, increments the event's
    `version`, and fires a three-link cascade."

    Design: Corner/state_machines/confirm_twice_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    event = create_disease_event(complex_["id"], [house["id"]])
    confirmed = confirm_disease_event(event["id"])
    assert confirmed["version"] == 2  # create (1) + one confirmation

    validate_error(
        api.confirm_disease_event(event["id"], HEALTH), ERR.ERR_INVALID_STATE
    )
    after = validate_success(api.get_disease_event(event["id"], HEALTH))
    assert after["status"] == "CONFIRMED"
    assert after["version"] == 2


def test_scope_house_from_other_complex_rejected(api):
    """A scope member that exists but belongs to another complex passes
    existence yet fails scope membership.

    PRD §3.3: "Every scope member must resolve (else `ERR_HOUSE_NOT_FOUND`)
    and must belong to the path complex (else
    `ERR_SCOPE_HOUSE_NOT_IN_COMPLEX`); existence of the references is judged
    before that scope check."

    Design: Corner/validations/scope_house_from_other_complex_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    farm_a = create_complex(name="Farm A")
    farm_b = create_complex(name="Farm B")
    house_b = create_house(farm_b["id"], house_code="HB", capacity_hens=50_000)

    response = api.create_disease_event(
        farm_a["id"],
        {
            "pathogen": "HPAI",
            "detection_date": "2026-09-01T00:00:00Z",
            "scope_house_ids": [house_b["id"]],
        },
        HEALTH,
    )
    validate_error(response, ERR.ERR_SCOPE_HOUSE_NOT_IN_COMPLEX)
    rows, meta = validate_paginated(api.list_disease_events(farm_a["id"], HEALTH))
    assert rows == [] and meta["total_count"] == 0
