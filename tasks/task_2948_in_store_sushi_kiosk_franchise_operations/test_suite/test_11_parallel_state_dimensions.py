"""Two independent state dimensions on a kiosk, and the audit's bounded cycle."""

from test_helpers import (
    AUDIT_CLOSED,
    AUDIT_CORRECTIVE_ACTION_PENDING,
    AUDIT_ESCALATED_CLOSURE,
    AUDIT_REVERIFICATION,
    AUDITOR_VERIFIER_ID,
    ApiErrorId,
    CLOSURE_ESCALATED,
    CLOSURE_PASS_AFTER_CORRECTION,
    FINDING_CORRECTED,
    FINDING_OPEN,
    FINDING_VERIFIED,
    KIOSK_OPERATING,
    KIOSK_SUSPENDED,
    KIOSK_SUSPENSION_AUDIT_ESCALATION,
    POSTURE_CLEAR,
    POSTURE_LOCKDOWN,
    POSTURE_WATCH,
    SEVERITY_MAJOR,
    VERIFY_OUTCOME_FAIL,
    add_kiosk,
    add_reverification_request,
    add_submitted_audit,
    base_world,
    correct_all_findings,
    drive_audit_to_second_round,
    find_by_id,
    ids_of,
    suspension_payload,
    validate_error,
    validate_list,
    validate_success,
    verify_audit,
)

TWO_MAJOR_CODES = ["FS-HANDWASH-SIGNAGE", "FS-GLOVE-USE"]


def test_the_sanitation_dimension_travels_while_the_operational_one_holds_still(api):
    """A kiosk walks CLEAR to WATCH and back without ever leaving OPERATING.

    "Running alongside `operational_state`, and never constraining it, is the
    kiosk's food-safety dimension: `sanitation_posture` … It is never set by a
    caller. It is re-derived by the system from `risk_points` and
    `open_critical_finding_count` after every event that changes a risk input."

    Design: Difficulty/non_linear_state_machine/kiosk_parallel_operational_and_sanitation_dimensions
    """
    world = base_world()
    opening = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert opening["operational_state"] == KIOSK_OPERATING
    assert opening["sanitation_posture"] == POSTURE_CLEAR

    submitted = add_submitted_audit(
        world, severities=(SEVERITY_MAJOR, SEVERITY_MAJOR), codes=TWO_MAJOR_CODES
    )
    audit_id = submitted["audit_id"]
    assert submitted["audit"]["score"] == 84

    watched = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert watched["risk_points"] == 8
    assert watched["sanitation_posture"] == POSTURE_WATCH
    assert watched["operational_state"] == KIOSK_OPERATING
    assert watched["consecutive_clean_audits"] == 0

    requested = add_reverification_request(world, audit_id, submitted["findings"])
    assert requested["status"] == AUDIT_REVERIFICATION
    assert requested["round_count"] == 1

    mid_cycle = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert mid_cycle["risk_points"] == 8
    assert mid_cycle["sanitation_posture"] == POSTURE_WATCH
    assert mid_cycle["operational_state"] == KIOSK_OPERATING

    closed = verify_audit(world, audit_id)
    assert closed["status"] == AUDIT_CLOSED
    assert closed["closure_outcome"] == CLOSURE_PASS_AFTER_CORRECTION
    assert closed["round_count"] == 1
    assert closed["score"] == 84
    assert closed["verified_by_user_id"] == AUDITOR_VERIFIER_ID

    verified = validate_list(
        api.list_findings(audit_id, world["auditor_headers"]), expected_total=2
    )
    assert all(finding["status"] == FINDING_VERIFIED for finding in verified)

    cleared = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert cleared["risk_points"] == 0
    assert cleared["sanitation_posture"] == POSTURE_CLEAR
    assert cleared["operational_state"] == KIOSK_OPERATING


def test_a_suspended_kiosk_keeps_the_posture_its_findings_earned(api):
    """Closing the shutters does not clear the risk that put the kiosk on WATCH.

    "What suspension does *not* do is touch `sanitation_posture`: the two
    dimensions move independently, and a manually suspended kiosk keeps whatever
    posture its risk total warrants."

    Design: Difficulty/non_linear_state_machine/kiosk_parallel_operational_and_sanitation_dimensions
    """
    world = base_world()
    submitted = add_submitted_audit(
        world, severities=(SEVERITY_MAJOR, SEVERITY_MAJOR), codes=TWO_MAJOR_CODES
    )
    audit_id = submitted["audit_id"]

    down = validate_success(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(suspension_reason="CASE_COMPRESSOR_FAULT"),
            world["ops_headers"],
        )
    )
    assert down["operational_state"] == KIOSK_SUSPENDED
    assert down["suspension_reason"] == "CASE_COMPRESSOR_FAULT"
    assert down["sanitation_posture"] == POSTURE_WATCH
    assert down["risk_points"] == 8

    add_reverification_request(world, audit_id, submitted["findings"])
    held = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert held["operational_state"] == KIOSK_SUSPENDED
    assert held["sanitation_posture"] == POSTURE_WATCH

    verify_audit(world, audit_id)
    forgiven = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert forgiven["risk_points"] == 0
    assert forgiven["sanitation_posture"] == POSTURE_CLEAR
    assert forgiven["operational_state"] == KIOSK_SUSPENDED
    assert forgiven["suspension_reason"] == "CASE_COMPRESSOR_FAULT"

    back_up = validate_success(
        api.reinstate_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert back_up["operational_state"] == KIOSK_OPERATING
    assert back_up["suspension_reason"] is None
    assert back_up["sanitation_posture"] == POSTURE_CLEAR


def test_the_two_dimensions_narrow_the_kiosk_list_independently(api):
    """One filter finds the watched kiosk, the other finds the suspended one.

    "Kiosks can be listed with the list narrowed by `license_agreement_id`,
    `lead_chef_id`, `operational_state` or `sanitation_posture`."

    Design: Difficulty/non_linear_state_machine/kiosk_parallel_operational_and_sanitation_dimensions
    """
    world = base_world()
    add_submitted_audit(
        world, severities=(SEVERITY_MAJOR, SEVERITY_MAJOR), codes=TWO_MAJOR_CODES
    )
    sibling = add_kiosk(world, "K-418-B", "Mika Sato")
    validate_success(
        api.suspend_kiosk(
            sibling["kiosk_id"],
            suspension_payload(suspension_reason="HOST_CHAIN_REMODEL_PAUSE"),
            world["ops_headers"],
        )
    )

    operating = validate_list(
        api.list_kiosks(
            world["ops_headers"],
            {
                "license_agreement_id": world["agreement_id"],
                "operational_state": KIOSK_OPERATING,
            },
        ),
        expected_total=1,
    )
    assert ids_of(operating) == [world["kiosk_id"]]

    watched = validate_list(
        api.list_kiosks(
            world["ops_headers"],
            {
                "license_agreement_id": world["agreement_id"],
                "sanitation_posture": POSTURE_WATCH,
            },
        ),
        expected_total=1,
    )
    assert ids_of(watched) == [world["kiosk_id"]]

    suspended = validate_list(
        api.list_kiosks(
            world["ops_headers"],
            {
                "license_agreement_id": world["agreement_id"],
                "operational_state": KIOSK_SUSPENDED,
            },
        ),
        expected_total=1,
    )
    assert ids_of(suspended) == [sibling["kiosk_id"]]

    clear = validate_list(
        api.list_kiosks(
            world["ops_headers"],
            {
                "license_agreement_id": world["agreement_id"],
                "sanitation_posture": POSTURE_CLEAR,
            },
        ),
        expected_total=1,
    )
    assert ids_of(clear) == [sibling["kiosk_id"]]


def test_a_failed_reverification_hands_the_audit_back_for_another_round(api):
    """The audit walks backwards along the cycle edge instead of closing.

    "`FAIL` while `round_count` is still below the two-round corrective budget
    returns every `CORRECTED` finding to `OPEN`, clearing each one's
    `correction_note` and re-incrementing `open_finding_count`, re-applies their
    `risk_points` to the kiosk and re-derives the posture, and returns the audit to
    `CORRECTIVE_ACTION_PENDING`."

    Design: Difficulty/non_linear_state_machine/audit_reverification_cycle_returns_to_corrective_action_pending
    """
    world = base_world()
    submitted = add_submitted_audit(world, severities=(SEVERITY_MAJOR,))
    audit_id = submitted["audit_id"]
    finding_id = submitted["findings"][0]["id"]
    assert submitted["audit"]["status"] == AUDIT_CORRECTIVE_ACTION_PENDING
    assert submitted["audit"]["score"] == 92

    correct_all_findings(world, audit_id, submitted["findings"])
    corrected = find_by_id(
        validate_list(api.list_findings(audit_id, world["auditor_headers"])), finding_id
    )
    assert corrected["status"] == FINDING_CORRECTED
    assert corrected["correction_note"] is not None

    requested = validate_success(
        api.request_reverification(audit_id, world["manager_headers"])
    )
    assert requested["status"] == AUDIT_REVERIFICATION
    assert requested["round_count"] == 1

    failed = verify_audit(world, audit_id, VERIFY_OUTCOME_FAIL)
    assert failed["status"] == AUDIT_CORRECTIVE_ACTION_PENDING
    assert failed["round_count"] == 1
    assert failed["score"] == 92
    assert failed["closure_outcome"] is None
    assert failed["open_finding_count"] == 1

    reopened = find_by_id(
        validate_list(api.list_findings(audit_id, world["auditor_headers"])), finding_id
    )
    assert reopened["status"] == FINDING_OPEN
    assert reopened["correction_note"] is None

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["risk_points"] == 4
    assert kiosk["sanitation_posture"] == POSTURE_CLEAR
    assert kiosk["operational_state"] == KIOSK_OPERATING


def test_the_second_failure_escalates_instead_of_cycling(api):
    """The same trigger and payload land in a terminal state once the budget is spent.

    "`FAIL` when `round_count` has reached 2 is the end of the road. The audit moves
    to `ESCALATED_CLOSURE` with `closure_outcome` `ESCALATED` and
    `verified_by_user_id` recorded … the audited kiosk moves `OPERATING →
    SUSPENDED` with `suspension_reason` `AUDIT_ESCALATION` and — uniquely among the
    ways a kiosk gets suspended — `sanitation_posture` forced to `LOCKDOWN`."

    Design: Difficulty/non_linear_state_machine/audit_reverification_cycle_returns_to_corrective_action_pending
    """
    world = base_world()
    cycled = drive_audit_to_second_round(world, severities=(SEVERITY_MAJOR,))
    audit_id = cycled["audit_id"]

    second_round = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert second_round["status"] == AUDIT_REVERIFICATION
    assert second_round["round_count"] == 2

    escalated = verify_audit(world, audit_id, VERIFY_OUTCOME_FAIL)
    assert escalated["status"] == AUDIT_ESCALATED_CLOSURE
    assert escalated["closure_outcome"] == CLOSURE_ESCALATED
    assert escalated["round_count"] == 2
    assert escalated["score"] == 92
    assert escalated["verified_by_user_id"] == AUDITOR_VERIFIER_ID

    shut = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert shut["operational_state"] == KIOSK_SUSPENDED
    assert shut["suspension_reason"] == KIOSK_SUSPENSION_AUDIT_ESCALATION
    assert shut["sanitation_posture"] == POSTURE_LOCKDOWN

    validate_error(
        api.request_reverification(audit_id, world["manager_headers"]),
        ApiErrorId.ERR_CORRECTIVE_ROUNDS_EXHAUSTED.value,
        422,
    )
    still_terminal = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert still_terminal["status"] == AUDIT_ESCALATED_CLOSURE
    assert still_terminal["round_count"] == 2
