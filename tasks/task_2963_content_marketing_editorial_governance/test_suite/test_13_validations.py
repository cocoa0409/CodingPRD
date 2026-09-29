"""
The validation ladder: which rung answers when several are violated at once.

Every case here violates two or more rules in a single call and asserts the
one error the declared order requires, then repairs exactly the higher rung so
the lower one becomes reachable. Where a rule is a boundary, both sides of the
boundary are exercised.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACCESSIBILITY_METADATA_MISSING,
    ERR_BRIEF_ALREADY_HAS_ITEM,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CLOCK_REWIND,
    ERR_GATE_ROLE_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_PUBLISH_OUTSIDE_SLOT_WEEK,
    ERR_REGULATED_REVIEW_REQUIRED,
    ERR_SLOT_CAMPAIGN_MISMATCH,
    ERR_SLOT_DUPLICATE_WEEK,
    ERR_SME_NOT_ASSIGNED_TO_BRIEF,
    ERR_STALE_EXPERT_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_distribution_channel_order,
    assert_gate,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
)
from test_helpers.test_users import (
    ACCESSIBILITY_REVIEWER,
    ANALYTICS_SERVICE,
    EDITOR_TWO_ID,
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    blank_auth_headers,
    expert_headers,
    undeclared_role_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
IN_WEEK_LAST_INSTANT = "2026-08-09T23:59:59.999Z"
OUT_OF_WEEK_INSTANT = "2026-08-10T00:00:00.000Z"
COMPLIANT_META = (
    "A practical buyer guide to zero trust platform pricing for security "
    "and procurement teams."
)


class TestAuthLadder:
    """Authentication outranks authorisation, which outranks existence."""

    def test_unauthenticated_outranks_unauthorized_which_outranks_not_found(self, flow):
        """
        One never-minted campaign id is probed four ways: zero-length auth values and a
        role string outside the declared six both answer unauthenticated, a declared but
        unlisted role answers unauthorized even though the id does not exist, and only
        the authorised role is told the row is missing.

        Design: Corner/validations/auth_ladder_unauthenticated_outranks_unauthorized_which_outranks_not_found
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.create_campaign(
            code="CMP-AUTH", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )

        validate_error(
            flow.api.get_campaign(NON_EXISTENT_UUID, blank_auth_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            flow.api.get_campaign(NON_EXISTENT_UUID, undeclared_role_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            flow.api.get_campaign(NON_EXISTENT_UUID, ANALYTICS_SERVICE),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            flow.api.get_campaign(NON_EXISTENT_UUID, MANAGING_EDITOR),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )

        satisfied = validate_success(
            flow.api.get_campaign(campaign["id"], MANAGING_EDITOR)
        )
        assert satisfied["status"] == "PLANNING"


class TestShapeBeforeForeignKey:
    """The body shape gate runs before any body foreign key is dereferenced."""

    def test_body_shape_check_outranks_body_foreign_key_existence(self, flow):
        """
        A brief create carrying both an undeclared search intent and an unknown campaign
        answers the shape error; repairing only the enum leaves the same unknown campaign
        in place and the answer becomes the existence error, with nothing persisted
        either way.

        Design: Corner/validations/body_shape_check_outranks_body_foreign_key_existence
        """
        flow.set_clock(SETUP_CLOCK)
        base = dict(
            funnel_stage="DECISION",
            primary_keyword="zero trust platform pricing",
            target_word_count=1500,
            required_expertise_tag="security",
            review_window_start="2026-08-03T09:00:00.000Z",
            review_window_end="2026-08-03T17:00:00.000Z",
        )

        validate_error(
            flow.api.create_brief(
                f.brief_payload(NON_EXISTENT_UUID, search_intent="BROWSING", **base),
                MANAGING_EDITOR,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        validate_error(
            flow.api.create_brief(
                f.brief_payload(NON_EXISTENT_UUID, search_intent="COMMERCIAL", **base),
                MANAGING_EDITOR,
            ),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )

        assert_list_response(
            flow.api.list_briefs(MANAGING_EDITOR),
            expected_total_count=0,
            expected_row_count=0,
        )


class TestLogicalClockMonotonicity:
    """The clock may stand still but never step back."""

    def test_clock_accepts_an_equal_instant_and_rejects_any_rewind(self, flow):
        """
        Re-setting the clock to the instant it already holds is accepted, a rewind of a
        single millisecond is refused, and the refused call leaves the clock exactly
        where it was, which the following one-millisecond advance proves.

        Design: Corner/validations/logical_clock_accepts_an_equal_instant_and_rejects_any_rewind
        """
        flow.set_clock(SETUP_CLOCK)

        equal = validate_success(flow.api.set_clock(SETUP_CLOCK, MANAGING_EDITOR))
        assert equal["current_utc"] == SETUP_CLOCK

        validate_error(
            flow.api.set_clock("2026-08-03T07:59:59.999Z", MANAGING_EDITOR),
            ERR_CLOCK_REWIND,
            422,
        )

        forward = validate_success(
            flow.api.set_clock("2026-08-03T08:00:00.001Z", MANAGING_EDITOR)
        )
        assert forward["current_utc"] == "2026-08-03T08:00:00.001Z"


class TestSlotCreateLadder:
    """Slot uniqueness is the campaign, week and funnel-stage triple."""

    def test_duplicate_week_and_stage_is_refused_while_other_triples_are_allowed(
        self, flow
    ):
        """
        The triple of owning campaign, week_start_date and funnel_stage is unique, so a
        campaign may hold one awareness slot and one decision slot in the same week but
        not two decision slots; the duplicate answers ERR_SLOT_DUPLICATE_WEEK and the
        original slot is left exactly as it was.
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-DUPWEEK", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )

        validate_error(
            flow.api.create_calendar_slot(
                campaign["id"],
                f.calendar_slot_payload(
                    week_start_date="2026-08-03", funnel_stage="DECISION",
                    capacity_points=25,
                ),
                MANAGING_EDITOR,
            ),
            ERR_SLOT_DUPLICATE_WEEK,
            409,
        )
        # The same week at a different funnel stage is a different triple.
        validate_success(
            flow.api.create_calendar_slot(
                campaign["id"],
                f.calendar_slot_payload(
                    week_start_date="2026-08-03", funnel_stage="AWARENESS",
                    capacity_points=25,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        # A different week at the same funnel stage is likewise a different triple.
        validate_success(
            flow.api.create_calendar_slot(
                campaign["id"],
                f.calendar_slot_payload(
                    week_start_date="2026-08-10", funnel_stage="DECISION",
                    capacity_points=25,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        survivor = flow.read_slot(slot["id"])
        assert survivor["capacity_points"] == 40
        assert survivor["status"] == "OPEN"
        assert_list_response(
            flow.api.list_campaign_calendar_slots(campaign["id"], MANAGING_EDITOR),
            expected_total_count=3,
            expected_row_count=3,
        )


class TestContentItemCreateLadder:
    """A brief that already owns a piece is refused before the slot is cross-checked."""

    def test_brief_already_has_item_outranks_the_slot_campaign_mismatch_check(self, flow):
        """
        Both attempts point at a slot belonging to a different campaign; the brief that
        already owns a piece answers the duplicate-brief error and only the untouched
        brief reaches the mismatch error, leaving the foreign slot and its campaign
        ledger at zero.

        Design: Corner/validations/brief_already_has_item_outranks_the_slot_campaign_mismatch_check
        """
        flow.set_clock(SETUP_CLOCK)
        campaign_a = flow.active_campaign(
            code="CMP-MIXA", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot_a = flow.create_slot(
            campaign_a["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        campaign_b = flow.active_campaign(
            code="CMP-MIXB", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot_b = flow.create_slot(
            campaign_b["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        expert = flow.create_expert(["security"], weekly_capacity_hours=40)
        brief_one, _ = flow.approved_brief(
            campaign_a["id"], funnel_stage="DECISION", expert_id=expert["id"],
            expertise_tag="security", search_intent="COMMERCIAL",
            target_word_count=1500,
            review_window_start="2026-08-03T09:00:00.000Z",
            review_window_end="2026-08-03T17:00:00.000Z",
        )
        brief_two, _ = flow.approved_brief(
            campaign_a["id"], funnel_stage="DECISION", expert_id=expert["id"],
            expertise_tag="security", search_intent="COMMERCIAL",
            target_word_count=1500,
            review_window_start="2026-08-04T09:00:00.000Z",
            review_window_end="2026-08-04T17:00:00.000Z",
        )
        item_one = flow.create_item(
            brief_one["id"], slot_a["id"], campaign_a["id"],
            title="Zero trust platform pricing guide",
            planned_publish_at="2026-08-05T09:00:00.000Z",
        )

        pinned_version = flow.campaign_version(campaign_a["id"])
        validate_error(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief_one["id"], slot_b["id"], pinned_version,
                    title="Zero trust platform pricing reprint",
                    planned_publish_at="2026-08-05T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            ERR_BRIEF_ALREADY_HAS_ITEM,
            409,
        )
        validate_error(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief_two["id"], slot_b["id"], pinned_version,
                    title="Zero trust vendor shortlist",
                    planned_publish_at="2026-08-05T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            ERR_SLOT_CAMPAIGN_MISMATCH,
            422,
        )

        assert_slot_commitment(flow.read_slot(slot_b["id"]), 0, 0.00, "OPEN")
        assert_slot_commitment(flow.read_slot(slot_a["id"]), 16, 40.00, "OPEN")
        assert_campaign_counters(
            flow.read_campaign(campaign_b["id"]), committed_points_total=0
        )
        rows = assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"campaign_id": campaign_a["id"]}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert rows[0]["id"] == item_one["id"]


class TestOptimisticConcurrencyRung:
    """A replayed expert version answers before the brief's own state check."""

    def test_stale_expert_version_outranks_the_brief_state_check(self, flow):
        """
        The second assignment on an already-assigned brief answers the stale-version
        error rather than the state error when the pre-assignment version is replayed,
        and the expert's weekly ledger does not move.

        Design: Corner/validations/stale_expert_version_outranks_the_brief_state_check
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-STALEV", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        expert = flow.create_expert(["security"], weekly_capacity_hours=40)
        stale_version = expert["version"]
        brief = flow.create_brief(
            campaign["id"], funnel_stage="DECISION", search_intent="COMMERCIAL",
            target_word_count=1500, required_expertise_tag="security",
            review_window_start="2026-08-03T09:00:00.000Z",
            review_window_end="2026-08-03T17:00:00.000Z",
        )
        assert brief["sme_reserved_hours"] == 8
        validate_success(
            flow.api.assign_sme(
                brief["id"],
                f.assign_sme_payload(expert["id"], stale_version),
                MANAGING_EDITOR,
            )
        )

        validate_error(
            flow.api.assign_sme(
                brief["id"],
                f.assign_sme_payload(expert["id"], stale_version),
                MANAGING_EDITOR,
            ),
            ERR_STALE_EXPERT_VERSION,
            412,
        )

        assert flow.read_brief(brief["id"])["state"] == "SME_ASSIGNED"
        held = flow.read_expert(expert["id"])
        assert held["committed_hours_total"] == 8
        assert held["version"] == 2


class TestGateDecisionAuthorisation:
    """Gate ownership is scoped to the expert dimension; role match covers the rest."""

    def test_sme_ownership_outranks_the_gate_role_match_check(self, flow):
        """
        An expert who is not the brief's assigned expert is stopped on the expert gate by
        the ownership rule, while that same assigned expert acting on the brand gate is
        stopped by the role rule, so the two refusals are told apart by which gate is
        targeted rather than by which role is acting.

        Design: Corner/validations/sme_ownership_outranks_the_gate_role_match_check
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        assigned_expert = chain["expert_id"]
        other_expert = flow.create_expert(["cloud-security"], weekly_capacity_hours=40)
        flow.submit(item_id)
        sme_gate = flow.gate_of(item_id, "SME")
        brand_gate = flow.gate_of(item_id, "BRAND")
        accessibility_gate = flow.gate_of(item_id, "ACCESSIBILITY")

        validate_error(
            flow.api.decide_review_gate(
                sme_gate["id"], "APPROVED", expert_headers(other_expert["id"])
            ),
            ERR_SME_NOT_ASSIGNED_TO_BRIEF,
            403,
        )
        validate_error(
            flow.api.decide_review_gate(
                brand_gate["id"], "APPROVED", expert_headers(assigned_expert)
            ),
            ERR_GATE_ROLE_MISMATCH,
            403,
        )
        decided = validate_success(
            flow.api.decide_review_gate(
                accessibility_gate["id"], "APPROVED", ACCESSIBILITY_REVIEWER
            )
        )
        assert decided["state"] == "APPROVED"

        untouched_sme = flow.gate_of(item_id, "SME")
        untouched_brand = flow.gate_of(item_id, "BRAND")
        assert_gate(untouched_sme, state="PENDING")
        assert untouched_sme["decided_by_user_id"] is None
        assert_gate(untouched_brand, state="PENDING")
        assert untouched_brand["decided_by_user_id"] is None
        assert flow.read_item(item_id)["workflow_state"] == "IN_REVIEW"


class TestRegulatedClaimScope:
    """The regulated-claim rule is conditional on the brief and scoped to one type."""

    def test_regulated_claim_scope_follows_the_brief_flag(self, flow):
        """
        Two pieces on one campaign differ only in whether their brief opted into
        regulated review: the identical regulated claim text is refused on the opted-out
        piece and accepted on the opted-in one, while a performance claim is accepted on
        both.

        Design: Corner/validations/regulated_claim_scope_applies_only_when_the_brief_opts_into_regulated_review
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-REGSCOPE", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        expert = flow.create_expert(["security"], weekly_capacity_hours=40)
        brief_x, _ = flow.approved_brief(
            campaign["id"], funnel_stage="DECISION", expert_id=expert["id"],
            expertise_tag="security", search_intent="COMMERCIAL",
            target_word_count=1500,
            review_window_start="2026-08-03T09:00:00.000Z",
            review_window_end="2026-08-03T17:00:00.000Z",
        )
        brief_y, _ = flow.approved_brief(
            campaign["id"], funnel_stage="DECISION", expert_id=expert["id"],
            expertise_tag="security", requires_regulated_review=True,
            search_intent="COMMERCIAL", target_word_count=1500,
            review_window_start="2026-08-04T06:00:00.000Z",
            review_window_end="2026-08-04T17:00:00.000Z",
        )
        assert brief_x["requires_regulated_review"] is False
        assert brief_x["effort_points"] == 16
        assert brief_y["effort_points"] == 21
        item_x = flow.create_item(
            brief_x["id"], slot["id"], campaign["id"],
            title="Zero trust platform pricing guide",
            planned_publish_at="2026-08-05T09:00:00.000Z",
        )
        item_y = flow.create_item(
            brief_y["id"], slot["id"], campaign["id"],
            title="Zero trust compliance posture guide",
            planned_publish_at="2026-08-06T09:00:00.000Z",
        )

        regulated_text = (
            "The platform meets the regional data residency mandate for regulated "
            "workloads."
        )
        validate_error(
            flow.api.create_claim(
                item_x["id"],
                f.claim_payload(claim_text=regulated_text, claim_type="REGULATED"),
                MANAGING_EDITOR,
            ),
            ERR_REGULATED_REVIEW_REQUIRED,
            422,
        )
        performance = validate_success(
            flow.api.create_claim(
                item_x["id"], f.claim_payload(claim_type="PERFORMANCE"), MANAGING_EDITOR
            ),
            201,
        )
        regulated = validate_success(
            flow.api.create_claim(
                item_y["id"],
                f.claim_payload(claim_text=regulated_text, claim_type="REGULATED"),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert performance["substantiation_state"] == "DRAFT"
        assert regulated["scoring_variant"] == "STRICT_REGULATED"
        assert_list_response(
            flow.api.list_item_claims(item_x["id"], MANAGING_EDITOR),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert_list_response(
            flow.api.list_item_claims(item_y["id"], MANAGING_EDITOR),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert_slot_commitment(flow.read_slot(slot["id"]), 37, 92.50, "OPEN")


class TestPublishLadder:
    """The accessibility floor answers before the slot-week window is examined."""

    def test_metadata_gate_runs_before_the_slot_week_gate(self, flow):
        """
        Four attempts on one ready piece separate the rungs: a short description and a
        single-tag body each answer the accessibility error even though the same call
        also schedules outside the slot week, and only a metadata-complete body reaches
        the week check, where the first instant of the following Monday is outside the
        half-open week and the last millisecond of Sunday is inside it.

        Design: Corner/validations/publish_metadata_gate_runs_before_the_slot_week_gate_and_the_week_is_half_open
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.ready_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        assert chain["item"]["workflow_state"] == "READY"

        validate_error(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at=OUT_OF_WEEK_INSTANT,
                    channels=["OWNED"],
                    meta_description="Zero trust pricing for security buyers.",
                    url_slug="zero-trust-pricing-short-meta",
                    tags=["security", "pricing"],
                ),
                MANAGING_EDITOR_TWO,
            ),
            ERR_ACCESSIBILITY_METADATA_MISSING,
            422,
        )
        validate_error(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at=OUT_OF_WEEK_INSTANT,
                    channels=["OWNED"],
                    meta_description=COMPLIANT_META,
                    url_slug="zero-trust-pricing-one-tag",
                    tags=["security"],
                ),
                MANAGING_EDITOR_TWO,
            ),
            ERR_ACCESSIBILITY_METADATA_MISSING,
            422,
        )
        validate_error(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at=OUT_OF_WEEK_INSTANT,
                    channels=["OWNED"],
                    meta_description=COMPLIANT_META,
                    url_slug="zero-trust-pricing-out-of-week",
                    tags=["security", "pricing"],
                ),
                MANAGING_EDITOR_TWO,
            ),
            ERR_PUBLISH_OUTSIDE_SLOT_WEEK,
            422,
        )

        published = validate_success(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at=IN_WEEK_LAST_INSTANT,
                    channels=["OWNED", "EMAIL"],
                    meta_description=COMPLIANT_META,
                    url_slug="zero-trust-platform-pricing-guide",
                    tags=["security", "pricing"],
                ),
                MANAGING_EDITOR_TWO,
            )
        )

        assert published["workflow_state"] == "PUBLISHED"
        assert published["published_by_user_id"] == EDITOR_TWO_ID
        assert published["url_slug"] == "zero-trust-platform-pricing-guide"
        assert published["published_at"] == SETUP_CLOCK
        rows = assert_list_response(
            flow.api.list_distributions(item_id, MANAGING_EDITOR),
            expected_total_count=2,
            expected_row_count=2,
        )
        assert_distribution_channel_order(rows)
        for row in rows:
            assert row["state"] == "SCHEDULED"
            assert row["scheduled_at"] == IN_WEEK_LAST_INSTANT
            assert row["went_live_at"] is None


class TestRightsRulesSatisfied:
    """An attach that satisfies every rights rule succeeds on each licensed channel."""

    def test_attach_succeeds_on_both_licensed_channels_of_one_asset(self, flow):
        """
        One attach clears four separate rights rules at once — the licence outlives the
        clock, the channel is licensed, a use remains in the budget and no other piece
        holds an overlapping promotion window — and a second attach on the other licensed
        channel of the same asset succeeds too, each consuming one licensed use.

        Design: Corner/validations/asset_usage_attach_that_satisfies_every_rights_rule_succeeds_on_both_licensed_channels
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        assert chain["item"]["promotion_window_days"] == 3
        asset = flow.create_asset(
            name="Zero trust hero photo",
            asset_type="STOCK",
            license_start="2026-07-01T00:00:00.000Z",
            license_end="2026-12-31T00:00:00.000Z",
            licensed_channels=["OWNED", "EMAIL"],
            max_licensed_uses=2,
        )

        owned = validate_success(
            flow.api.attach_asset_usage(
                item_id, f.asset_usage_payload(asset["id"], "OWNED"), MANAGING_EDITOR
            ),
            201,
        )
        email = validate_success(
            flow.api.attach_asset_usage(
                item_id, f.asset_usage_payload(asset["id"], "EMAIL"), MANAGING_EDITOR
            ),
            201,
        )

        assert owned["usage_state"] == "ACTIVE"
        assert owned["attached_at"] == SETUP_CLOCK
        assert owned["released_at"] is None
        assert email["usage_state"] == "ACTIVE"
        assert email["released_at"] is None
        assert_asset_rights(
            flow.read_asset(asset["id"]),
            status="LICENSED",
            active_use_count=2,
            remaining_licensed_uses=0,
        )
        assert_list_response(
            flow.api.list_asset_usages(
                asset["id"], MANAGING_EDITOR, {"usage_state": "ACTIVE"}
            ),
            expected_total_count=2,
            expected_row_count=2,
        )
        campaign = flow.read_campaign(chain["campaign"]["id"])
        assert_campaign_counters(campaign, expired_usage_count=0)
        assert_posture(campaign, "OPEN")
