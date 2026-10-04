"""Difficulty tests: dual-variant calculations — severity scoring and reputation variants."""
import pytest

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_validated_report,
    get_researcher,
    resolve_report,
    set_clock,
    setup_active_program,
    register_researcher,
    submit_report,
)


def test_severity_base_vs_environmental_divergence_values(api):
    """PRD §3.7: "The base score is a weighted blend — half of `impact`, three
    tenths of `exploitability`, and one fifth of `affected_scope` — rounded half-up
    to one decimal place and stored as `severity_score_base`; this is the unadjusted,
    CVSS-like figure reported to researchers."
    PRD §3.7: "The environmental score multiplies the base by an asset-criticality
    factor — 1.2 for `CRITICAL`, 1.1 for `HIGH`, 1.0 for `MEDIUM`, and 0.8 for `LOW`
    — and then by the program's `exposure_modifier`, again rounded half-up to one
    decimal place, stored as `severity_score_adjusted`."

    Design: Difficulty/dual_variant_calc/severity_base_vs_environmental_divergence
    """
    program, asset = setup_active_program(exposure_modifier=1.0)
    researcher = register_researcher()
    report = submit_report(program, asset, researcher, vulnerability_class="RCE")
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    validated = get_success_data(api.validate_report(
        report["id"],
        {"impact": 9, "exploitability": 8, "affected_scope": 5},
        TRIAGER,
    ))
    # base = 0.5*9 + 0.3*8 + 0.2*5 = 7.9; adjusted = 7.9 * 1.2 * 1.0 = 9.48 -> 9.5
    assert validated["severity_score_base"] == pytest.approx(7.9, abs=1e-9)
    assert validated["severity_score_adjusted"] == pytest.approx(9.5, abs=1e-9)
    assert validated["status"] == "VALIDATED"


def test_severity_final_bands_from_adjusted_variant_only(api):
    """PRD §3.7: "The final severity `severity_final` is banded from the
    environmental score alone: `CRITICAL` at 9.0 or above, `HIGH` at 7.0 or above,
    `MEDIUM` at 4.0 or above, `LOW` at 0.1 or above, and `NONE` only when the
    adjusted score is exactly 0.0 — every band threshold inclusive."
    PRD §3.7: "Because the environmental variant can band higher than the raw base,
    the two stored figures may disagree, and it is always the adjusted figure that
    drives severity-banded behavior such as resolution bounties and reputation."

    Design: Difficulty/dual_variant_calc/severity_base_vs_environmental_divergence
    """
    program, asset = setup_active_program(exposure_modifier=1.0)
    researcher = register_researcher()
    report = submit_report(program, asset, researcher, vulnerability_class="RCE")
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    validated = get_success_data(api.validate_report(
        report["id"],
        {"impact": 9, "exploitability": 8, "affected_scope": 5},
        TRIAGER,
    ))
    # raw base 7.9 would band HIGH; the adjusted 9.5 bands CRITICAL
    assert validated["severity_score_base"] == pytest.approx(7.9, abs=1e-9)
    assert validated["severity_final"] == "CRITICAL"


def _setup_researcher_with_critical_resolution(clock, resolution_time):
    """ACTIVE program (min_reputation 150) + researcher whose CRITICAL report is
    RESOLVED at `resolution_time`. Returns (program, researcher)."""
    set_clock(clock)
    program, asset = setup_active_program(
        clock=clock, min_reputation=150, effective_from="2026-01-01T00:00:00Z")
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    resolve_report(report["id"])
    return program, researcher


def test_reputation_lifetime_vs_rolling180_divergence_values(api):
    """PRD §3.3: "`reputation_lifetime` is 100 plus the sum of all unreversed
    deltas, floored at zero; it never expires deltas and governs invitation
    eligibility and the `reputation_at_issue` snapshot."
    PRD §3.3: "`reputation_rolling180` is 100 plus the sum of unreversed deltas
    whose `occurred_at` is within the trailing 180 days — the boundary instant
    itself counts as inside the window — floored at zero; it drives the
    researcher's `tier`"

    Design: Difficulty/dual_variant_calc/reputation_lifetime_vs_rolling180_divergence
    """
    program, researcher = _setup_researcher_with_critical_resolution(
        "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    set_clock("2026-09-01T00:00:00Z")
    refreshed = get_researcher(researcher["id"])
    # +100 CRITICAL delta earned 2026-01-01: lifetime keeps it, rolling180 drops it
    assert refreshed["reputation_lifetime"] == 200
    assert refreshed["reputation_rolling180"] == 100
    assert refreshed["tier"] == "NOVICE"


def test_reputation_lifetime_governs_invitation_eligibility(api):
    """PRD §3.3: "`reputation_lifetime` ... never expires deltas and governs
    invitation eligibility and the `reputation_at_issue` snapshot."
    PRD §3.4: "requires the researcher's `reputation_lifetime` to be at least the
    program's `min_reputation`, where equality passes and only a strictly lower
    reputation is rejected with `ERR_REPUTATION_TOO_LOW`."

    Design: Difficulty/dual_variant_calc/reputation_lifetime_vs_rolling180_divergence
    """
    program, researcher = _setup_researcher_with_critical_resolution(
        "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    set_clock("2026-09-01T00:00:00Z")
    refreshed = get_researcher(researcher["id"])
    assert refreshed["reputation_lifetime"] == 200
    assert refreshed["reputation_rolling180"] == 100
    # lifetime 200 >= min_reputation 150 -> invitation issuance succeeds
    resp = api.create_invitation(
        {"program_id": program["id"], "researcher_id": researcher["id"]}, PROGRAM_ADMIN)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
