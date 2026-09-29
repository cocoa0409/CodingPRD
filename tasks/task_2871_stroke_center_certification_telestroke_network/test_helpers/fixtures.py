"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints.  Setup calls go
through get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" rather than as a confusing assertion.

The logical clock (PRD 2.4) is driven explicitly: nothing in this module reads
wall-clock time either.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    REQUIRED_HANDOFF_PACKET_ITEMS,
    REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY,
    REQUIRED_INCLUSION_ITEM_CODES,
)
from .test_users import (
    ABSTRACTOR,
    ATTESTER,
    COORD,
    ED,
    REVIEWER,
    TRANSFER,
    make_neurologist_headers,
)

# ---------------------------------------------------------------------------
# Instant arithmetic on the logical clock
# ---------------------------------------------------------------------------
BASE_DAY = "2026-09-01T00:00:00Z"


def parse_instant(instant: str) -> datetime:
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(instant: str, *, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    """Return the instant moved by the supplied whole offsets."""
    return format_instant(
        parse_instant(instant)
        + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    )


def set_clock(instant: str, headers: Optional[Dict] = None) -> None:
    """Drive the server-held logical UTC clock to `instant` (PRD 2.4)."""
    get_success_data(api_client.set_clock(instant, headers or COORD))


# ---------------------------------------------------------------------------
# Tier 1: single-record registry setup (PRD 3.1)
# ---------------------------------------------------------------------------
def register_center(**overrides) -> dict:
    return get_success_data(
        api_client.register_stroke_center(f.register_center_payload(**overrides), COORD)
    )


def register_hub(**overrides) -> dict:
    return get_success_data(
        api_client.register_stroke_center(f.hub_center_payload(**overrides), COORD)
    )


def register_spoke(**overrides) -> dict:
    return get_success_data(
        api_client.register_stroke_center(f.spoke_center_payload(**overrides), COORD)
    )


def register_thrombectomy_center(**overrides) -> dict:
    return get_success_data(
        api_client.register_stroke_center(f.thrombectomy_center_payload(**overrides), COORD)
    )


def register_neurologist(home_center_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.register_neurologist(f.neurologist_payload(home_center_id, **overrides), COORD)
    )


def set_on_call(neurologist_id: str, state: str = "ON_CALL", headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.set_on_call_state(
            neurologist_id, f.on_call_state_payload(state), headers or COORD
        )
    )


def create_agreement(hub_id: str, spoke_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_spoke_agreement(f.spoke_agreement_payload(hub_id, spoke_id, **overrides), COORD)
    )


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_spoke_agreement(agreement_id, COORD))


def grant_credential(agreement_id: str, neurologist_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.grant_proxy_credential(
            agreement_id, f.proxy_credential_payload(neurologist_id, **overrides), COORD
        )
    )


def attest_readiness(center_id: str, component: str, result: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_readiness_attestation(
            center_id, f.readiness_attestation_payload(component, result, **overrides), COORD
        )
    )


def take_center_offline(center_id: str) -> dict:
    """Both readiness flags false, so equipment_readiness_posture is OFFLINE (PRD 2.9)."""
    attest_readiness(center_id, "CT_SCANNER", "FAIL")
    return attest_readiness(center_id, "VIDEO_CART", "FAIL")


def degrade_center(center_id: str, component: str = "VIDEO_CART") -> dict:
    """Exactly one readiness flag false, so the posture is DEGRADED (PRD 2.9)."""
    return attest_readiness(center_id, component, "FAIL")


def suspend_center(center_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_stroke_center(center_id, f.suspend_center_payload(**overrides), REVIEWER)
    )


def read_center(center_id: str) -> dict:
    return get_success_data(api_client.get_stroke_center(center_id, COORD))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_spoke_agreement(agreement_id, COORD))


def read_neurologist(neurologist_id: str) -> dict:
    return get_success_data(api_client.get_neurologist(neurologist_id, COORD))


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_code_stroke(case_id, ED))


def read_consult(consult_id: str) -> dict:
    return get_success_data(api_client.get_consult(consult_id, ED))


def read_checklist(checklist_id: str) -> dict:
    return get_success_data(api_client.get_checklist(checklist_id, ED))


def read_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer(transfer_id, TRANSFER))


def read_abstraction(abstraction_id: str) -> dict:
    return get_success_data(api_client.get_abstraction(abstraction_id, ABSTRACTOR))


def read_report(report_id: str) -> dict:
    return get_success_data(api_client.get_certification_report(report_id, COORD))


def list_case_deviations(case_id: str, **params) -> List[dict]:
    query = {"case_id": case_id, "limit": 100, "offset": 0}
    query.update(params)
    return get_success_data(api_client.list_deviations(ABSTRACTOR, query))


# ---------------------------------------------------------------------------
# Tier 2: the telestroke network - hub, spoke, agreement, credentialed roster
# ---------------------------------------------------------------------------
DEFAULT_NEUROLOGIST = {
    "board_certified": True,
    "roster_rank": 10,
    "concurrent_consult_limit": 2,
    "on_call": True,
    "privilege_scope": "CONSULT_AND_THROMBOLYSIS",
    "grant_credential": True,
}


def setup_network(
    *,
    clock: str = BASE_DAY,
    state_code: str = "CA",
    spoke_state_code: Optional[str] = None,
    spoke_facility_type: str = "SPOKE",
    coverage_tier: str = "TIER_1_FULL",
    max_concurrent_consults: int = 3,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2027-08-01T00:00:00Z",
    credential_expires_at: str = "2027-08-01T00:00:00Z",
    activate: bool = True,
    neurologists: Optional[List[dict]] = None,
) -> dict:
    """Hub + spoke + agreement + credentialed on-call roster.

    Returns a context dict with keys `hub`, `spoke`, `agreement`,
    `neurologists` (list), `neurologist` (the first one) and
    `neurologist_headers` (ownership-safe headers for the first one).
    Each entry of `neurologists` may override board_certified, roster_rank,
    concurrent_consult_limit, licensed_state_codes, privilege_scope,
    credential_expires_at, grant_credential and on_call.
    """
    set_clock(clock)
    hub = register_hub(state_code=state_code)
    spoke = register_center(
        state_code=spoke_state_code or state_code, facility_type=spoke_facility_type
    )
    agreement = create_agreement(
        hub["id"],
        spoke["id"],
        coverage_tier=coverage_tier,
        max_concurrent_consults=max_concurrent_consults,
        effective_from=effective_from,
        effective_until=effective_until,
    )

    specs = neurologists if neurologists is not None else [dict(DEFAULT_NEUROLOGIST)]
    built = []
    for index, raw in enumerate(specs):
        spec = dict(DEFAULT_NEUROLOGIST)
        spec.update(raw or {})
        licensed = spec.get("licensed_state_codes", [spoke_state_code or state_code])
        neurologist = register_neurologist(
            hub["id"],
            board_certified=spec["board_certified"],
            roster_rank=spec["roster_rank"] + index if raw is None else spec["roster_rank"],
            concurrent_consult_limit=spec["concurrent_consult_limit"],
            licensed_state_codes=licensed,
        )
        if spec["grant_credential"]:
            grant_credential(
                agreement["id"],
                neurologist["id"],
                privilege_scope=spec["privilege_scope"],
                expires_at=spec.get("credential_expires_at", credential_expires_at),
            )
        if spec["on_call"]:
            set_on_call(neurologist["id"], "ON_CALL")
        built.append(read_neurologist(neurologist["id"]))

    if activate:
        agreement = activate_agreement(agreement["id"])

    context = {
        "hub": hub,
        "spoke": spoke,
        "agreement": agreement,
        "neurologists": built,
        "neurologist": built[0] if built else None,
        "neurologist_headers": make_neurologist_headers(built[0]["id"]) if built else None,
    }
    return context


# ---------------------------------------------------------------------------
# Tier 3: the clinical clock - activation, imaging, consult lifecycle
# ---------------------------------------------------------------------------
def activate_case(
    center_id: str,
    door_at: str,
    *,
    clock: Optional[str] = None,
    lkw_precision: str = "EXACT",
    last_known_well_at: Optional[str] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Activate a code stroke, driving the clock to `clock` (default `door_at`) first."""
    set_clock(clock or door_at)
    if lkw_precision in ("EXACT", "ESTIMATED") and last_known_well_at is None:
        last_known_well_at = shift(door_at, minutes=-10)
    payload = f.code_stroke_payload(
        center_id,
        door_at,
        lkw_precision=lkw_precision,
        last_known_well_at=last_known_well_at,
        **overrides,
    )
    return get_success_data(api_client.activate_code_stroke(payload, headers or ED))


def complete_imaging(case_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.complete_imaging(case_id, f.imaging_complete_payload(), headers or ED)
    )


def request_consult(
    case_id: str,
    agreement_id: str,
    *,
    at: Optional[str] = None,
    requested_privilege_scope: str = "CONSULT_AND_THROMBOLYSIS",
    expected_case_version: Optional[int] = None,
    headers: Optional[Dict] = None,
) -> dict:
    """Request a consult, reading the case's live `version` when none is supplied."""
    if at is not None:
        set_clock(at)
    if expected_case_version is None:
        expected_case_version = read_case(case_id)["version"]
    payload = f.consult_request_payload(
        case_id, agreement_id, expected_case_version,
        requested_privilege_scope=requested_privilege_scope,
    )
    return get_success_data(api_client.request_consult(payload, headers or ED))


def accept_consult(consult_id: str, neurologist_id: str, *, at: Optional[str] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.accept_consult(consult_id, make_neurologist_headers(neurologist_id))
    )


def append_video_session(
    consult_id: str,
    neurologist_id: str,
    started_at: str,
    ended_at: str,
    *,
    video_quality: str = "HD",
    disconnect_count: int = 0,
) -> dict:
    return get_success_data(
        api_client.append_video_session(
            consult_id,
            f.video_session_payload(started_at, ended_at, video_quality, disconnect_count),
            make_neurologist_headers(neurologist_id),
        )
    )


def complete_consult(
    consult_id: str,
    neurologist_id: str,
    *,
    at: Optional[str] = None,
    recommendation: str = "THROMBOLYSIS",
    nihss_score: int = 12,
) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.complete_consult(
            consult_id,
            f.complete_consult_payload(recommendation=recommendation, nihss_score=nihss_score),
            make_neurologist_headers(neurologist_id),
        )
    )


def run_consult_to_completed(
    case_id: str,
    agreement_id: str,
    neurologist_id: str,
    *,
    requested_at: str,
    accept_after_seconds: int = 60,
    session_seconds: int = 240,
    video_quality: str = "HD",
    disconnect_count: int = 0,
    recommendation: str = "THROMBOLYSIS",
    nihss_score: int = 12,
    requested_privilege_scope: str = "CONSULT_AND_THROMBOLYSIS",
) -> dict:
    """Request -> assign -> accept -> one valid video session -> COMPLETED.

    `accept_after_seconds` fixes `response_latency_seconds`; `session_seconds`
    fixes the appended session's `duration_seconds`.
    """
    consult = request_consult(
        case_id, agreement_id, at=requested_at,
        requested_privilege_scope=requested_privilege_scope,
    )
    accepted_at = shift(requested_at, seconds=accept_after_seconds)
    accept_consult(consult["id"], neurologist_id, at=accepted_at)
    append_video_session(
        consult["id"], neurologist_id, accepted_at,
        shift(accepted_at, seconds=session_seconds),
        video_quality=video_quality, disconnect_count=disconnect_count,
    )
    completed_at = shift(accepted_at, seconds=session_seconds)
    return complete_consult(
        consult["id"], neurologist_id, at=completed_at,
        recommendation=recommendation, nihss_score=nihss_score,
    )


# ---------------------------------------------------------------------------
# Tier 4: checklist, determination, thrombolytic, closure
# ---------------------------------------------------------------------------
def create_checklist(case_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.create_checklist(f.checklist_payload(case_id), headers or ED), 201
    )


def confirm_item(checklist_id: str, item_code: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.confirm_inclusion_item(
            checklist_id, f.inclusion_item_payload(item_code), headers or ED
        )
    )


def document_contraindication(
    checklist_id: str,
    code: str = "CI_RECENT_SURGERY",
    severity: str = "RELATIVE",
    documented_evidence: Optional[str] = None,
    *,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api_client.document_contraindication(
            checklist_id,
            f.contraindication_payload(code, severity, documented_evidence),
            headers or ED,
        ),
        201,
    )


def setup_documented_checklist(
    case_id: str,
    *,
    item_codes: Optional[Sequence[str]] = None,
    relative_contraindications: int = 0,
    absolute_contraindications: int = 0,
    headers: Optional[Dict] = None,
) -> dict:
    """Open a checklist and document it: N inclusion items plus contraindications."""
    checklist = create_checklist(case_id, headers=headers)
    codes = REQUIRED_INCLUSION_ITEM_CODES if item_codes is None else item_codes
    for code in codes:
        checklist = confirm_item(checklist["id"], code, headers=headers)
    for index in range(relative_contraindications):
        checklist = document_contraindication(
            checklist["id"], f"CI_RELATIVE_{index}", "RELATIVE", headers=headers
        )
    for index in range(absolute_contraindications):
        checklist = document_contraindication(
            checklist["id"], f"CI_ABSOLUTE_{index}", "ABSOLUTE",
            "operative note filed in the chart", headers=headers,
        )
    return checklist


def determine(
    checklist_id: str,
    neurologist_id: str,
    *,
    at: Optional[str] = None,
    override_justification: Optional[str] = None,
) -> dict:
    if at is not None:
        set_clock(at)
    payload = f.determine_payload()
    if override_justification is not None:
        payload["override_justification"] = override_justification
    return get_success_data(
        api_client.determine_checklist(
            checklist_id,
            headers=make_neurologist_headers(neurologist_id),
            payload=payload,
        )
    )


def amend_checklist(checklist_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.amend_checklist(checklist_id, f.amend_checklist_payload(), headers or ED)
    )


def administer(
    case_id: str,
    *,
    at: Optional[str] = None,
    agent: str = "ALTEPLASE",
    dose_mg: float = 65.0,
    headers: Optional[Dict] = None,
) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.administer_thrombolytic(
            case_id,
            f.administer_thrombolytic_payload(thrombolytic_agent=agent, thrombolytic_dose_mg=dose_mg),
            headers or ED,
        )
    )


def close_case(case_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.close_code_stroke(case_id, headers or ED))


def abort_case(case_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.abort_code_stroke(case_id, f.abort_case_payload(), headers or ED))


def setup_case_with_completed_consult(
    context: dict,
    door_at: str,
    *,
    accept_after_seconds: int = 60,
    session_seconds: int = 240,
    video_quality: str = "HD",
    disconnect_count: int = 0,
    recommendation: str = "THROMBOLYSIS",
    nihss_score: int = 12,
    neurologist_id: Optional[str] = None,
    lkw_precision: str = "EXACT",
    last_known_well_at: Optional[str] = None,
    **case_overrides,
) -> dict:
    """Activate a case at the spoke and run one consult through to COMPLETED.

    Returns `{"case": ..., "consult": ...}` with the case in CONSULT_IN_PROGRESS.
    """
    case = activate_case(
        context["spoke"]["id"], door_at,
        lkw_precision=lkw_precision, last_known_well_at=last_known_well_at,
        **case_overrides,
    )
    consult = run_consult_to_completed(
        case["id"], context["agreement"]["id"],
        neurologist_id or context["neurologist"]["id"],
        requested_at=door_at,
        accept_after_seconds=accept_after_seconds,
        session_seconds=session_seconds,
        video_quality=video_quality,
        disconnect_count=disconnect_count,
        recommendation=recommendation,
        nihss_score=nihss_score,
    )
    return {"case": read_case(case["id"]), "consult": consult}


def setup_eligible_case(
    context: dict,
    door_at: str,
    *,
    dti_minutes: int = 20,
    determine_at: Optional[str] = None,
    item_codes: Optional[Sequence[str]] = None,
    relative_contraindications: int = 0,
    absolute_contraindications: int = 0,
    override_justification: Optional[str] = None,
    neurologist_id: Optional[str] = None,
    accept_after_seconds: int = 60,
    session_seconds: int = 240,
    lkw_precision: str = "EXACT",
    last_known_well_at: Optional[str] = None,
    **case_overrides,
) -> dict:
    """Case at ELIGIBILITY_DETERMINED with a DOCUMENTED, determined checklist.

    `dti_minutes` fixes door_to_imaging_minutes; the determination runs at
    `determine_at` (default: the imaging instant).  Returns
    `{"case", "consult", "checklist"}`.
    """
    neuro = neurologist_id or context["neurologist"]["id"]
    built = setup_case_with_completed_consult(
        context, door_at,
        accept_after_seconds=accept_after_seconds,
        session_seconds=session_seconds,
        neurologist_id=neuro,
        lkw_precision=lkw_precision,
        last_known_well_at=last_known_well_at,
        **case_overrides,
    )
    case_id = built["case"]["id"]
    imaging_at = shift(door_at, minutes=dti_minutes)
    complete_imaging(case_id, at=imaging_at)
    checklist = setup_documented_checklist(
        case_id,
        item_codes=item_codes,
        relative_contraindications=relative_contraindications,
        absolute_contraindications=absolute_contraindications,
    )
    checklist = determine(
        checklist["id"], neuro,
        at=determine_at or imaging_at,
        override_justification=override_justification,
    )
    return {"case": read_case(case_id), "consult": built["consult"], "checklist": checklist}


def setup_treated_case(
    context: dict,
    door_at: str,
    *,
    dtn_minutes: int = 45,
    dti_minutes: int = 20,
    **kwargs,
) -> dict:
    """Case at THROMBOLYSIS_ADMINISTERED with door_to_needle_minutes = dtn_minutes."""
    built = setup_eligible_case(context, door_at, dti_minutes=dti_minutes, **kwargs)
    administer(built["case"]["id"], at=shift(door_at, minutes=dtn_minutes))
    built["case"] = read_case(built["case"]["id"])
    return built


def setup_closed_treated_case(
    context: dict,
    door_at: str,
    *,
    dtn_minutes: int = 45,
    dti_minutes: int = 20,
    close_after_minutes: Optional[int] = None,
    **kwargs,
) -> dict:
    """A CLOSED, locally treated case - the unit a certification report counts."""
    built = setup_treated_case(
        context, door_at, dtn_minutes=dtn_minutes, dti_minutes=dti_minutes, **kwargs
    )
    close_at = shift(door_at, minutes=close_after_minutes if close_after_minutes is not None else dtn_minutes + 10)
    close_case(built["case"]["id"], at=close_at)
    built["case"] = read_case(built["case"]["id"])
    return built


# ---------------------------------------------------------------------------
# Tier 5: transfers, deviations, abstractions and reports
# ---------------------------------------------------------------------------
def propose_transfer(
    case_id: str,
    destination_center_id: str,
    *,
    mode: str = "TRANSFER_ONLY",
    transport_eta_minutes: int = 35,
    at: Optional[str] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.propose_transfer(
            f.transfer_payload(
                case_id, destination_center_id, mode, transport_eta_minutes, **overrides
            ),
            headers or TRANSFER,
        ),
        201,
    )


def accept_transfer(transfer_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.accept_transfer(transfer_id, headers or TRANSFER))


def decline_transfer(transfer_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.decline_transfer(transfer_id, f.decline_transfer_payload(), headers or TRANSFER)
    )


def complete_handoff(
    transfer_id: str,
    *,
    mode: str = "TRANSFER_ONLY",
    at: Optional[str] = None,
    handoff_packet_items: Optional[Sequence[str]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    """Settle a handoff with the mode-conditional complete packet by default."""
    if at is not None:
        set_clock(at)
    if handoff_packet_items is None:
        handoff_packet_items = (
            REQUIRED_HANDOFF_PACKET_ITEMS
            if mode == "DRIP_AND_SHIP"
            else REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY
        )
    return get_success_data(
        api_client.complete_handoff(
            transfer_id, f.handoff_payload(handoff_packet_items), headers or TRANSFER
        )
    )


def setup_accepted_transfer(
    context: dict,
    door_at: str,
    *,
    mode: str = "TRANSFER_ONLY",
    transport_eta_minutes: int = 35,
    destination_id: Optional[str] = None,
    propose_at: Optional[str] = None,
    accept_at: Optional[str] = None,
    dtn_minutes: int = 45,
    dti_minutes: int = 20,
    **kwargs,
) -> dict:
    """An ACCEPTED transfer over a case in TRANSFER_INITIATED.

    TRANSFER_ONLY ships from ELIGIBILITY_DETERMINED, DRIP_AND_SHIP from
    THROMBOLYSIS_ADMINISTERED.  Returns `{"case", "consult", "checklist",
    "destination", "transfer"}`.
    """
    if mode == "DRIP_AND_SHIP":
        built = setup_treated_case(
            context, door_at, dtn_minutes=dtn_minutes, dti_minutes=dti_minutes, **kwargs
        )
        default_offset = dtn_minutes + 5
    else:
        built = setup_eligible_case(context, door_at, dti_minutes=dti_minutes, **kwargs)
        default_offset = dti_minutes + 5
    if destination_id is None:
        destination = register_thrombectomy_center(state_code=context["spoke"]["state_code"])
    else:
        destination = read_center(destination_id)
    transfer = propose_transfer(
        built["case"]["id"], destination["id"],
        mode=mode, transport_eta_minutes=transport_eta_minutes,
        at=propose_at or shift(door_at, minutes=default_offset),
    )
    transfer = accept_transfer(
        transfer["id"], at=accept_at or shift(door_at, minutes=default_offset + 1)
    )
    built["destination"] = read_center(destination["id"])
    built["transfer"] = transfer
    built["case"] = read_case(built["case"]["id"])
    return built


def create_deviation(
    case_id: str,
    *,
    deviation_type: str = "DTN_EXCEEDED",
    severity: str = "MAJOR",
    narrative: str = "needle time missed the sixty minute target",
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_deviation(
            f.deviation_payload(case_id, deviation_type, severity, narrative, **overrides),
            headers or ABSTRACTOR,
        ),
        201,
    )


def start_review(deviation_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.start_deviation_review(deviation_id, headers or REVIEWER))


def return_for_info(deviation_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.return_deviation_for_info(deviation_id, f.return_for_info_payload(), headers or REVIEWER)
    )


def resubmit_deviation(deviation_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.resubmit_deviation(deviation_id, f.resubmit_deviation_payload(), headers or ABSTRACTOR)
    )


def debrief_deviation(deviation_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.debrief_deviation(deviation_id, f.debrief_payload(), headers or ABSTRACTOR)
    )


def decide_deviation(deviation_id: str, outcome: str = "SUBSTANTIATE", *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.decide_deviation(
            deviation_id, f.decide_deviation_payload(outcome), headers or REVIEWER
        )
    )


def substantiate_deviation(
    case_id: str,
    *,
    severity: str = "MAJOR",
    deviation_type: str = "DTN_EXCEEDED",
    debrief: bool = False,
) -> dict:
    """Raise a manual deviation and drive it all the way to SUBSTANTIATED."""
    deviation = create_deviation(case_id, deviation_type=deviation_type, severity=severity)
    if debrief or severity == "SENTINEL":
        debrief_deviation(deviation["id"])
    start_review(deviation["id"])
    return decide_deviation(deviation["id"], "SUBSTANTIATE")


def create_abstraction(
    case_id: str,
    measure_code: str = "STK_DTN_60",
    *,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api_client.create_abstraction(f.abstraction_payload(case_id, measure_code), headers or ABSTRACTOR),
        201,
    )


def finalize_abstraction(abstraction_id: str, *, headers: Optional[Dict] = None) -> dict:
    """Finalize under a second QualityAbstractor identity, per PRD 2.10."""
    return get_success_data(
        api_client.finalize_abstraction(
            abstraction_id, f.finalize_abstraction_payload(), headers or ATTESTER
        )
    )


def retract_abstraction(abstraction_id: str, *, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.retract_abstraction(
            abstraction_id, f.retract_abstraction_payload(), headers or ABSTRACTOR
        )
    )


def create_report(
    center_id: str,
    period_start: str,
    period_end: str,
    *,
    expected_center_version: Optional[int] = None,
    at: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> dict:
    if at is not None:
        set_clock(at)
    if expected_center_version is None:
        expected_center_version = read_center(center_id)["version"]
    return get_success_data(
        api_client.create_certification_report(
            f.certification_report_payload(center_id, period_start, period_end, expected_center_version),
            headers or COORD,
        ),
        201,
    )


def submit_report(report_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.submit_certification_report(report_id, headers or COORD))


def decide_report(report_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.decide_certification_report(
            report_id, headers=headers or REVIEWER, payload=f.decide_report_payload()
        )
    )


def publish_report(report_id: str, *, at: Optional[str] = None, headers: Optional[Dict] = None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.publish_certification_report(report_id, headers or COORD))


def setup_reportable_case(
    context: dict,
    door_at: str,
    *,
    dtn_minutes: Optional[int] = 45,
    dti_minutes: int = 20,
    measures: Sequence[str] = ("STK_DTN_60",),
    finalize: bool = True,
    **kwargs,
) -> dict:
    """A CLOSED case at the spoke carrying one abstraction per named measure.

    Abstractions are opened while the case is still live (PRD 3.9) and attested
    after it closes, by a second QualityAbstractor identity.  `dtn_minutes` of
    None leaves the case untreated so it closes on an INELIGIBLE checklist.
    Returns `{"case", "checklist", "consult", "abstractions": {measure: row}}`.
    """
    if dtn_minutes is None:
        built = setup_eligible_case(
            context, door_at, dti_minutes=dti_minutes,
            absolute_contraindications=1, item_codes=REQUIRED_INCLUSION_ITEM_CODES,
            **kwargs,
        )
        close_offset = dti_minutes + 10
    else:
        built = setup_treated_case(
            context, door_at, dtn_minutes=dtn_minutes, dti_minutes=dti_minutes, **kwargs
        )
        close_offset = dtn_minutes + 10
    case_id = built["case"]["id"]
    abstractions = {code: create_abstraction(case_id, code) for code in measures}
    close_case(case_id, at=shift(door_at, minutes=close_offset))
    if finalize:
        abstractions = {
            code: finalize_abstraction(row["id"]) for code, row in abstractions.items()
        }
    built["case"] = read_case(case_id)
    built["abstractions"] = abstractions
    return built


def setup_report_scenario(
    *,
    context: Optional[dict] = None,
    cases: Optional[Sequence[dict]] = None,
    period_start: str = BASE_DAY,
    period_days: int = 30,
    period_end: Optional[str] = None,
    spoke_facility_type: str = "SPOKE",
    create: bool = True,
    submit: bool = False,
    **network_kwargs,
) -> dict:
    """Build a facility with N closed, abstracted cases and open its report.

    Each entry of `cases` is a kwargs dict for setup_reportable_case; a `door_at`
    key is honoured, otherwise the cases are spaced two hours apart inside the
    period so the ten-minute neurologist cooldown of PRD 3.3 never bites.
    Returns `{"context", "center", "cases", "report"}`.
    """
    if context is None:
        context = setup_network(
            clock=period_start, spoke_facility_type=spoke_facility_type, **network_kwargs
        )
    specs = list(cases) if cases is not None else [{}, {}]
    period_end = period_end or shift(period_start, days=period_days)

    built_cases = []
    for index, spec in enumerate(specs):
        spec = dict(spec)
        door_at = spec.pop("door_at", None) or shift(period_start, hours=1 + 2 * index)
        built_cases.append(setup_reportable_case(context, door_at, **spec))

    center = read_center(context["spoke"]["id"])
    report = None
    if create:
        report = create_report(center["id"], period_start, period_end)
        if submit:
            report = submit_report(report["id"])
    return {
        "context": context,
        "center": read_center(center["id"]),
        "cases": built_cases,
        "report": report,
        "period_start": period_start,
        "period_end": period_end,
    }
