"""State-machine transitions, guards and terminal-state lockdowns across cases, allergy panels, endoscopes, extract vials, doses, blocks and bookings."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def test_a_new_sinuplasty_case_opens_in_draft_with_undetermined_candidacy(api):
    """PRD 3.6: "The new case is created in status `DRAFT` with `candidacy_status`
    `UNDETERMINED`, `revision_round` 0, `authorized_device_count` 0,
    `criteria_met_count` 0, `contiguous_management_days` 0,
    `cumulative_management_days` 0, and `pinned_policy_version`,
    `auth_expires_at`, `payer_reference`, `submitted_by_user_id` and
    `documented_by_user_id` all null."

    Design: Corner/state_machines/sinuplasty_case_starts_in_draft_with_undetermined_candidacy
    """
    # A prior-authorization plan carrying one adult chart.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMA-2999",
        patient_mrn=C.mrn(10201),
        policy_overrides={"payer_name": "Draft Mutual", "requires_prior_auth": True},
        patient_overrides={
            "full_name": "Iris Cole",
            "date_of_birth": "1970-04-04",
            "epinephrine_on_file": True,
        },
    )

    # The otolaryngologist opens the case and nothing else happens to it.
    response = api.create_sinuplasty_case(
        F.sinuplasty_case_payload(
            base["patient"]["id"],
            laterality=C.LATERALITY_BILATERAL,
            sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
        ),
        USERS.ENT_1,
    )
    case = validate_success(response, 201)

    # Every opening value the contract fixes at creation.
    check.assert_sinuplasty_case(
        case,
        status=C.CASE_DRAFT,
        candidacy_status=C.CANDIDACY_UNDETERMINED,
        revision_round=0,
        authorized_device_count=0,
        criteria_met_count=0,
        contiguous_management_days=0,
        cumulative_management_days=0,
        pinned_policy_version=None,
        auth_expires_at=None,
        payer_reference=None,
        submitted_by_user_id=None,
        documented_by_user_id=None,
    )


def test_a_bilateral_case_over_two_sinuses_plans_four_devices(api):
    """PRD 3.6: "From those two inputs the server derives `planned_device_count`:
    the number of sinuses listed, doubled when `laterality` is `BILATERAL` and
    taken as-is otherwise."

    Design: Corner/state_machines/sinuplasty_case_starts_in_draft_with_undetermined_candidacy
    """
    # One plan, one adult chart under it.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMA-2999",
        patient_mrn=C.mrn(10201),
        policy_overrides={"payer_name": "Draft Mutual", "requires_prior_auth": True},
        patient_overrides={
            "full_name": "Iris Cole",
            "date_of_birth": "1970-04-04",
            "epinephrine_on_file": True,
        },
    )

    # Two sinuses dilated bilaterally.
    response = api.create_sinuplasty_case(
        F.sinuplasty_case_payload(
            base["patient"]["id"],
            laterality=C.LATERALITY_BILATERAL,
            sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
        ),
        USERS.ENT_1,
    )
    case = validate_success(response, 201)

    # Two sinuses doubled by the bilateral laterality.
    check.assert_sinuplasty_case(
        case,
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
        planned_device_count=4,
    )


def test_a_prior_authorization_plan_fixes_the_strict_evaluation_variant(api):
    """PRD 3.6: "Its `evaluation_variant` is fixed from the patient's plan at
    creation: `POLICY_STRICT` when the plan's `requires_prior_auth` is true,
    `CLINICAL_BROAD` when it is false."

    Design: Corner/state_machines/sinuplasty_case_starts_in_draft_with_undetermined_candidacy
    """
    # The plan demands prior authorization.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMA-2999",
        patient_mrn=C.mrn(10201),
        policy_overrides={"payer_name": "Draft Mutual", "requires_prior_auth": True},
        patient_overrides={
            "full_name": "Iris Cole",
            "date_of_birth": "1970-04-04",
            "epinephrine_on_file": True,
        },
    )
    check.assert_payer_policy(base["policy"], requires_prior_auth=True)

    # A case opened under that plan.
    case = SETUP.create_case(
        api,
        base["patient"]["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
    )

    # The variant is already fixed on the freshly minted row.
    check.assert_sinuplasty_case(
        case,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        candidacy_status=C.CANDIDACY_UNDETERMINED,
    )


def test_the_submission_stamps_the_filing_liaison_and_pins_the_plan_version(api):
    """PRD 3.6: "Every submission, whichever origin it came from, stamps
    `submitted_by_user_id` from the acting identifier and stamps
    `pinned_policy_version` with the plan's `version` **as read at that
    instant**."

    Design: Corner/state_machines/payer_approval_authorizes_case_with_capped_device_count
    """
    # A plan requiring prior authorization, with its balloon ceiling at two.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMB-2999",
        patient_mrn=C.mrn(10202),
        policy_overrides={
            "payer_name": "Broad Approve",
            "requires_prior_auth": True,
            "max_balloon_devices": 2,
            "auth_validity_days": 90,
            "min_documented_criteria": 3,
            "min_medical_management_days": 28,
        },
        patient_overrides={
            "full_name": "Omar Blake",
            "date_of_birth": "1968-09-12",
            "epinephrine_on_file": True,
        },
    )

    # A bilateral two-sinus case documented so that candidacy lands on ELIGIBLE.
    case = SETUP.eligible_documented_case(
        api,
        base["patient"]["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
    )
    check.assert_sinuplasty_case(
        case,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        planned_device_count=4,
    )

    # The first payer liaison files the submission.
    response = api.submit_authorization(case["id"], USERS.LIAISON_1)
    submitted = check.validate_unpaginated(response)

    check.assert_sinuplasty_case(
        submitted,
        status=C.CASE_AUTH_SUBMITTED,
        submitted_by_user_id=C.USER_LIAISON_1,
        pinned_policy_version=1,
        revision_round=0,
    )


def test_payer_approval_caps_the_authorized_device_count_at_the_plan_ceiling(api):
    """PRD 3.6: "`APPROVED` moves the case `AUTH_SUBMITTED → AUTHORIZED`, sets
    `authorized_device_count` to whichever is smaller of the case's
    `planned_device_count` and the plan's `max_balloon_devices`, and sets
    `auth_expires_at` to the current logical-clock instant advanced by the plan's
    `auth_validity_days` whole days."

    Design: Corner/state_machines/payer_approval_authorizes_case_with_capped_device_count
    """
    # A plan whose ceiling of two sits below the four devices this case plans.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMB-2999",
        patient_mrn=C.mrn(10202),
        policy_overrides={
            "payer_name": "Broad Approve",
            "requires_prior_auth": True,
            "max_balloon_devices": 2,
            "auth_validity_days": 90,
            "min_documented_criteria": 3,
            "min_medical_management_days": 28,
        },
        patient_overrides={
            "full_name": "Omar Blake",
            "date_of_birth": "1968-09-12",
            "epinephrine_on_file": True,
        },
    )
    case = SETUP.eligible_documented_case(
        api,
        base["patient"]["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
    )
    SETUP.submit_case(api, case["id"], headers=USERS.LIAISON_1)

    # The second liaison records the payer's approval.
    response = api.record_payer_decision(
        case["id"],
        F.payer_decision_payload("PA-77001", decision=C.DECISION_APPROVED),
        USERS.LIAISON_2,
    )
    authorized = check.validate_unpaginated(response)

    # Four planned devices capped to the plan's two, dated ninety whole days out.
    check.assert_sinuplasty_case(
        authorized,
        status=C.CASE_AUTHORIZED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        planned_device_count=4,
        authorized_device_count=2,
        payer_reference="PA-77001",
        pinned_policy_version=1,
    )
    check.assert_instant_equals(authorized["auth_expires_at"], "2026-10-30T00:00:00Z")


def test_closing_a_block_leaves_its_scheduled_booking_holding_its_slot(api):
    """PRD 3.9: "`CLOSED` is terminal: no booking may be created against a closed
    block, but bookings already `SCHEDULED` inside it keep their slots and may
    still be started and completed normally."

    Design: Corner/state_machines/block_close_rejects_further_bookings_and_keeps_scheduled_slots
    """
    # One plan, one adult chart.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMC-2999",
        patient_mrn=C.mrn(10203),
        policy_overrides={"payer_name": "Block Mutual"},
        patient_overrides={
            "full_name": "Nia Frost",
            "date_of_birth": "1994-06-06",
            "epinephrine_on_file": True,
        },
    )

    # A four-hour block over two rooms, with one two-hour case inside it.
    block = SETUP.publish_block(
        api,
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        max_concurrent_cases=2,
        center_name="Northside Surgery Center",
    )
    booking = SETUP.create_booking(
        api,
        base["patient"]["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T11:00:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block["id"],
    )
    check.assert_procedure_booking(
        booking, status=C.BOOKING_SCHEDULED, duration_minutes=120
    )

    # The administrator closes the block.
    response = api.close_surgery_center_block(block["id"], USERS.ADMIN_1)
    closed = check.validate_unpaginated(response)

    # The block is terminal, yet every aggregate the booking contributed stands.
    check.assert_surgery_center_block(
        closed,
        status=C.BLOCK_CLOSED,
        booked_case_count=1,
        booked_minutes=120,
        capacity_minutes=480,
        utilization_bps=2500,
    )

    # The scheduled case still holds its slot.
    check.assert_procedure_booking(
        SETUP.read_booking(api, booking["id"]),
        status=C.BOOKING_SCHEDULED,
        surgery_center_block_id=block["id"],
    )


def test_no_booking_may_be_created_against_a_closed_block(api):
    """PRD 3.9: "And a booking against a block whose status is `FULL` or `CLOSED`
    is refused with `ERR_BLOCK_NOT_OPEN`."

    Design: Corner/state_machines/block_close_rejects_further_bookings_and_keeps_scheduled_slots
    """
    # One plan, one adult chart, one block with a single case already inside it.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMC-2999",
        patient_mrn=C.mrn(10203),
        policy_overrides={"payer_name": "Block Mutual"},
        patient_overrides={
            "full_name": "Nia Frost",
            "date_of_birth": "1994-06-06",
            "epinephrine_on_file": True,
        },
    )
    block = SETUP.publish_block(
        api,
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        max_concurrent_cases=2,
        center_name="Northside Surgery Center",
    )
    SETUP.create_booking(
        api,
        base["patient"]["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T11:00:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block["id"],
    )
    SETUP.close_block(api, block["id"])

    # A second case, well inside the remaining capacity, is offered to the block.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            base["patient"]["id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
            procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
            venue=C.VENUE_SURGERY_CENTER,
            surgery_center_block_id=block["id"],
        ),
        USERS.ADMIN_1,
    )
    validate_error(response, ApiErrorId.BLOCK_NOT_OPEN.value)

    # Nothing was booked by the refused request.
    check.assert_surgery_center_block(
        SETUP.read_block(api, block["id"]),
        status=C.BLOCK_CLOSED,
        booked_case_count=1,
        booked_minutes=120,
    )


def test_administering_an_already_administered_panel_is_refused(api):
    """PRD 3.2: "Administering the panel is an `AllergyNurse` action carrying no
    request body, and it is only available on the skin arm: the order must still
    be `ORDERED` and its `method` must be either `SKIN_PRICK` or `INTRADERMAL`,
    or the request is refused with `ERR_ORDER_STATE_INVALID`."

    Design: Corner/state_machines/administer_twice_returns_order_state_invalid
    """
    # One plan, one adult chart, one skin panel already administered at midnight.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMD-2999",
        patient_mrn=C.mrn(10204),
        policy_overrides={"payer_name": "Idem Mutual"},
        patient_overrides={
            "full_name": "Ravi Shaw",
            "date_of_birth": "1983-12-30",
            "epinephrine_on_file": True,
        },
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )
    check.assert_allergy_test_order(order, status=C.ORDER_ADMINISTERED)

    # Twenty minutes later a second nurse tries to administer the same panel.
    SETUP.set_clock(api, "2026-08-01T00:20:00Z")
    response = api.administer_allergy_test_order(order["id"], USERS.NURSE_2)
    validate_error(response, ApiErrorId.ORDER_STATE_INVALID.value)

    # The first administration's stamps are untouched by the refused repeat.
    refreshed = SETUP.read_order(api, order["id"])
    check.assert_allergy_test_order(
        refreshed,
        status=C.ORDER_ADMINISTERED,
        administered_by_user_id=C.USER_NURSE_1,
        observation_required_minutes=30,
    )
    check.assert_instant_equals(refreshed["administered_at"], "2026-08-01T00:00:00Z")


def test_a_reading_on_a_panel_that_was_never_administered_is_refused(api):
    """PRD 3.3: "In either case, an order in any other status is refused with
    `ERR_ORDER_STATE_INVALID`."

    Design: Corner/state_machines/readings_on_ordered_order_returns_order_state_invalid
    """
    # One plan, one adult chart, one panel left sitting in ORDERED.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SME-2999",
        patient_mrn=C.mrn(10205),
        policy_overrides={"payer_name": "Invalid From"},
        patient_overrides={
            "full_name": "Cleo Marsh",
            "date_of_birth": "1977-05-05",
            "epinephrine_on_file": True,
        },
    )
    order = SETUP.create_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    # A reading is offered against a panel nobody has administered.
    response = api.record_allergy_test_reading(
        order["id"], F.allergy_reading_payload(4), USERS.NURSE_1
    )
    validate_error(response, ApiErrorId.ORDER_STATE_INVALID.value)

    # Nothing was read and nothing was billed.
    check.assert_allergy_test_order(
        SETUP.read_order(api, order["id"]),
        status=C.ORDER_ORDERED,
        billed_units=0,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
        positive_antigen_count=0,
    )

    # The chart never learned of a sensitization.
    check.assert_patient(
        SETUP.read_patient(api, base["patient"]["id"]),
        sensitized_antigen_count=0,
        risk_score=5,
    )


def test_converting_an_administered_panel_to_serum_is_refused(api):
    """PRD 3.2: "The order must be `ORDERED` and its `method` must not already be
    `SERUM_IGE`, or the conversion is refused with `ERR_ORDER_STATE_INVALID`."

    Design: Corner/state_machines/readings_on_ordered_order_returns_order_state_invalid
    """
    # One plan, one adult chart, one venom panel already administered.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SME-2999",
        patient_mrn=C.mrn(10205),
        policy_overrides={"payer_name": "Invalid From"},
        patient_overrides={
            "full_name": "Cleo Marsh",
            "date_of_birth": "1977-05-05",
            "epinephrine_on_file": True,
        },
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_VENOM_5,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    # The serum arm is offered a panel that has already been put on the skin.
    response = api.convert_allergy_test_order_to_serum(order["id"], USERS.NURSE_1)
    validate_error(response, ApiErrorId.ORDER_STATE_INVALID.value)

    # The conversion did not partially apply.
    check.assert_allergy_test_order(
        SETUP.read_order(api, order["id"]),
        status=C.ORDER_ADMINISTERED,
        method=C.METHOD_SKIN_PRICK,
        panel_code=C.PANEL_VENOM_5,
        billed_units=0,
    )


def test_opening_a_reprocessing_run_on_a_ready_scope_is_refused(api):
    """PRD 3.8: "The scope must be `SOILED` or `QUARANTINED`, or the request is
    refused with `ERR_SCOPE_STATE_INVALID`; and when the scope is `QUARANTINED`,
    its `consecutive_mec_failures` must be strictly below 2, which is what makes a
    retired scope's quarantine irreversible rather than retryable."

    Design: Corner/state_machines/reprocessing_start_on_ready_scope_returns_scope_state_invalid
    """
    # A scope fresh from the register, therefore READY with no history at all.
    scope = SETUP.register_scope(api, serial=C.scope_serial(6), model="Rhino-Fiber 4")
    check.assert_endoscope(scope, status=C.SCOPE_READY, cycle_count=0)

    # The technician tries to disinfect a scope that has not been soiled.
    response = api.start_reprocessing(scope["id"], USERS.TECH_1)
    validate_error(response, ApiErrorId.SCOPE_STATE_INVALID.value)

    # No run was opened on it.
    check.assert_endoscope(
        SETUP.read_scope(api, scope["id"]),
        status=C.SCOPE_READY,
        cycle_count=0,
        consecutive_mec_failures=0,
        last_reprocessed_at=None,
        hld_expires_at=None,
        reprocessing_started_by_user_id=None,
    )


def test_closing_a_reprocessing_run_on_a_ready_scope_is_refused(api):
    """PRD 3.8: "The scope must be `REPROCESSING`, or the completion is refused
    with `ERR_SCOPE_STATE_INVALID`, and the acting identifier must equal
    `reprocessing_started_by_user_id`, or the completion is refused with
    `ERR_REPROCESSING_TECH_MISMATCH`."

    Design: Corner/state_machines/reprocessing_start_on_ready_scope_returns_scope_state_invalid
    """
    # A scope fresh from the register, therefore READY.
    scope = SETUP.register_scope(api, serial=C.scope_serial(6), model="Rhino-Fiber 4")

    # The technician tries to close a run that was never opened.
    response = api.complete_reprocessing(
        scope["id"], F.reprocessing_completion_payload(True), USERS.TECH_1
    )
    validate_error(response, ApiErrorId.SCOPE_STATE_INVALID.value)

    # The cycle counter never moved.
    check.assert_endoscope(
        SETUP.read_scope(api, scope["id"]),
        status=C.SCOPE_READY,
        cycle_count=0,
        consecutive_mec_failures=0,
        mec_test_due=False,
        last_reprocessed_at=None,
        hld_expires_at=None,
        reprocessing_started_by_user_id=None,
    )


def test_a_systemic_reaction_aborts_the_panel_and_zeroes_its_billing(api):
    """PRD 3.4: "**On an allergy test order** that is currently `ADMINISTERED`,
    the order takes the branch `ADMINISTERED → ABORTED` with `abort_reason` set to
    `SYSTEMIC_REACTION`, and its `practice_charge_cents` and
    `patient_responsibility_cents` are forced to 0 — a panel that put the patient
    into a systemic reaction is not billed."

    Design: Corner/state_machines/terminal_aborted_order_accepts_no_further_transitions
    """
    # One plan, one adult chart with epinephrine on file, one administered panel.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMF-2999",
        patient_mrn=C.mrn(10206),
        policy_overrides={"payer_name": "Terminal Mutual"},
        patient_overrides={
            "full_name": "Vera Lund",
            "date_of_birth": "1986-08-08",
            "epinephrine_on_file": True,
        },
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    # A grade-two systemic reaction is documented against that panel.
    SETUP.record_reaction(
        api,
        2,
        8,
        order_id=order["id"],
        local_wheal_mm=30.0,
        epinephrine_given=True,
    )

    # The panel is aborted and carries no charge at all.
    check.assert_allergy_test_order(
        SETUP.read_order(api, order["id"]),
        status=C.ORDER_ABORTED,
        abort_reason=C.ABORT_REASON_SYSTEMIC_REACTION,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
        billed_units=0,
    )


def test_the_reaction_flips_the_chart_onto_the_post_reaction_variant(api):
    """PRD 3.4: "A second hop, caused by that abort rather than by the request,
    flips the patient's `risk_score_variant` to `POST_REACTION` and recomputes
    `risk_score` under that variant, which now includes the decayed event term of
    §3.1."

    Design: Corner/state_machines/terminal_aborted_order_accepts_no_further_transitions
    """
    # One plan, one adult chart with no reaction history, one administered panel.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMF-2999",
        patient_mrn=C.mrn(10206),
        policy_overrides={"payer_name": "Terminal Mutual"},
        patient_overrides={
            "full_name": "Vera Lund",
            "date_of_birth": "1986-08-08",
            "epinephrine_on_file": True,
        },
    )
    check.assert_patient(
        base["patient"],
        risk_score=5,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    # A grade-two systemic reaction is documented against that panel.
    SETUP.record_reaction(
        api,
        2,
        8,
        order_id=order["id"],
        local_wheal_mm=30.0,
        epinephrine_given=True,
    )

    # The chart is rescored under the post-reaction variant and stays STANDARD.
    check.assert_patient(
        SETUP.read_patient(api, base["patient"]["id"]),
        risk_score_variant=C.RISK_VARIANT_POST_REACTION,
        risk_score=45,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )


def test_a_terminal_aborted_panel_accepts_no_further_transition(api):
    """PRD 3.3: "Both `READ` and `ABORTED` are terminal: nothing further can be
    done to the order."

    Design: Corner/state_machines/terminal_aborted_order_accepts_no_further_transitions
    """
    # One administered panel driven to ABORTED by a grade-two reaction.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMF-2999",
        patient_mrn=C.mrn(10206),
        policy_overrides={"payer_name": "Terminal Mutual"},
        patient_overrides={
            "full_name": "Vera Lund",
            "date_of_birth": "1986-08-08",
            "epinephrine_on_file": True,
        },
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )
    SETUP.record_reaction(
        api,
        2,
        8,
        order_id=order["id"],
        local_wheal_mm=30.0,
        epinephrine_given=True,
    )
    check.assert_allergy_test_order(
        SETUP.read_order(api, order["id"]), status=C.ORDER_ABORTED
    )

    # Each of the order's three triggers is offered to the terminal row.
    validate_error(
        api.administer_allergy_test_order(order["id"], USERS.NURSE_1),
        ApiErrorId.ORDER_STATE_INVALID.value,
    )
    validate_error(
        api.record_allergy_test_reading(
            order["id"], F.allergy_reading_payload(2), USERS.NURSE_1
        ),
        ApiErrorId.ORDER_STATE_INVALID.value,
    )
    validate_error(
        api.convert_allergy_test_order_to_serum(order["id"], USERS.NURSE_1),
        ApiErrorId.ORDER_STATE_INVALID.value,
    )

    # The terminal row is exactly as the abort left it.
    check.assert_allergy_test_order(
        SETUP.read_order(api, order["id"]),
        status=C.ORDER_ABORTED,
        abort_reason=C.ABORT_REASON_SYSTEMIC_REACTION,
        method=C.METHOD_SKIN_PRICK,
        positive_antigen_count=0,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
    )


def test_clearing_a_dose_before_its_window_has_elapsed_is_refused(api):
    """PRD 3.5: "At least `observation_required_minutes` whole minutes must have
    elapsed since `administered_at`, or it is refused with
    `ERR_OBSERVATION_NOT_COMPLETE`."

    Design: Corner/state_machines/clear_observation_before_window_returns_observation_not_complete
    """
    # One plan, one adult chart, one label-verified vial of five millilitres.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="SMG-2999",
        patient_mrn=C.mrn(10207),
        policy_overrides={"payer_name": "Observe Mutual"},
        patient_overrides={
            "full_name": "Sol Adeyemi",
            "date_of_birth": "1984-01-21",
            "epinephrine_on_file": True,
        },
        volume_ml_initial=5.00,
    )

    # The first dose is drawn at midnight and owes thirty minutes of watching.
    dose = SETUP.administer_dose(api, base["vial"]["id"])
    check.assert_immunotherapy_dose(
        dose,
        status=C.DOSE_ADMINISTERED,
        escalation_step_at_dose=1,
        gap_days_at_dose=0,
        observation_required_minutes=30,
        observation_cleared_at=None,
    )
    check.assert_volume_ml(dose["volume_ml"], 0.05)

    # Ten minutes in, the nurse tries to discharge the patient.
    SETUP.set_clock(api, "2026-08-01T00:10:00Z")
    response = api.clear_dose_observation(dose["id"], USERS.NURSE_1)
    validate_error(response, ApiErrorId.OBSERVATION_NOT_COMPLETE.value)
    check.assert_immunotherapy_dose(
        SETUP.read_dose(api, dose["id"]),
        status=C.DOSE_ADMINISTERED,
        observation_cleared_at=None,
    )

    # At exactly thirty minutes the same call is admissible.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    cleared = check.validate_unpaginated(
        api.clear_dose_observation(dose["id"], USERS.NURSE_1)
    )
    check.assert_immunotherapy_dose(cleared, status=C.DOSE_CLEARED)
    check.assert_instant_equals(cleared["observation_cleared_at"], "2026-08-01T00:30:00Z")


def test_clearing_an_already_cleared_dose_is_refused(api):
    """PRD 3.5: "The dose must be `ADMINISTERED`, or the clearance is refused with
    `ERR_DOSE_STATE_INVALID`."

    Design: Corner/state_machines/clear_observation_before_window_returns_observation_not_complete
    """
    # One label-verified vial and one dose whose window has already been closed.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="SMG-2999",
        patient_mrn=C.mrn(10207),
        policy_overrides={"payer_name": "Observe Mutual"},
        patient_overrides={
            "full_name": "Sol Adeyemi",
            "date_of_birth": "1984-01-21",
            "epinephrine_on_file": True,
        },
        volume_ml_initial=5.00,
    )
    dose = SETUP.administer_dose(api, base["vial"]["id"])
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    SETUP.clear_dose(api, dose["id"])

    # The clearance is offered a second time.
    response = api.clear_dose_observation(dose["id"], USERS.NURSE_1)
    validate_error(response, ApiErrorId.DOSE_STATE_INVALID.value)

    # The discharge instant is unchanged by the refused repeat.
    refreshed = SETUP.read_dose(api, dose["id"])
    check.assert_immunotherapy_dose(refreshed, status=C.DOSE_CLEARED)
    check.assert_instant_equals(
        refreshed["observation_cleared_at"], "2026-08-01T00:30:00Z"
    )


def test_compounding_a_second_vial_supersedes_the_first_and_wastes_its_remainder(api):
    """PRD 3.5: "Compounding also **supersedes**: if that patient already holds a
    vial in status `LABEL_VERIFIED` or `IN_USE`, that older vial is moved to
    `DISCARDED` with `discard_reason` `SUPERSEDED`, its `volume_ml_remaining` is
    moved into `volume_ml_wasted` and its `volume_ml_remaining` is set to 0.00,
    leaving the ledger identity of §2.10 intact."

    Design: Corner/state_machines/new_vial_supersedes_previous_vial_with_wasted_volume
    """
    # A verified five-millilitre vial with exactly one dose drawn from it.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="SMH-2999",
        patient_mrn=C.mrn(10208),
        policy_overrides={"payer_name": "Supersede Mutual"},
        patient_overrides={
            "full_name": "Pia Novak",
            "date_of_birth": "1990-10-10",
            "epinephrine_on_file": True,
        },
        volume_ml_initial=5.00,
    )
    dose = SETUP.administer_dose(api, base["vial"]["id"])
    in_use = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_immunotherapy_vial(in_use, status=C.VIAL_IN_USE)
    check.assert_volume_ml(in_use["volume_ml_remaining"], 4.95)

    # The nurse compounds a fresh vial for the same patient.
    version_before = SETUP.patient_version(api, base["patient"]["id"])
    response = api.create_immunotherapy_vial(
        F.immunotherapy_vial_payload(
            base["patient"]["id"],
            base["lot"]["id"],
            base["patient"]["mrn"],
            version_before,
            SETUP.VIAL_EXPIRY_DEFAULT,
            dilution_code=C.DILUTION_BLUE,
            volume_ml_initial=5.00,
        ),
        USERS.NURSE_1,
    )
    replacement = validate_success(response, 201)

    # The replacement opens full and untouched.
    check.assert_immunotherapy_vial(
        replacement,
        status=C.VIAL_MIXED,
        discard_reason=None,
        label_text=C.make_label_text(
            base["patient"]["mrn"], C.DILUTION_BLUE, SETUP.VIAL_EXPIRY_DEFAULT
        ),
    )
    check.assert_volume_ml(replacement["volume_ml_remaining"], 5.00)
    check.assert_volume_ml(replacement["volume_ml_wasted"], 0.00)

    # The older vial is discarded and its whole remainder is booked as waste.
    superseded = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_immunotherapy_vial(
        superseded,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_SUPERSEDED,
    )
    check.assert_volume_ml(superseded["volume_ml_remaining"], 0.00)
    check.assert_volume_ml(superseded["volume_ml_dispensed_total"], 0.05)
    check.assert_volume_ml(superseded["volume_ml_wasted"], 4.95)

    # The dose the old vial fed is untouched, and the chart's version moved once.
    check.assert_immunotherapy_dose(
        SETUP.read_dose(api, dose["id"]), status=C.DOSE_ADMINISTERED
    )
    check.assert_patient(
        SETUP.read_patient(api, base["patient"]["id"]), version=version_before + 1
    )


def test_a_failed_disinfection_run_quarantines_the_scope_without_crediting_a_cycle(api):
    """PRD 3.8: "Hop one: the scope moves `REPROCESSING → QUARANTINED`,
    `consecutive_mec_failures` increments by one, `reprocessing_started_by_user_id`
    is cleared to null, and `cycle_count` is deliberately **not** incremented,
    because a failed run disinfected nothing."

    Design: Corner/state_machines/scope_retirement_flags_scheduled_bookings
    """
    # One chart and one freshly registered scope, soiled by a completed endoscopy.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMI-2999",
        patient_mrn=C.mrn(10210),
        policy_overrides={"payer_name": "Sterile Mutual"},
        patient_overrides={
            "full_name": "Cato Ferreira",
            "date_of_birth": "1979-03-03",
        },
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(10), model="Rhino-Fiber 7")
    soiled = SETUP.soil_scope(api, scope["id"], base["patient"]["id"])
    check.assert_endoscope(soiled, status=C.SCOPE_SOILED, cycle_count=0)

    # The technician opens a run and fails its leak test.
    SETUP.start_reprocessing(api, scope["id"])
    failed = SETUP.complete_reprocessing(api, scope["id"], leak_test_passed=False)

    # The scope is held back, and the failed run buys it no cycle credit.
    check.assert_endoscope(
        failed,
        status=C.SCOPE_QUARANTINED,
        consecutive_mec_failures=1,
        cycle_count=0,
        reprocessing_started_by_user_id=None,
        last_reprocessed_at=None,
        hld_expires_at=None,
        mec_test_due=False,
    )


def test_a_second_consecutive_failure_retires_the_scope_for_good(api):
    """PRD 3.8: "Hop two, caused by hop one and only when
    `consecutive_mec_failures` has thereby reached 2: the scope moves
    `QUARANTINED → RETIRED`, which is terminal and admits no further transition of
    any kind."

    Design: Corner/state_machines/scope_retirement_flags_scheduled_bookings
    """
    # A soiled scope that has already failed one run and sits quarantined.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMI-2999",
        patient_mrn=C.mrn(10210),
        policy_overrides={"payer_name": "Sterile Mutual"},
        patient_overrides={
            "full_name": "Cato Ferreira",
            "date_of_birth": "1979-03-03",
        },
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(10), model="Rhino-Fiber 7")
    SETUP.soil_scope(api, scope["id"], base["patient"]["id"])
    SETUP.start_reprocessing(api, scope["id"])
    SETUP.complete_reprocessing(api, scope["id"], leak_test_passed=False)

    # The retry from quarantine fails its leak test as well.
    SETUP.start_reprocessing(api, scope["id"])
    retired = SETUP.complete_reprocessing(api, scope["id"], leak_test_passed=False)
    check.assert_endoscope(
        retired,
        status=C.SCOPE_RETIRED,
        consecutive_mec_failures=2,
        cycle_count=0,
        reprocessing_started_by_user_id=None,
        last_reprocessed_at=None,
        hld_expires_at=None,
    )

    # Nothing further may be attempted on it: the retry arc is closed too.
    response = api.start_reprocessing(scope["id"], USERS.TECH_1)
    validate_error(response, ApiErrorId.SCOPE_STATE_INVALID.value)
    check.assert_endoscope(
        SETUP.read_scope(api, scope["id"]),
        status=C.SCOPE_RETIRED,
        consecutive_mec_failures=2,
    )


def test_retirement_flags_the_scheduled_booking_and_blocks_its_start(api):
    """PRD 3.8: "Hop three, caused by hop two: every `ProcedureBooking`
    referencing this scope whose status is `SCHEDULED` has
    `scope_reassignment_required` set to true, which blocks its start until the
    operator reassigns it."

    Design: Corner/state_machines/scope_retirement_flags_scheduled_bookings
    """
    # One chart, one scope, and the endoscopy that soiled it earlier this morning.
    base = SETUP.policy_with_patient(
        api,
        plan_code="SMI-2999",
        patient_mrn=C.mrn(10211),
        policy_overrides={"payer_name": "Sterile Mutual"},
        patient_overrides={
            "full_name": "Ines Bauer",
            "date_of_birth": "1981-07-07",
        },
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(11), model="Rhino-Fiber 7")
    finished = SETUP.create_booking(
        api,
        base["patient"]["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-01T00:30:00Z",
        procedure_type=C.PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        endoscope_asset_id=scope["id"],
    )
    SETUP.start_booking(api, finished["id"])
    SETUP.complete_booking(api, finished["id"])

    # A second endoscopy on the same scope is booked for two o'clock.
    upcoming = SETUP.create_booking(
        api,
        base["patient"]["id"],
        "2026-08-01T02:00:00Z",
        "2026-08-01T03:00:00Z",
        procedure_type=C.PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        endoscope_asset_id=scope["id"],
    )
    check.assert_procedure_booking(
        upcoming, status=C.BOOKING_SCHEDULED, scope_reassignment_required=False
    )

    # Two failed runs in a row retire the scope.
    SETUP.start_reprocessing(api, scope["id"])
    SETUP.complete_reprocessing(api, scope["id"], leak_test_passed=False)
    SETUP.start_reprocessing(api, scope["id"])
    SETUP.complete_reprocessing(api, scope["id"], leak_test_passed=False)

    # The retirement reaches forward into the schedule, and only into what is
    # still scheduled.
    check.assert_procedure_booking(
        SETUP.read_booking(api, upcoming["id"]),
        status=C.BOOKING_SCHEDULED,
        scope_reassignment_required=True,
    )
    check.assert_procedure_booking(
        SETUP.read_booking(api, finished["id"]),
        status=C.BOOKING_COMPLETED,
        scope_reassignment_required=False,
    )

    # The flagged booking can no longer be started.
    SETUP.set_clock(api, "2026-08-01T02:00:00Z")
    response = api.start_procedure_booking(
        upcoming["id"], USERS.ENT_1, F.booking_start_payload()
    )
    validate_error(response, ApiErrorId.SCOPE_REASSIGNMENT_REQUIRED.value)
    check.assert_procedure_booking(
        SETUP.read_booking(api, upcoming["id"]),
        status=C.BOOKING_SCHEDULED,
        scope_reassignment_required=True,
    )


def test_clearing_a_dose_advances_the_parent_chart_one_escalation_step(api):
    """PRD 3.5: "On success the dose moves `ADMINISTERED → CLEARED`,
    `observation_cleared_at` is stamped, the patient's
    `immunotherapy_escalation_step` advances to the dose's
    `escalation_step_at_dose` plus one but never beyond 12, and
    `immunotherapy_status` is re-derived from the new step: `BUILD_UP` when the
    new step is 6 or lower, `MAINTENANCE` when it is 7 or higher."

    Design: Corner/state_machines/cleared_doses_advance_the_parent_patient_schedule
    """
    # A chart standing at step one with a label-verified five-millilitre vial.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="SMJ-2999",
        patient_mrn=C.mrn(10254),
        policy_overrides={"payer_name": "Ladder Mutual"},
        patient_overrides={
            "full_name": "Remy Ohara",
            "date_of_birth": "1987-05-05",
            "epinephrine_on_file": True,
        },
        volume_ml_initial=5.00,
    )
    check.assert_patient(
        base["patient"],
        immunotherapy_escalation_step=1,
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
        last_dose_administered_at=None,
    )

    # The first dose is drawn at midnight off step one.
    dose = SETUP.administer_dose(api, base["vial"]["id"])
    check.assert_immunotherapy_dose(
        dose,
        status=C.DOSE_ADMINISTERED,
        escalation_step_at_dose=1,
        gap_days_at_dose=0,
        observation_required_minutes=30,
    )
    check.assert_volume_ml(dose["volume_ml"], 0.05)
    check.assert_instant_equals(dose["administered_at"], "2026-08-01T00:00:00Z")

    # Administration alone moves no rung: the chart still stands at step one.
    check.assert_patient(
        SETUP.read_patient(api, base["patient"]["id"]),
        immunotherapy_escalation_step=1,
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
    )

    # Half an hour later the observation is discharged.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    SETUP.clear_dose(api, dose["id"])

    # The clearance is what carries the chart up to step two.
    advanced = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        advanced,
        immunotherapy_escalation_step=2,
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
    )
    check.assert_instant_equals(
        advanced["last_dose_administered_at"], "2026-08-01T00:00:00Z"
    )


def test_the_second_dose_draws_the_next_volume_on_the_schedule(api):
    """PRD 3.5: "Stage three reads the volume from the **post-rollback** effective
    step, using this schedule: step 1 draws 0.05 mL, step 2 draws 0.10, step 3
    draws 0.20, step 4 draws 0.30, step 5 draws 0.40, step 6 draws 0.50, and the
    maintenance half of the schedule repeats the same ladder — step 7 draws 0.05,
    step 8 draws 0.10, step 9 draws 0.20, step 10 draws 0.30, step 11 draws 0.40,
    step 12 draws 0.50."

    Design: Corner/state_machines/cleared_doses_advance_the_parent_patient_schedule
    """
    # A chart whose first dose has already been given and discharged.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="SMJ-2999",
        patient_mrn=C.mrn(10254),
        policy_overrides={"payer_name": "Ladder Mutual"},
        patient_overrides={
            "full_name": "Remy Ohara",
            "date_of_birth": "1987-05-05",
            "epinephrine_on_file": True,
        },
        volume_ml_initial=5.00,
    )
    first = SETUP.administer_dose(api, base["vial"]["id"])
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    SETUP.clear_dose(api, first["id"])

    # The second dose is drawn off step two on the same day.
    second = SETUP.administer_dose(api, base["vial"]["id"])
    check.assert_immunotherapy_dose(
        second,
        status=C.DOSE_ADMINISTERED,
        escalation_step_at_dose=2,
        gap_days_at_dose=0,
    )
    check.assert_volume_ml(second["volume_ml"], 0.10)
    check.assert_instant_equals(second["administered_at"], "2026-08-01T00:30:00Z")

    # Its own thirty minutes elapse and it too is discharged.
    SETUP.set_clock(api, "2026-08-01T01:00:00Z")
    SETUP.clear_dose(api, second["id"])
    walked_up = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        walked_up,
        immunotherapy_escalation_step=3,
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
    )
    check.assert_instant_equals(
        walked_up["last_dose_administered_at"], "2026-08-01T00:30:00Z"
    )

    # Both draws come out of the one vial's ledger.
    vial = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_immunotherapy_vial(vial, status=C.VIAL_IN_USE)
    check.assert_volume_ml(vial["volume_ml_remaining"], 4.85)
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.15)
    check.assert_volume_ml(vial["volume_ml_wasted"], 0.00)

    # And both are visible as cleared doses of that vial.
    rows, meta = validate_paginated(
        api.list_immunotherapy_doses(
            USERS.NURSE_1,
            params={
                "immunotherapy_vial_id": base["vial"]["id"],
                "status": C.DOSE_CLEARED,
            },
        )
    )
    assert meta["total_count"] == 2, "expected two cleared doses, got {0}".format(
        meta["total_count"]
    )
    assert len(rows) == 2, "expected two rows, got {0}".format(len(rows))
    assert [row["status"] for row in rows] == [C.DOSE_CLEARED, C.DOSE_CLEARED]
