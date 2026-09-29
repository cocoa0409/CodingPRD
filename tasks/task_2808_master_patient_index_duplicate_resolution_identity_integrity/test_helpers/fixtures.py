"""Composite setup helpers.

Every helper here builds its preconditions exclusively through documented
endpoints, so each test starts from an empty database and walks the same
lifecycle a real caller would.

The tiers are:
  1. primitives           - clock, sites, rule sets, downstream systems
  2. entity hierarchy     - patient records and scoring couples
  3. lifecycle shortcuts  - candidate pair ladders up to a recommendation
  4. accumulation targets - merges, propagation tasks, remediations
  5. terminal states      - completed merges, closed remediations, fraud holds
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import MpiApiClient
from .assertions import assert_created, assert_ok, list_rows
from .constants import (
    ATTRIBUTION_CREATION_SITE,
    DEFAULT_CLOCK_UTC,
    OUTCOME_SAME_PERSON,
    OVERLAY_DEMOGRAPHIC_OVERWRITE,
    PROPAGATION_MODE_BATCH,
    RECOMMENDATION_MERGE,
    SCORE_VARIANT_STRICT,
    TRIGGER_MANUAL,
)
from . import factories as f
from .test_users import (
    admin_headers,
    analyst_headers,
    make_site_registrar_headers,
    officer_headers,
    steward_headers,
)


# ─────────────────────────────────────────────────────
# Tier 1 - primitives
# ─────────────────────────────────────────────────────
def pin_clock(client: MpiApiClient, current_utc: str = DEFAULT_CLOCK_UTC) -> None:
    """Pin the service's logical clock before any other call."""
    response = client.set_clock(current_utc, admin_headers())
    assert response.status_code == 200, (
        f"pinning the clock to {current_utc} failed: {response.status_code} "
        f"{response.text}"
    )


def create_site(
    client: MpiApiClient,
    site_code: str,
    name: str = "Central Registration",
    region_code: str = "MW-01",
    registrar_headcount: int = 4,
) -> Dict[str, Any]:
    response = client.create_site(
        f.site_payload(site_code, name, region_code, registrar_headcount),
        admin_headers(),
    )
    return assert_created(response)


def create_rule_set(
    client: MpiApiClient,
    activate: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Mint a rule set, optionally activating it."""
    response = client.create_rule_set(f.rule_set_payload(**overrides), admin_headers())
    rule_set = assert_created(response)
    if activate:
        rule_set = assert_ok(client.activate_rule_set(rule_set["id"], admin_headers()))
    return rule_set


def create_system(
    client: MpiApiClient,
    system_code: str,
    name: str = "Downstream Consumer",
    propagation_mode: str = PROPAGATION_MODE_BATCH,
    ack_required: bool = True,
    max_concurrent_dispatch: int = 1,
) -> Dict[str, Any]:
    response = client.create_system(
        f.system_payload(
            system_code, name, propagation_mode, ack_required, max_concurrent_dispatch
        ),
        admin_headers(),
    )
    return assert_created(response)


# ─────────────────────────────────────────────────────
# Tier 2 - patient records and scoring couples
# ─────────────────────────────────────────────────────
def create_record(
    client: MpiApiClient,
    site_id: str,
    mrn: str,
    last_name: str = "Nakamura",
    first_name: str = "Haruto",
    dob: str = "1984-02-19",
    sex: str = "M",
    headers: Optional[Dict[str, str]] = None,
    **optional: Any,
) -> Dict[str, Any]:
    payload = f.record_payload(
        site_id, mrn, last_name, first_name, dob, sex,
        **{key: value for key, value in optional.items()},
    )
    response = client.create_record(payload, headers or analyst_headers())
    return assert_created(response)


def create_identical_couple(
    client: MpiApiClient,
    site_id: str,
    mrn_a: str,
    mrn_b: str,
    last_name: str = "Okonkwo",
    first_name: str = "Chidi",
    dob: str = "1979-11-04",
    sex: str = "M",
    ssn_last4: str = "5521",
    postal_code: str = "30301",
    phone: str = "4045550133",
    elements_a: int = 0,
    elements_b: int = 0,
    **extra: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Two records agreeing on all seven scored attributes (raw score 100.00)."""
    record_a = create_record(
        client, site_id, mrn_a, last_name, first_name, dob, sex,
        ssn_last4=ssn_last4, postal_code=postal_code, phone=phone,
        clinical_element_count=elements_a, **extra,
    )
    record_b = create_record(
        client, site_id, mrn_b, last_name, first_name, dob, sex,
        ssn_last4=ssn_last4, postal_code=postal_code, phone=phone,
        clinical_element_count=elements_b, **extra,
    )
    return record_a, record_b


def create_seventy_couple(
    client: MpiApiClient,
    site_id: str,
    mrn_a: str,
    mrn_b: str,
    last_name: str = "Andersson",
    first_name: str = "Elin",
    dob: str = "1991-06-22",
    sex: str = "F",
    elements_a: int = 0,
    elements_b: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A couple scoring exactly 70.00 under STRICT and 77.50 under TOLERANT.

    The four supplied attributes agree fully (25.00 + 15.00 + 25.00 + 5.00) and
    ssn_last4, postal_code and phone are absent on both sides, so they earn no
    credit under STRICT and quarter-weight credit under TOLERANT.
    """
    record_a = create_record(
        client, site_id, mrn_a, last_name, first_name, dob, sex,
        clinical_element_count=elements_a,
    )
    record_b = create_record(
        client, site_id, mrn_b, last_name, first_name, dob, sex,
        clinical_element_count=elements_b,
    )
    return record_a, record_b


# ─────────────────────────────────────────────────────
# Tier 3 - candidate pair lifecycle shortcuts
# ─────────────────────────────────────────────────────
def create_pair(
    client: MpiApiClient,
    record_a_id: str,
    record_b_id: str,
    rule_set_id: str,
    score_variant: Any = f.OMIT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = client.create_pair(
        f.pair_payload(record_a_id, record_b_id, rule_set_id, score_variant),
        headers or analyst_headers(),
    )
    return assert_created(response)


def triage(
    client: MpiApiClient,
    pair_id: str,
    triage_note: str = "Queueing for manual adjudication.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return assert_ok(
        client.triage_pair(
            pair_id, f.triage_payload(triage_note), headers or analyst_headers()
        )
    )


def start_review(
    client: MpiApiClient, pair_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return assert_ok(client.start_review(pair_id, headers or analyst_headers()))


def advance_to_under_review(
    client: MpiApiClient,
    pair_id: str,
    triage_note: str = "Queueing for manual adjudication.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Walk a NEW pair through triage into UNDER_REVIEW."""
    triage(client, pair_id, triage_note, headers)
    return start_review(client, pair_id, headers)


def add_evidence(
    client: MpiApiClient,
    pair_id: str,
    evidence_type: str,
    outcome: str,
    weight_points: float,
    note: Any = f.OMIT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = client.add_evidence(
        pair_id,
        f.evidence_payload(evidence_type, outcome, weight_points, note),
        headers or analyst_headers(),
    )
    return assert_created(response)


def add_supporting_evidence_pair(
    client: MpiApiClient,
    pair_id: str,
    first_points: float = 1.00,
    second_points: float = 1.00,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """Attach the two evidence entries a recommendation requires."""
    add_evidence(
        client, pair_id, "PHOTO_ID", OUTCOME_SAME_PERSON, first_points,
        headers=headers,
    )
    add_evidence(
        client, pair_id, "PHONE_VERIFICATION", OUTCOME_SAME_PERSON, second_points,
        headers=headers,
    )


def recommend(
    client: MpiApiClient,
    pair_id: str,
    recommendation: str = RECOMMENDATION_MERGE,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return assert_ok(
        client.recommend(
            pair_id, f.recommend_payload(recommendation), headers or analyst_headers()
        )
    )


def ladder_to_recommendation(
    client: MpiApiClient,
    pair_id: str,
    recommendation: str = RECOMMENDATION_MERGE,
    first_points: float = 1.00,
    second_points: float = 1.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Triage, start review, attach two evidence rows and recommend."""
    advance_to_under_review(client, pair_id, headers=headers)
    add_supporting_evidence_pair(
        client, pair_id, first_points, second_points, headers=headers
    )
    return recommend(client, pair_id, recommendation, headers=headers)


# ─────────────────────────────────────────────────────
# Tier 4 - merges, propagation and remediation
# ─────────────────────────────────────────────────────
def merge(
    client: MpiApiClient,
    pair_id: str,
    survivor_record_id: str,
    subsumed_record_id: str,
    rationale: str = "Same patient confirmed by review evidence.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = client.create_merge(
        f.merge_payload(pair_id, survivor_record_id, subsumed_record_id, rationale),
        headers or steward_headers(),
    )
    return assert_created(response)


def auto_link_merge(
    client: MpiApiClient,
    site_id: str,
    rule_set_id: str,
    mrn_survivor: str,
    mrn_subsumed: str,
    elements_survivor: int = 0,
    elements_subsumed: int = 0,
    **couple_overrides: Any,
) -> Dict[str, Any]:
    """Build an AUTO_LINK couple, then merge it without a manual ladder.

    An AUTO_LINK pair with no conflict flags opens directly in
    RECOMMENDED_MERGE with a null recommender, so no duty split applies.
    """
    survivor, subsumed = create_identical_couple(
        client, site_id, mrn_survivor, mrn_subsumed,
        elements_a=elements_survivor, elements_b=elements_subsumed,
        **couple_overrides,
    )
    pair = create_pair(client, survivor["id"], subsumed["id"], rule_set_id)
    merge_row = merge(client, pair["id"], survivor["id"], subsumed["id"])
    return {
        "survivor": survivor,
        "subsumed": subsumed,
        "pair": pair,
        "merge": merge_row,
    }


def tasks_for_merge(
    client: MpiApiClient, merge_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"merge_operation_id": merge_id}
    query.update(params)
    return list_rows(client.list_tasks(admin_headers(), query))


def tasks_for_overlay(
    client: MpiApiClient, overlay_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"overlay_correction_id": overlay_id}
    query.update(params)
    return list_rows(client.list_tasks(admin_headers(), query))


def first_task_for_merge(client: MpiApiClient, merge_id: str) -> Dict[str, Any]:
    rows = tasks_for_merge(client, merge_id)
    assert rows, f"merge {merge_id} produced no propagation task"
    return rows[0]


def first_task_for_overlay(client: MpiApiClient, overlay_id: str) -> Dict[str, Any]:
    rows = tasks_for_overlay(client, overlay_id)
    assert rows, f"overlay {overlay_id} produced no propagation task"
    return rows[0]


def send_task(
    client: MpiApiClient,
    task_id: str,
    window_start: str,
    window_end: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return assert_ok(
        client.send_task(
            task_id, f.send_payload(window_start, window_end), headers or admin_headers()
        )
    )


def ack_task(
    client: MpiApiClient, task_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return assert_ok(client.ack_task(task_id, headers or admin_headers()))


def remediations_for_record(
    client: MpiApiClient, record_id: str
) -> List[Dict[str, Any]]:
    return list_rows(client.list_remediations(admin_headers(), {"record_id": record_id}))


def all_remediations(client: MpiApiClient) -> List[Dict[str, Any]]:
    return list_rows(client.list_remediations(admin_headers()))


def create_overlay(
    client: MpiApiClient,
    record_id: str,
    corrected_field_snapshot: Dict[str, Any],
    affected_clinical_element_count: int,
    expected_record_version: int,
    encounter_from_date: str = "2026-07-15",
    encounter_to_date: str = "2026-07-16",
    overlay_type: str = OVERLAY_DEMOGRAPHIC_OVERWRITE,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = client.create_overlay(
        f.overlay_payload(
            record_id,
            corrected_field_snapshot,
            affected_clinical_element_count,
            encounter_from_date,
            encounter_to_date,
            expected_record_version,
            overlay_type,
        ),
        headers or analyst_headers(),
    )
    return assert_created(response)


def apply_overlay(
    client: MpiApiClient, overlay_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return assert_ok(client.apply_overlay(overlay_id, headers or steward_headers()))


def overlay_applied(
    client: MpiApiClient,
    record_id: str,
    corrected_field_snapshot: Dict[str, Any],
    affected_clinical_element_count: int,
    expected_record_version: int,
    **overlay_kwargs: Any,
) -> Dict[str, Any]:
    """File an overlay and apply it, returning the applied overlay row."""
    overlay = create_overlay(
        client,
        record_id,
        corrected_field_snapshot,
        affected_clinical_element_count,
        expected_record_version,
        **overlay_kwargs,
    )
    return apply_overlay(client, overlay["id"])


# ─────────────────────────────────────────────────────
# Tier 5 - fraud holds, metrics and terminal states
# ─────────────────────────────────────────────────────
def open_manual_investigation(
    client: MpiApiClient,
    record_id: str,
    trigger_kind: str = TRIGGER_MANUAL,
    note: Any = f.OMIT,
    pair_id: Any = f.OMIT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = client.create_investigation(
        f.investigation_payload(record_id, trigger_kind, pair_id, note),
        headers or officer_headers(),
    )
    return assert_created(response)


def investigations_for_record(
    client: MpiApiClient, record_id: str
) -> List[Dict[str, Any]]:
    return list_rows(
        client.list_investigations(admin_headers(), {"record_id": record_id})
    )


def run_metric(
    client: MpiApiClient,
    site_id: str,
    window_start_date: str,
    window_end_date: str,
    attribution_variant: str = ATTRIBUTION_CREATION_SITE,
    headers: Optional[Dict[str, str]] = None,
):
    """Return the raw response so tests can assert acceptance or collision."""
    return client.create_metric_run(
        site_id,
        f.metric_run_payload(window_start_date, window_end_date, attribution_variant),
        headers or admin_headers(),
    )


# ─────────────────────────────────────────────────────
# Read-back conveniences
# ─────────────────────────────────────────────────────
def get_record(client: MpiApiClient, record_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_record(record_id, analyst_headers()))


def get_pair(client: MpiApiClient, pair_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_pair(pair_id, analyst_headers()))


def get_site(client: MpiApiClient, site_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_site(site_id, admin_headers()))


def get_merge(client: MpiApiClient, merge_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_merge(merge_id, steward_headers()))


def get_task(client: MpiApiClient, task_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_task(task_id, admin_headers()))


def get_overlay(client: MpiApiClient, overlay_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_overlay(overlay_id, analyst_headers()))


def get_remediation(client: MpiApiClient, remediation_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_remediation(remediation_id, officer_headers()))


def get_system(client: MpiApiClient, system_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_system(system_id, admin_headers()))


def get_investigation(client: MpiApiClient, investigation_id: str) -> Dict[str, Any]:
    return assert_ok(client.get_investigation(investigation_id, officer_headers()))


def records_at_site(client: MpiApiClient, site_id: str, **params: Any):
    query = {"site_id": site_id}
    query.update(params)
    return list_rows(client.list_records(analyst_headers(), query))


def enterprise_id_for(site_code: str, mrn: str) -> str:
    """The enterprise identifier the service mints for a new record."""
    return f"EID-{site_code}-{mrn}"
