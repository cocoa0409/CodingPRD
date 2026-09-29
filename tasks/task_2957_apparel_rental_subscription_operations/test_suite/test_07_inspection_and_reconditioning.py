"""Inspection records, technician fitness and the fork-join reconditioning legs.

A reverse-logistics job is a fork-join: the inspection decides which of the two
legs a garment owes, and `READY_FOR_PHOTO` is where the legs rejoin.  These
tests pin the immutability of the inspection trail, the live reading of a
technician's suspension, the per-job segregation of duties on a repair sign-off,
the policy ordering that puts stitching before laundry, the non-idempotence of a
sign-off, the bounded repair-retry loop that condemns a garment on its second
failure, and the two unit dimensions moving on their own schedules.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_REPAIR_ATTEMPTS_EXHAUSTED,
    ERR_REPAIR_PENDING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TECHNICIAN_SUSPENDED,
    ERR_UNIT_CONDEMNED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_event_fields,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Catalog,
    Scenario,
    Turn,
    received_turn,
    standard_catalog,
    turn_to_inspection,
)

JsonDict = dict

# The standard turn is received at this instant, so every reconditioning stamp
# in this module is taken from it unless a test moves the clock on purpose.
RECEIPT_CLOCK = K.CLOCK_AUG_10_0900


def _job_in_received(scenario: Scenario):
    """One completed turn whose garment is on the dock with a fresh job."""
    catalog = standard_catalog(scenario)
    turn = received_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    assert_fields(turn.job, state=K.JOB_RECEIVED)
    assert_null(turn.job, "inspecting_technician_id")
    return catalog, turn


def _inspected_job(
    scenario: Scenario,
    soil_level: str,
    damage_severity: str,
    condition_grade_after: str,
):
    """The same turn, inspected once by the first technician."""
    catalog, turn = _job_in_received(scenario)
    turn = turn_to_inspection(
        scenario, catalog, turn, soil_level, damage_severity, condition_grade_after
    )
    assert_fields(
        turn.job, inspecting_technician_id=catalog.inspector["id"]
    )
    return catalog, turn


def test_inspection_rows_are_append_only_and_carry_no_version(
    scenario: Scenario,
) -> None:
    """A re-inspection appends a second row; the first row never changes.

    PRD §3.6: "An inspection record is an immutable event: it carries `id` and `created_at` and neither `updated_at` nor `version`."
    PRD §3.6: "It appends a second inspection record whose `attempt_index` is one greater than the highest existing index on that job."

    Design: Corner/entities/entity_inspection_rows_are_append_only_and_carry_no_version
    """
    catalog, turn = _job_in_received(scenario)

    first = scenario.file_inspection(
        catalog.inspector, turn.job_id, K.SOIL_LIGHT, K.DAMAGE_NONE, K.GRADE_A
    )
    assert_event_fields(first)
    assert_fields(first, attempt_index=1, soil_level=K.SOIL_LIGHT)
    assert_fields(
        scenario.read_job(catalog.inspector, turn.job_id), state=K.JOB_PROCESSING
    )

    second = scenario.file_inspection(
        catalog.inspector,
        turn.job_id,
        K.SOIL_HEAVY,
        K.DAMAGE_NONE,
        K.GRADE_B,
        notes="second pass",
    )
    assert_event_fields(second)
    assert_fields(
        second,
        attempt_index=2,
        soil_level=K.SOIL_HEAVY,
        condition_grade_after=K.GRADE_B,
        notes="second pass",
    )

    # The first row is untouched by the second look.
    replayed = assert_ok(
        scenario.client.get_inspection(
            first["id"], Scenario.tech_headers(catalog.inspector)
        )
    )
    assert_event_fields(replayed)
    assert_fields(
        replayed,
        attempt_index=1,
        soil_level=K.SOIL_LIGHT,
        condition_grade_after=K.GRADE_A,
    )
    assert_null(replayed, "notes")

    rows, _meta = assert_list(
        scenario.client.list_inspections(
            Scenario.tech_headers(catalog.inspector), {"job_id": turn.job_id}
        ),
        total_count=2,
    )
    assert sorted(row["attempt_index"] for row in rows) == [1, 2]


def test_a_suspended_technician_cannot_file_an_inspection(scenario: Scenario) -> None:
    """Suspension is read at request time and lifts the moment it is reversed.

    PRD §3.6: "A `WarehouseTech` inspects a garment sitting on a job in `RECEIVED` or, as a re-inspection, in `PROCESSING`; the acting technician's `status` must be `ACTIVE`, and the unit's `availability_state` must be `PROCESSING`."
    PRD §2.10: "At rank 27, on every endpoint a `WarehouseTech` may call, the acting technician's `status` must be `ACTIVE`, otherwise `ERR_TECHNICIAN_SUSPENDED` (403)."

    Design: Corner/validations/validation_a_suspended_technician_cannot_file_an_inspection
    """
    catalog, turn = _job_in_received(scenario)

    suspended = assert_ok(
        scenario.client.update_technician(
            catalog.inspector["id"],
            F.technician_patch_payload(status=K.TECH_SUSPENDED),
            scenario.admin,
        )
    )
    assert_fields(suspended, status=K.TECH_SUSPENDED)

    refused = scenario.client.file_inspection(
        turn.job_id,
        F.clean_inspection_payload(),
        Scenario.tech_headers(catalog.inspector),
    )
    assert_error(refused, ERR_TECHNICIAN_SUSPENDED)

    frozen = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(frozen, state=K.JOB_RECEIVED)
    assert_null(frozen, "inspecting_technician_id")
    assert_list(
        scenario.client.list_inspections(
            Scenario.tech_headers(catalog.repairer), {"job_id": turn.job_id}
        ),
        total_count=0,
    )

    reinstated = assert_ok(
        scenario.client.update_technician(
            catalog.inspector["id"],
            F.technician_patch_payload(status=K.TECH_ACTIVE),
            scenario.admin,
        )
    )
    assert_fields(reinstated, status=K.TECH_ACTIVE)

    accepted = assert_created(
        scenario.client.file_inspection(
            turn.job_id,
            F.clean_inspection_payload(),
            Scenario.tech_headers(catalog.inspector),
        )
    )
    assert_fields(accepted, attempt_index=1)

    # A pristine garment needs neither leg, so the job joins straight away.
    assert_fields(
        scenario.read_job(catalog.inspector, turn.job_id),
        state=K.JOB_READY_FOR_PHOTO,
        inspecting_technician_id=catalog.inspector["id"],
    )
    assert_list(
        scenario.client.list_inspections(
            Scenario.tech_headers(catalog.inspector), {"job_id": turn.job_id}
        ),
        total_count=1,
    )


def test_the_inspecting_technician_may_not_sign_off_the_repair(
    scenario: Scenario,
) -> None:
    """The split is per job: the inspector is refused, the second technician is not.

    PRD §2.10: "At rank 25, on a repair sign-off, the acting technician's identifier must differ from the identifier of the technician who filed the job's inspection; if they are the same person, the response is `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/rbac_the_inspecting_technician_may_not_sign_off_the_repair
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_NONE, K.DAMAGE_MINOR, K.GRADE_B)
    assert_fields(
        turn.job,
        state=K.JOB_PROCESSING,
        repair_required=True,
        cleaning_required=False,
        repair_attempts=0,
    )

    # Both technicians are ACTIVE and repair_certified, so ranks 26 and 27 pass
    # for either of them and only the duty split can separate them.
    assert_fields(catalog.inspector, repair_certified=True, status=K.TECH_ACTIVE)
    assert_fields(catalog.repairer, repair_certified=True, status=K.TECH_ACTIVE)

    refused = scenario.client.complete_repair(
        turn.job_id,
        F.repair_completion_payload(K.REPAIR_ACCEPTED),
        Scenario.tech_headers(catalog.inspector),
    )
    assert_error(refused, ERR_SEGREGATION_OF_DUTIES)

    # A rejected sign-off may not consume one of the two permitted attempts.
    held = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(held, state=K.JOB_PROCESSING, repair_attempts=0)
    assert_null(held, "repair_completed_at")

    signed = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_ACCEPTED)
    assert_fields(signed, state=K.JOB_READY_FOR_PHOTO, repair_attempts=1)
    assert_instant(signed["repair_completed_at"], RECEIPT_CLOCK, "repair_completed_at")
    assert_money(
        signed, servicing_cost_cents=K.REPAIR_RATE_BY_SEVERITY[K.DAMAGE_MINOR]
    )

    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=K.GRADE_B,
    )


def test_cleaning_signoff_before_the_repair_is_refused_then_accepted(
    scenario: Scenario,
) -> None:
    """Stitching comes before laundry, and the same call succeeds once it has.

    PRD §3.6: "At rank 23, when both `cleaning_required` and `repair_required` are true, the job's `repair_completed_at` must already be non-null before cleaning may be signed off, otherwise the request is refused with `ERR_REPAIR_PENDING` (409)."
    PRD §3.6: "When `cleaning_required` is true, the unit moves `NEEDS_REPAIR → NEEDS_CLEANING` and the job **stays** where it is on a second self-loop `PROCESSING → PROCESSING`, because signing off only one of two required legs is not the join."

    Design: Corner/validations/validation_cleaning_signoff_before_the_repair_is_refused_then_accepted
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_HEAVY, K.DAMAGE_MINOR, K.GRADE_B)
    assert_fields(
        turn.job, state=K.JOB_PROCESSING, cleaning_required=True, repair_required=True
    )
    # The repair branch outranks the cleaning branch on the condition dimension.
    assert_unit_position(
        scenario.read_unit(turn.unit_id), condition_state=K.COND_NEEDS_REPAIR
    )

    too_early = scenario.client.complete_cleaning(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(too_early, ERR_REPAIR_PENDING)
    outstanding = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(outstanding, state=K.JOB_PROCESSING)
    assert_null(outstanding, "cleaning_completed_at")

    repaired = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_ACCEPTED)
    assert_fields(repaired, state=K.JOB_PROCESSING, repair_attempts=1)
    assert_instant(repaired["repair_completed_at"], RECEIPT_CLOCK, "repair_completed_at")
    assert_unit_position(
        scenario.read_unit(turn.unit_id), condition_state=K.COND_NEEDS_CLEANING
    )

    cleaned = scenario.complete_cleaning(catalog.repairer, turn.job_id)
    assert_fields(cleaned, state=K.JOB_READY_FOR_PHOTO)
    assert_instant(cleaned["cleaning_completed_at"], RECEIPT_CLOCK, "cleaning_completed_at")
    assert_money(
        cleaned,
        servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_HEAVY]
        + K.REPAIR_RATE_BY_SEVERITY[K.DAMAGE_MINOR],
    )
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )


def test_second_cleaning_completion_on_the_same_job_is_rejected(
    scenario: Scenario,
) -> None:
    """A sign-off is not idempotent: the replay finds no declared transition.

    PRD §3.6: "Signing off cleaning stamps `cleaning_completed_at`, moves the unit `NEEDS_CLEANING → FLOOR_READY`, and re-rolls `servicing_cost_cents`."
    PRD §2.5: "Ranks 15 and 16 are the two generic state guards, and their order matters: rank 15 rejects a request whose trigger is not a declared transition out of the target resource's **current, non-terminal** state with `ERR_INVALID_STATE_TRANSITION` (409), while rank 16 rejects an action aimed at a resource that already sits in one of its declared terminal states with `ERR_RESOURCE_TERMINAL` (409)."

    Design: Corner/state_machines/state_second_cleaning_completion_on_the_same_job_is_rejected
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_LIGHT, K.DAMAGE_NONE, K.GRADE_A)
    assert_fields(
        turn.job, state=K.JOB_PROCESSING, cleaning_required=True, repair_required=False
    )

    cleaned = scenario.complete_cleaning(catalog.repairer, turn.job_id)
    assert_fields(cleaned, state=K.JOB_READY_FOR_PHOTO)
    assert_instant(cleaned["cleaning_completed_at"], RECEIPT_CLOCK, "cleaning_completed_at")
    assert_money(
        cleaned, servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_LIGHT]
    )

    # A later clock would expose a second stamp, and a second laundry charge
    # would show up in the servicing roll-up.
    scenario.set_clock(K.CLOCK_AUG_11_0900)
    replayed = scenario.client.complete_cleaning(
        turn.job_id, Scenario.tech_headers(catalog.repairer)
    )
    assert_error(replayed, ERR_INVALID_STATE_TRANSITION)

    unchanged = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(unchanged, state=K.JOB_READY_FOR_PHOTO, version=cleaned["version"])
    assert_instant(
        unchanged["cleaning_completed_at"], RECEIPT_CLOCK, "cleaning_completed_at"
    )
    assert_money(
        unchanged, servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_LIGHT]
    )


def test_a_first_failed_repair_holds_the_job_in_the_bounded_retry_loop(
    scenario: Scenario,
) -> None:
    """One failure buys another attempt and still bills the labour that failed.

    PRD §3.6: "When the incremented attempt count is still strictly below the cap of 2 — that is, on the first failure — the job holds its place with a self-loop `PROCESSING → PROCESSING` and the garment stays in `NEEDS_REPAIR`, ready for another attempt; this is the bounded retry loop."
    PRD §3.6: "The repair component is a per-attempt rate keyed on the newest inspection's `damage_severity` — 0 cents for `NONE`, 1,500 cents for `MINOR`, 4,200 cents for `MODERATE`, 9,800 cents for `SEVERE` and 0 cents for `LOSS` — multiplied by the job's `repair_attempts`, floored at zero attempts, so two failed moderate attempts cost 8,400 cents in labour even though nothing was fixed."

    Design: Difficulty/non_linear_state_machine/repair_retry_loop_condemns_job_at_attempt_cap
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_NONE, K.DAMAGE_SEVERE, K.GRADE_C)
    assert_fields(
        turn.job,
        state=K.JOB_PROCESSING,
        repair_required=True,
        cleaning_required=False,
        repair_attempts=0,
        condemned=False,
    )
    assert_money(turn.job, servicing_cost_cents=0)

    failed = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_FAILED)
    assert_fields(
        failed,
        state=K.JOB_PROCESSING,
        repair_attempts=1,
        repair_required=True,
        condemned=False,
    )
    # A failed attempt is not a completed leg, so the stamp stays null and the
    # attempt budget still has one slot left.
    assert_null(failed, "repair_completed_at")
    assert failed["repair_attempts"] < K.REPAIR_ATTEMPT_CAP
    assert_money(
        failed, servicing_cost_cents=K.REPAIR_RATE_BY_SEVERITY[K.DAMAGE_SEVERE]
    )

    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_REPAIR,
        condition_grade=K.GRADE_C,
    )
    assert_fields(scenario.read_claim(turn.claim_id), state=K.CLAIM_OPEN, severity=K.DAMAGE_SEVERE)


def test_the_second_failed_repair_condemns_the_garment_and_escalates_the_claim(
    scenario: Scenario,
) -> None:
    """At the cap the loop breaks: the job sinks, the garment dies, the claim becomes a loss.

    PRD §3.6: "When the incremented attempt count reaches the cap of 2, the job moves `PROCESSING → CONDEMNED_HOLD` with `condemned` set to true; as a second hop the unit moves `NEEDS_REPAIR → CONDEMNED`; and as a third hop, if the linked damage claim's current `severity` is `SEVERE` and its `state` is `OPEN` or `ASSESSED`, that severity is escalated to `LOSS`, because a garment that could not be saved is a total loss rather than a bad tear."
    PRD §3.3: "If the named unit is not in the candidate set, the request is **rejected** rather than waitlisted, and the rejection reports the most specific failing reason: at rank 21, a unit whose `condition_state` is `CONDEMNED` yields `ERR_UNIT_CONDEMNED` (409); at rank 32, a unit that belongs to another style, carries a different size, is not simultaneously `IN_STOCK` and `FLOOR_READY`, or sits on quarantine hold yields `ERR_UNIT_NOT_ALLOCATABLE` (409); at rank 33, a unit whose `turns_completed` has already reached the style's `expected_rental_turns_per_unit` yields `ERR_UNIT_TURNS_EXHAUSTED` (409); and at rank 42, a unit whose existing commitments overlap the requested window under the buffer geometry above yields `ERR_UNIT_WINDOW_COLLISION` (409)."

    Design: Difficulty/non_linear_state_machine/repair_retry_loop_condemns_job_at_attempt_cap
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_NONE, K.DAMAGE_SEVERE, K.GRADE_C)

    scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_FAILED)
    exhausted = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_FAILED)
    assert_fields(
        exhausted,
        state=K.JOB_CONDEMNED_HOLD,
        repair_attempts=K.REPAIR_ATTEMPT_CAP,
        condemned=True,
    )
    assert_null(exhausted, "repair_completed_at")
    assert_money(
        exhausted,
        servicing_cost_cents=K.REPAIR_RATE_BY_SEVERITY[K.DAMAGE_SEVERE]
        * K.REPAIR_ATTEMPT_CAP,
    )

    # The two dimensions part company: the garment is unsalvageable while the
    # logistics dimension is still sitting in reconditioning.
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_CONDEMNED,
        condition_grade=K.GRADE_C,
    )
    assert_fields(
        scenario.read_claim(turn.claim_id), state=K.CLAIM_OPEN, severity=K.DAMAGE_LOSS
    )

    # A second member naming the dead garment is refused by condemnation, which
    # outranks the generic not-allocatable reason.
    other_member = scenario.enrol_member(
        catalog.plan["id"], full_name=K.MEMBER_ILSE_NAME, email=K.MEMBER_ILSE_EMAIL
    )
    refused = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            K.WINDOW_AUG_20_24[0],
            K.WINDOW_AUG_20_24[1],
            turn.unit_id,
        ),
        Scenario.member_headers(other_member),
    )
    assert_error(refused, ERR_UNIT_CONDEMNED)


def test_repair_completion_after_a_reinspection_has_no_attempt_left(
    scenario: Scenario,
) -> None:
    """A re-inspection re-opens the repair leg but never refunds an attempt.

    PRD §3.6: "A job that has already consumed both permitted repair attempts re-opens its repair leg with no attempts left, and the next repair sign-off on it is refused at rank 28 with `ERR_REPAIR_ATTEMPTS_EXHAUSTED`."
    PRD §3.6: "A unit sitting in `NEEDS_CLEANING` whose re-inspection reports a `damage_severity` of `MINOR`, `MODERATE` or `SEVERE`, with `biohazard_flag` false and the unit's `availability_state` still `PROCESSING`, moves `NEEDS_CLEANING → NEEDS_REPAIR`, takes the new `condition_grade_after` as its grade, has its claim severity re-copied as described above, and triggers a lifetime recompute of the member's `damage_risk_score` and `damage_risk_band`."

    Design: Corner/validations/validation_repair_completion_after_a_reinspection_has_no_attempt_left
    """
    catalog, turn = _inspected_job(scenario, K.SOIL_HEAVY, K.DAMAGE_SEVERE, K.GRADE_B)
    assert_fields(turn.job, cleaning_required=True, repair_required=True)

    scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_FAILED)
    accepted = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_ACCEPTED)
    # An accepted sign-off at the cap does not condemn: only a failure does.
    assert_fields(
        accepted,
        state=K.JOB_PROCESSING,
        repair_attempts=K.REPAIR_ATTEMPT_CAP,
        condemned=False,
    )
    assert_instant(accepted["repair_completed_at"], RECEIPT_CLOCK, "repair_completed_at")
    assert_unit_position(
        scenario.read_unit(turn.unit_id), condition_state=K.COND_NEEDS_CLEANING
    )

    scenario.set_clock(K.CLOCK_AUG_11_0900)
    reinspection = scenario.file_inspection(
        catalog.inspector, turn.job_id, K.SOIL_NONE, K.DAMAGE_MODERATE, K.GRADE_B
    )
    assert_fields(reinspection, attempt_index=2)

    reopened = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(
        reopened,
        state=K.JOB_PROCESSING,
        repair_required=True,
        cleaning_required=False,
        repair_attempts=K.REPAIR_ATTEMPT_CAP,
        condemned=False,
    )
    assert_null(reopened, "repair_completed_at")
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_REPAIR,
        condition_grade=K.GRADE_B,
    )
    assert_fields(
        scenario.read_claim(turn.claim_id),
        state=K.CLAIM_OPEN,
        severity=K.DAMAGE_MODERATE,
    )

    spent = scenario.client.complete_repair(
        turn.job_id,
        F.repair_completion_payload(K.REPAIR_ACCEPTED),
        Scenario.tech_headers(catalog.repairer),
    )
    assert_error(spent, ERR_REPAIR_ATTEMPTS_EXHAUSTED)

    stalled = scenario.read_job(catalog.repairer, turn.job_id)
    assert_fields(
        stalled,
        state=K.JOB_PROCESSING,
        repair_attempts=K.REPAIR_ATTEMPT_CAP,
        condemned=False,
    )
    assert_null(stalled, "repair_completed_at")
    assert_list(
        scenario.client.list_inspections(
            Scenario.tech_headers(catalog.inspector), {"job_id": turn.job_id}
        ),
        total_count=2,
    )


# A second circuit whose receipt lands on a later instant, so the two
# dimension tests below read their stamps from a clock of their own.
LATE_RECEIPT_CLOCK = K.CLOCK_AUG_18_0900


def _soiled_turn_awaiting_cleaning(scenario: Scenario):
    """A grubby but undamaged garment received on 18 August and inspected once."""
    catalog = standard_catalog(scenario)
    turn = received_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_10_16,
        planned_ship_date=K.SHIP_DATE_AUG_08,
        carrier_reference=K.CARRIER_OUT_AUG_08,
        dispatch_clock=K.CLOCK_AUG_10_0900,
        return_clock=K.CLOCK_AUG_16_0900,
        receipt_clock=LATE_RECEIPT_CLOCK,
    )
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )
    turn = turn_to_inspection(scenario, catalog, turn, K.SOIL_HEAVY, K.DAMAGE_NONE, K.GRADE_B)
    return catalog, turn


def test_condition_moves_while_availability_stays_parked_in_processing(
    scenario: Scenario,
) -> None:
    """Inspection and cleaning walk the physical dimension; the logistics one does not stir.

    PRD §2.8: "Reconditioning moves `condition_state` while `availability_state` sits at `PROCESSING`, and retirement moves `availability_state` while `condition_state` may sit at `FLOOR_READY` (a planned refresh of a perfectly good garment) or at `CONDEMNED` (a garment destroyed in service)."
    PRD §3.6: "Only when the garment is undamaged and non-hazardous does a `soil_level` other than `NONE` move it `FLOOR_READY → NEEDS_CLEANING`."

    Design: Difficulty/non_linear_state_machine/rental_unit_availability_and_condition_dimensions_advance_independently
    """
    catalog, turn = _soiled_turn_awaiting_cleaning(scenario)
    assert_fields(
        turn.job,
        state=K.JOB_PROCESSING,
        cleaning_required=True,
        repair_required=False,
    )

    after_inspection = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        after_inspection,
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_CLEANING,
        condition_grade=K.GRADE_B,
    )
    # turns_completed is still untouched: only a restock moves that counter.
    assert_fields(after_inspection, turns_completed=0)

    cleaned = scenario.complete_cleaning(catalog.repairer, turn.job_id)
    assert_fields(cleaned, state=K.JOB_READY_FOR_PHOTO)
    assert_instant(
        cleaned["cleaning_completed_at"], LATE_RECEIPT_CLOCK, "cleaning_completed_at"
    )
    assert_money(
        cleaned, servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_HEAVY]
    )

    after_cleaning = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        after_cleaning,
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=K.GRADE_B,
    )
    assert_fields(after_cleaning, turns_completed=0)
    # The garment now looks perfect and is still not allocatable, because the
    # logistics dimension has not come back yet.
    assert_fields(
        scenario.read_style(catalog.style_id), floor_ready_unit_count=0, active_unit_count=1
    )


def test_only_the_restock_brings_the_availability_dimension_home(
    scenario: Scenario,
) -> None:
    """Photography leaves both dimensions alone; the restock moves only availability.

    PRD §3.6: "Its second hop moves the unit `PROCESSING → IN_STOCK` and increments `turns_completed` by exactly 1 — this is the only place in the entire system where that counter moves."
    PRD §3.6: "The third hop moves the linked reservation `RETURNED → CLOSED` and stamps its `revenue_attributed_cents`."

    Design: Difficulty/non_linear_state_machine/rental_unit_availability_and_condition_dimensions_advance_independently
    """
    catalog, turn = _soiled_turn_awaiting_cleaning(scenario)
    scenario.complete_cleaning(catalog.repairer, turn.job_id)

    photographed = scenario.photograph(catalog.inspector, turn.job_id)
    assert_fields(photographed, state=K.JOB_PHOTOGRAPHED)
    assert_instant(photographed["photographed_at"], LATE_RECEIPT_CLOCK, "photographed_at")
    assert_money(
        photographed,
        servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_HEAVY]
        + K.PHOTOGRAPHY_COST_CENTS,
    )
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_fields(
        scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED
    )

    restocked = scenario.restock(catalog.inspector, turn.job_id)
    assert_fields(restocked, state=K.JOB_RESTOCKED)

    home = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        home,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=K.GRADE_B,
    )
    assert_fields(home, turns_completed=1)
    assert_money(
        home,
        cumulative_servicing_cost_cents=K.CLEANING_COST_BY_SOIL[K.SOIL_HEAVY]
        + K.PHOTOGRAPHY_COST_CENTS,
    )

    closed = scenario.read_reservation(turn.reservation_id)
    assert_fields(closed, state=K.RES_CLOSED, is_swap=False)
    assert_money(
        closed, revenue_attributed_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS
    )
    assert_fields(
        scenario.read_style(catalog.style_id), floor_ready_unit_count=1, active_unit_count=1
    )
