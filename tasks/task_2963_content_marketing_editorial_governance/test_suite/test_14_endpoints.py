"""
The endpoint surface: creates, reads, filtered lists, named actions and one batch.

The service exposes reads and posts only, so every mutation of a stored row runs
through a named action endpoint whose preconditions are part of the contract.
These cases exercise those actions and the computed reads they produce.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ASSET_RENEWAL_NOT_EXTENDING,
    ERR_ASSET_STATE_INVALID,
    ERR_PRUNE_NOT_ELIGIBLE,
    ERR_REFRESH_NOT_REQUIRED,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_gate,
    assert_immutable_row,
    assert_instant_precision,
    assert_list_response,
    assert_no_op_sweep,
    assert_posture,
    assert_slot_commitment,
    assert_sweep_tally,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    ACCESSIBILITY_REVIEWER,
    BRAND_REVIEWER,
    EDITOR_ONE_ID,
    LEGAL_REVIEWER,
    LEGAL_REVIEWER_ID,
    MANAGING_EDITOR,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
ASSET_CLOCK = "2026-08-03T00:00:00.000Z"


class TestAssetSurface:
    """Assets offer create, read and filtered list, and nothing else."""

    def test_assets_expose_create_read_and_list_only(self, flow):
        """
        Three assets, one of each type, are created and read back: the stored licence
        fields come back verbatim on the single read, the type filter narrows the
        collection to one row, and the status filter returns all three, with the whole
        collection fitting inside the default page.

        Design: Corner/endpoints/assets_expose_create_read_and_list_only_with_no_update_or_delete_verb
        """
        flow.set_clock(ASSET_CLOCK)

        stock = validate_success(
            flow.api.create_asset(
                f.asset_payload(
                    name="Zero trust hero photo",
                    asset_type="STOCK",
                    license_start="2026-07-01T00:00:00.000Z",
                    license_end="2027-01-01T00:00:00.000Z",
                    licensed_channels=["OWNED", "EMAIL"],
                    max_licensed_uses=5,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        talent = validate_success(
            flow.api.create_asset(
                f.asset_payload(
                    name="Analyst spokesperson clip",
                    asset_type="TALENT",
                    license_start="2026-07-01T00:00:00.000Z",
                    license_end="2027-01-01T00:00:00.000Z",
                    licensed_channels=["SOCIAL"],
                    max_licensed_uses=2,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        original = validate_success(
            flow.api.create_asset(
                f.asset_payload(
                    name="In-house architecture diagram",
                    asset_type="ORIGINAL",
                    license_start="2026-07-01T00:00:00.000Z",
                    license_end="2027-01-01T00:00:00.000Z",
                    licensed_channels=["OWNED"],
                    max_licensed_uses=9,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert stock["version"] == 1
        assert_instant_precision(stock["created_at"])

        read_back = validate_success(flow.api.get_asset(stock["id"], MANAGING_EDITOR))
        assert read_back["name"] == "Zero trust hero photo"
        assert read_back["licensed_channels"] == ["OWNED", "EMAIL"]
        assert read_back["status"] == "LICENSED"

        talent_rows = assert_list_response(
            flow.api.list_assets(BRAND_REVIEWER, {"asset_type": "TALENT"}),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert talent_rows[0]["id"] == talent["id"]
        assert_list_response(
            flow.api.list_assets(MANAGING_EDITOR, {"status": "LICENSED"}),
            expected_total_count=3,
            expected_row_count=3,
        )
        assert_list_response(
            flow.api.list_assets(MANAGING_EDITOR),
            expected_total_count=3,
            expected_has_more=False,
            expected_limit=10,
            expected_offset=0,
        )
        assert_asset_rights(
            flow.read_asset(original["id"]), remaining_licensed_uses=9
        )


class TestExpertAvailabilityAction:
    """The availability action flips the status and moves the version, nothing else."""

    def test_availability_round_trip_bumps_the_version_twice(self, flow):
        """
        An expert holding no briefs goes on leave and comes back: each call moves the
        status and the version, the weekly ledger stays at zero through both directions,
        and the status filter follows the expert from one bucket to the other.

        Design: Corner/endpoints/expert_availability_action_toggles_status_and_bumps_version_with_no_dependents
        """
        flow.set_clock(SETUP_CLOCK)
        expert = flow.create_expert(["security"], weekly_capacity_hours=40)
        assert expert["version"] == 1

        on_leave = validate_success(
            flow.api.set_expert_availability(expert["id"], "ON_LEAVE", MANAGING_EDITOR)
        )
        assert on_leave["status"] == "ON_LEAVE"
        assert on_leave["version"] == 2
        assert on_leave["committed_hours_total"] == 0

        available = validate_success(
            flow.api.set_expert_availability(expert["id"], "AVAILABLE", MANAGING_EDITOR)
        )
        assert available["status"] == "AVAILABLE"
        assert available["version"] == 3
        assert available["expertise_tags"] == ["security"]

        rows = assert_list_response(
            flow.api.list_experts(MANAGING_EDITOR, {"status": "AVAILABLE"}),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert rows[0]["id"] == expert["id"]
        assert_list_response(
            flow.api.list_experts(MANAGING_EDITOR, {"status": "ON_LEAVE"}),
            expected_total_count=0,
            expected_row_count=0,
        )


class TestEvidenceDossier:
    """Evidence rows link to one claim and the decision freezes the earliest expiry."""

    def test_evidence_links_to_its_claim_and_the_decision_freezes_the_earliest_expiry(
        self, flow
    ):
        """
        Two rows of different source types carry their own immutable weights, the first
        drags the claim out of draft into evidence review, and substantiation freezes the
        expiry at the earliest contributing row rather than the latest or the deciding
        one.

        Design: Corner/endpoints/evidence_links_to_its_claim_and_the_legal_decision_freezes_the_earliest_valid_until
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        claim = flow.create_claim(item_id, claim_type="PERFORMANCE")
        assert_two_decimal_value(claim["required_score"], 2.00)

        first = validate_success(
            flow.api.file_evidence(
                claim["id"],
                f.evidence_payload(
                    source_type="THIRD_PARTY_TEST",
                    citation="Northwind Labs comparative benchmark, June 2026, table 4",
                    collected_at="2026-06-01T00:00:00.000Z",
                    valid_until="2027-06-01T00:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert first["weight"] == 2.0
        assert first["submitted_by_user_id"] == EDITOR_ONE_ID
        assert first["claim_id"] == claim["id"]
        assert_immutable_row(first)

        after_first = validate_success(
            flow.api.get_claim(claim["id"], LEGAL_REVIEWER)
        )
        assert after_first["substantiation_state"] == "EVIDENCE_PENDING"
        assert_two_decimal_value(after_first["evidence_score"], 2.00)

        second = validate_success(
            flow.api.file_evidence(
                claim["id"],
                f.evidence_payload(
                    source_type="CUSTOMER_DATA",
                    citation="Aggregated telemetry from 42 opted-in accounts, July 2026",
                    collected_at="2026-07-01T00:00:00.000Z",
                    valid_until="2026-12-01T00:00:00.000Z",
                ),
                expert_headers(chain["expert_id"]),
            ),
            201,
        )
        assert second["weight"] == 0.5

        decided = validate_success(
            flow.api.decide_claim(claim["id"], "SUBSTANTIATED", LEGAL_REVIEWER)
        )
        assert decided["substantiation_state"] == "SUBSTANTIATED"
        assert_two_decimal_value(decided["evidence_score"], 2.50)
        assert decided["evidence_valid_until"] == "2026-12-01T00:00:00.000Z"
        assert decided["decided_by_user_id"] == LEGAL_REVIEWER_ID
        assert decided["decided_at"] == SETUP_CLOCK

        assert_list_response(
            flow.api.list_claim_evidence(claim["id"], MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )
        filtered = assert_list_response(
            flow.api.list_claim_evidence(
                claim["id"], MANAGING_EDITOR, {"source_type": "CUSTOMER_DATA"}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert filtered[0]["id"] == second["id"]
        assert_campaign_counters(
            flow.read_campaign(chain["campaign"]["id"]),
            unsubstantiated_published_claim_count=0,
        )


class TestGateTurnaroundRead:
    """Turnaround is derived on read from the decision instant, not stored at fan-out."""

    def test_turnaround_hours_is_computed_with_fractional_precision(self, flow):
        """
        One gate decided ninety minutes after fan-out reads an hour and a half and
        another decided eighteen and a quarter hours in reads exactly that, both well
        inside their deadlines, while the gate still open reports no turnaround at all.

        Design: Corner/endpoints/review_gate_turnaround_hours_is_a_computed_read_with_fractional_precision
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        flow.submit(item_id)
        sme_gate = flow.gate_of(item_id, "SME")
        brand_gate = flow.gate_of(item_id, "BRAND")
        accessibility_gate = flow.gate_of(item_id, "ACCESSIBILITY")

        flow.set_clock("2026-08-03T09:30:00.000Z")
        validate_success(
            flow.api.decide_review_gate(
                sme_gate["id"], "APPROVED", expert_headers(chain["expert_id"])
            )
        )
        sme_read = validate_success(
            flow.api.get_review_gate(sme_gate["id"], MANAGING_EDITOR)
        )
        assert_gate(
            sme_read, sla_hours=30, turnaround_hours=1.50, sla_breached=False
        )
        assert sme_read["decided_at"] == "2026-08-03T09:30:00.000Z"

        flow.set_clock("2026-08-04T02:15:00.000Z")
        validate_success(
            flow.api.decide_review_gate(
                accessibility_gate["id"], "APPROVED", ACCESSIBILITY_REVIEWER
            )
        )
        accessibility_read = validate_success(
            flow.api.get_review_gate(accessibility_gate["id"], MANAGING_EDITOR)
        )
        assert_gate(
            accessibility_read, sla_hours=45, turnaround_hours=18.25, sla_breached=False
        )

        brand_read = validate_success(
            flow.api.get_review_gate(brand_gate["id"], MANAGING_EDITOR)
        )
        assert_gate(brand_read, state="PENDING")
        assert brand_read["turnaround_hours"] is None
        assert flow.read_item(item_id)["workflow_state"] == "IN_REVIEW"
        assert_list_response(
            flow.api.list_review_gates(item_id, MANAGING_EDITOR, {"state": "APPROVED"}),
            expected_total_count=2,
            expected_row_count=2,
        )


class TestConditionalLifecycleActions:
    """Refresh and prune are gated on the refresh flag and the audit verdict."""

    def test_refresh_and_prune_follow_the_flag_and_the_verdict(self, flow):
        """
        A healthy published piece refuses both refresh and prune; a decay audit on an
        empty measurement history returns keep and changes nothing, so prune is still
        refused; only an accuracy finding of inaccurate raises the refresh flag and moves
        the piece, at which point refresh succeeds and voids the whole review fork while
        the calendar commitment stays where it is.

        Design: Corner/endpoints/refresh_and_prune_are_conditional_on_the_refresh_flag_and_the_audit_verdict
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.published_item(
            funnel_stage="DECISION", persona="IT_BUYER", channels=["OWNED"]
        )
        item_id = chain["item"]["id"]
        assert chain["item"]["workflow_state"] == "PUBLISHED"
        assert chain["item"]["commit_points"] == 16

        validate_error(
            flow.api.refresh_content_item(item_id, MANAGING_EDITOR),
            ERR_REFRESH_NOT_REQUIRED,
            409,
        )
        validate_error(
            flow.api.prune_content_item(item_id, MANAGING_EDITOR),
            ERR_PRUNE_NOT_ELIGIBLE,
            409,
        )

        decay_audit = validate_success(
            flow.api.audit_content_item(
                item_id, f.audit_payload(audit_type="DECAY"), MANAGING_EDITOR
            )
        )
        assert_two_decimal_value(decay_audit["decay_pct"], 0.00)
        assert decay_audit["last_audit_verdict"] == "KEEP"
        assert decay_audit["workflow_state"] == "PUBLISHED"
        assert decay_audit["last_audit_at"] == SETUP_CLOCK

        validate_error(
            flow.api.prune_content_item(item_id, MANAGING_EDITOR),
            ERR_PRUNE_NOT_ELIGIBLE,
            409,
        )

        accuracy_audit = validate_success(
            flow.api.audit_content_item(
                item_id,
                f.audit_payload(audit_type="ACCURACY", accuracy_finding="INACCURATE"),
                MANAGING_EDITOR,
            )
        )
        assert accuracy_audit["accuracy_status"] == "INACCURATE"
        assert accuracy_audit["last_audit_verdict"] == "REFRESH"
        assert accuracy_audit["refresh_required"] is True
        assert accuracy_audit["workflow_state"] == "NEEDS_REFRESH"

        refreshed = validate_success(
            flow.api.refresh_content_item(item_id, MANAGING_EDITOR)
        )
        assert refreshed["workflow_state"] == "DRAFT"
        assert refreshed["published_at"] is None

        assert_list_response(
            flow.api.list_review_gates(item_id, MANAGING_EDITOR, {"state": "VOIDED"}),
            expected_total_count=3,
            expected_row_count=3,
        )
        assert_list_response(
            flow.api.list_distributions(
                item_id, MANAGING_EDITOR, {"state": "RETRACTED"}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00)
        assert_campaign_counters(
            flow.read_campaign(chain["campaign"]["id"]), committed_points_total=16
        )


class TestAssetRenewalAction:
    """Renewal must strictly extend, and it is only declared from a lapsing licence."""

    def test_renewal_must_strictly_extend_and_is_refused_once_relicensed(self, flow):
        """
        Renewing to the instant the licence already ends is refused and so is any earlier
        date, both as a non-extending renewal rather than a shape error; a single
        millisecond of extension is accepted and stamps the licence healthy again, which
        makes an immediate second renewal an undeclared transition.

        Design: Corner/endpoints/asset_renewal_must_strictly_extend_past_both_the_clock_and_the_current_license_end
        """
        flow.set_clock(ASSET_CLOCK)
        asset = validate_success(
            flow.api.create_asset(
                f.asset_payload(
                    name="Zero trust hero photo",
                    asset_type="STOCK",
                    license_start="2026-07-01T00:00:00.000Z",
                    license_end="2026-09-02T00:00:00.000Z",
                    licensed_channels=["OWNED"],
                    max_licensed_uses=3,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert asset["status"] == "EXPIRING"
        assert asset["version"] == 1

        validate_error(
            flow.api.renew_asset(
                asset["id"], "2026-09-02T00:00:00.000Z", MANAGING_EDITOR
            ),
            ERR_ASSET_RENEWAL_NOT_EXTENDING,
            422,
        )
        validate_error(
            flow.api.renew_asset(
                asset["id"], "2026-08-01T00:00:00.000Z", MANAGING_EDITOR
            ),
            ERR_ASSET_RENEWAL_NOT_EXTENDING,
            422,
        )
        untouched = flow.read_asset(asset["id"])
        assert untouched["license_end"] == "2026-09-02T00:00:00.000Z"
        assert untouched["version"] == 1

        renewed = validate_success(
            flow.api.renew_asset(
                asset["id"], "2026-09-02T00:00:00.001Z", MANAGING_EDITOR
            )
        )
        assert renewed["license_end"] == "2026-09-02T00:00:00.001Z"
        assert renewed["status"] == "LICENSED"
        assert renewed["version"] == 2

        validate_error(
            flow.api.renew_asset(
                asset["id"], "2027-01-01T00:00:00.000Z", MANAGING_EDITOR
            ),
            ERR_ASSET_STATE_INVALID,
            409,
        )
        final = flow.read_asset(asset["id"])
        assert final["license_end"] == "2026-09-02T00:00:00.001Z"
        assert final["version"] == 2
        assert_asset_rights(final, active_use_count=0, remaining_licensed_uses=3)
        assert_list_response(
            flow.api.list_asset_usages(asset["id"], MANAGING_EDITOR),
            expected_total_count=0,
            expected_row_count=0,
        )


class TestGovernanceSweepReplay:
    """The one batch endpoint activates what is due and is a no-op when replayed."""

    def test_sweep_activates_only_due_distributions_and_replays_as_a_no_op(self, flow):
        """
        With nothing else for the sweep to do, the first pass reports exactly one
        activation and eight zeroes, and a second pass at the unmoved clock reports nine
        zeroes while leaving the go-live stamp at its first value.

        Design: Corner/endpoints/governance_sweep_activates_only_due_distributions_and_replays_as_a_no_op
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.published_item(
            funnel_stage="DECISION", persona="IT_BUYER", channels=["OWNED"],
            scheduled_at="2026-08-05T09:00:00.000Z",
        )
        item_id = chain["item"]["id"]
        before = flow.distributions(item_id)
        assert len(before) == 1
        assert before[0]["state"] == "SCHEDULED"

        flow.set_clock("2026-08-05T09:00:00.000Z")
        first_sweep = flow.sweep()
        assert_sweep_tally(first_sweep, distributions_activated=1)
        after_first = flow.distributions(item_id)
        assert after_first[0]["state"] == "LIVE"
        assert after_first[0]["went_live_at"] == "2026-08-05T09:00:00.000Z"

        second_sweep = flow.sweep()
        assert_no_op_sweep(second_sweep)
        after_second = flow.distributions(item_id)
        assert after_second[0]["state"] == "LIVE"
        assert after_second[0]["went_live_at"] == "2026-08-05T09:00:00.000Z"
        assert after_second[0]["suppression_reason"] is None
        assert flow.read_item(item_id)["workflow_state"] == "PUBLISHED"
        assert_posture(flow.read_campaign(chain["campaign"]["id"]), "OPEN")
