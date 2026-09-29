"""What the collection and computed-read surfaces return, and the promise that every
derived field is already correct in the response that changed it."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_disclosure_artifact,
    assert_terminal_census,
    create_jurisdiction,
    create_merchant,
    create_refund,
    disclosure_artifact_payload,
    file_complaint,
    file_cost_documentation,
    investigation_action,
    issue_refund,
    list_page,
    list_total,
    make_merchant_operator_headers,
    program_status_action_payload,
    provision_terminal,
    read_complaint_case,
    read_merchant,
    read_program,
    read_terminal,
    refund_payload,
    registration_decision_payload,
    remediation_action,
    set_clock,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    setup_program_pending_registration,
    setup_program_with_effective_registration,
    setup_refundable_sale,
    setup_surcharged_sale,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CONTENT_HASH_D, TS_AUG_31
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE

# The clock instant at which the re-pinning update below is issued; the task's
# shared constants stop at the startup default and the month-end boundary.
CLOCK_AUG_05 = "2026-08-05T00:00:00Z"
TS_AUG_05 = "2026-08-05T00:00:00.000Z"

REJECTION_NOTE = "surcharge disclosure package incomplete"


def test_a_paged_terminal_listing_counts_the_whole_filtered_set(api):
    """PRD §2.3: "Every list result is ordered by `created_at` ascending — the oldest row first — and pagination is applied to that ordering. List responses carry `response_type` of `"array"`, and their `meta` object includes `limit` and `offset` as applied, `total_count` giving the number of rows matching the filter before pagination, and `has_more` which is true exactly when rows remain beyond the returned page."
    PRD §3.8: "Terminals may be listed filtered by `merchant_id`, `program_id`, and `state`."

    Design: Corner/endpoints/terminal_listing_composes_the_state_filter_with_pagination
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])
    serials = ["TRM-AZ-9001", "TRM-AZ-9002", "TRM-AZ-9003"]
    provisioned = [provision_terminal(merchant["id"], serial) for serial in serials]
    assert [terminal["state"] for terminal in provisioned] == ["PROVISIONED"] * 3

    first_rows, first_meta = list_page(
        api_client.list_terminals(
            ADMIN,
            params={
                "merchant_id": merchant["id"],
                "state": "PROVISIONED",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_rows) == 2

    second_rows, second_meta = list_page(
        api_client.list_terminals(
            ADMIN,
            params={
                "merchant_id": merchant["id"],
                "state": "PROVISIONED",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_rows) == 1

    paged = [row["serial_number"] for row in first_rows + second_rows]
    assert sorted(paged) == sorted(serials)

    configured_rows, configured_meta = list_page(
        api_client.list_terminals(
            ADMIN, params={"merchant_id": merchant["id"], "state": "CONFIGURED"}
        )
    )
    assert configured_meta["total_count"] == 0
    assert configured_meta["has_more"] is False
    assert configured_rows == []


def test_repinning_a_draft_program_moves_the_cap_to_the_network_ceiling(api):
    """PRD §3.3: "The update recomputes `effective_cap_pct`, re-stamps `cost_documentation_pinned_at` from the logical clock only when `cost_documentation_id` actually changed, and bumps the program's `version` by 1."
    PRD §3.3: "Whichever of the three is smallest binds — a merchant whose documented cost is 2.19 percent is capped at 2.19 even in a state that permits four, while a merchant whose documented cost is 3.05 percent is capped at 3.0 by the network ceiling."

    Design: Corner/endpoints/program_patch_repins_the_cost_documentation_and_recomputes_the_cap
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program = ctx["program"]
    assert program["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)

    set_clock(CLOCK_AUG_05)
    documentation_b = file_cost_documentation(ctx["merchant"]["id"], profile="docB")
    assert documentation_b["documented_cost_pct"] == pytest.approx(3.05, abs=0.0001)

    patched = validate_success(
        api_client.patch_program(
            program["id"],
            {
                "cost_documentation_id": documentation_b["id"],
                "expected_program_version": program["version"],
            },
            OFFICER_ONE,
        )
    )
    assert patched["cost_documentation_id"] == documentation_b["id"]
    assert patched["effective_cap_pct"] == pytest.approx(3.0, abs=0.0001)
    assert patched["cost_documentation_pinned_at"] == TS_AUG_05
    assert patched["status"] == "DRAFT"
    assert patched["version"] == program["version"] + 1

    reread_documentation = validate_success(
        api_client.get_cost_documentation(documentation_b["id"], OFFICER_ONE)
    )
    assert reread_documentation["documented_cost_pct"] == pytest.approx(3.05, abs=0.0001)
    assert reread_documentation["state"] == "ACTIVE"


def test_a_rejected_registration_leaves_the_program_where_it_stood(api):
    """PRD §3.5: "`REJECT` moves `SUBMITTED → REJECTED`, and its side-effect set diverges deliberately from the acknowledge arm: the owning program stays exactly where it is, in `PENDING_REGISTRATION`, and not one program field changes — the program simply can never reach `ACTIVE` through this particular registration and must obtain another."
    PRD §3.5: "Every decision records the auditor's `X-User-ID` as `decided_by_user_id`, stores the supplied note as `decision_note`, and bumps the registration's `version` by 1."

    Design: Corner/endpoints/registration_rejection_leaves_the_program_pending_registration
    """
    ctx = setup_program_pending_registration()
    program_id = ctx["program"]["id"]
    assert ctx["program"]["status"] == "PENDING_REGISTRATION"

    decided = validate_success(
        api_client.decide_network_registration(
            ctx["registration"]["id"],
            registration_decision_payload("REJECT", decision_note=REJECTION_NOTE),
            AUDITOR,
        )
    )
    assert decided["state"] == "REJECTED"
    assert decided["decided_by_user_id"] == "auditor-1"
    assert decided["decision_note"] == REJECTION_NOTE
    assert decided["effective_at"] is None
    assert decided["version"] == ctx["registration"]["version"] + 1

    program = read_program(program_id)
    assert program["status"] == "PENDING_REGISTRATION"
    assert program["version"] == ctx["program"]["version"]
    assert program["disable_reason"] == "NONE"

    assert (
        list_total(
            api_client.list_network_registrations(
                OFFICER_ONE, params={"program_id": program_id, "state": "REJECTED"}
            )
        )
        == 1
    )


def test_a_drafted_artifact_carries_no_attestation_at_all(api):
    """PRD §3.6: "The artifact is created in state `DRAFT` with `effective_from`, `expires_at`, `attested_at`, and `attested_by_user_id` all null, and with `expired_reason` of `NONE`."
    PRD §3.6: "A `MerchantOperator` drafts a disclosure artifact against one of its own programs by naming the `artifact_type` — one of `ENTRY_SIGNAGE`, `POS_SIGNAGE`, `RECEIPT_TEMPLATE`, or `PRICE_LIST_POSTING` — and the `content_hash` of the filed signage or template, which must be exactly 64 lowercase hexadecimal characters."

    Design: Corner/endpoints/disclosure_artifact_creation_links_the_operators_own_program
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]

    created = validate_success(
        api_client.create_disclosure_artifact(
            program_id,
            disclosure_artifact_payload("ENTRY_SIGNAGE", CONTENT_HASH_D),
            make_merchant_operator_headers(ctx["merchant"]["id"]),
        ),
        expected_status=201,
    )
    assert_disclosure_artifact(created)
    assert created["program_id"] == program_id
    assert created["artifact_type"] == "ENTRY_SIGNAGE"
    assert created["content_hash"] == CONTENT_HASH_D
    assert created["state"] == "DRAFT"
    assert created["attested_by_user_id"] is None
    assert created["attested_at"] is None
    assert created["effective_from"] is None
    assert created["expires_at"] is None
    assert created["expired_reason"] == "NONE"
    assert created["version"] == 1

    rows, meta = list_page(
        api_client.list_disclosure_artifacts(
            ADMIN, params={"program_id": program_id, "state": "DRAFT"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [created["id"]]
    assert read_program(program_id)["status"] == "DRAFT"


def test_the_settlement_summary_nets_an_issued_refund_out_of_the_total(api):
    """PRD §3.11: "Finally the summary reports `refunded_surcharge_cents` as the sum of `refund_amount_cents` over refunds in state `ISSUED` that reference an in-scope sale — pending and voided refunds are excluded — and `net_surcharge_cents` as `per_line_rounded_surcharge_cents` minus that refunded total."
    PRD §3.11: "On success the server stamps `issued_at` from the logical clock and `issued_by_user_id` from the acting `X-User-ID`, decreases the merchant's `net_surcharge_collected_cents` by `refund_amount_cents` while leaving `gross_surcharge_collected_cents` completely unchanged, increases the sale's `refunded_surcharge_cents` by the same amount, recomputes the case's `refund_total_cents`, and bumps both the merchant's `version` and the refund's `version` by 1."

    Design: Corner/endpoints/settlement_summary_reports_refunded_and_net_beside_the_gross_total
    """
    ctx = setup_refundable_sale()
    case_id = ctx["complaint_case"]["id"]
    refund = create_refund(case_id, ctx["transaction"]["id"], 100)
    issued = issue_refund(refund["id"])
    assert issued["state"] == "ISSUED"

    summary = validate_success(
        api_client.get_settlement_summary(ctx["program"]["id"], OFFICER_ONE)
    )
    assert summary["transaction_count"] == 1
    assert summary["base_amount_total_cents"] == 10000
    assert summary["per_line_rounded_surcharge_cents"] == 219
    assert summary["pooled_rounding_reference_cents"] == 219
    assert summary["rounding_divergence_cents"] == 0
    assert summary["refunded_surcharge_cents"] == 100
    assert summary["net_surcharge_cents"] == 119

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 119
    assert read_complaint_case(case_id)["refund_total_cents"] == 100


def test_a_refund_filed_before_the_plan_is_accepted_is_refused(api):
    """PRD §3.11: "Creating a refund before the plan is accepted, or after the case has closed, is rejected with `ERR_INVALID_COMPLAINT_STATE`."
    PRD §3.11: "A created refund begins in state `PENDING`, with the creating officer's `X-User-ID` recorded as `created_by_user_id` and with `issued_by_user_id`, `issued_at`, and `voided_at` all null."

    Design: Corner/endpoints/refund_creation_is_locked_until_the_plan_is_accepted
    """
    ctx = setup_surcharged_sale()
    transaction_id = ctx["transaction"]["id"]
    case = file_complaint(ctx["program"]["id"], "CARDHOLDER")
    investigation_action(case["id"], "SUBSTANTIATE", "CARDHOLDER")
    submitted = remediation_action(case["id"], "SUBMIT_PLAN", "CARDHOLDER")
    assert submitted["remediation_state"] == "PLAN_SUBMITTED"

    refused = api_client.create_refund(
        case["id"], refund_payload(transaction_id, 219), OFFICER_ONE
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_COMPLAINT_STATE)

    accepted = remediation_action(case["id"], "ACCEPT_PLAN", "CARDHOLDER")
    assert accepted["remediation_state"] == "PLAN_ACCEPTED"

    created = validate_success(
        api_client.create_refund(
            case["id"], refund_payload(transaction_id, 219), OFFICER_ONE
        ),
        expected_status=201,
    )
    assert created["state"] == "PENDING"
    assert created["refund_amount_cents"] == 219
    assert created["created_by_user_id"] == "officer-1"

    rows, meta = list_page(
        api_client.list_refunds(OFFICER_ONE, params={"complaint_case_id": case["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [created["id"]]


def test_the_activation_response_already_holds_the_recomputed_program(api):
    """PRD §3.7: "`activated_at` is stamped from the logical clock and `activated_by_user_id` from the acting `X-User-ID`; `disable_reason` is set to `NONE`; `effective_cap_pct` is recomputed through the arm of the cap calculation matching the program's `program_type`; `disclosure_ready` is recomputed; and the program's `version` is bumped by 1."
    PRD §2.11: "This service maintains several derived aggregates, and the correctness bar is that they are consistent immediately after every single mutation — there is no deferred reconciliation, no eventual convergence, and no background sweep."

    Design: Corner/consistency_model/activation_response_already_carries_the_recomputed_cap_and_readiness
    """
    ctx = setup_program_with_effective_registration(jurisdiction_profile="AZ")
    before = ctx["program"]

    response = api_client.activate_program(before["id"], OFFICER_ONE)
    activated = validate_success(response)
    assert response.status_code == 200
    assert activated["status"] == "ACTIVE"
    assert activated["disable_reason"] == "NONE"
    assert activated["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)
    assert activated["disclosure_ready"] is True
    assert activated["activated_at"] == TS_AUG_31
    assert activated["activated_by_user_id"] == "officer-1"
    assert activated["version"] == before["version"] + 1

    reread = read_program(before["id"])
    for field in (
        "status",
        "effective_cap_pct",
        "disclosure_ready",
        "activated_at",
        "version",
    ):
        assert reread[field] == activated[field], field

    rows, meta = list_page(api_client.list_programs(ADMIN, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [before["id"]]


def test_the_suspension_response_and_the_reads_that_follow_it_agree(api):
    """PRD §3.7: "Its cascade runs in two steps: first, every `Terminal` of the program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_SUSPENDED`; second, each such terminal transition recomputes `enforcing_terminal_count` on that terminal's merchant."
    PRD §2.11: "A request either completes with every derived field it touches recomputed, or it fails and changes nothing."

    Design: Corner/consistency_model/suspension_response_and_the_immediate_reads_agree_on_the_cascade
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=1)
    merchant_id = ctx["merchant"]["id"]
    terminal_id = ctx["terminal"]["id"]
    assert_terminal_census(read_merchant(merchant_id), 1)

    suspended = validate_success(
        api_client.program_status_action(
            ctx["program"]["id"],
            program_status_action_payload("SUSPEND", reason="network inquiry pending"),
            OFFICER_ONE,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["disable_reason"] == "OPERATOR_SUSPENSION"

    terminal = read_terminal(terminal_id)
    assert terminal["state"] == "QUARANTINED"
    assert terminal["quarantine_reason"] == "PROGRAM_SUSPENDED"
    assert_terminal_census(read_merchant(merchant_id), 0)

    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"merchant_id": merchant_id, "state": "ENFORCING"}
            )
        )
        == 0
    )
