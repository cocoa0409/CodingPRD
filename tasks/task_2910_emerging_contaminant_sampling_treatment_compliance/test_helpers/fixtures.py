"""Composite state builders and pytest fixtures.

The server is restarted before every test, so every fixture builds its state
from scratch through the documented endpoints. Nothing here reaches into a
database; the only way state comes into existence is an HTTP call.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    SAMPLING_TECHNICIAN_HEADERS,
    STATE_REGULATOR_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UTILITY_ADMIN_HEADERS,
    make_laboratory_manager_headers,
)

# Canonical collection and analysis instants per monitoring period. Each
# analysis sits five days after its collection, well inside the 336 hour
# holding time of METHOD_533, and each lands on its own UTC calendar day so a
# laboratory's daily capacity is never the reason a quarter fails.
QUARTER_COLLECTED_AT = {
    "2025Q1": "2025-02-14T08:00:00.000Z",
    "2025Q2": "2025-05-15T08:00:00.000Z",
    "2025Q3": "2025-08-15T08:00:00.000Z",
    "2025Q4": "2025-11-14T08:00:00.000Z",
    "2026Q1": "2026-02-13T08:00:00.000Z",
    "2026Q2": "2026-05-15T08:00:00.000Z",
    "2026Q3": "2026-07-15T08:00:00.000Z",
}
QUARTER_ANALYZED_AT = {
    "2025Q1": "2025-02-19T08:00:00.000Z",
    "2025Q2": "2025-05-20T08:00:00.000Z",
    "2025Q3": "2025-08-20T08:00:00.000Z",
    "2025Q4": "2025-11-19T08:00:00.000Z",
    "2026Q1": "2026-02-18T08:00:00.000Z",
    "2026Q2": "2026-05-20T08:00:00.000Z",
    "2026Q3": "2026-07-20T08:00:00.000Z",
}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock to `instant`."""
    return get_success_data(api.set_clock(f.clock_payload(instant), headers))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Return the logical clock to its documented default."""
    return set_clock(api, DEFAULT_CLOCK)


# ---------------------------------------------------------------------------
# Registry (tier 1)
# ---------------------------------------------------------------------------
def register_contaminant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_contaminant(f.contaminant_payload(**overrides), UTILITY_ADMIN_HEADERS)
    )


def register_hazard_member(api: ApiClient, code: str, hbwc_ng_per_l: float, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_contaminant(
            f.hazard_member_payload(code, hbwc_ng_per_l, **overrides), UTILITY_ADMIN_HEADERS
        )
    )


def register_laboratory(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_laboratory(f.laboratory_payload(**overrides), UTILITY_ADMIN_HEADERS)
    )


def register_entry_point(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_entry_point(f.entry_point_payload(**overrides), UTILITY_ADMIN_HEADERS)
    )


def build_registry(
    api: ApiClient,
    contaminant_overrides: Optional[Dict[str, Any]] = None,
    laboratory_overrides: Optional[Dict[str, Any]] = None,
    entry_point_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One contaminant, one laboratory and one entry point, plus lab headers."""
    contaminant = register_contaminant(api, **(contaminant_overrides or {}))
    laboratory = register_laboratory(api, **(laboratory_overrides or {}))
    entry_point = register_entry_point(api, **(entry_point_overrides or {}))
    return {
        "contaminant": contaminant,
        "contaminant_id": contaminant["id"],
        "laboratory": laboratory,
        "laboratory_id": laboratory["id"],
        "lab_headers": make_laboratory_manager_headers(laboratory["id"]),
        "entry_point": entry_point,
        "entry_point_id": entry_point["id"],
    }


# ---------------------------------------------------------------------------
# Sample custody chain (tiers 2 and 3)
# ---------------------------------------------------------------------------
def collect_sample(
    api: ApiClient,
    entry_point_id: str,
    panel_contaminant_ids: List[str],
    monitoring_period: str = "2026Q2",
    collected_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.sample_payload(
        entry_point_id,
        panel_contaminant_ids,
        monitoring_period=monitoring_period,
        collected_at=collected_at or QUARTER_COLLECTED_AT[monitoring_period],
        **overrides,
    )
    return get_success_data(api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS))


def ship_sample(api: ApiClient, sample_id: str, laboratory_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.ship_sample(sample_id, f.ship_sample_payload(laboratory_id), SAMPLING_TECHNICIAN_HEADERS)
    )


def receive_sample(api: ApiClient, sample_id: str, laboratory_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.receive_sample(
            sample_id,
            f.receive_sample_payload(**overrides),
            make_laboratory_manager_headers(laboratory_id),
        )
    )


def received_sample(
    api: ApiClient,
    entry_point_id: str,
    panel_contaminant_ids: List[str],
    laboratory_id: str,
    monitoring_period: str = "2026Q2",
    collected_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Collect, ship and cleanly receive one sample, leaving it in RECEIVED."""
    sample = collect_sample(
        api,
        entry_point_id,
        panel_contaminant_ids,
        monitoring_period=monitoring_period,
        collected_at=collected_at,
        **overrides,
    )
    ship_sample(api, sample["id"], laboratory_id)
    return receive_sample(api, sample["id"], laboratory_id)


def submit_result(
    api: ApiClient,
    laboratory_id: str,
    sample_id: str,
    contaminant_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.lab_result_payload(sample_id, contaminant_id, **overrides)
    return get_success_data(
        api.create_lab_result(payload, make_laboratory_manager_headers(laboratory_id))
    )


def accept_result(api: ApiClient, result_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.review_lab_result(
            result_id, f.accept_review_payload(), headers or COMPLIANCE_OFFICER_HEADERS
        )
    )


def reject_result(api: ApiClient, result_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.review_lab_result(
            result_id, f.reject_review_payload(**overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def accepted_quarter(
    api: ApiClient,
    registry: Dict[str, Any],
    monitoring_period: str,
    reported_ng_per_l: float,
    detection_limit_ng_per_l: float = 1.00,
    method: str = "METHOD_533",
    preservative_lot: Optional[str] = None,
    contaminant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive one quarter from collection to an accepted result.

    Returns the sample and the accepted result for that period.
    """
    target_contaminant = contaminant_id or registry["contaminant_id"]
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [target_contaminant],
        registry["laboratory_id"],
        monitoring_period=monitoring_period,
        preservative_lot=preservative_lot or f"LOT-{monitoring_period}",
    )
    result = submit_result(
        api,
        registry["laboratory_id"],
        sample["id"],
        target_contaminant,
        method=method,
        reported_ng_per_l=reported_ng_per_l,
        detection_limit_ng_per_l=detection_limit_ng_per_l,
        analyzed_at=QUARTER_ANALYZED_AT[monitoring_period],
    )
    accepted = accept_result(api, result["id"])
    return {"sample": sample, "sample_id": sample["id"], "result": accepted, "result_id": result["id"]}


def accepted_quarters(
    api: ApiClient,
    registry: Dict[str, Any],
    readings: List[Tuple[str, float]],
    detection_limit_ng_per_l: float = 1.00,
) -> List[Dict[str, Any]]:
    """Accept one result per period, oldest period first."""
    return [
        accepted_quarter(
            api,
            registry,
            period,
            reported,
            detection_limit_ng_per_l=detection_limit_ng_per_l,
        )
        for period, reported in readings
    ]


def entry_point_version(api: ApiClient, entry_point_id: str) -> int:
    """The entry point's current `version`, for the concurrency guard."""
    entry_point = get_success_data(api.get_entry_point(entry_point_id, COMPLIANCE_OFFICER_HEADERS))
    return entry_point["version"]


def read_entry_point(api: ApiClient, entry_point_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_entry_point(entry_point_id, COMPLIANCE_OFFICER_HEADERS))


def read_sample(api: ApiClient, sample_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sample(sample_id, COMPLIANCE_OFFICER_HEADERS))


def read_lab_result(api: ApiClient, result_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lab_result(result_id, COMPLIANCE_OFFICER_HEADERS))


def read_determination(api: ApiClient, determination_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_determination(determination_id, COMPLIANCE_OFFICER_HEADERS)
    )


def read_notification(api: ApiClient, notification_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_notification(notification_id, COMPLIANCE_OFFICER_HEADERS)
    )


def read_evaluation(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_treatment_evaluation(evaluation_id, TREATMENT_ENGINEER_HEADERS)
    )


def read_pilot(api: ApiClient, pilot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pilot_test(pilot_id, TREATMENT_ENGINEER_HEADERS))


def read_manifest(api: ApiClient, manifest_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_residuals_manifest(manifest_id, TREATMENT_ENGINEER_HEADERS)
    )


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capital_project(project_id, FINANCE_OFFICER_HEADERS))


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_funding_application(application_id, FINANCE_OFFICER_HEADERS)
    )


def read_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_cost_recovery_claim(claim_id, FINANCE_OFFICER_HEADERS)
    )


# ---------------------------------------------------------------------------
# Determinations and notifications (tier 5)
# ---------------------------------------------------------------------------
def draft_determination(
    api: ApiClient,
    entry_point_id: str,
    contaminant_id: str,
    period_end: str = "2026Q2",
    expected_entry_point_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    version = (
        expected_entry_point_version
        if expected_entry_point_version is not None
        else entry_point_version(api, entry_point_id)
    )
    payload = f.determination_payload(entry_point_id, contaminant_id, version, period_end=period_end)
    return get_success_data(
        api.create_determination(payload, headers or COMPLIANCE_OFFICER_HEADERS)
    )


def issue_determination(api: ApiClient, determination_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.issue_determination(determination_id, {}, headers or COMPLIANCE_OFFICER_HEADERS)
    )


def notification_of(api: ApiClient, determination_id: str) -> Dict[str, Any]:
    """The notification the issuance cascade opened for a determination."""
    response = api.list_notifications(
        COMPLIANCE_OFFICER_HEADERS, params={"determination_id": determination_id}
    )
    rows = get_success_data(response)
    assert len(rows) == 1, f"Expected exactly one notification, got {len(rows)}"
    return rows[0]


def issued_violation(
    api: ApiClient,
    registry: Dict[str, Any],
    reported_ng_per_l: float = 20.00,
    period: str = "2026Q2",
) -> Dict[str, Any]:
    """One accepted exceedance, drafted and issued, with its notification."""
    quarter = accepted_quarter(api, registry, period, reported_ng_per_l)
    determination = draft_determination(
        api, registry["entry_point_id"], registry["contaminant_id"], period_end=period
    )
    issued = issue_determination(api, determination["id"])
    return {
        "quarter": quarter,
        "determination": issued,
        "determination_id": issued["id"],
        "notification": notification_of(api, issued["id"]),
    }


# ---------------------------------------------------------------------------
# Treatment evaluation, pilots and selection (tiers 2 to 5)
# ---------------------------------------------------------------------------
def open_evaluation(api: ApiClient, entry_point_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_treatment_evaluation(
            f.treatment_evaluation_payload(entry_point_id, **overrides),
            TREATMENT_ENGINEER_HEADERS,
        )
    )


def register_pilot(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_pilot_test(payload, TREATMENT_ENGINEER_HEADERS))


def start_pilot(api: ApiClient, pilot_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_pilot_test(pilot_id, {}, TREATMENT_ENGINEER_HEADERS))


def complete_pilot(api: ApiClient, pilot_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.complete_pilot_test(
            pilot_id, f.complete_pilot_payload(**overrides), TREATMENT_ENGINEER_HEADERS
        )
    )


def completed_gac_pilot(api: ApiClient, evaluation_id: str, **overrides: Any) -> Dict[str, Any]:
    """A GAC skid run in its May 2026 window: removal 96.30 on 800.00 kg."""
    pilot = register_pilot(api, f.gac_pilot_payload(evaluation_id, **overrides))
    start_pilot(api, pilot["id"])
    return complete_pilot(
        api, pilot["id"], influent_ng_per_l=50.00, effluent_ng_per_l=1.85, spent_media_kg=800.00
    )


def completed_ix_pilot(api: ApiClient, evaluation_id: str, **overrides: Any) -> Dict[str, Any]:
    """An IX skid run in its May 2026 window: removal 92.00 on 300.00 kg."""
    pilot = register_pilot(api, f.ix_pilot_payload(evaluation_id, **overrides))
    start_pilot(api, pilot["id"])
    return complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=4.00,
        bed_volumes_treated=18000.00,
        spent_media_kg=300.00,
    )


def piloted_evaluation(api: ApiClient, entry_point_id: str, **evaluation_overrides: Any) -> Dict[str, Any]:
    """An evaluation with the GAC and IX skids both completed."""
    evaluation = open_evaluation(api, entry_point_id, **evaluation_overrides)
    gac = completed_gac_pilot(api, evaluation["id"])
    ix = completed_ix_pilot(api, evaluation["id"])
    return {
        "evaluation": evaluation,
        "evaluation_id": evaluation["id"],
        "gac": gac,
        "gac_id": gac["id"],
        "ix": ix,
        "ix_id": ix["id"],
    }


def select_technology(api: ApiClient, evaluation_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.decide_treatment_evaluation(
            evaluation_id, f.evaluation_decision_payload(**overrides), TREATMENT_ENGINEER_HEADERS
        )
    )


def project_of_evaluation(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    response = api.list_capital_projects(
        FINANCE_OFFICER_HEADERS, params={"treatment_evaluation_id": evaluation_id}
    )
    rows = get_success_data(response)
    assert len(rows) == 1, f"Expected exactly one capital project, got {len(rows)}"
    return rows[0]


def selected_project(api: ApiClient, entry_point_id: str, **evaluation_overrides: Any) -> Dict[str, Any]:
    """The full treatment chain through selection, returning the capital project."""
    piloted = piloted_evaluation(api, entry_point_id, **evaluation_overrides)
    select_technology(api, piloted["evaluation_id"])
    project = project_of_evaluation(api, piloted["evaluation_id"])
    piloted["project"] = project
    piloted["project_id"] = project["id"]
    return piloted


# ---------------------------------------------------------------------------
# Residuals
# ---------------------------------------------------------------------------
def raise_manifest(api: ApiClient, pilot_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_residuals_manifest(
            f.manifest_payload(pilot_id, **overrides), TREATMENT_ENGINEER_HEADERS
        )
    )


def classify_manifest(api: ApiClient, manifest_id: str, leachate_pfas_ng_per_l: float) -> Dict[str, Any]:
    return get_success_data(
        api.classify_residuals_manifest(
            manifest_id,
            f.classify_manifest_payload(leachate_pfas_ng_per_l),
            STATE_REGULATOR_HEADERS,
        )
    )


def ship_manifest(api: ApiClient, manifest_id: str, disposal_method: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.ship_residuals_manifest(
            manifest_id,
            f.ship_manifest_payload(disposal_method, **overrides),
            TREATMENT_ENGINEER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Capital finance
# ---------------------------------------------------------------------------
def apply_for_funding(api: ApiClient, project_id: str, **overrides: Any) -> Dict[str, Any]:
    version = read_project(api, project_id)["version"]
    return get_success_data(
        api.create_funding_application(
            project_id, f.funding_application_payload(version, **overrides), FINANCE_OFFICER_HEADERS
        )
    )


def award_funding(api: ApiClient, application_id: str, awarded_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.decide_funding_application(
            application_id, f.award_payload(awarded_cents), STATE_REGULATOR_HEADERS
        )
    )


def awarded_funding(api: ApiClient, project_id: str, amount_requested_cents: int, awarded_cents: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    """An application submitted and awarded in one step."""
    application = apply_for_funding(
        api, project_id, amount_requested_cents=amount_requested_cents, **overrides
    )
    return award_funding(
        api, application["id"], awarded_cents if awarded_cents is not None else amount_requested_cents
    )


def open_claim(api: ApiClient, entry_point_id: str, project_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_cost_recovery_claim(
            f.cost_recovery_claim_payload(entry_point_id, project_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def file_claim(api: ApiClient, claim_id: str, claimed_cents: int = 900000000) -> Dict[str, Any]:
    return get_success_data(
        api.file_cost_recovery_claim(
            claim_id, f.file_claim_payload(claimed_cents), COMPLIANCE_OFFICER_HEADERS
        )
    )


def filed_claim(api: ApiClient, entry_point_id: str, project_id: str, claimed_cents: int = 900000000, **overrides: Any) -> Dict[str, Any]:
    claim = open_claim(api, entry_point_id, project_id, **overrides)
    return file_claim(api, claim["id"], claimed_cents)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def registry(api: ApiClient) -> Dict[str, Any]:
    """PFOA, one certified laboratory and entry point EPTDS-01."""
    return build_registry(api)


@pytest.fixture
def entry_point(api: ApiClient) -> Dict[str, Any]:
    """Entry point EPTDS-01 at a population of 45,000."""
    return register_entry_point(api)
