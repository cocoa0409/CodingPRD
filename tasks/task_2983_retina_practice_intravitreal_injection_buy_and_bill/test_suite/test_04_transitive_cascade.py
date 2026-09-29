"""
Cascades that travel three and four entities away from the call that fired them.

A related adverse event reaches the plan, its draft encounters, their vials and
the authorization behind them; a lot recall reaches the lot's vials, the draft
encounters holding them and a freshly generated notification set.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COMPLIANCE_USER_ID,
    assert_instant_equals,
    assert_vial_conservation,
    assert_vial_counters,
)
from test_helpers import factories as f

SECOND_STUDY_AT = "2026-08-29T00:00:00Z"
SECOND_ENCOUNTER_AT = "2026-08-29T09:00:00Z"


def _second_draft_on_the_plan(depth) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Move the clock four weeks on, read a fresh study and book a second encounter
    that is still `DRAFT`, returning the study and the encounter.
    """
    depth.set_clock(SECOND_STUDY_AT)
    study = depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt1["id"],
        eye="OD",
        study_datetime=SECOND_STUDY_AT,
        central_subfield_thickness_um=388,
        intraretinal_fluid=True,
    )
    plan = depth.read_plan(depth.plan1["id"])
    encounter = depth.encounter(
        clinician_id=depth.cl1["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=study["id"],
        encounter_datetime=SECOND_ENCOUNTER_AT,
        expected_treatment_plan_version=plan["version"],
    )
    return study, encounter


# ==========================================================================
# related_adverse_event_suspends_plan_voids_draft_and_revives_authorization
# ==========================================================================


def _exhausted_pair(depth) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Build a plan whose two-injection authorization is exhausted by one documented
    and one draft encounter, returning the authorization and both encounters.
    """
    depth.pol_comm_ref
    plan = depth.plan1_active
    pa = depth.approved_authorization(
        treatment_plan_id=plan["id"],
        expected_treatment_plan_version=plan["version"],
        auth_number="AUTH-611",
        approved_injections=2,
        effective_date=depth.CLOCK,
    )
    depth.lot_ref
    current = depth.read_plan(plan["id"])
    first = depth.encounter(
        clinician_id=depth.cl1["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=depth.img1["id"],
        encounter_datetime=depth.ENCOUNTER_AT,
        expected_treatment_plan_version=current["version"],
    )
    depth.document(first["id"], clinician_id=depth.cl1["id"], administered_dose_ml=0.06)
    _, second = _second_draft_on_the_plan(depth)
    return pa, first, second


def test_a_related_endophthalmitis_case_suspends_the_plan_and_dates_the_fda_deadline(
    depth,
):
    """
    Adjudicating an endophthalmitis report as related moves the event, recomputes
    its deadline from onset and suspends the treatment plan behind it.

    The PRD anchors the arithmetic on the clinical instants: "`days_post_injection`
    is written as the whole days from the encounter's `encounter_datetime` to
    `onset_datetime`, truncated downward" — 2026-08-01T09:00 to 2026-08-05T00:00 is
    3 — and "When reportable, `fda_report_due_date` is `onset_datetime` plus fifteen
    days for a `SEVERE` event", giving 2026-08-20.  The cascade is then explicit:
    "An `outcome` of `RELATED` moves the event to `ADJUDICATED_RELATED` and fires
    the system's deepest cascade, four hops of it. Hop two: because the event became
    `ADJUDICATED_RELATED`, the source encounter's treatment plan moves to
    `SUSPENDED` with `suspension_reason` recorded as `ADVERSE_EVENT` and
    `next_due_date` cleared to null."  The adjudicator is not the injector, as
    required by "The adjudicator may not be the clinician who gave the injection".

    Design: Difficulty/transitive_cascade/related_adverse_event_suspends_plan_voids_draft_and_revives_authorization
    """
    _, first, _ = _exhausted_pair(depth)

    event = depth.adverse_event(
        clinician_id=depth.cl1["id"],
        injection_encounter_id=first["id"],
        event_type="ENDOPHTHALMITIS",
        onset_datetime="2026-08-05T00:00:00Z",
        severity="SEVERE",
        culture_result="POSITIVE",
    )
    assert event["status"] == "REPORTED"
    depth.start_investigation(event["id"])
    adjudicated = depth.adjudicate(event["id"], clinician_id=depth.cl2["id"], outcome="RELATED")

    assert adjudicated["status"] == "ADJUDICATED_RELATED"
    assert adjudicated["adjudicated_by_clinician_id"] == depth.cl2["id"]
    assert adjudicated["days_post_injection"] == 3
    assert adjudicated["reportable"] is True
    assert_instant_equals(
        adjudicated["fda_report_due_date"], "2026-08-20T00:00:00Z", "fda_report_due_date"
    )

    plan = depth.read_plan(depth.plan1["id"])
    assert plan["status"] == "SUSPENDED"
    assert plan["suspension_reason"] == "ADVERSE_EVENT"
    assert plan["next_due_date"] is None

    documented = depth.read_encounter(first["id"])
    assert documented["status"] == "DOCUMENTED"


def test_the_suspension_releases_the_draft_vial_and_revives_the_exhausted_authorization(
    depth,
):
    """
    The same adjudication voids the plan's draft encounter, puts its vial back on
    the shelf and hands the freed slot back to the authorization.

    The PRD walks the remaining hops: "Hop three: because that plan became
    `SUSPENDED`, every vial reserved for one of the plan's `DRAFT` encounters
    returns to `IN_STOCK` and those encounters move to `VOIDED` with `void_reason`
    recorded as `PLAN_SUSPENDED`. Hop four: because those encounters became
    `VOIDED`, the plan's authorizations have `injections_used` recomputed and any
    that stood `EXHAUSTED` returns to `APPROVED`."  Releasing a reservation clears
    its pointers — "taking it clears both `reserved_for_encounter_id` and
    `reserved_at` back to null".  The conditional fifth hop counts but does not yet
    freeze: "the source lot's `related_endophthalmitis_count` is incremented, and if
    that count reaches two, the lot itself moves `AVAILABLE → QUARANTINED`", and one
    case is not two.

    Design: Difficulty/transitive_cascade/related_adverse_event_suspends_plan_voids_draft_and_revives_authorization
    """
    pa, first, second = _exhausted_pair(depth)
    assert depth.read_authorization(pa["id"])["status"] == "EXHAUSTED"

    event = depth.adverse_event(
        clinician_id=depth.cl1["id"],
        injection_encounter_id=first["id"],
        event_type="ENDOPHTHALMITIS",
        onset_datetime="2026-08-05T00:00:00Z",
        severity="SEVERE",
        culture_result="POSITIVE",
    )
    depth.start_investigation(event["id"])
    depth.adjudicate(event["id"], clinician_id=depth.cl2["id"], outcome="RELATED")

    voided = depth.read_encounter(second["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "PLAN_SUSPENDED"

    vial = depth.read_vial(second["vial_id"])
    assert vial["status"] == "IN_STOCK"
    assert vial["reserved_for_encounter_id"] is None
    assert vial["reserved_at"] is None

    revived = depth.read_authorization(pa["id"])
    assert revived["injections_used"] == 1
    assert revived["status"] == "APPROVED"

    lot = depth.read_lot(depth.lot_ref["id"])
    assert lot["related_endophthalmitis_count"] == 1
    assert lot["status"] == "AVAILABLE"
    assert_vial_counters(lot, vials_on_hand=4, vials_reserved=0, vials_administered=1)
    assert_vial_conservation(lot, 5)


# ==========================================================================
# lot_recall_quarantines_vials_voids_drafts_and_generates_notifications
# ==========================================================================


def test_recalling_a_lot_freezes_every_vial_and_voids_the_draft_holding_one(
    depth, compliance
):
    """
    A Class II recall on a lot with three shelved vials, one reserved and one
    injected freezes four of them, voids the draft reservation and dates the
    notification deadline ten days out.

    The PRD pins the deadline table — "`notification_deadline_date` is computed as
    the logical clock plus the class notice period: three days for `CLASS_I`, ten
    for `CLASS_II`, thirty for `CLASS_III`" — so a clock of 2026-08-29 gives
    2026-09-08.  The lot cascade is stated in one breath: "the lot moves to
    `RECALLED`, which is terminal; both its `IN_STOCK` and its `RESERVED` vials move
    to `QUARANTINED`; any `DRAFT` encounter holding one of those reserved vials is
    `VOIDED` with `void_reason` recorded as `LOT_RECALLED`".  The already-injected
    vial is untouched, so the six counters still sum to the five vials booked in.

    Design: Difficulty/transitive_cascade/lot_recall_quarantines_vials_voids_drafts_and_generates_notifications
    """
    depth.enc1_documented
    _, second = _second_draft_on_the_plan(depth)

    response = depth.api.create_lot_recall(
        f.recall_payload(
            drug_lot_id=depth.lot_ref["id"],
            recall_class="CLASS_II",
            reason="Manufacturer sterility deviation",
        ),
        compliance,
    )
    recall = validate_success(response, 201)

    assert recall["status"] == "INITIATED"
    assert recall["initiated_by_user_id"] == COMPLIANCE_USER_ID
    assert recall["notifications_required"] == 1
    assert_instant_equals(
        recall["notification_deadline_date"], "2026-09-08T00:00:00Z", "notification_deadline_date"
    )

    lot = depth.read_lot(depth.lot_ref["id"])
    assert lot["status"] == "RECALLED"
    assert_vial_counters(
        lot,
        vials_on_hand=0,
        vials_reserved=0,
        vials_quarantined=4,
        vials_administered=1,
    )
    assert_vial_conservation(lot, 5)

    vial = depth.read_vial(second["vial_id"])
    assert vial["status"] == "QUARANTINED"

    voided = depth.read_encounter(second["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "LOT_RECALLED"


def test_only_the_documented_encounter_generates_a_notification(depth, compliance):
    """
    The same recall generates exactly one notification — for the injected patient —
    and hands the freed authorization slot back.

    The PRD scopes the exposed population precisely: "The exposed population is
    every injection encounter whose administered vial belongs to the recalled lot
    and whose `status` is `DOCUMENTED`, `ATTESTED`, `BILLED` or `CLOSED`. `DRAFT`
    and `VOIDED` encounters generate no notification even when they held a vial
    from the lot, because no drug reached the patient."  Each row is born from the
    exposing encounter: "Each notification is born `PENDING` with `lot_recall_id`
    naming the recall, `patient_id` and `injection_encounter_id` copied from the
    exposing encounter, `channel` copied from that patient's `notification_channel`
    as it stood at generation time, and `sent_at`, `acknowledged_at` and
    `attempt_note` all null."  The voided draft also frees authorization capacity:
    "the authorization's `injections_used` is nevertheless recomputed".

    Design: Difficulty/transitive_cascade/lot_recall_quarantines_vials_voids_drafts_and_generates_notifications
    """
    depth.enc1_documented
    _second_draft_on_the_plan(depth)
    recall = depth.recall(
        drug_lot_id=depth.lot_ref["id"],
        recall_class="CLASS_II",
        reason="Manufacturer sterility deviation",
    )

    notifications = depth.recall_notifications(recall["id"])
    assert len(notifications) == 1
    only = notifications[0]
    assert only["lot_recall_id"] == recall["id"]
    assert only["patient_id"] == depth.pt1["id"]
    assert only["injection_encounter_id"] == depth.enc1["id"]
    assert only["channel"] == "EMAIL"
    assert only["status"] == "PENDING"
    assert only["sent_at"] is None
    assert only["acknowledged_at"] is None
    assert only["attempt_note"] is None

    authorization = depth.read_authorization(depth.pa1["id"])
    assert authorization["injections_used"] == 1
