"""
Error triggerability: every refusal is reachable, and it is the *only* refusal.

Each case drives one error identifier from a state where nothing else in the
validation ladder is broken, checks the refused write left no trace behind, and
then repairs the single offending input so the same call succeeds. Where two
rungs of the ladder are broken at once, the lower-numbered rung wins and the
case says so.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ASSET_CHANNEL_NOT_LICENSED,
    ERR_ASSET_USES_EXHAUSTED,
    ERR_CAMPAIGN_CODE_DUPLICATE,
    ERR_CAMPAIGN_HAS_OPEN_ITEMS,
    ERR_CAMPAIGN_POSTURE_RESTRICTED,
    ERR_CLAIM_STATE_INVALID,
    ERR_EVIDENCE_EXPIRED,
    ERR_EXPERTISE_TAG_MISMATCH,
    ERR_GATE_NOT_WAIVABLE,
    ERR_SLOT_LOCKED,
    ERR_SNAPSHOT_PERIOD_INVALID,
    ERR_SOD_LEGAL_CONFLICT,
    ERR_SOD_PUBLISH_CONFLICT,
    ERR_STALE_CAMPAIGN_VERSION,
    ERR_URL_SLUG_DUPLICATE,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_gate,
    assert_integer_value,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
    assert_sweep_tally,
    assert_two_decimal_value,
    assert_version,
)
from test_helpers.test_users import (
    ACCESSIBILITY_REVIEWER,
    ANALYTICS_SERVICE,
    BRAND_REVIEWER,
    EDITOR_ONE_ID,
    EDITOR_TWO_ID,
    LEGAL_ONE_ID,
    LEGAL_REVIEWER_ONE,
    LEGAL_REVIEWER_TWO,
    LEGAL_TWO_ID,
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
STARTUP_CLOCK = "2026-08-01T00:00:00.000Z"
ITEM_TITLE = "Zero trust login guide"
PLANNED_PUBLISH = "2026-08-05T09:00:00.000Z"
META_DESCRIPTION = (
    "A practical walkthrough of zero trust login for security and identity teams."
)
TAGS = ["security", "identity"]


class TestCampaignCodeUniqueness:
    """A campaign code is unique across the whole service, not within a quarter."""

    def test_duplicate_campaign_code_is_refused_regardless_of_persona_and_quarter(
        self, flow
    ):
        """
        A second campaign carrying an existing code but a different persona, funnel
        stage and quarter is still refused, a code differing by one character is
        accepted, and the refused create leaves the collection and the surviving row
        untouched.

        Design: Corner/errors/campaign_code_uniqueness_is_global_and_case_exact
        """
        flow.set_clock(STARTUP_CLOCK)

        first = validate_success(
            flow.api.create_campaign(
                f.campaign_payload(
                    code="CMP-UNIQ",
                    persona="IT_BUYER",
                    primary_funnel_stage="AWARENESS",
                    quarter_code="2026Q3",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert first["code"] == "CMP-UNIQ"

        duplicate = flow.api.create_campaign(
            f.campaign_payload(
                code="CMP-UNIQ",
                persona="EXECUTIVE",
                primary_funnel_stage="DECISION",
                quarter_code="2026Q4",
            ),
            MANAGING_EDITOR,
        )
        validate_error(duplicate, ERR_CAMPAIGN_CODE_DUPLICATE, 409)

        second = validate_success(
            flow.api.create_campaign(
                f.campaign_payload(
                    code="CMP-UNIQ2",
                    persona="EXECUTIVE",
                    primary_funnel_stage="DECISION",
                    quarter_code="2026Q4",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert second["code"] == "CMP-UNIQ2"
        assert second["id"] != first["id"]

        assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )

        survivor = flow.read_campaign(first["id"])
        assert survivor["persona"] == "IT_BUYER"
        assert survivor["quarter_code"] == "2026Q3"
        assert survivor["primary_funnel_stage"] == "AWARENESS"


class TestStaleCampaignVersionOnCommit:
    """The version a client read at create time is staled by the activation."""

    def test_activation_stales_the_campaign_version_a_naive_client_remembers(self, flow):
        """
        The campaign version captured from the create response is invalidated by the
        activation that item creation itself requires, so the first commit pinned to it
        is refused without consuming slot capacity; the re-read version then commits.

        Design: Corner/errors/content_item_create_rejects_a_campaign_version_staled_by_activation
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.create_campaign(
            code="CMP-OCC", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        version_at_create = campaign["version"]
        flow.activate_campaign(campaign["id"])
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        version_now = flow.campaign_version(campaign["id"])
        assert version_at_create == 1
        assert version_now == 2

        stale = flow.api.create_content_item(
            f.content_item_payload(
                brief["id"],
                slot["id"],
                version_at_create,
                title=ITEM_TITLE,
                planned_publish_at=PLANNED_PUBLISH,
            ),
            MANAGING_EDITOR,
        )
        validate_error(stale, ERR_STALE_CAMPAIGN_VERSION, 412)

        assert_slot_commitment(flow.read_slot(slot["id"]), 0, 0.00, status="OPEN")
        refused_campaign = flow.read_campaign(campaign["id"])
        assert_campaign_counters(refused_campaign, committed_points_total=0)
        assert_version(refused_campaign, 2)
        assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"campaign_id": campaign["id"]}
            ),
            expected_total_count=0,
            expected_row_count=0,
        )

        item = validate_success(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief["id"],
                    slot["id"],
                    version_now,
                    title=ITEM_TITLE,
                    planned_publish_at=PLANNED_PUBLISH,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_integer_value(item["commit_points"], 6)
        assert_slot_commitment(flow.read_slot(slot["id"]), 6, 15.00, status="OPEN")
        assert flow.campaign_version(campaign["id"]) == 3


class TestLockedSlotRefusal:
    """Locking one week of the calendar does not lock the campaign."""

    def test_locked_week_refuses_the_commit_that_the_next_open_week_accepts(self, flow):
        """
        The same approved brief is refused against the LOCKED week and accepted against
        an OPEN week of the same funnel stage seven days later; the locked week's
        commitment and version never move.

        Design: Corner/errors/content_item_create_on_a_locked_slot_is_refused_while_another_week_accepts_it
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-LOCKED", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        locked_slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        open_slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-10",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        # A commit reads the brief's own state as well as the slot's, so the brief is
        # carried to APPROVED and only the slot lock is left broken.
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        assert brief["state"] == "APPROVED"

        locked = flow.lock_slot(locked_slot["id"])
        assert locked["status"] == "LOCKED"

        campaign_version = flow.campaign_version(campaign["id"])
        refused = flow.api.create_content_item(
            f.content_item_payload(
                brief["id"],
                locked_slot["id"],
                campaign_version,
                title=ITEM_TITLE,
                planned_publish_at=PLANNED_PUBLISH,
            ),
            MANAGING_EDITOR,
        )
        validate_error(refused, ERR_SLOT_LOCKED, 409)
        assert_slot_commitment(flow.read_slot(locked_slot["id"]), 0, 0.00)

        item = validate_success(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief["id"],
                    open_slot["id"],
                    campaign_version,
                    title=ITEM_TITLE,
                    planned_publish_at="2026-08-12T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_integer_value(item["commit_points"], 6)
        assert_slot_commitment(flow.read_slot(open_slot["id"]), 6, 15.00, status="OPEN")

        still_locked = flow.read_slot(locked_slot["id"])
        assert still_locked["status"] == "LOCKED"
        assert_version(still_locked, 2)

        assert_list_response(
            flow.api.list_calendar_slots(
                MANAGING_EDITOR, {"campaign_id": campaign["id"], "status": "LOCKED"}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )


class TestCloseWithOpenItems:
    """Closure counts the four open item states and runs its cascade only once."""

    def test_close_is_refused_three_times_and_cascades_only_after_publication(self, flow):
        """
        The same close call is refused at DRAFT, at IN_REVIEW and at READY, each refusal
        leaving the slot OPEN and the brief APPROVED, and only the fourth close — once
        the piece is PUBLISHED — locks the calendar week without disturbing the
        commitment ledger or the approved brief.

        Design: Corner/errors/campaign_close_is_refused_while_an_item_is_still_open
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-OPENITEM",
            persona="PRACTITIONER",
            primary_funnel_stage="AWARENESS",
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
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )
        assert item["workflow_state"] == "DRAFT"

        validate_error(
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR),
            ERR_CAMPAIGN_HAS_OPEN_ITEMS,
            409,
        )

        submitted = flow.submit(item["id"])
        assert submitted["workflow_state"] == "IN_REVIEW"
        validate_error(
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR),
            ERR_CAMPAIGN_HAS_OPEN_ITEMS,
            409,
        )

        flow.decide_gate(
            flow.gate_of(item["id"], "SME")["id"],
            "APPROVED",
            expert_headers(expert_id),
        )
        flow.decide_gate(
            flow.gate_of(item["id"], "BRAND")["id"], "APPROVED", BRAND_REVIEWER
        )
        last_gate = flow.decide_gate(
            flow.gate_of(item["id"], "ACCESSIBILITY")["id"],
            "APPROVED",
            ACCESSIBILITY_REVIEWER,
        )
        assert last_gate["state"] == "APPROVED"
        assert flow.read_item(item["id"])["workflow_state"] == "READY"

        validate_error(
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR),
            ERR_CAMPAIGN_HAS_OPEN_ITEMS,
            409,
        )
        assert flow.read_slot(slot["id"])["status"] == "OPEN"
        assert flow.read_brief(brief["id"])["state"] == "APPROVED"

        published = validate_success(
            flow.api.publish_content_item(
                item["id"],
                f.publish_payload(
                    scheduled_at=PLANNED_PUBLISH,
                    channels=["OWNED"],
                    meta_description=META_DESCRIPTION,
                    url_slug="zero-trust-login-close",
                    tags=TAGS,
                ),
                MANAGING_EDITOR_TWO,
            )
        )
        assert published["workflow_state"] == "PUBLISHED"

        closed = validate_success(
            flow.api.close_campaign(campaign["id"], MANAGING_EDITOR)
        )
        assert closed["status"] == "CLOSED"

        assert_slot_commitment(flow.read_slot(slot["id"]), 6, 15.00, status="LOCKED")
        # The cascade archives DRAFT and SME_ASSIGNED briefs only, so an APPROVED brief
        # keeps its state and its reserved hours stay on the expert's ledger.
        assert flow.read_brief(brief["id"])["state"] == "APPROVED"
        assert_integer_value(flow.read_expert(expert_id)["committed_hours_total"], 3)
        assert flow.read_item(item["id"])["workflow_state"] == "PUBLISHED"
        assert_campaign_counters(
            flow.read_campaign(campaign["id"]), committed_points_total=6
        )


class TestPublishConflictPrecedence:
    """Slug uniqueness sits above publication segregation of duties in the ladder."""

    def test_slug_duplication_outranks_the_publisher_conflict_on_the_same_call(self, flow):
        """
        Publishing with a free slug as the creating editor is a segregation conflict,
        publishing a sibling's slug as a different editor is a duplicate, and a call
        that breaks both returns the duplicate because uniqueness is the lower rung;
        only a different editor with a free slug ships the piece.

        Design: Corner/errors/publish_url_slug_uniqueness_outranks_publisher_segregation_of_duties
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-SLUG", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=200,
        )
        expert_id = flow.create_expert(
            expertise_tags=["security"], weekly_capacity_hours=60
        )["id"]
        brief_a, _a = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expert_id=expert_id,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        brief_b, _b = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expert_id=expert_id,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        item_a = flow.create_item(
            brief_a["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )
        item_b = flow.create_item(
            brief_b["id"],
            slot["id"],
            campaign["id"],
            title="Zero trust SSO guide",
            planned_publish_at=PLANNED_PUBLISH,
        )
        assert item_b["created_by_user_id"] == EDITOR_ONE_ID

        flow.submit(item_a["id"])
        flow.approve_all_gates(item_a["id"], expert_id)
        published_a = validate_success(
            flow.api.publish_content_item(
                item_a["id"],
                f.publish_payload(
                    scheduled_at=PLANNED_PUBLISH,
                    channels=["OWNED"],
                    meta_description=META_DESCRIPTION,
                    url_slug="zero-trust-login-guide",
                    tags=TAGS,
                ),
                MANAGING_EDITOR_TWO,
            )
        )
        assert published_a["url_slug"] == "zero-trust-login-guide"

        flow.submit(item_b["id"])
        flow.decide_gate(
            flow.gate_of(item_b["id"], "SME")["id"],
            "APPROVED",
            expert_headers(expert_id),
        )
        flow.decide_gate(
            flow.gate_of(item_b["id"], "BRAND")["id"], "APPROVED", BRAND_REVIEWER
        )
        last_gate = flow.decide_gate(
            flow.gate_of(item_b["id"], "ACCESSIBILITY")["id"],
            "APPROVED",
            ACCESSIBILITY_REVIEWER,
        )
        assert last_gate["state"] == "APPROVED"

        sso_meta = (
            "A practical walkthrough of zero trust single sign on for identity teams."
        )
        free_slug_body = f.publish_payload(
            scheduled_at=PLANNED_PUBLISH,
            channels=["OWNED"],
            meta_description=sso_meta,
            url_slug="zero-trust-sso-guide",
            tags=TAGS,
        )
        taken_slug_body = f.publish_payload(
            scheduled_at=PLANNED_PUBLISH,
            channels=["OWNED"],
            meta_description=sso_meta,
            url_slug="zero-trust-login-guide",
            tags=TAGS,
        )

        validate_error(
            flow.api.publish_content_item(
                item_b["id"], free_slug_body, MANAGING_EDITOR
            ),
            ERR_SOD_PUBLISH_CONFLICT,
            409,
        )
        validate_error(
            flow.api.publish_content_item(
                item_b["id"], taken_slug_body, MANAGING_EDITOR_TWO
            ),
            ERR_URL_SLUG_DUPLICATE,
            409,
        )
        validate_error(
            flow.api.publish_content_item(
                item_b["id"], taken_slug_body, MANAGING_EDITOR
            ),
            ERR_URL_SLUG_DUPLICATE,
            409,
        )

        published_b = validate_success(
            flow.api.publish_content_item(
                item_b["id"], free_slug_body, MANAGING_EDITOR_TWO
            )
        )
        assert published_b["workflow_state"] == "PUBLISHED"
        assert published_b["url_slug"] == "zero-trust-sso-guide"
        assert published_b["published_by_user_id"] == EDITOR_TWO_ID

        stored_b = flow.read_item(item_b["id"])
        assert stored_b["published_at"] == SETUP_CLOCK
        assert stored_b["created_by_user_id"] == EDITOR_ONE_ID

        rows = assert_list_response(
            flow.api.list_distributions(item_b["id"], MANAGING_EDITOR),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert rows[0]["state"] == "SCHEDULED"

        assert_slot_commitment(flow.read_slot(slot["id"]), 12, 6.00)
        assert_posture(flow.read_campaign(campaign["id"]), "OPEN")


class TestExpertiseTagMembership:
    """Tag matching is membership of one required tag, not array overlap scoring."""

    def test_assignment_needs_the_required_tag_in_the_experts_own_tag_list(self, flow):
        """
        An available expert with free capacity but only an unrelated tag is refused, the
        refusal leaves the brief DRAFT and the expert's ledger and version untouched,
        and an expert carrying the required tag alongside the same unrelated one is
        accepted.

        Design: Corner/errors/assign_sme_requires_the_briefs_required_expertise_tag
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-TAGS", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        wrong_expert = flow.create_expert(
            expertise_tags=["security"], weekly_capacity_hours=40
        )
        right_expert = flow.create_expert(
            expertise_tags=["accessibility", "security"], weekly_capacity_hours=40
        )
        assert wrong_expert["expertise_tags"] == ["security"]

        brief = flow.create_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            required_expertise_tag="accessibility",
            week_monday="2026-08-03",
        )
        assert brief["required_expertise_tag"] == "accessibility"
        assert_integer_value(brief["sme_reserved_hours"], 3)

        refused = flow.api.assign_sme(
            brief["id"],
            f.assign_sme_payload(wrong_expert["id"], wrong_expert["version"]),
            MANAGING_EDITOR,
        )
        validate_error(refused, ERR_EXPERTISE_TAG_MISMATCH, 422)

        untouched_brief = flow.read_brief(brief["id"])
        assert untouched_brief["state"] == "DRAFT"
        assert untouched_brief["sme_expert_id"] is None
        untouched_expert = flow.read_expert(wrong_expert["id"])
        assert_version(untouched_expert, 1)
        assert_integer_value(untouched_expert["committed_hours_total"], 0)

        assigned = validate_success(
            flow.api.assign_sme(
                brief["id"],
                f.assign_sme_payload(right_expert["id"], right_expert["version"]),
                MANAGING_EDITOR,
            )
        )
        assert assigned["state"] == "SME_ASSIGNED"
        assert assigned["sme_expert_id"] == right_expert["id"]

        holder = flow.read_expert(right_expert["id"])
        assert_integer_value(holder["committed_hours_total"], 3)
        assert_version(holder, 2)

        assert_list_response(
            flow.api.list_briefs(
                MANAGING_EDITOR, {"sme_expert_id": wrong_expert["id"]}
            ),
            expected_total_count=0,
            expected_row_count=0,
        )


class TestSnapshotPeriodBounds:
    """One code guards three bad periods and deliberately admits a touching one."""

    def test_zero_length_future_and_overlapping_periods_are_refused_but_touching_is_not(
        self, flow
    ):
        """
        A zero-length period, a period ending one millisecond past the clock and a period
        whose interior overlaps a stored one are all refused without moving the item's
        attribution totals, while a period starting exactly where the stored one ends is
        accepted because the interval is half-open.

        Design: Corner/errors/snapshot_period_bounds_reject_zero_length_future_and_interior_overlap_but_admit_touching_periods
        """
        flow.set_clock("2026-08-20T00:00:00.000Z")

        campaign = flow.active_campaign(
            code="CMP-SNAP", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-17",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-17",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at="2026-08-19T09:00:00.000Z",
        )

        validate_error(
            flow.api.create_performance_snapshot(
                item["id"],
                f.performance_snapshot_payload(
                    "2026-08-01T00:00:00.000Z",
                    "2026-08-01T00:00:00.000Z",
                    engaged_sessions=100,
                    conversions=5,
                    influenced_opportunity_amount_cents=200000,
                    touch_position="FIRST",
                ),
                ANALYTICS_SERVICE,
            ),
            ERR_SNAPSHOT_PERIOD_INVALID,
            400,
        )
        validate_error(
            flow.api.create_performance_snapshot(
                item["id"],
                f.performance_snapshot_payload(
                    "2026-08-01T00:00:00.000Z",
                    "2026-08-20T00:00:00.001Z",
                    engaged_sessions=100,
                    conversions=5,
                    influenced_opportunity_amount_cents=200000,
                    touch_position="FIRST",
                ),
                ANALYTICS_SERVICE,
            ),
            ERR_SNAPSHOT_PERIOD_INVALID,
            400,
        )

        first = validate_success(
            flow.api.create_performance_snapshot(
                item["id"],
                f.performance_snapshot_payload(
                    "2026-08-01T00:00:00.000Z",
                    "2026-08-08T00:00:00.000Z",
                    engaged_sessions=100,
                    conversions=5,
                    influenced_opportunity_amount_cents=200000,
                    touch_position="FIRST",
                ),
                ANALYTICS_SERVICE,
            ),
            201,
        )
        after_first = flow.read_item(item["id"])
        assert_integer_value(after_first["engaged_sessions_total"], 100)
        assert_integer_value(after_first["assisted_pipeline_cents"], 80000)

        validate_error(
            flow.api.create_performance_snapshot(
                item["id"],
                f.performance_snapshot_payload(
                    "2026-08-05T00:00:00.000Z",
                    "2026-08-10T00:00:00.000Z",
                    engaged_sessions=40,
                    conversions=2,
                    influenced_opportunity_amount_cents=90000,
                    touch_position="MIDDLE",
                ),
                ANALYTICS_SERVICE,
            ),
            ERR_SNAPSHOT_PERIOD_INVALID,
            400,
        )
        after_overlap = flow.read_item(item["id"])
        assert_integer_value(after_overlap["engaged_sessions_total"], 100)
        assert_integer_value(after_overlap["conversions_total"], 5)
        assert_integer_value(after_overlap["assisted_pipeline_cents"], 80000)

        touching = validate_success(
            flow.api.create_performance_snapshot(
                item["id"],
                f.performance_snapshot_payload(
                    "2026-08-08T00:00:00.000Z",
                    "2026-08-15T00:00:00.000Z",
                    engaged_sessions=60,
                    conversions=3,
                    influenced_opportunity_amount_cents=150000,
                    touch_position="MIDDLE",
                ),
                ANALYTICS_SERVICE,
            ),
            201,
        )
        assert touching["period_end"] == "2026-08-15T00:00:00.000Z"
        assert touching["id"] != first["id"]

        final = flow.read_item(item["id"])
        assert_integer_value(final["engaged_sessions_total"], 160)
        assert_integer_value(final["conversions_total"], 8)
        assert_integer_value(final["last_touch_pipeline_cents"], 0)
        assert_integer_value(final["assisted_pipeline_cents"], 110000)

        assert_list_response(
            flow.api.list_performance_snapshots(item["id"], MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )
        assert_list_response(
            flow.api.list_performance_snapshots(
                item["id"], MANAGING_EDITOR, {"touch_position": "MIDDLE"}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )


class TestLegalGateSegregation:
    """The legal conflict is per-user, compared against every claim decider."""

    def test_the_lawyer_who_signed_the_claim_cannot_decide_the_items_legal_gate(self, flow):
        """
        The lawyer who substantiated the item's only claim is locked out of the LEGAL
        gate while a second lawyer of the same role passes the identical request, and the
        refusal leaves the gate PENDING at version 1.

        Design: Corner/errors/the_legal_gate_cannot_be_decided_by_the_lawyer_who_decided_the_items_claim
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-SODLEGAL",
            persona="PRACTITIONER",
            primary_funnel_stage="AWARENESS",
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )

        claim = flow.create_claim(
            item["id"],
            claim_type="PERFORMANCE",
            claim_text=(
                "Median deployment finishes 30 percent faster than the previous release."
            ),
        )
        assert_two_decimal_value(claim["required_score"], 2.00)
        flow.file_evidence(
            claim["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-114, deployment benchmark",
            collected_at="2026-08-01T00:00:00.000Z",
            valid_until="2027-01-01T00:00:00.000Z",
        )
        signed = flow.decide_claim(claim["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE)
        assert signed["substantiation_state"] == "SUBSTANTIATED"
        assert signed["decided_by_user_id"] == LEGAL_ONE_ID

        flow.submit(item["id"])
        legal_gate = flow.gate_of(item["id"], "LEGAL")
        # The one claim is already substantiated, so no regulated surcharge lengthens
        # the legal deadline beyond its base turnaround.
        assert_gate(legal_gate, gate_type="LEGAL", state="PENDING", sla_hours=48)

        validate_error(
            flow.api.decide_review_gate(
                legal_gate["id"],
                "APPROVED",
                LEGAL_REVIEWER_ONE,
                "Claim language reviewed and accepted.",
            ),
            ERR_SOD_LEGAL_CONFLICT,
            409,
        )
        still_pending = validate_success(
            flow.api.get_review_gate(legal_gate["id"], MANAGING_EDITOR)
        )
        assert still_pending["state"] == "PENDING"
        assert still_pending["decided_at"] is None
        assert still_pending["decided_by_user_id"] is None
        assert_version(still_pending, 1)

        approved = validate_success(
            flow.api.decide_review_gate(
                legal_gate["id"],
                "APPROVED",
                LEGAL_REVIEWER_TWO,
                "Claim language reviewed and accepted.",
            )
        )
        assert_gate(
            approved, state="APPROVED", turnaround_hours=0.00, sla_breached=False
        )
        assert approved["decided_by_user_id"] == LEGAL_TWO_ID

        assert flow.read_item(item["id"])["workflow_state"] == "IN_REVIEW"
        assert_list_response(
            flow.api.list_review_gates(item["id"], MANAGING_EDITOR),
            expected_total_count=4,
            expected_row_count=4,
        )
        assert_posture(flow.read_campaign(campaign["id"]), "OPEN")


class TestClaimStateMachineLocks:
    """One code guards both ends of the claim machine, asymmetrically."""

    def test_a_draft_claim_cannot_be_decided_and_a_substantiated_one_cannot_take_evidence(
        self, flow
    ):
        """
        A decision on a DRAFT claim is refused because decisions are declared only from
        EVIDENCE_PENDING, that state accepts a second evidence row through its self-loop,
        and once the claim is SUBSTANTIATED both a further evidence row and a second
        decision are refused with the same code.

        Design: Corner/errors/claim_decisions_and_evidence_filing_respect_the_substantiation_state_machine
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-CLAIMSM", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )

        claim = flow.create_claim(
            item["id"],
            claim_type="PERFORMANCE",
            claim_text=(
                "Median deployment finishes 30 percent faster than the previous release."
            ),
        )
        assert claim["substantiation_state"] == "DRAFT"
        assert_two_decimal_value(claim["evidence_score"], 0.00)

        validate_error(
            flow.api.decide_claim(claim["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE),
            ERR_CLAIM_STATE_INVALID,
            409,
        )

        first_row = validate_success(
            flow.api.file_evidence(
                claim["id"],
                f.evidence_payload(
                    source_type="CUSTOMER_DATA",
                    citation="Customer telemetry export CT-2026-08, deployment durations",
                    collected_at="2026-08-01T00:00:00.000Z",
                    valid_until="2027-01-01T00:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        second_row = validate_success(
            flow.api.file_evidence(
                claim["id"],
                f.evidence_payload(
                    source_type="THIRD_PARTY_TEST",
                    citation="Independent lab report LR-2026-114, deployment benchmark",
                    collected_at="2026-08-01T00:00:00.000Z",
                    valid_until="2026-12-01T00:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert first_row["id"] != second_row["id"]

        pending = flow.read_claim(claim["id"])
        assert pending["substantiation_state"] == "EVIDENCE_PENDING"
        assert_two_decimal_value(pending["evidence_score"], 2.50)

        decided = validate_success(
            flow.api.decide_claim(claim["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE)
        )
        assert decided["substantiation_state"] == "SUBSTANTIATED"
        assert decided["evidence_valid_until"] == "2026-12-01T00:00:00.000Z"

        validate_error(
            flow.api.file_evidence(
                claim["id"],
                f.evidence_payload(
                    source_type="INTERNAL_STUDY",
                    citation="Internal benchmark IS-2026-40, deployment durations",
                    collected_at="2026-08-01T00:00:00.000Z",
                    valid_until="2027-06-01T00:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            ERR_CLAIM_STATE_INVALID,
            409,
        )
        validate_error(
            flow.api.decide_claim(claim["id"], "REJECTED", LEGAL_REVIEWER_TWO),
            ERR_CLAIM_STATE_INVALID,
            409,
        )

        assert_list_response(
            flow.api.list_claim_evidence(claim["id"], MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )
        final = flow.read_claim(claim["id"])
        assert final["substantiation_state"] == "SUBSTANTIATED"
        assert final["decided_by_user_id"] == LEGAL_ONE_ID
        assert_two_decimal_value(final["evidence_score"], 2.50)


class TestEvidenceFreshnessAtDecision:
    """Freshness and sufficiency are separate gates on separate fields."""

    def test_a_stale_row_still_scores_but_cannot_carry_a_substantiation(self, flow):
        """
        The stale row contributes its full weight, so the score meets the required score
        exactly and the sufficiency rung cannot fire; the refusal comes only from the
        freshness rung finding no contributing row valid past the clock, while a sibling
        claim with an unexpired row of the same weight is substantiated.

        Design: Corner/errors/substantiation_requires_evidence_still_valid_at_the_clock_even_when_the_score_suffices
        """
        flow.set_clock(STARTUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-EVEXP", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )

        claim_a = flow.create_claim(
            item["id"],
            claim_type="PERFORMANCE",
            claim_text=(
                "Median deployment finishes 30 percent faster than the previous release."
            ),
        )
        flow.file_evidence(
            claim_a["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-114, deployment benchmark",
            collected_at="2026-08-01T00:00:00.000Z",
            valid_until="2026-08-10T00:00:00.000Z",
        )

        flow.set_clock("2026-08-10T00:00:00.000Z")

        claim_b = flow.create_claim(
            item["id"],
            claim_type="COMPARISON",
            claim_text=(
                "Our detection coverage exceeds the two leading competing platforms."
            ),
        )
        flow.file_evidence(
            claim_b["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-115, detection coverage matrix",
            collected_at="2026-08-10T00:00:00.000Z",
            valid_until="2026-12-01T00:00:00.000Z",
        )
        flow.file_evidence(
            claim_b["id"],
            source_type="REGULATORY_FILING",
            citation="Filing REG-2026-77, detection coverage attestation",
            collected_at="2026-08-10T00:00:00.000Z",
            valid_until="2027-03-01T00:00:00.000Z",
        )

        before = flow.read_claim(claim_a["id"])
        assert_two_decimal_value(before["evidence_score"], 2.00)
        assert_two_decimal_value(before["required_score"], 2.00)
        assert before["substantiation_state"] == "EVIDENCE_PENDING"

        validate_error(
            flow.api.decide_claim(claim_a["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE),
            ERR_EVIDENCE_EXPIRED,
            422,
        )
        refused = flow.read_claim(claim_a["id"])
        assert refused["substantiation_state"] == "EVIDENCE_PENDING"
        assert refused["decided_by_user_id"] is None
        assert refused["evidence_valid_until"] is None

        substantiated = validate_success(
            flow.api.decide_claim(claim_b["id"], "SUBSTANTIATED", LEGAL_REVIEWER_ONE)
        )
        assert substantiated["substantiation_state"] == "SUBSTANTIATED"
        assert_two_decimal_value(substantiated["evidence_score"], 4.50)
        assert_two_decimal_value(substantiated["required_score"], 3.00)
        assert substantiated["evidence_valid_until"] == "2026-12-01T00:00:00.000Z"

        assert_list_response(
            flow.api.list_claim_evidence(claim_a["id"], MANAGING_EDITOR),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert_list_response(
            flow.api.list_claim_evidence(claim_b["id"], MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )

        final_campaign = flow.read_campaign(campaign["id"])
        assert_posture(final_campaign, "OPEN")
        assert_campaign_counters(
            final_campaign, unsubstantiated_published_claim_count=0
        )


class TestAssetRightsGateOrder:
    """Channel licensing is checked before the remaining-use budget."""

    def test_an_unlicensed_channel_is_refused_even_once_the_budget_is_exhausted(self, flow):
        """
        An unlicensed channel is refused while the budget is still free, a licensed
        channel is refused once the single permitted use is consumed, and re-attempting
        the unlicensed channel with the budget also gone still returns the channel error;
        neither refusal moves the asset's active use count.

        Design: Corner/errors/asset_channel_licensing_outranks_the_remaining_use_budget
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-CHANNEL", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )
        assert_integer_value(item["promotion_window_days"], 3)

        asset = flow.create_asset(
            name="Zero trust hero photo",
            asset_type="STOCK",
            license_start="2026-07-01T00:00:00.000Z",
            license_end="2026-12-01T00:00:00.000Z",
            licensed_channels=["OWNED", "EMAIL"],
            max_licensed_uses=1,
        )
        assert_asset_rights(asset, status="LICENSED", remaining_licensed_uses=1)

        validate_error(
            flow.api.attach_asset_usage(
                item["id"],
                f.asset_usage_payload(asset["id"], channel="SOCIAL"),
                MANAGING_EDITOR,
            ),
            ERR_ASSET_CHANNEL_NOT_LICENSED,
            422,
        )
        assert_asset_rights(
            flow.read_asset(asset["id"]),
            active_use_count=0,
            remaining_licensed_uses=1,
        )

        usage = validate_success(
            flow.api.attach_asset_usage(
                item["id"],
                f.asset_usage_payload(asset["id"], channel="OWNED"),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert usage["usage_state"] == "ACTIVE"
        assert usage["attached_at"] == SETUP_CLOCK
        assert_asset_rights(
            flow.read_asset(asset["id"]),
            active_use_count=1,
            remaining_licensed_uses=0,
        )

        validate_error(
            flow.api.attach_asset_usage(
                item["id"],
                f.asset_usage_payload(asset["id"], channel="EMAIL"),
                MANAGING_EDITOR,
            ),
            ERR_ASSET_USES_EXHAUSTED,
            409,
        )
        validate_error(
            flow.api.attach_asset_usage(
                item["id"],
                f.asset_usage_payload(asset["id"], channel="SOCIAL"),
                MANAGING_EDITOR,
            ),
            ERR_ASSET_CHANNEL_NOT_LICENSED,
            422,
        )

        rows = assert_list_response(
            flow.api.list_asset_usages(asset["id"], MANAGING_EDITOR),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert rows[0]["id"] == usage["id"]
        assert_list_response(
            flow.api.list_item_asset_usages(
                item["id"], MANAGING_EDITOR, {"channel": "EMAIL"}
            ),
            expected_total_count=0,
            expected_row_count=0,
        )

        assert_asset_rights(flow.read_asset(asset["id"]), status="LICENSED")
        assert_campaign_counters(
            flow.read_campaign(campaign["id"]), expired_usage_count=0
        )


class TestRestrictedPostureScope:
    """RESTRICTED closes exactly one door: the gate waiver."""

    def test_a_restricted_campaign_refuses_the_waiver_and_takes_the_approval(self, flow):
        """
        Two overdue deadlines take the campaign to the restriction threshold exactly, the
        gate still inside its own longer deadline cannot be waived, and the very next call
        approves that same gate through its own reviewer without lifting the restriction.

        Design: Corner/errors/a_restricted_campaign_refuses_gate_waivers_but_still_accepts_reviewer_approvals
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-RESTRICT",
            persona="PRACTITIONER",
            primary_funnel_stage="AWARENESS",
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
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )
        flow.submit(item["id"])

        sme_gate = flow.gate_of(item["id"], "SME")
        brand_gate = flow.gate_of(item["id"], "BRAND")
        accessibility_gate = flow.gate_of(item["id"], "ACCESSIBILITY")
        assert_gate(sme_gate, sla_hours=24, due_at="2026-08-04T08:00:00.000Z")
        assert_gate(brand_gate, sla_hours=24, due_at="2026-08-04T08:00:00.000Z")
        assert_gate(
            accessibility_gate, sla_hours=36, due_at="2026-08-04T20:00:00.000Z"
        )

        flow.set_clock("2026-08-04T14:00:00.000Z")
        assert_sweep_tally(flow.sweep(), gates_breached=2, campaigns_restricted=1)

        restricted = flow.read_campaign(campaign["id"])
        assert_posture(restricted, "RESTRICTED")
        assert_campaign_counters(restricted, breached_gate_count=2)

        validate_error(
            flow.api.decide_review_gate(
                accessibility_gate["id"],
                "WAIVED",
                MANAGING_EDITOR,
                "No accessibility reviewer on rota this week.",
            ),
            ERR_CAMPAIGN_POSTURE_RESTRICTED,
            409,
        )
        refused = validate_success(
            flow.api.get_review_gate(accessibility_gate["id"], MANAGING_EDITOR)
        )
        assert refused["state"] == "PENDING"
        assert refused["decided_at"] is None
        assert_version(refused, 1)

        approved = validate_success(
            flow.api.decide_review_gate(
                accessibility_gate["id"],
                "APPROVED",
                ACCESSIBILITY_REVIEWER,
                "Alt text and contrast verified.",
            )
        )
        assert_gate(
            approved, state="APPROVED", turnaround_hours=30.00, sla_breached=False
        )

        assert_gate(
            flow.gate_of(item["id"], "SME"), state="PENDING", sla_breached=True
        )
        assert_gate(
            flow.gate_of(item["id"], "BRAND"), state="PENDING", sla_breached=True
        )

        after = flow.read_campaign(campaign["id"])
        assert_posture(after, "RESTRICTED")
        assert_campaign_counters(after, breached_gate_count=2)
        assert flow.read_item(item["id"])["workflow_state"] == "IN_REVIEW"


class TestWaiverScope:
    """Waivability is a property of the gate dimension, not of the caller."""

    def test_only_brand_and_accessibility_gates_accept_a_waiver(self, flow):
        """
        The assigned expert clears both the ownership and the gate-role rungs and is still
        refused for waiving an SME gate, the same expert's approval goes through, and the
        editor's waivers on the other two dimensions carry the item to READY on a mixed
        set of approved and waived gates.

        Design: Corner/errors/only_brand_and_accessibility_gates_are_waivable_and_not_even_by_their_own_reviewer
        """
        flow.set_clock(SETUP_CLOCK)

        campaign = flow.active_campaign(
            code="CMP-WAIVER", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
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
            week_monday="2026-08-03",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=PLANNED_PUBLISH,
        )
        flow.submit(item["id"])

        gates = flow.gates(item["id"])
        assert gates[0]["gate_type"] == "SME"
        sme_gate, brand_gate, accessibility_gate = gates[0], gates[1], gates[2]

        validate_error(
            flow.api.decide_review_gate(
                sme_gate["id"],
                "WAIVED",
                expert_headers(expert_id),
                "Author is the expert, no separate review needed.",
            ),
            ERR_GATE_NOT_WAIVABLE,
            422,
        )
        refused = validate_success(
            flow.api.get_review_gate(sme_gate["id"], MANAGING_EDITOR)
        )
        assert refused["state"] == "PENDING"
        assert refused["decided_at"] is None
        assert refused["decision_notes"] is None
        assert_version(refused, 1)

        waived_brand = validate_success(
            flow.api.decide_review_gate(
                brand_gate["id"],
                "WAIVED",
                MANAGING_EDITOR,
                "Brand template unchanged from the approved family.",
            )
        )
        assert waived_brand["state"] == "WAIVED"
        assert waived_brand["decided_by_user_id"] == EDITOR_ONE_ID

        approved_sme = validate_success(
            flow.api.decide_review_gate(
                sme_gate["id"],
                "APPROVED",
                expert_headers(expert_id),
                "Technical accuracy confirmed.",
            )
        )
        assert approved_sme["state"] == "APPROVED"

        waived_accessibility = validate_success(
            flow.api.decide_review_gate(
                accessibility_gate["id"],
                "WAIVED",
                MANAGING_EDITOR,
                "Accessibility audit deferred to the quarterly sweep.",
            )
        )
        assert waived_accessibility["state"] == "WAIVED"

        assert flow.read_item(item["id"])["workflow_state"] == "READY"
        assert_list_response(
            flow.api.list_review_gates(
                item["id"], MANAGING_EDITOR, {"state": "WAIVED"}
            ),
            expected_total_count=2,
            expected_row_count=2,
        )
        final_campaign = flow.read_campaign(campaign["id"])
        assert_posture(final_campaign, "OPEN")
        assert_campaign_counters(final_campaign, breached_gate_count=0)
