"""
Declared edges, declared initial states, and the edges that do not exist.

Each machine is exercised on one legal edge and on the transitions the contract
never declares, including the replays that must be refused rather than absorbed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BRIEF_STATE_INVALID,
    ERR_CAMPAIGN_STATE_INVALID,
    ERR_GATE_ALREADY_DECIDED,
    ERR_ITEM_STATE_INVALID,
    ERR_SLOT_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_campaign_counters,
    assert_gate,
    assert_gate_dimension_order,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
    assert_two_decimal_value,
    assert_version,
)
from test_helpers.test_users import (
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"


class TestCampaignMachine:
    """The campaign has one edge out of planning and one terminal state."""

    def test_activate_moves_planning_to_active_and_bumps_the_version(self, flow):
        """
        The only declared edge out of planning lands on active and moves the version
        from 1 to 2; the posture stays open and the committed total stays 0 because no
        counter moved.

        Design: Corner/state_machines/campaign_activate_moves_planning_to_active_and_bumps_version
        """
        campaign = flow.create_campaign(
            code="CMP-ACT", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )

        activated = validate_success(
            flow.api.activate_campaign(campaign["id"], MANAGING_EDITOR)
        )

        assert activated["status"] == "ACTIVE"
        assert_posture(activated, "OPEN")
        assert_campaign_counters(activated, committed_points_total=0)
        assert_version(activated, 2)

    def test_a_closed_campaign_refuses_its_edges_and_its_dependent_writes(self, flow):
        """
        Closed is the campaign's only terminal state, so re-activating, re-closing and
        adding a brief are all refused with the campaign state error — the terminal
        state locks the dependent write surface the PRD names — and nothing is written
        under the campaign.

        Design: Corner/state_machines/closed_campaign_is_terminal_and_rejects_activate_close_and_dependent_writes
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-TERM", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        validate_success(flow.api.close_campaign(campaign["id"], MANAGING_EDITOR))

        attempts = [
            flow.api.activate_campaign(campaign["id"], MANAGING_EDITOR),
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR),
            flow.api.create_brief(
                f.brief_payload(
                    campaign["id"],
                    funnel_stage="DECISION",
                    required_expertise_tag="security",
                    review_window_start="2026-08-03T09:00:00.000Z",
                    review_window_end="2026-08-04T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
        ]

        for response in attempts:
            validate_error(response, ERR_CAMPAIGN_STATE_INVALID, 409)
        assert flow.read_campaign(campaign["id"])["status"] == "CLOSED"
        assert_list_response(
            flow.api.list_campaign_calendar_slots(campaign["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )
        assert_list_response(
            flow.api.list_briefs(MANAGING_EDITOR, {"campaign_id": campaign["id"]}),
            expected_total_count=0,
        )

    def test_closing_locks_every_slot_and_archives_only_the_open_briefs(self, flow):
        """
        One close request locks both slots without disturbing their commitments and
        archives the draft brief and the assigned brief, while the approved brief is
        deliberately left approved because the declared cascade names only the first
        two states.

        Design: Corner/state_machines/campaign_close_cascade_locks_every_slot_and_archives_every_open_brief
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-CLOSE", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot_one = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        slot_two = flow.create_slot(
            campaign["id"], week_start_date="2026-08-10", funnel_stage="DECISION",
            capacity_points=40,
        )
        expert = flow.create_expert(
            expertise_tags=["security"], weekly_capacity_hours=40
        )
        brief_a = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", effort_points=14,
            required_expertise_tag="security",
        )
        brief_b = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", effort_points=14,
            required_expertise_tag="security",
        )
        brief_c = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", effort_points=14,
            required_expertise_tag="security",
        )
        flow.assign_sme(brief_b["id"], expert["id"])
        flow.assign_sme(brief_c["id"], expert["id"])
        flow.approve_brief(brief_c["id"], expert["id"])

        closed = validate_success(
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR)
        )

        assert closed["status"] == "CLOSED"
        assert flow.read_slot(slot_one["id"])["status"] == "LOCKED"
        assert flow.read_slot(slot_two["id"])["status"] == "LOCKED"
        assert_slot_commitment(flow.read_slot(slot_one["id"]), 0, 0.00, "LOCKED")
        assert flow.read_brief(brief_a["id"])["state"] == "ARCHIVED"
        assert flow.read_brief(brief_b["id"])["state"] == "ARCHIVED"
        assert flow.read_brief(brief_c["id"])["state"] == "APPROVED"
        assert_list_response(
            flow.api.list_briefs(
                MANAGING_EDITOR,
                {"campaign_id": campaign["id"], "state": "ARCHIVED"},
            ),
            expected_total_count=2,
        )


class TestInitialStates:
    """Every machine starts where the contract says it starts."""

    def test_each_new_row_starts_in_its_declared_initial_state(self, flow):
        """
        Seven machines are read at birth: a campaign opens in planning, a slot open, an
        expert available, a brief and an item in draft, a claim in draft with no score
        and no decision, and an asset licensed with its full budget intact.

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.create_campaign(
            code="CMP-INIT", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        assert campaign["status"] == "PLANNING"
        flow.activate_campaign(campaign["id"])
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        expert = flow.create_expert(
            expertise_tags=["security"], weekly_capacity_hours=40
        )
        brief = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", required_expertise_tag="security"
        )
        assert brief["state"] == "DRAFT"
        flow.assign_sme(brief["id"], expert["id"])
        flow.approve_brief(brief["id"], expert["id"])
        item = flow.create_item(brief["id"], slot["id"], campaign["id"])

        claim = validate_success(
            flow.api.create_claim(
                item["id"],
                f.claim_payload(
                    claim_text="Deployment completes 40 percent faster than the previous release.",
                    claim_type="PERFORMANCE",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        asset = validate_success(
            flow.api.create_asset(
                f.asset_payload(
                    name="Launch hero illustration",
                    asset_type="ORIGINAL",
                    licensed_channels=["OWNED"],
                    max_licensed_uses=3,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert slot["status"] == "OPEN"
        assert expert["status"] == "AVAILABLE"
        assert item["workflow_state"] == "DRAFT"
        assert claim["substantiation_state"] == "DRAFT"
        assert_two_decimal_value(claim["evidence_score"], 0.00)
        assert claim["decided_at"] is None
        assert asset["status"] == "LICENSED"
        assert asset["active_use_count"] == 0
        assert asset["remaining_licensed_uses"] == 3


class TestBriefMachine:
    """A brief accepts one assignment; the second is a state error, not a version error."""

    def test_assigning_an_already_assigned_brief_is_a_state_error(self, flow):
        """
        The second assignment carries the freshly re-read expert version, so the
        concurrency check passes and the refusal can only come from the brief's own
        state, which has no second assignment edge; the first assignment's reserved
        hours and the expert's version both stand.

        Design: Corner/state_machines/assign_sme_on_an_already_assigned_brief_returns_brief_state_invalid
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-REASSIGN", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        expert = flow.create_expert(
            expertise_tags=["security"], weekly_capacity_hours=40
        )
        brief = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", required_expertise_tag="security"
        )
        flow.assign_sme(brief["id"], expert["id"])
        current_version = flow.expert_version(expert["id"])

        response = flow.api.assign_sme(
            brief["id"],
            f.assign_sme_payload(expert["id"], current_version),
            MANAGING_EDITOR,
        )

        validate_error(response, ERR_BRIEF_STATE_INVALID, 409)
        stored = flow.read_brief(brief["id"])
        assert stored["state"] == "SME_ASSIGNED"
        assert stored["sme_expert_id"] == expert["id"]
        stored_expert = flow.read_expert(expert["id"])
        assert stored_expert["committed_hours_total"] == 8
        assert_version(stored_expert, current_version)


class TestContentItemMachine:
    """Submitting fans out the review board; publishing from draft is not an edge."""

    def test_submitting_without_claims_fans_out_three_gates_in_order(self, flow):
        """
        With no claims on the item the fan-out emits exactly three pending gates in the
        fixed dimension order and omits the legal one, and each service level is the
        decision-stage scaling of its base: 30, 30 and 45 hours from the opening
        instant.

        Design: Corner/state_machines/submit_for_review_fans_out_three_gates_in_order_and_omits_legal_without_claims
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")

        submitted = validate_success(
            flow.api.submit_for_review(chain["item"]["id"], MANAGING_EDITOR)
        )

        assert submitted["workflow_state"] == "IN_REVIEW"
        assert submitted["revision_number"] == 1
        gates = assert_list_response(
            flow.api.list_review_gates(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=3,
        )
        assert [gate["gate_type"] for gate in gates] == [
            "SME",
            "BRAND",
            "ACCESSIBILITY",
        ]
        assert_gate_dimension_order(gates)
        for gate in gates:
            assert_gate(
                gate, state="PENDING", opened_at=SETUP_CLOCK, sla_breached=False
            )
            assert gate["decided_at"] is None
        assert_gate(gates[0], sla_hours=30, due_at="2026-08-04T14:00:00.000Z")
        assert_gate(gates[1], sla_hours=30, due_at="2026-08-04T14:00:00.000Z")
        assert_gate(gates[2], sla_hours=45, due_at="2026-08-05T05:00:00.000Z")
        assert_list_response(
            flow.api.list_review_gates(
                chain["item"]["id"], MANAGING_EDITOR, {"gate_type": "LEGAL"}
            ),
            expected_total_count=0,
        )

    def test_publishing_a_draft_item_is_not_a_declared_edge(self, flow):
        """
        Publication is declared only from the ready state, so a draft item is refused
        even with a complete, unique and accessible publication body from a second
        operator, and no distribution row appears.

        Design: Corner/state_machines/publish_from_draft_is_an_undeclared_edge_and_returns_item_state_invalid
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")

        response = flow.api.publish_content_item(
            chain["item"]["id"],
            f.publish_payload(
                scheduled_at="2026-08-05T09:00:00.000Z",
                channels=["OWNED", "EMAIL"],
                meta_description=(
                    "A practical buyer guide to zero trust platform pricing for "
                    "security and procurement teams."
                ),
                url_slug="zero-trust-platform-pricing",
                tags=["security", "pricing"],
            ),
            MANAGING_EDITOR_TWO,
        )

        validate_error(response, ERR_ITEM_STATE_INVALID, 409)
        item = flow.read_item(chain["item"]["id"])
        assert item["workflow_state"] == "DRAFT"
        assert item["published_at"] is None
        assert item["published_by_user_id"] is None
        assert item["url_slug"] is None
        assert_list_response(
            flow.api.list_distributions(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )


class TestReplayedDecisions:
    """A decided gate and a locked slot both refuse the replay."""

    def test_deciding_the_same_gate_twice_is_refused(self, flow):
        """
        The gate machine declares edges only out of the pending state, so replaying the
        same approval by the same authorised reviewer is refused rather than absorbed,
        and the fields stamped by the first decision — including the zero turnaround
        and the original notes — are untouched.

        Design: Corner/state_machines/deciding_the_same_review_gate_twice_returns_gate_already_decided
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        flow.submit(chain["item"]["id"])
        sme_gate = flow.gate_of(chain["item"]["id"], "SME")
        flow.decide_gate(
            sme_gate["id"],
            "APPROVED",
            expert_headers(chain["expert_id"]),
            decision_notes="Technical claims verified against the current rate card.",
        )

        response = flow.api.decide_review_gate(
            sme_gate["id"], "APPROVED", expert_headers(chain["expert_id"])
        )

        validate_error(response, ERR_GATE_ALREADY_DECIDED, 409)
        decided = flow.gate_of(chain["item"]["id"], "SME")
        assert_gate(
            decided, state="APPROVED", turnaround_hours=0.00
        )
        assert decided["decided_at"] == SETUP_CLOCK
        assert (
            decided["decision_notes"]
            == "Technical claims verified against the current rate card."
        )
        assert flow.read_item(chain["item"]["id"])["workflow_state"] == "IN_REVIEW"

    def test_locking_an_already_locked_slot_is_refused(self, flow):
        """
        Locked is the slot machine's terminal state and the lock action is declared only
        from the open and full states, so a replayed lock is refused and the version
        does not move a second time.

        Design: Corner/state_machines/locking_an_already_locked_calendar_slot_returns_slot_state_invalid
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-LOCK", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        locked = flow.lock_slot(slot["id"])

        response = flow.api.lock_calendar_slot(slot["id"], MANAGING_EDITOR)

        validate_error(response, ERR_SLOT_STATE_INVALID, 409)
        stored = flow.read_slot(slot["id"])
        assert_slot_commitment(stored, 0, 0.00, "LOCKED")
        assert_version(stored, locked["version"])
