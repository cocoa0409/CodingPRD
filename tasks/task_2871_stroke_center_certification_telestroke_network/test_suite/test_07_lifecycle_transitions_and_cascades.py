"""Declared lifecycle transitions, refusals from terminal states, and the abort/close cascades."""
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CERTIFICATION_REVIEWER_USER_ID,
    COORD,
    ED,
    QUALITY_ABSTRACTOR_USER_ID,
    REVIEWER,
    TRANSFER,
    make_neurologist_headers,
)


def _activated_case(door_at="2026-09-01T08:00:00Z"):
    """One SPOKE facility holding one freshly ACTIVATED code stroke."""
    center = fx.register_center()
    case = fx.activate_case(center["id"], door_at)
    return center, case


def _assigned_consult(door_at="2026-09-01T08:00:00Z"):
    """A case in CONSULT_IN_PROGRESS whose consult is ASSIGNED but never accepted."""
    context = fx.setup_network(clock=door_at)
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at=fx.shift(door_at, minutes=12))
    consult = fx.request_consult(
        case["id"], context["agreement"]["id"], at=fx.shift(door_at, minutes=15)
    )
    return context, case, consult


def _looped_deviation():
    """A MANUAL deviation walked around the review loop until review_round is 3."""
    center = fx.register_center()
    case = fx.activate_case(center["id"], "2026-09-01T08:00:00Z")
    deviation = fx.create_deviation(case["id"], deviation_type="DTN_EXCEEDED", severity="MAJOR")
    rounds = [fx.start_review(deviation["id"])]
    rounds.append(fx.return_for_info(deviation["id"]))
    rounds.append(fx.resubmit_deviation(deviation["id"]))
    rounds.append(fx.return_for_info(deviation["id"]))
    rounds.append(fx.resubmit_deviation(deviation["id"]))
    return case, deviation, rounds


def test_manual_deviation_opens_in_the_declared_initial_state():
    """A hand-raised deviation is born OPEN at review_round 0 with the caller as its opener.

    PRD 3.8: "is created with `source` `MANUAL`, `status` `OPEN`, `opened_by_user_id` from the caller's identity header, `review_round` 0 and `debrief_completed` false, returning 201 and raising the case's `deviation_count` by 1"

    Design: Corner/state_machines/protocol_deviation_opens_in_the_declared_initial_state
    """
    center, case = _activated_case()
    assert case["deviation_count"] == 0, (
        f"a freshly activated case carries no deviations, got {case['deviation_count']}"
    )

    deviation = fx.create_deviation(
        case["id"],
        deviation_type="DTI_EXCEEDED",
        severity="MINOR",
        narrative="the scan slipped past the forty five minute target",
    )

    a.assert_protocol_deviation(deviation)
    assert deviation["status"] == "OPEN", (
        f"the declared initial state of the review machine is OPEN, got {deviation['status']}"
    )
    assert deviation["source"] == "MANUAL", (
        f"a create call always produces a MANUAL row, got {deviation['source']}"
    )
    assert deviation["review_round"] == 0, (
        f"no review has been entered yet, got {deviation['review_round']}"
    )
    assert deviation["debrief_completed"] is False, (
        f"only the debrief write flips that flag, got {deviation['debrief_completed']}"
    )
    assert deviation["opened_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID, (
        "the opener is the caller's own identity header, not the literal 'system', got "
        f"{deviation['opened_by_user_id']!r}"
    )
    assert deviation["reviewed_by_user_id"] is None, (
        f"no reviewer has touched the row, got {deviation['reviewed_by_user_id']!r}"
    )
    assert deviation["case_id"] == case["id"]
    assert deviation["deviation_type"] == "DTI_EXCEEDED"
    assert deviation["severity"] == "MINOR"
    assert deviation["version"] == 1, (
        f"a created record begins at version 1, got {deviation['version']}"
    )

    after = fx.read_case(case["id"])
    assert after["deviation_count"] == 1, (
        f"the create raises the case's deviation_count by exactly 1, got {after['deviation_count']}"
    )
    listed = fx.list_case_deviations(case["id"])
    assert len(listed) == 1, f"exactly one deviation hangs off the case, got {len(listed)}"
    assert listed[0]["id"] == deviation["id"]
    assert fx.read_center(center["id"])["open_case_count"] == 1, (
        "raising a deviation moves no facility ledger"
    )


def test_imaging_completion_moves_an_activated_case_and_stamps_the_clock():
    """ACTIVATED -> IMAGING_COMPLETE writes imaging_at and the door-to-imaging interval.

    PRD 3.6: "The transition depends on where the case is. From `ACTIVATED` the case moves to `IMAGING_COMPLETE`."
    PRD 3.6: "it stamps `imaging_at` from the logical clock and computes `door_to_imaging_minutes` from the case's `door_at` to that instant"
    PRD 2.5: "a monotonically increasing counter that begins at 1 on creation and increments by exactly 1 on every mutation of that record"

    Design: Corner/state_machines/imaging_complete_moves_an_activated_case_and_stamps_the_clock
    """
    center, case = _activated_case()
    assert case["status"] == "ACTIVATED", f"the case starts at ACTIVATED, got {case['status']}"
    assert case["imaging_at"] is None, "nothing has been scanned yet"
    assert case["door_to_imaging_minutes"] is None
    assert case["version"] == 1, f"activation is the creating write, got {case['version']}"

    imaged = fx.complete_imaging(case["id"], at="2026-09-01T08:20:00Z")

    assert imaged["status"] == "IMAGING_COMPLETE", (
        f"the only declared transition out of ACTIVATED for imaging, got {imaged['status']}"
    )
    assert imaged["imaging_at"] == "2026-09-01T08:20:00Z", (
        f"imaging_at is stamped from the logical clock, got {imaged['imaging_at']}"
    )
    assert imaged["door_to_imaging_minutes"] == 20, (
        "08:00 to 08:20 is twenty whole minutes, got "
        f"{imaged['door_to_imaging_minutes']}"
    )
    assert imaged["version"] == 2, (
        f"exactly one mutation has landed on the case since creation, got {imaged['version']}"
    )
    assert imaged["disposition"] == "PENDING", (
        f"imaging decides no branch, got {imaged['disposition']}"
    )
    assert imaged["needle_at"] is None, "no drug has been given"
    assert imaged["deviation_count"] == 0, (
        f"twenty minutes is well inside the 45-minute target, got {imaged['deviation_count']}"
    )
    assert fx.list_case_deviations(case["id"]) == [], "a fast scan opens no deviation at all"
    assert fx.read_center(center["id"])["open_case_count"] == 1, (
        "imaging moves no facility ledger; the patient is still in the department"
    )


def test_imaging_completion_is_blocked_while_the_ct_scanner_is_failed():
    """The equipment gate reads the individual scanner flag, and a PASS re-opens the transition.

    PRD 3.6: "The facility's `ct_scanner_ready` must be true — and note that this gate reads the individual flag, not the aggregate posture"
    PRD 3.1: "The named component's flag is set to true when the result is `PASS` and false when it is `FAIL`"

    Design: Corner/state_machines/imaging_complete_is_blocked_while_the_ct_scanner_is_failed
    """
    center, case = _activated_case()
    degraded = fx.degrade_center(center["id"], "CT_SCANNER")
    assert degraded["ct_scanner_ready"] is False, (
        f"the FAIL attestation lowers the scanner flag, got {degraded['ct_scanner_ready']}"
    )
    assert degraded["video_cart_ready"] is True, "the other half of the pair is untouched"
    assert degraded["equipment_readiness_posture"] == "DEGRADED", (
        f"one false flag is DEGRADED, not OFFLINE, got {degraded['equipment_readiness_posture']}"
    )

    fx.set_clock("2026-09-01T08:20:00Z")
    response = api_client.complete_imaging(case["id"], f.imaging_complete_payload(), ED)
    validate_error(response, ApiErrorId.ERR_CENTER_EQUIPMENT_OFFLINE.value, 409)

    blocked = fx.read_case(case["id"])
    assert blocked["status"] == "ACTIVATED", (
        f"the refused call leaves the case where it stood, got {blocked['status']}"
    )
    assert blocked["imaging_at"] is None, (
        f"no clock is stamped by a rejected write, got {blocked['imaging_at']}"
    )
    assert blocked["door_to_imaging_minutes"] is None
    assert blocked["version"] == 1, (
        f"a rejected write is not a mutation, got {blocked['version']}"
    )

    restored = fx.attest_readiness(center["id"], "CT_SCANNER", "PASS")
    assert restored["ct_scanner_ready"] is True
    assert restored["equipment_readiness_posture"] == "READY", (
        f"both flags true is READY again, got {restored['equipment_readiness_posture']}"
    )

    imaged = fx.complete_imaging(case["id"], at="2026-09-01T08:30:00Z")
    assert imaged["status"] == "IMAGING_COMPLETE", (
        f"the same call now takes the declared transition, got {imaged['status']}"
    )
    assert imaged["door_to_imaging_minutes"] == 30, (
        "the interval runs from door to the successful scan, not to the refused one, got "
        f"{imaged['door_to_imaging_minutes']}"
    )
    assert imaged["version"] == 2, (
        f"only the successful imaging write bumped the case, got {imaged['version']}"
    )


def test_consult_creation_applies_every_declared_routing_side_effect():
    """One create call stamps the assignment, advances the case and recomputes two load counts.

    PRD 3.3: "The winner is written to `assigned_neurologist_id`, `assigned_at` is stamped from the logical clock, the consult's `status` becomes `ASSIGNED`, `routing_attempt_count` reflects the pass just executed, and both the winner's `active_consult_count` and the agreement's `active_consult_count` are recomputed."
    PRD 3.3: "A case sitting in `ACTIVATED` or in `IMAGING_COMPLETE` transitions to `CONSULT_IN_PROGRESS`, and that transition increments the case's `version`"
    PRD 3.3: "On acceptance the consult's `status` becomes `IN_SESSION`, `accepted_at` is stamped from the logical clock"

    Design: Corner/state_machines/consult_creation_applies_every_declared_routing_side_effect
    """
    context, case, consult = _assigned_consult()
    neurologist_id = context["neurologist"]["id"]

    assert consult["status"] == "ASSIGNED", (
        f"routing found a candidate on the first pass, got {consult['status']}"
    )
    assert consult["assigned_neurologist_id"] == neurologist_id, (
        "the sole on-call credentialed neurologist wins, got "
        f"{consult['assigned_neurologist_id']}"
    )
    assert consult["requested_at"] == "2026-09-01T08:15:00Z", (
        f"requested_at comes from the logical clock, got {consult['requested_at']}"
    )
    assert consult["assigned_at"] == "2026-09-01T08:15:00Z", (
        "assignment happens inside the same request, so it shares the instant, got "
        f"{consult['assigned_at']}"
    )
    assert consult["routing_attempt_count"] == 1, (
        f"exactly one routing pass was executed, got {consult['routing_attempt_count']}"
    )
    assert consult["excluded_neurologist_ids"] == [], (
        f"nobody declined, so nobody is excluded, got {consult['excluded_neurologist_ids']}"
    )
    assert consult["decline_count"] == 0
    assert consult["accepted_at"] is None, (
        f"assignment is not acceptance, got {consult['accepted_at']}"
    )
    assert consult["response_latency_seconds"] is None, (
        "the latency is only computable once the neurologist answers"
    )
    assert consult["valid_video_session_count"] == 0
    assert consult["cancellation_reason"] is None

    moved = fx.read_case(case["id"])
    assert moved["status"] == "CONSULT_IN_PROGRESS", (
        f"IMAGING_COMPLETE walks forward to CONSULT_IN_PROGRESS, got {moved['status']}"
    )
    assert moved["version"] == 3, (
        "activation, imaging and the consult transition are three mutations, got "
        f"{moved['version']}"
    )
    assert moved["imaging_at"] == "2026-09-01T08:12:00Z", (
        "the imaging clock survives the consult transition untouched"
    )

    neurologist = fx.read_neurologist(neurologist_id)
    assert neurologist["active_consult_count"] == 1, (
        f"the assignment is live load on the winner, got {neurologist['active_consult_count']}"
    )
    assert neurologist["on_call_state"] == "ON_CALL", (
        "only acceptance flips the roster state to IN_CONSULT, got "
        f"{neurologist['on_call_state']}"
    )
    assert neurologist["completed_consult_count"] == 0
    assert neurologist["last_consult_completed_at"] is None, (
        "no cooldown starts at assignment"
    )

    agreement = fx.read_agreement(context["agreement"]["id"])
    assert agreement["active_consult_count"] == 1, (
        f"the contract carries the same live consult, got {agreement['active_consult_count']}"
    )
    assert agreement["status"] == "ACTIVE"


def test_completing_a_consult_that_was_never_accepted_is_refused():
    """ASSIGNED has no completion transition, and the refusal outranks the video-session gate.

    PRD 3.4: "The consult must be `IN_SESSION` and the caller must be its assignee."
    PRD 2.11: "The addressed record must be in a state from which the requested transition is declared"

    Design: Corner/state_machines/completing_a_consult_that_was_never_accepted_is_refused
    """
    context, case, consult = _assigned_consult()
    neurologist_id = context["neurologist"]["id"]
    assert consult["status"] == "ASSIGNED", "the consult was never accepted"

    fx.set_clock("2026-09-01T08:25:00Z")
    response = api_client.complete_consult(
        consult["id"], f.complete_consult_payload(), make_neurologist_headers(neurologist_id)
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_CONSULT_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_NO_VALID_VIDEO_SESSION.value, (
        "the declared-transition rule outranks the video-session gate, got "
        f"{error['error_id']}"
    )
    assert error["error_id"] != ApiErrorId.ERR_NOT_CONSULT_OWNER.value, (
        "the assignee did call, so ownership is not the complaint"
    )

    unchanged = fx.read_consult(consult["id"])
    assert unchanged["status"] == "ASSIGNED", (
        f"the refused completion leaves the consult ASSIGNED, got {unchanged['status']}"
    )
    assert unchanged["completed_at"] is None, (
        f"no completion instant is stamped, got {unchanged['completed_at']}"
    )
    assert unchanged["recommendation"] is None, (
        f"no recommendation is recorded, got {unchanged['recommendation']}"
    )
    assert unchanged["nihss_score"] is None
    assert unchanged["version"] == consult["version"], (
        f"a rejected write is not a mutation, got {unchanged['version']}"
    )

    neurologist = fx.read_neurologist(neurologist_id)
    assert neurologist["completed_consult_count"] == 0, (
        f"nothing was completed, got {neurologist['completed_consult_count']}"
    )
    assert neurologist["last_consult_completed_at"] is None, (
        "no cooldown was started by the refused call"
    )
    assert neurologist["on_call_state"] == "ON_CALL", (
        f"the roster state never left ON_CALL, got {neurologist['on_call_state']}"
    )
    assert neurologist["active_consult_count"] == 1, (
        "the assignment is still live load, got "
        f"{neurologist['active_consult_count']}"
    )
    assert fx.read_case(case["id"])["status"] == "CONSULT_IN_PROGRESS", (
        "the case is still waiting on the same consult"
    )


def test_a_closed_case_refuses_every_further_lifecycle_action():
    """Five different writes against a CLOSED case all land on the same terminal-state code.

    PRD 3.2: "Requesting a consult, opening a checklist, writing an inclusion item or a contraindication, determining eligibility, proposing a transfer, administering a thrombolytic and creating an abstraction all require the case's `status` to be neither `CLOSED` nor `ABORTED`, and all report `ERR_CASE_NOT_ACTIVE` when it is."
    PRD 2.11: "The same code covers a case action attempted from a status for which no transition is declared."

    Design: Corner/state_machines/a_closed_case_refuses_every_further_lifecycle_action
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_closed_treated_case(context, door_at, dtn_minutes=45, dti_minutes=20)
    case_id = built["case"]["id"]
    spoke_id = context["spoke"]["id"]
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    closed = fx.read_case(case_id)
    assert closed["status"] == "CLOSED", f"the case is terminal, got {closed['status']}"
    assert closed["disposition"] == "TREATED_LOCAL"
    assert closed["needle_at"] == "2026-09-01T08:45:00Z"
    version_at_close = closed["version"]

    fx.set_clock("2026-09-01T09:00:00Z")

    aborted = api_client.abort_code_stroke(case_id, f.abort_case_payload(), ED)
    validate_error(aborted, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)

    reclosed = api_client.close_code_stroke(case_id, ED)
    validate_error(reclosed, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)

    shipped = api_client.propose_transfer(
        f.transfer_payload(case_id, destination["id"], "TRANSFER_ONLY", 30), TRANSFER
    )
    mode_error = validate_error(shipped, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)
    assert mode_error["error_id"] != ApiErrorId.ERR_TRANSFER_MODE_MISMATCH.value, (
        "the terminal-state rule outranks the mode-versus-treatment check, got "
        f"{mode_error['error_id']}"
    )

    duplicate = api_client.create_checklist(f.checklist_payload(case_id), ED)
    checklist_error = validate_error(duplicate, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)
    assert checklist_error["error_id"] != ApiErrorId.ERR_DUPLICATE_CHECKLIST.value, (
        "the terminal-state rule outranks the one-checklist-per-case rule, got "
        f"{checklist_error['error_id']}"
    )

    requested = api_client.request_consult(
        f.consult_request_payload(case_id, context["agreement"]["id"], version_at_close), ED
    )
    consult_error = validate_error(requested, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)
    assert consult_error["error_id"] != ApiErrorId.ERR_STALE_CASE_VERSION.value, (
        f"the supplied version was the live one, got {consult_error['error_id']}"
    )

    after = fx.read_case(case_id)
    assert after["status"] == "CLOSED", (
        f"five refusals leave the terminal status alone, got {after['status']}"
    )
    assert after["disposition"] == "TREATED_LOCAL", (
        f"the branch actually taken is preserved, got {after['disposition']}"
    )
    assert after["version"] == version_at_close, (
        f"not one of the refused writes was a mutation, got {after['version']}"
    )
    origin = fx.read_center(spoke_id)
    assert origin["open_case_count"] == 0, (
        f"the ledger was released once by the close and never again, got {origin['open_case_count']}"
    )
    assert origin["ems_routing_posture"] == "ROUTINE"
    assert fx.read_center(destination["id"])["open_case_count"] == 0, (
        "the refused proposal never reached the destination's ledger"
    )
    transfers, meta = validate_paginated(
        api_client.list_transfers(TRANSFER, {"case_id": case_id, "limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"no transfer decision was brought into existence, got {meta['total_count']}"
    )
    assert transfers == []


def test_activating_an_already_active_agreement_is_rejected_not_ignored():
    """A second activate on an ACTIVE agreement errors rather than silently re-succeeding.

    PRD 3.1: "Any activation attempted from a state or against a hub for which no transition is declared — activating an already `ACTIVE` agreement, or a `TERMINATED` one, or one whose hub is suspended — is rejected with `ERR_INVALID_AGREEMENT_STATE`."
    PRD 3.1: "Activation sets the `status` to `ACTIVE` and clears `suspension_reason` to null."

    Design: Corner/state_machines/activating_an_already_active_agreement_is_rejected_not_ignored
    """
    fx.set_clock("2026-09-01T00:00:00Z")
    hub = fx.register_hub()
    spoke = fx.register_center()
    agreement = fx.create_agreement(hub["id"], spoke["id"])
    assert agreement["status"] == "DRAFT", (
        f"a new agreement lands in DRAFT, got {agreement['status']}"
    )
    assert agreement["version"] == 1

    activated = fx.activate_agreement(agreement["id"])
    assert activated["status"] == "ACTIVE", (
        f"DRAFT -> ACTIVE is declared, got {activated['status']}"
    )
    assert activated["suspension_reason"] is None, (
        f"activation clears the reason to null, got {activated['suspension_reason']!r}"
    )
    assert activated["version"] == 2, (
        f"one mutation has landed on the agreement, got {activated['version']}"
    )

    response = api_client.activate_spoke_agreement(agreement["id"], COORD)
    validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value, 409)

    after = fx.read_agreement(agreement["id"])
    assert after["status"] == "ACTIVE", (
        f"the refusal leaves the agreement usable, got {after['status']}"
    )
    assert after["version"] == 2, (
        "a rejected activation is not an idempotent no-op write either: no version moved, got "
        f"{after['version']}"
    )
    assert after["suspension_reason"] is None
    assert after["active_consult_count"] == 0, (
        f"nothing about the load changed, got {after['active_consult_count']}"
    )
    assert after["updated_at"] == activated["updated_at"], (
        "the refused call did not even refresh updated_at, got "
        f"{after['updated_at']}"
    )


def test_both_transfer_forks_reach_transfer_initiated_with_different_dispositions():
    """One untreated and one treated case join at TRANSFER_INITIATED keeping distinct branches.

    PRD 3.7: "The case moves accordingly: `ELIGIBILITY_DETERMINED → TRANSFER_INITIATED` with `disposition` `TRANSFER_ONLY` for a transfer-only proposal, or `THROMBOLYSIS_ADMINISTERED → TRANSFER_INITIATED` with `disposition` `DRIP_AND_SHIP` for the drip-and-ship path"
    PRD 3.7: "No `open_case_count` moves at proposal time; a proposal is not yet a commitment."
    PRD 3.7: "**Step 4** sets `projected_door_in_door_out_minutes` to `adjusted_transport_minutes` plus 20 minutes of handoff preparation, plus a further 10 minutes when the `mode` is `DRIP_AND_SHIP`"

    Design: Corner/state_machines/both_transfer_forks_reach_transfer_initiated_with_different_dispositions
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    assert destination["ems_routing_posture"] == "ROUTINE", (
        f"a fresh thrombectomy centre routes routinely, got {destination['ems_routing_posture']}"
    )

    untreated = fx.setup_eligible_case(context, "2026-09-01T08:00:00Z", dti_minutes=20)
    treated = fx.setup_treated_case(
        context, "2026-09-01T09:00:00Z", dtn_minutes=45, dti_minutes=20
    )
    assert untreated["case"]["status"] == "ELIGIBILITY_DETERMINED"
    assert untreated["case"]["needle_at"] is None, "the unlysed branch never got the drug"
    assert treated["case"]["status"] == "THROMBOLYSIS_ADMINISTERED"
    assert treated["case"]["needle_at"] == "2026-09-01T09:45:00Z", (
        f"the treated branch has a needle instant, got {treated['case']['needle_at']}"
    )

    ship_unlysed = fx.propose_transfer(
        untreated["case"]["id"], destination["id"],
        mode="TRANSFER_ONLY", transport_eta_minutes=30, at="2026-09-01T09:50:00Z",
    )
    ship_lysed = fx.propose_transfer(
        treated["case"]["id"], destination["id"],
        mode="DRIP_AND_SHIP", transport_eta_minutes=30, at="2026-09-01T09:52:00Z",
    )

    for transfer in (ship_unlysed, ship_lysed):
        assert transfer["status"] == "PROPOSED", (
            f"both forks open as proposals, got {transfer['status']}"
        )
        assert transfer["origin_center_id"] == spoke_id, (
            f"origin_center_id is copied from the case, got {transfer['origin_center_id']}"
        )
        assert transfer["destination_posture_at_proposal"] == "ROUTINE", (
            "the uncommitted destination is still routine at both proposals, got "
            f"{transfer['destination_posture_at_proposal']}"
        )
        assert transfer["congestion_factor"] == 1.00, (
            f"a routine snapshot carries no congestion, got {transfer['congestion_factor']}"
        )
        a.assert_two_decimal_places(transfer["congestion_factor"], "congestion_factor")
        assert transfer["adjusted_transport_minutes"] == 30, (
            f"30 minutes at a factor of 1.00 needs no rounding, got "
            f"{transfer['adjusted_transport_minutes']}"
        )
        assert transfer["accepted_at"] is None
        assert transfer["cancellation_reason"] is None

    assert ship_unlysed["mode"] == "TRANSFER_ONLY"
    assert ship_unlysed["projected_door_in_door_out_minutes"] == 50, (
        "30 of transport plus 20 of preparation and no infusion overhead, got "
        f"{ship_unlysed['projected_door_in_door_out_minutes']}"
    )
    assert ship_lysed["mode"] == "DRIP_AND_SHIP"
    assert ship_lysed["projected_door_in_door_out_minutes"] == 60, (
        "the same transport leg plus 20 of preparation plus 10 for the infusion in transit, got "
        f"{ship_lysed['projected_door_in_door_out_minutes']}"
    )

    joined_unlysed = fx.read_case(untreated["case"]["id"])
    joined_lysed = fx.read_case(treated["case"]["id"])
    assert joined_unlysed["status"] == "TRANSFER_INITIATED", (
        f"the unlysed fork joins at TRANSFER_INITIATED, got {joined_unlysed['status']}"
    )
    assert joined_lysed["status"] == "TRANSFER_INITIATED", (
        f"the treated fork joins at the same node, got {joined_lysed['status']}"
    )
    assert joined_unlysed["disposition"] == "TRANSFER_ONLY", (
        f"the branch taken is preserved in disposition, got {joined_unlysed['disposition']}"
    )
    assert joined_lysed["disposition"] == "DRIP_AND_SHIP", (
        "the treated-then-shipped patient is distinguishable at the same status, got "
        f"{joined_lysed['disposition']}"
    )
    assert joined_unlysed["needle_at"] is None, "joining the node gives nobody a drug"
    assert joined_lysed["needle_at"] == "2026-09-01T09:45:00Z"

    assert fx.read_center(destination["id"])["open_case_count"] == 0, (
        "two proposals are two non-commitments at the destination"
    )
    assert fx.read_center(spoke_id)["open_case_count"] == 2, (
        "the origin still holds both patients"
    )


def test_aborting_a_case_cancels_its_live_consult_and_releases_the_neurologist():
    """The abort cascade cancels the in-session consult, frees its neurologist and starts no cooldown.

    PRD 3.8: "First, every consult on the case in `REQUESTED`, `ASSIGNED` or `IN_SESSION` is cancelled and every transfer decision in `PROPOSED` or `ACCEPTED` is cancelled."
    PRD 3.4: "the neurologist is released from `IN_CONSULT` back to `ON_CALL` and their `active_consult_count` is recomputed, but `last_consult_completed_at` is **not** set and `completed_consult_count` is **not** raised"
    PRD 3.4: "A cancelled consult records a `cancellation_reason` and retains its `assigned_neurologist_id` for audit rather than clearing it"
    PRD 3.8: "Consults cancelled by the case's own abort do **not** get a `CONSULT_UNFILLED` deviation"

    Design: Corner/state_machines/aborting_a_case_cancels_its_live_consult_and_releases_the_neurologist
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    spoke_id = context["spoke"]["id"]
    neurologist_id = context["neurologist"]["id"]
    case = fx.activate_case(spoke_id, door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    consult = fx.request_consult(
        case["id"], context["agreement"]["id"], at="2026-09-01T08:14:00Z"
    )
    accepted = fx.accept_consult(consult["id"], neurologist_id, at="2026-09-01T08:16:00Z")
    assert accepted["status"] == "IN_SESSION", (
        f"the neurologist is in the room, got {accepted['status']}"
    )
    in_session = fx.read_neurologist(neurologist_id)
    assert in_session["on_call_state"] == "IN_CONSULT", (
        f"acceptance flips the roster state, got {in_session['on_call_state']}"
    )
    assert in_session["active_consult_count"] == 1
    assert fx.read_center(spoke_id)["open_case_count"] == 1

    aborted = fx.abort_case(case["id"], at="2026-09-01T08:25:00Z")

    assert aborted["status"] == "ABORTED", (
        f"the escape hatch is reachable from CONSULT_IN_PROGRESS, got {aborted['status']}"
    )
    assert aborted["disposition"] == "NO_TREATMENT", (
        f"an aborted case treated nobody, got {aborted['disposition']}"
    )
    assert aborted["needle_at"] is None

    cancelled = fx.read_consult(consult["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"the live consult is cancelled by the first hop, got {cancelled['status']}"
    )
    assert isinstance(cancelled["cancellation_reason"], str) and cancelled["cancellation_reason"], (
        f"a cancelled consult records why, got {cancelled['cancellation_reason']!r}"
    )
    assert cancelled["assigned_neurologist_id"] == neurologist_id, (
        "the assignee is retained for audit rather than cleared, got "
        f"{cancelled['assigned_neurologist_id']}"
    )
    assert cancelled["completed_at"] is None, (
        f"a cancellation is not a completion, got {cancelled['completed_at']}"
    )
    assert cancelled["recommendation"] is None
    assert cancelled["accepted_at"] == "2026-09-01T08:16:00Z", (
        "the acceptance that really happened is not rewritten by the cascade"
    )

    released = fx.read_neurologist(neurologist_id)
    assert released["on_call_state"] == "ON_CALL", (
        f"the second hop returns the neurologist to the roster, got {released['on_call_state']}"
    )
    assert released["active_consult_count"] == 0, (
        f"the live load is recomputed downwards, got {released['active_consult_count']}"
    )
    assert released["completed_consult_count"] == 0, (
        "a cancelled consult was not work performed, got "
        f"{released['completed_consult_count']}"
    )
    assert released["last_consult_completed_at"] is None, (
        "no cooldown is started, so the neurologist is immediately routable, got "
        f"{released['last_consult_completed_at']!r}"
    )

    agreement = fx.read_agreement(context["agreement"]["id"])
    assert agreement["active_consult_count"] == 0, (
        f"the contract's live count is recomputed too, got {agreement['active_consult_count']}"
    )
    assert agreement["status"] == "ACTIVE", "the agreement itself is untouched by a case abort"

    origin = fx.read_center(spoke_id)
    assert origin["open_case_count"] == 0, (
        "the third hop exactly compensates the activation increment, got "
        f"{origin['open_case_count']}"
    )
    assert origin["ems_routing_posture"] == "ROUTINE", (
        f"the fourth hop re-derives the posture, got {origin['ems_routing_posture']}"
    )

    assert fx.read_case(case["id"])["deviation_count"] == 0, (
        "an abort does not penalise the facility with a CONSULT_UNFILLED row"
    )
    assert fx.list_case_deviations(case["id"]) == [], (
        "no deviation of any type is synthesised by the abort cascade"
    )


def test_closing_a_case_reconciles_the_center_open_case_ledger_and_posture():
    """Closing the third open case drops the count to 2 and returns the facility to ROUTINE.

    PRD 3.8: "On success the origin facility's `open_case_count` drops by 1 and its `ems_routing_posture` is recomputed, in that order."
    PRD 2.9: "closing the third case drops the count back to 2 and returns the posture to `ROUTINE` inside the very same request"
    PRD 3.8: "Two routes reach it: from `THROMBOLYSIS_ADMINISTERED`, where the `disposition` stays `TREATED_LOCAL`"

    Design: Corner/state_machines/closing_a_case_reconciles_the_center_open_case_ledger_and_posture
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    spoke_id = context["spoke"]["id"]
    built = fx.setup_treated_case(context, door_at, dtn_minutes=40, dti_minutes=20)
    case_id = built["case"]["id"]
    fillers = [fx.activate_case(spoke_id, "2026-09-01T08:45:00Z") for _ in range(2)]

    crowded = fx.read_center(spoke_id)
    assert crowded["open_case_count"] == 3, (
        f"the treated case plus two fresh activations, got {crowded['open_case_count']}"
    )
    assert crowded["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "the threshold is inclusive at three, got "
        f"{crowded['ems_routing_posture']}"
    )
    assert fx.read_consult(built["consult"]["id"])["status"] == "COMPLETED", (
        "the case's only consult is already settled, so nothing holds the case open"
    )

    closed = fx.close_case(case_id, at="2026-09-01T08:50:00Z")

    assert closed["status"] == "CLOSED", (
        f"THROMBOLYSIS_ADMINISTERED closes directly, got {closed['status']}"
    )
    assert closed["disposition"] == "TREATED_LOCAL", (
        f"the locally treated branch is preserved, got {closed['disposition']}"
    )
    assert closed["needle_at"] == "2026-09-01T08:40:00Z", (
        f"the needle instant survives the close, got {closed['needle_at']}"
    )
    assert closed["door_to_needle_minutes"] == 40, (
        f"08:00 to 08:40 is forty whole minutes, got {closed['door_to_needle_minutes']}"
    )

    released = fx.read_center(spoke_id)
    assert released["open_case_count"] == 2, (
        f"exactly one case left the ledger, got {released['open_case_count']}"
    )
    assert released["ems_routing_posture"] == "ROUTINE", (
        "the posture is recomputed after the decrement, inside the same request, got "
        f"{released['ems_routing_posture']}"
    )
    assert released["equipment_readiness_posture"] == "READY", (
        "no equipment flag was involved in the close"
    )

    for filler in fillers:
        still_open = fx.read_case(filler["id"])
        assert still_open["status"] == "ACTIVATED", (
            f"the other open cases are untouched by the close, got {still_open['status']}"
        )
        assert still_open["version"] == 1, (
            f"no sibling case was mutated, got {still_open['version']}"
        )

    live, meta = validate_paginated(
        api_client.list_code_strokes(
            ED, {"center_id": spoke_id, "status": "ACTIVATED", "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        f"two cases remain at ACTIVATED after the close, got {meta['total_count']}"
    )
    assert {row["id"] for row in live} == {filler["id"] for filler in fillers}, (
        "the surviving open cases are exactly the two fillers"
    )
    assert case_id not in {row["id"] for row in live}, (
        "the closed case no longer answers the ACTIVATED filter"
    )


def test_abort_releases_the_destination_only_when_the_transfer_was_accepted():
    """Two aborts cancel two transfers, but only the accepted one gives an open case back.

    PRD 3.7: "when the case is aborted underneath the transfer, both `PROPOSED` and `ACCEPTED` decisions are cancelled with a `cancellation_reason` of 'case aborted' — but only the `ACCEPTED` ones give the destination's `open_case_count` back, since only they ever took it."
    PRD 3.7: "Acceptance is the moment the destination starts carrying the patient: it stamps `accepted_at`, raises the destination's `open_case_count` by 1 and recomputes that facility's `ems_routing_posture`"

    Design: Corner/state_machines/abort_releases_the_destination_only_when_the_transfer_was_accepted
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])

    proposed_case = fx.setup_eligible_case(context, "2026-09-01T08:00:00Z", dti_minutes=20)
    accepted_case = fx.setup_eligible_case(context, "2026-09-01T09:00:00Z", dti_minutes=20)
    never_taken = fx.propose_transfer(
        proposed_case["case"]["id"], destination["id"],
        mode="TRANSFER_ONLY", transport_eta_minutes=35, at="2026-09-01T08:30:00Z",
    )
    taken = fx.propose_transfer(
        accepted_case["case"]["id"], destination["id"],
        mode="TRANSFER_ONLY", transport_eta_minutes=35, at="2026-09-01T09:25:00Z",
    )
    taken = fx.accept_transfer(taken["id"], at="2026-09-01T09:26:00Z")

    assert never_taken["status"] == "PROPOSED", (
        f"the first transfer was never answered, got {never_taken['status']}"
    )
    assert taken["status"] == "ACCEPTED", f"the second was accepted, got {taken['status']}"
    assert taken["accepted_at"] == "2026-09-01T09:26:00Z"
    loaded = fx.read_center(destination["id"])
    assert loaded["open_case_count"] == 1, (
        "only the accepted transfer put a patient on the destination's ledger, got "
        f"{loaded['open_case_count']}"
    )

    fx.abort_case(proposed_case["case"]["id"], at="2026-09-01T09:30:00Z")

    cancelled_proposal = fx.read_transfer(never_taken["id"])
    assert cancelled_proposal["status"] == "CANCELLED", (
        f"a PROPOSED decision is cancelled by the abort, got {cancelled_proposal['status']}"
    )
    assert cancelled_proposal["cancellation_reason"] == "case aborted", (
        f"the reason is the literal 'case aborted', got {cancelled_proposal['cancellation_reason']!r}"
    )
    assert cancelled_proposal["accepted_at"] is None, "it was never accepted"
    unchanged_destination = fx.read_center(destination["id"])
    assert unchanged_destination["open_case_count"] == 1, (
        "cancelling a proposal returns nothing, because a proposal never took anything, got "
        f"{unchanged_destination['open_case_count']}"
    )
    assert fx.read_center(spoke_id)["open_case_count"] == 1, (
        "the origin released only the aborted case"
    )
    assert fx.read_consult(proposed_case["consult"]["id"])["status"] == "COMPLETED", (
        "an already completed consult is not touched by the abort cascade"
    )

    fx.abort_case(accepted_case["case"]["id"], at="2026-09-01T09:35:00Z")

    cancelled_acceptance = fx.read_transfer(taken["id"])
    assert cancelled_acceptance["status"] == "CANCELLED", (
        f"an ACCEPTED decision is cancelled too, got {cancelled_acceptance['status']}"
    )
    assert cancelled_acceptance["cancellation_reason"] == "case aborted", (
        f"the same literal reason is recorded, got {cancelled_acceptance['cancellation_reason']!r}"
    )
    assert cancelled_acceptance["accepted_at"] == "2026-09-01T09:26:00Z", (
        "the acceptance that really happened stays on the record for audit"
    )
    freed = fx.read_center(destination["id"])
    assert freed["open_case_count"] == 0, (
        "the accepted transfer gives its open case back, got "
        f"{freed['open_case_count']}"
    )
    assert freed["ems_routing_posture"] == "ROUTINE", (
        f"the destination's posture is re-derived after the decrement, got {freed['ems_routing_posture']}"
    )
    assert fx.read_center(spoke_id)["open_case_count"] == 0, (
        "both origin increments have now been compensated"
    )
    for aborted in (proposed_case, accepted_case):
        case = fx.read_case(aborted["case"]["id"])
        assert case["status"] == "ABORTED"
        assert case["disposition"] == "NO_TREATMENT", (
            f"the abort overwrites the transfer disposition, got {case['disposition']}"
        )


def test_transfer_acceptance_is_guarded_by_the_live_destination_posture():
    """Acceptance re-reads the destination while the frozen snapshot keeps its old value.

    PRD 3.7: "so a destination that degrades or loses its certification between proposal and acceptance blocks the acceptance with `ERR_DESTINATION_BYPASS`"
    PRD 3.7: "but `destination_posture_at_proposal` keeps the value it was frozen with, and `congestion_factor`, `adjusted_transport_minutes` and `projected_door_in_door_out_minutes` all keep the figures derived from it"
    PRD 2.9: "The posture is `BYPASS` if the facility's `certification_status` is `SUSPENDED` or `WITHDRAWN`, or if its `equipment_readiness_posture` is `OFFLINE`."

    Design: Corner/state_machines/transfer_acceptance_is_guarded_by_the_live_destination_posture
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    destination = fx.register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    built = fx.setup_eligible_case(context, "2026-09-01T08:00:00Z", dti_minutes=20)
    case_id = built["case"]["id"]

    transfer = fx.propose_transfer(
        case_id, destination["id"],
        mode="TRANSFER_ONLY", transport_eta_minutes=40, at="2026-09-01T08:30:00Z",
    )
    assert transfer["destination_posture_at_proposal"] == "ROUTINE", (
        f"the destination was routine at proposal, got {transfer['destination_posture_at_proposal']}"
    )
    assert transfer["adjusted_transport_minutes"] == 40
    assert transfer["projected_door_in_door_out_minutes"] == 60, (
        "40 of transport plus 20 of preparation, got "
        f"{transfer['projected_door_in_door_out_minutes']}"
    )

    offline = fx.take_center_offline(destination["id"])
    assert offline["equipment_readiness_posture"] == "OFFLINE", (
        f"both flags are down, got {offline['equipment_readiness_posture']}"
    )
    assert offline["ems_routing_posture"] == "BYPASS", (
        f"an offline facility is bypassed outright, got {offline['ems_routing_posture']}"
    )

    fx.set_clock("2026-09-01T08:40:00Z")
    response = api_client.accept_transfer(transfer["id"], TRANSFER)
    validate_error(response, ApiErrorId.ERR_DESTINATION_BYPASS.value, 409)

    blocked = fx.read_transfer(transfer["id"])
    assert blocked["status"] == "PROPOSED", (
        f"the refused acceptance leaves the decision open, got {blocked['status']}"
    )
    assert blocked["accepted_at"] is None, (
        f"no acceptance instant is stamped, got {blocked['accepted_at']}"
    )
    assert blocked["destination_posture_at_proposal"] == "ROUTINE", (
        "the snapshot never refreshes, not even on a failed acceptance, got "
        f"{blocked['destination_posture_at_proposal']}"
    )
    assert blocked["congestion_factor"] == 1.00, (
        f"the factor derived from the snapshot is kept, got {blocked['congestion_factor']}"
    )
    assert blocked["adjusted_transport_minutes"] == 40
    assert blocked["projected_door_in_door_out_minutes"] == 60
    assert fx.read_center(destination["id"])["open_case_count"] == 0, (
        "a refused acceptance takes no patient onto the destination's ledger"
    )
    assert fx.read_case(case_id)["status"] == "TRANSFER_INITIATED", (
        "the case is still waiting on the same proposal"
    )

    fx.attest_readiness(destination["id"], "CT_SCANNER", "PASS")
    recovered = fx.attest_readiness(destination["id"], "VIDEO_CART", "PASS")
    assert recovered["ems_routing_posture"] == "ROUTINE", (
        f"the destination is routable again, got {recovered['ems_routing_posture']}"
    )

    accepted = fx.accept_transfer(transfer["id"], at="2026-09-01T08:50:00Z")
    assert accepted["status"] == "ACCEPTED", (
        f"the live posture now passes the guard, got {accepted['status']}"
    )
    assert accepted["accepted_at"] == "2026-09-01T08:50:00Z", (
        f"acceptance is stamped from the logical clock, got {accepted['accepted_at']}"
    )
    assert accepted["destination_posture_at_proposal"] == "ROUTINE", (
        "the snapshot is still the proposal-time value, not a fresh read"
    )
    assert accepted["projected_door_in_door_out_minutes"] == 60, (
        "the projection is never recomputed at acceptance, got "
        f"{accepted['projected_door_in_door_out_minutes']}"
    )
    assert fx.read_center(destination["id"])["open_case_count"] == 1, (
        "acceptance is the moment the destination starts carrying the patient"
    )


def test_deviation_review_loops_between_under_review_and_returned_for_info():
    """Start, return, resubmit, return, resubmit walks review_round from 0 to 3 one entry at a time.

    PRD 3.8: "A reviewer starts the review of an `OPEN` deviation, which moves it to `UNDER_REVIEW`, raises `review_round` to 1 and records `reviewed_by_user_id`."
    PRD 3.8: "the abstractor then supplies `additional_info` to push it back to `UNDER_REVIEW`, raising `review_round` by 1 each time"
    PRD 2.5: "increments by exactly 1 on every mutation of that record"

    Design: Corner/state_machines/deviation_review_loops_between_under_review_and_returned_for_info
    """
    case, deviation, rounds = _looped_deviation()
    entered, returned_once, second_entry, returned_twice, third_entry = rounds

    assert entered["status"] == "UNDER_REVIEW", (
        f"OPEN -> UNDER_REVIEW is the entry transition, got {entered['status']}"
    )
    assert entered["review_round"] == 1, (
        f"entering review raises the round to 1, got {entered['review_round']}"
    )
    assert entered["reviewed_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID, (
        f"the reviewer's identity header is recorded, got {entered['reviewed_by_user_id']!r}"
    )
    assert entered["version"] == 2, (
        f"one mutation since creation, got {entered['version']}"
    )

    assert returned_once["status"] == "RETURNED_FOR_INFO", (
        f"the reviewer pushes it back for more information, got {returned_once['status']}"
    )
    assert returned_once["review_round"] == 1, (
        "the return itself is not an entry into review, so the round holds at 1, got "
        f"{returned_once['review_round']}"
    )
    assert returned_once["version"] == 3

    assert second_entry["status"] == "UNDER_REVIEW", (
        f"the resubmission re-enters review, got {second_entry['status']}"
    )
    assert second_entry["review_round"] == 2, (
        f"each re-entry raises the round by exactly 1, got {second_entry['review_round']}"
    )
    assert second_entry["version"] == 4

    assert returned_twice["status"] == "RETURNED_FOR_INFO"
    assert returned_twice["review_round"] == 2, (
        f"the second return again leaves the round alone, got {returned_twice['review_round']}"
    )

    assert third_entry["status"] == "UNDER_REVIEW", (
        f"the third entry is still permitted from a round of 2, got {third_entry['status']}"
    )
    assert third_entry["review_round"] == 3, (
        f"the loop has now reached its ceiling value, got {third_entry['review_round']}"
    )
    assert third_entry["version"] == 6, (
        "five successive lifecycle writes over the creating one, got "
        f"{third_entry['version']}"
    )
    assert third_entry["reviewed_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID, (
        "the reviewer identity survives the round trips"
    )
    assert third_entry["debrief_completed"] is False, (
        "no debrief has been recorded anywhere in the loop, got "
        f"{third_entry['debrief_completed']}"
    )
    assert third_entry["source"] == "MANUAL"
    assert third_entry["severity"] == "MAJOR"
    assert fx.read_case(case["id"])["deviation_count"] == 1, (
        "walking the loop creates no further deviations"
    )
    assert deviation["review_round"] == 0, (
        "the create response captured the row before any review began"
    )


def test_the_review_loop_refuses_a_return_for_info_once_the_round_ceiling_is_reached():
    """At review_round 3 the loop is closed: a further return-for-info is refused.

    PRD 3.8: "The loop terminates because entering review requires `review_round` to be below 3: the fourth entry attempt is refused with `ERR_REVIEW_ROUND_LIMIT`, and so is a return-for-info once `review_round` has already reached 3."

    Design: Corner/state_machines/deviation_review_loops_between_under_review_and_returned_for_info
    """
    case, deviation, rounds = _looped_deviation()
    at_ceiling = rounds[-1]
    assert at_ceiling["status"] == "UNDER_REVIEW"
    assert at_ceiling["review_round"] == 3, (
        f"the loop is parked at its ceiling, got {at_ceiling['review_round']}"
    )

    response = api_client.return_deviation_for_info(
        deviation["id"], f.return_for_info_payload(), REVIEWER
    )
    error = validate_error(response, ApiErrorId.ERR_REVIEW_ROUND_LIMIT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_DEVIATION_STATE.value, (
        "UNDER_REVIEW is a legal state for a return; it is the round ceiling that bites, got "
        f"{error['error_id']}"
    )

    unchanged = fx.list_case_deviations(case["id"])[0]
    assert unchanged["status"] == "UNDER_REVIEW", (
        f"the refused return leaves the deviation under review, got {unchanged['status']}"
    )
    assert unchanged["review_round"] == 3, (
        f"the round never moves past 3, got {unchanged['review_round']}"
    )
    assert unchanged["version"] == at_ceiling["version"], (
        f"a rejected write is not a mutation, got {unchanged['version']}"
    )
    assert unchanged["debrief_completed"] is False
