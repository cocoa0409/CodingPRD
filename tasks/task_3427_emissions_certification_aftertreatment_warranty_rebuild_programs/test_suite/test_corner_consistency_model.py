"""Corner coverage — consistency model (PRD §2.9 cascade semantics, §3.8
verification cascade): a mutating response and the immediately following
reads observe the same post-cascade state with no settling delay.

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    complete_work_order,
    get_unit,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_full_environment,
    stamp_family_non_conforming,
    start_work_order,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_verify_mutation_immediately_visible_across_reads(api, officer_headers):
    """PRD §3.8: "On success the order moves to `VERIFIED` — terminal — and stamps `verified_at`; then, in the same request: the unit transitions from `CAMPAIGN_OPEN` to `REMEDIED` (unit `version` increments); the campaign's `verified_unit_count` increments by 1 and its `completion_rate` is recomputed (campaign `version` increments)"
    PRD §2.9: "Many operations in this system mutate more than one resource atomically inside a single request"

    Immediate consistency: the verify response itself carries VERIFIED, and
    the very next reads of the unit and campaign already reflect the cascade
    (REMEDIED, verified_unit_count 1) with no settling delay.

    Design: Corner/consistency_model/verify_mutation_immediately_visible_across_reads
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CG")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"]
    )
    start_work_order(work_order["id"], center_id)
    complete_work_order(work_order["id"], center_id)

    set_logical_clock("2026-12-15T00:00:00Z")
    verified = validate_success(api.verify_work_order(work_order["id"], officer_headers))
    assert verified["status"] == "VERIFIED"
    assert _dt(verified["verified_at"]) == _dt("2026-12-15T00:00:00Z"), (
        f"verified_at is stamped from the logical clock, got {verified['verified_at']}"
    )

    unit_now = get_unit(unit["id"])
    assert unit_now["campaign_compliance"] == "REMEDIED", (
        f"the unit read immediately reflects the cascade, got {unit_now['campaign_compliance']}"
    )

    campaign_now = validate_success(api.get_field_campaign(campaign["id"], officer_headers))
    assert campaign_now["verified_unit_count"] == 1, (
        f"the campaign read immediately reflects the cascade, got {campaign_now['verified_unit_count']}"
    )
