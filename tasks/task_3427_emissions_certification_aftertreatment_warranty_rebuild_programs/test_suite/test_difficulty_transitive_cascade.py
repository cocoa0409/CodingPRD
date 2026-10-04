"""Transitive cascade tests (PRD §3.8 work-order verify cascade, §3.9 core
rejection reversal cascade).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    assert_engine_unit,
    assert_field_campaign,
    assert_reman_order,
    assert_service_center,
    complete_work_order,
    compute_completion_rate,
    get_family,
    get_unit,
    grade_core,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_full_environment,
    setup_reman_order_core_received,
    stamp_family_non_conforming,
    start_work_order,
    validate_success,
    verify_work_order,
)

CAMPAIGN_CLOCK = "2026-12-15T00:00:00Z"
ORDER_CLOCK = "2026-12-01T00:00:00Z"


# ---------------------------------------------------------------------------
# depth-4 cascade: verify -> unit REMEDIED -> counters -> CLOSED -> family
# ---------------------------------------------------------------------------
def _campaign_one_verify_short_of_closing():
    """RECALL campaign CMP-2 IN_PROGRESS over units UN-601/UN-602 with both
    work orders COMPLETED; UN-601's order is verified (rate 0.5) and the
    campaign has been moved to COMPLETION_REVIEW, one verification short of
    its 0.95 threshold."""
    env = setup_full_environment()
    family, fleet, center, tech = (
        env["family"], env["fleet"], env["center"], env["technician"],
    )
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-601")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-602")
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=10, passing_units=8,
    )
    set_logical_clock(CAMPAIGN_CLOCK)
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-2", campaign_type="RECALL",
        defect_summary="DPF substrate cracking",
        remedy_description="Replace DPF assembly", remedy_bay_days=1,
    )
    wo_a = schedule_work_order(
        campaign["id"], unit_a["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    wo_b = schedule_work_order(
        campaign["id"], unit_b["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    for wo in (wo_a, wo_b):
        start_work_order(wo["id"], center["id"])
        complete_work_order(wo["id"], center["id"])
    verify_work_order(wo_a["id"])
    return env, unit_a, unit_b, campaign, wo_a, wo_b


def test_verify_remediates_unit_and_recomputes_campaign_rate(api, officer_headers, admin_headers):
    """PRD §3.8: "On success the order moves to `VERIFIED` — terminal — and stamps `verified_at`; then, in the same request: the unit transitions from `CAMPAIGN_OPEN` to `REMEDIED` (unit `version` increments); the campaign's `verified_unit_count` increments by 1 and its `completion_rate` is recomputed (campaign `version` increments); if the campaign is in `COMPLETION_REVIEW` and the recomputed rate meets its threshold, the campaign closes as described below; and if that closure leaves the family with no other open campaign, the family exits `COMPLIANCE_HOLD` (family `version` increments)."

    Hop 1 and hop 2 of the cascade: the second verify moves UN-602 to REMEDIED
    and recomputes the campaign to verified 2 / notified 2 = rate 1.0.

    Design: Difficulty/transitive_cascade/work_order_verify_four_hop_close_releases_family
    """
    env, unit_a, unit_b, campaign, wo_a, wo_b = _campaign_one_verify_short_of_closing()
    validate_success(api.campaign_completion_review(campaign["id"], officer_headers))

    verified = verify_work_order(wo_b["id"])
    assert verified["status"] == "VERIFIED"

    unit_b_now = get_unit(unit_b["id"])
    assert_engine_unit(unit_b_now)
    assert unit_b_now["campaign_compliance"] == "REMEDIED", (
        f"hop 1: verify drives CAMPAIGN_OPEN -> REMEDIED, got {unit_b_now['campaign_compliance']}"
    )

    campaign_now = validate_success(api.get_field_campaign(campaign["id"], admin_headers))
    assert_field_campaign(campaign_now)
    assert campaign_now["verified_unit_count"] == 2, (
        f"hop 2: verified_unit_count increments to 2, got {campaign_now['verified_unit_count']}"
    )
    assert campaign_now["notified_unit_count"] == 2
    assert campaign_now["completion_rate"] == compute_completion_rate(2, 2), (
        f"hop 2: rate recomputed to 1.0, got {campaign_now['completion_rate']}"
    )


def test_verify_closes_campaign_and_releases_family_from_hold(api, officer_headers, admin_headers):
    """PRD §3.8: "Closure itself is the system transition from `COMPLETION_REVIEW` to `CLOSED`: in addition to the campaign's own `version` increment, if no other campaign of the same family sits in `ANNOUNCED`, `IN_PROGRESS`, or `COMPLETION_REVIEW`, the family exits `COMPLIANCE_HOLD` — to `IN_PRODUCTION` when `production_entered` is true, otherwise to `CERTIFIED`."
    PRD §3.2: "Symmetrically, when the family's last open campaign closes, the system moves the family out of `COMPLIANCE_HOLD`: to `IN_PRODUCTION` when `production_entered` is true, and back to `CERTIFIED` when it is false."

    Hop 3 and hop 4: the recomputed rate 1.0 meets the 0.95 threshold while the
    campaign sits in COMPLETION_REVIEW, so the campaign closes and — with no
    other open campaign — the family returns to IN_PRODUCTION.

    Design: Difficulty/transitive_cascade/work_order_verify_four_hop_close_releases_family
    """
    env, unit_a, unit_b, campaign, wo_a, wo_b = _campaign_one_verify_short_of_closing()
    validate_success(api.campaign_completion_review(campaign["id"], officer_headers))

    verify_work_order(wo_b["id"])

    campaign_now = validate_success(api.get_field_campaign(campaign["id"], admin_headers))
    assert campaign_now["status"] == "CLOSED", (
        f"hop 3: rate 1.0 >= 0.95 in COMPLETION_REVIEW closes the campaign, got {campaign_now['status']}"
    )

    family_now = get_family(env["family"]["id"])
    assert family_now["certification_status"] == "IN_PRODUCTION", (
        "hop 4: production_entered true and no other open campaign -> "
        f"IN_PRODUCTION, got {family_now['certification_status']}"
    )
    assert family_now["production_entered"] is True


# ---------------------------------------------------------------------------
# depth-3 cascade: grade REJECT -> reversal -> center SUSPENDED at count 2
# ---------------------------------------------------------------------------
def _two_received_orders_same_center():
    """Two units (UN-701/UN-702), each with a confirmed and core-received reman
    order quoting price 500000 / core 200000 -> provisional 120000 posted per
    confirm; the center ledger stands at 240000."""
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-701")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-702")
    set_logical_clock(ORDER_CLOCK)
    order_a = setup_reman_order_core_received(
        unit_a["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    order_b = setup_reman_order_core_received(
        unit_b["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    return env, order_a, order_b


def test_first_core_reject_reverses_provisional_credit(api, admin_headers):
    """PRD §3.9: "A grade of `REJECT` — defined as a 0.0 grade percentage — takes a different branch: the order moves to `CORE_REJECTED`, `final_core_credit_cents` is set to 0, the center's balance decreases by the full provisional credit, and the center's `core_reversal_count` increments by 1, all center mutations."
    PRD §3.6: "Suspension moves an `AUTHORIZED` center to `SUSPENDED`, and it happens in two ways: a `PlatformAdmin` may suspend a center directly, or the system suspends it as a side effect of the remanufacturing core-reversal cascade when the center's `core_reversal_count` reaches 2 (§3.9)."

    After the first REJECT the ledger falls from 240000 to 120000 and the
    reversal count reaches 1 — still below the suspension threshold, so the
    center remains AUTHORIZED.

    Design: Difficulty/transitive_cascade/core_reject_three_hop_suspends_center
    """
    env, order_a, order_b = _two_received_orders_same_center()
    center_id = env["center"]["id"]

    rejected_a = grade_core(order_a["id"], "REJECT")
    assert_reman_order(rejected_a)
    assert rejected_a["status"] == "CORE_REJECTED"
    assert rejected_a["final_core_credit_cents"] == 0

    center_now = validate_success(api.get_service_center(center_id, admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 120000, (
        "240000 posted minus the full 120000 provisional reversal = 120000, "
        f"got {center_now['core_credit_balance_cents']}"
    )
    assert center_now["core_reversal_count"] == 1, (
        f"first rejection increments the count to 1, got {center_now['core_reversal_count']}"
    )
    assert center_now["auth_status"] == "AUTHORIZED", (
        f"count 1 is below the suspension threshold 2, got {center_now['auth_status']}"
    )


def test_second_core_reject_suspends_service_center(api, admin_headers):
    """PRD §3.9: "When that count reaches 2, the center transitions from `AUTHORIZED` to `SUSPENDED` as a further system mutation of the same request — the reversal-suspension cascade that §3.6's reinstatement loop exists to reverse."

    The second REJECT reverses the second 120000 provisional (ledger back to
    exactly 0) and drives the reversal count to 2, suspending the center in the
    same request.

    Design: Difficulty/transitive_cascade/core_reject_three_hop_suspends_center
    """
    env, order_a, order_b = _two_received_orders_same_center()
    center_id = env["center"]["id"]
    grade_core(order_a["id"], "REJECT")

    rejected_b = grade_core(order_b["id"], "REJECT")
    assert_reman_order(rejected_b)
    assert rejected_b["status"] == "CORE_REJECTED"
    assert rejected_b["final_core_credit_cents"] == 0

    center_now = validate_success(api.get_service_center(center_id, admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 0, (
        f"both provisionals reversed: 240000 - 120000 - 120000 = 0, got {center_now['core_credit_balance_cents']}"
    )
    assert center_now["core_reversal_count"] == 2, (
        f"second rejection reaches the threshold, got {center_now['core_reversal_count']}"
    )
    assert center_now["auth_status"] == "SUSPENDED", (
        f"count 2 suspends the center, got {center_now['auth_status']}"
    )

    order_a_now = validate_success(api.get_reman_order(order_a["id"], admin_headers))
    assert order_a_now["status"] == "CORE_REJECTED", (
        "the first rejection is terminal and unaffected by the second"
    )
