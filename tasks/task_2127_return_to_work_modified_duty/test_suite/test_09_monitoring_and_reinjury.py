"""Workplace monitoring, supervisor accountability and the surveillance risk variant."""
from test_helpers import (
    assert_compliance_audit,
    assert_placement_dimensions_independent,
    create_placement_payload,
    fixtures,
    validate_paginated,
    validate_success,
)


def test_a_monitoring_observation_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "Three record types are deliberate exceptions because they are append-only observations rather than mutable state: `ComplianceAudit`, `WageDifferentialEntry` and `CaseReviewVote` carry only `id` and `created_at`. For those three, `updated_at` and `version` are absent entirely"
    PRD §3.8: "Monitoring observations are filed against a placement by the hosting supervisor, a coordinator, a nurse or an administrator, and they are append-only: a `ComplianceAudit` carries only an `id` and a `created_at`, never an `updated_at` or a `version`."

    Design: Corner/entities/compliance_audit_is_immutable_and_carries_no_version
    """
    ctx = fixtures.setup_active_placement()
    fixtures.file_compliance_audit(
        ctx, observed_on="2026-08-01", finding_severity="MINOR", finding_code="DOCUMENTATION"
    )

    data, _ = validate_paginated(
        api.list_compliance_audits(ctx["placement_id"], fixtures.COORD)
    )

    assert len(data) == 1
    assert data[0]["finding_severity"] == "MINOR"
    assert_compliance_audit(data[0])
    assert "version" not in data[0]
    assert "updated_at" not in data[0]


def test_the_baseline_score_is_pinned_at_creation_without_observed_events(api):
    """PRD §3.4: "At creation the placement is scored under the `BASELINE` variant, which consists of the structural term alone, evaluated against the restriction set named by the placement's own `restriction_set_id`; no monitoring observation and no reinjury report participates, because none exists yet. Whatever the variant, the result is clamped into the range from 0 to 100 and rounded half up to a whole number."

    Design: Difficulty/dual_variant_calc/reinjury_risk_baseline_vs_surveillance_diverge_on_same_placement
    """
    ctx = fixtures.setup_active_restriction_set()

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert data["reinjury_risk_variant"] == "BASELINE"
    assert data["reinjury_risk_score"] == 54, (
        f"LOW base 12 + 0.45 * severity 60 + 22.0 * 0.6667 rounds to 54, got "
        f"{data['reinjury_risk_score']}"
    )


def test_the_surveillance_variant_adds_the_observed_term_after_the_first_finding(api):
    """PRD §3.8: "Under `SURVEILLANCE` the score is the structural term of §3.4 *plus* an observed term"
    PRD §3.8: "The first walks every monitoring observation of the placement, ordered by `observed_on` ascending and then by `created_at` ascending, and for each one takes its severity points — 0 for `NONE`, 4 for `MINOR`, 11 for `MAJOR`, 25 for `CRITICAL` — multiplied by a decay factor."
    PRD §3.8: "A move into `WATCH` recomputes the supervisor's `compliance_strike_points` and `effective_strike_points`, recomputes the placement's `reinjury_risk_score` under the `SURVEILLANCE` variant, and recomputes the claim's `rtw_posture`, which lands on `RESTRICTED`."

    Design: Difficulty/dual_variant_calc/reinjury_risk_baseline_vs_surveillance_diverge_on_same_placement
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-05T00:00:00Z")

    fixtures.file_compliance_audit(
        ctx, observed_on="2026-08-04", finding_severity="MAJOR",
        finding_code="HOURS_DEVIATION", restriction_deviation_detected=False,
        corrective_action_note="Coached on break cadence",
    )

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["reinjury_risk_score"] == 65, (
        f"one undecayed MAJOR finding adds 11 to the 53.6667 structural term, got "
        f"{placement['reinjury_risk_score']}"
    )
    assert placement["reinjury_risk_variant"] == "SURVEILLANCE"
    assert_placement_dimensions_independent(placement, "ACTIVE", "WATCH")
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "RESTRICTED"


def test_observation_points_halve_after_one_thirty_day_block(api):
    """PRD §3.8: "That decay factor is 1 minus one half for each whole 30-day block that has elapsed between the observation's `observed_on` and the logical clock's calendar date, where the elapsed day count is floored at zero before the block count is taken and the block count is itself rounded down; the resulting factor is clamped into the range from 0 to 1, so an observation more than 60 days old contributes nothing."

    Design: Corner/calculations/audit_points_decay_by_half_after_thirty_days
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-09-10T00:00:00Z")

    fixtures.file_compliance_audit(
        ctx, observed_on="2026-08-05", finding_severity="MAJOR", finding_code="HOURS_DEVIATION"
    )

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["reinjury_risk_score"] == 59, (
        f"36 days back is one whole block, so the MAJOR finding contributes 5.5 rather "
        f"than 11, got {placement['reinjury_risk_score']}"
    )
    assert placement["reinjury_risk_variant"] == "SURVEILLANCE"


def test_a_critical_finding_drives_the_placement_noncompliant_and_scores_the_supervisor(api):
    """PRD §3.8: "From `WATCH`, a finding of `MAJOR` or `CRITICAL` moves it `WATCH → NONCOMPLIANT`."
    PRD §3.3: "`compliance_strike_points` totals the strike weight of every monitoring observation ever filed against a placement this supervisor hosts, where a finding of `NONE` or `MINOR` is worth no points, a `MAJOR` finding is worth 1 point, and a `CRITICAL` finding is worth 2 points."
    PRD §3.3: "`effective_strike_points` is the greater of zero and the difference between `compliance_strike_points` and `strike_forgiveness_points`, and it is the figure the suspension threshold actually reads."

    Design: Difficulty/transitive_cascade/critical_audit_supervisor_suspension_job_pause_cascade_depth_three
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-05T00:00:00Z")

    fixtures.drive_supervisor_to_suspension(ctx)

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["compliance_status"] == "NONCOMPLIANT"
    assert placement["reinjury_risk_score"] == 90, (
        f"an undecayed MAJOR (11) and CRITICAL (25) add to the 53.6667 structural term, "
        f"got {placement['reinjury_risk_score']}"
    )
    supervisor = validate_success(api.get_supervisor(ctx["supervisor_id"], fixtures.ADMIN))
    assert supervisor["compliance_strike_points"] == 3
    assert supervisor["effective_strike_points"] == 3


def test_the_supervisors_suspension_pauses_their_job_bank_entry(api):
    """PRD §3.8: "The third, caused by the second, flips every transitional job of that supervisor whose `job_status` is `OPEN` to `PAUSED`, and flips every *other* placement of that supervisor whose `placement_status` is `ACTIVE` or `PROGRESSION_HOLD` and whose `compliance_status` is `COMPLIANT` to `WATCH`."
    PRD §3.8: "The second, caused by the first, recomputes the hosting supervisor's `compliance_strike_points` and, when their `effective_strike_points` has reached the suspension threshold of 2 points or more, flips that supervisor's `oversight_status` from `ACTIVE` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/critical_audit_supervisor_suspension_job_pause_cascade_depth_three
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-05T00:00:00Z")

    fixtures.drive_supervisor_to_suspension(ctx)

    supervisor = validate_success(api.get_supervisor(ctx["supervisor_id"], fixtures.ADMIN))
    assert supervisor["oversight_status"] == "SUSPENDED"
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert job["job_status"] == "PAUSED"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "RESTRICTED"
