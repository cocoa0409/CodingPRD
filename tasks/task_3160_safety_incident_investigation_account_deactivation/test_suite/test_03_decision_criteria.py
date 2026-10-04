"""The graduated deactivation decision: the category tier floor, the continuous
evidence overrides and the pinned order in which they are applied."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    decide_now,
    get_account,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_incident_in_state,
    setup_policy,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]

# One evidence type only: three DISPOSITIVE EXTERNAL_RECORD items, each 1.125
# with a 1.00 type cap. The S4 required-sources penalty is one missing source
# (0.15) and the cap ceiling is 3.00, so the frozen score settles at exactly
# 3.00 with a single distinct source — over the 2.50 provisional threshold and
# below the 4.00 deactivation threshold.
S4_SINGLE_SOURCE_TRIO = [
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
]


def _provisional_incident(account_id):
    """A held S4 incident at PENDING_DECISION with the single-source trio.

    The report is filed before the default clock instant so no other incident of
    the account can share the incident's `created_at` (the frozen-prior-count
    key of PRD §3.1)."""
    set_clock("2026-09-01T00:00:00Z")
    incident = make_incident(account_id, incident_category="PHYSICAL_ASSAULT")
    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    from test_helpers import gather_and_accept

    gather_and_accept(incident["id"], S4_SINGLE_SOURCE_TRIO)
    return incident["id"]


def test_decision_criteria_holds_the_floor_at_restricted_on_a_provisional_score(api):
    """PRD §3.4: "the **category tier floor** is read first, and the continuous-evidence
    overrides are then applied in ascending threshold order, each override able to raise the
    floor result but never to lower it."
    PRD §3.4: "a `PHYSICAL_ASSAULT` incident scoring 3.99 on a single source resolves to
    `RESTRICTED` rather than escaping all the way to `DEACTIVATED`"

    Design: Difficulty/combinatorial_formula/combinatorial_decision_criteria_circular_tier_floor
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="dara.whitfield")
    incident_id = _provisional_incident(account["id"])

    criteria = get_success_data(api_client.get_decision_criteria(incident_id, INVESTIGATOR))
    frozen = get_success_data(api_client.get_incident(incident_id, INVESTIGATOR))

    assert criteria["category_tier"] == "DEACTIVATED", (
        "PHYSICAL_ASSAULT is a category that floors at DEACTIVATED"
    )
    assert frozen["decision_evidence_score"] >= 2.50, (
        "the provisional override only engages at or above 2.50"
    )
    assert frozen["decision_evidence_score"] < 4.00, (
        "the >= 4.00 override does not apply, so the provisional branch is the one read"
    )
    assert frozen["decision_distinct_evidence_sources"] < 2, (
        "the second corroborating source is what caps the provisional branch"
    )
    assert criteria["evidence_tier"] == "RESTRICTED", (
        "the evidence tier lands on the provisional deactivation, which cannot fire for "
        f"want of a second corroborating source, got {criteria['evidence_tier']}"
    )
    assert criteria["proposed_decision"] == "RESTRICTED", (
        "the provisional deactivation settles at RESTRICTED rather than escaping all the "
        "way to the DEACTIVATED the category floor alone would give"
    )


def test_decision_criteria_reads_the_category_floor_alone(api):
    """PRD §3.4: "The floor itself is a ladder of conditions, read top to bottom:"
    PRD §3.4: "`PHYSICAL_ASSAULT` and `SEXUAL_MISCONDUCT` floor at `DEACTIVATED`."
    PRD §3.4: "the **category tier floor** is read first, and the continuous-evidence overrides
    are then applied in ascending threshold order, each override able to raise the floor result
    but never to lower it."

    Design: Difficulty/combinatorial_formula/combinatorial_decision_criteria_circular_tier_floor
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="dara.whitfield.floor")
    incident_id = _provisional_incident(account["id"])

    criteria = get_success_data(api_client.get_decision_criteria(incident_id, INVESTIGATOR))

    assert criteria["category_tier"] == "DEACTIVATED"
    assert criteria["proposed_decision"] == "RESTRICTED"
    assert criteria["evidence_tier"] == "RESTRICTED"


def test_boundary_evidence_score_exactly_at_the_deactivation_floor(api):
    """PRD §3.4: "When `decision_evidence_score` is at least **4.00**, or is at least **2.50**
    with `decision_distinct_evidence_sources` of at least 2, the outcome is `DEACTIVATED`."
    PRD §2.5: "Implementations must expose the primary, per-item-rounded reading on the freeze
    path."

    Design: Difficulty/boundary_precision_check/boundary_evidence_score_exactly_at_the_deactivation_floor
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    # SAFETY_VIOLATION is not a reportable category, so the action stays ACTIVE.
    account = setup_account(handle="pia.lindqvist")
    incident = make_incident(account["id"], incident_category="SAFETY_VIOLATION",
                             aggravator_codes=["S3_INJURY"])
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    set_clock("2026-10-01T00:00:00Z")
    # SAFETY_VIOLATION without three prior serious incidents floors at NO_ACTION, so
    # any outcome above it is attributable to the evidence score alone.
    four_trip_items = [
        {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"}
        for _ in range(4)
    ]
    from test_helpers import gather_and_accept

    gather_and_accept(incident["id"], four_trip_items)

    view = get_success_data(api_client.get_evidence_score(incident["id"], INVESTIGATOR))
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))

    assert view["distinct_evidence_source_count"] == 1, (
        "all four items share one evidence type, so the distinct-source condition of the "
        "2.50 override cannot be satisfied"
    )
    assert frozen["decision_evidence_score"] == pytest.approx(4.00, abs=0.005), (
        "four DISPOSITIVE TRIP_DATA items give an unclamped 5.72, so the four-item type "
        f"cap of 4.00 binds and the value sits exactly on the constant, "
        f"got {frozen['decision_evidence_score']}"
    )
    assert view["applied_evidence_cap"] == pytest.approx(4.00, abs=0.005), (
        "the cap ceiling is the four per-item TRIP_DATA caps summed"
    )

    assert frozen["incident_status"] == "PENDING_DECISION"
    assert frozen["decision_evidence_score"] == pytest.approx(4.00, abs=0.005), (
        "four DISPOSITIVE TRIP_DATA items give an unclamped 5.72, so the four-item type "
        f"cap of 4.00 binds, got {frozen['decision_evidence_score']}"
    )
    decided = decide_now(incident["id"], "RESTRICTED", frozen["version"])
    assert decided["incident_status"] == "DECIDED"
    assert decided["decision_category"] == "RESTRICTED", (
        "a mono-source set engages the provisional override, which settles at RESTRICTED"
    )


def test_property_damage_warning_floor_from_the_evidence_score(api):
    """PRD §3.4: "`PROPERTY_DAMAGE` floors at `WARNING` when `decision_evidence_score` is at
    least 1.50."

    Design: Corner/calculations/enforcement_risk_term_ignores_weight_for_a_warning_outcome
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="priya.nair")
    incident, _ = setup_incident_in_state(
        account["id"], incident_category="PROPERTY_DAMAGE",
        evidence_specs=[
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
        ],
    )

    criteria = get_success_data(api_client.get_decision_criteria(incident["id"], INVESTIGATOR))
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))

    assert frozen["decision_evidence_score"] >= 1.50, (
        "the PROPERTY_DAMAGE warning floor only engages at or above 1.50"
    )
    assert criteria["category_tier"] == "WARNING", (
        "PROPERTY_DAMAGE with an evidence score at or above 1.50 floors at WARNING"
    )
    assert criteria["proposed_decision"] == "WARNING"

    decided = decide_now(incident["id"], "WARNING", frozen["version"])
    assert decided["decision_category"] == "WARNING"
    account_after = get_account(account["id"])
    assert account_after["status"] == "RESTRICTED", (
        "a WARNING outcome moves the account to RESTRICTED rather than deactivating it"
    )


def test_deactivation_while_an_account_sits_restricted(api):
    """PRD §3.4: "A decision may also be committed against an incident at `PENDING_DECISION`
    whose account currently sits at `RESTRICTED` from an earlier matter, which is the
    repeat-offender path."

    Design: Difficulty/cross_entity_state_dependency/dependency_decision_blocked_by_sibling_in_flight_appeal
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="sana.iqbal")
    set_clock("2026-09-01T00:00:00Z")

    first, _ = setup_incident_in_state(
        account["id"], incident_category="PHYSICAL_ASSAULT",
        evidence_specs=[
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    first_frozen = get_success_data(api_client.get_incident(first["id"], INVESTIGATOR))
    first_criteria = get_success_data(
        api_client.get_decision_criteria(first["id"], INVESTIGATOR)
    )
    first_decision = decide_now(first["id"], "RESTRICTED", first_frozen["version"])
    assert first_decision["decision_category"] in ("RESTRICTED", "WARNING", "DEACTIVATED")
    assert get_account(account["id"])["status"] == "RESTRICTED", (
        "a non-deactivating graduated outcome lands the account at RESTRICTED"
    )

    set_clock("2026-10-01T00:00:00Z")
    second, _ = setup_incident_in_state(
        account["id"], incident_category="SEXUAL_MISCONDUCT",
        evidence_specs=[
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    second_frozen = get_success_data(api_client.get_incident(second["id"], INVESTIGATOR))
    assert second_frozen["incident_status"] == "PENDING_DECISION"
    assert get_account(account["id"])["status"] == "PENDING_DECISION", (
        "the investigation advance carries the account to PENDING_DECISION with the "
        "incident, which is the state the repeat-offender decision is declared from"
    )

    decided = decide_now(second["id"], "DEACTIVATED", second_frozen["version"])
    assert decided["incident_status"] == "DECIDED"
    assert decided["decision_category"] == "DEACTIVATED"
    after = get_account(account["id"])
    assert after["status"] == "DEACTIVATED"
    assert after["deactivation_count"] == 1