"""Requests that break two rules at once, and which rule is allowed to answer.

Each pair is proved twice: once with both rules broken, and once with only the
lower-priority rule broken so that it is visibly still live.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DETERMINATION_NOT_APPROVED,
    ERR_FEE_REQUEST_EXCEEDS_CEILING,
    ERR_INVALID_STATE_TRANSITION,
    ERR_OPEN_SETTLEMENT_EXISTS,
    ERR_PEER_REVIEW_REQUIRED,
    ERR_PLACEMENT_OVERLAP,
)
from test_helpers.assertions import assert_cents, assert_margin, assert_status
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_SUBMITTED,
    DEFAULT_CLOCK,
    DETERMINATION_REVOKED,
    METHOD_MODELED,
    PLACEMENT_PLANNED,
    REQUIRED_CHANNEL_LABEL,
    ROUTE_DERMAL,
    SETTLEMENT_PROPOSED,
    VIOLATION_INADEQUATE_WARNING_CONTENT,
)
from test_helpers.fixtures import (
    add_placement,
    build_warned_product,
    escalate_notice_to_negotiation,
    make_assessment,
    make_bpa,
    make_notice,
    make_product,
    make_product_with_component,
    propose_settlement,
    set_clock,
    submit_assessment,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    REGULATORY_COUNSEL,
    TOXICOLOGY_REVIEWER,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def draft_assessment(api):
    """A DRAFT assessment that has never been peer reviewed on a submittable product."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    base = make_product_with_component(
        api,
        chemical["id"],
        sku="SKU-PC1",
        product_overrides={"product_name": "Dog Bowl", "annual_units": 50000},
    )
    assessment = make_assessment(
        api, base["product"]["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    base["chemical"] = chemical
    base["assessment"] = assessment
    return base


@pytest.fixture
def revoked_determination_with_planned_placement(api):
    """A REVOKED determination still holding one PLANNED LABEL window [2026-06-01, 2026-07-01]."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-PC2",
        route=ROUTE_DERMAL,
        place=False,
        product_overrides={"product_name": "Tool Grip", "annual_units": 50000},
    )
    placement = add_placement(
        api,
        bundle["determination"]["id"],
        REQUIRED_CHANNEL_LABEL,
        "2026-06-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
        placement_detail="Interim sticker",
    )
    determination = get_success_data(
        api.determination_transition(
            bundle["determination"]["id"],
            f.action_payload("REVOKE"),
            REGULATORY_COUNSEL,
        )
    )
    bundle["chemical"] = chemical
    bundle["placement"] = placement
    bundle["determination"] = determination
    return bundle


@pytest.fixture
def two_negotiating_notices(api):
    """Two notices on one product, both in SETTLEMENT_NEGOTIATION, one already settled at 400000."""
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-PC3", product_name="Door Sweep", annual_units=500000
    )
    first = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    second = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Delta Watch Alliance",
        alleged_violation_type=VIOLATION_INADEQUATE_WARNING_CONTENT,
    )
    first = escalate_notice_to_negotiation(api, first["id"])
    second = escalate_notice_to_negotiation(api, second["id"])
    set_clock(api, DEFAULT_CLOCK)
    settlement = propose_settlement(
        api, first["id"], 400000, reformulation_commitment=False
    )
    return {
        "chemical": chemical,
        "product": product,
        "first": first,
        "second": second,
        "settlement": settlement,
    }


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _finalize(api, assessment_id):
    return api.assessment_transition(
        assessment_id, f.action_payload("FINALIZE"), TOXICOLOGY_REVIEWER
    )


def _create_placement(api, determination_id, effective_from, effective_to, detail):
    return api.create_placement(
        determination_id,
        f.placement_payload(
            REQUIRED_CHANNEL_LABEL,
            effective_from,
            effective_to,
            placement_detail=detail,
        ),
        LABELING_SPECIALIST,
    )


def _create_settlement(api, notice_id, fees):
    version = api.notice_version(notice_id, REGULATORY_COUNSEL)
    return api.create_settlement(
        notice_id,
        f.settlement_payload(fees, version, reformulation_commitment=False),
        REGULATORY_COUNSEL,
    )


# ─────────────────────────────────────────────────────────────────────────────
# State legality outranks the peer-review gate
# ─────────────────────────────────────────────────────────────────────────────


class TestFinalizeFromDraft:
    def test_finalizing_a_draft_reports_the_illegal_transition(
        self, api, draft_assessment
    ):
        """Both rules are broken at once and only the state-legality rule may answer.

        PRD: "Finalization requested on an assessment that is currently `DRAFT` is not a legal transition at all, so the state-legality rule fires first and the response is `ERR_INVALID_STATE_TRANSITION` — never `ERR_PEER_REVIEW_REQUIRED` — regardless of whether a reviewer was ever recorded."

        Design: Difficulty/priority_pair_validation_conflict/finalize_from_draft_reports_illegal_transition_over_missing_peer_review
        """
        assessment = draft_assessment["assessment"]
        assert assessment["reviewed_by_user_id"] is None
        error = validate_error(
            _finalize(api, assessment["id"]), ERR_INVALID_STATE_TRANSITION
        )
        assert error["error_id"] != ERR_PEER_REVIEW_REQUIRED

    def test_the_refused_finalization_leaves_the_row_alone(
        self, api, draft_assessment
    ):
        """No side effect survives the refusal: the assessment is still an unreviewed DRAFT.

        PRD: "A newly created assessment has `status` `DRAFT`, `submitted_by_user_id`, `reviewed_by_user_id` and `finalized_at` all null, `rejection_count` 0 and `review_note` null; its numbers are computed immediately from the product's active components."

        Design: Difficulty/priority_pair_validation_conflict/finalize_from_draft_reports_illegal_transition_over_missing_peer_review
        """
        assessment = draft_assessment["assessment"]
        validate_error(
            _finalize(api, assessment["id"]), ERR_INVALID_STATE_TRANSITION
        )
        unchanged = _read_assessment(api, assessment["id"])
        assert_status(unchanged, ASSESSMENT_DRAFT)
        assert unchanged["reviewed_by_user_id"] is None
        assert unchanged["finalized_at"] is None

    def test_finalizing_a_submitted_row_reaches_the_peer_review_gate(
        self, api, draft_assessment
    ):
        """From SUBMITTED the edge is legal, so the peer-review rule is the one that decides.

        PRD: "From `SUBMITTED → FINAL` it additionally needs `reviewed_by_user_id` to be non-null — that is, this assessment must have been peer-reviewed on an earlier turn of the cycle — and when it is null the request is refused with `ERR_PEER_REVIEW_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/finalize_from_draft_reports_illegal_transition_over_missing_peer_review
        """
        assessment = draft_assessment["assessment"]
        submit_assessment(api, assessment["id"])
        validate_error(_finalize(api, assessment["id"]), ERR_PEER_REVIEW_REQUIRED)

        unchanged = _read_assessment(api, assessment["id"])
        assert_status(unchanged, ASSESSMENT_SUBMITTED)
        assert unchanged["finalized_at"] is None


# ─────────────────────────────────────────────────────────────────────────────
# The temporal overlap rule outranks the approved-parent rule
# ─────────────────────────────────────────────────────────────────────────────


class TestPlacementOverlapPrecedence:
    def test_a_touching_window_reports_the_overlap_not_the_parent_state(
        self, api, revoked_determination_with_planned_placement
    ):
        """A new window starting exactly where the PLANNED one ends collides, and that answers first.

        PRD: "The determination must be in status `APPROVED`, otherwise the create is refused with `ERR_DETERMINATION_NOT_APPROVED` — but recall from Section 2.8 that the closed-window overlap check is evaluated first, so a request that both overlaps and targets a non-approved determination reports `ERR_PLACEMENT_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/placement_overlap_reported_before_determination_not_approved
        """
        bundle = revoked_determination_with_planned_placement
        assert_status(bundle["determination"], DETERMINATION_REVOKED)
        assert_status(bundle["placement"], PLACEMENT_PLANNED)

        error = validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Replacement sticker",
            ),
            ERR_PLACEMENT_OVERLAP,
        )
        assert error["error_id"] != ERR_DETERMINATION_NOT_APPROVED

    def test_a_disjoint_window_falls_through_to_the_parent_state_rule(
        self, api, revoked_determination_with_planned_placement
    ):
        """With the overlap rule satisfied the revoked parent is what refuses the create.

        PRD: "**Layer 7 — referential business rules.** In order: (1) an exposure assessment opened for a chemical that is not currently listed → `ERR_CHEMICAL_NOT_LISTED`; (2) a placement created against a determination that is not approved → `ERR_DETERMINATION_NOT_APPROVED`; (3) a settlement created against a notice that is not in settlement negotiation → `ERR_NOTICE_NOT_NEGOTIABLE`; (4) a material parent that would create a cycle or exceed the depth ceiling → `ERR_MATERIAL_CYCLE`, guarding both material creation and material update; (5) a reformulation project whose named link is inconsistent → `ERR_REFORMULATION_LINK_MISMATCH`; (6) a determination whose basis assessment is not final or belongs to another product → `ERR_BASIS_ASSESSMENT_NOT_FINAL`."

        Design: Difficulty/priority_pair_validation_conflict/placement_overlap_reported_before_determination_not_approved
        """
        bundle = revoked_determination_with_planned_placement
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-09-01T00:00:00Z",
                "2026-10-01T00:00:00Z",
                "Far future sticker",
            ),
            ERR_DETERMINATION_NOT_APPROVED,
        )

    def test_neither_refusal_creates_a_placement_row(
        self, api, revoked_determination_with_planned_placement
    ):
        """The one PLANNED window is still the only placement, and it covers nothing.

        PRD: "A newly created placement has `status` `PLANNED`, `implemented_by_user_id` null and `remediation_count` 0, and its creation recomputes the determination's `covered_channel_count` and the product's `compliance_posture`."

        Design: Difficulty/priority_pair_validation_conflict/placement_overlap_reported_before_determination_not_approved
        """
        bundle = revoked_determination_with_planned_placement
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Replacement sticker",
            ),
            ERR_PLACEMENT_OVERLAP,
        )
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-09-01T00:00:00Z",
                "2026-10-01T00:00:00Z",
                "Far future sticker",
            ),
            ERR_DETERMINATION_NOT_APPROVED,
        )

        rows, _ = validate_paginated(
            api.list_placements(
                COMPLIANCE_ANALYST,
                {"determination_id": bundle["determination"]["id"]},
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == bundle["placement"]["id"]
        determination = get_success_data(
            api.get_determination(bundle["determination"]["id"], COMPLIANCE_ANALYST)
        )
        assert determination["covered_channel_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# The open-settlement rule outranks the fee ceiling
# ─────────────────────────────────────────────────────────────────────────────


class TestSettlementConflictPrecedence:
    def test_a_second_proposal_reports_the_open_settlement_not_the_fee_ceiling(
        self, api, two_negotiating_notices
    ):
        """Fees of 6,000,000 cents are over the ceiling, but the live settlement answers first.

        PRD: "Layer 9's fee-ceiling rule is the lower half of a second deliberate conflict pair: a settlement create that both names a notice which already has a live settlement **and** requests fees above the ceiling reports `ERR_OPEN_SETTLEMENT_EXISTS`, because the open-settlement rule sits in layer 8."

        Design: Difficulty/priority_pair_validation_conflict/open_settlement_conflict_beats_absolute_fee_ceiling
        """
        bundle = two_negotiating_notices
        assert_status(bundle["settlement"], SETTLEMENT_PROPOSED)
        assert_margin(bundle["settlement"]["mitigation_factor"], 1.0)
        assert_cents(
            bundle["settlement"]["adjusted_penalty_cents"],
            2000000,
            "adjusted_penalty_cents",
        )

        error = validate_error(
            _create_settlement(api, bundle["first"]["id"], 6000000),
            ERR_OPEN_SETTLEMENT_EXISTS,
        )
        assert error["error_id"] != ERR_FEE_REQUEST_EXCEEDS_CEILING

    def test_the_same_request_on_a_clean_notice_hits_the_fee_ceiling(
        self, api, two_negotiating_notices
    ):
        """With no live settlement in the way the fiscal rule is visibly still live.

        PRD: "`requested_attorney_fees_cents` may not exceed the absolute request ceiling of five million cents (fifty thousand dollars), which is refused with `ERR_FEE_REQUEST_EXCEEDS_CEILING`."

        Design: Difficulty/priority_pair_validation_conflict/open_settlement_conflict_beats_absolute_fee_ceiling
        """
        bundle = two_negotiating_notices
        validate_error(
            _create_settlement(api, bundle["second"]["id"], 6000000),
            ERR_FEE_REQUEST_EXCEEDS_CEILING,
            422,
        )

    def test_neither_refusal_adds_a_settlement_row(self, api, two_negotiating_notices):
        """One PROPOSED settlement before, one PROPOSED settlement after.

        PRD: "The notice must be in status `SETTLEMENT_NEGOTIATION`, otherwise the create is refused with `ERR_NOTICE_NOT_NEGOTIABLE`, and the notice must not already hold a settlement in status `PROPOSED`, `COUNTERED` or `EXECUTED`, otherwise it is refused with `ERR_OPEN_SETTLEMENT_EXISTS`."

        Design: Difficulty/priority_pair_validation_conflict/open_settlement_conflict_beats_absolute_fee_ceiling
        """
        bundle = two_negotiating_notices
        validate_error(
            _create_settlement(api, bundle["first"]["id"], 6000000),
            ERR_OPEN_SETTLEMENT_EXISTS,
        )
        validate_error(
            _create_settlement(api, bundle["second"]["id"], 6000000),
            ERR_FEE_REQUEST_EXCEEDS_CEILING,
            422,
        )

        rows, _ = validate_paginated(api.list_settlements(REGULATORY_COUNSEL))
        assert len(rows) == 1
        assert rows[0]["id"] == bundle["settlement"]["id"]
        assert rows[0]["status"] == SETTLEMENT_PROPOSED
