"""Severity classification interactions and excerpt truncation."""
import pytest

from test_helpers import (
    assert_alert,
    ingest_content,
    make_parent_headers,
    setup_monitoring_pipeline,
    validate_success,
    validate_paginated,
)


def test_severity_classification_multi_factor_mode_a(api):
    """PRD §3.6: "The base level comes from the `risk_score` alone: a score of
    at least 85 yields level 4 (`SEVERE`), a score from 60 to 84 inclusive
    yields level 3 (`HIGH`), a score from 30 to 59 inclusive yields level 2
    (`MODERATE`), and anything below 30 yields level 1 (`LOW`)."
    PRD §3.6: "The age adjustment adds one level when the child's `age_band` is
    `CHILD_9_UNDER`, subtracts one level when the band is `OLDER_TEEN_16_17` and
    the dominant category is `EXPLICIT`, and adds nothing otherwise."
    PRD §3.6: "The sensitivity adjustment adds one level when the child's
    `monitoring_sensitivity` is `STRICT`, subtracts one when it is `LENIENT`,
    and adds nothing when it is `STANDARD`."
    PRD §3.8: "A `SEVERE` alert always opens an escalation case in `OPEN`
    status, linked through the case's `alert_id` and the child's
    `child_profile_id`, with the alert's `escalation_case_id` pointing back (the
    field remains null for non-severe alerts)."
    PRD §3.8: "At case creation the system populates `crisis_resource_codes`
    from the alert's category: `SELF_HARM` maps to the codes `CRISIS_TEXT_LINE`
    and `988_LIFELINE`; `PREDATORY_CONTACT` maps to `NCMEC_CYBERTIPLINE`;
    `BULLYING` maps to `STOPBULLYING_GOV`; and `EXPLICIT` maps to
    `COMMON_SENSE_MEDIA`."

    Design: Difficulty/combinatorial_formula/severity_classification_multi_factor_mode_a
    """
    # Child: birth_year 2020 -> age 6 -> CHILD_9_UNDER (+1); STRICT (+1).
    fam, parent, child, dev, conn = setup_monitoring_pipeline(
        birth_year=2020, monitoring_sensitivity="STRICT", service_type="EMAIL"
    )
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[
            {"category": "BULLYING", "weight": 30},
            {"category": "EXPLICIT", "weight": 25},
        ],
        raw_text="multi factor item",
    )
    # base 55 -> MODERATE (level 2); +1 age +1 sensitivity -> level 4 SEVERE.
    assert item["risk_score"] == 55
    assert item["severity"] == "SEVERE"
    assert item["alert_created"] is True

    headers = make_parent_headers(parent["id"])
    alert = validate_success(api.get_alert(item["alert_id"], headers))
    assert_alert(alert)
    assert alert["severity"] == "SEVERE"
    assert alert["escalation_case_id"] is not None

    case = validate_success(api.get_escalation_case(alert["escalation_case_id"], headers))
    assert case["case_status"] == "OPEN"
    # Dominant category is BULLYING (weight 30 > 25).
    assert case["crisis_resource_codes"] == ["STOPBULLYING_GOV"]


def test_severity_floor_for_predatory_contact(api):
    """PRD §3.6: "Separately, each dominant category imposes a floor:
    `PREDATORY_CONTACT` and `SELF_HARM` each floor the outcome at level 3, while
    `BULLYING` and `EXPLICIT` floor it at level 1. The final level is the larger
    of the adjusted base level and the dominant category's floor, clamped into
    the 1-to-4 range, and maps to `LOW`, `MODERATE`, `HIGH`, and `SEVERE`
    respectively."

    Design: Difficulty/combinatorial_formula/severity_classification_multi_factor_mode_a
    """
    # Older teen, LENIENT: base 10 -> LOW (level 1); sensitivity -1 -> clamped 1;
    # dominant PREDATORY_CONTACT floor 3 -> HIGH.
    fam, parent, child, dev, conn = setup_monitoring_pipeline(
        birth_year=2009, monitoring_sensitivity="LENIENT"
    )
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "PREDATORY_CONTACT", "weight": 10}],
        raw_text="floor item",
    )
    assert item["risk_score"] == 10
    assert item["severity"] == "HIGH", (
        f"category floor must lift level to 3 (HIGH), got {item['severity']}"
    )
    assert item["alert_created"] is True


def test_excerpt_truncation_word_boundary_and_teen_cap(api):
    """PRD §3.7: "The character cap is 140, with one exception: when the child's
    `age_band` is `OLDER_TEEN_16_17` and the child's `monitoring_sensitivity` is
    `LENIENT`, the cap is 70 characters. If the raw text fits within the cap,
    the excerpt is the raw text unchanged. Otherwise, the system takes the
    leading characters of the raw text up to the cap; if that head contains a
    space, the head is cut back to end just before its last space; the excerpt
    is then that head followed by a single ellipsis character."

    Design: Corner/calculations/excerpt_truncation_word_boundary_and_teen_cap
    """
    raw = "x" * 139 + " " + "y" * 100

    fam, parent, child_a, dev_a, conn_a = setup_monitoring_pipeline(
        birth_year=2012, monitoring_sensitivity="STANDARD"
    )
    item_a = ingest_content(
        conn_a["id"], dev_a["id"],
        signals=[{"category": "BULLYING", "weight": 40}],
        raw_text=raw,
    )
    headers = make_parent_headers(parent["id"])
    alert_a = validate_success(api.get_alert(item_a["alert_id"], headers))
    # Head of 140 chars contains the space at position 139 -> cut back to 139.
    assert alert_a["excerpt_text"] == "x" * 139 + "…"
    assert len(alert_a["excerpt_text"]) == 140

    # Older teen + LENIENT -> cap 70; first 70 chars are all 'x' (no space).
    # Base score 60 -> HIGH; LENIENT subtracts one -> MODERATE, so an alert is
    # still created even after the leniency adjustment.
    child_b_resp = api.create_child(
        {"family_account_id": fam["id"], "display_name": "Kid EXB",
         "birth_year": 2009, "monitoring_sensitivity": "LENIENT"},
        headers,
    )
    child_b = validate_success(child_b_resp, expected_status=201)
    dev_b_resp = api.pair_device(
        child_b["id"], {"platform": "IOS", "nickname": "EXB-1"}, headers
    )
    dev_b = validate_success(dev_b_resp, expected_status=201)
    conn_b_resp = api.create_connection(
        child_b["id"],
        {"service_type": "MESSAGING", "external_handle": "kidexb@msg",
         "credential_token": "tok-exb"},
        headers,
    )
    conn_b = validate_success(conn_b_resp, expected_status=201)
    resp = api.set_connection_state(conn_b["id"], {"to_status": "ACTIVE"}, headers)
    validate_success(resp)

    item_b = ingest_content(
        conn_b["id"], dev_b["id"],
        signals=[{"category": "BULLYING", "weight": 60}],
        raw_text=raw,
    )
    alert_b = validate_success(api.get_alert(item_b["alert_id"], headers))
    assert alert_b["excerpt_text"] == "x" * 70 + "…"
    assert len(alert_b["excerpt_text"]) == 71
