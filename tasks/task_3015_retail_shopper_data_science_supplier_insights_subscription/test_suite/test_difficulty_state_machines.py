"""Non-linear state machines: the segment reject-and-resubmit revert loop and
the incrementality study's revise cycle back into RUNNING."""

from test_helpers import (
    account_with_contract,
    create_approved_segment,
    create_segment,
    create_study,
    get_success_data,
    ingest_category_households,
    ingest_households,
    read_study,
    set_clock,
    start_study,
    submit_segment,
)
from test_helpers.test_users import TEST_USERS
MATCH_PANEL = [
    {
        "household_ref": "T1",
        "category_codes": ["SNACKS"],
        "recency_days": 5,
        "frequency_12m": 10,
        "monetary_12m_cents": 24000,
        "exposed_brands": ["ACME"],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 22000, "campaign_spend_cents": 24000}],
    },
    {
        "household_ref": "T2",
        "category_codes": ["SNACKS"],
        "recency_days": 5,
        "frequency_12m": 10,
        "monetary_12m_cents": 24000,
        "exposed_brands": ["ACME"],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 22000, "campaign_spend_cents": 24000}],
    },
    {
        "household_ref": "C1",
        "category_codes": ["SNACKS"],
        "recency_days": 6,
        "frequency_12m": 10,
        "monetary_12m_cents": 23000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
    {
        "household_ref": "C2",
        "category_codes": ["SNACKS"],
        "recency_days": 4,
        "frequency_12m": 12,
        "monetary_12m_cents": 23000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
    {
        "household_ref": "C3",
        "category_codes": ["SNACKS"],
        "recency_days": 6,
        "frequency_12m": 8,
        "monetary_12m_cents": 25000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
]

SCIENTIST = TEST_USERS["insights_scientist_headers"]
STEWARD = TEST_USERS["data_steward_headers"]


def _segment_world(api):
    """Contract with SNACKS scope and 25 SNACKS households; returns world."""
    world = account_with_contract(api, name="Delta Dairy", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 25, "s")
    return world


def test_segment_reject_resubmit_approve_revert_cycle(api):
    """DRAFT -> PENDING_APPROVAL -> REJECTED -> PENDING_APPROVAL -> APPROVED traverses the revert edge.

    PRD: "Submission is valid from `DRAFT` and from `REJECTED` alike — a rejected segment may be revised and resubmitted — but from no other state (else `ERR_SEGMENT_NOT_SUBMITTABLE`)."
    PRD: "The steward may instead reject a `PENDING_APPROVAL` segment, moving it to `REJECTED`"
    Design: Difficulty/non_linear_state_machine/segment_rejection_revert_cycle
    """
    world = _segment_world(api)
    segment = create_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="Snackers")
    first = submit_segment(api, segment["id"], world["analyst_headers"])
    assert first["status"] == "PENDING_APPROVAL"
    rejected = get_success_data(api.reject_segment(segment["id"], STEWARD))
    assert rejected["status"] == "REJECTED"
    resubmitted = submit_segment(api, segment["id"], world["analyst_headers"])
    assert resubmitted["status"] == "PENDING_APPROVAL"
    approved = get_success_data(api.approve_segment(segment["id"], STEWARD))
    assert approved["status"] == "APPROVED"


def test_segment_size_recomputed_across_the_revert_cycle(api):
    """The revert loop still lands on APPROVED with the live size of 25.

    PRD: "The segment's `size` is the count of panel households that satisfy every supplied criterion, computed against the full panel at creation and recomputed at every submission."
    PRD: "Approval moves the segment to `APPROVED`."
    Design: Difficulty/non_linear_state_machine/segment_rejection_revert_cycle
    """
    world = _segment_world(api)
    segment = create_segment(api, world["contract"]["id"], world["analyst_headers"])
    submit_segment(api, segment["id"], world["analyst_headers"])
    get_success_data(api.reject_segment(segment["id"], STEWARD))
    resubmitted = submit_segment(api, segment["id"], world["analyst_headers"])
    assert resubmitted["size"] == 25
    approved = get_success_data(api.approve_segment(segment["id"], STEWARD))
    assert approved["status"] == "APPROVED"
    assert approved["size"] == 25


def _study_in_review(api):
    """Started study, clock past window_end, pushed ANALYSIS -> IN_REVIEW."""
    ingest_households(api, MATCH_PANEL)
    study = create_study(api)
    start_study(api, study["id"])
    set_clock(api, "2026-09-10T00:00:00Z")
    assert read_study(api, study["id"])["status"] == "ANALYSIS"
    get_success_data(api.submit_review_study(study["id"], SCIENTIST))
    return study


def test_study_revise_cycles_back_to_running_and_rematches(api):
    """Revise from IN_REVIEW returns to RUNNING and re-runs the matched-control selection.

    PRD: "Revising sends the study back to `RUNNING` and re-runs the matched-control selection against the current panel, replacing `matched_pairs` wholesale"
    Design: Difficulty/non_linear_state_machine/study_revision_cycle_rematches_controls
    """
    study = _study_in_review(api)
    revised = get_success_data(api.revise_study(study["id"], SCIENTIST))
    assert revised["status"] == "RUNNING"
    # The clock is already past window_end, so the next read lands in ANALYSIS again.
    observed = read_study(api, study["id"])
    assert observed["status"] == "ANALYSIS"
    pairs = observed["matched_pairs"]
    assert [(p["test_household_ref"], p["control_household_ref"]) for p in pairs] == [
        ("T1", "C1"),
        ("T2", "C2"),
    ]


def test_study_republish_after_terminal_state_rejected(api):
    """After the revise loop, the study publishes; a second publish is rejected as an invalid transition.

    PRD: "Both review exits require the study to actually be `IN_REVIEW`, else `ERR_STUDY_INVALID_TRANSITION`."
    PRD: "Publishing moves the study to its terminal `PUBLISHED` state."
    Design: Difficulty/non_linear_state_machine/study_revision_cycle_rematches_controls
    """
    from test_helpers import ApiErrorId, validate_error

    study = _study_in_review(api)
    get_success_data(api.revise_study(study["id"], SCIENTIST))
    read_study(api, study["id"])  # auto-transition back to ANALYSIS
    get_success_data(api.submit_review_study(study["id"], SCIENTIST))
    published = get_success_data(api.publish_study(study["id"], SCIENTIST))
    assert published["status"] == "PUBLISHED"
    validate_error(api.publish_study(study["id"], SCIENTIST), ApiErrorId.STUDY_INVALID_TRANSITION.value, 409)
