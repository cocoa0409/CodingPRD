"""
Role boundaries: every endpoint admits exactly the roles named on its own row.

The role check is per-endpoint rather than a seniority ladder, so the busiest
role in the service is still refused on the three endpoints it does not appear
on. The measurement role is the mirror image: it is the only writer of
performance snapshots and holds three item reads, while the whole governance
surface is closed to it. The third case walks the legal segregation rule across
every claim decider on a piece rather than only the most recent one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_SOD_LEGAL_CONFLICT, ERR_UNAUTHORIZED
from test_helpers.assertions import (
    assert_bare_uuid,
    assert_gate,
    assert_integer_value,
    assert_list_response,
    assert_two_decimal_value,
    assert_version,
)
from test_helpers.test_users import (
    ACCESSIBILITY_REVIEWER,
    ANALYTICS_SERVICE,
    BRAND_REVIEWER,
    LEGAL_ONE_ID,
    LEGAL_REVIEWER,
    LEGAL_REVIEWER_ONE,
    LEGAL_REVIEWER_THREE,
    LEGAL_REVIEWER_TWO,
    LEGAL_THREE_ID,
    LEGAL_TWO_ID,
    MANAGING_EDITOR,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
ITEM_TITLE = "Zero trust login guide"
PLANNED_PUBLISH = "2026-08-05T09:00:00.000Z"
PERFORMANCE_CLAIM = (
    "Median deployment finishes 30 percent faster than the previous release."
)
COMPARISON_CLAIM = "Our detection coverage exceeds the two leading competing platforms."


def _draft_item_chain(flow, code):
    """An ACTIVE campaign, an APPROVED brief and one DRAFT item created by me-1."""
    campaign = flow.active_campaign(
        code=code, persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
    )
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="AWARENESS",
        capacity_points=40,
    )
    brief, expert_id = flow.approved_brief(
        campaign["id"],
        funnel_stage="AWARENESS",
        effort_points=6,
        expertise_tag="security",
    )
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        title=ITEM_TITLE,
        planned_publish_at=PLANNED_PUBLISH,
    )
    return {
        "campaign": campaign,
        "slot": slot,
        "brief": brief,
        "expert_id": expert_id,
        "item": item,
    }


class TestExclusiveWriteDenials:
    """A role absent from an endpoint's row is refused there, seniority aside."""

    def test_every_exclusive_write_refuses_the_other_roles_with_one_shared_code(
        self, flow
    ):
        """
        Seven writes attempted by a role the endpoint does not name are all refused
        with the same 403 ``ERR_UNAUTHORIZED`` — including the three writes the
        managing editor is not on, which are claim decisions, brief approvals and
        snapshot writes — and none of the refusals leaves a row, a gate or a version
        change behind.

        Design: Corner/rbac/every_exclusive_write_denies_all_five_other_roles_with_the_same_code
        """
        chain = _draft_item_chain(flow, "CMP-RBAC")
        item_id = chain["item"]["id"]
        brief_id = chain["brief"]["id"]
        claim = flow.create_claim(
            item_id, claim_type="PERFORMANCE", claim_text=PERFORMANCE_CLAIM
        )

        validate_error(
            flow.api.create_campaign(
                f.campaign_payload(
                    code="CMP-RBAC2", primary_funnel_stage="AWARENESS"
                ),
                LEGAL_REVIEWER,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.create_expert(
                f.expert_payload(
                    full_name="Omar Kelly",
                    expertise_tags=["security"],
                    weekly_capacity_hours=40,
                ),
                BRAND_REVIEWER,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.submit_for_review(item_id, ACCESSIBILITY_REVIEWER),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.decide_claim(claim["id"], "SUBSTANTIATED", MANAGING_EDITOR),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.approve_brief(brief_id, MANAGING_EDITOR), ERR_UNAUTHORIZED, 403
        )
        validate_error(
            flow.api.create_performance_snapshot(
                item_id,
                f.performance_snapshot_payload(
                    "2026-07-01T00:00:00.000Z",
                    "2026-07-08T00:00:00.000Z",
                    engaged_sessions=10,
                    conversions=1,
                    influenced_opportunity_amount_cents=1000,
                    touch_position="FIRST",
                ),
                MANAGING_EDITOR,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.run_governance_sweep(ANALYTICS_SERVICE), ERR_UNAUTHORIZED, 403
        )

        assert flow.read_item(item_id)["workflow_state"] == "DRAFT"
        assert flow.read_claim(claim["id"])["substantiation_state"] == "DRAFT"
        assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR), expected_total_count=1
        )
        assert_list_response(
            flow.api.list_experts(MANAGING_EDITOR), expected_total_count=1
        )
        assert_list_response(
            flow.api.list_performance_snapshots(item_id, MANAGING_EDITOR),
            expected_total_count=0,
            expected_row_count=0,
        )
        assert_list_response(
            flow.api.list_review_gates(item_id, MANAGING_EDITOR),
            expected_total_count=0,
            expected_row_count=0,
        )
        refused_brief = flow.read_brief(brief_id)
        assert refused_brief["state"] == "APPROVED"
        assert_version(refused_brief, chain["brief"]["version"])


class TestAnalyticsServiceSurface:
    """The measurement role writes snapshots and reads items, nothing else."""

    def test_analytics_service_writes_measurements_but_sees_no_governance_surface(
        self, flow
    ):
        """
        The same token that successfully files a measurement period and reads the
        item back — carrying the recomputed pipeline attribution — is refused on the
        campaign, brief and claim reads that every reviewer role holds, while the
        snapshot sub-resource and the item collection remain open to it.

        Design: Corner/rbac/analytics_service_writes_measurements_and_reads_items_but_sees_no_governance_surface
        """
        flow.set_clock(SETUP_CLOCK)
        chain = _draft_item_chain(flow, "CMP-ANALYTICS")
        item_id = chain["item"]["id"]

        snapshot = validate_success(
            flow.api.create_performance_snapshot(
                item_id,
                f.performance_snapshot_payload(
                    "2026-07-20T00:00:00.000Z",
                    "2026-07-27T00:00:00.000Z",
                    engaged_sessions=800,
                    conversions=12,
                    influenced_opportunity_amount_cents=500000,
                    touch_position="LAST",
                ),
                ANALYTICS_SERVICE,
            ),
            201,
        )
        assert_bare_uuid(snapshot["id"])
        assert snapshot["touch_position"] == "LAST"

        seen = validate_success(flow.api.get_content_item(item_id, ANALYTICS_SERVICE))
        assert seen["workflow_state"] == "DRAFT"
        # A single LAST period contributes its whole amount to last touch and the
        # 0.40 last-position share to the assisted figure.
        assert_integer_value(seen["last_touch_pipeline_cents"], 500000)
        assert_integer_value(seen["assisted_pipeline_cents"], 200000)

        validate_error(
            flow.api.get_campaign(chain["campaign"]["id"], ANALYTICS_SERVICE),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.get_brief(chain["brief"]["id"], ANALYTICS_SERVICE),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.list_item_claims(item_id, ANALYTICS_SERVICE),
            ERR_UNAUTHORIZED,
            403,
        )

        assert_list_response(
            flow.api.list_performance_snapshots(item_id, ANALYTICS_SERVICE),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert_list_response(
            flow.api.list_content_items(ANALYTICS_SERVICE), expected_total_count=1
        )
        totals = flow.read_item(item_id)
        assert_integer_value(totals["engaged_sessions_total"], 800)
        assert_integer_value(totals["conversions_total"], 12)


class TestLegalSegregationAcrossClaims:
    """The legal exclusion set spans every claim decider on the piece."""

    def test_legal_gate_excludes_every_claim_decider_not_only_the_latest_one(
        self, flow
    ):
        """
        Two lawyers who each substantiated one of the item's two claims are both
        locked out of the legal gate with 409 ``ERR_SOD_LEGAL_CONFLICT``, leaving the
        gate pending at version 1, and a third lawyer who touched neither dossier is
        the only identity that can approve it.

        Design: Corner/rbac/legal_gate_segregation_spans_every_claim_decider_on_the_item_not_just_the_latest_one
        """
        flow.set_clock(SETUP_CLOCK)
        chain = _draft_item_chain(flow, "CMP-SODSPAN")
        item_id = chain["item"]["id"]

        claim_a = flow.create_claim(
            item_id, claim_type="PERFORMANCE", claim_text=PERFORMANCE_CLAIM
        )
        flow.file_evidence(
            claim_a["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-114, deployment benchmark",
            collected_at="2026-08-01T00:00:00.000Z",
            valid_until="2027-01-01T00:00:00.000Z",
        )
        decided_a = flow.decide_claim(claim_a["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE)
        assert decided_a["decided_by_user_id"] == LEGAL_ONE_ID

        claim_b = flow.create_claim(
            item_id, claim_type="COMPARISON", claim_text=COMPARISON_CLAIM
        )
        flow.file_evidence(
            claim_b["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-115, detection coverage matrix",
            collected_at="2026-08-01T00:00:00.000Z",
            valid_until="2027-01-01T00:00:00.000Z",
        )
        flow.file_evidence(
            claim_b["id"],
            source_type="REGULATORY_FILING",
            citation="Filing REG-2026-77, detection coverage attestation",
            collected_at="2026-08-01T00:00:00.000Z",
            valid_until="2027-03-01T00:00:00.000Z",
        )
        decided_b = flow.decide_claim(claim_b["id"], "SUBSTANTIATED", LEGAL_REVIEWER_TWO)
        assert decided_b["decided_by_user_id"] == LEGAL_TWO_ID
        # A third-party test worth 2.00 plus a regulatory filing worth 2.50 clears
        # the comparison requirement of 3.00.
        assert_two_decimal_value(decided_b["evidence_score"], 4.50)

        flow.submit(item_id)
        legal_gate = flow.gate_of(item_id, "LEGAL")
        assert_gate(legal_gate, gate_type="LEGAL", state="PENDING", sla_hours=48)

        validate_error(
            flow.api.decide_review_gate(
                legal_gate["id"], "APPROVED", LEGAL_REVIEWER_ONE
            ),
            ERR_SOD_LEGAL_CONFLICT,
            409,
        )
        validate_error(
            flow.api.decide_review_gate(
                legal_gate["id"], "APPROVED", LEGAL_REVIEWER_TWO
            ),
            ERR_SOD_LEGAL_CONFLICT,
            409,
        )
        still_pending = flow.gate_of(item_id, "LEGAL")
        assert still_pending["state"] == "PENDING"
        assert still_pending["decided_at"] is None
        assert_version(still_pending, 1)

        approved = validate_success(
            flow.api.decide_review_gate(
                legal_gate["id"],
                "APPROVED",
                LEGAL_REVIEWER_THREE,
                "Both claim dossiers reviewed independently.",
            )
        )
        assert approved["state"] == "APPROVED"
        assert approved["decided_by_user_id"] == LEGAL_THREE_ID

        substantiated = assert_list_response(
            flow.api.list_item_claims(
                item_id, MANAGING_EDITOR, {"substantiation_state": "SUBSTANTIATED"}
            ),
            expected_total_count=2,
            expected_row_count=2,
        )
        assert {row["id"] for row in substantiated} == {claim_a["id"], claim_b["id"]}

        assert flow.read_item(item_id)["workflow_state"] == "IN_REVIEW"
        remaining = {
            gate["gate_type"]: gate["state"]
            for gate in flow.gates(item_id)
            if gate["gate_type"] != "LEGAL"
        }
        assert remaining == {
            "SME": "PENDING",
            "BRAND": "PENDING",
            "ACCESSIBILITY": "PENDING",
        }
