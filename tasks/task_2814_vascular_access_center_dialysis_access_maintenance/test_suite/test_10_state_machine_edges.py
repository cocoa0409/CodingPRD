"""Lifecycle edges: the transitions that are refused and the ones that fire twice.

An access is born counting nothing, a catheter is barred from the maturation fork, a
referral may be triaged exactly once, a cancelled case is inert on every later call, and
a lot's two release paths -- recall and expiry -- give back the promise without moving a
single unit off the shelf.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

ACCESS_PLACED_ON = "2026-04-01"


def test_01_a_new_access_is_born_planned_with_every_counter_at_zero(api):
    """The whole intervention history of a fresh access is a row of zeroes.

    The PRD states: "A newly recorded access begins in `PLANNED`, with
    `angioplasty_count`, `thrombectomy_count`, `catheter_exchange_count`,
    `maturation_intervention_count`, `attributable_infection_count` and
    `intervention_burden_score` all 0, and `abandoned_at` null."

    It also states: "An optional `predecessor_access_id` names the access this one is
    intended to replace, forming a self-referential conversion lineage; it is null for a
    patient's first access."

    And it states: "Recording it increases the owning patient's `access_count` by one;
    `access_count` counts the patient's accesses whose `status` is `PLANNED`, `PLACED`,
    `MATURING`, `IN_USE` or `DYSFUNCTIONAL`, so an access that later reaches `ABANDONED`
    decrements it again." PLANNED is inside that counted set, so the count is already 1
    before the access has been placed.

    Design: Corner/state_machines/new_vascular_access_starts_in_planned_with_zero_counters
    """
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    assert patient["access_count"] == 0

    access = validate_success(
        api.create_vascular_access(
            {
                "patient_id": patient["id"],
                "access_type": "AVG",
                "laterality": "LEFT",
                "site": "FOREARM",
                "placed_on": ACCESS_PLACED_ON,
            },
            fx.COORDINATOR,
        ),
        201,
    )
    assertions.assert_vascular_access(access)
    assert access["status"] == "PLANNED"
    assert access["access_type"] == "AVG"
    assert access["laterality"] == "LEFT"
    assert access["site"] == "FOREARM"
    assert access["placed_on"] == ACCESS_PLACED_ON
    assert access["angioplasty_count"] == 0
    assert access["thrombectomy_count"] == 0
    assert access["catheter_exchange_count"] == 0
    assert access["maturation_intervention_count"] == 0
    assert access["attributable_infection_count"] == 0
    assert access["intervention_burden_score"] == 0
    assert access["abandoned_at"] is None
    assert access["predecessor_access_id"] is None
    assert access["version"] == 1
    assertions.assert_burden_score(access)

    assert fx.read_patient(api, patient["id"])["access_count"] == 1


SINGLE_READING_AT = "2026-07-25T08:00:00Z"


def _referral_triaged_once_off_a_single_reading(api):
    """An IN_USE graft with exactly one in-window reading, and a referral through triage.

    One qualifying reading forces the absolute-based variant, and a flow of 900 with a
    venous pressure of 100, a recirculation of 2.0 and no missed treatments earns nothing
    under any component, so the score is 0 and the urgency bands to ROUTINE.
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        SINGLE_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    referral = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative="rising venous pressures reported at the chair",
        missed_treatment_count=0,
    )
    return center, access, referral


def test_02_a_referral_may_be_triaged_exactly_once(api):
    """The second triage is refused on state, and the first triage's numbers survive it.

    The PRD states: "An `AccessCoordinator` or `CenterAdmin` triages a `SUBMITTED`
    referral, moving it `SUBMITTED → TRIAGED`." A referral already in `TRIAGED` therefore
    fails the declared-state rung, which the PRD describes as "The target row is in a
    state from which the requested transition is declared." Of the two referral
    identifiers that rung offers, the PRD reserves the other one for booking — "A booking
    against a referral in `SUBMITTED`, `INFO_REQUESTED`, `SCHEDULED`, `COMPLETED` or
    `DECLINED` is refused with `ERR_REFERRAL_NOT_TRIAGED`" — so a repeat triage reports
    `ERR_REFERRAL_STATE_INVALID`.

    It also states: "When exactly one reading qualifies, `triage_variant` is
    `ABSOLUTE_BASED`."

    Design: Corner/state_machines/triage_of_an_already_triaged_referral_is_rejected
    """
    _center, _access, referral = _referral_triaged_once_off_a_single_reading(api)
    assert referral["status"] == "SUBMITTED"

    triaged = validate_success(api.triage_referral(referral["id"], fx.COORDINATOR))
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_variant"] == "ABSOLUTE_BASED"
    assert triaged["triage_score"] == 0
    assert triaged["urgency"] == "ROUTINE"
    assertions.assert_instant(triaged["triaged_at"], "triaged_at")

    refused = api.triage_referral(referral["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_REFERRAL_STATE_INVALID", 409)

    unchanged = fx.read_referral(api, referral["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["triage_variant"] == "ABSOLUTE_BASED"
    assert unchanged["triage_score"] == 0
    assert unchanged["urgency"] == "ROUTINE"
    assertions.assert_version_unchanged(triaged, unchanged)


def test_03_the_rejected_second_triage_does_not_re_run_the_triage_consequences(api):
    """The access was moved once, by the triage that succeeded, and not again.

    The PRD states: "When the `suspected_problem` is `STENOSIS`, `THROMBOSIS` or
    `CATHETER_DYSFUNCTION` — that is, a mechanical failure rather than a
    `MATURATION_FAILURE` — and the referral's access is currently `IN_USE`, that access is
    moved `IN_USE → DYSFUNCTIONAL`."

    It also states: "An access moves `IN_USE → DYSFUNCTIONAL` only as a system consequence
    — either when a referral naming it is triaged with a mechanical suspicion, or when its
    attributable infection count reaches two — never by direct request."

    A refused request performs no part of its side effects, so the access's version after
    the second triage is exactly the version the first triage left behind.

    Design: Corner/state_machines/triage_of_an_already_triaged_referral_is_rejected
    """
    _center, access, referral = _referral_triaged_once_off_a_single_reading(api)
    assert access["status"] == "IN_USE"

    fx.triage(api, referral["id"])
    after_first = fx.read_access(api, access["id"])
    assert after_first["status"] == "DYSFUNCTIONAL"

    validate_error(
        api.triage_referral(referral["id"], fx.COORDINATOR),
        "ERR_REFERRAL_STATE_INVALID",
        409,
    )

    after_second = fx.read_access(api, access["id"])
    assert after_second["status"] == "DYSFUNCTIONAL"
    assertions.assert_version_unchanged(after_first, after_second)
    assert after_second["angioplasty_count"] == 0
    assert after_second["intervention_burden_score"] == 0


def _catheter_at_the_fork(api):
    """A tunnelled catheter walked as far as PLACED, standing at the modality fork."""
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    access = fx.seed_catheter_access(api, patient["id"], placed_on=ACCESS_PLACED_ON)
    assert access["access_type"] == "TUNNELED_CATHETER"
    assert access["status"] == "PLANNED"
    placed = fx.move_access(api, access["id"], "PLACED")
    assert placed["status"] == "PLACED"
    return patient, placed


def test_04_a_tunnelled_catheter_is_barred_from_the_maturation_fork(api):
    """The refused branch and the permitted branch are asked of the same PLACED row.

    The PRD states: "`PLACED → MATURING` requires the `access_type` to be `AVF` or `AVG`;
    a `TUNNELED_CATHETER` never matures, and the attempt is refused."

    It also states: "Any pair of current status and requested `to_status` that is not one
    of the declared transitions below — including any attempt to leave the terminal
    `ABANDONED` state — is refused with `ERR_ACCESS_TRANSITION_NOT_ALLOWED`."

    And it states: "`PLACED → IN_USE` requires the `access_type` to be exactly
    `TUNNELED_CATHETER`, because a fistula or graft must pass through `MATURING` first;
    that transition also refreshes the owning patient's `access_count`."

    So the fork is exclusive in both directions on one row: the maturation branch is
    refused and leaves the version untouched, and the direct branch to `IN_USE` then
    succeeds. `PLACED` and `IN_USE` are both inside the counted set, so the patient's
    `access_count` never moves off 1.

    Design: Corner/state_machines/tunneled_catheter_cannot_move_from_placed_to_maturing
    """
    patient, placed = _catheter_at_the_fork(api)
    assert fx.read_patient(api, patient["id"])["access_count"] == 1

    refused = api.set_vascular_access_status(
        placed["id"], {"to_status": "MATURING"}, fx.COORDINATOR
    )
    validate_error(refused, "ERR_ACCESS_TRANSITION_NOT_ALLOWED", 409)

    unchanged = fx.read_access(api, placed["id"])
    assert unchanged["status"] == "PLACED"
    assertions.assert_version_unchanged(placed, unchanged)
    assert fx.read_patient(api, patient["id"])["access_count"] == 1

    in_use = fx.move_access(api, placed["id"], "IN_USE")
    assert in_use["status"] == "IN_USE"
    assert in_use["version"] == placed["version"] + 1
    assert fx.read_patient(api, patient["id"])["access_count"] == 1


def test_05_a_cancelled_case_cannot_be_brought_into_the_room(api):
    """Cancellation is not merely a status: it closes the door the operator would use.

    The PRD states: "Cancellation by an `AccessCoordinator` or `CenterAdmin` accepts an
    optional `cancel_note`, requires the procedure's `clinical_status` to be `SCHEDULED`
    (otherwise `ERR_PROCEDURE_NOT_SCHEDULED`), and moves it `SCHEDULED → CANCELLED` with
    `cancel_reason` recorded as `COORDINATOR_CANCEL`."

    It also states, of starting a case: "The procedure's `clinical_status` must be
    `SCHEDULED`, otherwise `ERR_PROCEDURE_NOT_SCHEDULED`." That generic requirement is
    overridden for the three terminal source states by the categorical sentence
    "`DISCHARGED`, `ABORTED` and `CANCELLED` are all terminal for the clinical dimension.
    Any clinical transition attempted from one of them is refused with
    `ERR_PROCEDURE_TERMINAL`." The override is the only reading under which
    `ERR_PROCEDURE_TERMINAL` is reachable at all, since every non-terminal source state is
    already claimed by an operation's own identifier, so a start attempted on a `CANCELLED`
    case reports `ERR_PROCEDURE_TERMINAL`.

    And it states: "On this explicitly requested cancellation the parent referral reverts
    `SCHEDULED → TRIAGED` so that the case can be rebooked".

    The start is attempted by the assigned primary operator, so no role or assignment rung
    can explain the refusal, and the refusal leaves the case exactly as the cancellation
    left it — still `UNCODED`, with no `sedation_end_at` and no `discharged_at`.

    Design: Corner/state_machines/cancelled_procedure_cannot_be_started
    """
    bundle = fx.seed_scheduled_case(api)

    cancelled = fx.cancel_case(
        api, bundle["procedure_id"], cancel_note="patient admitted overnight elsewhere"
    )
    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "COORDINATOR_CANCEL"
    assert fx.read_referral(api, bundle["referral_id"])["status"] == "TRIAGED"

    refused = api.start_procedure(bundle["procedure_id"], bundle["operator_headers"])
    validate_error(refused, "ERR_PROCEDURE_TERMINAL", 409)

    unchanged = fx.read_procedure(api, bundle["procedure_id"])
    assert unchanged["clinical_status"] == "CANCELLED"
    assert unchanged["coding_status"] == "UNCODED"
    assert unchanged["cancel_reason"] == "COORDINATOR_CANCEL"
    assert unchanged["sedation_end_at"] is None
    assert unchanged["discharged_at"] is None
    assertions.assert_version_unchanged(cancelled, unchanged)

    assert fx.read_referral(api, bundle["referral_id"])["status"] == "TRIAGED"


def test_06_the_second_cancel_of_a_cancelled_case_is_refused_not_absorbed(api):
    """Re-cancelling is an error, not a silent success, and the referral is handed back once.

    The PRD states: "Cancellation by an `AccessCoordinator` or `CenterAdmin` accepts an
    optional `cancel_note`, requires the procedure's `clinical_status` to be `SCHEDULED`
    (otherwise `ERR_PROCEDURE_NOT_SCHEDULED`), and moves it `SCHEDULED → CANCELLED` with
    `cancel_reason` recorded as `COORDINATOR_CANCEL`."

    Because that state requirement is checked against the row rather than against the
    request, the second call cannot be absorbed: the PRD's declared-state rung reads "The
    target row is in a state from which the requested transition is declared."

    The identifier the refusal carries is settled by the terminal sentence: "`DISCHARGED`,
    `ABORTED` and `CANCELLED` are all terminal for the clinical dimension. Any clinical
    transition attempted from one of them is refused with `ERR_PROCEDURE_TERMINAL`." A
    cancellation is a clinical transition and its source row is `CANCELLED`, so the second
    call reports `ERR_PROCEDURE_TERMINAL` rather than the operation's own
    `ERR_PROCEDURE_NOT_SCHEDULED`, which the PRD reserves for the non-terminal source
    states.

    An implementation that treated the repeat as idempotent would bump the procedure's
    version a second time and would have to decide what to do with the referral it already
    reverted; here the referral crosses `SCHEDULED → TRIAGED` exactly once and stays at the
    version the first cancellation left it.

    Design: Corner/state_machines/second_cancel_of_a_cancelled_procedure_is_rejected
    """
    bundle = fx.seed_scheduled_case(api)

    cancelled = fx.cancel_case(
        api, bundle["procedure_id"], cancel_note="first and only cancellation"
    )
    assert cancelled["clinical_status"] == "CANCELLED"
    reverted = fx.read_referral(api, bundle["referral_id"])
    assert reverted["status"] == "TRIAGED"

    refused = api.cancel_procedure(
        bundle["procedure_id"], fx.COORDINATOR, {"cancel_note": "second attempt"}
    )
    validate_error(refused, "ERR_PROCEDURE_TERMINAL", 409)

    unchanged = fx.read_procedure(api, bundle["procedure_id"])
    assert unchanged["clinical_status"] == "CANCELLED"
    assert unchanged["cancel_reason"] == "COORDINATOR_CANCEL"
    assertions.assert_version_unchanged(cancelled, unchanged)

    still_triaged = fx.read_referral(api, bundle["referral_id"])
    assert still_triaged["status"] == "TRIAGED"
    assertions.assert_version_unchanged(reverted, still_triaged)


RECALL_REASON = "manufacturer field safety notice"
STERILITY_REASON = "sterility investigation"


def _case_with_a_four_unit_balloon_reservation(api):
    """A scheduled case holding four units of a ten-unit balloon lot."""
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(api, "BALLOON", received_quantity=10, unit_cost_cents=22000)
    usage = fx.reserve_units(api, bundle["procedure_id"], lot, 4)
    assert usage["state"] == "RESERVED"
    fx.reset_clock(api)
    return bundle, lot, usage


def test_07_a_recall_strips_the_promise_and_leaves_the_shelf_alone(api):
    """Quarantine releases the reservation without moving a single unit off the shelf.

    The PRD states that quarantine "requires the lot's `status` to be `AVAILABLE`, records
    the supplied `quarantine_reason`, and moves it `AVAILABLE → QUARANTINED`; every
    `RESERVED` device usage drawn from that lot is simultaneously moved to `RELEASED`,
    decrementing the lot's `quantity_reserved` by each released `quantity` while leaving
    `quantity_on_hand` untouched."

    It also states, of the release path: "`released_at` is set to the clock and only
    `quantity_reserved` falls."

    And it states: "`received_quantity` is never mutated again; it is the anchor of the
    conservation invariant of §2.11."

    The recall reaches the stock and stops there: the case that was promised those units is
    still `SCHEDULED`, because nothing in the quarantine chain cancels a booking.

    Design: Corner/state_machines/quarantining_a_lot_releases_its_reservations_without_touching_on_hand
    """
    bundle, lot, usage = _case_with_a_four_unit_balloon_reservation(api)

    before = fx.read_lot(api, lot["id"])
    assert before["quantity_on_hand"] == 10
    assert before["quantity_reserved"] == 4
    assert before["status"] == "AVAILABLE"
    assertions.assert_lot_headroom(before, 6)

    quarantined = validate_success(
        api.quarantine_device_lot(
            lot["id"], {"quarantine_reason": RECALL_REASON}, fx.ADMIN
        )
    )
    assertions.assert_device_lot(quarantined)
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == RECALL_REASON
    assert quarantined["quantity_reserved"] == 0
    assert quarantined["quantity_on_hand"] == 10
    assert quarantined["received_quantity"] == 10
    assert quarantined["version"] == before["version"] + 1
    assertions.assert_lot_headroom(quarantined, 10)

    released = fx.read_usage(api, usage["id"])
    assert released["state"] == "RELEASED"
    assert released["quantity"] == 4
    assert released["wasted_quantity"] == 0
    assert released["consumed_at"] is None
    assertions.assert_instant_equals(
        released["released_at"], fx.CLOCK_STARTUP_UTC, "released_at"
    )
    assertions.assert_device_unit_conservation(quarantined, [released])

    assert fx.read_procedure(api, bundle["procedure_id"])["clinical_status"] == "SCHEDULED"


def test_08_the_release_restores_the_lot_and_keeps_the_reason_it_was_pulled(api):
    """A lot comes back reservable, but the units it released stay released.

    The PRD states that release "requires the lot's `status` to be `QUARANTINED` and moves
    it `QUARANTINED → AVAILABLE`, but only while the lot is still in date: a lot whose
    `expires_on` falls before the clock's current calendar date cannot be brought back and
    the attempt is refused with `ERR_DEVICE_LOT_EXPIRED`."

    It also states that the `quarantine_reason` is deliberately retained "rather than
    cleared, so the audit trail survives the release."

    This lot expires on 2027-06-30, well after the clock's calendar date, so the expiry
    guard cannot fire and the transition is the only thing under test. The release is not a
    rollback: the usage the quarantine released is still `RELEASED`, and the four units are
    re-promised only because a fresh reservation asks for them, which leaves two rows on the
    same case.

    Design: Corner/state_machines/releasing_a_quarantined_lot_restores_available_and_keeps_the_reason
    """
    bundle, lot, usage = _case_with_a_four_unit_balloon_reservation(api)
    fx.quarantine_lot(api, lot["id"], quarantine_reason=STERILITY_REASON)

    released_lot = validate_success(api.release_device_lot(lot["id"], fx.ADMIN))
    assert released_lot["status"] == "AVAILABLE"
    assert released_lot["quarantine_reason"] == STERILITY_REASON
    assert released_lot["expires_on"] == "2027-06-30"
    assert released_lot["quantity_on_hand"] == 10
    assert released_lot["quantity_reserved"] == 0
    assertions.assert_lot_headroom(released_lot, 10)

    stale = fx.read_usage(api, usage["id"])
    assert stale["state"] == "RELEASED"
    assert stale["consumed_at"] is None

    second = fx.reserve_units(api, bundle["procedure_id"], released_lot, 4)
    assert second["state"] == "RESERVED"
    assert second["quantity"] == 4
    assert second["released_at"] is None

    reserved_again = fx.read_lot(api, lot["id"])
    assert reserved_again["quantity_on_hand"] == 10
    assert reserved_again["quantity_reserved"] == 4
    assert reserved_again["status"] == "AVAILABLE"
    assert reserved_again["quarantine_reason"] == STERILITY_REASON
    assertions.assert_device_unit_conservation(reserved_again, [stale, second])

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in usages] == [usage["id"], second["id"]]
    assert [row["state"] for row in usages] == ["RELEASED", "RESERVED"]


LAPSING_ON = "2026-08-15"
SWEEP_CLOCK = "2026-09-01T00:00:00Z"


def test_09_the_sweep_expires_a_lapsed_lot_once_and_reports_nothing_thereafter(api):
    """A lot that was perfectly reservable in August is swept away in September.

    The PRD states: "The sweep moves every lot whose `status` is `AVAILABLE` or
    `QUARANTINED` and whose `expires_on` falls strictly before the clock's current calendar
    date into `EXPIRED`, and moves every `RESERVED` device usage on each swept lot to
    `RELEASED`, decrementing that lot's `quantity_reserved` and leaving its
    `quantity_on_hand` untouched."

    It also states: "It reports `expired_lot_ids` and `released_usage_ids`, both ordered by
    their lots' `expires_on` ascending then `created_at` ascending, together with the
    tallies `expired_count` and `released_count`."

    And it states: "The sweep is idempotent: an `EXPIRED` lot is no longer in the input
    set, so a second sweep against an unchanged clock reports nothing."

    The reservation itself was legal when it was made, because the lot's `expires_on` is
    strictly after the calendar date of the case — the PRD notes "so a lot expiring on the
    case date is not usable for that case" — so nothing but the advancing clock turns this
    lot terminal.

    Design: Corner/state_machines/expiry_sweep_expires_a_lapsed_lot_and_releases_its_reserved_units
    """
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(
        api, "SHEATH", received_quantity=8, unit_cost_cents=9000, expires_on=LAPSING_ON
    )
    usage = fx.reserve_units(api, bundle["procedure_id"], lot, 3)
    assert lot["expires_on"] == LAPSING_ON
    assert usage["state"] == "RESERVED"

    fx.set_clock(api, SWEEP_CLOCK)
    first = validate_success(api.run_expiry_sweep(fx.ADMIN))
    assert first["expired_count"] == 1
    assert first["expired_lot_ids"] == [lot["id"]]
    assert first["released_count"] == 1
    assert first["released_usage_ids"] == [usage["id"]]

    expired = fx.read_lot(api, lot["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["quantity_reserved"] == 0
    assert expired["quantity_on_hand"] == 8
    assert expired["received_quantity"] == 8

    swept = fx.read_usage(api, usage["id"])
    assert swept["state"] == "RELEASED"
    assert swept["consumed_at"] is None
    assertions.assert_instant_equals(swept["released_at"], SWEEP_CLOCK, "released_at")
    assertions.assert_device_unit_conservation(expired, [swept])

    second = fx.run_expiry_sweep(api)
    assert second["expired_count"] == 0
    assert second["released_count"] == 0
    assert second["expired_lot_ids"] == []
    assert second["released_usage_ids"] == []

    assert fx.read_lot(api, lot["id"])["status"] == "EXPIRED"
    assert fx.read_procedure(api, bundle["procedure_id"])["clinical_status"] == "SCHEDULED"
