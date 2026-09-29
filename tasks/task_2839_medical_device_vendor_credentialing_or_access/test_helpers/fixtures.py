"""Composite setup chains built entirely out of declared endpoints.

Nothing here assumes preloaded server state: every chain creates what it needs
through the public API, in the role the endpoint table names for each step, so a
test that starts against an empty server can reach a deep state such as a
credentialed representative holding an approved badge in a handful of lines.

The two optimistic-concurrency chains re-read the parent's ``version``
immediately before the guarded write, because section 2.7 advances the parent's
version on every successful write and a stale echo is refused with 412.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import VendorAccessApiClient
from .constants import (
    COMPLEXITY_SIMPLE,
    GATING_CREDENTIAL_TYPES,
    LOGICAL_CLOCK_DEFAULT_UTC,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    RESTRICTION_STANDARD,
)
from .factories import (
    access_appeal_payload,
    adjudicate_payload,
    attach_escort_payload,
    authorization_decision_payload,
    authorization_payload,
    check_in_payload,
    clinical_review_payload,
    compliance_sweep_payload,
    credential_decision_payload,
    credential_payload,
    facility_payload,
    incident_payload,
    loaner_set_payload,
    pir_payload,
    receive_payload,
    revoke_access_payload,
    surgical_case_payload,
    value_analysis_payload,
    vendor_payload,
    vendor_rep_payload,
)
from .test_users import (
    COMPLIANCE_ADMIN,
    COMPLIANCE_ADMIN_2,
    CLINICAL_SPONSOR,
    CREDENTIALING_OFFICER,
    OR_COORDINATOR,
    OR_COORDINATOR_2,
    STERILE_PROCESSING_TECH,
    USER_ESCORT_NURSE_1,
    VALUE_ANALYSIS_APPROVER,
    make_vendor_admin_headers,
    make_vendor_rep_headers,
)
from .types import JsonDict


# ── The logical clock ─────────────────────────────────────────────────────────
def set_clock(client: VendorAccessApiClient, instant: str) -> JsonDict:
    """Move the server's logical current instant, which performs no transitions."""
    return validate_success(client.set_clock(instant, COMPLIANCE_ADMIN), 200)


def reset_clock(client: VendorAccessApiClient) -> JsonDict:
    """Return the logical clock to the startup default instant."""
    return set_clock(client, LOGICAL_CLOCK_DEFAULT_UTC)


# ── Registry rows ─────────────────────────────────────────────────────────────
def create_facility(
    client: VendorAccessApiClient, code: str, **overrides: Any
) -> JsonDict:
    """Register a facility and return the created row."""
    response = client.create_facility(
        facility_payload(code, **overrides), COMPLIANCE_ADMIN
    )
    return get_success_data(response, 201)


def create_vendor(client: VendorAccessApiClient, vendor_code: str, **overrides: Any) -> JsonDict:
    """Enrol a vendor and return the created row with its birth values."""
    response = client.create_vendor(
        vendor_payload(vendor_code, **overrides), COMPLIANCE_ADMIN
    )
    return get_success_data(response, 201)


def create_vendor_rep(
    client: VendorAccessApiClient,
    vendor_id: str,
    full_name: str = "Riley Vendor",
    **overrides: Any,
) -> JsonDict:
    """Register a representative under a vendor and return the created row."""
    response = client.create_vendor_rep(
        vendor_rep_payload(vendor_id, full_name, **overrides), CREDENTIALING_OFFICER
    )
    return get_success_data(response, 201)


def read_vendor(client: VendorAccessApiClient, vendor_id: str) -> JsonDict:
    """Read a vendor as compliance staff."""
    return validate_success(client.get_vendor(vendor_id, COMPLIANCE_ADMIN), 200)


def read_vendor_rep(client: VendorAccessApiClient, rep_id: str) -> JsonDict:
    """Read a representative as compliance staff."""
    return validate_success(client.get_vendor_rep(rep_id, COMPLIANCE_ADMIN), 200)


def read_case(client: VendorAccessApiClient, case_id: str) -> JsonDict:
    """Read a surgical case as compliance staff."""
    return validate_success(client.get_surgical_case(case_id, COMPLIANCE_ADMIN), 200)


def read_authorization(client: VendorAccessApiClient, auth_id: str) -> JsonDict:
    """Read an authorization as compliance staff."""
    return validate_success(client.get_authorization(auth_id, COMPLIANCE_ADMIN), 200)


def read_loaner_set(client: VendorAccessApiClient, set_id: str) -> JsonDict:
    """Read a loaner set as compliance staff."""
    return validate_success(client.get_loaner_set(set_id, COMPLIANCE_ADMIN), 200)


def read_check_in(client: VendorAccessApiClient, check_in_id: str) -> JsonDict:
    """Read a kiosk check-in as compliance staff."""
    return validate_success(client.get_check_in(check_in_id, COMPLIANCE_ADMIN), 200)


def read_pir(client: VendorAccessApiClient, pir_id: str) -> JsonDict:
    """Read a product introduction request as compliance staff."""
    return validate_success(client.get_pir(pir_id, COMPLIANCE_ADMIN), 200)


def read_approved_product(client: VendorAccessApiClient, product_id: str) -> JsonDict:
    """Read an approved product as compliance staff."""
    return validate_success(client.get_approved_product(product_id, COMPLIANCE_ADMIN), 200)


def read_incident(client: VendorAccessApiClient, incident_id: str) -> JsonDict:
    """Read an incident as compliance staff."""
    return validate_success(client.get_incident(incident_id, COMPLIANCE_ADMIN), 200)


def read_appeal(client: VendorAccessApiClient, appeal_id: str) -> JsonDict:
    """Read an access appeal as compliance staff."""
    return validate_success(client.get_access_appeal(appeal_id, COMPLIANCE_ADMIN), 200)


def read_scorecard(client: VendorAccessApiClient, vendor_id: str) -> JsonDict:
    """Read a vendor scorecard as compliance staff."""
    return validate_success(client.get_vendor_scorecard(vendor_id, COMPLIANCE_ADMIN), 200)


# ── Credentialing a representative (section 3.2) ──────────────────────────────
def file_credential(
    client: VendorAccessApiClient,
    rep_id: str,
    credential_type: str,
    **overrides: Any,
) -> JsonDict:
    """File one credential attestation, which lands in PENDING_VERIFICATION."""
    response = client.create_credential(
        credential_payload(rep_id, credential_type, **overrides), CREDENTIALING_OFFICER
    )
    return get_success_data(response, 201)


def verify_credential(client: VendorAccessApiClient, credential_id: str) -> JsonDict:
    """Verify a pending credential as the credentialing officer."""
    response = client.decide_credential(
        credential_id, credential_decision_payload("VERIFY"), CREDENTIALING_OFFICER
    )
    return validate_success(response, 200)


def credential_rep(
    client: VendorAccessApiClient, rep_id: str, **overrides: Any
) -> List[JsonDict]:
    """File and verify all four gating credentials, landing the rep in CREDENTIALED."""
    verified: List[JsonDict] = []
    for credential_type in GATING_CREDENTIAL_TYPES:
        filed = file_credential(client, rep_id, credential_type, **overrides)
        verified.append(verify_credential(client, filed["id"]))
    return verified


def credentialed_rep(
    client: VendorAccessApiClient,
    vendor_id: str,
    full_name: str = "Riley Vendor",
    **credential_overrides: Any,
) -> JsonDict:
    """Register a representative and carry it all the way to CREDENTIALED."""
    rep = create_vendor_rep(client, vendor_id, full_name)
    credential_rep(client, rep["id"], **credential_overrides)
    return read_vendor_rep(client, rep["id"])


def revoke_rep(
    client: VendorAccessApiClient,
    rep_id: str,
    headers: Optional[Dict[str, str]] = None,
    reason: str = "Policy violation on site",
) -> JsonDict:
    """Revoke a representative's site access, recording the acting officer."""
    response = client.revoke_rep_access(
        rep_id, revoke_access_payload(reason), headers or CREDENTIALING_OFFICER
    )
    return validate_success(response, 200)


# ── Surgical cases (section 3.3) ──────────────────────────────────────────────
def create_case(
    client: VendorAccessApiClient,
    facility_id: str,
    case_number: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    restriction_level: str = RESTRICTION_STANDARD,
    **overrides: Any,
) -> JsonDict:
    """Schedule a surgical case as the OR coordinator."""
    response = client.create_surgical_case(
        surgical_case_payload(
            facility_id,
            case_number,
            scheduled_start_utc,
            scheduled_end_utc,
            restriction_level=restriction_level,
            **overrides,
        ),
        OR_COORDINATOR,
    )
    return get_success_data(response, 201)


# ── Product introduction and approval (section 3.6) ───────────────────────────
def open_pir(
    client: VendorAccessApiClient,
    vendor_id: str,
    facility_id: str,
    product_catalog_number: str,
    unit_cost_cents: int,
    expected_vendor_version: Optional[int] = None,
    **overrides: Any,
) -> JsonDict:
    """Open a request as the owning VendorAdmin, echoing the vendor version just read."""
    if expected_vendor_version is None:
        expected_vendor_version = read_vendor(client, vendor_id)["version"]
    response = client.create_pir(
        pir_payload(
            vendor_id,
            facility_id,
            product_catalog_number,
            unit_cost_cents,
            expected_vendor_version,
            **overrides,
        ),
        make_vendor_admin_headers(vendor_id),
    )
    return get_success_data(response, 201)


def submit_pir(
    client: VendorAccessApiClient, vendor_id: str, pir_id: str
) -> JsonDict:
    """Submit or re-submit a request into clinical review as its owning vendor."""
    response = client.submit_pir(pir_id, {}, make_vendor_admin_headers(vendor_id))
    return validate_success(response, 200)


def endorse_pir(
    client: VendorAccessApiClient,
    pir_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Endorse a request in clinical review, recording the sponsor's identifier."""
    response = client.clinical_review_pir(
        pir_id, clinical_review_payload("ENDORSE"), headers or CLINICAL_SPONSOR
    )
    return validate_success(response, 200)


def decide_value_analysis(
    client: VendorAccessApiClient,
    pir_id: str,
    decision: str = "APPROVE",
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Cast the value-analysis vote on a request awaiting committee review."""
    response = client.value_analysis_decision(
        pir_id, value_analysis_payload(decision), headers or VALUE_ANALYSIS_APPROVER
    )
    return validate_success(response, 200)


def approved_product(
    client: VendorAccessApiClient,
    vendor_id: str,
    facility_id: str,
    product_catalog_number: str,
    unit_cost_cents: int,
    is_implant: bool = False,
    **overrides: Any,
) -> Tuple[JsonDict, JsonDict]:
    """Drive a request from DRAFT to APPROVED and return the request and its product."""
    pir = open_pir(
        client,
        vendor_id,
        facility_id,
        product_catalog_number,
        unit_cost_cents,
        is_implant=is_implant,
        **overrides,
    )
    submit_pir(client, vendor_id, pir["id"])
    endorse_pir(client, pir["id"])
    decided = decide_value_analysis(client, pir["id"], "APPROVE")
    products, _meta = validate_paginated(
        client.list_approved_products(
            COMPLIANCE_ADMIN, {"product_introduction_request_id": pir["id"]}
        )
    )
    assert products, "approving a request should mint exactly one approved product"
    return decided, products[0]


# ── Authorizations (section 3.4) ──────────────────────────────────────────────
def request_authorization(
    client: VendorAccessApiClient,
    case_id: str,
    rep_id: str,
    requested_role: str = REQUESTED_ROLE_TECHNICAL_SUPPORT,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Open an authorization request, which lands in REQUESTED."""
    response = client.create_authorization(
        authorization_payload(case_id, rep_id, requested_role),
        headers or OR_COORDINATOR,
    )
    return get_success_data(response, 201)


def decide_authorization(
    client: VendorAccessApiClient,
    auth_id: str,
    decision: str = "APPROVE",
    headers: Optional[Dict[str, str]] = None,
    escort_user_id: Any = None,
) -> JsonDict:
    """Approve or deny an authorization as a coordinator other than the requester."""
    payload = (
        authorization_decision_payload(decision)
        if escort_user_id is None
        else authorization_decision_payload(decision, escort_user_id)
    )
    response = client.decide_authorization(auth_id, payload, headers or OR_COORDINATOR_2)
    return validate_success(response, 200)


def approved_authorization(
    client: VendorAccessApiClient,
    case_id: str,
    rep_id: str,
    requested_role: str = REQUESTED_ROLE_TECHNICAL_SUPPORT,
    escort_user_id: Any = None,
) -> JsonDict:
    """Request an authorization with one coordinator and approve it with another."""
    requested = request_authorization(client, case_id, rep_id, requested_role)
    return decide_authorization(
        client, requested["id"], "APPROVE", escort_user_id=escort_user_id
    )


# ── Loaner sets (section 3.7) ─────────────────────────────────────────────────
def register_loaner_set(
    client: VendorAccessApiClient,
    vendor_id: str,
    case_id: str,
    product_id: str,
    tray_count: int,
    reprocessing_complexity: str = COMPLEXITY_SIMPLE,
    expected_case_version: Optional[int] = None,
) -> JsonDict:
    """Register a tray set, echoing the case version read immediately beforehand."""
    if expected_case_version is None:
        expected_case_version = read_case(client, case_id)["version"]
    response = client.create_loaner_set(
        loaner_set_payload(
            case_id,
            product_id,
            tray_count,
            expected_case_version,
            reprocessing_complexity,
        ),
        make_vendor_admin_headers(vendor_id),
    )
    return get_success_data(response, 201)


def receive_loaner_set(
    client: VendorAccessApiClient, set_id: str, delivered_at_utc: Any = None
) -> JsonDict:
    """Receive a tray set, optionally naming the delivery instant."""
    payload = (
        receive_payload() if delivered_at_utc is None else receive_payload(delivered_at_utc)
    )
    response = client.receive_loaner_set(set_id, payload, STERILE_PROCESSING_TECH)
    return validate_success(response, 200)


def release_loaner_set(client: VendorAccessApiClient, set_id: str) -> JsonDict:
    """Release a received tray set to the operating room."""
    response = client.release_loaner_set(set_id, {}, STERILE_PROCESSING_TECH)
    return validate_success(response, 200)


# ── Kiosk check-ins (section 3.5) ─────────────────────────────────────────────
def check_in(
    client: VendorAccessApiClient,
    auth_id: str,
    rep_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Check in at the kiosk against an approved authorization and take a badge."""
    response = client.create_check_in(
        check_in_payload(auth_id), headers or make_vendor_rep_headers(rep_id)
    )
    return get_success_data(response, 201)


def attach_escort(
    client: VendorAccessApiClient,
    check_in_id: str,
    escort_user_id: str = USER_ESCORT_NURSE_1,
) -> JsonDict:
    """Attach a department escort to an issued badge."""
    response = client.attach_escort(
        check_in_id, attach_escort_payload(escort_user_id), OR_COORDINATOR
    )
    return validate_success(response, 200)


def check_out(
    client: VendorAccessApiClient,
    check_in_id: str,
    rep_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Check out at the kiosk, moving the badge dimension to CHECKED_OUT."""
    response = client.check_out(
        check_in_id, {}, headers or make_vendor_rep_headers(rep_id)
    )
    return validate_success(response, 200)


# ── Incidents (section 3.8) ───────────────────────────────────────────────────
def report_incident(
    client: VendorAccessApiClient,
    case_id: str,
    rep_id: str,
    incident_type: Any = None,
    severity: Any = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    """Report an incident, which depresses the provisional score at once."""
    kwargs: Dict[str, Any] = dict(overrides)
    if incident_type is not None:
        kwargs["incident_type"] = incident_type
    if severity is not None:
        kwargs["severity"] = severity
    response = client.create_incident(
        incident_payload(case_id, rep_id, **kwargs), headers or COMPLIANCE_ADMIN
    )
    return get_success_data(response, 201)


def investigate_incident(
    client: VendorAccessApiClient,
    incident_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Open an investigation, which is score-neutral in both variants."""
    response = client.investigate_incident(incident_id, {}, headers or COMPLIANCE_ADMIN)
    return validate_success(response, 200)


def adjudicate_incident(
    client: VendorAccessApiClient,
    incident_id: str,
    outcome: str = "SUBSTANTIATED",
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Adjudicate an incident as an administrator other than its reporter."""
    response = client.adjudicate_incident(
        incident_id, adjudicate_payload(outcome), headers or COMPLIANCE_ADMIN_2
    )
    return validate_success(response, 200)


def substantiated_incident(
    client: VendorAccessApiClient,
    case_id: str,
    rep_id: str,
    incident_type: Any = None,
    severity: Any = None,
    **overrides: Any,
) -> JsonDict:
    """Report, investigate and substantiate one incident with distinct operators."""
    incident = report_incident(
        client,
        case_id,
        rep_id,
        incident_type,
        severity,
        headers=COMPLIANCE_ADMIN,
        **overrides,
    )
    investigate_incident(client, incident["id"], COMPLIANCE_ADMIN)
    return adjudicate_incident(client, incident["id"], "SUBSTANTIATED", COMPLIANCE_ADMIN_2)


# ── Appeals and sweeps (section 3.9) ──────────────────────────────────────────
def file_appeal(
    client: VendorAccessApiClient,
    vendor_id: str,
    rep_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    """File an appeal against a revocation as the owning vendor."""
    response = client.create_access_appeal(
        access_appeal_payload(rep_id, **overrides),
        headers or make_vendor_admin_headers(vendor_id),
    )
    return get_success_data(response, 201)


def run_sweep(
    client: VendorAccessApiClient, headers: Optional[Dict[str, str]] = None
) -> JsonDict:
    """Run one compliance sweep epoch through its nine pinned phases."""
    response = client.create_compliance_sweep(
        compliance_sweep_payload(), headers or COMPLIANCE_ADMIN
    )
    return get_success_data(response, 201)


# ── Listing helpers ───────────────────────────────────────────────────────────
def list_rows(response: Any) -> List[JsonDict]:
    """The rows of a paginated listing response."""
    rows, _meta = validate_paginated(response)
    return rows


def list_rows_and_meta(response: Any) -> Tuple[List[JsonDict], Dict[str, Any]]:
    """The rows and the pagination metadata of a listing response."""
    return validate_paginated(response)
