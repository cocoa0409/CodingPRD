"""
Entity shapes, declared defaults, and the listing contract.

Every row is checked for the fields the contract declares — echoed inputs,
server-minted system fields, computed fields and the pagination envelope — and
for the fields it deliberately withholds.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ASSET_NOT_FOUND,
    ERR_BRIEF_NOT_FOUND,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CONTENT_ITEM_NOT_FOUND,
    ERR_EXPERT_NOT_FOUND,
    ERR_GATE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SLOT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_bare_uuid,
    assert_campaign_counters,
    assert_error_envelope_meta,
    assert_immutable_row,
    assert_instant_precision,
    assert_list_response,
    assert_object_response,
    assert_posture,
    assert_slot_commitment,
    assert_two_decimal_value,
    assert_version,
)
from test_helpers.test_users import (
    ANALYTICS_SERVICE,
    BRAND_REVIEWER,
    EDITOR_ONE_ID,
    LEGAL_REVIEWER,
    MANAGING_EDITOR,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"


class TestCampaignCreation:
    """A created campaign carries every declared field at its declared default."""

    def test_campaign_create_returns_every_field_with_system_defaults(self, flow):
        """
        A campaign created from an empty database echoes its four inputs and reports
        every system field at its declared default: planning status, open posture,
        four zeroed counters and version 1, all inside the success envelope.

        Design: Corner/entities/campaign_create_returns_every_declared_field_with_system_defaults
        """
        response = flow.api.create_campaign(
            f.campaign_payload(
                code="CMP-CREATE",
                persona="PRACTITIONER",
                primary_funnel_stage="CONSIDERATION",
                quarter_code="2026Q3",
            ),
            MANAGING_EDITOR,
        )

        campaign = assert_object_response(response, 201)
        assert campaign["code"] == "CMP-CREATE"
        assert campaign["persona"] == "PRACTITIONER"
        assert campaign["primary_funnel_stage"] == "CONSIDERATION"
        assert campaign["quarter_code"] == "2026Q3"
        assert campaign["status"] == "PLANNING"
        assert_posture(campaign, "OPEN")
        assert_campaign_counters(campaign, committed_points_total=0)
        assert_version(campaign, 1)
        assert_bare_uuid(campaign["id"])
        assert_instant_precision(campaign["created_at"])
        assert_instant_precision(campaign["updated_at"])

    def test_campaign_system_fields_are_server_minted(self, flow):
        """
        A create body that supplies an id, a creation instant, a version and a status
        has none of the four honoured: the server mints its own identifier and
        timestamp, starts the version at 1 and forces the planning status.

        Design: Corner/entities/campaign_system_fields_are_server_minted_and_client_values_are_ignored_input
        """
        response = flow.api.create_campaign(
            f.campaign_payload(
                code="CMP-SYSFLD",
                persona="DEVELOPER",
                primary_funnel_stage="AWARENESS",
                quarter_code="2026Q4",
                id="11111111-1111-4111-8111-111111111111",
                created_at="2020-01-01T00:00:00.000Z",
                version=77,
                status="CLOSED",
            ),
            MANAGING_EDITOR,
        )

        campaign = validate_success(response, 201)
        assert campaign["id"] != "11111111-1111-4111-8111-111111111111"
        assert campaign["created_at"] != "2020-01-01T00:00:00.000Z"
        assert_version(campaign, 1)
        assert campaign["status"] == "PLANNING"
        assert campaign["code"] == "CMP-SYSFLD"

    def test_campaign_create_without_persona_is_a_shape_error(self, flow):
        """
        The persona is a required input with no default, so omitting it is rejected as
        a malformed request and no campaign row is created.

        Design: Corner/entities/campaign_create_missing_required_persona_returns_invalid_request
        """
        response = flow.api.create_campaign(
            {
                "code": "CMP-NOPERSONA",
                "primary_funnel_stage": "DECISION",
                "quarter_code": "2026Q3",
            },
            MANAGING_EDITOR,
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR), expected_total_count=0
        )


class TestCalendarSlotReads:
    """A slot reads back exactly as stored, and its list applies filters before paging."""

    def test_calendar_slot_read_by_id_returns_the_stored_row(self, flow):
        """
        A freshly created slot read through its own endpoint returns the parent
        campaign, week, funnel stage and capacity it was created with, and reports an
        empty commitment: zero points, 0.00 percent and open.

        Design: Corner/entities/calendar_slot_read_by_id_returns_the_stored_row
        """
        campaign = flow.create_campaign(
            code="CMP-READ", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="DECISION",
            capacity_points=40,
        )

        row = assert_object_response(
            flow.api.get_calendar_slot(slot["id"], BRAND_REVIEWER)
        )

        assert row["campaign_id"] == campaign["id"]
        assert row["week_start_date"] == "2026-08-03"
        assert row["funnel_stage"] == "DECISION"
        assert row["capacity_points"] == 40
        assert_slot_commitment(row, 0, 0.00, "OPEN")
        assert_version(row, 1)

    def test_calendar_slot_list_filters_before_it_pages(self, flow):
        """
        Two of the campaign's three slots are decision-stage, so a filtered page of
        one row reports a pre-page total of 2 with more to come, the second page
        returns the other decision slot, an unfiltered list returns all three under
        the default page window, and the awareness slot never appears.

        Design: Corner/entities/calendar_slot_list_filters_by_funnel_stage_and_honours_limit_and_offset
        """
        campaign = flow.create_campaign(
            code="CMP-LIST", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot_one = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        slot_two = flow.create_slot(
            campaign["id"], week_start_date="2026-08-10", funnel_stage="DECISION",
            capacity_points=30,
        )
        slot_three = flow.create_slot(
            campaign["id"], week_start_date="2026-08-17", funnel_stage="AWARENESS",
            capacity_points=20,
        )

        first_page = assert_list_response(
            flow.api.list_calendar_slots(
                MANAGING_EDITOR,
                {
                    "campaign_id": campaign["id"],
                    "funnel_stage": "DECISION",
                    "limit": 1,
                    "offset": 0,
                },
            ),
            expected_total_count=2,
            expected_has_more=True,
            expected_limit=1,
            expected_offset=0,
            expected_row_count=1,
        )

        assert first_page[0]["id"] == slot_one["id"]
        second_page = assert_list_response(
            flow.api.list_calendar_slots(
                MANAGING_EDITOR,
                {
                    "campaign_id": campaign["id"],
                    "funnel_stage": "DECISION",
                    "limit": 1,
                    "offset": 1,
                },
            ),
            expected_total_count=2,
            expected_has_more=False,
            expected_row_count=1,
        )
        assert second_page[0]["id"] == slot_two["id"]
        unfiltered = assert_list_response(
            flow.api.list_calendar_slots(
                MANAGING_EDITOR, {"campaign_id": campaign["id"]}
            ),
            expected_total_count=3,
            expected_limit=10,
            expected_offset=0,
            expected_row_count=3,
        )
        assert slot_three["id"] in [row["id"] for row in unfiltered]
        assert slot_three["id"] not in [
            row["id"] for row in first_page + second_page
        ]


def _one_row_per_filter_across_the_aggregates(flow):
    """
    Two campaigns arranged so every declared list filter has a matching and a
    non-matching row: campaign A is active with two slots, two briefs and one
    item, campaign B stays in planning with nothing under it.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign_a = flow.active_campaign(
        code="CMP-LISTA",
        persona="IT_BUYER",
        primary_funnel_stage="AWARENESS",
        quarter_code="2026Q3",
    )
    campaign_b = flow.create_campaign(
        code="CMP-LISTB",
        persona="EXECUTIVE",
        primary_funnel_stage="DECISION",
        quarter_code="2026Q4",
    )
    slot_one = flow.create_slot(
        campaign_a["id"], week_start_date="2026-08-03", funnel_stage="AWARENESS",
        capacity_points=40,
    )
    slot_two = flow.create_slot(
        campaign_a["id"], week_start_date="2026-08-10", funnel_stage="AWARENESS",
        capacity_points=30,
    )
    expert_one = flow.create_expert(
        full_name="Ines Baro", expertise_tags=["security"], weekly_capacity_hours=40
    )
    expert_two = flow.create_expert(
        full_name="Omar Kelly", expertise_tags=["analytics"], weekly_capacity_hours=20
    )
    flow.set_availability(expert_two["id"], "ON_LEAVE")
    brief_one = flow.create_brief(
        campaign_a["id"],
        funnel_stage="AWARENESS",
        effort_points=6,
        required_expertise_tag="security",
    )
    flow.assign_sme(brief_one["id"], expert_one["id"])
    flow.approve_brief(brief_one["id"], expert_one["id"])
    brief_two = flow.create_brief(
        campaign_a["id"],
        funnel_stage="AWARENESS",
        effort_points=6,
        required_expertise_tag="security",
    )
    item = flow.create_item(
        brief_one["id"],
        slot_one["id"],
        campaign_a["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    asset = flow.create_asset(
        name="List coverage stock photo",
        asset_type="STOCK",
        licensed_channels=["OWNED"],
        max_licensed_uses=3,
    )
    usage = flow.attach_usage(item["id"], asset["id"], channel="OWNED")
    return {
        "campaign_a": campaign_a,
        "campaign_b": campaign_b,
        "slot_one": slot_one,
        "slot_two": slot_two,
        "expert_one": expert_one,
        "expert_two": expert_two,
        "brief_one": brief_one,
        "brief_two": brief_two,
        "item": item,
        "asset": asset,
        "usage": usage,
    }


class TestDeclaredListFilters:
    """Every declared query parameter narrows its collection."""

    def test_every_declared_filter_narrows_its_own_collection(self, flow):
        """
        Each collection is queried through each filter it declares — campaign status,
        persona and quarter, slot funnel stage, expert status and expertise tag, brief
        campaign, state and expert, item campaign and workflow state, and usage state
        — and every one narrows to the matching row while the envelope keeps reporting
        the pre-page total; the empty planning campaign lists as an empty collection
        rather than a missing one.

        Design: Corner/entities/collection_lists_filter_by_their_declared_query_parameters_on_every_aggregate
        """
        chain = _one_row_per_filter_across_the_aggregates(flow)

        active = assert_list_response(
            flow.api.list_campaigns(
                MANAGING_EDITOR, {"status": "ACTIVE", "limit": 1, "offset": 0}
            ),
            expected_total_count=1,
            expected_has_more=False,
            expected_limit=1,
            expected_offset=0,
            expected_row_count=1,
        )
        assert active[0]["id"] == chain["campaign_a"]["id"]
        assert active[0]["status"] == "ACTIVE"
        assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR), expected_total_count=2
        )
        executives = assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR, {"persona": "EXECUTIVE"}),
            expected_total_count=1,
        )
        assert executives[0]["id"] == chain["campaign_b"]["id"]
        quarter = assert_list_response(
            flow.api.list_campaigns(MANAGING_EDITOR, {"quarter_code": "2026Q3"}),
            expected_total_count=1,
        )
        assert quarter[0]["id"] == chain["campaign_a"]["id"]

        slots = assert_list_response(
            flow.api.list_campaign_calendar_slots(
                chain["campaign_a"]["id"], MANAGING_EDITOR, {"funnel_stage": "AWARENESS"}
            ),
            expected_total_count=2,
        )
        assert [row["id"] for row in slots] == [
            chain["slot_one"]["id"],
            chain["slot_two"]["id"],
        ]
        assert_list_response(
            flow.api.list_campaign_calendar_slots(
                chain["campaign_b"]["id"], MANAGING_EDITOR
            ),
            expected_total_count=0,
            expected_row_count=0,
        )

        on_leave = assert_list_response(
            flow.api.list_experts(MANAGING_EDITOR, {"status": "ON_LEAVE"}),
            expected_total_count=1,
        )
        assert on_leave[0]["id"] == chain["expert_two"]["id"]
        assert on_leave[0]["status"] == "ON_LEAVE"
        tagged = assert_list_response(
            flow.api.list_experts(
                MANAGING_EDITOR, {"expertise_tag": "security", "limit": 1, "offset": 0}
            ),
            expected_total_count=1,
            expected_has_more=False,
        )
        assert tagged[0]["id"] == chain["expert_one"]["id"]

        approved = assert_list_response(
            flow.api.list_briefs(
                MANAGING_EDITOR,
                {"campaign_id": chain["campaign_a"]["id"], "state": "APPROVED"},
            ),
            expected_total_count=1,
        )
        assert approved[0]["id"] == chain["brief_one"]["id"]
        assert approved[0]["state"] == "APPROVED"
        drafts = assert_list_response(
            flow.api.list_briefs(
                MANAGING_EDITOR,
                {"campaign_id": chain["campaign_a"]["id"], "state": "DRAFT"},
            ),
            expected_total_count=1,
        )
        assert drafts[0]["id"] == chain["brief_two"]["id"]
        by_expert = assert_list_response(
            flow.api.list_briefs(
                MANAGING_EDITOR, {"sme_expert_id": chain["expert_one"]["id"]}
            ),
            expected_total_count=1,
        )
        assert by_expert[0]["id"] == chain["brief_one"]["id"]

        items = assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"campaign_id": chain["campaign_a"]["id"]}
            ),
            expected_total_count=1,
        )
        assert items[0]["id"] == chain["item"]["id"]
        assert items[0]["workflow_state"] == "DRAFT"
        assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"campaign_id": chain["campaign_b"]["id"]}
            ),
            expected_total_count=0,
        )
        assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"workflow_state": "PUBLISHED"}
            ),
            expected_total_count=0,
        )

        usages = assert_list_response(
            flow.api.list_asset_usages(
                chain["asset"]["id"], MANAGING_EDITOR, {"usage_state": "ACTIVE"}
            ),
            expected_total_count=1,
        )
        assert usages[0]["id"] == chain["usage"]["id"]
        assert usages[0]["channel"] == "OWNED"
        assert_list_response(
            flow.api.list_asset_usages(
                chain["asset"]["id"], MANAGING_EDITOR, {"usage_state": "RELEASED"}
            ),
            expected_total_count=0,
        )


class TestNotFoundSurface:
    """Every path-addressed entity answers its own dedicated not-found code."""

    def test_each_lookup_answers_its_own_not_found_error(self, flow):
        """
        A syntactically valid but unused identifier on each of the eight
        path-addressed reads answers that entity's own not-found code against an
        empty database, and each error body carries an identifier and a message.

        Design: Corner/entities/unknown_ids_on_every_lookup_return_the_matching_not_found_error
        """
        lookups = [
            (flow.api.get_campaign, ERR_CAMPAIGN_NOT_FOUND),
            (flow.api.get_calendar_slot, ERR_SLOT_NOT_FOUND),
            (flow.api.get_expert, ERR_EXPERT_NOT_FOUND),
            (flow.api.get_brief, ERR_BRIEF_NOT_FOUND),
            (flow.api.get_content_item, ERR_CONTENT_ITEM_NOT_FOUND),
            (flow.api.get_review_gate, ERR_GATE_NOT_FOUND),
            (flow.api.get_claim, ERR_CLAIM_NOT_FOUND),
            (flow.api.get_asset, ERR_ASSET_NOT_FOUND),
        ]

        for read, expected_error in lookups:
            response = read(NON_EXISTENT_UUID, MANAGING_EDITOR)
            error = validate_error(response, expected_error, 404)
            assert error["message"]
            assert_error_envelope_meta(response)

    def test_a_slot_create_under_an_unknown_campaign_is_not_found(self, flow):
        """
        The nested create path carries a valid but unused campaign identifier, so the
        parent existence check answers first even though the body is well formed, and
        no slot is written.

        Design: Corner/entities/calendar_slot_create_under_an_unknown_parent_campaign_returns_not_found
        """
        response = flow.api.create_calendar_slot(
            NON_EXISTENT_UUID,
            f.calendar_slot_payload(
                week_start_date="2026-08-03",
                funnel_stage="DECISION",
                capacity_points=40,
            ),
            MANAGING_EDITOR,
        )

        validate_error(response, ERR_CAMPAIGN_NOT_FOUND, 404)
        assert_list_response(
            flow.api.list_calendar_slots(MANAGING_EDITOR), expected_total_count=0
        )


class TestDeclaredDefaultsAndComputedFields:
    """Omitted optional inputs take their declared defaults; computed fields ignore input."""

    def test_omitted_optional_inputs_take_their_declared_defaults(self, flow):
        """
        A brief created without secondary keywords and an item created without a
        promotion window or tags take the declared defaults — an empty keyword list,
        a three-day promotion window, an empty tag list, no metadata yet and no
        regulated review — rather than nulls or a seven-day window.

        Design: Corner/entities/content_item_promotion_window_days_defaults_to_three_when_omitted
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-DEFAULT", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=40,
        )
        brief, _expert_id = flow.approved_brief(
            campaign["id"], funnel_stage="DECISION", expertise_tag="security"
        )

        item = validate_success(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief["id"],
                    slot["id"],
                    flow.campaign_version(campaign["id"]),
                    title="Zero trust platform pricing guide",
                    planned_publish_at="2026-08-05T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert item["promotion_window_days"] == 3
        assert item["tags"] == []
        assert item["meta_description"] is None
        assert item["url_slug"] is None
        stored_brief = flow.read_brief(brief["id"])
        assert stored_brief["secondary_keywords"] == []
        assert stored_brief["requires_regulated_review"] is False

    def test_brief_effort_and_reserved_hours_ignore_client_supplied_values(self, flow):
        """
        A create body that supplies its own effort, reserved hours and state is
        overruled: the stored brief reads 16 effort points and 8 reserved hours from
        the commercial intent, the three word blocks and the decision uplift, and
        starts unassigned in draft at version 1.

        Design: Corner/entities/brief_effort_points_are_computed_and_client_supplied_values_are_ignored_input
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-COMPUTED", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )

        brief = validate_success(
            flow.api.create_brief(
                f.brief_payload(
                    campaign["id"],
                    funnel_stage="DECISION",
                    search_intent="COMMERCIAL",
                    primary_keyword="zero trust platform pricing",
                    target_word_count=1500,
                    required_expertise_tag="security",
                    review_window_start="2026-08-03T09:00:00.000Z",
                    review_window_end="2026-08-04T09:00:00.000Z",
                    effort_points=99,
                    sme_reserved_hours=99,
                    state="APPROVED",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert brief["effort_points"] == 16
        assert brief["sme_reserved_hours"] == 8
        assert brief["state"] == "DRAFT"
        assert brief["sme_expert_id"] is None
        assert_version(brief, 1)

    def test_out_of_enum_and_non_monday_inputs_are_shape_errors(self, flow):
        """
        An unknown search intent and a week start that falls on a Tuesday are both
        rejected as malformed requests, and neither the brief nor the slot is
        persisted.

        Design: Corner/entities/brief_search_intent_outside_the_declared_enum_is_invalid_enum
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-ENUM", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )

        bad_enum = flow.api.create_brief(
            f.brief_payload(
                campaign["id"],
                funnel_stage="DECISION",
                search_intent="SUPPORT",
                primary_keyword="zero trust platform pricing",
                target_word_count=1500,
                required_expertise_tag="security",
                review_window_start="2026-08-03T09:00:00.000Z",
                review_window_end="2026-08-04T09:00:00.000Z",
            ),
            MANAGING_EDITOR,
        )
        bad_week = flow.api.create_calendar_slot(
            campaign["id"],
            f.calendar_slot_payload(
                week_start_date="2026-08-04",
                funnel_stage="DECISION",
                capacity_points=40,
            ),
            MANAGING_EDITOR,
        )

        validate_error(bad_enum, ERR_INVALID_REQUEST, 400)
        validate_error(bad_week, ERR_INVALID_REQUEST, 400)
        assert_list_response(
            flow.api.list_briefs(MANAGING_EDITOR, {"campaign_id": campaign["id"]}),
            expected_total_count=0,
        )
        assert_list_response(
            flow.api.list_campaign_calendar_slots(campaign["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )


class TestAppendOnlyRows:
    """Evidence and measurement rows carry no version and no update verb."""

    def test_evidence_and_snapshot_rows_omit_updated_at_and_version(self, flow):
        """
        Both append-only rows expose an identifier and a creation instant and nothing
        more: no modification instant and no version, because the only way their
        content changes is by appending another row. The evidence weight and the
        filing operator are recorded, and the measurement row links to its item.

        Design: Corner/entities/evidence_and_performance_snapshot_are_immutable_rows_without_a_version_field
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        claim = flow.create_claim(chain["item"]["id"], claim_type="PERFORMANCE")
        evidence = flow.file_evidence(
            claim["id"],
            source_type="THIRD_PARTY_TEST",
            citation="Independent lab report LR-2026-114, section 4.",
            collected_at="2026-08-02T00:00:00.000Z",
            valid_until="2027-08-02T00:00:00.000Z",
        )
        flow.set_clock("2026-08-10T00:00:00.000Z")
        snapshot = flow.snapshot(
            chain["item"]["id"],
            "2026-08-03T08:00:00.000Z",
            "2026-08-10T00:00:00.000Z",
            engaged_sessions=120,
            conversions=3,
            influenced_opportunity_amount_cents=250000,
            touch_position="LAST",
        )

        evidence_rows = assert_list_response(
            flow.api.list_claim_evidence(claim["id"], LEGAL_REVIEWER),
            expected_total_count=1,
        )
        snapshot_rows = assert_list_response(
            flow.api.list_performance_snapshots(chain["item"]["id"], ANALYTICS_SERVICE),
            expected_total_count=1,
        )

        assert evidence_rows[0]["id"] == evidence["id"]
        assert_immutable_row(evidence_rows[0])
        assert snapshot_rows[0]["id"] == snapshot["id"]
        assert_immutable_row(snapshot_rows[0])
        assert_two_decimal_value(evidence_rows[0]["weight"], 2.0)
        assert evidence_rows[0]["submitted_by_user_id"] == EDITOR_ONE_ID
        assert snapshot_rows[0]["content_item_id"] == chain["item"]["id"]


class TestAssetUsageJunction:
    """One asset reaches several items through the usage junction."""

    def test_one_asset_carries_usages_on_two_items_across_channels(self, flow):
        """
        The junction is readable from both ends: the asset lists both of its usages in
        attachment order while each item lists only its own, the second usage records
        its item, asset and channel, and the asset's budget falls by two.

        Design: Corner/entities/asset_usage_junction_links_one_asset_to_several_items_across_channels
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-GRAPH", persona="IT_BUYER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="AWARENESS",
            capacity_points=40,
        )
        items = []
        for publish_at, title in (
            ("2026-08-04T00:00:00.000Z", "Zero trust glossary"),
            ("2026-08-06T00:00:00.000Z", "Zero trust myth list"),
        ):
            brief, _expert_id = flow.approved_brief(
                campaign["id"],
                funnel_stage="AWARENESS",
                effort_points=6,
                expertise_tag="security",
            )
            items.append(
                flow.create_item(
                    brief["id"],
                    slot["id"],
                    campaign["id"],
                    title=title,
                    planned_publish_at=publish_at,
                    promotion_window_days=1,
                )
            )
        asset = flow.create_asset(
            name="Shared rack photography",
            asset_type="STOCK",
            licensed_channels=["OWNED", "EMAIL"],
            max_licensed_uses=5,
        )
        first_usage = flow.attach_usage(items[0]["id"], asset["id"], channel="OWNED")

        second_usage = validate_success(
            flow.api.attach_asset_usage(
                items[1]["id"],
                f.asset_usage_payload(asset["id"], channel="EMAIL"),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert second_usage["content_item_id"] == items[1]["id"]
        assert second_usage["asset_id"] == asset["id"]
        assert second_usage["channel"] == "EMAIL"
        assert second_usage["usage_state"] == "ACTIVE"
        rows = assert_list_response(
            flow.api.list_asset_usages(asset["id"], MANAGING_EDITOR),
            expected_total_count=2,
        )
        assert [row["id"] for row in rows] == [first_usage["id"], second_usage["id"]]
        first_item_rows = assert_list_response(
            flow.api.list_item_asset_usages(items[0]["id"], MANAGING_EDITOR),
            expected_total_count=1,
        )
        assert first_item_rows[0]["id"] == first_usage["id"]
        second_item_rows = assert_list_response(
            flow.api.list_item_asset_usages(items[1]["id"], MANAGING_EDITOR),
            expected_total_count=1,
        )
        assert second_item_rows[0]["id"] == second_usage["id"]
        assert_asset_rights(
            flow.read_asset(asset["id"]),
            active_use_count=2,
            remaining_licensed_uses=3,
        )
