"""Composite setup helpers.

Every test runs against a freshly launched server with an empty database and
the logical clock booted at 2026-09-01T00:00:00Z, so every helper here builds
its preconditions from scratch using only PRD-declared endpoints. Nothing is
cached at module level; every call re-creates its world through the API.

Identity threading: LabAgent calls always carry the acting laboratory's id
(make_lab_agent_headers(lab["id"])) and ElectionOfficial calls carry the
acting official's id (make_election_official_headers(official["id"])). The
opaque roles use their shared constants.

All helpers use the lenient get_success_data() validator so a setup failure
surfaces as a clear setup error rather than an assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BOOT_CLOCK_ISO
from .factories import (
    DEFAULTS,
    budget_adjustment_payload,
    campaign_transition_payload,
    certificate_transition_payload,
    create_acceptance_test_payload,
    create_campaign_payload,
    create_custody_transfer_payload,
    create_election_definition_payload,
    create_equipment_unit_payload,
    create_jurisdiction_payload,
    create_la_test_payload,
    create_official_payload,
    create_post_election_audit_payload,
    create_procurement_payload,
    create_software_modification_payload,
    create_test_laboratory_payload,
    create_voting_system_payload,
    create_work_order_payload,
    election_definition_transition_payload,
    la_test_transition_payload,
    official_transition_payload,
    post_election_audit_transition_payload,
    procurement_transition_payload,
    put_layout_payload,
    record_usage_payload,
    set_clock_payload,
    software_modification_transition_payload,
    work_order_transition_payload,
    equipment_unit_transition_payload,
)
from .test_users import (
    TEST_USERS,
    make_election_official_headers,
    make_lab_agent_headers,
)

# Opaque-role header shortcuts (no ownership checks ever bind these).
ADMIN = TEST_USERS["platform_admin_headers"]
AUTHORITY = TEST_USERS["certification_authority_headers"]
VENDOR = TEST_USERS["vendor_rep_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
PUBLIC = TEST_USERS["public_requester_headers"]


# ==========================================================================
# Tier 0 — clock + plain creates + reads
# ==========================================================================
def set_clock(to_iso8601: str = BOOT_CLOCK_ISO) -> str:
    """Advance the logical clock (forward-only at call sites) and return the
    resulting current_utc."""
    data = get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN))
    return data["current_utc"]


def create_voting_system(**overrides) -> dict:
    """Register a voting system (PlatformAdmin); starts REGISTERED."""
    return get_success_data(
        api_client.create_voting_system(create_voting_system_payload(**overrides), ADMIN)
    )


def get_voting_system(system_id: str) -> dict:
    return get_success_data(api_client.get_voting_system(system_id, AUDITOR))


def create_test_laboratory(**overrides) -> dict:
    """Accredit a test laboratory (PlatformAdmin); starts ACCREDITED."""
    return get_success_data(
        api_client.create_test_laboratory(create_test_laboratory_payload(**overrides), ADMIN)
    )


def create_campaign(voting_system_id: str, lab_id: str, **overrides) -> dict:
    """Submit a certification campaign (VendorRep); starts SUBMITTED."""
    return get_success_data(
        api_client.create_certification_campaign(
            create_campaign_payload(voting_system_id, lab_id, **overrides), VENDOR
        )
    )


def get_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_certification_campaign(campaign_id, AUDITOR))


def create_jurisdiction(**overrides) -> dict:
    """Create a jurisdiction (PlatformAdmin); available == budget_total."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN)
    )


def get_jurisdiction(jurisdiction_id: str) -> dict:
    return get_success_data(api_client.get_jurisdiction(jurisdiction_id, AUDITOR))


def adjust_budget(jurisdiction_id: str, delta_cents: int, reason: str = "adjustment") -> dict:
    return get_success_data(
        api_client.create_budget_adjustment(
            jurisdiction_id, budget_adjustment_payload(delta_cents, reason), ADMIN
        )
    )


def create_official(jurisdiction_id: str, **overrides) -> dict:
    """Enroll an election official (PlatformAdmin); starts ACTIVE."""
    return get_success_data(
        api_client.create_official(jurisdiction_id, create_official_payload(**overrides), ADMIN)
    )


def set_official_status(official_id: str, to_state: str) -> dict:
    """ACTIVE <-> INACTIVE (PlatformAdmin)."""
    return get_success_data(
        api_client.transition_official(
            official_id, official_transition_payload(to_state), ADMIN
        )
    )


# ==========================================================================
# Tier 1 — campaign lifecycle (certification pipeline)
# ==========================================================================
def begin_campaign_testing(campaign_id: str, lab_id: str) -> dict:
    """SUBMITTED -> IN_TEST as the campaign's own laboratory agent."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id,
            campaign_transition_payload("IN_TEST"),
            make_lab_agent_headers(lab_id),
        )
    )


def file_deficiencies(
    campaign_id: str, lab_id: str, critical_count: int, major_count: int, minor_count: int
) -> dict:
    """IN_TEST -> DEFICIENCIES_FILED with the given counts."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id,
            campaign_transition_payload(
                "DEFICIENCIES_FILED",
                critical_count=critical_count,
                major_count=major_count,
                minor_count=minor_count,
            ),
            make_lab_agent_headers(lab_id),
        )
    )


def resubmit_campaign(
    campaign_id: str,
    resolved_critical: int,
    resolved_major: int,
    resolved_minor: int,
) -> dict:
    """DEFICIENCIES_FILED -> SUBMITTED (VendorRep; all-or-nothing resolution)."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id,
            campaign_transition_payload(
                "SUBMITTED",
                resolved_critical=resolved_critical,
                resolved_major=resolved_major,
                resolved_minor=resolved_minor,
            ),
            VENDOR,
        )
    )


def certify_campaign(campaign_id: str) -> dict:
    """IN_TEST -> CERTIFIED (CertificationAuthority); mints the certificate."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id, campaign_transition_payload("CERTIFIED"), AUTHORITY
        )
    )


def deny_campaign(campaign_id: str) -> dict:
    """DEFICIENCIES_FILED -> DENIED (CertificationAuthority)."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id, campaign_transition_payload("DENIED"), AUTHORITY
        )
    )


def withdraw_campaign(campaign_id: str) -> dict:
    """SUBMITTED|DEFICIENCIES_FILED -> WITHDRAWN (VendorRep)."""
    return get_success_data(
        api_client.transition_certification_campaign(
            campaign_id, campaign_transition_payload("WITHDRAWN"), VENDOR
        )
    )


def get_certificate_for_campaign(campaign_id: str) -> dict:
    """Fetch the certificate minted by a certifying campaign via the registry
    list filtered by campaign_id."""
    data = get_success_data(
        api_client.list_certificates(AUDITOR, params={"campaign_id": campaign_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one certificate for campaign {campaign_id}, got {data!r}"
    )
    return data[0]


def get_certificate(certificate_id: str) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, AUDITOR))


def transition_certificate(certificate_id: str, to_state: str, **extras) -> dict:
    """Certificate lifecycle (CertificationAuthority): SUSPENDED / ACTIVE /
    REVOKED."""
    return get_success_data(
        api_client.transition_certificate(
            certificate_id, certificate_transition_payload(to_state, **extras), AUTHORITY
        )
    )


# ==========================================================================
# Tier 1 — procurement pipeline
# ==========================================================================
def create_procurement(
    jurisdiction_id: str,
    voting_system_id: str,
    certificate_id: str,
    acting_official_id: str,
    **overrides,
) -> dict:
    """Place a procurement as a jurisdiction official; starts PLACED."""
    return get_success_data(
        api_client.create_procurement(
            create_procurement_payload(
                jurisdiction_id, voting_system_id, certificate_id, **overrides
            ),
            make_election_official_headers(acting_official_id),
        )
    )


def get_procurement(procurement_id: str) -> dict:
    return get_success_data(api_client.get_procurement(procurement_id, AUDITOR))


def transition_procurement(procurement_id: str, to_state: str, acting_official_id: str, **extras) -> dict:
    return get_success_data(
        api_client.transition_procurement(
            procurement_id,
            procurement_transition_payload(to_state, **extras),
            make_election_official_headers(acting_official_id),
        )
    )


def record_acceptance_test(procurement_id: str, acting_official_id: str, **overrides) -> dict:
    """Record an acceptance test against a procurement in ACCEPTANCE_TESTING."""
    return get_success_data(
        api_client.create_acceptance_test(
            procurement_id,
            create_acceptance_test_payload(**overrides),
            make_election_official_headers(acting_official_id),
        )
    )


# ==========================================================================
# Tier 1 — election definition pipeline
# ==========================================================================
def create_election_definition(
    jurisdiction_id: str, procurement_id: str, acting_official_id: str, **overrides
) -> dict:
    """Create a DRAFT election definition against an in-flight or accepted
    procurement."""
    return get_success_data(
        api_client.create_election_definition(
            create_election_definition_payload(jurisdiction_id, procurement_id, **overrides),
            make_election_official_headers(acting_official_id),
        )
    )


def get_election_definition(definition_id: str) -> dict:
    return get_success_data(api_client.get_election_definition(definition_id, AUDITOR))


def store_layout(definition_id: str, acting_official_id: str, base_version=None, **overrides) -> dict:
    """OCC-guarded layout store. When base_version is None the definition is
    re-read and its current version used, keeping the happy path fresh."""
    if base_version is None:
        base_version = get_election_definition(definition_id)["version"]
    return get_success_data(
        api_client.put_layout(
            definition_id,
            put_layout_payload(base_version, **overrides),
            make_election_official_headers(acting_official_id),
        )
    )


def transition_election_definition(
    definition_id: str, to_state: str, acting_official_id: str, **extras
) -> dict:
    return get_success_data(
        api_client.transition_election_definition(
            definition_id,
            election_definition_transition_payload(to_state, **extras),
            make_election_official_headers(acting_official_id),
        )
    )


def create_la_test(definition_id: str, conductor_official_id: str, **overrides) -> dict:
    """Conduct an L&A test; conducted_by is set from the acting official."""
    return get_success_data(
        api_client.create_la_test(
            definition_id,
            create_la_test_payload(**overrides),
            make_election_official_headers(conductor_official_id),
        )
    )


def transition_la_test(la_test_id: str, to_state: str, acting_official_id: str, **extras) -> dict:
    return get_success_data(
        api_client.transition_la_test(
            la_test_id,
            la_test_transition_payload(to_state, **extras),
            make_election_official_headers(acting_official_id),
        )
    )


def certify_la_test(la_test_id: str, certifier_official_id: str) -> dict:
    """CONDUCTED -> CERTIFIED; the certifier must differ from the conductor
    (segregation of duties)."""
    return transition_la_test(la_test_id, "CERTIFIED", certifier_official_id)


# ==========================================================================
# Tier 1 — equipment units, custody, work orders
# ==========================================================================
def create_equipment_unit(
    jurisdiction_id: str,
    voting_system_id: str,
    initial_custodian_id: str,
    acting_official_id: str = None,
    **overrides,
) -> dict:
    """Register a unit (ElectionOfficial of the jurisdiction). The acting
    official defaults to the initial custodian."""
    acting = acting_official_id or initial_custodian_id
    return get_success_data(
        api_client.create_equipment_unit(
            create_equipment_unit_payload(
                jurisdiction_id, voting_system_id, initial_custodian_id, **overrides
            ),
            make_election_official_headers(acting),
        )
    )


def get_equipment_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_equipment_unit(unit_id, AUDITOR))


def transition_equipment_unit(unit_id: str, to_state: str, headers, **extras) -> dict:
    """Unit lifecycle. Deploy/store/retire use a jurisdiction official's
    headers; quarantine and quarantine-release use the authority's."""
    return get_success_data(
        api_client.transition_equipment_unit(
            unit_id, equipment_unit_transition_payload(to_state, **extras), headers
        )
    )


def deploy_unit(unit_id: str, acting_official_id: str) -> dict:
    """IN_STORAGE -> IN_SERVICE."""
    return transition_equipment_unit(
        unit_id, "IN_SERVICE", make_election_official_headers(acting_official_id)
    )


def store_unit(
    unit_id: str,
    acting_official_id: str,
    storage_temperature_c: int = DEFAULTS["STORAGE_TEMPERATURE_C"],
    storage_humidity_pct: int = DEFAULTS["STORAGE_HUMIDITY_PCT"],
) -> dict:
    """IN_SERVICE -> IN_STORAGE with environment readings (in-band defaults)."""
    return transition_equipment_unit(
        unit_id,
        "IN_STORAGE",
        make_election_official_headers(acting_official_id),
        storage_temperature_c=storage_temperature_c,
        storage_humidity_pct=storage_humidity_pct,
    )


def record_usage(unit_id: str, acting_official_id: str, cycles_used: int) -> dict:
    return get_success_data(
        api_client.record_usage(
            unit_id,
            record_usage_payload(cycles_used),
            make_election_official_headers(acting_official_id),
        )
    )


def transfer_custody(
    unit_id: str, from_official_id: str, to_official_id: str, **overrides
) -> dict:
    """Record a custody transfer; the actor is the unit's current custodian."""
    return get_success_data(
        api_client.create_custody_transfer(
            unit_id,
            create_custody_transfer_payload(to_official_id, **overrides),
            make_election_official_headers(from_official_id),
        )
    )


def create_work_order(unit_id: str, acting_official_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(unit_id, **overrides),
            make_election_official_headers(acting_official_id),
        )
    )


def transition_work_order(work_order_id: str, to_state: str, acting_official_id: str, **extras) -> dict:
    return get_success_data(
        api_client.transition_work_order(
            work_order_id,
            work_order_transition_payload(to_state, **extras),
            make_election_official_headers(acting_official_id),
        )
    )


def start_work_order(work_order_id: str, acting_official_id: str) -> dict:
    """SCHEDULED -> IN_PROGRESS; the unit moves to IN_MAINTENANCE."""
    return transition_work_order(work_order_id, "IN_PROGRESS", acting_official_id)


def complete_work_order(work_order_id: str, acting_official_id: str, resolution_note: str = "done") -> dict:
    return transition_work_order(
        work_order_id, "COMPLETED", acting_official_id, resolution_note=resolution_note
    )


def abort_work_order(work_order_id: str, acting_official_id: str, **extras) -> dict:
    return transition_work_order(work_order_id, "ABORTED", acting_official_id, **extras)


# ==========================================================================
# Tier 1 — software modifications
# ==========================================================================
def propose_modification(
    voting_system_id: str, expected_voting_system_version=None, **overrides
) -> dict:
    """Propose a software modification (VendorRep). The OCC field
    expected_voting_system_version defaults to the system's freshly read
    current version; pass it explicitly to exercise the stale-version path."""
    if expected_voting_system_version is None:
        expected_voting_system_version = get_voting_system(voting_system_id)["version"]
    return get_success_data(
        api_client.create_software_modification(
            create_software_modification_payload(
                voting_system_id, expected_voting_system_version, **overrides
            ),
            VENDOR,
        )
    )


def transition_software_modification(modification_id: str, to_state: str, headers, **extras) -> dict:
    return get_success_data(
        api_client.transition_software_modification(
            modification_id,
            software_modification_transition_payload(to_state, **extras),
            headers,
        )
    )


def classify_modification_de_minimis(modification_id: str) -> dict:
    """PROPOSED -> DE_MINIMIS_APPROVED (CertificationAuthority)."""
    return transition_software_modification(modification_id, "DE_MINIMIS_APPROVED", AUTHORITY)


def classify_modification_recertification(modification_id: str) -> dict:
    """PROPOSED -> RECERTIFICATION_PENDING (CertificationAuthority); fires the
    certificate-suspension cascade after computing lead_time_days."""
    return transition_software_modification(modification_id, "RECERTIFICATION_PENDING", AUTHORITY)


def apply_modification(modification_id: str, new_baseline_version: str = "1.0.1") -> dict:
    """Classified -> EFFECTIVE (VendorRep) with the new baseline string."""
    return transition_software_modification(
        modification_id, "EFFECTIVE", VENDOR, new_baseline_version=new_baseline_version
    )


# ==========================================================================
# Tier 1 — post-election audits
# ==========================================================================
def open_audit(election_definition_id: str, **overrides) -> dict:
    """Open a post-election audit (Auditor) on a CANVASSING definition."""
    return get_success_data(
        api_client.create_post_election_audit(
            create_post_election_audit_payload(election_definition_id, **overrides), AUDITOR
        )
    )


def transition_audit(audit_id: str, to_state: str, **extras) -> dict:
    return get_success_data(
        api_client.transition_post_election_audit(
            audit_id, post_election_audit_transition_payload(to_state, **extras), AUDITOR
        )
    )


def file_findings(audit_id: str, critical_findings: int, major_findings: int, minor_findings: int) -> dict:
    return transition_audit(
        audit_id,
        "FINDINGS_FILED",
        critical_findings=critical_findings,
        major_findings=major_findings,
        minor_findings=minor_findings,
    )


def publish_audit(audit_id: str) -> dict:
    return get_success_data(api_client.publish_post_election_audit(audit_id, AUDITOR))


# ==========================================================================
# Tier 2 — composite scenario builders
# ==========================================================================
def setup_certified_system(
    state_code=DEFAULTS["STATE_CODE"],
    lab_scope=DEFAULTS["ACCREDITATION_SCOPE"],
    system_overrides=None,
    lab_overrides=None,
    campaign_overrides=None,
) -> dict:
    """Full certification pipeline: voting system + laboratory + campaign
    carried SUBMITTED -> IN_TEST -> CERTIFIED. Returns the system (FIELDED
    after certification), the lab, the campaign and the minted certificate.

    state_code=None produces a FEDERAL-scope certificate (federal-only
    campaign); any two-letter code produces a STATE-scope certificate.
    """
    system = create_voting_system(**(system_overrides or {}))
    lab = create_test_laboratory(
        **({"accreditation_scope": lab_scope} | (lab_overrides or {}))
    )
    campaign = create_campaign(
        system["id"], lab["id"], **({"state_code": state_code} | (campaign_overrides or {}))
    )
    begin_campaign_testing(campaign["id"], lab["id"])
    campaign = certify_campaign(campaign["id"])
    certificate = get_certificate_for_campaign(campaign["id"])
    system = get_voting_system(system["id"])
    return {"system": system, "lab": lab, "campaign": campaign, "certificate": certificate}


def setup_jurisdiction_with_officials(
    official_count: int = 2,
    budget_total_cents: int = DEFAULTS["BUDGET_TOTAL_CENTS"],
    state_code: str = DEFAULTS["STATE_CODE"],
    name: str = DEFAULTS["JURISDICTION_NAME"],
) -> dict:
    """A jurisdiction with official_count ACTIVE officials enrolled.
    officials[0] is the primary actor; officials[1] the SoD certifier."""
    jurisdiction = create_jurisdiction(
        name=name, state_code=state_code, budget_total_cents=budget_total_cents
    )
    officials = [
        create_official(jurisdiction["id"], full_name=f"Official {i + 1}")
        for i in range(official_count)
    ]
    return {"jurisdiction": jurisdiction, "officials": officials}


def setup_certified_jurisdiction(**kwargs) -> dict:
    """Certified (FIELDED) system plus a jurisdiction with two officials."""
    cert_side = setup_certified_system(
        state_code=kwargs.get("campaign_state_code", DEFAULTS["STATE_CODE"]),
        lab_scope=kwargs.get("lab_scope", DEFAULTS["ACCREDITATION_SCOPE"]),
        system_overrides=kwargs.get("system_overrides"),
        lab_overrides=kwargs.get("lab_overrides"),
        campaign_overrides=kwargs.get("campaign_overrides"),
    )
    jur_side = setup_jurisdiction_with_officials(
        official_count=kwargs.get("official_count", 2),
        budget_total_cents=kwargs.get("budget_total_cents", DEFAULTS["BUDGET_TOTAL_CENTS"]),
        state_code=kwargs.get("jurisdiction_state_code", DEFAULTS["STATE_CODE"]),
    )
    return {**cert_side, **jur_side}


def setup_procurement(target_status: str = "ACCEPTED", **kwargs) -> dict:
    """Certified jurisdiction plus a procurement walked to target_status.

    target_status one of PLACED, DELIVERED, ACCEPTANCE_TESTING, ACCEPTED.
    ACCEPTED records one passing HARDWARE_DIAGNOSTIC and one passing
    BALLOT_SCAN_CALIBRATION test before the accept transition.
    """
    base = setup_certified_jurisdiction(**kwargs)
    off1 = base["officials"][0]["id"]
    procurement = create_procurement(
        base["jurisdiction"]["id"],
        base["system"]["id"],
        base["certificate"]["id"],
        acting_official_id=off1,
        quantity=kwargs.get("quantity", DEFAULTS["QUANTITY"]),
        unit_price_cents=kwargs.get("unit_price_cents", DEFAULTS["UNIT_PRICE_CENTS"]),
    )
    if target_status in ("DELIVERED", "ACCEPTANCE_TESTING", "ACCEPTED"):
        procurement = transition_procurement(procurement["id"], "DELIVERED", off1)
    if target_status in ("ACCEPTANCE_TESTING", "ACCEPTED"):
        procurement = transition_procurement(procurement["id"], "ACCEPTANCE_TESTING", off1)
    acceptance_tests = []
    if target_status == "ACCEPTED":
        acceptance_tests.append(
            record_acceptance_test(
                procurement["id"], off1, test_type="HARDWARE_DIAGNOSTIC"
            )
        )
        acceptance_tests.append(
            record_acceptance_test(
                procurement["id"], off1, test_type="BALLOT_SCAN_CALIBRATION"
            )
        )
        procurement = transition_procurement(procurement["id"], "ACCEPTED", off1)
    return {**base, "procurement": procurement, "acceptance_tests": acceptance_tests}


def setup_election_definition(target_status: str = "DRAFT", **kwargs) -> dict:
    """Accepted procurement plus an election definition walked to
    target_status: DRAFT, PROGRAMMED, LA_PASSED, LOCKED or CANVASSING.

    LA_PASSED conducts one passing L&A test (conductor officials[0]) and
    certifies it with officials[1] (segregation of duties). CANVASSING moves
    the logical clock forward to election day (08:00 UTC) before canvassing.
    """
    election_date = kwargs.pop("election_date", DEFAULTS["ELECTION_DATE"])
    precinct_count = kwargs.pop("precinct_count", DEFAULTS["PRECINCT_COUNT"])
    name = kwargs.pop("election_name", DEFAULTS["ELECTION_NAME"])
    canvass_clock = kwargs.pop("canvass_clock", f"{election_date}T08:00:00Z")
    base = setup_procurement("ACCEPTED", **kwargs)
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"],
        base["procurement"]["id"],
        acting_official_id=off1,
        name=name,
        election_date=election_date,
        precinct_count=precinct_count,
    )
    la_test = None
    if target_status in ("PROGRAMMED", "LA_PASSED", "LOCKED", "CANVASSING"):
        definition = store_layout(definition["id"], off1)
        definition = transition_election_definition(definition["id"], "PROGRAMMED", off1)
    if target_status in ("LA_PASSED", "LOCKED", "CANVASSING"):
        la_test = create_la_test(definition["id"], off1)
        la_test = certify_la_test(la_test["id"], off2)
        definition = transition_election_definition(definition["id"], "LA_PASSED", off1)
    if target_status in ("LOCKED", "CANVASSING"):
        definition = transition_election_definition(definition["id"], "LOCKED", off1)
    if target_status == "CANVASSING":
        set_clock(canvass_clock)
        definition = transition_election_definition(definition["id"], "CANVASSING", off1)
    return {**base, "definition": definition, "la_test": la_test}


# ==========================================================================
# Tier 4 — accumulation / threshold targeting
# ==========================================================================
def create_unit_with_battery_cycles(
    jurisdiction_id: str,
    voting_system_id: str,
    custodian_id: str,
    cycles: int,
    **overrides,
) -> dict:
    """A unit driven to exactly `cycles` battery cycles and returned to
    IN_STORAGE with in-band readings (deploy -> record-usage -> store), ready
    for a deploy boundary attempt."""
    unit = create_equipment_unit(
        jurisdiction_id, voting_system_id, custodian_id, **overrides
    )
    deploy_unit(unit["id"], custodian_id)
    record_usage(unit["id"], custodian_id, cycles)
    return store_unit(unit["id"], custodian_id)
