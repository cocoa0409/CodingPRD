"""Two single-call cascades that travel four hops without any further request.

* One `POST /complaints/{id}/adjudicate` substantiating a MAJOR complaint with a
  90-day suspension walks complaint -> disciplinary action -> interpreter roster
  and quality scores -> assignment cancellation -> voided claim, released
  courthouse encumbrance and a hearing returned to SCHEDULED (PRD §3.9, §3.7,
  §2.9, §3.2).
* One `POST /hearings/{id}/continue` 33 hours before a hearing walks hearing ->
  assignment cancellation -> a claim finalized on the late-cancellation terms ->
  a courthouse encumbrance replaced by an obligation that also lands in the
  interpreter's `pending_pay_cents` (PRD §3.5, §3.7, §3.8, §2.9, §3.2).
"""

from test_helpers import (
    adjudicate_complaint_payload,
    continue_hearing_payload,
    validate_success,
)
import test_helpers.fixtures as fixtures

SUSPENSION_DAYS = 90


def _reviewed_suspension_case():
    """CONFIRMED assignment on H1 plus a REVIEWED MAJOR complaint naming it.

    The claim behind the confirmed assignment is ENCUMBERED at 22050 cents, so
    the courthouse carries exactly that much encumbrance before the trigger.
    """
    bundle = fixtures.setup_confirmed_assignment(
        assignment_overrides={"estimated_one_way_miles": 33.7}
    )
    bundle["complaint"] = fixtures.setup_reviewed_complaint(
        bundle["interpreter"]["id"],
        bundle["assignment"]["id"],
        category="PROFESSIONALISM",
        severity="MAJOR",
        narrative="Interpreter abandoned the courtroom mid-proceeding.",
        recommendation="SUBSTANTIATE",
        findings="Bailiff and clerk statements corroborate the account.",
    )
    return bundle


def _adjudicate_with_suspension(api, headers, complaint_id):
    """The single trigger call: substantiate with a 90-day suspension."""
    return validate_success(
        api.adjudicate_complaint(
            complaint_id,
            adjudicate_complaint_payload(
                "SUBSTANTIATED",
                sanction_type="SUSPENSION",
                suspension_days=SUSPENSION_DAYS,
            ),
            headers,
        ),
        200,
    )


def test_adjudication_substantiates_the_complaint_and_records_the_adjudicator(
    api, program_admin_headers
):
    """PRD §3.9: "A substantiation is the loud branch, `REVIEWED →
    SUBSTANTIATED`, and it cascades in four hops."
    PRD §3.9: "Both branches record `adjudicator_user_id` from the caller's
    `X-User-ID` and `adjudicated_at` from the logical clock, which starts the appeal
    window; both set `disposition` to match; and both increment the complaint's
    `version` by 1."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    reviewed = bundle["complaint"]
    assert reviewed["status"] == "REVIEWED", (
        f"setup expected REVIEWED, got {reviewed['status']}"
    )
    # The confirmed assignment's provisional claim is the courthouse's only
    # encumbrance before the trigger (PRD §2.9).
    assert fixtures.read_courthouse(bundle["courthouse"]["id"])[
        "encumbered_pay_cents"
    ] == 22050, "setup expected encumbered_pay_cents 22050 before adjudication"

    complaint = _adjudicate_with_suspension(api, program_admin_headers, reviewed["id"])

    assert complaint["status"] == "SUBSTANTIATED", (
        f"expected REVIEWED -> SUBSTANTIATED, got {complaint['status']}"
    )
    assert complaint["disposition"] == "SUBSTANTIATED", (
        f"expected disposition SUBSTANTIATED, got {complaint['disposition']}"
    )
    assert complaint["adjudicator_user_id"] == "pa-001", (
        f"expected adjudicator_user_id pa-001 from the acting X-User-ID, "
        f"got {complaint['adjudicator_user_id']}"
    )
    assert complaint["adjudicated_at"].startswith("2026-08-01T00:00:00"), (
        f"expected adjudicated_at at the logical clock 2026-08-01T00:00:00, "
        f"got {complaint['adjudicated_at']}"
    )
    assert complaint["version"] == reviewed["version"] + 1, (
        f"expected version {reviewed['version'] + 1}, got {complaint['version']}"
    )


def test_hop_one_creates_a_twelve_point_suspension_action_in_effect(
    api, program_admin_headers
):
    """PRD §3.9: "**Hop one** creates a single disciplinary action in `IN_EFFECT`
    status, recording `complaint_id` and copying `interpreter_id` from the
    complaint, with `action_type` set to the requested sanction and `points` taken
    from the sanction scale — 5 for a `LETTER`, 10 for `PROBATION`, 12 for a
    `SUSPENSION`, 20 for a `REVOCATION`."
    PRD §3.9: "Its `effective_from` is the logical-clock date, and its
    `effective_through` is 365 days after `effective_from` for a `LETTER`, 180 days
    after for `PROBATION`, the requested `suspension_days` after for a `SUSPENSION`,
    and null for a `REVOCATION`, which is permanent."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    complaint_id = bundle["complaint"]["id"]

    _adjudicate_with_suspension(api, program_admin_headers, complaint_id)

    actions = fixtures.disciplinary_actions_for_complaint(complaint_id)
    assert len(actions) == 1, (
        f"expected exactly one disciplinary action for the complaint, got {len(actions)}"
    )
    action = actions[0]
    assert action["status"] == "IN_EFFECT", (
        f"expected the action IN_EFFECT, got {action['status']}"
    )
    assert action["action_type"] == "SUSPENSION", (
        f"expected action_type SUSPENSION, got {action['action_type']}"
    )
    assert action["points"] == 12, (
        f"expected 12 points for a suspension, got {action['points']}"
    )
    assert action["complaint_id"] == complaint_id, (
        f"expected complaint_id {complaint_id}, got {action['complaint_id']}"
    )
    assert action["interpreter_id"] == bundle["interpreter"]["id"], (
        f"expected interpreter_id copied from the complaint, "
        f"got {action['interpreter_id']}"
    )
    assert action["effective_from"] == "2026-08-01", (
        f"expected effective_from 2026-08-01 (the logical-clock date), "
        f"got {action['effective_from']}"
    )
    assert action["effective_through"] == "2026-10-30", (
        f"expected effective_through 2026-10-30 (90 days after effective_from), "
        f"got {action['effective_through']}"
    )


def test_hop_two_suspends_the_roster_standing_through_the_action_window(
    api, program_admin_headers
):
    """PRD §3.9: "**Hop two** is triggered by that action becoming in-effect: the
    interpreter's `complaint_points` is recomputed to include the new points, both
    quality scores are recomputed, and the interpreter's `roster_status` moves
    `ACTIVE → SUSPENDED` for a suspension, with `suspension_through` set to the
    action's `effective_through`, or `ACTIVE → REVOKED` for a revocation."
    PRD §3.2: "The field `suspension_through` holds the date through which an
    in-effect suspension keeps `roster_status` at `SUSPENDED`, and is null whenever
    the interpreter is not suspended."
    PRD §3.2: "The separate field `complaint_points` is the plain, unweighted sum
    of `points` over the same `IN_EFFECT` and `EXPIRED` rows, with no decay and no
    floor."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    interpreter_id = bundle["interpreter"]["id"]
    assert bundle["interpreter"]["roster_status"] == "ACTIVE", (
        f"setup expected an ACTIVE interpreter, "
        f"got {bundle['interpreter']['roster_status']}"
    )

    _adjudicate_with_suspension(api, program_admin_headers, bundle["complaint"]["id"])

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["roster_status"] == "SUSPENDED", (
        f"expected ACTIVE -> SUSPENDED, got {interpreter['roster_status']}"
    )
    assert interpreter["suspension_through"] == "2026-10-30", (
        f"expected suspension_through 2026-10-30, the action's effective_through, "
        f"got {interpreter['suspension_through']}"
    )
    assert interpreter["complaint_points"] == 12, (
        f"expected complaint_points 12, got {interpreter['complaint_points']}"
    )


def test_hop_two_rescores_both_quality_figures_from_the_new_points(
    api, program_admin_headers
):
    """PRD §3.2: "Sum the points of the recent actions to obtain the
    recent-points figure and the points of the older actions to obtain the
    older-points figure."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the
    recent-points figure, floored at 0 so it never reports a negative number."
    PRD §3.2: "And `lifetime_score` is 100 less four times the recent-points
    figure less twice the older-points figure, also floored at 0."
    PRD §3.2: "A dedicated computed read exposes the two side by side for one
    interpreter, returning `interpreter_id`, `rolling_12_month_score`,
    `lifetime_score`, `complaint_points`, and the two intermediate figures
    `recent_points` and `older_points` that the formula above derived."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    interpreter_id = bundle["interpreter"]["id"]

    _adjudicate_with_suspension(api, program_admin_headers, bundle["complaint"]["id"])

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["rolling_12_month_score"] == 52, (
        f"expected rolling_12_month_score 100 - 4*12 = 52, "
        f"got {interpreter['rolling_12_month_score']}"
    )
    assert interpreter["lifetime_score"] == 52, (
        f"expected lifetime_score 100 - 4*12 - 2*0 = 52, "
        f"got {interpreter['lifetime_score']}"
    )

    score = fixtures.read_quality_score(interpreter_id)
    assert score["interpreter_id"] == interpreter_id, (
        f"expected the score read to name {interpreter_id}, "
        f"got {score['interpreter_id']}"
    )
    assert score["recent_points"] == 12, (
        f"expected recent_points 12 for an action dated today, "
        f"got {score['recent_points']}"
    )
    assert score["older_points"] == 0, (
        f"expected older_points 0, got {score['older_points']}"
    )
    assert score["rolling_12_month_score"] == 52, (
        f"expected the computed read to agree at 52, "
        f"got {score['rolling_12_month_score']}"
    )
    assert score["lifetime_score"] == 52, (
        f"expected the computed read to agree at 52, got {score['lifetime_score']}"
    )
    assert score["complaint_points"] == 12, (
        f"expected complaint_points 12, got {score['complaint_points']}"
    )


def test_hop_three_cancels_the_overlapping_assignment_and_frees_its_hearing(
    api, program_admin_headers
):
    """PRD §3.9: "**Hop three** applies to a suspension: every assignment of that
    interpreter whose `service_status` is `PROPOSED` or `CONFIRMED` and whose
    hearing's `scheduled_start` date falls on or before `suspension_through` is
    cancelled with `cancel_reason_code` set to `INTERPRETER_SUSPENDED`, processed in
    assignment `created_at` ascending order, each cancellation voiding an encumbered
    claim and returning its hearing to `SCHEDULED`."
    PRD §3.9: "A revocation is broader still: it cancels every `PROPOSED` or
    `CONFIRMED` assignment of the interpreter regardless of date with the same reason
    code, and it drives every credential of theirs in `PENDING_WRITTEN`,
    `PENDING_ORAL`, `PENDING_ETHICS`, `ACTIVE`, or `LAPSED` to `REVOKED`, processed
    in credential `created_at` ascending order."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    # The trial starts 2026-09-10, on or before the 2026-10-30 suspension_through.
    assert bundle["hearing"]["status"] == "COVERED", (
        f"setup expected a COVERED hearing, got {bundle['hearing']['status']}"
    )

    _adjudicate_with_suspension(api, program_admin_headers, bundle["complaint"]["id"])

    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["service_status"] == "CANCELLED", (
        f"expected CONFIRMED -> CANCELLED, got {assignment['service_status']}"
    )
    assert assignment["cancel_reason_code"] == "INTERPRETER_SUSPENDED", (
        f"expected cancel_reason_code INTERPRETER_SUSPENDED, "
        f"got {assignment['cancel_reason_code']}"
    )
    hearing = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing["status"] == "SCHEDULED", (
        f"expected the hearing returned COVERED -> SCHEDULED, got {hearing['status']}"
    )
    credential = fixtures.read_credential(bundle["credential"]["id"])
    assert credential["status"] == "ACTIVE", (
        f"expected the credential untouched at ACTIVE — only a revocation revokes "
        f"credentials — got {credential['status']}"
    )


def test_hop_three_voids_the_encumbered_claim_and_releases_the_ledger(
    api, program_admin_headers
):
    """PRD §3.9: "**Hop three** applies to a suspension: every assignment of that
    interpreter whose `service_status` is `PROPOSED` or `CONFIRMED` and whose
    hearing's `scheduled_start` date falls on or before `suspension_through` is
    cancelled with `cancel_reason_code` set to `INTERPRETER_SUSPENDED`, processed in
    assignment `created_at` ascending order, each cancellation voiding an encumbered
    claim and returning its hearing to `SCHEDULED`."
    PRD §3.7: "An **early** cancellation — lead time at or above that threshold —
    voids the encumbered claim: it moves `ENCUMBERED → VOIDED`,
    `provisional_total_cents` is preserved on the row for audit while
    `final_total_cents` stays null, and exactly `provisional_total_cents` is released
    from the courthouse's `encumbered_pay_cents`, restoring the ledger to its
    pre-confirmation value."
    PRD §2.9: "A claim in `VOIDED` status appears in neither sum, and a
    vendor-served assignment produces no claim at all and therefore never touches
    either sum."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less
    `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    claim_id = bundle["pay_claim"]["id"]
    assert bundle["pay_claim"]["status"] == "ENCUMBERED", (
        f"setup expected an ENCUMBERED claim, got {bundle['pay_claim']['status']}"
    )

    _adjudicate_with_suspension(api, program_admin_headers, bundle["complaint"]["id"])

    claim = fixtures.read_pay_claim(claim_id)
    assert claim["status"] == "VOIDED", (
        f"expected ENCUMBERED -> VOIDED, got {claim['status']}"
    )
    assert claim["final_total_cents"] is None, (
        f"expected final_total_cents still null on a voided claim, "
        f"got {claim['final_total_cents']}"
    )
    assert claim["provisional_total_cents"] == 22050, (
        f"expected provisional_total_cents preserved at 22050 for audit, "
        f"got {claim['provisional_total_cents']}"
    )

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected the 22050-cent encumbrance released, "
        f"got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 0, (
        f"expected no obligation from a voided claim, "
        f"got {courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 5000000, (
        f"expected the whole 5000000-cent budget available again, "
        f"got {courthouse['available_pay_cents']}"
    )


def test_hop_four_marks_the_cancelled_assignment_with_a_substantiated_defect(
    api, program_admin_headers
):
    """PRD §3.9: "**Hop four** applies when the complaint named an assignment:
    that assignment's `compliance_status` moves `UNDER_QUALITY_REVIEW →
    SUBSTANTIATED_DEFECT`, which keeps its pay claim frozen at `SUBMITTED`."
    PRD §3.9: "Every row touched by any hop has its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/substantiated_suspension_cascades_four_hops_to_hearing_and_ledger
    """
    bundle = _reviewed_suspension_case()
    before = fixtures.read_assignment(bundle["assignment"]["id"])
    assert before["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"setup expected UNDER_QUALITY_REVIEW from the complaint intake, "
        f"got {before['compliance_status']}"
    )

    _adjudicate_with_suspension(api, program_admin_headers, bundle["complaint"]["id"])

    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["compliance_status"] == "SUBSTANTIATED_DEFECT", (
        f"expected UNDER_QUALITY_REVIEW -> SUBSTANTIATED_DEFECT, "
        f"got {assignment['compliance_status']}"
    )
    assert assignment["version"] > before["version"], (
        f"expected the assignment version incremented past {before['version']}, "
        f"got {assignment['version']}"
    )


# ---------------------------------------------------------------------------
# A continuance 33 hours out (PRD §3.5, §3.7, §3.8, §2.9, §3.2)
# ---------------------------------------------------------------------------
def _late_continuance_scenario():
    """CONFIRMED assignment on a four-hour trial that starts 33 hours from now.

    The clock is at its default 2026-08-01T00:00:00Z and the hearing starts
    2026-08-02T09:00:00Z, so the lead time is inside the schedule's 48-hour
    `late_cancellation_hours`. Mileage of 12.0 sits inside the 30-mile free radius.
    """
    return fixtures.setup_confirmed_assignment(
        hearing_overrides={
            "case_number": "CR-2026-0083",
            "scheduled_start": "2026-08-02T09:00:00.000Z",
            "scheduled_end": "2026-08-02T13:00:00.000Z",
        },
        assignment_overrides={"estimated_one_way_miles": 12.0},
    )


def test_continuance_continues_the_hearing_and_cancels_its_confirmed_assignment(
    api, scheduling_coordinator_headers
):
    """PRD §3.5: "The hearing moves to `CONTINUED`, `continuance_count` is
    increased by 1, `continuance_reason_code` records the supplied code, and
    `version` is incremented by 1 — which invalidates any `expected_hearing_version`
    a client was holding."
    PRD §3.5: "As the second hop, every assignment of this hearing whose
    `service_status` is `PROPOSED` or `CONFIRMED` is cancelled with
    `cancel_reason_code` set to `COURT_CONTINUANCE`, processed in assignment
    `created_at` ascending order, and each of those cancellations then runs the
    ordinary pay consequences of §3.7: a cancelled confirmed assignment inside
    `late_cancellation_hours` of `scheduled_start` finalizes its claim on the
    late-cancellation terms instead of voiding it, moving the amount out of the
    courthouse's `encumbered_pay_cents` and into its `obligated_pay_cents` and into
    the interpreter's `pending_pay_cents`."

    Design: Difficulty/transitive_cascade/hearing_continuance_cascades_into_late_cancellation_pay_and_pending_ledger
    """
    bundle = _late_continuance_scenario()
    hearing = bundle["hearing"]
    # 40 (TRIAL) + 25 (in custody) + 0 (DESIGNATED) + 18 (one day out) = 83, class A
    # by the frozen scoring of PRD §3.5.
    assert hearing["priority_score"] == 83, (
        f"setup expected priority_score 83, got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "A", (
        f"setup expected priority_class A, got {hearing['priority_class']}"
    )
    assert hearing["status"] == "COVERED", (
        f"setup expected a COVERED hearing, got {hearing['status']}"
    )

    continued = validate_success(
        api.continue_hearing(
            hearing["id"],
            continue_hearing_payload(reason_code="COURT_CONGESTION"),
            scheduling_coordinator_headers,
        ),
        200,
    )

    assert continued["status"] == "CONTINUED", (
        f"expected COVERED -> CONTINUED, got {continued['status']}"
    )
    assert continued["continuance_count"] == 1, (
        f"expected continuance_count 1, got {continued['continuance_count']}"
    )
    assert continued["continuance_reason_code"] == "COURT_CONGESTION", (
        f"expected continuance_reason_code COURT_CONGESTION, "
        f"got {continued['continuance_reason_code']}"
    )
    assert continued["version"] == hearing["version"] + 1, (
        f"expected version {hearing['version'] + 1}, got {continued['version']}"
    )

    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["service_status"] == "CANCELLED", (
        f"expected the confirmed assignment CANCELLED by the second hop, "
        f"got {assignment['service_status']}"
    )
    assert assignment["cancel_reason_code"] == "COURT_CONTINUANCE", (
        f"expected cancel_reason_code COURT_CONTINUANCE, "
        f"got {assignment['cancel_reason_code']}"
    )


def test_continuance_finalizes_the_claim_on_the_late_cancellation_terms(
    api, scheduling_coordinator_headers
):
    """PRD §3.7: "A **late** cancellation — lead time strictly below the threshold
    — compensates the interpreter instead: the claim moves `ENCUMBERED → FINALIZED`
    with `variant` set to `FINAL`, `late_cancellation` set to true, and
    `final_total_cents` computed by the late-cancellation arithmetic of §3.8, after
    which the interpreter's `pending_pay_cents` is recomputed from the newly
    finalized claim."
    PRD §3.8: "`LATE_CANCELLATION` is computed when a confirmed assignment is
    cancelled inside the schedule's `late_cancellation_hours`; it pays
    `late_cancellation_pay_hours` at the snapshot tier's rate with the delivery
    multiplier applied, adds any rare-language premium on that service component,
    contributes no travel at all, and sets `late_cancellation` to true."
    PRD §3.8: "For the `LATE_CANCELLATION` variant, `billable_hours` is set
    directly to the schedule's `late_cancellation_pay_hours` and neither the
    quarter-hour round-up nor the minimum-call floor is applied."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to
    `provisional_total_cents`; the `FINAL` and `LATE_CANCELLATION` variants write it
    to `final_total_cents` and leave `provisional_total_cents` frozen at whatever the
    provisional run produced."

    Design: Difficulty/transitive_cascade/hearing_continuance_cascades_into_late_cancellation_pay_and_pending_ledger
    """
    bundle = _late_continuance_scenario()
    claim_id = bundle["pay_claim"]["id"]
    assert bundle["pay_claim"]["status"] == "ENCUMBERED", (
        f"setup expected an ENCUMBERED claim, got {bundle['pay_claim']['status']}"
    )
    assert bundle["pay_claim"]["provisional_total_cents"] == 35000, (
        f"setup expected provisional_total_cents 35000 for the four-hour window, "
        f"got {bundle['pay_claim']['provisional_total_cents']}"
    )

    validate_success(
        api.continue_hearing(
            bundle["hearing"]["id"],
            continue_hearing_payload(reason_code="COURT_CONGESTION"),
            scheduling_coordinator_headers,
        ),
        200,
    )

    claim = fixtures.read_pay_claim(claim_id)
    assert claim["status"] == "FINALIZED", (
        f"expected ENCUMBERED -> FINALIZED rather than VOIDED, got {claim['status']}"
    )
    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL, got {claim['variant']}"
    )
    assert claim["late_cancellation"] is True, (
        f"expected late_cancellation true, got {claim['late_cancellation']}"
    )
    assert claim["billable_hours"] == 2.0, (
        f"expected billable_hours 2.0 straight from late_cancellation_pay_hours, "
        f"got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == 17500, (
        f"expected service_cents 2.0 * 8750 = 17500, got {claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected no rare premium on a DESIGNATED language, "
        f"got {claim['rare_premium_cents']}"
    )
    assert claim["travel_cents"] == 0, (
        f"expected travel_cents 0 — a late cancellation contributes no travel, "
        f"got {claim['travel_cents']}"
    )
    assert claim["final_total_cents"] == 17500, (
        f"expected final_total_cents 17500, got {claim['final_total_cents']}"
    )
    assert claim["provisional_total_cents"] == 35000, (
        f"expected provisional_total_cents frozen at 35000, "
        f"got {claim['provisional_total_cents']}"
    )


def test_continuance_swaps_the_courthouse_encumbrance_for_an_obligation(
    api, scheduling_coordinator_headers
):
    """PRD §3.5: "As the second hop, every assignment of this hearing whose
    `service_status` is `PROPOSED` or `CONFIRMED` is cancelled with
    `cancel_reason_code` set to `COURT_CONTINUANCE`, processed in assignment
    `created_at` ascending order, and each of those cancellations then runs the
    ordinary pay consequences of §3.7: a cancelled confirmed assignment inside
    `late_cancellation_hours` of `scheduled_start` finalizes its claim on the
    late-cancellation terms instead of voiding it, moving the amount out of the
    courthouse's `encumbered_pay_cents` and into its `obligated_pay_cents` and into
    the interpreter's `pending_pay_cents`."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every
    pay claim whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or
    `PAID`, reached through the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less
    `encumbered_pay_cents` less `obligated_pay_cents`."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this
    interpreter's pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`,
    and `paid_pay_cents` is the same sum restricted to claims in `PAID`."

    Design: Difficulty/transitive_cascade/hearing_continuance_cascades_into_late_cancellation_pay_and_pending_ledger
    """
    bundle = _late_continuance_scenario()
    courthouse_id = bundle["courthouse"]["id"]
    interpreter_id = bundle["interpreter"]["id"]
    before = fixtures.read_courthouse(courthouse_id)
    assert before["encumbered_pay_cents"] == 35000, (
        f"setup expected a 35000-cent encumbrance, "
        f"got {before['encumbered_pay_cents']}"
    )

    validate_success(
        api.continue_hearing(
            bundle["hearing"]["id"],
            continue_hearing_payload(reason_code="COURT_CONGESTION"),
            scheduling_coordinator_headers,
        ),
        200,
    )

    courthouse = fixtures.read_courthouse(courthouse_id)
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected the encumbrance released to 0, "
        f"got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 17500, (
        f"expected obligated_pay_cents 17500 from the finalized claim, "
        f"got {courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4982500, (
        f"expected available_pay_cents 5000000 - 0 - 17500 = 4982500, "
        f"got {courthouse['available_pay_cents']}"
    )

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["pending_pay_cents"] == 17500, (
        f"expected pending_pay_cents 17500, got {interpreter['pending_pay_cents']}"
    )
    assert interpreter["paid_pay_cents"] == 0, (
        f"expected paid_pay_cents still 0, got {interpreter['paid_pay_cents']}"
    )
