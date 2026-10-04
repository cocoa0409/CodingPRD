"""Tax credit qualification: establishment, dual continuity variants, lapse,
and the cure window."""
import pytest

from test_helpers import (
    ApiErrorId,
    certify_milestone,
    create_certified_continuous_work,
    create_project,
    establish_tcq,
    get_project,
    get_success_data,
    get_tcq,
    safe_harbor_project,
    set_clock,
    validate_error,
    validate_success,
)


def _build_project_with_qualified_order(name, **order_kwargs):
    project = create_project(name=name, technology="SOLAR", target_capacity_mw=80,
                             resource_class="B")
    safe_harbor_project(project["id"], order_amount_usd=2500000,
                        safe_harbor_method="FIVE_PERCENT_COST",
                        eligible_cost_basis_usd=2500000,
                        deposit_usd=200000.00, **order_kwargs)
    return project


def test_continuity_four_year_vs_facts_circumstances_diverge(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "Under the `FOUR_YEAR_SAFE_HARBOR` variant the assessment
    passes if and only if the logical clock is at or before the
    `safe_harbor_established_date` plus four years — a 1461-day window
    inclusive of one leap day — or the project itself already sits in
    `COMMERCIAL_OPERATION` or `OPERATIONAL`; internal work gaps are never
    examined under this variant. Under the `FACTS_AND_CIRCUMSTANCES` variant
    the calendar deadline is irrelevant: the assessment builds a date series
    consisting of the `safe_harbor_established_date`, then each certified
    continuous-work milestone's `work_date` in order, then the current logical
    clock reading, and passes if and only if every consecutive gap in that
    series is at most 365 days. The same work history and clock can therefore
    pass under one variant and lapse under the other. A failed assessment does
    not merely reject: the qualification auto-transitions into
    `CONTINUITY_LAPSED`, its `lapse_date` is stamped from the logical clock,
    its `lapse_count` increments by one, and the caller receives
    `ERR_CONTINUITY_LAPSED` (HTTP 409)."

    Design: Difficulty/dual_variant_calc/continuity_four_year_vs_facts_circumstances_diverge
    """
    px = _build_project_with_qualified_order("Four Year Farm")
    py = _build_project_with_qualified_order("Facts Farm")
    # Both establish safe harbor at 2026-12-01.
    set_clock("2026-12-01T00:00:00Z")
    tcq_x = establish_tcq(px["id"], "FOUR_YEAR_SAFE_HARBOR")
    tcq_y = establish_tcq(py["id"], "FACTS_AND_CIRCUMSTANCES")
    # One certified continuous-work milestone each, work_date 2027-06-01.
    create_certified_continuous_work(px["id"], 1, "2027-06-01T00:00:00Z")
    create_certified_continuous_work(py["id"], 1, "2027-06-01T00:00:00Z")
    # Clock 2030-06-01: within 2026-12-01 + 1461 days (2030-12-01), but the
    # gap 2027-06-01 -> 2030-06-01 is 1096 days > 365.
    set_clock("2030-06-01T00:00:00Z")
    maintained = get_success_data(
        api.transition_tax_credit_qualification(
            tcq_x["id"], {"to": "CONTINUITY_MAINTAINED"}, tax_counsel_headers
        )
    )
    assert maintained["status"] == "CONTINUITY_MAINTAINED"

    resp = api.transition_tax_credit_qualification(
        tcq_y["id"], {"to": "CONTINUITY_MAINTAINED"}, tax_counsel_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUITY_LAPSED)
    tcq_y_now = get_success_data(
        api.get_tax_credit_qualification(tcq_y["id"], tax_counsel_headers)
    )
    assert tcq_y_now["status"] == "CONTINUITY_LAPSED"
    assert tcq_y_now["lapse_count"] == 1


def test_facts_and_circumstances_passes_with_tight_gaps(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "Under the `FACTS_AND_CIRCUMSTANCES` variant the calendar
    deadline is irrelevant: the assessment builds a date series consisting of
    the `safe_harbor_established_date`, then each certified continuous-work
    milestone's `work_date` in order, then the current logical clock reading,
    and passes if and only if every consecutive gap in that series is at most
    365 days."

    Design: Difficulty/dual_variant_calc/continuity_four_year_vs_facts_circumstances_diverge
    """
    project = _build_project_with_qualified_order("Facts Tight Farm")
    pid = project["id"]
    set_clock("2026-12-01T00:00:00Z")
    tcq = establish_tcq(pid, "FACTS_AND_CIRCUMSTANCES")
    # Gaps: 2026-12-01 -> 2027-06-01 (182d) -> 2027-12-01 (183d) -> clock
    # 2028-03-01 (91d): all <= 365.
    create_certified_continuous_work(pid, 1, "2027-06-01T00:00:00Z")
    create_certified_continuous_work(pid, 2, "2027-12-01T00:00:00Z")
    set_clock("2028-03-01T00:00:00Z")
    maintained = get_success_data(
        api.transition_tax_credit_qualification(
            tcq["id"], {"to": "CONTINUITY_MAINTAINED"}, tax_counsel_headers
        )
    )
    assert maintained["status"] == "CONTINUITY_MAINTAINED"


def test_cure_window_expiry_disqualifies(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "Cure from `CONTINUITY_LAPSED` requires two conditions. The
    logical clock must be at or before the `lapse_date` plus 90 days — a cure
    attempted after that window fails with `ERR_CURE_WINDOW_EXPIRED` (HTTP 422)
    and the failed attempt itself pushes the qualification into terminal
    `DISQUALIFIED`, which also sets the project's `tax_credit_anchored` to
    false and ends all further qualification for the project."

    Design: Corner/state_machines/cure_window_expiry_disqualifies
    """
    project = _build_project_with_qualified_order("Cure Farm")
    pid = project["id"]
    set_clock("2026-12-01T00:00:00Z")
    tcq = establish_tcq(pid, "FACTS_AND_CIRCUMSTANCES")
    create_certified_continuous_work(pid, 1, "2027-06-01T00:00:00Z")
    # Lapse at 2030-06-01 (gap 1096 > 365).
    set_clock("2030-06-01T00:00:00Z")
    lapse = api.transition_tax_credit_qualification(
        tcq["id"], {"to": "CONTINUITY_MAINTAINED"}, tax_counsel_headers
    )
    validate_error(lapse, ApiErrorId.ERR_CONTINUITY_LAPSED)
    # Fresh certified work after the lapse date exists, but the clock is
    # 137 days past the lapse: beyond lapse_date + 90 days.
    create_certified_continuous_work(pid, 2, "2030-06-15T00:00:00Z")
    set_clock("2030-10-15T00:00:00Z")
    cure = api.transition_tax_credit_qualification(
        tcq["id"], {"to": "CURED"}, tax_counsel_headers
    )
    validate_error(cure, ApiErrorId.ERR_CURE_WINDOW_EXPIRED)
    tcq_now = get_success_data(
        api.get_tax_credit_qualification(tcq["id"], tax_counsel_headers)
    )
    assert tcq_now["status"] == "DISQUALIFIED"
    assert tcq_now["lapse_count"] == 1
    assert get_project(pid)["tax_credit_anchored"] is False


def test_establish_requires_safe_harbor_qualified_order(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "A `TaxCounsel` establishes safe harbor — moving the
    qualification from `NOT_ELIGIBLE` to `SAFE_HARBOR_ESTABLISHED` — once at
    least one procurement order of the project is in `SAFE_HARBOR_QUALIFIED`,
    `DELIVERED`, or `ACCEPTED` (otherwise `ERR_SAFE_HARBOR_NOT_QUALIFIED`, HTTP
    409), and the transition payload must carry the `continuity_variant`
    (omitting it fails with `ERR_VALIDATION`, HTTP 400)."

    Design: Corner/state_machines/cure_window_expiry_disqualifies
    """
    project = create_project(name="Anchorless Farm", technology="SOLAR",
                             target_capacity_mw=50)
    tcq = get_tcq(project["id"])
    resp = api.transition_tax_credit_qualification(
        tcq["id"],
        {"to": "SAFE_HARBOR_ESTABLISHED", "continuity_variant": "FOUR_YEAR_SAFE_HARBOR"},
        tax_counsel_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_HARBOR_NOT_QUALIFIED)
