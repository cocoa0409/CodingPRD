"""Request-body factories.

Each factory returns a valid body with the field types the PRD declares:
score and hour fields are JSON numbers, never strings; every instant is a full
ISO-8601 instant with a date, a time and a UTC designator, never a bare date;
and element-code arrays carry real student data-element codes.  Overrides are
applied last so a test can pin exactly the one field it is probing.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    ACCESSIBILITY_WCAG21_AA,
    ALL_FRAMEWORKS,
    CATEGORY_ASSESSMENT,
    ELEMENT_STUDENT_NAME,
    HARD_DELETE,
    INCIDENT_BREACH,
    JUST_240,
    PURPOSE_61,
    SOURCE_NETWORK_DNS,
    SSO_SAML2,
)

_counter = itertools.count(1)


def next_sequence() -> int:
    """A per-process counter used to keep unique keys distinct."""
    return next(_counter)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(base)
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Vendor and subprocessor
# ---------------------------------------------------------------------------


def vendor_payload(**overrides: Any) -> Dict[str, Any]:
    """A registrable vendor.  Contractual hours are JSON numbers."""
    n = next_sequence()
    return _merge(
        {
            "legal_name": f"Brightpath Learning {n} Inc",
            "hq_country_code": "US",
            "breach_notification_hours": 48,
            "data_deletion_days": 30,
            "signed_state_addendum": True,
            "subprocessor_disclosure_complete": True,
        },
        overrides,
    )


def subprocessor_payload(vendor_id: str, **overrides: Any) -> Dict[str, Any]:
    """A subprocessor disclosure.

    `data_categories` carries student data-element codes, which is what PRD
    §2.5 declares the field to be.
    """
    n = next_sequence()
    return _merge(
        {
            "vendor_id": vendor_id,
            "name": f"Downstream Hosting {n} Ltd",
            "country_code": "US",
            "data_categories": [ELEMENT_STUDENT_NAME],
            "purpose": PURPOSE_61,
            "sub_breach_notification_hours": 24,
        },
        overrides,
    )


def subprocessor_review_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """An analyst disposition on a disclosed subprocessor."""
    return _merge({"disposition": disposition}, overrides)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def application_payload(vendor_id: str, **overrides: Any) -> Dict[str, Any]:
    """An application registered against a vendor."""
    n = next_sequence()
    return _merge(
        {
            "vendor_id": vendor_id,
            "name": f"Brightpath Formative {n}",
            "category": CATEGORY_ASSESSMENT,
            "grade_band_low": 6,
            "grade_band_high": 8,
            "sso_protocol": SSO_SAML2,
            "accessibility_conformance_level": ACCESSIBILITY_WCAG21_AA,
            "vpat_on_file": True,
        },
        overrides,
    )


def attestation_payload(sso_verified: bool = True, **overrides: Any) -> Dict[str, Any]:
    """The district's integration-review outcome."""
    return _merge({"sso_verified": sso_verified}, overrides)


# ---------------------------------------------------------------------------
# Teacher and analyst
# ---------------------------------------------------------------------------


def teacher_payload(**overrides: Any) -> Dict[str, Any]:
    """An enrollable teacher with a district-unique employee number."""
    n = next_sequence()
    return _merge(
        {
            "full_name": f"Dana Reyes {n}",
            "employee_number": f"EMP-{7000 + n}",
            "school_code": "MS-04",
            "grade_bands_taught": [6, 7, 8],
        },
        overrides,
    )


def analyst_payload(credential_level: str = "SENIOR", **overrides: Any) -> Dict[str, Any]:
    """An enrollable privacy analyst."""
    n = next_sequence()
    return _merge(
        {
            "full_name": f"Morgan Ellis {n}",
            "credential_level": credential_level,
            "review_capacity_minutes": 1200,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Application request
# ---------------------------------------------------------------------------


def request_payload(
    application_id: str, requester_teacher_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A teacher's draft request for an application."""
    return _merge(
        {
            "application_id": application_id,
            "requester_teacher_id": requester_teacher_id,
            "instructional_justification": JUST_240,
            "requested_data_elements": [ELEMENT_STUDENT_NAME],
            "student_count_estimate": 300,
            "grade_band_low": 7,
            "grade_band_high": 8,
        },
        overrides,
    )


def submit_payload(**overrides: Any) -> Dict[str, Any]:
    """A submission body.  Every field is optional and overwrites the draft."""
    return dict(overrides)


def triage_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """A privacy-office triage decision on a submitted request."""
    return _merge({"disposition": disposition}, overrides)


# ---------------------------------------------------------------------------
# Data practice review
# ---------------------------------------------------------------------------


def review_payload(
    source_request_id: str,
    assigned_analyst_id: str,
    framework_set: Optional[List[str]] = None,
    estimated_minutes: int = 240,
    **overrides: Any,
) -> Dict[str, Any]:
    """A review opened against a triaged request."""
    return _merge(
        {
            "source_request_id": source_request_id,
            "assigned_analyst_id": assigned_analyst_id,
            "framework_set": list(framework_set or ALL_FRAMEWORKS),
            "estimated_minutes": estimated_minutes,
        },
        overrides,
    )


def findings_payload(findings_count: int, **overrides: Any) -> Dict[str, Any]:
    """A round of findings issued to the vendor."""
    return _merge({"findings_count": findings_count}, overrides)


def remediation_payload(resolved_findings_count: int, **overrides: Any) -> Dict[str, Any]:
    """The vendor's answer to the outstanding findings."""
    return _merge({"resolved_findings_count": resolved_findings_count}, overrides)


def decision_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """A lead analyst's terminal review decision."""
    return _merge({"disposition": disposition}, overrides)


def reassign_payload(assigned_analyst_id: str, **overrides: Any) -> Dict[str, Any]:
    """A reassignment to a different analyst."""
    return _merge({"assigned_analyst_id": assigned_analyst_id}, overrides)


# ---------------------------------------------------------------------------
# Data element commitment
# ---------------------------------------------------------------------------


def commitment_payload(
    review_id: str,
    element_code: str,
    expected_review_version: int,
    retention_days: int = 365,
    deletion_method: str = HARD_DELETE,
    **overrides: Any,
) -> Dict[str, Any]:
    """A data-element commitment carrying the review's concurrency token."""
    return _merge(
        {
            "review_id": review_id,
            "element_code": element_code,
            "justified_purpose": PURPOSE_61,
            "retention_days": retention_days,
            "deletion_method": deletion_method,
            "expected_review_version": expected_review_version,
        },
        overrides,
    )


def commitment_decision_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """An accept or reject on a commitment."""
    return _merge({"disposition": disposition}, overrides)


# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------


def catalog_entry_payload(
    application_id: str,
    review_id: str,
    effective_from: str,
    expires_at: str,
    authorized_grade_band_low: int = 7,
    authorized_grade_band_high: int = 8,
    **overrides: Any,
) -> Dict[str, Any]:
    """A publication window.  Both bounds are full ISO-8601 instants."""
    return _merge(
        {
            "application_id": application_id,
            "review_id": review_id,
            "effective_from": effective_from,
            "expires_at": expires_at,
            "authorized_grade_band_low": authorized_grade_band_low,
            "authorized_grade_band_high": authorized_grade_band_high,
        },
        overrides,
    )


def revoke_payload(revoked_reason: str, **overrides: Any) -> Dict[str, Any]:
    """An early revocation of a published authorization."""
    return _merge({"revoked_reason": revoked_reason}, overrides)


def reauthorize_payload(
    expires_at: str, expected_application_version: int, **overrides: Any
) -> Dict[str, Any]:
    """An annual reauthorization carrying the application's token."""
    return _merge(
        {
            "expires_at": expires_at,
            "expected_application_version": expected_application_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Telemetry detection
# ---------------------------------------------------------------------------


def detection_payload(
    observed_domain: str,
    observed_at: str,
    application_id: Optional[str] = None,
    distinct_user_count: int = 30,
    session_count: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """One collector observation.  `observed_at` is a full instant."""
    body: Dict[str, Any] = {
        "observed_domain": observed_domain,
        "school_code": "MS-04",
        "source": SOURCE_NETWORK_DNS,
        "observed_at": observed_at,
        "distinct_user_count": distinct_user_count,
        "session_count": session_count,
    }
    if application_id is not None:
        body["application_id"] = application_id
    return _merge(body, overrides)


def detection_triage_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """A triage decision on a detection."""
    return _merge({"disposition": disposition}, overrides)


# ---------------------------------------------------------------------------
# Vendor incident
# ---------------------------------------------------------------------------


def incident_payload(
    vendor_id: str,
    detected_at: str,
    affected_student_count: int = 30,
    max_data_tier: int = 3,
    incident_type: str = INCIDENT_BREACH,
    **overrides: Any,
) -> Dict[str, Any]:
    """A vendor self-report.  `detected_at` is a full instant."""
    return _merge(
        {
            "vendor_id": vendor_id,
            "incident_type": incident_type,
            "detected_at": detected_at,
            "affected_student_count": affected_student_count,
            "max_data_tier": max_data_tier,
        },
        overrides,
    )


def containment_payload(contained_at: Optional[str] = None, **overrides: Any):
    """Containment of a reported incident."""
    body: Dict[str, Any] = {}
    if contained_at is not None:
        body["contained_at"] = contained_at
    return _merge(body, overrides)


def notification_payload(notified_party_count: int, **overrides: Any) -> Dict[str, Any]:
    """The district's record that affected parties were told."""
    return _merge({"notified_party_count": notified_party_count}, overrides)


def resolution_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    """Closure of the incident response dimension."""
    return _merge({"disposition": disposition}, overrides)


def suspension_payload(reason: str = "District-wide privacy suspension", **overrides):
    """A district-wide vendor suspension."""
    return _merge({"reason": reason}, overrides)
