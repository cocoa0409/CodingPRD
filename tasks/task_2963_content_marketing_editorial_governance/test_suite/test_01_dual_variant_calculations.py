"""
Two named calculation variants over one input set.

Both cases here pit two declared formulas against a single body of data: the
claim substantiation score under ``STANDARD`` versus ``STRICT_REGULATED``
admissibility and recency, and the pipeline figures under last-touch versus
assisted-fractional attribution. In each case the same rows must produce two
different, separately specified answers.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_EVIDENCE_INSUFFICIENT
from test_helpers.assertions import (
    assert_list_response,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    ANALYTICS_SERVICE,
    LEGAL_REVIEWER_ONE,
    MANAGING_EDITOR,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
MEASUREMENT_CLOCK = "2026-09-14T00:00:00.000Z"

# One dossier, filed identically against both claims: a fresh third-party
# test, a fresh internal study, and a 945-day-old regulatory filing.
SHARED_EVIDENCE = [
    {
        "source_type": "THIRD_PARTY_TEST",
        "citation": "Northwind Labs comparative benchmark, report NL-2026-118",
        "collected_at": "2026-06-01T00:00:00.000Z",
        "valid_until": "2027-06-01T00:00:00.000Z",
    },
    {
        "source_type": "INTERNAL_STUDY",
        "citation": "Internal response-time study, cohort 2026H1",
        "collected_at": "2026-07-01T00:00:00.000Z",
        "valid_until": "2027-07-01T00:00:00.000Z",
    },
    {
        "source_type": "REGULATORY_FILING",
        "citation": "Filing 2024-DR-0091, residency schedule B",
        "collected_at": "2024-01-01T00:00:00.000Z",
        "valid_until": "2027-01-01T00:00:00.000Z",
    },
]


def _item_with_two_claims(flow):
    """A DRAFT item on a regulated brief, carrying one claim of each variant."""
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    brief, expert_id = flow.approved_brief(
        campaign["id"],
        funnel_stage="DECISION",
        requires_regulated_review=True,
        expertise_tag="security",
    )
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    performance = flow.create_claim(item["id"], claim_type="PERFORMANCE")
    regulated = flow.create_claim(item["id"], claim_type="REGULATED")
    for claim_id in (performance["id"], regulated["id"]):
        for row in SHARED_EVIDENCE:
            flow.file_evidence(claim_id, **row)
    return {
        "campaign": campaign,
        "item": item,
        "performance": performance,
        "regulated": regulated,
        "expert_id": expert_id,
    }


class TestClaimScoringVariants:
    """The scoring variant selected from the claim type decides the score."""

    def test_standard_variant_admits_all_four_source_types_and_substantiates(
        self, flow
    ):
        """
        Under ``STANDARD`` every source type is admissible and a row older than
        730 days keeps half its weight, so the dossier scores 4.25 against a
        required score of 2.00 and the claim substantiates.

        Design: Difficulty/dual_variant_calc/claim_evidence_score_strict_regulated_diverges_from_standard
        """
        chain = _item_with_two_claims(flow)
        claim_id = chain["performance"]["id"]

        decided = validate_success(
            flow.api.decide_claim(claim_id, "SUBSTANTIATED", LEGAL_REVIEWER_ONE)
        )

        assert decided["scoring_variant"] == "STANDARD"
        assert_two_decimal_value(decided["required_score"], 2.00)
        assert_two_decimal_value(decided["evidence_score"], 4.25)
        assert decided["substantiation_state"] == "SUBSTANTIATED"
        assert decided["evidence_valid_until"] == "2027-01-01T00:00:00.000Z"
        assert decided["decided_by_user_id"] == LEGAL_REVIEWER_ONE["X-User-ID"]
        assert decided["decided_at"] == SETUP_CLOCK

    def test_strict_regulated_variant_discards_and_zeroes_the_same_rows(self, flow):
        """
        Under ``STRICT_REGULATED`` only third-party tests and regulatory filings
        are admissible and a row older than 365 days contributes nothing, so the
        byte-identical dossier scores 2.00 against a required score of 4.00 and
        the decision is refused as insufficient.

        Design: Difficulty/dual_variant_calc/claim_evidence_score_strict_regulated_diverges_from_standard
        """
        chain = _item_with_two_claims(flow)
        regulated_id = chain["regulated"]["id"]
        performance_id = chain["performance"]["id"]

        response = flow.api.decide_claim(
            regulated_id, "SUBSTANTIATED", LEGAL_REVIEWER_ONE
        )

        validate_error(response, ERR_EVIDENCE_INSUFFICIENT, 422)
        regulated = flow.read_claim(regulated_id)
        assert regulated["scoring_variant"] == "STRICT_REGULATED"
        assert_two_decimal_value(regulated["required_score"], 4.00)
        assert_two_decimal_value(regulated["evidence_score"], 2.00)
        assert regulated["substantiation_state"] == "EVIDENCE_PENDING"
        assert regulated["decided_at"] is None
        assert regulated["evidence_valid_until"] is None

        # The two dossiers are the same rows, so the whole 2.25 gap between
        # 4.25 and 2.00 is attributable to the scoring variant alone.
        strict_rows = assert_list_response(
            flow.api.list_claim_evidence(regulated_id, MANAGING_EDITOR),
            expected_total_count=3,
        )
        standard_rows = assert_list_response(
            flow.api.list_claim_evidence(performance_id, MANAGING_EDITOR),
            expected_total_count=3,
        )
        shape = [(row["source_type"], row["collected_at"]) for row in strict_rows]
        assert shape == [
            (row["source_type"], row["collected_at"]) for row in standard_rows
        ]
        standard = flow.read_claim(performance_id)
        assert_two_decimal_value(standard["evidence_score"], 4.25)


def _item_with_measurements(flow, periods):
    """A DRAFT item carrying the supplied measurement periods."""
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    brief, _expert_id = flow.approved_brief(campaign["id"], funnel_stage="DECISION")
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    flow.set_clock(MEASUREMENT_CLOCK)
    for period in periods[:-1]:
        flow.snapshot(item["id"], **period)
    return item


ATTRIBUTION_PERIODS = [
    {
        "period_start": "2026-08-03T00:00:00.000Z",
        "period_end": "2026-08-10T00:00:00.000Z",
        "engaged_sessions": 400,
        "conversions": 10,
        "influenced_opportunity_amount_cents": 1000003,
        "touch_position": "FIRST",
    },
    {
        "period_start": "2026-08-10T00:00:00.000Z",
        "period_end": "2026-08-17T00:00:00.000Z",
        "engaged_sessions": 300,
        "conversions": 8,
        "influenced_opportunity_amount_cents": 987657,
        "touch_position": "MIDDLE",
    },
    {
        "period_start": "2026-08-17T00:00:00.000Z",
        "period_end": "2026-08-24T00:00:00.000Z",
        "engaged_sessions": 250,
        "conversions": 6,
        "influenced_opportunity_amount_cents": 555557,
        "touch_position": "LAST",
    },
    {
        "period_start": "2026-08-24T00:00:00.000Z",
        "period_end": "2026-08-31T00:00:00.000Z",
        "engaged_sessions": 250,
        "conversions": 4,
        "influenced_opportunity_amount_cents": 2400331,
        "touch_position": "LAST",
    },
]


class TestPipelineAttributionVariants:
    """Last-touch and assisted-fractional pipeline read the same periods."""

    def test_last_touch_credits_only_the_last_position_periods(self, flow):
        """
        The last-touch figure is the plain sum of the influenced amounts on the
        periods whose touch position is ``LAST``, so the two ``FIRST`` and
        ``MIDDLE`` periods contribute nothing to it.

        Design: Difficulty/dual_variant_calc/pipeline_attribution_last_touch_diverges_from_assisted_fractional
        """
        item = _item_with_measurements(flow, ATTRIBUTION_PERIODS)

        created = validate_success(
            flow.api.create_performance_snapshot(
                item["id"],
                ATTRIBUTION_PERIODS[-1],
                ANALYTICS_SERVICE,
            ),
            201,
        )
        assert created["touch_position"] == "LAST"

        refreshed = flow.read_item(item["id"])
        # 555557 + 2400331, with the first and middle periods excluded entirely.
        assert refreshed["last_touch_pipeline_cents"] == 2955888
        assert refreshed["engaged_sessions_total"] == 1200
        assert refreshed["conversions_total"] == 28
        assert refreshed["workflow_state"] == "DRAFT"
        assert_list_response(
            flow.api.list_performance_snapshots(item["id"], MANAGING_EDITOR),
            expected_total_count=4,
        )

    def test_assisted_fractional_credits_every_period_its_touch_weight(self, flow):
        """
        The assisted figure weights each period by its touch position — 0.40 for
        first, 0.20 for middle, 0.40 for last — so it lands on 1779887 against a
        last-touch reading of 2955888 on the very same four periods.

        Design: Difficulty/dual_variant_calc/pipeline_attribution_last_touch_diverges_from_assisted_fractional
        """
        item = _item_with_measurements(flow, ATTRIBUTION_PERIODS)
        flow.snapshot(item["id"], **ATTRIBUTION_PERIODS[-1])

        refreshed = flow.read_item(item["id"])
        # 400001 + 197531 + 222223 + 960132
        assert refreshed["assisted_pipeline_cents"] == 1779887
        assert refreshed["last_touch_pipeline_cents"] == 2955888
        assert (
            refreshed["last_touch_pipeline_cents"]
            != refreshed["assisted_pipeline_cents"]
        )
        assert (
            refreshed["last_touch_pipeline_cents"]
            - refreshed["assisted_pipeline_cents"]
        ) == 1176001
