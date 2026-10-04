"""Content ingestion and risk scoring: variants, caps, suppression."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_content_item,
    create_connection,
    create_family,
    create_child,
    ingest_content,
    make_parent_headers,
    pair_device,
    set_connection_state,
    setup_monitoring_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = None  # resolved lazily via TEST_USERS


def _admin():
    from test_helpers import TEST_USERS

    return TEST_USERS["platform_admin_headers"]


def test_risk_scoring_lexical_vs_contextual_variants(api):
    """PRD §3.5: "Both variants begin from the same base: the sum of the
    `weight` of every entry in the `signals` array, capped at 100. Under
    `LEXICAL_V1`, the `risk_score` is exactly that capped base — pure keyword
    weighting, with thread depth ignored. Under `CONTEXTUAL_V2`, the base is
    first multiplied by a thread-depth factor: one plus five-hundredths times
    the thread depth, where the depth used is the actual `thread_depth` or 5,
    whichever is smaller; the product is rounded half-up to the nearest integer
    and then capped at 100."
    PRD §3.5: "At ingest, the system records `analysis_variant_used` by copying
    the family's current `analysis_variant`, and computes the content item's
    `risk_score` on a 0–100 integer scale using that variant."

    Design: Difficulty/dual_variant_calc/risk_scoring_lexical_vs_contextual_variants
    """
    signals = [
        {"category": "BULLYING", "weight": 30},
        {"category": "EXPLICIT", "weight": 25},
    ]

    fam_a, parent_a, child_a, dev_a, conn_a = setup_monitoring_pipeline(
        birth_year=2012,
        monitoring_sensitivity="STANDARD",
        family_overrides={"analysis_variant": "LEXICAL_V1"},
    )
    fam_b, parent_b, child_b, dev_b, conn_b = setup_monitoring_pipeline(
        birth_year=2012,
        monitoring_sensitivity="STANDARD",
        family_overrides={"analysis_variant": "CONTEXTUAL_V2"},
    )

    item_a = ingest_content(
        conn_a["id"], dev_a["id"], signals=signals, thread_depth=3,
        raw_text="sample text A",
    )
    item_b = ingest_content(
        conn_b["id"], dev_b["id"], signals=signals, thread_depth=3,
        raw_text="sample text B",
    )
    assert_content_item(item_a)
    assert_content_item(item_b)

    # base = 30 + 25 = 55; LEXICAL_V1 -> 55.
    assert item_a["risk_score"] == 55
    assert item_a["analysis_variant_used"] == "LEXICAL_V1"
    # CONTEXTUAL_V2: round_half_up(55 * (1 + 0.05*3)) = round_half_up(63.25) = 63.
    assert item_b["risk_score"] == 63
    assert item_b["analysis_variant_used"] == "CONTEXTUAL_V2"
    assert item_a["risk_score"] != item_b["risk_score"]


def test_risk_scoring_depth_beyond_cap_and_saturation(api):
    """PRD §3.5: "Under `CONTEXTUAL_V2`, the base is first multiplied by a
    thread-depth factor: one plus five-hundredths times the thread depth, where
    the depth used is the actual `thread_depth` or 5, whichever is smaller; the
    product is rounded half-up to the nearest integer and then capped at 100."

    Design: Difficulty/dual_variant_calc/risk_scoring_lexical_vs_contextual_variants
    """
    # depth 10 is clamped to 5: factor 1.25; base 40 -> 50.
    fam, parent, child, dev, conn = setup_monitoring_pipeline(
        birth_year=2012,
        family_overrides={"analysis_variant": "CONTEXTUAL_V2"},
    )
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}],
        thread_depth=10,
    )
    assert item["risk_score"] == 50, (
        f"depth clamped to 5 must yield 40*1.25 = 50, got {item['risk_score']}"
    )

    # depth beyond 5 does not score higher than depth exactly 5.
    item5 = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}],
        thread_depth=5,
    )
    assert item5["risk_score"] == 50


def test_risk_score_capped_at_100(api):
    """PRD §3.5: "Both variants begin from the same base: the sum of the
    `weight` of every entry in the `signals` array, capped at 100."
    PRD §3.6: "The base level comes from the `risk_score` alone: a score of at
    least 85 yields level 4 (`SEVERE`), a score from 60 to 84 inclusive yields
    level 3 (`HIGH`), a score from 30 to 59 inclusive yields level 2
    (`MODERATE`), and anything below 30 yields level 1 (`LOW`)."
    PRD §3.6: "The dominant category is the signal entry with the greatest
    `weight`; ties break to the entry appearing earliest in the `signals`
    array."

    Design: Corner/calculations/risk_score_capped_at_100
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[
            {"category": "PREDATORY_CONTACT", "weight": 60},
            {"category": "SELF_HARM", "weight": 50},
            {"category": "BULLYING", "weight": 45},
        ],
        raw_text="cap item",
    )
    # 60 + 50 + 45 = 155, capped to 100 -> SEVERE.
    assert item["risk_score"] == 100
    assert item["severity"] == "SEVERE"
    assert item["alert_created"] is True

    headers = make_parent_headers(parent["id"])
    alert = validate_success(api.get_alert(item["alert_id"], headers))
    assert alert["category"] == "PREDATORY_CONTACT"
    assert alert["severity"] == "SEVERE"


def test_low_severity_content_suppressed_no_alert(api):
    """PRD §3.6: "An alert is created exactly when the resulting `severity` is
    `MODERATE`, `HIGH`, or `SEVERE`; the content item's `alert_created` flag
    records this, and its `alert_id` references the created alert, remaining
    null for suppressed `LOW` content."

    Design: Corner/calculations/low_severity_content_suppressed_no_alert
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "EXPLICIT", "weight": 10}],
        raw_text="mild item",
    )
    assert item["risk_score"] == 10
    assert item["severity"] == "LOW"
    assert item["alert_created"] is False
    assert item["alert_id"] is None

    headers = make_parent_headers(parent["id"])
    alerts, meta = validate_paginated(
        api.list_alerts(headers, params={"child_profile_id": child["id"]})
    )
    assert meta["total_count"] == 0
    assert alerts == []


def test_error_connection_not_active_on_ingest(api):
    """PRD §3.4: "Only an `ACTIVE` connection accepts content ingestion;
    attempting to ingest content through a connection in any other state is
    rejected with `ERR_CONNECTION_NOT_ACTIVE`."

    Design: Corner/errors/error_connection_not_active_on_ingest
    """
    from test_helpers import make_device_agent_headers, create_content_item_payload

    fam, parent = create_family()
    child = create_child(fam["id"], parent["id"])
    dev = pair_device(child["id"], parent["id"], nickname="NA-1")
    conn = create_connection(
        child["id"], parent["id"],
        service_type="MESSAGING", external_handle="kidna@msg",
        credential_token="tok-na",
    )
    # Connection remains AWAITING_CONSENT.
    resp = api.ingest_content_item(
        create_content_item_payload(service_connection_id=conn["id"]),
        make_device_agent_headers(dev["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONNECTION_NOT_ACTIVE)
