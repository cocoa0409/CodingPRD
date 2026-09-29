"""The two independent complaint dimensions, the two exposure methods, and the
four-level remediation cascade that a substantiation sets off."""
import pytest

from test_helpers import (
    api_client,
    file_complaint,
    get_success_data,
    investigation_action,
    read_complaint_case,
    read_merchant,
    read_program,
    read_terminal,
    remediation_action,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    list_total,
)
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, read_artifact

PLAN_TEXT = "Reprint receipt templates and retrain staff."


def test_reviewing_moves_only_the_investigation_dimension(api):
    """PRD §3.10: "The two dimensions never read each other except through one coupling: substantiating the investigation sets `remediation_state` to `PLAN_REQUIRED`."
    PRD §3.10: "**`REVIEW`** is available to a `ComplianceOfficer` only, requires `investigation_state` of `OPEN`, and moves it to `UNDER_REVIEW`; it records the reviewer's `X-User-ID` as `reviewed_by_user_id`, leaves `remediation_state` untouched at `NONE`, recomputes the program's `ag_exposure_score` (an `UNDER_REVIEW` case still scores as unresolved), and bumps the case's `version` by 1."

    Design: Difficulty/non_linear_state_machine/complaint_case_parallel_dimensions_advance_independently
    """
    ctx = setup_draft_program()
    case = file_complaint(
        ctx["program"]["id"],
        "NETWORK",
        allegation_type="MISSING_RECEIPT_LINE",
        narrative="Receipt did not itemise the surcharge.",
    )
    assert case["investigation_state"] == "OPEN"
    assert case["remediation_state"] == "NONE"
    assert case["response_due_at"] == "2026-08-11T00:00:00.000Z", (
        "a NETWORK complaint carries a ten-day response window"
    )

    reviewed = investigation_action(case["id"], "REVIEW", "NETWORK", note="assigned to officer-1")
    assert reviewed["investigation_state"] == "UNDER_REVIEW"
    assert reviewed["remediation_state"] == "NONE"
    assert reviewed["reviewed_by_user_id"] == "officer-1"
    assert reviewed["version"] == case["version"] + 1


def test_substantiation_couples_the_dimensions_once_and_then_they_part(api):
    """PRD §3.10: "**`SUBSTANTIATE`** is available to a `NetworkAuditor` or a `StateRegulator` whose channel matches the case's `source`, requires `investigation_state` of `OPEN` or `UNDER_REVIEW`, and moves it to `SUBSTANTIATED`; it sets `remediation_state` to `PLAN_REQUIRED`, recomputes both `network_exposure_score` and `ag_exposure_score`, may trigger the remediation cascade below, and bumps the case's `version` by 1."
    PRD §3.10: "`plan_summary` must be present in the request, else the request is rejected with `ERR_INVALID_REQUEST`, and the supplied text is stored on the case. `investigation_state` is untouched and stays `SUBSTANTIATED`."

    Design: Difficulty/non_linear_state_machine/complaint_case_parallel_dimensions_advance_independently
    """
    ctx = setup_draft_program()
    case = file_complaint(
        ctx["program"]["id"],
        "NETWORK",
        allegation_type="MISSING_RECEIPT_LINE",
        narrative="Receipt did not itemise the surcharge.",
    )
    investigation_action(case["id"], "REVIEW", "NETWORK", note="assigned to officer-1")

    substantiated = investigation_action(
        case["id"], "SUBSTANTIATE", "NETWORK", note="allegation upheld"
    )
    assert substantiated["investigation_state"] == "SUBSTANTIATED"
    assert substantiated["remediation_state"] == "PLAN_REQUIRED"

    submitted = remediation_action(
        case["id"], "SUBMIT_PLAN", "NETWORK", plan_summary=PLAN_TEXT
    )
    assert submitted["investigation_state"] == "SUBSTANTIATED"
    assert submitted["remediation_state"] == "PLAN_SUBMITTED"
    assert submitted["plan_summary"] == PLAN_TEXT

    accepted = remediation_action(case["id"], "ACCEPT_PLAN", "NETWORK")
    assert accepted["investigation_state"] == "SUBSTANTIATED"
    assert accepted["remediation_state"] == "PLAN_ACCEPTED"

    program = read_program(ctx["program"]["id"])
    assert program["status"] == "DRAFT", (
        "the enforcement cascade only fires on a program that is ACTIVE"
    )
    assert program["network_exposure_score"] == pytest.approx(30.00, abs=0.01)


def test_the_two_exposure_methods_disagree_on_the_same_two_cases(api):
    """PRD §3.10: "One substantiated `NETWORK` case therefore scores 20 multiplied by 1.5, which is 30.00, while one substantiated `CARDHOLDER` case scores 20 multiplied by 1.0, which is 20.00."
    PRD §3.10: "The two methods genuinely disagree: a program with one substantiated `NETWORK` case and one still-open `ATTORNEY_GENERAL` case, sitting in a `MONITORED` state, scores 30.00 under the network method and 1.0 multiplied by the sum of 20 and 8, which is 28.00, under the attorney-general method."

    Design: Difficulty/dual_variant_calc/exposure_score_network_method_vs_ag_method
    """
    ctx = setup_draft_program(jurisdiction_profile="NY")
    program_id = ctx["program"]["id"]
    network_case = file_complaint(
        program_id,
        "NETWORK",
        allegation_type="CAP_EXCEEDED",
        narrative="Visa compliance: surcharge above documented cost.",
    )
    investigation_action(
        network_case["id"], "SUBSTANTIATE", "NETWORK", note="cap breach confirmed"
    )
    file_complaint(
        program_id,
        "ATTORNEY_GENERAL",
        allegation_type="UNDISCLOSED_SURCHARGE",
        narrative="AG inquiry: signage not posted at entry.",
    )

    program = read_program(program_id)
    assert program["network_exposure_score"] == pytest.approx(30.00, abs=0.01)
    assert program["ag_exposure_score"] == pytest.approx(28.00, abs=0.01)
    assert program["status"] == "DRAFT"


def test_exposure_summary_publishes_both_methods_side_by_side(api):
    """PRD §3.11: "It reports `program_id`, the persisted `network_exposure_score` and `ag_exposure_score`, `substantiated_case_count` as the number of that program's cases whose `investigation_state` is `SUBSTANTIATED`, `unresolved_case_count` as the number whose `investigation_state` is `OPEN` or `UNDER_REVIEW`, `posture_multiplier` as the weight implied by the jurisdiction's `ag_enforcement_posture`, and `remediation_threshold` as the network-method trigger of 30."

    Design: Difficulty/dual_variant_calc/exposure_score_network_method_vs_ag_method
    """
    ctx = setup_draft_program(jurisdiction_profile="NY")
    program_id = ctx["program"]["id"]
    network_case = file_complaint(
        program_id,
        "NETWORK",
        allegation_type="CAP_EXCEEDED",
        narrative="Visa compliance: surcharge above documented cost.",
    )
    investigation_action(
        network_case["id"], "SUBSTANTIATE", "NETWORK", note="cap breach confirmed"
    )
    file_complaint(
        program_id,
        "ATTORNEY_GENERAL",
        allegation_type="UNDISCLOSED_SURCHARGE",
        narrative="AG inquiry: signage not posted at entry.",
    )

    summary = get_success_data(api_client.get_exposure_summary(program_id, OFFICER_ONE))
    assert summary["program_id"] == program_id
    assert summary["network_exposure_score"] == pytest.approx(30.00, abs=0.01)
    assert summary["ag_exposure_score"] == pytest.approx(28.00, abs=0.01)
    assert summary["substantiated_case_count"] == 1
    assert summary["unresolved_case_count"] == 1
    assert summary["posture_multiplier"] == pytest.approx(1.0, abs=0.01)
    assert summary["remediation_threshold"] == 30


def test_substantiation_strips_the_disclosures_and_stops_the_estate(api):
    """PRD §3.10: "Step one: the program moves `ACTIVE → REMEDIATION` with `disable_reason` set to `REMEDIATION_ORDER`. Step two: every disclosure artifact of that program in state `ATTESTED` moves to `EXPIRED` with `expired_reason` set to `REMEDIATION_ORDER`. Step three: because every attested artifact is now gone, the program's `disclosure_ready` is recomputed and becomes false, and consequently every `Terminal` of the program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `DISCLOSURE_EXPIRED`. Step four: each of those terminal quarantines recomputes `enforcing_terminal_count` on the terminal's merchant."

    Design: Difficulty/transitive_cascade/substantiation_remediation_cascade_artifacts_readiness_terminals
    """
    ctx = setup_enforcing_surcharge_estate(
        jurisdiction_profile="NY",
        terminal_count=1,
        serial_prefix="T-NY-",
        legal_name="Hudson Goods Inc",
        mcc="5999",
    )
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    assert ctx["program"]["status"] == "ACTIVE"
    assert ctx["program"]["disclosure_ready"] is True
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 1
    assert sorted(ctx["artifacts"]) == ["ENTRY_SIGNAGE", "POS_SIGNAGE", "RECEIPT_TEMPLATE"]

    case = file_complaint(
        program_id,
        "NETWORK",
        allegation_type="CAP_EXCEEDED",
        narrative="Cardholder reported a surcharge above the documented cost.",
    )
    substantiated = investigation_action(
        case["id"], "SUBSTANTIATE", "NETWORK", note="network upheld the allegation"
    )
    assert substantiated["investigation_state"] == "SUBSTANTIATED"
    assert substantiated["remediation_state"] == "PLAN_REQUIRED"

    program = read_program(program_id)
    assert program["network_exposure_score"] == pytest.approx(30.00, abs=0.01)
    assert program["status"] == "REMEDIATION"
    assert program["disable_reason"] == "REMEDIATION_ORDER"
    assert program["disclosure_ready"] is False

    for artifact in ctx["artifacts"].values():
        refreshed = read_artifact(artifact["id"])
        assert refreshed["state"] == "EXPIRED"
        assert refreshed["expired_reason"] == "REMEDIATION_ORDER"

    terminal = read_terminal(ctx["terminal"]["id"])
    assert terminal["state"] == "QUARANTINED"
    assert terminal["quarantine_reason"] == "DISCLOSURE_EXPIRED"
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0


def test_the_cascade_leaves_no_artifact_still_attested_and_no_terminal_enforcing(api):
    """PRD §3.6: "`EXPIRED` is terminal — an expired artifact is never revived, and recovery means drafting and attesting a fresh one."
    PRD §3.10: "A single substantiated network complaint can therefore stop a merchant's entire estate of terminals, which is the intended serialisation point between enforcement and capture."

    Design: Difficulty/transitive_cascade/substantiation_remediation_cascade_artifacts_readiness_terminals
    """
    ctx = setup_enforcing_surcharge_estate(
        jurisdiction_profile="NY",
        terminal_count=1,
        serial_prefix="T-NY-",
        legal_name="Hudson Goods Inc",
        mcc="5999",
    )
    program_id = ctx["program"]["id"]
    case = file_complaint(
        program_id,
        "NETWORK",
        allegation_type="CAP_EXCEEDED",
        narrative="Cardholder reported a surcharge above the documented cost.",
    )
    investigation_action(case["id"], "SUBSTANTIATE", "NETWORK", note="network upheld the allegation")

    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
            )
        )
        == 0
    )
    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "EXPIRED"}
            )
        )
        == 3
    )
    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"program_id": program_id, "state": "ENFORCING"}
            )
        )
        == 0
    )
