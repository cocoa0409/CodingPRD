"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment at the startup clock instant,
so each test builds the world it needs through the public API only. These
helpers do that walking and return the entity dicts, bound headers, and
observed versions the test then asserts against.

Conventions:
- Every function takes the ``ApiClient`` first and returns parsed ``data``.
- Setup calls use the lenient success reader, so a failure inside a fixture
  reports as a setup failure with the response body, not as a confusing
  assertion error.
- Registrar calls are always made with headers bound to the real
  jurisdiction id (``make_jurisdiction_registrar_headers``); a placeholder
  id would fail ownership and even driver registration.
- Time is the logical clock. Helpers that position a scenario in time call
  ``set_clock`` with an explicit instant, and date defaults anchor to the
  PRD's startup instant — never to the host wall clock.

World-building helpers return a context dict. ``setup_certified_jurisdiction``
produces::

    {
        "jurisdiction":       <Jurisdiction dict as last observed>,
        "jurisdiction_id":    <str>,
        "registrar_headers":  <headers bound to the jurisdiction id>,
        "participations":     {"POINTER_NETWORK": <SystemParticipation>, ...},
    }

Later builders (``setup_driver_record``, ``setup_verified_license``) extend
the same dict in place with ``driver`` / ``driver_id`` / ``driver_version`` /
``record`` / ``record_id`` / ``license`` / ``license_id``.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import (
    DEFAULT_CERT_WINDOW_END,
    DEFAULT_CERT_WINDOW_START,
    DEFAULT_CLOCK_ISO,
)
from .test_users import (
    ASSOCIATION_ADMIN_HEADERS,
    AUDIT_AUTHORITY_HEADERS,
    CERTIFICATION_ENGINEER_HEADERS,
    FEDERAL_VERIFIER_HEADERS,
    make_jurisdiction_registrar_headers,
)
from .types import (
    CertificationStatus,
    CheckType,
    ConvictionSeverity,
    LicenseClass,
    MembershipStatus,
    SystemName,
)

POINTER = SystemName.POINTER_NETWORK.value
COMMERCIAL = SystemName.COMMERCIAL_DRIVER_NETWORK.value
TITLE = SystemName.TITLE_NETWORK.value


# ═══ Tier 1: the logical clock ═══════════════════════════════════════════════

def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock to an explicit instant (AssociationAdmin)."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), ASSOCIATION_ADMIN_HEADERS))


def advance_clock_past(api: ApiClient, iso_date: str) -> Dict[str, Any]:
    """Set the logical clock to 00:00:00Z on the day after ``iso_date`` —
    the smallest move that makes a closed interval ending on ``iso_date``
    read as completed."""
    return set_clock(api, f.date_plus_days(iso_date, 1) + "T00:00:00Z")


# ═══ Tier 1: jurisdictions ═══════════════════════════════════════════════════

def create_jurisdiction(
    api: ApiClient,
    code: str = "AA",
    name: Optional[str] = None,
    fee_tier: str = "TIER_1",
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a jurisdiction (starts APPLIED). Returns the Jurisdiction."""
    return get_success_data(
        api.create_jurisdiction(
            f.jurisdiction_payload(code=code, name=name or f"State {code}", fee_tier=fee_tier, **overrides),
            ASSOCIATION_ADMIN_HEADERS,
        )
    )


def transition_jurisdiction(api: ApiClient, jurisdiction_id: str, status: str) -> Dict[str, Any]:
    """PATCH the membership status (AssociationAdmin). Returns the Jurisdiction."""
    return get_success_data(
        api.update_jurisdiction(
            jurisdiction_id, f.membership_transition_payload(status), ASSOCIATION_ADMIN_HEADERS
        )
    )


def activate_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    """APPLIED -> ACTIVE (or SUSPENDED -> ACTIVE). Caller must already hold a
    CERTIFIED POINTER_NETWORK participation for the APPLIED -> ACTIVE arc."""
    return transition_jurisdiction(api, jurisdiction_id, MembershipStatus.ACTIVE.value)


def suspend_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    """ACTIVE -> SUSPENDED; fires the participation/transfer cascades."""
    return transition_jurisdiction(api, jurisdiction_id, MembershipStatus.SUSPENDED.value)


def withdraw_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    """ACTIVE|SUSPENDED -> WITHDRAWN (terminal)."""
    return transition_jurisdiction(api, jurisdiction_id, MembershipStatus.WITHDRAWN.value)


def read_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_jurisdiction(jurisdiction_id, ASSOCIATION_ADMIN_HEADERS))


# ═══ Tier 2: participations and certifications ═══════════════════════════════

def enroll_participation(
    api: ApiClient, jurisdiction_id: str, system: str = POINTER
) -> Dict[str, Any]:
    """Enroll the jurisdiction in a system (starts ENROLLING). The registrar
    acts for its own jurisdiction."""
    return get_success_data(
        api.create_participation(
            f.participation_payload(jurisdiction_id, system),
            make_jurisdiction_registrar_headers(jurisdiction_id),
        )
    )


def schedule_certification(
    api: ApiClient,
    participation_id: str,
    window_start: str = DEFAULT_CERT_WINDOW_START,
    window_end: str = DEFAULT_CERT_WINDOW_END,
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule a certification window (CertificationEngineer). The default
    window contains the startup instant and every instant scenarios move the
    clock to; pass explicit bounds if the clock was moved past it."""
    return get_success_data(
        api.create_certification(
            f.certification_payload(participation_id, window_start, window_end, **overrides),
            CERTIFICATION_ENGINEER_HEADERS,
        )
    )


def complete_certification(
    api: ApiClient,
    certification_id: str,
    result: str = CertificationStatus.PASSED.value,
    score: Optional[int] = 95,
) -> Dict[str, Any]:
    """Record the certification result; the logical clock must sit inside
    [window_start, window_end)."""
    return get_success_data(
        api.complete_certification(
            certification_id,
            f.certification_completion_payload(result, score),
            CERTIFICATION_ENGINEER_HEADERS,
        )
    )


def grant_certification(api: ApiClient, participation_id: str) -> Dict[str, Any]:
    """Grant CERTIFIED (AssociationAdmin) after the latest completed
    certification PASSED. Returns the participation."""
    return get_success_data(api.grant_certification(participation_id, ASSOCIATION_ADMIN_HEADERS))


def certify_participation(
    api: ApiClient,
    participation_id: str,
    score: int = 95,
    window_start: str = DEFAULT_CERT_WINDOW_START,
    window_end: str = DEFAULT_CERT_WINDOW_END,
) -> Dict[str, Any]:
    """Schedule a window, record PASSED, and grant — the participation ends
    CERTIFIED. The logical clock must sit inside the window at completion."""
    certification = schedule_certification(
        api, participation_id, window_start=window_start, window_end=window_end
    )
    complete_certification(api, certification["id"], score=score)
    return grant_certification(api, participation_id)


def setup_certified_jurisdiction(
    api: ApiClient,
    code: str = "AA",
    systems: Sequence[str] = (POINTER,),
    fee_tier: str = "TIER_1",
    activate: bool = True,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Jurisdiction with every system in ``systems`` carried through
    ENROLLING -> TESTING -> CERTIFIED, optionally ending ACTIVE.

    Activation requires a CERTIFIED POINTER_NETWORK participation, so
    ``activate=True`` requires POINTER_NETWORK among ``systems``.
    """
    if activate and POINTER not in systems:
        raise ValueError("activation requires a CERTIFIED POINTER_NETWORK participation")
    jurisdiction = create_jurisdiction(api, code=code, name=name, fee_tier=fee_tier)
    jurisdiction_id = jurisdiction["id"]
    participations: Dict[str, Dict[str, Any]] = {}
    for system in systems:
        participation = enroll_participation(api, jurisdiction_id, system)
        participations[system] = certify_participation(api, participation["id"])
    if activate:
        jurisdiction = activate_jurisdiction(api, jurisdiction_id)
    return {
        "jurisdiction": jurisdiction,
        "jurisdiction_id": jurisdiction_id,
        "registrar_headers": make_jurisdiction_registrar_headers(jurisdiction_id),
        "participations": participations,
    }


def read_participations(api: ApiClient, jurisdiction_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(rows, meta) of a jurisdiction's participations, created_at ascending."""
    return validate_paginated(
        api.list_jurisdiction_participations(jurisdiction_id, ASSOCIATION_ADMIN_HEADERS)
    )


def read_certification(api: ApiClient, certification_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_certification(certification_id, ASSOCIATION_ADMIN_HEADERS))


def list_certifications(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_certifications(ASSOCIATION_ADMIN_HEADERS, params=params))


# ═══ Tier 3: drivers, records, licenses ══════════════════════════════════════

def register_driver(api: ApiClient, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a driver identity. The registrar's jurisdiction must exist;
    it need not be ACTIVE."""
    return get_success_data(
        api.create_driver(
            f.driver_payload(**overrides), make_jurisdiction_registrar_headers(jurisdiction_id)
        )
    )


def read_driver(api: ApiClient, driver_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_driver(driver_id, ASSOCIATION_ADMIN_HEADERS))


def current_driver_version(api: ApiClient, driver_id: str) -> int:
    """The driver identity's current version — read it here before either
    OCC-guarded write (record claim, transfer initiation)."""
    return int(read_driver(api, driver_id)["version"])


def claim_driver_record(
    api: ApiClient,
    driver_id: str,
    jurisdiction_id: str,
    expected_driver_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Claim the master record into the caller's jurisdiction. When no
    expected version is given, the driver's current version is read first.
    The jurisdiction must be ACTIVE with a CERTIFIED POINTER_NETWORK
    participation."""
    if expected_driver_version is None:
        expected_driver_version = current_driver_version(api, driver_id)
    return get_success_data(
        api.create_driver_record(
            f.driver_record_payload(driver_id, expected_driver_version),
            make_jurisdiction_registrar_headers(jurisdiction_id),
        )
    )


def setup_driver_record(api: ApiClient, ctx: Dict[str, Any], **driver_overrides: Any) -> Dict[str, Any]:
    """Extend a jurisdiction context with a registered driver and the ACTIVE
    record the jurisdiction claimed for them. Requires the jurisdiction to be
    ACTIVE with CERTIFIED POINTER_NETWORK."""
    driver = register_driver(api, ctx["jurisdiction_id"], **driver_overrides)
    record = claim_driver_record(api, driver["id"], ctx["jurisdiction_id"])
    ctx.update(
        driver=driver,
        driver_id=driver["id"],
        record=record,
        record_id=record["id"],
        driver_version=current_driver_version(api, driver["id"]),
    )
    return ctx


def read_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_driver_record(record_id, ASSOCIATION_ADMIN_HEADERS))


def list_driver_records(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_driver_records(ASSOCIATION_ADMIN_HEADERS, params=params))


def issue_license(
    api: ApiClient,
    driver_id: str,
    jurisdiction_id: str,
    license_class: str = LicenseClass.STANDARD.value,
) -> Dict[str, Any]:
    """Issue a license (starts PENDING_VERIFICATION). The driver must have an
    ACTIVE record held by this jurisdiction."""
    return get_success_data(
        api.create_license(
            f.license_payload(driver_id, license_class),
            make_jurisdiction_registrar_headers(jurisdiction_id),
        )
    )


def verify_license(
    api: ApiClient,
    license_id: str,
    ssn_result: str = "VERIFIED",
    lawful_status_result: str = "VERIFIED",
) -> Dict[str, Any]:
    """Post both verification dimensions (FederalVerifier) and return the
    license as the second response reports it. With both VERIFIED the license
    is ACTIVE; any FAILED denies it."""
    get_success_data(
        api.post_verification_result(
            license_id,
            f.verification_result_payload(CheckType.SSN.value, ssn_result),
            FEDERAL_VERIFIER_HEADERS,
        )
    )
    return get_success_data(
        api.post_verification_result(
            license_id,
            f.verification_result_payload(CheckType.LAWFUL_STATUS.value, lawful_status_result),
            FEDERAL_VERIFIER_HEADERS,
        )
    )


def setup_verified_license(
    api: ApiClient,
    ctx: Dict[str, Any],
    license_class: str = LicenseClass.STANDARD.value,
    **driver_overrides: Any,
) -> Dict[str, Any]:
    """Extend a jurisdiction context with driver + ACTIVE record + a license
    whose two verification dimensions both landed VERIFIED (status ACTIVE)."""
    if "record_id" not in ctx:
        setup_driver_record(api, ctx, **driver_overrides)
    license_body = issue_license(api, ctx["driver_id"], ctx["jurisdiction_id"], license_class)
    license_body = verify_license(api, license_body["id"])
    ctx.update(license=license_body, license_id=license_body["id"])
    return ctx


def read_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_license(license_id, ASSOCIATION_ADMIN_HEADERS))


def list_licenses(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_licenses(ASSOCIATION_ADMIN_HEADERS, params=params))


def reinstate_license(api: ApiClient, license_id: str, issuing_jurisdiction_id: str) -> Dict[str, Any]:
    """SUSPENDED -> ACTIVE by a registrar of the issuing jurisdiction."""
    return get_success_data(
        api.reinstate_license(
            license_id, make_jurisdiction_registrar_headers(issuing_jurisdiction_id)
        )
    )


# ═══ Tier 4: convictions and disqualifications ═══════════════════════════════

def setup_conviction_world(api: ApiClient, code: str = "AA", **driver_overrides: Any) -> Dict[str, Any]:
    """ACTIVE jurisdiction certified for POINTER_NETWORK and
    COMMERCIAL_DRIVER_NETWORK, plus a driver whose ACTIVE record it holds —
    the minimal world in which convictions can be posted."""
    ctx = setup_certified_jurisdiction(api, code=code, systems=(POINTER, COMMERCIAL))
    return setup_driver_record(api, ctx, **driver_overrides)


def post_conviction(
    api: ApiClient,
    record_id: str,
    holding_jurisdiction_id: str,
    offense_date: Optional[str] = None,
    conviction_date: Optional[str] = None,
    severity: str = ConvictionSeverity.NON_CMV.value,
    points: int = 2,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post a conviction to a record the caller's jurisdiction holds. Dates
    default to a timely posting relative to ``clock_iso`` — the instant the
    logical clock reads; pass explicit dates (and the matching ``clock_iso``)
    whenever the scenario moved the clock or probes a boundary."""
    return get_success_data(
        api.create_conviction(
            f.conviction_payload(
                record_id,
                offense_date=offense_date,
                conviction_date=conviction_date,
                severity=severity,
                points=points,
                clock_iso=clock_iso,
                **overrides,
            ),
            make_jurisdiction_registrar_headers(holding_jurisdiction_id),
        )
    )


def post_convictions(
    api: ApiClient,
    record_id: str,
    holding_jurisdiction_id: str,
    specs: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Post several convictions in order; each spec carries the keyword
    arguments of ``post_conviction`` (dates, severity, points)."""
    return [
        post_conviction(api, record_id, holding_jurisdiction_id, **spec) for spec in specs
    ]


def read_record_convictions(api: ApiClient, record_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_record_convictions(record_id, ASSOCIATION_ADMIN_HEADERS)
    )
    return rows


def create_manual_disqualification(
    api: ApiClient, record_id: str, start_date: str, end_date: str, **overrides: Any
) -> Dict[str, Any]:
    """Record a judicial disqualification (AuditAuthority) with explicit
    closed-interval dates."""
    return get_success_data(
        api.create_disqualification(
            f.disqualification_payload(record_id, start_date, end_date, **overrides),
            AUDIT_AUTHORITY_HEADERS,
        )
    )


def overturn_disqualification(api: ApiClient, disqualification_id: str) -> Dict[str, Any]:
    """ACTIVE -> OVERTURNED (AuditAuthority). Returns the disqualification."""
    return get_success_data(
        api.overturn_disqualification(disqualification_id, AUDIT_AUTHORITY_HEADERS)
    )


def read_record_disqualifications(api: ApiClient, record_id: str) -> List[Dict[str, Any]]:
    """Disqualifications of a record with derived statuses evaluated against
    the current logical clock."""
    rows, _ = validate_paginated(
        api.list_record_disqualifications(record_id, ASSOCIATION_ADMIN_HEADERS)
    )
    return rows


def setup_suspended_commercial_license(
    api: ApiClient, code: str = "AA", conviction: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """World where a verified COMMERCIAL license has been dropped to
    SUSPENDED by an AUTO_MAJOR disqualification: ACTIVE jurisdiction certified
    for POINTER + COMMERCIAL, driver record held, verified COMMERCIAL license,
    then one CMV_MAJOR conviction. Returns the context extended with
    ``disqualification`` (re-read so the derived status is fresh)."""
    ctx = setup_certified_jurisdiction(api, code=code, systems=(POINTER, COMMERCIAL))
    setup_verified_license(api, ctx, license_class=LicenseClass.COMMERCIAL.value)
    spec = {
        "offense_date": "2026-08-15",
        "conviction_date": "2026-08-25",
        "severity": ConvictionSeverity.CMV_MAJOR.value,
        "points": 6,
    }
    if conviction:
        spec.update(conviction)
    post_conviction(api, ctx["record_id"], ctx["jurisdiction_id"], **spec)
    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    ctx.update(
        disqualification=disqualifications[0] if disqualifications else None,
        license=read_license(api, ctx["license_id"]),
    )
    return ctx


# ═══ Tier 4: license transfers ═══════════════════════════════════════════════

def initiate_transfer(
    api: ApiClient,
    driver_id: str,
    prior_license_id: str,
    to_jurisdiction_id: str,
    expected_driver_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Initiate a transfer into the caller's jurisdiction. When no expected
    version is given, the driver's current version is read first."""
    if expected_driver_version is None:
        expected_driver_version = current_driver_version(api, driver_id)
    return get_success_data(
        api.create_license_transfer(
            f.license_transfer_payload(driver_id, prior_license_id, expected_driver_version),
            make_jurisdiction_registrar_headers(to_jurisdiction_id),
        )
    )


def surrender_transfer(api: ApiClient, transfer_id: str, from_jurisdiction_id: str) -> Dict[str, Any]:
    """INITIATED|CONTESTED -> SURRENDER_RECORDED by the sending side; the
    prior license goes SURRENDERED and any contest reason clears."""
    return get_success_data(
        api.record_surrender(
            transfer_id, make_jurisdiction_registrar_headers(from_jurisdiction_id)
        )
    )


def contest_transfer(
    api: ApiClient, transfer_id: str, to_jurisdiction_id: str, reason: str = "DATA_MISMATCH"
) -> Dict[str, Any]:
    """SURRENDER_RECORDED -> CONTESTED by the receiving side; the prior
    license walks back to ACTIVE while the dispute runs."""
    return get_success_data(
        api.contest_transfer(
            transfer_id,
            f.contest_payload(reason),
            make_jurisdiction_registrar_headers(to_jurisdiction_id),
        )
    )


def complete_transfer(api: ApiClient, transfer_id: str, to_jurisdiction_id: str) -> Dict[str, Any]:
    """SURRENDER_RECORDED -> COMPLETED by the receiving side: the record
    moves and a fresh PENDING_VERIFICATION license is created."""
    return get_success_data(
        api.complete_transfer(
            transfer_id, make_jurisdiction_registrar_headers(to_jurisdiction_id)
        )
    )


def read_license_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_license_transfer(transfer_id, ASSOCIATION_ADMIN_HEADERS))


def list_license_transfers(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_license_transfers(ASSOCIATION_ADMIN_HEADERS, params=params))


def setup_transfer_world(
    api: ApiClient,
    from_code: str = "AA",
    to_code: str = "BB",
    license_class: str = LicenseClass.STANDARD.value,
    stage: str = "INITIATED",
    contest_reason: str = "DATA_MISMATCH",
    **driver_overrides: Any,
) -> Dict[str, Any]:
    """Two ACTIVE jurisdictions (POINTER_NETWORK certified on both), a driver
    whose ACTIVE record and verified license live on the sending side, and a
    transfer into the receiving side walked to ``stage`` — one of INITIATED,
    SURRENDER_RECORDED, CONTESTED, COMPLETED. CONTESTED walks
    INITIATED -> SURRENDER_RECORDED -> CONTESTED; COMPLETED walks
    INITIATED -> SURRENDER_RECORDED -> COMPLETED.

    Returns ``{"from_ctx", "to_ctx", "transfer", "transfer_id",
    "driver_version"}`` where ``from_ctx`` also carries the driver, record and
    prior license, and ``driver_version`` is the current version after
    initiation.
    """
    from_ctx = setup_certified_jurisdiction(api, code=from_code, systems=(POINTER,))
    setup_verified_license(api, from_ctx, license_class=license_class, **driver_overrides)
    to_ctx = setup_certified_jurisdiction(api, code=to_code, systems=(POINTER,))
    transfer = initiate_transfer(
        api, from_ctx["driver_id"], from_ctx["license_id"], to_ctx["jurisdiction_id"]
    )
    if stage in ("SURRENDER_RECORDED", "CONTESTED", "COMPLETED"):
        transfer = surrender_transfer(api, transfer["id"], from_ctx["jurisdiction_id"])
    if stage == "CONTESTED":
        transfer = contest_transfer(api, transfer["id"], to_ctx["jurisdiction_id"], contest_reason)
    elif stage == "COMPLETED":
        transfer = complete_transfer(api, transfer["id"], to_ctx["jurisdiction_id"])
    elif stage != "INITIATED" and stage not in ("SURRENDER_RECORDED", "CONTESTED"):
        raise ValueError(f"unknown transfer stage {stage!r}")
    return {
        "from_ctx": from_ctx,
        "to_ctx": to_ctx,
        "transfer": transfer,
        "transfer_id": transfer["id"],
        "driver_version": current_driver_version(api, from_ctx["driver_id"]),
    }


# ═══ Tier 4: vehicle titles and title transfers ══════════════════════════════

def create_vehicle_title(
    api: ApiClient,
    jurisdiction_id: str,
    vin: str = "1HGCM82633A004352",
    brands: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Title a vehicle in the caller's jurisdiction (ACTIVE + CERTIFIED
    TITLE_NETWORK required). ``brands=None`` omits the field so the default
    empty set applies."""
    return get_success_data(
        api.create_vehicle_title(
            f.vehicle_title_payload(vin, brands, **overrides),
            make_jurisdiction_registrar_headers(jurisdiction_id),
        )
    )


def create_title_transfer(
    api: ApiClient,
    vehicle_title_id: str,
    to_jurisdiction_id: str,
    disclosed_brands: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Request an interstate re-titling; the brand-washing check runs
    synchronously at creation. On success the transfer is VERIFIED."""
    return get_success_data(
        api.create_title_transfer(
            f.title_transfer_payload(vehicle_title_id, disclosed_brands, **overrides),
            make_jurisdiction_registrar_headers(to_jurisdiction_id),
        )
    )


def complete_title_transfer(api: ApiClient, transfer_id: str, to_jurisdiction_id: str) -> Dict[str, Any]:
    """VERIFIED -> COMPLETED: source title EXPORTED, new title minted in the
    receiving jurisdiction carrying the carried brands."""
    return get_success_data(
        api.complete_title_transfer(
            transfer_id, make_jurisdiction_registrar_headers(to_jurisdiction_id)
        )
    )


def read_title_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_title_transfer(transfer_id, ASSOCIATION_ADMIN_HEADERS))


def list_title_transfers(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_title_transfers(ASSOCIATION_ADMIN_HEADERS, params=params))


def list_jurisdiction_titles(
    api: ApiClient, jurisdiction_id: str, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(rows, meta) of titles a jurisdiction holds — the way to read a title's
    current state, since titles have no single-get endpoint."""
    return validate_paginated(
        api.list_jurisdiction_vehicle_titles(jurisdiction_id, ASSOCIATION_ADMIN_HEADERS, params=params)
    )


def setup_title_world(
    api: ApiClient,
    from_code: str = "AA",
    to_code: str = "BB",
    vin: str = "1HGCM82633A004352",
    source_brands: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Two ACTIVE jurisdictions each certified for POINTER_NETWORK and
    TITLE_NETWORK, with an ACTIVE source title held by the sending side."""
    from_ctx = setup_certified_jurisdiction(api, code=from_code, systems=(POINTER, TITLE))
    to_ctx = setup_certified_jurisdiction(api, code=to_code, systems=(POINTER, TITLE))
    title = create_vehicle_title(api, from_ctx["jurisdiction_id"], vin, source_brands)
    return {"from_ctx": from_ctx, "to_ctx": to_ctx, "title": title, "title_id": title["id"]}


# ═══ Tier 5: fee invoices ════════════════════════════════════════════════════

def issue_fee_invoice(
    api: ApiClient,
    jurisdiction_id: str,
    fiscal_year: int = 2027,
    projected_volume: int = 8000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Issue the annual dues invoice (AssociationAdmin); created ISSUED with
    the certified count pinned and the provisional amount computed."""
    return get_success_data(
        api.create_fee_invoice(
            f.fee_invoice_payload(jurisdiction_id, fiscal_year, projected_volume, **overrides),
            ASSOCIATION_ADMIN_HEADERS,
        )
    )


def dispute_invoice(
    api: ApiClient, invoice_id: str, jurisdiction_id: str, reason: str = "VOLUME_OVERSTATED"
) -> Dict[str, Any]:
    """ISSUED -> DISPUTED by the invoiced jurisdiction's registrar."""
    return get_success_data(
        api.dispute_invoice(
            invoice_id,
            f.dispute_payload(reason),
            make_jurisdiction_registrar_headers(jurisdiction_id),
        )
    )


def reissue_invoice(api: ApiClient, invoice_id: str, projected_volume: int) -> Dict[str, Any]:
    """DISPUTED -> ISSUED (AssociationAdmin) with a corrected projected
    volume; the pinned certified count survives."""
    return get_success_data(
        api.reissue_invoice(invoice_id, f.reissue_payload(projected_volume), ASSOCIATION_ADMIN_HEADERS)
    )


def settle_invoice(
    api: ApiClient, invoice: Dict[str, Any], amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    """ISSUED -> SETTLED by the invoiced jurisdiction's registrar. With no
    explicit amount, pays exactly the invoice's provisional amount."""
    if amount_cents is None:
        amount_cents = invoice["provisional_amount_cents"]
    return get_success_data(
        api.settle_invoice(
            invoice["id"],
            f.settle_payload(amount_cents),
            make_jurisdiction_registrar_headers(invoice["jurisdiction_id"]),
        )
    )


def finalize_audit(
    api: ApiClient, invoice_id: str, actual_volume_quarters: Sequence[int]
) -> Dict[str, Any]:
    """SETTLED -> AUDITED (AuditAuthority) with exactly four quarterly
    volumes; computes the final and adjustment amounts."""
    return get_success_data(
        api.finalize_audit(
            invoice_id, f.finalize_audit_payload(actual_volume_quarters), AUDIT_AUTHORITY_HEADERS
        )
    )


def list_jurisdiction_invoices(
    api: ApiClient, jurisdiction_id: str, params: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(rows, meta) of a jurisdiction's invoices — the way to read an
    invoice's current state, since invoices have no single-get endpoint."""
    return validate_paginated(
        api.list_jurisdiction_fee_invoices(jurisdiction_id, ASSOCIATION_ADMIN_HEADERS, params=params)
    )


def setup_invoice(
    api: ApiClient,
    code: str = "AA",
    systems: Sequence[str] = (POINTER,),
    fee_tier: str = "TIER_1",
    fiscal_year: int = 2027,
    projected_volume: int = 8000,
    stage: str = "ISSUED",
    dispute_reason: str = "VOLUME_OVERSTATED",
) -> Dict[str, Any]:
    """ACTIVE jurisdiction (certified for ``systems``) with an invoice walked
    to ``stage`` — ISSUED, DISPUTED, or SETTLED (settled at the provisional
    amount). Returns the jurisdiction context extended with ``invoice`` /
    ``invoice_id`` / ``provisional_amount_cents``."""
    ctx = setup_certified_jurisdiction(api, code=code, systems=systems, fee_tier=fee_tier)
    invoice = issue_fee_invoice(api, ctx["jurisdiction_id"], fiscal_year, projected_volume)
    if stage == "DISPUTED":
        invoice = dispute_invoice(api, invoice["id"], ctx["jurisdiction_id"], dispute_reason)
    elif stage == "SETTLED":
        invoice = settle_invoice(api, invoice)
    elif stage != "ISSUED":
        raise ValueError(f"unknown invoice stage {stage!r}")
    ctx.update(
        invoice=invoice,
        invoice_id=invoice["id"],
        provisional_amount_cents=invoice["provisional_amount_cents"],
    )
    return ctx
