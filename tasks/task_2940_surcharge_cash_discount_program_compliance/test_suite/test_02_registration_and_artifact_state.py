"""The registration machine from submission through decision and effectuation, and
the artifact machine's one-way trip into expiry."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_days_apart,
    assert_instant_equals,
    assert_network_registration,
    attest_artifact,
    attest_disclosures,
    configure_terminal,
    decide_registration,
    draft_artifact,
    list_total,
    program_status_action,
    provision_terminal,
    read_artifact,
    read_merchant,
    read_program,
    read_registration,
    read_terminal,
    set_clock,
    setup_draft_program,
    setup_program_pending_registration,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_31,
    CLOCK_AUG_01,
    CLOCK_DEC_31,
    CLOCK_OCT_01,
    CLOCK_SEP_01,
    CONTENT_HASH_C,
    NOTICE_PERIOD_DAYS,
    OFFICER_TWO_USER_ID,
    TS_AUG_01,
    TS_AUG_31,
    TS_SEP_01,
)
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, OFFICER_TWO


def test_first_registration_opens_submitted_and_moves_the_program_to_pending(api):
    """PRD §3.5: "Submission stamps the registration's `submitted_at` from the logical clock, copies the platform's notice period of 30 days onto the row as `notice_days`, and derives `earliest_effective_at` as `submitted_at` plus those 30 days."
    PRD §3.5: "The registration is created in state `SUBMITTED`, with `decided_by_user_id`, `decision_note`, `effective_at`, and `revoked_at` all null."
    PRD §3.5: "The first registration also drives the program from `DRAFT` to `PENDING_REGISTRATION`, and the program's `version` is bumped by 1."

    Design: Corner/state_machines/network_registration_initial_state_is_submitted
    """
    ctx = setup_draft_program()
    program_id = ctx["program"]["id"]
    assert ctx["program"]["status"] == "DRAFT"

    registration = validate_success(
        api_client.create_network_registration(
            program_id,
            {"network": "VISA", "registration_ref": "VS-2940-AZ-111"},
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert_network_registration(registration)
    assert registration["state"] == "SUBMITTED"
    assert registration["version"] == 1
    assert registration["notice_days"] == NOTICE_PERIOD_DAYS == 30
    assert_instant_equals(registration["submitted_at"], TS_AUG_01, "submitted_at")
    assert_instant_equals(
        registration["earliest_effective_at"], TS_AUG_31, "earliest_effective_at"
    )
    assert_days_apart(
        registration["earliest_effective_at"], registration["submitted_at"], 30, "notice period"
    )
    assert registration["decided_by_user_id"] is None
    assert registration["decision_note"] is None
    assert registration["effective_at"] is None
    assert registration["revoked_at"] is None

    assert read_program(program_id)["status"] == "PENDING_REGISTRATION"


def test_acknowledgement_records_the_deciding_auditor_and_the_note(api):
    """PRD §3.5: "Every decision records the auditor's `X-User-ID` as `decided_by_user_id`, stores the supplied note as `decision_note`, and bumps the registration's `version` by 1."
    PRD §3.5: "`ACKNOWLEDGE` moves `SUBMITTED → ACKNOWLEDGED` and does nothing else."

    Design: Corner/state_machines/network_registration_acknowledge_records_decider_and_note
    """
    ctx = setup_program_pending_registration()
    registration_id = ctx["registration"]["id"]
    assert ctx["registration"]["state"] == "SUBMITTED"

    decided = validate_success(
        api_client.decide_network_registration(
            registration_id,
            {
                "decision": "ACKNOWLEDGE",
                "decision_note": "registration on file, awaiting notice period",
            },
            AUDITOR,
        )
    )
    assert decided["state"] == "ACKNOWLEDGED"
    assert decided["version"] == 2
    assert decided["decided_by_user_id"] == "auditor-1"
    assert decided["decision_note"] == "registration on file, awaiting notice period"
    assert decided["effective_at"] is None
    assert decided["revoked_at"] is None

    assert read_program(ctx["program"]["id"])["status"] == "PENDING_REGISTRATION"


def test_a_second_acknowledgement_is_refused_and_keeps_the_first_decision(api):
    """PRD §3.5: "A decision requested from the wrong state — acknowledging a registration that is not `SUBMITTED`, or revoking one that is not `EFFECTIVE` — is rejected with `ERR_INVALID_REGISTRATION_STATE`."
    PRD §2.11: "A request either completes with every derived field it touches recomputed, or it fails and changes nothing."

    Design: Corner/state_machines/network_registration_second_acknowledge_rejected
    """
    ctx = setup_program_pending_registration()
    registration_id = ctx["registration"]["id"]
    decide_registration(registration_id, "ACKNOWLEDGE", decision_note="first decision")

    response = api_client.decide_network_registration(
        registration_id,
        {"decision": "ACKNOWLEDGE", "decision_note": "second decision"},
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE)

    registration = read_registration(registration_id)
    assert registration["state"] == "ACKNOWLEDGED"
    assert registration["version"] == 2
    assert registration["decision_note"] == "first decision"


def test_a_rejected_registration_stays_rejected_once_the_notice_period_has_run(api):
    """PRD §3.5: "`REJECTED` and `REVOKED` are both terminal."
    PRD §3.5: "`REJECT` moves `SUBMITTED → REJECTED`, and its side-effect set diverges deliberately from the acknowledge arm: the owning program stays exactly where it is, in `PENDING_REGISTRATION`, and not one program field changes — the program simply can never reach `ACTIVE` through this particular registration and must obtain another."
    PRD §3.5: "A `ComplianceOfficer` effectuates an acknowledged registration, moving `ACKNOWLEDGED → EFFECTIVE` and stamping `effective_at` from the logical clock, but only if the clock has reached `earliest_effective_at`."

    Design: Corner/state_machines/rejected_registration_cannot_be_effectuated
    """
    ctx = setup_program_pending_registration()
    registration_id = ctx["registration"]["id"]
    rejected = decide_registration(
        registration_id, "REJECT", decision_note="the network refused the filing"
    )
    assert rejected["state"] == "REJECTED"

    set_clock(CLOCK_AUG_31)
    response = api_client.effectuate_network_registration(registration_id, OFFICER_ONE)
    body = validate_error(response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE)
    assert body["error_id"] != ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED

    registration = read_registration(registration_id)
    assert registration["state"] == "REJECTED"
    assert registration["effective_at"] is None
    assert read_program(ctx["program"]["id"])["status"] == "PENDING_REGISTRATION"


def test_withdrawal_expires_the_signage_revokes_the_filing_and_disables_the_terminal(api):
    """PRD §3.7: "Its side effects are: every disclosure artifact of the program in state `ATTESTED` moves to `EXPIRED` with `expired_reason` set to `PROGRAM_WITHDRAWN`; every registration of the program in state `SUBMITTED`, `ACKNOWLEDGED`, or `EFFECTIVE` moves to `REVOKED` with `revoked_at` stamped from the logical clock; every `Terminal` of the program whose `state` is not already `DISABLED` moves to `DISABLED`; `enforcing_terminal_count` is recomputed for the program's merchant; and the program's `version` is bumped by 1."
    PRD §2.11: "A cascade never partially applies: if a law change disables three programs, all three programs, all of their affected terminals, and all of the affected merchants' census figures move together within that one request."

    Design: Corner/state_machines/program_withdrawal_cascade_expires_artifacts_revokes_registration_disables_terminals
    """
    ctx = setup_program_pending_registration()
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    registration_id = ctx["registration"]["id"]
    decide_registration(registration_id, "ACKNOWLEDGE")

    artifact = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")
    attest_artifact(artifact["id"], CLOCK_AUG_01, CLOCK_SEP_01, OFFICER_TWO_USER_ID)
    terminal = provision_terminal(merchant_id, "TRM-AZ-0001")
    configure_terminal(terminal["id"], merchant_id, program_id)

    withdrawn = program_status_action(
        program_id, "WITHDRAW", reason="merchant exits the surcharge program"
    )
    assert withdrawn["status"] == "WITHDRAWN"

    expired = read_artifact(artifact["id"])
    assert expired["state"] == "EXPIRED"
    assert expired["expired_reason"] == "PROGRAM_WITHDRAWN"

    revoked = read_registration(registration_id)
    assert revoked["state"] == "REVOKED"
    assert_instant_equals(revoked["revoked_at"], TS_AUG_01, "revoked_at")

    assert read_terminal(terminal["id"])["state"] == "DISABLED"
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0


def test_a_withdrawn_program_cannot_be_suspended(api):
    """PRD §3.7: "**`WITHDRAW`**, available to a `ComplianceOfficer` only, is permitted from any `status` other than `WITHDRAWN` and is irreversible."
    PRD §3.7: "**`SUSPEND`**, available to a `ComplianceOfficer` or a `NetworkAuditor`, requires `status` of `ACTIVE` and moves the program `ACTIVE → SUSPENDED` with `disable_reason` set to `OPERATOR_SUSPENSION`."

    Design: Corner/state_machines/withdrawn_program_cannot_be_suspended
    """
    ctx = setup_draft_program()
    program_id = ctx["program"]["id"]
    program_status_action(program_id, "WITHDRAW", reason="merchant never opened")

    response = api_client.program_status_action(
        program_id, {"action": "SUSPEND", "reason": "too late"}, OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PROGRAM_STATE)

    assert read_program(program_id)["status"] == "WITHDRAWN"


def test_the_third_attestation_is_what_makes_a_new_york_program_disclosure_ready(api):
    """PRD §3.6: "For a `SURCHARGE` program: if the jurisdiction's `disclosure_signage_required` is true, both `ENTRY_SIGNAGE` and `POS_SIGNAGE` are required; if its `receipt_line_item_required` is true, `RECEIPT_TEMPLATE` is required as well."
    PRD §3.6: "`disclosure_ready` is true exactly when every member of the required set appears in the satisfied set."
    PRD §3.6: "Attestation recomputes the owning program's `disclosure_ready` flag, bumps that program's `version` by 1, and bumps the artifact's own `version` by 1."

    Design: Corner/state_machines/third_artifact_attestation_flips_program_disclosure_ready_and_bumps_program_version
    """
    ctx = setup_draft_program(jurisdiction_profile="NY", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    attest_disclosures(
        program_id,
        merchant_id,
        ["ENTRY_SIGNAGE", "POS_SIGNAGE"],
        CLOCK_AUG_01,
        CLOCK_SEP_01,
        OFFICER_TWO_USER_ID,
    )
    receipt = draft_artifact(program_id, merchant_id, "RECEIPT_TEMPLATE", CONTENT_HASH_C)

    before = read_program(program_id)
    assert before["disclosure_ready"] is False
    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
            )
        )
        == 2
    )

    attested = validate_success(
        api_client.attest_disclosure_artifact(
            receipt["id"],
            {"effective_from": CLOCK_AUG_01, "expires_at": CLOCK_SEP_01},
            OFFICER_TWO,
        )
    )
    assert attested["state"] == "ATTESTED"
    assert attested["attested_by_user_id"] == "officer-2"
    assert_instant_equals(attested["attested_at"], TS_AUG_01, "attested_at")
    assert attested["version"] == 2

    after = read_program(program_id)
    assert after["disclosure_ready"] is True
    assert after["version"] == before["version"] + 1
    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
            )
        )
        == 3
    )


def test_an_expired_artifact_cannot_be_attested_a_second_time(api):
    """PRD §3.6: "`EXPIRED` is terminal — an expired artifact is never revived, and recovery means drafting and attesting a fresh one."
    PRD §3.6: "Attesting an artifact that is not in `DRAFT` is rejected with `ERR_INVALID_ARTIFACT_STATE`."
    PRD §3.6: "When a program is withdrawn, every `ATTESTED` artifact moves to `EXPIRED` with `expired_reason` set to `PROGRAM_WITHDRAWN`."

    Design: Corner/state_machines/expired_artifact_cannot_be_reattested
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    artifact = draft_artifact(program_id, ctx["merchant"]["id"], "ENTRY_SIGNAGE")
    attest_artifact(artifact["id"], CLOCK_AUG_01, CLOCK_SEP_01, OFFICER_TWO_USER_ID)
    program_status_action(program_id, "WITHDRAW", reason="programme abandoned")
    assert read_artifact(artifact["id"])["state"] == "EXPIRED"

    response = api_client.attest_disclosure_artifact(
        artifact["id"],
        {"effective_from": CLOCK_OCT_01, "expires_at": CLOCK_DEC_31},
        OFFICER_TWO,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ARTIFACT_STATE)

    unchanged = read_artifact(artifact["id"])
    assert unchanged["state"] == "EXPIRED"
    assert unchanged["expired_reason"] == "PROGRAM_WITHDRAWN"
    assert_instant_equals(unchanged["effective_from"], TS_AUG_01, "effective_from")
    assert_instant_equals(unchanged["expires_at"], TS_SEP_01, "expires_at")
