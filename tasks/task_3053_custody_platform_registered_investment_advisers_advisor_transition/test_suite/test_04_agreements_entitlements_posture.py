"""Custody agreement lifecycle, entitlement authority and derived firm posture."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    make_advisor_ops_headers,
    make_custody_officer_headers,
    make_compliance_headers,
    setup_firm_with_agreement,
    setup_firm,
    refetch_firm,
    setup_supersession_scenario,
    setup_deficient_firm,
    setup_multi_hop_cascade_scenario,
    setup_terminated_agreement_scenario,
    setup_revoked_entitlement_scenario,
    setup_account_at_evidence_ceiling,
    setup_custody_evidence,
    refetch_evidence,
    refetch_agreement,
    refetch_entitlement,
)
"""Custody agreement lifecycle, entitlement authority and derived firm posture."""
"""Custody agreement lifecycle, entitlement authority and derived firm posture."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestCustodyAgreementLifecycle:

    def test_submit_records_the_drafter_and_revert_clears_it(self):
        """PRD §3.1: "On success the request's `X-User-ID` is recorded into
        `drafted_by_user_id`, which is the segregation-of-duties stamp that §2.5
        compares against later."
        PRD §3.1: "The drafter may revert it from `PENDING_SIGNATURE` to `DRAFT`,
        which clears `drafted_by_user_id` and nulls the submission stamp".

        Design: Corner/state_machines/custody_agreement_submit_and_revert_round_trip
        """
        firm = setup_firm()
        draft = validate_success(api_client.create_custody_agreement(
            firm["id"], {"adviser_crd_number": firm["crd_number"]}, ADVISOR,
        ), 201)
        submitted = validate_success(
            api_client.submit_custody_agreement(draft["id"], {}, ADVISOR, row=draft), 200
        )
        assert submitted["agreement_status"] == "PENDING_SIGNATURE"
        assert submitted["drafted_by_user_id"] is not None

        reverted = validate_success(
            api_client.revert_custody_agreement(draft["id"], {}, ADVISOR, row=refetch_agreement(draft["id"])), 200
        )
        assert reverted["agreement_status"] == "DRAFT"
        assert reverted["drafted_by_user_id"] is None
        assert refetch_firm(firm["id"])["firm_posture"] == "SUSPENDED"

    def test_executing_twice_leaves_the_first_countersignature_intact(self):
        """PRD §3.1: "a submission against any other state is refused with
        `ERR_INVALID_STATE` (HTTP 409)".
        PRD §2.4: "if the firm has no executed agreement at this point, the posture
        derivation of §2.4 lands on rule 1 and the firm is born `SUSPENDED`".

        Design: Corner/state_machines/custody_agreement_invalid_from_draft_execute
        """
        firm = setup_firm()
        draft = validate_success(api_client.create_custody_agreement(
            firm["id"], {"adviser_crd_number": firm["crd_number"]}, ADVISOR,
        ), 201)
        validate_success(api_client.submit_custody_agreement(draft["id"], {}, ADVISOR, row=draft), 200)
        executed = validate_success(
            api_client.execute_custody_agreement(firm["id"], {}, CUSTODY, row=refetch_agreement(draft["id"])), 200
        )
        assert executed["agreement_status"] == "EXECUTED"
        original_hash = executed["countersignature_hash"]

        res = api_client.execute_custody_agreement(firm["id"], {}, CUSTODY, row=executed)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

        unchanged = validate_success(
            api_client.get_custody_agreement(executed["id"], ADVISOR), 200
        )
        assert unchanged["agreement_status"] == "EXECUTED"
        assert unchanged["countersignature_hash"] == original_hash
        assert refetch_firm(firm["id"])["firm_posture"] == "OPEN"

    def test_a_terminated_agreement_refuses_every_further_action(self):
        """PRD §3.1: "and `TERMINATED` is terminal."
        PRD §3.1: "Termination is the final agreement transition and the most
        constrained. It is only available on the firm's current agreement, only from
        `EXECUTED`, and only when the firm has zero `HouseholdAccount` rows whose
        `account_status` is `OPEN`".

        Design: Corner/state_machines/custody_agreement_terminal_terminated_locks_actions
        """
        scenario = setup_terminated_agreement_scenario()
        assert scenario["agreement"]["agreement_status"] == "TERMINATED"

        res = api_client.revert_custody_agreement(scenario["agreement"]["id"], {}, ADVISOR, row=scenario["agreement"])
        validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)

        unchanged = validate_success(
            api_client.get_custody_agreement(scenario["agreement"]["id"], ADVISOR), 200
        )
        assert unchanged["agreement_status"] == "TERMINATED"
        firm = refetch_firm(scenario["firm"]["id"])
        assert firm["firm_posture"] == "SUSPENDED"
        assert firm["posture_reason_code"] == "CUSTODY_AGREEMENT_TERMINATED"


class TestEntitlementAuthority:

    def test_a_revoked_entitlement_refuses_a_repeat_revoke_but_reopens(self):
        """PRD §3.2: "Revocation is reserved to a `ComplianceReviewer` and — on the
        explicit path — is available only from `SUSPENDED`".
        PRD §3.2: "An `AdvisorOperationsLead` returns a `REVOKED` entitlement to
        `REQUESTED`, which re-points `requested_custody_agreement_id` at the firm's
        current executed agreement and sets `payload_integrity_verified` back to
        true."

        Design: Corner/state_machines/entitlement_revoke_and_reopen_cycle
        """
        scenario = setup_revoked_entitlement_scenario()
        entitlement = scenario["entitlement"]
        assert entitlement["entitlement_status"] == "REVOKED"

        res = api_client.revoke_entitlement(entitlement["id"], {}, COMPLIANCE, row=entitlement)
        validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)

        reopened = validate_success(
            api_client.reopen_entitlement(entitlement["id"], {}, ADVISOR, row=refetch_entitlement(entitlement["id"])), 200
        )
        assert reopened["entitlement_status"] == "REQUESTED"
        assert reopened["requested_custody_agreement_id"] == scenario["agreement"]["id"]
        assert reopened["payload_integrity_verified"] is True
        assert refetch_firm(scenario["firm"]["id"])["entitlement_count"] == 0

    def test_granting_a_second_identical_entitlement_is_refused(self):
        """PRD §3.2: "Finally, no sibling `AdvisorFirmEntitlement` of the same firm
        may already hold the same `entitlement_code` in `GRANTED`; a duplicate is
        refused with `ERR_ENTITLEMENT_DUPLICATE` (HTTP 409)".

        Design: Corner/validations/entitlement_duplicate_rejected_only_for_granted_siblings
        """
        firm, agreement = setup_firm_with_agreement()
        first = validate_success(api_client.create_entitlement(
            {"firm_id": firm["id"], "entitlement_code": "BILLING",
             "requested_custody_agreement_id": agreement["id"]}, ADVISOR,
        ), 201)
        second = validate_success(api_client.create_entitlement(
            {"firm_id": firm["id"], "entitlement_code": "BILLING",
             "requested_custody_agreement_id": agreement["id"]}, ADVISOR,
        ), 201)

        validate_success(api_client.grant_entitlement(first["id"], {}, CUSTODY, row=first), 200)
        assert refetch_firm(firm["id"])["entitlement_count"] == 1

        res = api_client.grant_entitlement(second["id"], {}, CUSTODY, row=second)
        validate_error(res, "ERR_ENTITLEMENT_DUPLICATE", expected_status=409)
        assert validate_success(
            api_client.get_entitlement(second["id"], ADVISOR), 200
        )["entitlement_status"] == "REQUESTED"


class TestSegregationOfDuties:

    def test_the_drafter_cannot_countersign_their_own_agreement(self):
        """PRD §2.5: "countersigning a custody agreement, where the executing officer
        must differ from `drafted_by_user_id`".
        PRD §3.1: "the executing officer must differ from `drafted_by_user_id` (a
        same-officer attempt is refused with `ERR_SOD_VIOLATION`, HTTP 403, per §2.5)".

        Design: Corner/validations/sod_violation_when_drafter_executes_own_agreement
        """
        firm = setup_firm()
        draft = validate_success(api_client.create_custody_agreement(
            firm["id"], {"adviser_crd_number": firm["crd_number"]},
            make_advisor_ops_headers("operator-lead-1"),
        ), 201)
        validate_success(api_client.submit_custody_agreement(
            draft["id"], {}, make_advisor_ops_headers("operator-lead-1"), row=draft), 200)

        res = api_client.execute_custody_agreement(
            firm["id"], {}, make_custody_officer_headers("operator-lead-1"), row=refetch_agreement(draft["id"]))
        validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)

        still_pending = validate_success(
            api_client.get_custody_agreement(draft["id"], ADVISOR), 200
        )
        assert still_pending["agreement_status"] == "PENDING_SIGNATURE"
        assert refetch_firm(firm["id"])["firm_posture"] == "SUSPENDED"

        executed = validate_success(api_client.execute_custody_agreement(
            firm["id"], {}, make_custody_officer_headers("custody-officer-7"), row=refetch_agreement(draft["id"])), 200)
        assert executed["agreement_status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "custody-officer-7"
        assert executed["executed_by_user_id"] != executed["drafted_by_user_id"]

    def test_a_reviewer_cannot_accept_the_evidence_they_submitted(self):
        """PRD §2.5: "accepting custody evidence, where the accepting officer must
        differ from the submitter recorded in `drafted_by_user_id`".

        Design: Corner/rbac/segregation_of_duties_blocks_self_acceptance_of_evidence
        """
        firm, agreement = setup_firm_with_agreement()
        evidence = setup_custody_evidence(
            firm["id"], requirement_code="CLIENT_NOTIFICATION", critical=True,
            submit_as="reviewer-5",
        )
        assert evidence["requirement_status"] == "SUBMITTED"

        res = api_client.accept_custody_evidence(
            evidence["id"], {}, make_compliance_headers("reviewer-5"), row=evidence)
        validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)
        assert refetch_evidence(evidence["id"])["requirement_status"] == "SUBMITTED"

        accepted = validate_success(api_client.accept_custody_evidence(
            evidence["id"], {}, make_compliance_headers("reviewer-9"), row=evidence), 200)
        assert accepted["requirement_status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "reviewer-9"
        assert accepted["evidence_document_hash"] is not None


class TestPostureCascade:

    def test_a_critical_deficiency_cascades_through_four_hops(self):
        """PRD §3.9: "the posture derivation runs, dropping an `OPEN` firm with a
        critical deficient row to `LIMITED`; and that `LIMITED` posture in turn
        suspends the firm's `MODEL_MANAGEMENT` and `ALTERNATIVE_ASSETS`
        entitlements".
        PRD §3.2: "the feed moves from `ACTIVE` to `THROTTLED` whenever the firm's
        posture is `LIMITED`, `SUSPENDED` or `FROZEN`".

        Design: Difficulty/transitive_cascade/custody_evidence_deficiency_four_hop_cascade
        """
        scenario = setup_multi_hop_cascade_scenario()
        firm = scenario["firm"]

        validate_success(api_client.reject_custody_evidence(
            scenario["evidence"]["id"],
            {"deficiency_reason_code": "CUSTODIAN_STATEMENT_EXPIRED"}, COMPLIANCE, row=scenario["evidence"]), 200)

        hop1 = refetch_firm(firm["id"])
        assert hop1["firm_posture"] == "LIMITED"
        assert hop1["posture_reason_code"] == "CUSTODY_EVIDENCE_DEFICIENT"

        feeds = validate_success(
            api_client.list_firm_data_feeds(firm["id"], COMPLIANCE), 200
        )
        assert feeds[0]["provision_status"] == "THROTTLED"
        assert feeds[0]["throttle_reason_code"] == "CUSTODY_EVIDENCE_DEFICIENT"

        entitlements = validate_success(
            api_client.list_firm_entitlements(firm["id"], COMPLIANCE), 200
        )
        model_entitlement = next(
            e for e in entitlements if e["entitlement_code"] == "MODEL_MANAGEMENT"
        )
        assert model_entitlement["entitlement_status"] == "SUSPENDED"

        model = validate_success(
            api_client.get_model(scenario["model"]["id"], TEST_USERS["admin_headers"]), 200
        )
        assert model["model_status"] == "REBALANCING"

    def test_a_throttled_feed_refuses_a_pull(self):
        """PRD §3.2: "Pulling a page from a feed is where the throttle becomes
        visible. The request carries `limit` and `offset` and is refused with
        `ERR_FEED_THROTTLED` (HTTP 409) if the feed's `provision_status` is
        `THROTTLED`."

        Design: Difficulty/transitive_cascade/custody_evidence_deficiency_four_hop_cascade
        """
        scenario = setup_multi_hop_cascade_scenario()
        validate_success(api_client.reject_custody_evidence(
            scenario["evidence"]["id"],
            {"deficiency_reason_code": "CUSTODIAN_STATEMENT_EXPIRED"}, COMPLIANCE, row=scenario["evidence"]), 200)

        res = api_client.pull_data_feed(scenario["feed"]["id"], {}, ADVISOR)
        validate_error(res, "ERR_FEED_THROTTLED", expected_status=409)

    def test_a_limited_firm_returns_to_open_when_its_critical_evidence_is_accepted(self):
        """PRD §3.9: "The evidence rollup is recomputed, and the posture derivation
        runs one more hop: a firm sitting in `LIMITED` whose critical evidence has
        all been accepted returns to `OPEN`."

        Design: Difficulty/transitive_cascade/custody_evidence_deficiency_four_hop_cascade
        """
        firm, agreement, evidence = setup_deficient_firm()
        assert refetch_firm(firm["id"])["firm_posture"] == "LIMITED"

        validate_success(api_client.resubmit_custody_evidence(evidence["id"], {}, ADVISOR, row=evidence), 200)
        validate_success(api_client.accept_custody_evidence(evidence["id"], {}, COMPLIANCE, row=refetch_evidence(evidence["id"])), 200)

        restored = refetch_firm(firm["id"])
        assert restored["firm_posture"] == "OPEN"
        assert restored["posture_reason_code"] is None
        assert restored["supervision_evidence_status"] == "CLEAR"


class TestEvidenceCorrectionCeiling:

    def test_the_fifth_resubmission_is_refused_at_the_round_ceiling(self):
        """PRD §2.11: "`evidence_round_number` starts at 0 and increments on every
        transition from `SUBMITTED` to `DEFICIENT`; a row sitting at 4 may not be
        resubmitted, and an attempt to do so is refused with
        `ERR_EVIDENCE_ROUND_LIMIT` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/custody_evidence_correction_cycle_capped_at_four_rounds
        """
        scenario = setup_account_at_evidence_ceiling()
        evidence = scenario["evidence"]
        assert evidence["evidence_round_number"] == 4

        res = api_client.resubmit_custody_evidence(evidence["id"], {}, ADVISOR, row=evidence)
        validate_error(res, "ERR_EVIDENCE_ROUND_LIMIT", expected_status=409)
        assert refetch_evidence(evidence["id"])["requirement_status"] == "DEFICIENT"

    def test_the_ceiling_leaves_the_firm_limited_and_deficient(self):
        """PRD §3.9: "the firm's `supervision_evidence_status` becomes `DEFICIENT`;
        the posture derivation runs, dropping an `OPEN` firm with a critical
        deficient row to `LIMITED`".

        Design: Difficulty/non_linear_state_machine/custody_evidence_correction_cycle_capped_at_four_rounds
        """
        scenario = setup_account_at_evidence_ceiling()
        firm = refetch_firm(scenario["firm"]["id"])
        assert firm["firm_posture"] == "LIMITED"
        assert firm["posture_reason_code"] == "CUSTODY_EVIDENCE_DEFICIENT"
        assert firm["supervision_evidence_status"] == "DEFICIENT"