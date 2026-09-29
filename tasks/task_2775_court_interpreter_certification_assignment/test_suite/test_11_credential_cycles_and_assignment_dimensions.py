"""Credential cycles that re-enter states they already left, and the two
independent status dimensions an assignment carries.

Two concerns live here:

* A credential walks ACTIVE -> LAPSED -> ACTIVE and then loops ACTIVE -> ACTIVE
  through an early renewal, dragging the holder's roster standing around the
  matching ACTIVE -> INACTIVE -> ACTIVE loop (PRD §3.3, §3.4, §3.10).
* One assignment row advances its service dimension CONFIRMED -> CHECKED_IN ->
  COMPLETED while its compliance dimension independently advances
  CLEAR -> UNDER_QUALITY_REVIEW -> SUBSTANTIATED_DEFECT (PRD §3.7, §3.9).
"""

from test_helpers import (
    adjudicate_complaint_payload,
    complete_assignment_payload,
    create_complaint_payload,
    make_interpreter_headers,
    renew_credential_payload,
    validate_success,
)
import test_helpers.fixtures as fixtures


def test_first_activation_sets_the_two_year_cycle_and_its_grace_window(api):
    """PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier`
    is set to `target_tier`; `issued_on` records the logical-clock date of this
    first activation; `expires_on` is set 730 days — two full years — after that
    date for a `MASTER`, `CERTIFIED`, or `REGISTERED` credential, and 365 days
    after it for a `PROVISIONAL` one, whose shorter cycle reflects that it rests
    on no examination; and `grace_through` is set 90 days after `expires_on`."
    PRD §3.3: "The activation then cascades: the language's
    `active_credentialed_count` is recomputed, the holder's `credential_tier` and
    `credentialed_language_ids` are recomputed, and the holder's `roster_status`
    bubbles up from `CANDIDATE` to `ACTIVE` if this is their first active
    credential or from `INACTIVE` to `ACTIVE` if they had fallen off the roster."

    Design: Difficulty/non_linear_state_machine/credential_active_lapsed_active_cycle_then_early_renewal_self_loop
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"], target_tier="CERTIFIED")
    credential = bundle["credential"]

    assert credential["status"] == "ACTIVE", (
        f"expected ACTIVE, got {credential['status']} after the ethics advancement"
    )
    assert credential["tier"] == "CERTIFIED", (
        f"expected tier CERTIFIED, got {credential['tier']} on activation"
    )
    assert credential["issued_on"] == "2026-08-01", (
        f"expected issued_on 2026-08-01, got {credential['issued_on']}"
    )
    assert credential["expires_on"] == "2028-07-31", (
        f"expected expires_on 2028-07-31 (730 days after issue), "
        f"got {credential['expires_on']}"
    )
    assert credential["grace_through"] == "2028-10-29", (
        f"expected grace_through 2028-10-29 (90 days after expiry), "
        f"got {credential['grace_through']}"
    )
    assert credential["renewal_count"] == 0, (
        f"expected renewal_count 0, got {credential['renewal_count']}"
    )

    interpreter = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter["roster_status"] == "ACTIVE", (
        f"expected roster_status ACTIVE, got {interpreter['roster_status']}"
    )
    assert interpreter["credential_tier"] == "CERTIFIED", (
        f"expected credential_tier CERTIFIED, got {interpreter['credential_tier']}"
    )
    assert interpreter["credentialed_language_ids"] == [language["id"]], (
        f"expected the activated language only, "
        f"got {interpreter['credentialed_language_ids']}"
    )
    assert fixtures.read_language(language["id"])["active_credentialed_count"] == 1, (
        "expected active_credentialed_count 1 after the first activation"
    )


def test_expiry_sweep_lapses_the_credential_and_drops_the_holder_to_inactive(
    api, program_admin_headers
):
    """PRD §3.10: "Every credential in `ACTIVE` status whose `expires_on` date
    lies strictly before the current logical-clock date moves `ACTIVE → LAPSED`
    with its `tier` cleared, the owning language's `active_credentialed_count` is
    decremented, the holder's `credential_tier` and `credentialed_language_ids`
    are recomputed, and a holder left with no active credential at all drops
    `ACTIVE → INACTIVE`, which cancels each of their `PROPOSED` and `CONFIRMED`
    assignments with `cancel_reason_code` set to `CREDENTIAL_LAPSED`, voiding
    those assignments' encumbered claims and returning their hearings to
    `SCHEDULED`."
    PRD §3.2: "`ACTIVE → INACTIVE` happens the moment the interpreter's last
    activated credential stops being activated, which requires that the count of
    their credentials in `ACTIVE` status has fallen to zero; that transition also
    sets `credential_tier` to `NONE` and empties `credentialed_language_ids` to an
    empty list."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run
    executed, together with six identifier arrays: `lapsed_credential_ids`,
    `downgraded_interpreter_ids`, `expired_action_ids`,
    `reinstated_interpreter_ids`, `unmet_hearing_ids`, `cancelled_assignment_ids`,
    and `voided_pay_claim_ids`."

    Design: Difficulty/non_linear_state_machine/credential_active_lapsed_active_cycle_then_early_renewal_self_loop
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"], target_tier="CERTIFIED")
    credential_id = bundle["credential"]["id"]
    interpreter_id = bundle["interpreter"]["id"]

    # One day past expires_on 2028-07-31, still inside the 90-day grace window.
    fixtures.set_clock("2028-08-01T00:00:00Z")
    sweep = validate_success(api.run_daily_sweep(program_admin_headers), 200)

    assert credential_id in sweep["lapsed_credential_ids"], (
        f"expected {credential_id} in lapsed_credential_ids, "
        f"got {sweep['lapsed_credential_ids']}"
    )
    assert interpreter_id in sweep["downgraded_interpreter_ids"], (
        f"expected {interpreter_id} in downgraded_interpreter_ids, "
        f"got {sweep['downgraded_interpreter_ids']}"
    )

    lapsed = fixtures.read_credential(credential_id)
    assert lapsed["status"] == "LAPSED", (
        f"expected LAPSED, got {lapsed['status']} after the expiry sweep"
    )
    assert lapsed["tier"] is None, (
        f"expected tier cleared to null, got {lapsed['tier']} after the lapse"
    )

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["roster_status"] == "INACTIVE", (
        f"expected roster_status INACTIVE, got {interpreter['roster_status']}"
    )
    assert interpreter["credential_tier"] == "NONE", (
        f"expected credential_tier NONE, got {interpreter['credential_tier']}"
    )
    assert interpreter["credentialed_language_ids"] == [], (
        f"expected an empty credentialed_language_ids, "
        f"got {interpreter['credentialed_language_ids']}"
    )
    assert fixtures.read_language(language["id"])["active_credentialed_count"] == 0, (
        "expected active_credentialed_count decremented to 0 by the lapse"
    )


def test_grace_renewal_reinstates_the_lapsed_credential_rebasing_the_cycle_on_the_clock(
    api, credentialing_officer_headers
):
    """PRD §3.4: "A successful renewal sets `expires_on` to 730 days after the
    later of the credential's current `expires_on` and the current logical-clock
    date — 365 days for a `PROVISIONAL` credential — recomputes `grace_through` as
    90 days after the new `expires_on`, overwrites `cycle_credit_hours` with the
    submitted figure, adds 1 to `renewal_count`, and increments the credential's
    `version` by 1."
    PRD §3.4: "Renewing a credential that has already gone `LAPSED` is the
    reinstatement leg, `LAPSED → ACTIVE`: the clock is by then past `expires_on`,
    so the new cycle is measured from the clock date, and the days spent lapsed are
    lost rather than credited."
    PRD §3.4: "Reinstatement also restores service — `status` returns to `ACTIVE`
    and `tier` returns to `target_tier`, the language's `active_credentialed_count`
    is recomputed, and the holder's `roster_status` bubbles `INACTIVE → ACTIVE`
    provided no suspension is in effect against them."

    Design: Difficulty/non_linear_state_machine/credential_active_lapsed_active_cycle_then_early_renewal_self_loop
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    language = fixtures.bootstrap_language()
    lapsed = fixtures.setup_lapsed_credential(language["id"], "2028-08-01T00:00:00Z")
    assert lapsed["credential"]["status"] == "LAPSED", (
        f"setup expected LAPSED, got {lapsed['credential']['status']}"
    )

    renewed = validate_success(
        api.renew_credential(
            lapsed["credential"]["id"],
            renew_credential_payload(16),
            credentialing_officer_headers,
        ),
        200,
    )

    assert renewed["status"] == "ACTIVE", (
        f"expected LAPSED -> ACTIVE, got {renewed['status']} after the grace renewal"
    )
    assert renewed["tier"] == "CERTIFIED", (
        f"expected tier restored to CERTIFIED, got {renewed['tier']}"
    )
    assert renewed["expires_on"] == "2030-08-01", (
        f"expected the cycle rebased on the clock date to 2030-08-01, "
        f"got {renewed['expires_on']}"
    )
    assert renewed["grace_through"] == "2030-10-30", (
        f"expected grace_through 2030-10-30 (90 days after the new expiry), "
        f"got {renewed['grace_through']}"
    )
    assert renewed["renewal_count"] == 1, (
        f"expected renewal_count 1, got {renewed['renewal_count']}"
    )
    assert renewed["cycle_credit_hours"] == 16, (
        f"expected cycle_credit_hours overwritten with 16, "
        f"got {renewed['cycle_credit_hours']}"
    )

    interpreter = fixtures.read_interpreter(lapsed["interpreter"]["id"])
    assert interpreter["roster_status"] == "ACTIVE", (
        f"expected roster_status back to ACTIVE, got {interpreter['roster_status']}"
    )
    assert interpreter["credential_tier"] == "CERTIFIED", (
        f"expected credential_tier CERTIFIED, got {interpreter['credential_tier']}"
    )
    assert fixtures.read_language(language["id"])["active_credentialed_count"] == 1, (
        "expected active_credentialed_count recomputed back to 1 by the reinstatement"
    )


def test_early_renewal_self_loop_rebases_the_cycle_on_the_existing_expires_on(
    api, credentialing_officer_headers
):
    """PRD §3.4: "Renewing a credential that is still `ACTIVE` is a self-loop,
    `ACTIVE → ACTIVE`: because the clock has not yet passed `expires_on`, the
    extension is measured from the existing `expires_on`, so an early renewer
    neither gains nor loses days and their cycle boundary simply slides forward by
    one full cycle."
    PRD §3.4: "A successful renewal sets `expires_on` to 730 days after the later
    of the credential's current `expires_on` and the current logical-clock date —
    365 days for a `PROVISIONAL` credential — recomputes `grace_through` as 90 days
    after the new `expires_on`, overwrites `cycle_credit_hours` with the submitted
    figure, adds 1 to `renewal_count`, and increments the credential's `version` by
    1."

    Design: Difficulty/non_linear_state_machine/credential_active_lapsed_active_cycle_then_early_renewal_self_loop
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    language = fixtures.bootstrap_language()
    lapsed = fixtures.setup_lapsed_credential(language["id"], "2028-08-01T00:00:00Z")
    credential_id = lapsed["credential"]["id"]
    reinstated = fixtures.renew_credential(credential_id, 16)
    assert reinstated["expires_on"] == "2030-08-01", (
        f"setup expected expires_on 2030-08-01, got {reinstated['expires_on']}"
    )

    # The clock is still 2028-08-01, well inside the new cycle: an early renewal.
    looped = validate_success(
        api.renew_credential(
            credential_id, renew_credential_payload(20), credentialing_officer_headers
        ),
        200,
    )

    assert looped["status"] == "ACTIVE", (
        f"expected the ACTIVE -> ACTIVE self-loop, got {looped['status']}"
    )
    assert looped["expires_on"] == "2032-07-31", (
        f"expected the cycle rebased on the existing expires_on to 2032-07-31, "
        f"got {looped['expires_on']}"
    )
    assert looped["grace_through"] == "2032-10-29", (
        f"expected grace_through 2032-10-29, got {looped['grace_through']}"
    )
    assert looped["renewal_count"] == 2, (
        f"expected renewal_count 2 after the second renewal, "
        f"got {looped['renewal_count']}"
    )
    assert looped["cycle_credit_hours"] == 20, (
        f"expected cycle_credit_hours overwritten with 20, "
        f"got {looped['cycle_credit_hours']}"
    )
    assert looped["tier"] == "CERTIFIED", (
        f"expected tier to stay CERTIFIED through the self-loop, got {looped['tier']}"
    )


# ---------------------------------------------------------------------------
# The two independent status dimensions of one assignment (PRD §3.7, §3.9)
# ---------------------------------------------------------------------------
COMPLAINT_NARRATIVE = "Party reports one omitted qualifier during the plea colloquy."


def _confirmed_assignment_with_open_complaint():
    """CONFIRMED assignment on the 2026-09-10 trial, plus a complaint naming it.

    The complaint drives the compliance dimension to UNDER_QUALITY_REVIEW while
    the service dimension is still sitting at CONFIRMED.
    """
    bundle = fixtures.setup_confirmed_assignment(
        assignment_overrides={"estimated_one_way_miles": 33.7}
    )
    bundle["complaint"] = fixtures.file_complaint(
        bundle["interpreter"]["id"],
        bundle["assignment"]["id"],
        filer_user_id="qr-001",
        category="ACCURACY",
        severity="MINOR",
        narrative=COMPLAINT_NARRATIVE,
    )
    return bundle


def test_filing_a_complaint_moves_only_the_compliance_dimension(
    api, quality_reviewer_headers
):
    """PRD §3.9: "When an `assignment_id` is present, however, the named
    assignment's `compliance_status` moves `CLEAR → UNDER_QUALITY_REVIEW`, which
    immediately freezes fiscal approval of that assignment's pay claim."
    PRD §3.9: "Intake changes neither the interpreter's roster standing nor their
    `complaint_points` — nothing is proven yet."
    PRD §3.7: "Complaint events move the compliance dimension regardless of where
    the service dimension sits, and service events move the service dimension
    regardless of where the compliance dimension sits."

    Design: Difficulty/non_linear_state_machine/assignment_service_and_compliance_dimensions_advance_independently
    """
    bundle = fixtures.setup_confirmed_assignment(
        assignment_overrides={"estimated_one_way_miles": 33.7}
    )
    assignment = bundle["assignment"]
    assert assignment["service_status"] == "CONFIRMED", (
        f"setup expected CONFIRMED, got {assignment['service_status']}"
    )
    assert assignment["compliance_status"] == "CLEAR", (
        f"setup expected CLEAR, got {assignment['compliance_status']}"
    )

    payload = create_complaint_payload(
        bundle["interpreter"]["id"],
        category="ACCURACY",
        severity="MINOR",
        narrative=COMPLAINT_NARRATIVE,
    )
    payload["assignment_id"] = assignment["id"]
    complaint = validate_success(
        api.create_complaint(payload, quality_reviewer_headers), 201
    )

    assert complaint["status"] == "FILED", (
        f"expected the complaint FILED, got {complaint['status']}"
    )
    after = fixtures.read_assignment(assignment["id"])
    assert after["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected compliance_status UNDER_QUALITY_REVIEW, "
        f"got {after['compliance_status']} after intake"
    )
    assert after["service_status"] == "CONFIRMED", (
        f"expected service_status untouched at CONFIRMED, "
        f"got {after['service_status']} after intake"
    )
    interpreter = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter["complaint_points"] == 0, (
        f"expected complaint_points still 0 at intake, "
        f"got {interpreter['complaint_points']}"
    )
    assert interpreter["roster_status"] == "ACTIVE", (
        f"expected roster_status still ACTIVE at intake, "
        f"got {interpreter['roster_status']}"
    )


def test_service_dimension_reaches_completed_while_still_under_quality_review(api):
    """PRD §3.7: "An assignment can perfectly well be `COMPLETED` and
    `UNDER_QUALITY_REVIEW` at the same time; indeed that combination is the normal
    one after a served hearing draws an accuracy complaint."
    PRD §3.7: "Checking in is the interpreter's own act and nobody else's,
    `CONFIRMED → CHECKED_IN`."
    PRD §3.7: "For a rostered interpreter the path is `CHECKED_IN → COMPLETED` and
    `actual_end_utc` must be strictly after `check_in_utc`; for a vendor-served
    assignment the path is `CONFIRMED → COMPLETED` — there is no check-in for a
    vendor — and `actual_end_utc` must be strictly after the hearing's
    `scheduled_start`."
    PRD §3.7: "Completion moves the hearing `COVERED → SERVED` and increments the
    hearing's `version` by 1."

    Design: Difficulty/non_linear_state_machine/assignment_service_and_compliance_dimensions_advance_independently
    """
    bundle = _confirmed_assignment_with_open_complaint()
    assignment_id = bundle["assignment"]["id"]
    interpreter_id = bundle["interpreter"]["id"]
    owner_headers = make_interpreter_headers(interpreter_id)

    fixtures.set_clock("2026-09-10T09:00:00Z")
    checked_in = validate_success(
        api.check_in_assignment(assignment_id, owner_headers), 200
    )
    assert checked_in["service_status"] == "CHECKED_IN", (
        f"expected CHECKED_IN, got {checked_in['service_status']}"
    )
    assert checked_in["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected the compliance dimension to stay UNDER_QUALITY_REVIEW, "
        f"got {checked_in['compliance_status']} after check-in"
    )

    completed = validate_success(
        api.complete_assignment(
            assignment_id,
            complete_assignment_payload("2026-09-10T12:10:00.000Z", 33.7),
            owner_headers,
        ),
        200,
    )
    assert completed["service_status"] == "COMPLETED", (
        f"expected COMPLETED, got {completed['service_status']}"
    )
    assert completed["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected the compliance dimension to stay UNDER_QUALITY_REVIEW, "
        f"got {completed['compliance_status']} after completion"
    )
    hearing = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing["status"] == "SERVED", (
        f"expected the hearing COVERED -> SERVED, got {hearing['status']}"
    )


def test_completion_finalizes_the_pay_claim_while_the_quality_review_stays_open(api):
    """PRD §3.7: "For a rostered interpreter, completion also settles the money:
    the pay claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL` and
    `final_total_cents` computed by the final arithmetic of §3.8, the courthouse's
    `encumbered_pay_cents`, `obligated_pay_cents` and `available_pay_cents` are all
    recomputed, and the interpreter's `pending_pay_cents` is recomputed to include
    the newly finalized amount."
    PRD §3.8: "The `FINAL` variant measures the *served* window, from the
    assignment's `check_in_utc` up to but not including its `actual_end_utc`, and
    takes its mileage from `actual_one_way_miles`."
    PRD §3.8: "Multiply that figure by four, round the product *up* to the next
    whole number, and divide by four again — the effect is that any part-used
    quarter hour is billed as a whole quarter hour."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to
    `provisional_total_cents`; the `FINAL` and `LATE_CANCELLATION` variants write it
    to `final_total_cents` and leave `provisional_total_cents` frozen at whatever
    the provisional run produced."

    Design: Difficulty/non_linear_state_machine/assignment_service_and_compliance_dimensions_advance_independently
    """
    bundle = _confirmed_assignment_with_open_complaint()
    assignment_id = bundle["assignment"]["id"]
    owner_headers = make_interpreter_headers(bundle["interpreter"]["id"])
    encumbered = fixtures.read_pay_claim(bundle["pay_claim"]["id"])
    assert encumbered["status"] == "ENCUMBERED", (
        f"setup expected an ENCUMBERED claim, got {encumbered['status']}"
    )
    assert encumbered["provisional_total_cents"] == 22050, (
        f"setup expected provisional_total_cents 22050, "
        f"got {encumbered['provisional_total_cents']}"
    )

    fixtures.set_clock("2026-09-10T09:00:00Z")
    fixtures.check_in_assignment(assignment_id, bundle["interpreter"]["id"])
    validate_success(
        api.complete_assignment(
            assignment_id,
            complete_assignment_payload("2026-09-10T12:10:00.000Z", 33.7),
            owner_headers,
        ),
        200,
    )

    claim = fixtures.read_pay_claim(bundle["pay_claim"]["id"])
    assert claim["status"] == "FINALIZED", (
        f"expected ENCUMBERED -> FINALIZED even with the quality review open, "
        f"got {claim['status']}"
    )
    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL, got {claim['variant']}"
    )
    assert claim["billable_hours"] == 3.25, (
        f"expected 3h10m served billed as 3.25 hours, got {claim['billable_hours']}"
    )
    assert claim["final_total_cents"] == 32988, (
        f"expected final_total_cents 32988, got {claim['final_total_cents']}"
    )
    assert claim["provisional_total_cents"] == 22050, (
        f"expected provisional_total_cents frozen at 22050, "
        f"got {claim['provisional_total_cents']}"
    )
    assert (
        fixtures.read_assignment(assignment_id)["compliance_status"]
        == "UNDER_QUALITY_REVIEW"
    ), "expected the compliance dimension untouched by the money settlement"


def test_substantiation_marks_the_completed_assignment_with_a_substantiated_defect(
    api, program_admin_headers
):
    """PRD §3.9: "A substantiation is the loud branch, `REVIEWED →
    SUBSTANTIATED`, and it cascades in four hops."
    PRD §3.9: "**Hop one** creates a single disciplinary action in `IN_EFFECT`
    status, recording `complaint_id` and copying `interpreter_id` from the
    complaint, with `action_type` set to the requested sanction and `points` taken
    from the sanction scale — 5 for a `LETTER`, 10 for `PROBATION`, 12 for a
    `SUSPENSION`, 20 for a `REVOCATION`."
    PRD §3.9: "**Hop two** is triggered by that action becoming in-effect: the
    interpreter's `complaint_points` is recomputed to include the new points, both
    quality scores are recomputed, and the interpreter's `roster_status` moves
    `ACTIVE → SUSPENDED` for a suspension, with `suspension_through` set to the
    action's `effective_through`, or `ACTIVE → REVOKED` for a revocation."
    PRD §3.9: "**Hop four** applies when the complaint named an assignment: that
    assignment's `compliance_status` moves `UNDER_QUALITY_REVIEW →
    SUBSTANTIATED_DEFECT`, which keeps its pay claim frozen at `SUBMITTED`."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the
    recent-points figure, floored at 0 so it never reports a negative number."

    Design: Difficulty/non_linear_state_machine/assignment_service_and_compliance_dimensions_advance_independently
    """
    bundle = _confirmed_assignment_with_open_complaint()
    assignment_id = bundle["assignment"]["id"]
    interpreter_id = bundle["interpreter"]["id"]

    fixtures.set_clock("2026-09-10T09:00:00Z")
    fixtures.check_in_assignment(assignment_id, interpreter_id)
    fixtures.complete_assignment(
        assignment_id, interpreter_id, "2026-09-10T12:10:00.000Z", 33.7
    )
    fixtures.review_complaint(
        bundle["complaint"]["id"],
        recommendation="SUBSTANTIATE",
        findings="Recording confirms the omitted qualifier.",
        reviewer_user_id="qr-002",
    )

    complaint = validate_success(
        api.adjudicate_complaint(
            bundle["complaint"]["id"],
            adjudicate_complaint_payload("SUBSTANTIATED", sanction_type="LETTER"),
            program_admin_headers,
        ),
        200,
    )
    assert complaint["disposition"] == "SUBSTANTIATED", (
        f"expected disposition SUBSTANTIATED, got {complaint['disposition']}"
    )
    assert complaint["status"] == "SUBSTANTIATED", (
        f"expected REVIEWED -> SUBSTANTIATED, got {complaint['status']}"
    )

    assignment = fixtures.read_assignment(assignment_id)
    assert assignment["compliance_status"] == "SUBSTANTIATED_DEFECT", (
        f"expected compliance_status SUBSTANTIATED_DEFECT, "
        f"got {assignment['compliance_status']}"
    )
    assert assignment["service_status"] == "COMPLETED", (
        f"expected the service dimension still COMPLETED, "
        f"got {assignment['service_status']}"
    )

    interpreter = fixtures.read_interpreter(interpreter_id)
    assert interpreter["complaint_points"] == 5, (
        f"expected complaint_points 5 from the letter of instruction, "
        f"got {interpreter['complaint_points']}"
    )
    assert interpreter["rolling_12_month_score"] == 80, (
        f"expected rolling_12_month_score 100 - 4*5 = 80, "
        f"got {interpreter['rolling_12_month_score']}"
    )
    assert interpreter["roster_status"] == "ACTIVE", (
        f"expected roster_status untouched at ACTIVE by a letter sanction, "
        f"got {interpreter['roster_status']}"
    )
