"""State-machine corners: the two initial dimensions written by one create call,
terminal lockdown against four repeat triggers, the bounded intake amendment
loop, the therapist cycle whose only terminal state is INACTIVE, single-shot
retail resolution, the refused second final settlement, and the clearance reason
rewritten under a fixed precedence.
"""

from test_helpers import (
    COORDINATOR_USER_ID,
    ApiErrorId,
    assert_list_count,
    assert_same_instant,
    assert_state_pair,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import (
    CANON_CONSENT_VERSION,
    CANON_QUOTED_PRICE_CENTS,
    CANON_START_AT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

PROVISIONAL_FOLIO_TOTAL_CENTS = 50504
FINAL_REALIZED_CENTS = 45300
FINAL_FOLIO_TOTAL_CENTS = 58454
SETTLEMENT_ADJUSTMENT_CENTS = FINAL_FOLIO_TOTAL_CENTS - PROVISIONAL_FOLIO_TOTAL_CENTS


def test_one_booking_call_writes_both_initial_dimensions_and_every_derivation():
    """REQUESTED x PENDING, five derived fields and both ledgers, in one call.

    PRD §3.5: "A successful booking lands with `schedule_status` `REQUESTED` and
    `clearance_status` `PENDING` with `clearance_block_reason` null: the
    appointment exists but is neither confirmed nor clinically cleared."

    PRD §3.5: "`assignment_mode` is `EXPLICIT` when `therapist_id` was supplied
    and `AUTO` when the server chose the therapist; either way `therapist_id` is
    never null on a successfully created appointment."

    PRD §3.5: "`high_demand_slot` is true when either the treatment type's
    `high_demand` flag is true or the UTC hour of `start_at` is at least 16 and
    less than 20 — the four-hour late-afternoon peak — and false otherwise."

    PRD §3.5: "Booking an appointment finally adds `scheduled_duration_minutes`
    plus the room's `turnover_buffer_minutes` to that room's
    `booked_minutes_total` and adds `scheduled_duration_minutes` to the
    therapist's `assigned_minutes_total`, each increment bumping that row's own
    `version` by 1."

    Design: Corner/state_machines/appointment_initial_states_on_both_dimensions
    """
    world = fx.build_world()
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0

    appointment = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT, world.therapist_id),
        fx.COORDINATOR), 201)

    assert_state_pair(appointment, "REQUESTED", "PENDING", None)
    assert appointment["realized_price_cents"] is None
    assert appointment["actual_duration_minutes"] is None
    assert appointment["gratuity_cents"] == 0
    assert appointment["cancellation_charge_cents"] == 0
    assert appointment["version"] == 1

    assert appointment["scheduled_duration_minutes"] == 90, (
        "the duration is a snapshot of the treatment type, not a client input")
    assert_same_instant(appointment["end_at"], "2026-08-10T18:30:00.000Z", "end_at")
    assert appointment["assignment_mode"] == "EXPLICIT", (
        "therapist_id was supplied, so the mode is EXPLICIT rather than AUTO")
    assert appointment["therapist_id"] == world.therapist_id
    assert appointment["high_demand_slot"] is True, (
        "both clauses hold: the treatment is high_demand and 17:00Z is inside "
        "the 16 <= hour < 20 peak")
    assert appointment["quoted_price_cents"] == CANON_QUOTED_PRICE_CENTS

    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "90 scheduled plus the room's 30 turnover minutes, committed at creation "
        "and not deferred to confirmation")
    assert world.fetch_therapist()["assigned_minutes_total"] == 90


def test_cancelled_is_terminal_and_no_trigger_departs_from_it():
    """Confirm is not idempotent, and three triggers bounce off CANCELLED.

    PRD §2.7 rung 9: "**State legality** — the target resource currently sits in a
    state from which the requested transition departs. This rung also rejects
    repeating a trigger that has already been applied and acting on a resource in
    a terminal state."

    PRD §3.8: "When that figure is 24 hours or more — the boundary is inclusive —
    the appointment moves `REQUESTED → CANCELLED` or `CONFIRMED → CANCELLED`,
    `cancellation_charge_cents` is 0 and **no folio posting is made at all**."

    Design: Corner/state_machines/appointment_terminal_lockdown_and_repeat_trigger_rejection
    """
    world = fx.world_with_confirmed_appointment()
    appointment_id = world.appointments["a"]["id"]

    validate_error(api_client.confirm_appointment(appointment_id, {}, fx.COORDINATOR),
                   ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)

    cancelled = validate_success(api_client.cancel_appointment(
        appointment_id, f.cancel_payload("guest request"), fx.COORDINATOR))
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancellation_charge_cents"] == 0

    for label, response in (
        ("cancel again",
         api_client.cancel_appointment(appointment_id, f.cancel_payload("again"),
                                      fx.COORDINATOR)),
        ("check-in",
         api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR)),
        ("no-show",
         api_client.no_show_appointment(appointment_id, {}, fx.COORDINATOR)),
    ):
        error = validate_error(
            response, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)
        assert error["error_id"] == ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, (
            f"{label} must be refused as a departure from a terminal state")

    assert world.fetch_room()["booked_minutes_total"] == 0, (
        "the minutes were released exactly once, never once per failed attempt")
    assert world.fetch_therapist()["assigned_minutes_total"] == 0
    assert world.fetch_guest()["folio_balance_cents"] == 0
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings")


# ---------------------------------------------------------------------------
# The bounded intake amendment loop
# ---------------------------------------------------------------------------

def _flagged_draft_form():
    """A GOLD guest whose DRAFT form declares one registry condition."""
    guest = fx.create_guest(loyalty_tier="GOLD")
    guest_headers = fx.make_guest_headers(guest["id"])
    form = validate_success(api_client.create_intake_form(
        guest["id"],
        f.intake_form_payload(guest["version"],
                              condition_codes=["ACTIVE_INFECTION"],
                              medications=[]),
        guest_headers), 201)
    return guest, guest_headers, form


def _submit_and_screen(form_id, guest_headers, screen_user=fx.CO_SCREEN):
    validate_success(api_client.submit_intake_form(form_id, {}, guest_headers))
    return validate_success(api_client.screen_intake_form(
        form_id, {}, fx.make_compliance_headers(screen_user)))


def test_amend_departs_only_from_screened_flagged_and_resets_the_screening():
    """A DRAFT form cannot be amended, and the first legal amend clears the verdict.

    PRD §3.4: "Acting on a form from a state that has no such transition —
    submitting a form that is not `DRAFT`, or touching a form that has already
    reached `SUPERSEDED` — is refused with `ERR_INVALID_INTAKE_STATE`."

    PRD §3.4: "The second exit is the guest amendment loop, available to a `Guest`
    or a `SpaCoordinator`, which returns the form `SCREENED_FLAGGED → DRAFT` with
    corrected answers: `condition_codes` and `medications` are replaced by the
    submitted values, `flagged_condition_codes` is reset to an empty array, and
    `screened_by_user_id` and `screened_at` are reset to null."

    PRD §3.4: "Because an amended form is no longer screened, the guest's
    `authoritative_intake_form_id` is recomputed and becomes null when no other
    screened form exists, with `screened_condition_codes` following it, and the
    guest's `version` increments by 1."

    Design: Corner/state_machines/intake_amendment_loop_is_bounded_and_state_guarded
    """
    guest, guest_headers, form = _flagged_draft_form()
    assert form["status"] == "DRAFT"
    assert form["amendment_round"] == 0

    too_early = api_client.amend_intake_form(
        form["id"], f.amend_payload(condition_codes=[]), guest_headers)
    validate_error(too_early, ApiErrorId.ERR_INVALID_INTAKE_STATE.value, 409)

    screened = _submit_and_screen(form["id"], guest_headers)
    assert screened["status"] == "SCREENED_FLAGGED"
    assert screened["flagged_condition_codes"] == ["ACTIVE_INFECTION"]
    assert screened["amendment_round"] == 0, (
        "screening is not an amendment and must not touch the counter")
    assert validate_success(api_client.get_guest(
        guest["id"], fx.COORDINATOR))["authoritative_intake_form_id"] == form["id"]

    amended = validate_success(api_client.amend_intake_form(
        form["id"], f.amend_payload(condition_codes=["DEEP_VEIN_THROMBOSIS"]),
        guest_headers))
    assert amended["status"] == "DRAFT"
    assert amended["amendment_round"] == 1
    assert amended["flagged_condition_codes"] == []
    assert amended["screened_by_user_id"] is None
    assert amended["screened_at"] is None
    assert amended["condition_codes"] == ["DEEP_VEIN_THROMBOSIS"], (
        "the submitted answers replace the declared ones")

    after = validate_success(api_client.get_guest(guest["id"], fx.COORDINATOR))
    assert after["authoritative_intake_form_id"] is None, (
        "no screened form remains, so the computed pointer goes back to null")
    assert after["screened_condition_codes"] == []


def test_the_amendment_loop_is_hard_capped_at_two_completed_rounds():
    """A third amendment attempt on a twice-amended flagged form is refused.

    PRD §3.4: "Each amendment increments `amendment_round` by 1, and the loop is
    hard-capped at two completed rounds: a third amendment attempt on a form whose
    `amendment_round` has already reached 2 is refused with
    `ERR_AMENDMENT_LIMIT`."

    PRD §2.7 rung 34: "**Amendment budget** — the intake form's
    `amendment_round` is below the amendment cap. Applies to intake amendment.
    Violation: `ERR_AMENDMENT_LIMIT` (409)."

    Design: Corner/state_machines/intake_amendment_loop_is_bounded_and_state_guarded
    """
    _guest, guest_headers, form = _flagged_draft_form()
    form_id = form["id"]
    _submit_and_screen(form_id, guest_headers)

    first = validate_success(api_client.amend_intake_form(
        form_id, f.amend_payload(condition_codes=["DEEP_VEIN_THROMBOSIS"]),
        guest_headers))
    assert first["amendment_round"] == 1
    reflagged = _submit_and_screen(form_id, guest_headers)
    assert reflagged["status"] == "SCREENED_FLAGGED"
    assert reflagged["flagged_condition_codes"] == ["DEEP_VEIN_THROMBOSIS"]

    second = validate_success(api_client.amend_intake_form(
        form_id, f.amend_payload(condition_codes=["RECENT_SURGERY_90D"]),
        guest_headers))
    assert second["amendment_round"] == 2
    flagged_again = _submit_and_screen(form_id, guest_headers)
    assert flagged_again["status"] == "SCREENED_FLAGGED"
    assert flagged_again["amendment_round"] == 2

    third = api_client.amend_intake_form(
        form_id, f.amend_payload(condition_codes=[]), guest_headers)
    validate_error(third, ApiErrorId.ERR_AMENDMENT_LIMIT.value, 409)

    unchanged = validate_success(api_client.get_intake_form(form_id, guest_headers))
    assert unchanged["amendment_round"] == 2, (
        "the counter never exceeds two completed rounds")
    assert unchanged["status"] == "SCREENED_FLAGGED"
    assert unchanged["condition_codes"] == ["RECENT_SURGERY_90D"], (
        "the refused amendment replaced nothing")


# ---------------------------------------------------------------------------
# The therapist roster cycle
# ---------------------------------------------------------------------------

def test_suspended_is_re_enterable_but_inactive_is_the_only_terminal_state():
    """Suspend, reinstate, suspend permanently, then nothing departs.

    PRD §3.2: "`INACTIVE` is the only terminal roster state — no transition leads
    out of it, and an attempt to suspend a therapist who is not `ACTIVE` (other
    than the permanent path), to reinstate one who is not `SUSPENDED`, or to move
    a therapist out of `INACTIVE` at all is refused with
    `ERR_INVALID_THERAPIST_STATE`."

    PRD §3.2: "Reinstatement runs the other way, `SUSPENDED → ACTIVE`, and it is
    credential-gated: the therapist must hold at least one licence whose
    `verification_status` is `VERIFIED` and whose `expires_on` falls on or after
    the current logical-clock date."

    PRD §3.5: "On credentials, the assigned therapist must hold a `VERIFIED`
    licence for their `practice_state_code` (`ERR_LICENSE_NOT_VERIFIED`) whose
    `expires_on` is on or after the current logical-clock date
    (`ERR_LICENSE_EXPIRED`), must hold an `ACTIVE`, unexpired certification grant
    for the treatment's `required_skill_code` at or above the required scope rank
    (`ERR_SCOPE_OF_PRACTICE_VIOLATION`), and must themselves be `ACTIVE`
    (`ERR_THERAPIST_NOT_ACTIVE`)."

    Design: Corner/state_machines/therapist_cycle_suspend_reinstate_and_permanent_inactive
    """
    world = fx.build_world()
    therapist_id = world.therapist_id

    suspended = validate_success(api_client.suspend_therapist(
        therapist_id, f.suspend_payload(reason_note="guest complaint under review"),
        fx.DIRECTOR))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "DIRECTOR_ACTION"

    refused_booking = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT, therapist_id),
        fx.COORDINATOR)
    validate_error(refused_booking, ApiErrorId.ERR_THERAPIST_NOT_ACTIVE.value, 409)

    reinstated = validate_success(
        api_client.reinstate_therapist(therapist_id, {}, fx.DIRECTOR))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    validate_error(api_client.reinstate_therapist(therapist_id, {}, fx.DIRECTOR),
                   ApiErrorId.ERR_INVALID_THERAPIST_STATE.value, 409)

    inactive = validate_success(api_client.suspend_therapist(
        therapist_id,
        f.suspend_payload(permanent=True, reason_note="licence surrendered"),
        fx.DIRECTOR))
    assert inactive["status"] == "INACTIVE"
    assert inactive["suspension_reason"] == "DIRECTOR_ACTION"

    validate_error(api_client.reinstate_therapist(therapist_id, {}, fx.DIRECTOR),
                   ApiErrorId.ERR_INVALID_THERAPIST_STATE.value, 409)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the refused booking")
    assert world.fetch_therapist()["assigned_minutes_total"] == 0
    assert world.fetch_room()["booked_minutes_total"] == 0


# ---------------------------------------------------------------------------
# Single-shot retail resolution
# ---------------------------------------------------------------------------

def test_both_retail_outcomes_are_terminal_so_four_attempts_post_one_row():
    """A purchase cannot be re-posted and a decline cannot be flipped.

    PRD §3.7: "Resolving an attachment that is not `RECOMMENDED` — including one
    that has already been purchased, declined or expired — is refused with
    `ERR_INVALID_ATTACHMENT_STATE`."

    PRD §3.7: "With `outcome` `PURCHASED`, the attachment moves
    `RECOMMENDED → PURCHASED`, records the resolving user as `resolved_by_user_id`
    and stamps `resolved_at` with the logical clock, and posts a folio charge of
    `kind` `RETAIL` whose `amount_cents` is the attachment's `amount_cents`, after
    which the guest's `folio_balance_cents` is recomputed as the exact sum of the
    guest's postings and the guest's `version` increments by 1."

    PRD §3.7: "With `outcome` `DECLINED`, the attachment moves
    `RECOMMENDED → DECLINED`, records `resolved_by_user_id` and `resolved_at` in
    exactly the same way, and posts nothing at all."

    Design: Corner/state_machines/retail_attachment_branch_resolution_is_single_shot
    """
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    appointment_id = world.appointments["a"]["id"]
    attachments = [
        validate_success(api_client.create_retail_attachment(
            appointment_id, f.retail_attachment_payload(product_sku=sku),
            world.therapist_headers), 201)
        for sku in ("MARINE-SERUM-30", "MARINE-BALM-50")
    ]
    assert all(row["status"] == "RECOMMENDED" for row in attachments)

    purchased = validate_success(api_client.resolve_retail_attachment(
        attachments[0]["id"], f.resolve_payload("PURCHASED"), world.guest_headers))
    assert purchased["status"] == "PURCHASED"
    assert purchased["resolved_by_user_id"] == world.guest_id
    assert_same_instant(purchased["resolved_at"], CANON_START_AT, "resolved_at")

    validate_error(
        api_client.resolve_retail_attachment(
            attachments[0]["id"], f.resolve_payload("DECLINED"),
            world.guest_headers),
        ApiErrorId.ERR_INVALID_ATTACHMENT_STATE.value, 409)

    declined = validate_success(api_client.resolve_retail_attachment(
        attachments[1]["id"], f.resolve_payload("DECLINED"), fx.COORDINATOR))
    assert declined["status"] == "DECLINED"
    assert declined["resolved_by_user_id"] == COORDINATOR_USER_ID
    assert_same_instant(declined["resolved_at"], CANON_START_AT, "resolved_at")

    validate_error(
        api_client.resolve_retail_attachment(
            attachments[1]["id"], f.resolve_payload("PURCHASED"), fx.COORDINATOR),
        ApiErrorId.ERR_INVALID_ATTACHMENT_STATE.value, 409)

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR), 2,
        "appointment folio postings")
    retail_rows = [row for row in postings if row["kind"] == "RETAIL"]
    assert len(retail_rows) == 1, (
        f"exactly one RETAIL row survives four resolve attempts, got {postings}")
    assert retail_rows[0]["amount_cents"] == 4595
    assert world.fetch_guest()["folio_balance_cents"] == 55099, (
        "50504 + 4595, with no re-post and no reversal")


# ---------------------------------------------------------------------------
# The refused second final settlement
# ---------------------------------------------------------------------------

def test_a_second_final_settlement_is_refused_on_state_not_on_version():
    """The retry quotes the current version and still loses to the state rung.

    PRD §3.9: "Attempting it on an appointment that has not reached `COMPLETED` is
    refused with `ERR_INVALID_APPOINTMENT_STATE`; attempting it when a row with
    `variant` `FINAL` already exists is refused with
    `ERR_SETTLEMENT_ALREADY_FINAL`; a version that does not match the
    appointment's current `version` is refused with
    `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412)."

    PRD §3.9: "A row cut at settlement time is created with `variant` `FINAL` and
    `status` `FINALIZED`."

    PRD §3.9: "It posts a folio charge of `kind` `SETTLEMENT_ADJUSTMENT` whose
    `amount_cents` is the final row's `folio_total_cents` less the sum of
    `amount_cents` over every folio posting already recorded against that
    appointment — a figure that is negative whenever the delivered service came in
    cheaper than the provisional estimate."

    Design: Corner/state_machines/second_final_settlement_is_refused
    """
    world = fx.world_with_completed_appointment(gratuity_cents=5000)
    appointment_id = world.appointments["a"]["id"]
    completed = world.fetch_appointment(appointment_id)
    assert completed["schedule_status"] == "COMPLETED"

    final_row = validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(completed["version"]), fx.DIRECTOR),
        201)
    assert final_row["variant"] == "FINAL"
    assert final_row["status"] == "FINALIZED"
    assert final_row["realized_price_cents"] == FINAL_REALIZED_CENTS, (
        "42800 quoted plus one 2500-cent overtime block for 105 delivered minutes")
    assert final_row["folio_total_cents"] == FINAL_FOLIO_TOTAL_CENTS

    settled = world.fetch_appointment(appointment_id)
    assert settled["realized_price_cents"] == FINAL_REALIZED_CENTS
    balance_after_first = world.fetch_guest()["folio_balance_cents"]
    assert balance_after_first == FINAL_FOLIO_TOTAL_CENTS

    retry = api_client.create_settlement(
        appointment_id, f.settlement_payload(settled["version"]), fx.DIRECTOR)
    error = validate_error(retry, ApiErrorId.ERR_SETTLEMENT_ALREADY_FINAL.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value, (
        "the retry quotes the appointment's current version, so the optimistic "
        "concurrency rung passes and the state rung is what refuses it")

    rows, meta = validate_paginated(api_client.list_settlements(
        appointment_id, fx.DIRECTOR, params={"variant": "FINAL"}))
    assert meta["total_count"] == 1, (
        f"exactly one FINAL row exists, got {meta['total_count']}")
    assert rows[0]["id"] == final_row["id"]

    postings = validate_success(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR))
    adjustments = [row for row in postings if row["kind"] == "SETTLEMENT_ADJUSTMENT"]
    assert len(adjustments) == 1, (
        f"no second adjustment is posted, got {[r['kind'] for r in postings]}")
    assert adjustments[0]["amount_cents"] == SETTLEMENT_ADJUSTMENT_CENTS, (
        f"{FINAL_FOLIO_TOTAL_CENTS} less the {PROVISIONAL_FOLIO_TOTAL_CENTS} "
        "already posted at check-in")
    assert world.fetch_guest()["folio_balance_cents"] == balance_after_first, (
        "the refused retry leaves the balance exactly where it stood")


# ---------------------------------------------------------------------------
# The clearance reason under a fixed precedence
# ---------------------------------------------------------------------------

def _blocked_world_with_recommendation():
    """A CONFIRMED x CLEARED appointment carrying one RECOMMENDED attachment, then
    the room taken to MAINTENANCE so clause 4 alone fails."""
    world = fx.world_with_confirmed_appointment()
    appointment_id = world.appointments["a"]["id"]
    attachment = validate_success(api_client.create_retail_attachment(
        appointment_id, f.retail_attachment_payload(), world.therapist_headers),
        201)
    assert attachment["status"] == "RECOMMENDED"
    fx.set_room_status(world.room_id, "MAINTENANCE")
    return world, attachment


def _flag_the_guest_with_a_newer_form(world):
    """Screen a second, flagged form for the same guest so clause 1 fails too."""
    guest = world.fetch_guest()
    guest_headers = world.guest_headers
    form = validate_success(api_client.create_intake_form(
        world.guest_id,
        f.intake_form_payload(guest["version"],
                              condition_codes=["RECENT_SURGERY_90D"],
                              medications=[]),
        guest_headers), 201)
    validate_success(api_client.sign_consent(
        form["id"], f.consent_payload(CANON_CONSENT_VERSION), guest_headers))
    validate_success(api_client.submit_intake_form(form["id"], {}, guest_headers))
    screened = validate_success(api_client.screen_intake_form(
        form["id"], {}, fx.make_compliance_headers("co-7")))
    assert screened["status"] == "SCREENED_FLAGGED"
    return form


def test_the_block_reason_is_rewritten_to_the_first_failing_clause_each_time():
    """ROOM_UNAVAILABLE, then INTAKE_FLAGGED, then back, then CLEARED.

    PRD §2.10: "When one or more fail, clearance is `BLOCKED` and
    `clearance_block_reason` is set from the **first** failing clause in that
    order — `INTAKE_FLAGGED`, then `LICENSE_INVALID`, then `THERAPIST_SUSPENDED`,
    then `ROOM_UNAVAILABLE`."

    PRD §2.10: "If a later event repairs only some of the failing clauses, the
    appointment stays `BLOCKED` and `clearance_block_reason` is rewritten to the
    new first failing clause."

    PRD §2.10: "They advance independently: an appointment may legitimately sit at
    `CONFIRMED` with `BLOCKED` clearance, at `CONFIRMED` with `CLEARED` clearance,
    or at `CHECKED_IN` with `BLOCKED` clearance, and it is the **pair** that
    decides which transitions are legal."

    Design: Corner/state_machines/clearance_block_reason_follows_fixed_precedence
    """
    world, _attachment = _blocked_world_with_recommendation()
    appointment_id = world.appointments["a"]["id"]

    after_room = world.fetch_appointment(appointment_id)
    assert_state_pair(after_room, "CONFIRMED", "BLOCKED", "ROOM_UNAVAILABLE")

    form = _flag_the_guest_with_a_newer_form(world)
    after_screen = world.fetch_appointment(appointment_id)
    assert_state_pair(after_screen, "CONFIRMED", "BLOCKED", "INTAKE_FLAGGED")

    overridden = validate_success(api_client.override_intake_form(
        form["id"], f.override_payload("surgeon clearance letter"),
        fx.make_director_headers("dir-9")))
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["overridden_by_user_id"] == "dir-9"
    after_override = world.fetch_appointment(appointment_id)
    assert_state_pair(after_override, "CONFIRMED", "BLOCKED", "ROOM_UNAVAILABLE")

    fx.set_room_status(world.room_id, "ACTIVE")
    after_repair = world.fetch_appointment(appointment_id)
    assert_state_pair(after_repair, "CONFIRMED", "CLEARED", None)
    assert after_repair["schedule_status"] == "CONFIRMED", (
        "the schedule dimension never moved across any of the four events")


def test_an_expired_recommendation_is_never_revived_by_the_re_clear():
    """Expiry is one-directional even after the appointment is fully cleared.

    PRD §2.10: "Every appointment driven to `BLOCKED` also expires that
    appointment's retail recommendations: each retail attachment still in
    `RECOMMENDED` becomes `EXPIRED`. This is one-directional — a retail attachment
    that has already reached `EXPIRED` is **never** revived when the appointment is
    later re-cleared."

    PRD §3.7: "When the parent appointment's `clearance_status` becomes `BLOCKED`
    for any reason, every attachment on that appointment still in `RECOMMENDED`
    moves `RECOMMENDED → EXPIRED` as a system act; `resolved_by_user_id` and
    `resolved_at` stay null precisely because no user resolved it, and no folio
    posting is made."

    PRD §3.4: "An override re-evaluates the guest's `BLOCKED` non-terminal
    appointments and promotes each to `CLEARED` when all four clauses hold — but
    retail attachments that already reached `EXPIRED` are not revived."

    Design: Corner/state_machines/clearance_block_reason_follows_fixed_precedence
    """
    world, attachment = _blocked_world_with_recommendation()
    appointment_id = world.appointments["a"]["id"]

    expired = [row for row in validate_success(
        api_client.list_retail_attachments(appointment_id, world.therapist_headers))
        if row["id"] == attachment["id"]]
    assert len(expired) == 1
    assert expired[0]["status"] == "EXPIRED", (
        f"the block expired the recommendation, got {expired[0]['status']}")
    assert expired[0]["resolved_by_user_id"] is None, (
        "no user resolved it, so the resolver stays null")
    assert expired[0]["resolved_at"] is None
    assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR), 0,
        "appointment folio postings")

    form = _flag_the_guest_with_a_newer_form(world)
    validate_success(api_client.override_intake_form(
        form["id"], f.override_payload("surgeon clearance letter"),
        fx.make_director_headers("dir-9")))
    fx.set_room_status(world.room_id, "ACTIVE")
    assert world.fetch_appointment(appointment_id)["clearance_status"] == "CLEARED"

    still_expired = validate_success(api_client.list_retail_attachments(
        appointment_id, world.therapist_headers, params={"status": "EXPIRED"}))
    assert len(still_expired) == 1 and still_expired[0]["id"] == attachment["id"], (
        "the re-clear must not move the row back to RECOMMENDED")
    assert validate_success(api_client.list_retail_attachments(
        appointment_id, world.therapist_headers,
        params={"status": "RECOMMENDED"})) == [], (
        "the guest must be re-offered the product as a new recommendation")

    refused = api_client.resolve_retail_attachment(
        attachment["id"], f.resolve_payload("PURCHASED"), world.guest_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_ATTACHMENT_STATE.value, 409)
    assert world.fetch_guest()["folio_balance_cents"] == 0
