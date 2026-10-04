"""Evidence admissibility: the weighted score, its type caps, the pinned rounding
order and the freeze onto the incident snapshot."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_incident,
    gather_and_accept,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_incident_in_state,
    setup_policy,
)


def _score_view(incident_id):
    return get_success_data(
        api_client.get_evidence_score(incident_id, TEST_USERS["investigator_headers"])
    )


def test_evidence_score_uses_the_per_item_rounded_reading(api):
    """PRD §2.5: "Each admitted evidence item's weighted value is rounded to **three**
    decimal places using round-half-up, the rounded values are summed, any cap and penalty
    are applied to that rounded sum, and the final figure is rounded to **two** decimal
    places using round-half-up."
    PRD §2.5: "The region-level triage projection deliberately sums the same items
    **unrounded** and rounds only the final figure, so the two readings of one evidence set
    can diverge by up to 0.02 whenever an item's third decimal is non-zero."

    Design: Difficulty/dual_variant_calc/dual_variant_evidence_score_per_item_rounding_vs_raw_sum
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="ada.mensah")
    set_clock("2026-09-01T00:00:00Z")
    incident = make_incident(account["id"], incident_category="HARASSMENT",
                            reporter_type="RIDER")
    # HARASSMENT (base 2) plus one aggravator reaches the S3 hold floor of §3.2.
    get_success_data(
        api_client.patch_incident_severity(incident["id"], ["S3_INJURY"],
                                          TEST_USERS["investigator_headers"])
    )
    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(incident["id"], TEST_USERS["investigator_headers"]))
    gather_and_accept(incident["id"], [
        {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "STRONG",
         "source_entity_id": account["id"]},
        {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "STANDARD"},
        {"evidence_type": "RATINGS_HISTORY", "evidence_weight": "STANDARD"},
    ])

    frozen = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["investigator_headers"])
    )
    view = _score_view(incident["id"])

    # Per item: LAW_ENFORCEMENT_CONTACT STRONG -> 0.95 * 1.00 = 0.950 (cap 0.70);
    #           EXTERNAL_RECORD STANDARD      -> 0.75 * 0.70 = 0.525 (cap 1.00);
    #           RATINGS_HISTORY STANDARD      -> 0.90 * 0.70 = 0.630 (cap 0.80).
    # Three distinct types are present and S3 needs two sources, so the cap
    # penalty is 0 and the cap ceiling is 0.70 + 1.00 + 0.80 = 2.50.
    assert frozen["decision_evidence_score"] == pytest.approx(2.11, abs=0.005), (
        "the weighted values are summed and the figure is rounded once at the end with "
        "round-half-up, so 2.105 becomes 2.11 rather than the 2.10 a banker's rounding "
        f"would give, got {frozen['decision_evidence_score']}"
    )
    assert frozen["decision_distinct_evidence_sources"] == 3
    assert view["applied_evidence_cap"] == pytest.approx(2.50, abs=0.005), (
        "the cap ceiling is the sum of the per-item type caps 0.70 + 1.00 + 0.80"
    )
    assert frozen["decision_evidence_score"] < view["applied_evidence_cap"], (
        "the reading is not clamped by the cap ceiling here"
    )


def test_single_law_enforcement_item_is_capped_and_lands_at_the_threshold(api):
    """PRD §3.3: "Each item also carries a type cap — 0.80 for `IN_APP_MESSAGE` and
    `RATINGS_HISTORY`, 0.70 for `LAW_ENFORCEMENT_CONTACT`, and 1.00 for every other type."
    PRD §2.5: "Each admitted evidence item's weighted value is rounded to **three** decimal
    places using round-half-up, the rounded values are summed, any cap and penalty are applied
    to that rounded sum, and the final figure is rounded to **two** decimal places using
    round-half-up."

    Design: Corner/calculations/evidence_cap_binds_before_the_type_cap_and_rounds_half_up
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="rosa.aguirre")
    set_clock("2026-09-01T00:00:00Z")
    incident = make_incident(account["id"], incident_category="SEXUAL_MISCONDUCT")
    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(incident["id"], TEST_USERS["investigator_headers"]))
    # PRD §3.3: the item's only type cap is the 0.70 LAW_ENFORCEMENT_CONTACT cap, and
    # a single accepted item is enough to resolve the last outstanding one.
    # A non-empty source keeps the item out of the STALE_SOURCE exclusion, so the
    # single item is the one admitted and the sole contributor to the cap.
    gather_and_accept(incident["id"], [
        {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE",
         "source_entity_id": account["id"]},
    ])
    frozen = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["investigator_headers"])
    )

    view = _score_view(incident["id"])

    assert frozen["incident_status"] == "PENDING_DECISION", (
        "the advance is gated on outstanding evidence only, so a single accepted item "
        "still moves the incident to decision-pending"
    )
    assert view["evidence_score"] == pytest.approx(0.70, abs=0.005), (
        "the DISPOSITIVE LAW_ENFORCEMENT_CONTACT item is worth 0.95 * 1.50 = 1.425 "
        "unclamped, but its 0.70 type cap binds and the penalty is zero for S4 once a "
        f"source is present, got {view['evidence_score']}"
    )
    assert view["applied_evidence_cap"] == pytest.approx(0.70, abs=0.005)
    assert view["distinct_evidence_source_count"] == 1
    assert_incident(frozen)


def test_evidence_snapshots_are_frozen_when_the_incident_reaches_pending_decision(api):
    """PRD §2.5: "the four fields that snapshot it — `decision_evidence_score`,
    `decision_support`, `decision_distinct_evidence_sources` and the instant `decided_at` —
    are frozen when the incident reaches `PENDING_DECISION` and are never recomputed
    afterwards."
    PRD §3.3: "When the last `PENDING` item resolves and at least one `INCLUDED` row exists,
    the investigation advances"

    Design: Difficulty/dual_variant_calc/dual_variant_evidence_score_per_item_rounding_vs_raw_sum
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="frozen.subject")
    set_clock("2026-09-01T00:00:00Z")
    incident = make_incident(account["id"], incident_category="HARASSMENT",
                            reporter_type="RIDER")
    # HARASSMENT (base 2) plus one aggravator reaches the S3 hold floor of §3.2.
    get_success_data(
        api_client.patch_incident_severity(incident["id"], ["S3_INJURY"],
                                          TEST_USERS["investigator_headers"])
    )
    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(incident["id"], TEST_USERS["investigator_headers"]))

    rows = gather_and_accept(incident["id"], [
        {"evidence_type": "RATINGS_HISTORY", "evidence_weight": "STANDARD"},
    ])
    assert rows, "at least one evidence row must exist"

    after_accept = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["investigator_headers"])
    )
    assert after_accept["incident_status"] == "PENDING_DECISION"
    frozen_score = after_accept["decision_evidence_score"]
    frozen_support = after_accept["decision_support"]
    frozen_sources = after_accept["decision_distinct_evidence_sources"]
    assert frozen_sources == 1, "one distinct evidence type was admitted"

    # Gathering a further item after the freeze must not move the snapshots: the
    # projection reads the frozen record rather than a moving one.
    gather_and_accept(incident["id"], [
        {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
    ])

    reread = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["investigator_headers"])
    )
    assert reread["decision_evidence_score"] == pytest.approx(frozen_score, abs=0.005), (
        "the frozen evidence score must not be recomputed by evidence resolved later"
    )
    assert reread["decision_support"] == pytest.approx(frozen_support, abs=0.005)
    assert reread["decision_distinct_evidence_sources"] == frozen_sources


def test_evidence_precision_is_pinned_to_two_decimal_places(api):
    """PRD §2.5: "Each admitted evidence item's weighted value is rounded to **three**
    decimal places using round-half-up, the rounded values are summed, any cap and penalty
    are applied to that rounded sum, and the final figure is rounded to **two** decimal
    places using round-half-up."

    Design: Corner/calculations/evidence_cap_binds_before_the_type_cap_and_rounds_half_up
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="precision.subject")
    set_clock("2026-09-01T00:00:00Z")
    # SAFETY_VIOLATION (base 2) plus one aggravator reaches the S3 hold floor.
    incident = make_incident(account["id"], incident_category="SAFETY_VIOLATION",
                             aggravator_codes=["S3_INJURY"])
    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(incident["id"], TEST_USERS["investigator_headers"]))
    gather_and_accept(incident["id"], [
        {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "STANDARD"},
        {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "STANDARD"},
        {"evidence_type": "RATINGS_HISTORY", "evidence_weight": "STANDARD"},
    ])
    incident = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["investigator_headers"])
    )

    score = incident["decision_evidence_score"]
    assert round(score, 2) == score, (
        f"the frozen score must carry at most two decimal places, got {score}"
    )
    external = 0.75 * 0.70    # 0.525
    ratings = 0.90 * 0.70     # 0.630
    cap_ceiling = 1.00 + 1.00 + 0.80
    expected = min(external + external + ratings, cap_ceiling)
    assert score == pytest.approx(expected, abs=0.005), (
        "the score is the sum of the weighted values with the cap and penalty applied to "
        "that sum, rounded once to two decimals at the end"
    )
    assert incident["decision_distinct_evidence_sources"] == 2, (
        "EXTERNAL_RECORD and RATINGS_HISTORY are the two distinct types admitted"
    )