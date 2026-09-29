"""
The declared formulas, their constants, and their rounding.

Each calculation is driven with inputs that make a plausible mis-implementation
land on a different number: a clamp that never fires, a rounding that goes the
other way, or an input set that admits a row the window excludes.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_EXPERT_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_gate,
    assert_gate_dimension_order,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
    assert_sweep_tally,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    ANALYTICS_SERVICE,
    BRAND_REVIEWER,
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"


class TestBriefEffortFormula:
    """Effort points and reserved hours follow the declared formula and its clamps."""

    def test_effort_points_and_reserved_hours_match_the_formula(self, flow):
        """
        A commercial decision-stage brief of 1500 words scores its intent base plus
        three whole word blocks plus the decision uplift, giving 16 effort points and
        half that, rounded up, as reserved hours.

        Design: Corner/calculations/brief_effort_points_and_reserved_hours_match_the_declared_formula
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-EFFORT", persona="IT_BUYER", primary_funnel_stage="DECISION"
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
                    review_window_end="2026-08-03T17:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert brief["effort_points"] == 16
        assert brief["sme_reserved_hours"] == 8
        assert brief["state"] == "DRAFT"
        assert brief["requires_regulated_review"] is False
        assert brief["secondary_keywords"] == []

    def test_effort_points_clamp_to_the_declared_floor_and_ceiling(self, flow):
        """
        Three briefs pin the clamp from both sides and in the middle: a raw 5 rises to
        the floor of 6, a raw 53 falls to the ceiling of 40 and a raw 14 passes through
        untouched, with the reserved hours always following the clamped figure.

        Design: Corner/calculations/brief_effort_points_clamp_to_the_declared_min_and_max_constants
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-CLAMP", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )

        low = validate_success(
            flow.api.create_brief(
                f.brief_payload(
                    campaign["id"],
                    funnel_stage="AWARENESS",
                    search_intent="NAVIGATIONAL",
                    primary_keyword="zero trust login",
                    target_word_count=100,
                    required_expertise_tag="security",
                    review_window_start="2026-08-03T09:00:00.000Z",
                    review_window_end="2026-08-03T12:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        high = validate_success(
            flow.api.create_brief(
                f.brief_payload(
                    campaign["id"],
                    funnel_stage="DECISION",
                    search_intent="TRANSACTIONAL",
                    primary_keyword="buy zero trust licences",
                    target_word_count=9000,
                    required_expertise_tag="security",
                    requires_regulated_review=True,
                    review_window_start="2026-08-04T02:00:00.000Z",
                    review_window_end="2026-08-04T22:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        mid = validate_success(
            flow.api.create_brief(
                f.brief_payload(
                    campaign["id"],
                    funnel_stage="CONSIDERATION",
                    search_intent="INFORMATIONAL",
                    primary_keyword="zero trust rollout stages",
                    target_word_count=2000,
                    required_expertise_tag="security",
                    review_window_start="2026-08-05T09:00:00.000Z",
                    review_window_end="2026-08-05T16:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert (low["effort_points"], low["sme_reserved_hours"]) == (6, 3)
        assert (high["effort_points"], high["sme_reserved_hours"]) == (40, 20)
        assert (mid["effort_points"], mid["sme_reserved_hours"]) == (14, 7)


class TestSlotUtilizationPrecision:
    """Utilization is two decimals, rounded half up in both directions."""

    def test_utilization_rounds_half_up_at_two_decimals_across_two_commits(self, flow):
        """
        A capacity of 30 makes both readings non-terminating: 16 of 30 renders 53.33 and
        26 of 30 renders 86.67, so one commitment pins the truncating direction and the
        other the rounding-up direction, while the integer ledgers stay exact.

        Design: Corner/calculations/slot_utilization_is_two_decimals_round_half_up_across_two_commits
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-UTIL", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        slot = flow.create_slot(
            campaign["id"], week_start_date="2026-08-03", funnel_stage="DECISION",
            capacity_points=30,
        )
        brief_one, _e1 = flow.approved_brief(
            campaign["id"], funnel_stage="DECISION", effort_points=16,
            expertise_tag="security",
        )
        brief_two, _e2 = flow.approved_brief(
            campaign["id"], funnel_stage="DECISION", effort_points=9,
            expertise_tag="security",
        )

        first = flow.create_item(
            brief_one["id"], slot["id"], campaign["id"],
            title="Zero trust platform pricing guide",
            planned_publish_at="2026-08-05T09:00:00.000Z",
        )
        after_first = flow.read_slot(slot["id"])
        second = flow.create_item(
            brief_two["id"], slot["id"], campaign["id"],
            title="Zero trust login basics",
            planned_publish_at="2026-08-06T09:00:00.000Z",
        )
        after_second = flow.read_slot(slot["id"])

        assert first["capacity_tier_at_commit"] == "LOW"
        assert first["commit_points"] == 16
        assert_slot_commitment(after_first, 16, 53.33, "OPEN")
        assert second["capacity_tier_at_commit"] == "MEDIUM"
        assert second["commit_points"] == 10
        assert_slot_commitment(after_second, 26, 86.67, "OPEN")
        assert_campaign_counters(
            flow.read_campaign(campaign["id"]), committed_points_total=26
        )


class TestExpertWeeklyLedger:
    """The weekly hour ledger counts only the states and the week the PRD names."""

    def test_weekly_hours_count_only_assigned_and_approved_briefs_in_that_week(
        self, flow
    ):
        """
        An expert with a twenty hour week holds one assigned and one approved brief in
        the target week; a third assignment lands exactly on capacity, a fourth in the
        same week is refused, and a fifth in a later week is admitted, which shows the
        ledger sums reserved hours per ISO week and ignores briefs still in draft.

        Design: Corner/calculations/expert_week_committed_hours_counts_only_assigned_and_approved_briefs_in_the_target_week
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-WEEK", persona="IT_BUYER", primary_funnel_stage="DECISION"
        )
        expert = flow.create_expert(["security"], weekly_capacity_hours=20)

        def brief(word_count: int, start: str, end: str):
            return flow.create_brief(
                campaign["id"],
                funnel_stage="DECISION",
                search_intent="INFORMATIONAL",
                target_word_count=word_count,
                required_expertise_tag="security",
                review_window_start=start,
                review_window_end=end,
            )

        brief_a = brief(2000, "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z")
        brief_b = brief(1000, "2026-08-04T09:00:00.000Z", "2026-08-04T15:00:00.000Z")
        brief_c = brief(1000, "2026-08-05T09:00:00.000Z", "2026-08-05T15:00:00.000Z")
        brief_d = brief(2000, "2026-08-06T09:00:00.000Z", "2026-08-06T17:00:00.000Z")
        brief_e = brief(2000, "2026-08-07T09:00:00.000Z", "2026-08-07T17:00:00.000Z")
        brief_f = brief(2000, "2026-08-17T09:00:00.000Z", "2026-08-17T17:00:00.000Z")

        assert brief_a["sme_reserved_hours"] == 8
        assert brief_b["sme_reserved_hours"] == 6
        flow.assign_sme(brief_a["id"], expert["id"])
        flow.assign_sme(brief_b["id"], expert["id"])
        flow.approve_brief(brief_b["id"], expert["id"])

        assert flow.read_expert(expert["id"])["committed_hours_total"] == 14

        on_capacity = flow.assign_sme(brief_c["id"], expert["id"])
        assert on_capacity["sme_reserved_hours"] == 6
        assert flow.read_expert(expert["id"])["committed_hours_total"] == 20

        refused = flow.api.assign_sme(
            brief_e["id"],
            f.assign_sme_payload(expert["id"], flow.expert_version(expert["id"])),
            MANAGING_EDITOR,
        )
        validate_error(refused, ERR_EXPERT_CAPACITY_EXCEEDED, 409)
        rejected = flow.read_brief(brief_e["id"])
        assert rejected["state"] == "DRAFT"
        assert rejected["sme_expert_id"] is None

        later_week = flow.assign_sme(brief_f["id"], expert["id"])
        assert later_week["state"] == "SME_ASSIGNED"
        assert flow.read_expert(expert["id"])["committed_hours_total"] == 28
        assert flow.read_brief(brief_d["id"])["state"] == "DRAFT"
        assert_list_response(
            flow.api.list_briefs(MANAGING_EDITOR, {"sme_expert_id": expert["id"]}),
            expected_total_count=4,
            expected_row_count=4,
        )


class TestReviewGateServiceLevels:
    """Gate service levels multiply their factors and round the product once."""

    def test_gate_sla_rounds_the_full_factor_product_half_up_once(self, flow):
        """
        An executive-persona decision piece multiplies both the stage factor and the
        persona factor into every base, so the products land on halves: 34.5 rises to
        35 and 51.75 to 52, which only holds if the rounding happens once on the whole
        product rather than after each factor.

        Design: Corner/calculations/review_gate_sla_rounds_the_full_factor_product_half_up_exactly_once
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="EXECUTIVE")
        flow.submit(chain["item"]["id"])

        gates = flow.gates(chain["item"]["id"])

        assert len(gates) == 3
        assert_gate_dimension_order(gates)
        by_type = {gate["gate_type"]: gate for gate in gates}
        assert_gate(
            by_type["SME"], state="PENDING", sla_hours=35,
            due_at="2026-08-04T19:00:00.000Z", opened_at=SETUP_CLOCK,
            sla_breached=False,
        )
        assert_gate(
            by_type["BRAND"], state="PENDING", sla_hours=35,
            due_at="2026-08-04T19:00:00.000Z", opened_at=SETUP_CLOCK,
            sla_breached=False,
        )
        assert_gate(
            by_type["ACCESSIBILITY"], state="PENDING", sla_hours=52,
            due_at="2026-08-05T12:00:00.000Z", opened_at=SETUP_CLOCK,
            sla_breached=False,
        )

    def test_legal_gate_sla_adds_the_declared_hours_per_unsubstantiated_claim(
        self, flow
    ):
        """
        A regulated decision piece carrying two unsubstantiated regulated claims and one
        performance claim opens a legal gate whose allowance is the multiplied base plus
        twelve hours for each regulated claim only, while its three siblings keep the
        allowances they would have had with no claims at all.

        Design: Corner/calculations/legal_gate_sla_adds_twelve_hours_for_each_unsubstantiated_regulated_claim
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(
            funnel_stage="DECISION", persona="IT_BUYER", requires_regulated_review=True
        )
        item_id = chain["item"]["id"]
        assert chain["brief"]["effort_points"] == 21

        claim_one = flow.create_claim(
            item_id, claim_type="REGULATED",
            claim_text="The platform meets the regulated retention standard for audit logs.",
        )
        claim_two = flow.create_claim(
            item_id, claim_type="REGULATED",
            claim_text="Encryption at rest satisfies the regulated key rotation schedule.",
        )
        claim_three = flow.create_claim(item_id, claim_type="PERFORMANCE")
        flow.submit(item_id)

        gates = flow.gates(item_id)
        assert len(gates) == 4
        assert_gate_dimension_order(gates)
        by_type = {gate["gate_type"]: gate for gate in gates}
        assert_gate(
            by_type["LEGAL"], state="PENDING", sla_hours=84,
            due_at="2026-08-06T20:00:00.000Z", opened_at=SETUP_CLOCK,
            sla_breached=False,
        )
        assert_gate(
            by_type["SME"], sla_hours=30, due_at="2026-08-04T14:00:00.000Z"
        )
        assert_gate(
            by_type["BRAND"], sla_hours=30, due_at="2026-08-04T14:00:00.000Z"
        )
        assert_gate(
            by_type["ACCESSIBILITY"], sla_hours=45, due_at="2026-08-05T05:00:00.000Z"
        )
        for claim in (claim_one, claim_two, claim_three):
            assert flow.read_claim(claim["id"])["substantiation_state"] == "DRAFT"


class TestClaimScoringSelection:
    """A claim's scoring variant and required score are two independent lookups."""

    def test_scoring_variant_and_required_score_are_bound_at_creation(self, flow):
        """
        Three claim types on one regulated piece: performance and comparison share the
        standard variant but carry different required scores, while the regulated claim
        binds the strict variant at the highest score, so neither field can be inferred
        from the other.

        Design: Corner/calculations/claim_scoring_variant_and_required_score_are_selected_from_claim_type_at_creation
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(
            funnel_stage="DECISION", persona="IT_BUYER", requires_regulated_review=True
        )
        item_id = chain["item"]["id"]

        performance = validate_success(
            flow.api.create_claim(
                item_id,
                f.claim_payload(
                    claim_text="Median deployment finishes 30 percent faster than the previous release.",
                    claim_type="PERFORMANCE",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        comparison = validate_success(
            flow.api.create_claim(
                item_id,
                f.claim_payload(
                    claim_text="Our detection coverage exceeds the two leading competing platforms.",
                    claim_type="COMPARISON",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        regulated = validate_success(
            flow.api.create_claim(
                item_id,
                f.claim_payload(
                    claim_text="The platform meets the regional data residency mandate for regulated workloads.",
                    claim_type="REGULATED",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert performance["scoring_variant"] == "STANDARD"
        assert_two_decimal_value(performance["required_score"], 2.00)
        assert_two_decimal_value(performance["evidence_score"], 0.00)
        assert comparison["scoring_variant"] == "STANDARD"
        assert_two_decimal_value(comparison["required_score"], 3.00)
        assert regulated["scoring_variant"] == "STRICT_REGULATED"
        assert_two_decimal_value(regulated["required_score"], 4.00)
        assert regulated["evidence_valid_until"] is None

        assert_list_response(
            flow.api.list_item_claims(item_id, MANAGING_EDITOR),
            expected_total_count=3,
            expected_row_count=3,
        )
        assert_list_response(
            flow.api.list_item_claims(item_id, MANAGING_EDITOR, {"claim_type": "REGULATED"}),
            expected_total_count=1,
            expected_row_count=1,
        )


class TestDecayWindowMembership:
    """A measurement period counts toward a window only when it falls entirely inside it."""

    def test_decay_windows_admit_only_fully_contained_periods(self, flow):
        """
        A period running from 30 August to 6 September straddles both the end of the
        baseline window and the start of the trailing window, so it belongs to neither:
        1600 against 641 reads 59.94, where crediting the straddler to both would read
        45.67, while the running totals still count every period recorded.

        Design: Corner/calculations/decay_windows_admit_only_fully_contained_snapshots
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.ready_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]

        flow.set_clock("2026-08-05T09:00:00.000Z")
        published = validate_success(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at="2026-08-05T09:00:00.000Z",
                    channels=["OWNED"],
                    meta_description=(
                        "A practical buyer guide to zero trust platform pricing for "
                        "security and procurement teams."
                    ),
                    url_slug="zero-trust-platform-pricing-decay",
                    tags=["security", "pricing"],
                ),
                MANAGING_EDITOR_TWO,
            )
        )
        assert published["published_at"] == "2026-08-05T09:00:00.000Z"

        flow.set_clock("2026-09-30T09:00:00.000Z")
        periods = [
            ("2026-08-05T09:00:00.000Z", "2026-08-12T09:00:00.000Z", 1000, 10, "FIRST"),
            ("2026-08-12T09:00:00.000Z", "2026-08-19T09:00:00.000Z", 600, 6, "MIDDLE"),
            ("2026-08-30T09:00:00.000Z", "2026-09-06T09:00:00.000Z", 500, 5, "MIDDLE"),
            ("2026-09-10T09:00:00.000Z", "2026-09-17T09:00:00.000Z", 300, 3, "MIDDLE"),
            ("2026-09-17T09:00:00.000Z", "2026-09-24T09:00:00.000Z", 341, 4, "LAST"),
        ]
        for start, end, sessions, conversions, touch in periods:
            validate_success(
                flow.api.create_performance_snapshot(
                    item_id,
                    f.performance_snapshot_payload(
                        start, end,
                        engaged_sessions=sessions,
                        conversions=conversions,
                        influenced_opportunity_amount_cents=0,
                        touch_position=touch,
                    ),
                    ANALYTICS_SERVICE,
                ),
                201,
            )

        audited = flow.audit(item_id, audit_type="DECAY")

        assert_two_decimal_value(audited["decay_pct"], 59.94)
        assert audited["refresh_required"] is True
        assert audited["last_audit_verdict"] == "REFRESH"
        assert audited["workflow_state"] == "NEEDS_REFRESH"
        assert audited["engaged_sessions_total"] == 2741
        assert audited["conversions_total"] == 28
        assert audited["published_at"] == "2026-08-05T09:00:00.000Z"
        assert_list_response(
            flow.api.list_performance_snapshots(item_id, MANAGING_EDITOR),
            expected_total_count=5,
            expected_row_count=5,
        )
        assert_list_response(
            flow.api.list_performance_snapshots(
                item_id, MANAGING_EDITOR, {"touch_position": "LAST"}
            ),
            expected_total_count=1,
            expected_row_count=1,
        )


class TestAssetLicenceBoundaries:
    """Both licence comparisons are inclusive, at the warning edge and at expiry."""

    def test_licence_status_uses_the_warning_window_and_an_inclusive_expiry(self, flow):
        """
        Against a clock of 3 August, a licence ending exactly thirty days out is already
        in its warning window, one ending thirty-one days out is untroubled, and one
        ending exactly at the clock has already lapsed, so neither comparison is strict.

        Design: Corner/calculations/asset_license_status_boundaries_use_the_thirty_day_warning_and_an_inclusive_expiry
        """
        flow.set_clock("2026-08-03T00:00:00.000Z")

        def asset(name: str, license_end: str):
            return validate_success(
                flow.api.create_asset(
                    f.asset_payload(
                        name=name,
                        asset_type="STOCK",
                        license_start="2026-07-01T00:00:00.000Z",
                        license_end=license_end,
                        licensed_channels=["OWNED"],
                        max_licensed_uses=4,
                    ),
                    MANAGING_EDITOR,
                ),
                201,
            )

        warning = asset("Warning-window stock photo", "2026-09-02T00:00:00.000Z")
        comfortable = asset("Comfortable stock photo", "2026-09-03T00:00:00.000Z")
        lapsed = asset("Lapsed stock photo", "2026-08-03T00:00:00.000Z")

        assert_asset_rights(
            warning, status="EXPIRING", active_use_count=0, remaining_licensed_uses=4
        )
        assert_asset_rights(
            comfortable, status="LICENSED", remaining_licensed_uses=4
        )
        assert_asset_rights(lapsed, status="EXPIRED", active_use_count=0)

        rows = assert_list_response(
            flow.api.list_assets(MANAGING_EDITOR, {"status": "EXPIRING"}),
            expected_total_count=1,
            expected_row_count=1,
        )
        assert rows[0]["id"] == warning["id"]
        assert comfortable["id"] != lapsed["id"]


class TestPostureRestrictThreshold:
    """The restrict tier arrives exactly at the second breached gate, never earlier."""

    def test_posture_turns_restricted_at_the_second_breached_gate(self, flow):
        """
        Staggered deadlines let one sweep breach a single gate and a later sweep breach
        the second: at one breach the posture is still open and no campaign is
        restricted, and only the second breach crosses the threshold, while the gate
        approved at fan-out never breaches and an already-flagged gate is not recounted.

        Design: Corner/calculations/campaign_posture_turns_restricted_exactly_at_the_second_breached_gate
        """
        flow.set_clock(SETUP_CLOCK)
        chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
        item_id = chain["item"]["id"]
        campaign_id = chain["campaign"]["id"]
        flow.submit(item_id)
        brand_gate = flow.gate_of(item_id, "BRAND")
        flow.decide_gate(brand_gate["id"], "APPROVED", BRAND_REVIEWER)

        flow.set_clock("2026-08-04T15:00:00.000Z")
        first_sweep = flow.sweep()
        assert_sweep_tally(first_sweep, gates_breached=1)
        after_first = flow.read_campaign(campaign_id)
        assert_posture(after_first, "OPEN")
        assert_campaign_counters(after_first, breached_gate_count=1)
        assert_gate(flow.gate_of(item_id, "SME"), state="PENDING", sla_breached=True)
        assert_gate(
            flow.gate_of(item_id, "ACCESSIBILITY"), state="PENDING", sla_breached=False
        )

        flow.set_clock("2026-08-05T06:00:00.000Z")
        second_sweep = flow.sweep()
        assert_sweep_tally(second_sweep, gates_breached=1, campaigns_restricted=1)
        after_second = flow.read_campaign(campaign_id)
        assert_posture(after_second, "RESTRICTED")
        assert_campaign_counters(after_second, breached_gate_count=2)
        assert_gate(
            flow.gate_of(item_id, "ACCESSIBILITY"), state="PENDING", sla_breached=True
        )
        assert_gate(
            flow.gate_of(item_id, "BRAND"), state="APPROVED", sla_breached=False
        )
