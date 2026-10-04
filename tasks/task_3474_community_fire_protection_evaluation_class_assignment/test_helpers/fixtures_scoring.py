"""Composite fixtures, tier 2–3: field verification, scoring, publication.

The workhorse is ``setup_scoring_cycle``: it registers a community bundle,
opens a cycle, walks the data window, submits the requested field data
(apparatus, hydrants, flow tests, credits, alternate supply), performs the
requested verification actions, and lands the cycle in the wanted state.
On top of it sit the sheet / classification lifecycle shortcuts.
"""
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .fixtures_core import (
    COORDINATOR,
    advance_cycle_to,
    add_apparatus,
    add_hydrant,
    attest_comms,
    create_community_bundle,
    create_cycle,
    cycle_version,
    get_community,
    patch_water_system,
    set_apparatus_status,
    submit_department_data,
    submit_flow_test,
    transition_cycle,
)
from .test_users import (
    DEFAULT_ANALYST_ID,
    DEFAULT_REGISTRAR_ID,
    make_community_official_headers,
    make_field_analyst_headers,
    make_class_registrar_headers,
)

# Outcomes a flow-test spec may request once FIELD_VERIFICATION is reached.
_TEST_OUTCOMES = ("submitted", "witnessed", "certified", "rejected")
_CREDIT_OUTCOMES = ("pending", "verified", "rejected")


# ── Single verification actions (Tier 1) ─────────────────────────────────

def transition_flow_test(api: ApiClient, test_id: str, target_state: str, analyst_id: str = DEFAULT_ANALYST_ID, **corrections: Any) -> Dict[str, Any]:
    return get_success_data(
        api.transition_flow_test(
            test_id, f.flow_test_transition_payload(target_state, **corrections),
            make_field_analyst_headers(analyst_id),
        )
    )


def witness_flow_test(api: ApiClient, test_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_flow_test(api, test_id, "WITNESSED", analyst_id)


def certify_flow_test(api: ApiClient, test_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_flow_test(api, test_id, "CERTIFIED", analyst_id)


def reject_flow_test(api: ApiClient, test_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_flow_test(api, test_id, "REJECTED", analyst_id)


def correct_flow_test(
    api: ApiClient,
    test_id: str,
    analyst_id: str = DEFAULT_ANALYST_ID,
    corrected_static_psi: Any = 80,
    corrected_residual_psi: Any = 60,
    corrected_measured_flow_gpm: Any = 1000,
    correction_reason: str = "gauge recalibration",
) -> Dict[str, Any]:
    """CORRECTED on a CERTIFIED test; returns the CERTIFIED replacement row."""
    return transition_flow_test(
        api,
        test_id,
        "CORRECTED",
        analyst_id,
        corrected_static_psi=corrected_static_psi,
        corrected_residual_psi=corrected_residual_psi,
        corrected_measured_flow_gpm=corrected_measured_flow_gpm,
        correction_reason=correction_reason,
    )


def file_credit(api: ApiClient, cycle_id: str, community_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_risk_reduction_credit(
            f.risk_reduction_credit_payload(cycle_id, **overrides),
            make_community_official_headers(community_id),
        )
    )


def transition_credit(api: ApiClient, credit_id: str, target_state: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return get_success_data(
        api.transition_risk_reduction_credit(
            credit_id, f.credit_transition_payload(target_state), make_field_analyst_headers(analyst_id)
        )
    )


def verify_credit(api: ApiClient, credit_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_credit(api, credit_id, "VERIFIED", analyst_id)


def reject_credit(api: ApiClient, credit_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_credit(api, credit_id, "REJECTED", analyst_id)


def verify_alternate_supply(api: ApiClient, system_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return get_success_data(
        api.verify_alternate_supply(system_id, make_field_analyst_headers(analyst_id))
    )


# ── The scoring-pipeline workhorse (Tier 2) ──────────────────────────────

def setup_scoring_cycle(
    api: ApiClient,
    *,
    analyst_id: str = DEFAULT_ANALYST_ID,
    dept_data: Optional[Dict[str, Any]] = None,
    comms: Optional[Dict[str, Any]] = None,
    apparatus: Iterable[Dict[str, Any]] = (),
    hydrant_count: int = 0,
    hydrants: Optional[Iterable[Dict[str, Any]]] = None,
    flow_tests: Iterable[Dict[str, Any]] = (),
    credits: Iterable[Dict[str, Any]] = (),
    alternate_supply: Optional[Dict[str, Any]] = None,
    verify_alternate: bool = False,
    target_state: str = "SCORING",
    open_date: str = f.DEFAULT_OPEN_DATE,
    freeze_date: str = f.DEFAULT_FREEZE_DATE,
    **community_overrides: Any,
) -> Dict[str, Any]:
    """Community + cycle + field data, driven to ``target_state``.

    Spec conventions:
      - apparatus spec: factory kwargs plus optional "status" to move to.
      - flow_tests spec: flow-test factory kwargs plus "hydrant" (index into
        the created hydrant list, default 0) and "outcome" (default
        "submitted"; "certified"/"rejected" witness first, then settle).
      - credits spec: credit factory kwargs plus "outcome" (default
        "pending"; adjudicated during FIELD_VERIFICATION).
      - alternate_supply: PATCHed onto the water system during
        DATA_COLLECTION; verify_alternate certifies it during
        FIELD_VERIFICATION.
    Verification actions only run when target_state reaches
    FIELD_VERIFICATION; requesting outcomes under DATA_COLLECTION fails fast.
    """
    bundle = create_community_bundle(api, **community_overrides)
    community, department, system = bundle["community"], bundle["department"], bundle["system"]
    cycle = create_cycle(
        api, community["id"], field_analyst_id=analyst_id,
        scheduled_open_date=open_date, data_freeze_date=freeze_date,
    )
    advance_cycle_to(api, cycle["id"], "DATA_COLLECTION")

    submit_department_data(api, department["id"], **(dept_data or {}))
    attest_comms(api, community["id"], **(comms if comms is not None else {}))
    if alternate_supply:
        patch_water_system(api, system["id"], **alternate_supply)

    apparatus_rows: List[Dict[str, Any]] = []
    for spec in apparatus:
        spec = dict(spec)
        move_to = spec.pop("status", None)
        kind = spec.pop("kind", "ENGINE")
        row = add_apparatus(api, department["id"], kind, **spec)
        if move_to:
            row = set_apparatus_status(api, department["id"], row["id"], move_to)
        apparatus_rows.append(row)

    hydrant_rows: List[Dict[str, Any]] = []
    if hydrants is not None:
        for spec in hydrants:
            hydrant_rows.append(add_hydrant(api, system["id"], **dict(spec)))
    else:
        for _ in range(hydrant_count):
            hydrant_rows.append(add_hydrant(api, system["id"]))

    test_specs = [dict(s) for s in flow_tests]
    credit_specs = [dict(s) for s in credits]
    test_outcomes: List[str] = []
    credit_outcomes: List[str] = []
    test_rows: List[Dict[str, Any]] = []
    credit_rows: List[Dict[str, Any]] = []
    for spec in test_specs:
        outcome = spec.pop("outcome", "submitted")
        assert outcome in _TEST_OUTCOMES, f"unknown flow-test outcome {outcome}"
        assert hydrant_rows, "flow_tests require hydrant_count or hydrants"
        hydrant = hydrant_rows[spec.pop("hydrant", 0)]
        spec.setdefault("test_date", f.DEFAULT_TEST_DATE)
        test_rows.append(submit_flow_test(api, system["id"], hydrant["id"], **spec))
        test_outcomes.append(outcome)
    for spec in credit_specs:
        outcome = spec.pop("outcome", "pending")
        assert outcome in _CREDIT_OUTCOMES, f"unknown credit outcome {outcome}"
        credit_rows.append(file_credit(api, cycle["id"], community["id"], **spec))
        credit_outcomes.append(outcome)

    verification_needed = (
        any(o != "submitted" for o in test_outcomes)
        or any(o != "pending" for o in credit_outcomes)
        or verify_alternate
    )
    if target_state == "DATA_COLLECTION":
        assert not verification_needed, (
            "verification actions cannot run while stopped in DATA_COLLECTION"
        )
    else:
        advance_cycle_to(api, cycle["id"], "FIELD_VERIFICATION")
        for row, outcome in zip(test_rows, test_outcomes):
            if outcome != "submitted":
                witness_flow_test(api, row["id"], analyst_id)
            if outcome == "certified":
                certify_flow_test(api, row["id"], analyst_id)
            elif outcome == "rejected":
                reject_flow_test(api, row["id"], analyst_id)
        for row, outcome in zip(credit_rows, credit_outcomes):
            if outcome == "verified":
                verify_credit(api, row["id"], analyst_id)
            elif outcome == "rejected":
                reject_credit(api, row["id"], analyst_id)
        if verify_alternate:
            verify_alternate_supply(api, system["id"], analyst_id)

    if target_state == "SCORING":
        transition_cycle(api, cycle["id"], "SCORING")
    elif target_state not in ("DATA_COLLECTION", "FIELD_VERIFICATION"):
        raise ValueError(f"setup_scoring_cycle cannot target {target_state}")

    return {
        "community": get_community(api, community["id"]),
        "department": department,
        "system": system,
        "cycle": get_success_data(api.get_evaluation_cycle(cycle["id"], COORDINATOR)),
        "apparatus": apparatus_rows,
        "hydrants": hydrant_rows,
        "flow_tests": test_rows,
        "credits": credit_rows,
        "analyst_id": analyst_id,
    }


# ── Sheet lifecycle (Tier 3) ─────────────────────────────────────────────

def create_score_sheet(
    api: ApiClient,
    cycle_id: str,
    analyst_id: str = DEFAULT_ANALYST_ID,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a DRAFT sheet; captures the fresh cycle version unless given."""
    version = expected_version if expected_version is not None else cycle_version(api, cycle_id)
    return get_success_data(
        api.create_score_sheet(
            cycle_id, f.score_sheet_create_payload(version), make_field_analyst_headers(analyst_id)
        )
    )


def finalize_score_sheet(api: ApiClient, sheet_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return get_success_data(api.finalize_score_sheet(sheet_id, make_field_analyst_headers(analyst_id)))


def publish_classification(
    api: ApiClient, cycle_id: str, score_sheet_id: str, registrar_id: str = DEFAULT_REGISTRAR_ID
) -> Dict[str, Any]:
    """Publish from a FINAL sheet; registrar must differ from the analyst."""
    return get_success_data(
        api.publish_classification(
            cycle_id, f.publish_classification_payload(score_sheet_id),
            make_class_registrar_headers(registrar_id),
        )
    )


def activate_classification(
    api: ApiClient,
    classification_id: str,
    effective_from: str = f.DEFAULT_OPEN_DATE,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.activate_classification(
            classification_id, f.activate_classification_payload(effective_from),
            make_class_registrar_headers(registrar_id),
        )
    )


# ── Full grading lifecycles (Tier 3 shortcuts) ───────────────────────────

def setup_classification_review(api: ApiClient, *, analyst_id: str = DEFAULT_ANALYST_ID, **setup_kwargs: Any) -> Dict[str, Any]:
    """SCORING cycle plus a FINAL sheet, advanced to CLASSIFICATION_REVIEW."""
    ctx = setup_scoring_cycle(api, analyst_id=analyst_id, target_state="SCORING", **setup_kwargs)
    sheet = create_score_sheet(api, ctx["cycle"]["id"], analyst_id)
    sheet = finalize_score_sheet(api, sheet["id"], analyst_id)
    transition_cycle(api, ctx["cycle"]["id"], "CLASSIFICATION_REVIEW")
    ctx["sheet"] = sheet
    return ctx


def setup_published_classification(
    api: ApiClient,
    *,
    analyst_id: str = DEFAULT_ANALYST_ID,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Through publication: ctx gains "classification" (PUBLISHED)."""
    ctx = setup_classification_review(api, analyst_id=analyst_id, **setup_kwargs)
    ctx["classification"] = publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"], registrar_id)
    ctx["registrar_id"] = registrar_id
    return ctx


def setup_classified_community(
    api: ApiClient,
    *,
    effective_from: str = f.DEFAULT_OPEN_DATE,
    analyst_id: str = DEFAULT_ANALYST_ID,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
    **setup_kwargs: Any,
) -> Dict[str, Any]:
    """Full grading lifecycle through activation; community is CLASSIFIED."""
    ctx = setup_published_classification(api, analyst_id=analyst_id, registrar_id=registrar_id, **setup_kwargs)
    ctx["classification"] = activate_classification(
        api, ctx["classification"]["id"], effective_from, registrar_id
    )
    ctx["community"] = get_community(api, ctx["community"]["id"])
    return ctx
