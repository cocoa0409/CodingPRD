"""Two contended timelines with deliberately opposite interval semantics.

A holder's licences for one rule in one country form a half-open timeline where touching
endpoints are legal. An advertiser's enforcement timeline is closed at both ends, so the
final instant of a blackout still collides. Each pair probes its window at the exact
boundary instant and one step past it.
"""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

GAMBLING = "GAMBLING_ONLINE"


# ---------------------------------------------------------------------------
# Shared setup for the certification timeline
# ---------------------------------------------------------------------------
def _holder_with_one_live_licence():
    """One ACTIVE licence for (holder, GAMBLING_ONLINE, US) covering August."""
    rule = fixtures.create_policy_rule(
        GAMBLING,
        "RESTRICTED",
        4.00,
        title="Online gambling",
        requires_certification=True,
        confidence_auto_disapprove_threshold=0.88,
        confidence_manual_threshold=0.35,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        severity_multiplier=1.20,
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Tidewater Gaming Ltd",
        country_code="US",
        industry_code="GAMING",
    )
    advertiser_id = advertiser["id"]
    first = fixtures.create_certification(
        advertiser_id,
        rule["id"],
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        issuing_country_code="US",
        license_number="GAM-US-2026-0001",
        headers=make_advertiser_headers(advertiser_id),
    )
    return {
        "rule_id": rule["id"],
        "advertiser_id": advertiser_id,
        "first": first,
    }


def _file_licence(case, license_number, valid_from, valid_until, country="US"):
    """The raw response to one certification submission by the holder."""
    return api_client.create_certification(
        factories.create_certification_payload(
            case["advertiser_id"],
            case["rule_id"],
            valid_from,
            valid_until,
            country,
            license_number=license_number,
        ),
        make_advertiser_headers(case["advertiser_id"]),
    )


def test_licences_abutting_at_either_endpoint_are_both_admitted():
    """PRD §3.5: "On submission, the new interval is rejected when there already exists
    a certification for the same combination of `advertiser_id`, `policy_rule_id` and
    `issuing_country_code` whose `status` is `SUBMITTED` or `ACTIVE` and whose interval
    intersects the new one — intersection meaning that the new `valid_from` is strictly
    before the existing `valid_until` and the existing `valid_from` is strictly before the
    new `valid_until`."

    PRD §3.5: "Adjacency is therefore expressly legal: a new interval starting exactly at
    an existing interval's `valid_until`, or ending exactly at an existing interval's
    `valid_from`, does not intersect it and is admitted."

    PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    Design: Difficulty/resource_temporal_overlap/certification_half_open_intervals_reject_overlap_but_accept_both_adjacencies
    """
    case = _holder_with_one_live_licence()
    # The clock sits exactly on the inclusive valid_from of the first licence.
    assert case["first"]["status"] == "ACTIVE"

    right = validate_success(
        _file_licence(
            case, "GAM-US-2026-0002", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        201,
    )
    assert right["status"] == "SUBMITTED"

    left = validate_success(
        _file_licence(
            case, "GAM-US-2026-0003", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        201,
    )
    # The clock is not strictly inside this window, so it is not born ACTIVE.
    assert left["status"] == "SUBMITTED"


def test_a_straddling_licence_collides_only_within_its_own_country():
    """PRD §3.5: "The rejection is `ERR_CERTIFICATION_INTERVAL_OVERLAP` (HTTP 409)."

    PRD §3.5: "A holder may not hold two overlapping licences for the same rule in the
    same country."

    PRD §2.3: "certifications by `valid_from` ascending and then `created_at` ascending"

    Design: Difficulty/resource_temporal_overlap/certification_half_open_intervals_reject_overlap_but_accept_both_adjacencies
    """
    case = _holder_with_one_live_licence()
    validate_success(
        _file_licence(
            case, "GAM-US-2026-0002", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        201,
    )
    validate_success(
        _file_licence(
            case, "GAM-US-2026-0003", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        201,
    )

    # Mid-August to mid-September straddles the shared 2026-09-01 boundary.
    validate_error(
        _file_licence(
            case, "GAM-US-2026-0004", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z"
        ),
        ApiErrorId.ERR_CERTIFICATION_INTERVAL_OVERLAP,
        409,
    )

    # The identical window issued in another country contends with nothing.
    swedish = validate_success(
        _file_licence(
            case,
            "GAM-SE-2026-0005",
            "2026-08-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
            country="SE",
        ),
        201,
    )
    assert swedish["issuing_country_code"] == "SE"

    rows, pagination = validate_paginated(
        api_client.list_certifications(
            ADMIN,
            {
                "advertiser_id": case["advertiser_id"],
                "policy_rule_id": case["rule_id"],
            },
        )
    )
    assert pagination["total_count"] == 4, "the refused submission wrote nothing"
    assert [row["valid_from"][:10] for row in rows] == [
        "2026-07-01",
        "2026-08-01",
        "2026-08-15",
        "2026-09-01",
    ]
    active = [row for row in rows if row["status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["id"] == case["first"]["id"]


# ---------------------------------------------------------------------------
# Shared setup for the enforcement timeline
# ---------------------------------------------------------------------------
def _advertiser_under_a_warning_at_the_blackout_edge():
    """A clean advertiser carrying one manual WARNING, clocked to the blackout's edge.

    The warning runs 2026-08-01 to 2026-08-10, so its blackout window closes at
    2026-08-13T00:00:00Z once the 72 cooldown hours are added. Nothing else exists on
    the account: no creative, no notice and no ledger entry.
    """
    advertiser = fixtures.create_advertiser(
        legal_name="Kestrel Direct Marketing",
        country_code="US",
        industry_code="RETAIL",
    )
    advertiser_id = advertiser["id"]
    base_version = fixtures.read_advertiser(advertiser_id)["version"]
    warning = fixtures.mint_enforcement_action(
        advertiser_id,
        "WARNING",
        base_version,
        trigger_reason="Manual integrity warning after a partner audit.",
        effective_until="2026-08-10T00:00:00Z",
    )
    fixtures.set_clock("2026-08-13T00:00:00Z")
    return {
        "advertiser_id": advertiser_id,
        "base_version": base_version,
        "warning": warning,
    }


def _mint_restriction(advertiser_id, expected_version, trigger_reason):
    """The raw response to one manual RESTRICTION request."""
    return api_client.create_enforcement_action(
        advertiser_id,
        factories.create_enforcement_action_payload(
            "RESTRICTION", expected_version, trigger_reason=trigger_reason
        ),
        ADMIN,
    )


def test_the_final_instant_of_the_blackout_still_refuses_a_manual_action():
    """PRD §3.9: "A manual action is additionally blocked by a cooldown: the new
    `effective_from` — the logical clock — may not fall inside the blackout window of any
    existing action on the advertiser, where that window runs from that action's
    `effective_from` through its `effective_until` extended by a further 72 hours,
    inclusive at both ends, and where existing actions in every status — `ACTIVE`,
    `LIFTED`, `EXPIRED` and `SUPERSEDED` — are considered."

    PRD §3.9: "An action is `EXPIRED` by the sweep's fifth phase once its
    `effective_until` has been reached or passed, which likewise re-derives
    `account_status` and bumps both versions."

    Design: Difficulty/resource_temporal_overlap/enforcement_cooldown_closed_blackout_window_rejects_action_at_its_final_instant
    """
    case = _advertiser_under_a_warning_at_the_blackout_edge()
    advertiser_id = case["advertiser_id"]

    warning = case["warning"]
    assert warning["origin"] == "MANUAL"
    assert warning["severity_index_at_issue"] == pytest.approx(0.00, abs=0.01)
    assert_instant_equals(
        warning["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        warning["effective_until"], "2026-08-10T00:00:00Z", "effective_until"
    )

    # The clock has passed effective_until, but expiry is sweep-driven and no sweep
    # has run, so the row is still in force.
    before = fixtures.read_advertiser(advertiser_id)
    assert fixtures.read_action(warning["id"])["status"] == "ACTIVE"
    assert before["account_status"] == "WARNED"
    assert before["version"] == case["base_version"] + 1

    validate_error(
        _mint_restriction(
            advertiser_id,
            before["version"],
            "Escalating to a restriction at the blackout boundary.",
        ),
        ApiErrorId.ERR_ENFORCEMENT_COOLDOWN_CONFLICT,
        409,
    )

    after = fixtures.read_advertiser(advertiser_id)
    assert after["version"] == before["version"], "the refused call wrote nothing"
    assert after["account_status"] == "WARNED"
    assert len(fixtures.actions_for_advertiser(advertiser_id)) == 1


def test_one_second_past_the_blackout_the_identical_action_lands():
    """PRD §3.9: "When `effective_until` is not supplied it defaults to `effective_from`
    plus the duration for the type: 30 days for a warning, 60 days for a restriction and
    180 days for a suspension."

    PRD §3.9: "Creating an action moves any existing `ACTIVE` action on the advertiser to
    `SUPERSEDED`, points the new action's `prior_action_id` at it, re-derives
    `account_status` and increments the advertiser's `version` by 1; a `SUSPENSION`
    additionally sweeps the advertiser's creatives to `SUSPENDED_HOLD` and expires their
    review tasks."

    Design: Difficulty/resource_temporal_overlap/enforcement_cooldown_closed_blackout_window_rejects_action_at_its_final_instant
    """
    case = _advertiser_under_a_warning_at_the_blackout_edge()
    advertiser_id = case["advertiser_id"]
    warning_id = case["warning"]["id"]

    validate_error(
        _mint_restriction(
            advertiser_id,
            case["base_version"] + 1,
            "Escalating to a restriction at the blackout boundary.",
        ),
        ApiErrorId.ERR_ENFORCEMENT_COOLDOWN_CONFLICT,
        409,
    )

    fixtures.set_clock("2026-08-13T00:00:01Z")
    restriction = validate_success(
        _mint_restriction(
            advertiser_id,
            fixtures.read_advertiser(advertiser_id)["version"],
            "Escalating to a restriction one second after the blackout.",
        ),
        201,
    )
    assert restriction["action_type"] == "RESTRICTION"
    assert restriction["origin"] == "MANUAL"
    assert restriction["status"] == "ACTIVE"
    assert_instant_equals(
        restriction["effective_from"], "2026-08-13T00:00:01Z", "effective_from"
    )
    # 60 whole days from the new effective_from, the restriction default.
    assert_instant_equals(
        restriction["effective_until"], "2026-10-12T00:00:01Z", "effective_until"
    )
    assert restriction["prior_action_id"] == warning_id
    assert restriction["source_notice_id"] is None
    assert fixtures.read_action(warning_id)["status"] == "SUPERSEDED"

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["account_status"] == "RESTRICTED"
    # The whole ladder ran on an account with no points at all.
    assert advertiser["violation_points_raw"] == pytest.approx(0.00, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(0.00, abs=0.01)
    assert fixtures.ledger_for_advertiser(advertiser_id) == []
    assert len(fixtures.actions_for_advertiser(advertiser_id)) == 2
