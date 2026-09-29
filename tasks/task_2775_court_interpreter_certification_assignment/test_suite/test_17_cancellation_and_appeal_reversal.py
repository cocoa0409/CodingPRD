"""Compensating reversals: early cancellation and a vacated appeal.

Two conserved-quantity scenarios from the PRD contract:

* an early cancellation of a confirmed assignment must release exactly the
  provisional amount it encumbered, leaving the courthouse ledger on the
  identical trio of numbers it held before the confirmation (PRD §2.9, §3.7);
* a `VACATED` appeal must reverse the sanction's points, roster standing and
  quality scores while leaving the work the sanction cancelled cancelled
  (PRD §3.9).

Every test builds its own world; the server is relaunched before each test.
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_decision_payload,
    assert_ordered_by,
    cancel_assignment_payload,
    create_assignment_payload,
    make_program_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]

# The hearing under test: 2026-08-20T09:00-12:00Z, TRIAL, in custody, at the
# main courthouse whose pay_budget_cents is 5_000_000.
HEARING_OVERRIDES = {
    "case_number": "CR-2026-0120",
    "hearing_type": "TRIAL",
    "in_custody": True,
    "scheduled_start": "2026-08-20T09:00:00.000Z",
    "scheduled_end": "2026-08-20T12:00:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}
# IN_PERSON with 40.0 estimated one-way miles, i.e. past the 30.0-mile free
# radius, so the provisional claim carries a travel component.
ASSIGNMENT_OVERRIDES = {"delivery_mode": "IN_PERSON", "estimated_one_way_miles": 40.0}

PAY_BUDGET_CENTS = 5_000_000
# 3.00 billable hours x 8_750 certified cents = 26_250 service, plus
# 2 x 40.0 x 67.5 = 5_400 travel.
PROVISIONAL_TOTAL_CENTS = 31_650
AVAILABLE_WHILE_ENCUMBERED_CENTS = 4_968_350


def _setup_confirmed_in_person_assignment(config=None):
    """Program config + ACTIVE CERTIFIED interpreter + CONFIRMED assignment.

    The confirmation encumbers PROVISIONAL_TOTAL_CENTS against the courthouse.
    """
    return fixtures.setup_confirmed_assignment(
        config=config,
        hearing_overrides=dict(HEARING_OVERRIDES),
        assignment_overrides=dict(ASSIGNMENT_OVERRIDES),
    )


def _setup_appealed_suspension():
    """Confirmed assignment, then a substantiated 90-day suspension, then an appeal.

    Adds to the bundle: `adjudicated_complaint` (the SUBSTANTIATED complaint),
    `action` (the IN_EFFECT disciplinary action), `sanctioned_interpreter` and
    `cancelled_assignment` (both read after the suspension cascade), and
    `complaint` (the same complaint after the interpreter appealed it).
    """
    bundle = _setup_confirmed_in_person_assignment()
    interpreter_id = bundle["interpreter"]["id"]
    sanction = fixtures.setup_sanction(
        interpreter_id,
        "SUSPENSION",
        assignment_id=bundle["assignment"]["id"],
        severity="MAJOR",
        category="ACCURACY",
        suspension_days=90,
        narrative="Counsel reports whole answers omitted during direct examination.",
    )
    bundle["adjudicated_complaint"] = sanction["complaint"]
    bundle["action"] = sanction["action"]
    bundle["sanctioned_interpreter"] = fixtures.read_interpreter(interpreter_id)
    bundle["cancelled_assignment"] = fixtures.read_assignment(bundle["assignment"]["id"])
    fixtures.set_clock("2026-08-10T00:00:00Z")
    bundle["complaint"] = fixtures.appeal_complaint(
        sanction["complaint"]["id"],
        interpreter_id,
        grounds="The omitted answers were struck from the record before interpretation.",
    )
    return bundle


def _action_row(interpreter_id, action_id):
    """The one disciplinary-action row with this id, from the interpreter listing."""
    rows = fixtures.disciplinary_actions_for(interpreter_id)
    matches = [row for row in rows if row["id"] == action_id]
    assert len(matches) == 1, (
        f"expected exactly one disciplinary action {action_id} for interpreter "
        f"{interpreter_id}, got {[row['id'] for row in rows]}"
    )
    return matches[0]


def test_early_cancellation_returns_the_ledger_to_its_exact_pre_confirmation_triple(api):
    """PRD §2.9: "The ledger is a conserved quantity: confirming an assignment and then cancelling it early returns `encumbered_pay_cents` to exactly its pre-confirmation value, because the claim leaves the `ENCUMBERED` set and no other field absorbs the amount."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."
    PRD §3.7: "An **early** cancellation — lead time at or above that threshold — voids the encumbered claim: it moves `ENCUMBERED → VOIDED`, `provisional_total_cents` is preserved on the row for audit while `final_total_cents` stays null, and exactly `provisional_total_cents` is released from the courthouse's `encumbered_pay_cents`, restoring the ledger to its pre-confirmation value."
    PRD §3.7: "`service_status` tracks the work — `PROPOSED`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `DECLINED`, `CANCELLED`, `SUPERSEDED`, `NO_SHOW`, with the last five terminal on that dimension."
    PRD §3.7: "An explicit cancellation carries a `reason_code`, which is written to `cancel_reason_code`; a cascaded one writes the reason the cascade dictates."

    Design: Difficulty/compensating_invariant/early_cancellation_releases_the_exact_encumbrance_leaving_no_ledger_drift
    """
    config = fixtures.setup_program_config()
    courthouse_id = config["courthouse"]["id"]

    before = fixtures.read_courthouse(courthouse_id)
    assert before["encumbered_pay_cents"] == 0, (
        f"expected 0 encumbered on a fresh courthouse, got {before['encumbered_pay_cents']}"
    )
    assert before["obligated_pay_cents"] == 0, (
        f"expected 0 obligated on a fresh courthouse, got {before['obligated_pay_cents']}"
    )
    assert before["available_pay_cents"] == PAY_BUDGET_CENTS, (
        f"expected {PAY_BUDGET_CENTS} available on a fresh courthouse, "
        f"got {before['available_pay_cents']}"
    )

    bundle = _setup_confirmed_in_person_assignment(config=config)
    encumbered = fixtures.read_courthouse(courthouse_id)
    assert encumbered["encumbered_pay_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected {PROVISIONAL_TOTAL_CENTS} encumbered after confirm, "
        f"got {encumbered['encumbered_pay_cents']}"
    )
    assert encumbered["obligated_pay_cents"] == 0, (
        f"expected 0 obligated after confirm, got {encumbered['obligated_pay_cents']}"
    )
    assert encumbered["available_pay_cents"] == AVAILABLE_WHILE_ENCUMBERED_CENTS, (
        f"expected {AVAILABLE_WHILE_ENCUMBERED_CENTS} available after confirm, "
        f"got {encumbered['available_pay_cents']}"
    )
    assert bundle["pay_claim"]["provisional_total_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected provisional_total_cents {PROVISIONAL_TOTAL_CENTS}, "
        f"got {bundle['pay_claim']['provisional_total_cents']}"
    )

    cancelled = validate_success(
        api.cancel_assignment(
            bundle["assignment"]["id"],
            cancel_assignment_payload(reason_code="COORDINATOR_CANCELLED"),
            COORDINATOR,
        )
    )
    assert cancelled["service_status"] == "CANCELLED", (
        f"expected service_status CANCELLED, got {cancelled['service_status']}"
    )
    assert cancelled["cancel_reason_code"] == "COORDINATOR_CANCELLED", (
        "expected cancel_reason_code COORDINATOR_CANCELLED, got "
        f"{cancelled['cancel_reason_code']}"
    )

    after = fixtures.read_courthouse(courthouse_id)
    assert after["encumbered_pay_cents"] == 0, (
        f"expected 0 encumbered after the early cancellation, "
        f"got {after['encumbered_pay_cents']}"
    )
    assert after["obligated_pay_cents"] == 0, (
        f"expected 0 obligated after the early cancellation, "
        f"got {after['obligated_pay_cents']}"
    )
    assert after["available_pay_cents"] == PAY_BUDGET_CENTS, (
        f"expected available_pay_cents back to {PAY_BUDGET_CENTS}, "
        f"got {after['available_pay_cents']}"
    )


def test_early_cancellation_freezes_the_voided_claim_and_leaves_no_pending_pay(api):
    """PRD §3.7: "An **early** cancellation — lead time at or above that threshold — voids the encumbered claim: it moves `ENCUMBERED → VOIDED`, `provisional_total_cents` is preserved on the row for audit while `final_total_cents` stays null, and exactly `provisional_total_cents` is released from the courthouse's `encumbered_pay_cents`, restoring the ledger to its pre-confirmation value."
    PRD §3.8: "The boolean `late_cancellation` is false unless the final figures were produced by the late-cancellation path, and `payment_reference` stays null until the warrant is issued."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this interpreter's pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`, and `paid_pay_cents` is the same sum restricted to claims in `PAID`."

    Design: Difficulty/compensating_invariant/early_cancellation_releases_the_exact_encumbrance_leaving_no_ledger_drift
    """
    bundle = _setup_confirmed_in_person_assignment()
    claim_id = bundle["pay_claim"]["id"]

    validate_success(
        api.cancel_assignment(
            bundle["assignment"]["id"],
            cancel_assignment_payload(reason_code="COORDINATOR_CANCELLED"),
            COORDINATOR,
        )
    )

    claim = fixtures.read_pay_claim(claim_id)
    assert claim["status"] == "VOIDED", (
        f"expected claim status VOIDED after the early cancellation, got {claim['status']}"
    )
    assert claim["provisional_total_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected provisional_total_cents frozen at {PROVISIONAL_TOTAL_CENTS}, "
        f"got {claim['provisional_total_cents']}"
    )
    assert claim["final_total_cents"] is None, (
        f"expected final_total_cents null on a voided claim, got {claim['final_total_cents']}"
    )
    assert claim["late_cancellation"] is False, (
        f"expected late_cancellation false, got {claim['late_cancellation']}"
    )

    interpreter = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter["pending_pay_cents"] == 0, (
        "expected pending_pay_cents 0 because a VOIDED claim is in none of the "
        f"FINALIZED/SUBMITTED/APPROVED states, got {interpreter['pending_pay_cents']}"
    )


def test_early_cancellation_releases_the_hearing_for_a_fresh_proposal(api):
    """PRD §3.7: "The hearing follows suit: a `COVERED` hearing returns to `SCHEDULED` on an early cancellation and moves to `UNMET` on a late one, incrementing its `version` by 1; a hearing still in `SCHEDULED` because the assignment was only `PROPOSED` is left untouched, as is a hearing already in `CONTINUED`."
    PRD §3.5: "Every one of these transitions increments the hearing's `version` by 1, which is exactly why a client caching a hearing view must re-read it before pinning `expected_hearing_version` on a fresh assignment."
    PRD §3.6: "Creation sets `service_status` to `PROPOSED` and `compliance_status` to `CLEAR`, leaves `actual_one_way_miles`, `check_in_utc`, `actual_end_utc` and `cancel_reason_code` null, and deliberately leaves the hearing in `SCHEDULED` — coverage is recorded only on confirmation."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."
    PRD §4: "Status codes follow one rule: an endpoint that brings a new resource into existence answers 201 Created, and every other successful call — state transitions, updates, computed reads, list reads and the operations capabilities — answers 200 OK."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current page."
    PRD §2.3: "Unless a specific list endpoint declares a different ordering in §4, list results are sorted by `created_at` ascending."

    Design: Difficulty/compensating_invariant/early_cancellation_releases_the_exact_encumbrance_leaving_no_ledger_drift
    """
    bundle = _setup_confirmed_in_person_assignment()
    hearing_id = bundle["hearing"]["id"]
    courthouse_id = bundle["courthouse"]["id"]
    covered_version = bundle["hearing"]["version"]
    assert bundle["hearing"]["status"] == "COVERED", (
        f"expected the confirmed hearing to be COVERED, got {bundle['hearing']['status']}"
    )

    validate_success(
        api.cancel_assignment(
            bundle["assignment"]["id"],
            cancel_assignment_payload(reason_code="COORDINATOR_CANCELLED"),
            COORDINATOR,
        )
    )

    released = fixtures.read_hearing(hearing_id)
    assert released["status"] == "SCHEDULED", (
        f"expected the hearing back at SCHEDULED after the early cancellation, "
        f"got {released['status']}"
    )
    assert released["version"] > covered_version, (
        f"expected the hearing version to rise above {covered_version} on the "
        f"COVERED -> SCHEDULED transition, got {released['version']}"
    )

    fresh = validate_success(
        api.create_assignment(
            create_assignment_payload(
                hearing_id,
                released["version"],
                bundle["interpreter"]["id"],
                delivery_mode="IN_PERSON",
                estimated_one_way_miles=40.0,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert fresh["service_status"] == "PROPOSED", (
        f"expected the re-proposal to land in PROPOSED, got {fresh['service_status']}"
    )

    ledger = fixtures.read_courthouse(courthouse_id)
    assert ledger["encumbered_pay_cents"] == 0, (
        "expected encumbered_pay_cents to stay 0 because a PROPOSED assignment "
        f"creates no claim, got {ledger['encumbered_pay_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing_id})
    )
    assert meta["total_count"] == 2, (
        f"expected total_count 2 for the hearing's assignments, got {meta['total_count']}"
    )
    assert_ordered_by(rows, "created_at")
    assert rows[0]["service_status"] == "CANCELLED", (
        f"expected the first row to be the CANCELLED assignment, "
        f"got {rows[0]['service_status']}"
    )
    assert rows[1]["service_status"] == "PROPOSED", (
        f"expected the second row to be the PROPOSED re-proposal, "
        f"got {rows[1]['service_status']}"
    )


def test_adjudicator_may_not_decide_the_appeal_of_their_own_substantiation(api):
    """PRD §2.10: "Appeal-decision independence: the `ProgramAdmin` whose `X-User-ID` decides an appeal must differ from the `adjudicator_user_id` that the same complaint's adjudication recorded."
    PRD §3.9: "Deciding the appeal is again a `ProgramAdmin` act, and the decider must not be the administrator whose `X-User-ID` is recorded in `adjudicator_user_id`; a self-review of one's own adjudication is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The disciplinary action stays `IN_EFFECT` while the appeal is pending, so an appealing interpreter remains suspended."

    Design: Difficulty/compensating_invariant/vacated_appeal_reverses_points_and_roster_without_resurrecting_cancelled_work
    """
    bundle = _setup_appealed_suspension()
    complaint_id = bundle["complaint"]["id"]
    interpreter_id = bundle["interpreter"]["id"]
    action_id = bundle["action"]["id"]

    assert bundle["adjudicated_complaint"]["status"] == "SUBSTANTIATED", (
        "expected the adjudicated complaint to be SUBSTANTIATED, got "
        f"{bundle['adjudicated_complaint']['status']}"
    )
    assert bundle["complaint"]["status"] == "APPEALED", (
        f"expected the appealed complaint to be APPEALED, got {bundle['complaint']['status']}"
    )
    assert _action_row(interpreter_id, action_id)["status"] == "IN_EFFECT", (
        "expected the disciplinary action to stay IN_EFFECT while the appeal is pending"
    )

    # pa-001 recorded the adjudication, so pa-001 may not decide the appeal.
    validate_error(
        api.decide_appeal(
            complaint_id,
            appeal_decision_payload(outcome="VACATED"),
            make_program_admin_headers("pa-001"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    unchanged = fixtures.read_complaint(complaint_id)
    assert unchanged["status"] == "APPEALED", (
        f"expected the complaint to stay APPEALED after the refused decision, "
        f"got {unchanged['status']}"
    )
    assert _action_row(interpreter_id, action_id)["status"] == "IN_EFFECT", (
        "expected the disciplinary action to stay IN_EFFECT after the refused decision"
    )
    still_suspended = fixtures.read_interpreter(interpreter_id)
    assert still_suspended["roster_status"] == "SUSPENDED", (
        f"expected roster_status to stay SUSPENDED after the refused decision, "
        f"got {still_suspended['roster_status']}"
    )


def test_vacated_appeal_rescinds_the_action_while_its_points_stay_on_the_row(api):
    """PRD §3.9: "**Hop one** creates a single disciplinary action in `IN_EFFECT` status, recording `complaint_id` and copying `interpreter_id` from the complaint, with `action_type` set to the requested sanction and `points` taken from the sanction scale — 5 for a `LETTER`, 10 for `PROBATION`, 12 for a `SUSPENSION`, 20 for a `REVOCATION`."
    PRD §3.9: "Its `effective_from` is the logical-clock date, and its `effective_through` is 365 days after `effective_from` for a `LETTER`, 180 days after for `PROBATION`, the requested `suspension_days` after for a `SUSPENSION`, and null for a `REVOCATION`, which is permanent."
    PRD §3.9: "The disciplinary action created by this complaint's adjudication moves `IN_EFFECT → RESCINDED`, at which point its points drop out of both quality scores and out of `complaint_points`, all three of which are recomputed."
    PRD §4: "Status codes follow one rule: an endpoint that brings a new resource into existence answers 201 Created, and every other successful call — state transitions, updates, computed reads, list reads and the operations capabilities — answers 200 OK."

    Design: Difficulty/compensating_invariant/vacated_appeal_reverses_points_and_roster_without_resurrecting_cancelled_work
    """
    bundle = _setup_appealed_suspension()
    interpreter_id = bundle["interpreter"]["id"]
    action_id = bundle["action"]["id"]

    before = _action_row(interpreter_id, action_id)
    assert before["points"] == 12, (
        f"expected 12 points for a SUSPENSION, got {before['points']}"
    )
    assert before["effective_from"] == "2026-08-01", (
        f"expected effective_from 2026-08-01, got {before['effective_from']}"
    )
    assert before["effective_through"] == "2026-10-30", (
        "expected effective_through 2026-08-01 plus 90 suspension_days = 2026-10-30, "
        f"got {before['effective_through']}"
    )
    assert before["status"] == "IN_EFFECT", (
        f"expected the action to be IN_EFFECT before the appeal decision, "
        f"got {before['status']}"
    )

    decided = validate_success(
        api.decide_appeal(
            bundle["complaint"]["id"],
            appeal_decision_payload(outcome="VACATED"),
            make_program_admin_headers("pa-002"),
        ),
        200,
    )
    assert decided["status"] == "VACATED", (
        f"expected the complaint to reach VACATED, got {decided['status']}"
    )

    after = _action_row(interpreter_id, action_id)
    assert after["status"] == "RESCINDED", (
        f"expected the disciplinary action to be RESCINDED, got {after['status']}"
    )
    assert after["points"] == 12, (
        f"expected the rescinded row to keep its 12 points, got {after['points']}"
    )


def test_vacated_appeal_returns_roster_standing_and_both_quality_scores_to_pre_sanction_values(api):
    """PRD §3.9: "**Hop two** is triggered by that action becoming in-effect: the interpreter's `complaint_points` is recomputed to include the new points, both quality scores are recomputed, and the interpreter's `roster_status` moves `ACTIVE → SUSPENDED` for a suspension, with `suspension_through` set to the action's `effective_through`, or `ACTIVE → REVOKED` for a revocation."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points figure, floored at 0 so it never reports a negative number."
    PRD §3.2: "And `lifetime_score` is 100 less four times the recent-points figure less twice the older-points figure, also floored at 0."
    PRD §3.2: "The separate field `complaint_points` is the plain, unweighted sum of `points` over the same `IN_EFFECT` and `EXPIRED` rows, with no decay and no floor."
    PRD §3.9: "The interpreter's `roster_status` moves `SUSPENDED → ACTIVE` when no other suspension action of theirs remains `IN_EFFECT`, and `suspension_through` returns to null."
    PRD §3.2: "Both are computed from the interpreter's disciplinary actions whose status is either `IN_EFFECT` or `EXPIRED`; a `RESCINDED` action is invisible to both."
    PRD §3.2: "A dedicated computed read exposes the two side by side for one interpreter, returning `interpreter_id`, `rolling_12_month_score`, `lifetime_score`, `complaint_points`, and the two intermediate figures `recent_points` and `older_points` that the formula above derived."

    Design: Difficulty/compensating_invariant/vacated_appeal_reverses_points_and_roster_without_resurrecting_cancelled_work
    """
    bundle = _setup_appealed_suspension()
    interpreter_id = bundle["interpreter"]["id"]

    sanctioned = bundle["sanctioned_interpreter"]
    assert sanctioned["roster_status"] == "SUSPENDED", (
        f"expected roster_status SUSPENDED under the suspension, "
        f"got {sanctioned['roster_status']}"
    )
    assert sanctioned["suspension_through"] == "2026-10-30", (
        "expected suspension_through to copy the action's effective_through 2026-10-30, "
        f"got {sanctioned['suspension_through']}"
    )
    assert sanctioned["complaint_points"] == 12, (
        f"expected complaint_points 12 under the suspension, "
        f"got {sanctioned['complaint_points']}"
    )
    assert sanctioned["rolling_12_month_score"] == 52, (
        f"expected rolling_12_month_score 100 - 4 x 12 = 52, "
        f"got {sanctioned['rolling_12_month_score']}"
    )
    assert sanctioned["lifetime_score"] == 52, (
        f"expected lifetime_score 100 - 4 x 12 - 2 x 0 = 52, "
        f"got {sanctioned['lifetime_score']}"
    )

    decided = validate_success(
        api.decide_appeal(
            bundle["complaint"]["id"],
            appeal_decision_payload(outcome="VACATED"),
            make_program_admin_headers("pa-002"),
        ),
        200,
    )
    assert decided["status"] == "VACATED", (
        f"expected the complaint to reach VACATED, got {decided['status']}"
    )

    reinstated = fixtures.read_interpreter(interpreter_id)
    assert reinstated["roster_status"] == "ACTIVE", (
        f"expected roster_status back to ACTIVE after the vacatur, "
        f"got {reinstated['roster_status']}"
    )
    assert reinstated["suspension_through"] is None, (
        f"expected suspension_through back to null after the vacatur, "
        f"got {reinstated['suspension_through']}"
    )
    assert reinstated["complaint_points"] == 0, (
        f"expected complaint_points 0 once the action is RESCINDED, "
        f"got {reinstated['complaint_points']}"
    )
    assert reinstated["rolling_12_month_score"] == 100, (
        f"expected rolling_12_month_score back to 100, "
        f"got {reinstated['rolling_12_month_score']}"
    )
    assert reinstated["lifetime_score"] == 100, (
        f"expected lifetime_score back to 100, got {reinstated['lifetime_score']}"
    )

    score = fixtures.read_quality_score(interpreter_id)
    assert score["interpreter_id"] == interpreter_id, (
        f"expected the computed read to name interpreter {interpreter_id}, "
        f"got {score['interpreter_id']}"
    )
    assert score["rolling_12_month_score"] == 100, (
        f"expected the computed rolling_12_month_score 100, "
        f"got {score['rolling_12_month_score']}"
    )
    assert score["lifetime_score"] == 100, (
        f"expected the computed lifetime_score 100, got {score['lifetime_score']}"
    )
    assert score["complaint_points"] == 0, (
        f"expected the computed complaint_points 0, got {score['complaint_points']}"
    )
    assert score["recent_points"] == 0, (
        f"expected recent_points 0 once the only action is RESCINDED, "
        f"got {score['recent_points']}"
    )
    assert score["older_points"] == 0, (
        f"expected older_points 0 once the only action is RESCINDED, "
        f"got {score['older_points']}"
    )


def test_vacated_appeal_clears_the_compliance_hold_without_resurrecting_cancelled_work(api):
    """PRD §3.9: "**Hop three** applies to a suspension: every assignment of that interpreter whose `service_status` is `PROPOSED` or `CONFIRMED` and whose hearing's `scheduled_start` date falls on or before `suspension_through` is cancelled with `cancel_reason_code` set to `INTERPRETER_SUSPENDED`, processed in assignment `created_at` ascending order, each cancellation voiding an encumbered claim and returning its hearing to `SCHEDULED`."
    PRD §3.9: "**Hop four** applies when the complaint named an assignment: that assignment's `compliance_status` moves `UNDER_QUALITY_REVIEW → SUBSTANTIATED_DEFECT`, which keeps its pay claim frozen at `SUBMITTED`."
    PRD §3.9: "If the complaint named an assignment, that assignment's `compliance_status` moves `SUBSTANTIATED_DEFECT → CLEAR`, releasing the fiscal hold on its claim."
    PRD §3.9: "What a vacatur does *not* do is resurrect the assignments the sanction cancelled: those rows stay `CANCELLED` with their reason codes intact and their hearings stay wherever the cascade left them."
    PRD §3.8: "Its `status` walks `ENCUMBERED`, then either `FINALIZED` or `VOIDED`, then `SUBMITTED`, `APPROVED`, and `PAID`, with `PAID` and `VOIDED` terminal."
    PRD §2.9: "A claim in `VOIDED` status appears in neither sum, and a vendor-served assignment produces no claim at all and therefore never touches either sum."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Difficulty/compensating_invariant/vacated_appeal_reverses_points_and_roster_without_resurrecting_cancelled_work
    """
    bundle = _setup_appealed_suspension()
    assignment_id = bundle["assignment"]["id"]
    courthouse_id = bundle["courthouse"]["id"]

    cascaded = bundle["cancelled_assignment"]
    assert cascaded["service_status"] == "CANCELLED", (
        f"expected the suspension cascade to cancel the assignment, "
        f"got {cascaded['service_status']}"
    )
    assert cascaded["cancel_reason_code"] == "INTERPRETER_SUSPENDED", (
        f"expected cancel_reason_code INTERPRETER_SUSPENDED, "
        f"got {cascaded['cancel_reason_code']}"
    )
    assert cascaded["compliance_status"] == "SUBSTANTIATED_DEFECT", (
        f"expected compliance_status SUBSTANTIATED_DEFECT after the substantiation, "
        f"got {cascaded['compliance_status']}"
    )

    decided = validate_success(
        api.decide_appeal(
            bundle["complaint"]["id"],
            appeal_decision_payload(outcome="VACATED"),
            make_program_admin_headers("pa-002"),
        ),
        200,
    )
    assert decided["status"] == "VACATED", (
        f"expected the complaint to reach VACATED, got {decided['status']}"
    )

    after = fixtures.read_assignment(assignment_id)
    assert after["compliance_status"] == "CLEAR", (
        f"expected the vacatur to release the fiscal hold to CLEAR, "
        f"got {after['compliance_status']}"
    )
    assert after["service_status"] == "CANCELLED", (
        f"expected the cancelled work to stay CANCELLED after the vacatur, "
        f"got {after['service_status']}"
    )
    assert after["cancel_reason_code"] == "INTERPRETER_SUSPENDED", (
        f"expected the reason code to stay INTERPRETER_SUSPENDED after the vacatur, "
        f"got {after['cancel_reason_code']}"
    )

    claim = fixtures.read_pay_claim(bundle["pay_claim"]["id"])
    assert claim["status"] == "VOIDED", (
        f"expected the voided claim to stay VOIDED, got {claim['status']}"
    )
    assert claim["final_total_cents"] is None, (
        f"expected final_total_cents to stay null on the voided claim, "
        f"got {claim['final_total_cents']}"
    )

    hearing = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing["status"] == "SCHEDULED", (
        f"expected the hearing to stay where the cascade left it, SCHEDULED, "
        f"got {hearing['status']}"
    )

    courthouse = fixtures.read_courthouse(courthouse_id)
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents 0 with the claim voided, "
        f"got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents 0, got {courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == PAY_BUDGET_CENTS, (
        f"expected available_pay_cents {PAY_BUDGET_CENTS} - 0 - 0, "
        f"got {courthouse['available_pay_cents']}"
    )
