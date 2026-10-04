"""Composite setup helpers.

Every helper builds its preconditions from scratch through published
endpoints — the database is empty at the start of each test (per-test server
restart), so nothing is shared between tests. Setup calls use the lenient
``get_success_data`` validator so a broken precondition surfaces as a setup
failure, not as a confusing assertion failure inside the test body.

Identity threading (PRD §2.1): after creating a Facility / ImporterFirm, every
ownership-gated call in these fixtures uses make_facility_owner_headers(
facility["id"]) / make_importer_headers(importer["id"]) — never the shared
placeholder constants.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_ANALYSIS_DATE,
    REQUIRED_STREAK,
)
from .factories import (
    adjudicate_petition_payload,
    amend_prior_notice_payload,
    classify_recall_payload,
    complete_inspection_payload,
    create_alert_petition_payload,
    create_entry_payload,
    create_facility_payload,
    create_import_alert_payload,
    create_importer_payload,
    create_inspection_payload,
    create_laboratory_payload,
    create_prior_notice_payload,
    create_recall_payload,
    make_lot,
    record_effectiveness_payload,
    record_reconditioning_outcome_payload,
    record_sample_payload,
    record_sample_result_payload,
    renew_facility_payload,
    request_reconditioning_payload,
    submit_evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_facility_owner_headers,
    make_field_inspector_headers,
    make_importer_headers,
)

# Shared opaque-role headers used across fixtures.
ADMIN = TEST_USERS["platform_admin_headers"]
ER_ONE = TEST_USERS["entry_reviewer_headers"]
ER_TWO = TEST_USERS["entry_reviewer_two_headers"]
CO_ONE = TEST_USERS["compliance_officer_headers"]
CO_TWO = TEST_USERS["compliance_officer_two_headers"]
FI_ONE = TEST_USERS["field_inspector_headers"]
FI_TWO = TEST_USERS["field_inspector_two_headers"]
RC_ONE = TEST_USERS["recall_coordinator_headers"]


# ---------------------------------------------------------------------------
# Platform: logical clock (PRD §2.4)
# ---------------------------------------------------------------------------


def set_clock(current_utc: str, api=api_client) -> dict:
    """Advance the logical clock and run the ops checkpoint.

    Returns {"current_utc", "expired_facility_ids", "auto_refused_entry_ids"}.
    """
    return get_success_data(
        api.set_current_utc({"current_utc": current_utc}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Reads (used to refresh stale snapshots after cascades/mutations)
# ---------------------------------------------------------------------------


def get_facility(facility_id: str, api=api_client) -> dict:
    return get_success_data(api.get_facility(facility_id, ADMIN))


def get_prior_notice(prior_notice_id: str, api=api_client) -> dict:
    return get_success_data(api.get_prior_notice(prior_notice_id, ADMIN))


def get_entry(entry_id: str, api=api_client) -> dict:
    return get_success_data(api.get_entry(entry_id, ADMIN))


def get_import_alert(alert_id: str, api=api_client) -> dict:
    return get_success_data(api.get_import_alert(alert_id, ADMIN))


def get_recall(recall_id: str, api=api_client) -> dict:
    return get_success_data(api.get_recall(recall_id, ADMIN))


def list_alert_petition_rows(alert_id: str, api=api_client) -> list:
    return get_success_data(api.list_alert_petitions(alert_id, ADMIN))


def find_petition(alert_id: str, petition_id: str, api=api_client) -> dict:
    """Petitions have no single-GET endpoint; read via the alert's collection."""
    for row in list_alert_petition_rows(alert_id, api=api):
        if row["id"] == petition_id:
            return row
    raise AssertionError(f"Petition {petition_id} not found under alert {alert_id}")


def list_facility_inspection_rows(facility_id: str, api=api_client) -> list:
    return get_success_data(api.list_facility_inspections(facility_id, ADMIN))


def find_inspection(facility_id: str, inspection_id: str, api=api_client) -> dict:
    """Inspections have no single-GET endpoint; read via the facility's collection."""
    for row in list_facility_inspection_rows(facility_id, api=api):
        if row["id"] == inspection_id:
            return row
    raise AssertionError(
        f"Inspection {inspection_id} not found under facility {facility_id}"
    )


def list_entry_sample_rows(entry_id: str, api=api_client) -> list:
    return get_success_data(api.list_entry_samples(entry_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------


def create_facility(api=api_client, **overrides) -> dict:
    """Register a facility (201). Registration carries no ownership check
    (PRD §3.1), so the FacilityOwner placeholder header is valid here; the
    caller thereafter authenticates with X-User-ID equal to the minted id."""
    return get_success_data(
        api.create_facility(
            create_facility_payload(**overrides), TEST_USERS["facility_owner_headers"]
        )
    )


def create_importer(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_importer(create_importer_payload(**overrides), ADMIN)
    )


def create_laboratory(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_laboratory(create_laboratory_payload(**overrides), ADMIN)
    )


def create_prior_notice(importer: dict, facility: dict, api=api_client, **overrides) -> dict:
    """File a notice as the owning importer; created CONFIRMED (201)."""
    payload = create_prior_notice_payload(
        importer_id=importer["id"], facility_id=facility["id"], **overrides
    )
    return get_success_data(
        api.create_prior_notice(payload, make_importer_headers(importer["id"]))
    )


def amend_prior_notice(prior_notice: dict, importer: dict, api=api_client, **overrides) -> dict:
    """Amend a CONFIRMED notice as its owner; returns the new CONFIRMED
    superseding notice (201); the original flips to SUPERSEDED."""
    payload = amend_prior_notice_payload(**overrides)
    return get_success_data(
        api.amend_prior_notice(
            prior_notice["id"], payload, make_importer_headers(importer["id"])
        )
    )


def create_entry(importer: dict, prior_notice: dict, api=api_client) -> dict:
    """File an entry against a CONFIRMED notice owned by the caller (201);
    the notice flips to CONSUMED."""
    return get_success_data(
        api.create_entry(
            create_entry_payload(prior_notice["id"]),
            make_importer_headers(importer["id"]),
        )
    )


def create_notice_and_entry(importer: dict, facility: dict, api=api_client, **notice_overrides):
    """Returns (notice, entry): notice filed and consumed by the new entry."""
    notice = create_prior_notice(importer, facility, api=api, **notice_overrides)
    entry = create_entry(importer, notice, api=api)
    return notice, entry


def create_entries_batch(importer: dict, facility: dict, count: int, api=api_client, **notice_overrides) -> list:
    """File `count` notices + entries (e.g. for pagination tests)."""
    entries = []
    for _ in range(count):
        _, entry = create_notice_and_entry(importer, facility, api=api, **notice_overrides)
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Tier 2: basic facility + importer context
# ---------------------------------------------------------------------------


def setup_facility_and_importer(
    api=api_client, facility_overrides=None, importer_overrides=None
):
    """Returns (facility, importer), both freshly created."""
    facility = create_facility(api=api, **(facility_overrides or {}))
    importer = create_importer(api=api, **(importer_overrides or {}))
    return facility, importer


# ---------------------------------------------------------------------------
# Facility lifecycle: renewal, expiry, suspension (PRD §3.1)
# ---------------------------------------------------------------------------


def renew_facility(facility: dict, expected_facility_version=None, api=api_client) -> dict:
    """OCC-aware biennial renewal. When expected_facility_version is None the
    facility's current version is read first (the fresh path); pass an explicit
    stale value to exercise ERR_STALE_VERSION."""
    if expected_facility_version is None:
        expected_facility_version = get_facility(facility["id"], api=api)["version"]
    return get_success_data(
        api.renew_facility(
            facility["id"],
            renew_facility_payload(expected_facility_version),
            make_facility_owner_headers(facility["id"]),
        )
    )


def setup_expired_facility(clock_after_expiry: str = "2028-09-01T00:00:00Z", api=api_client, **facility_overrides) -> dict:
    """Facility created at the default clock, then the clock advanced strictly
    past expires_at (2028-08-31T00:00:00Z) so the sweep flips it EXPIRED.
    Returns the refreshed facility (version 2)."""
    facility = create_facility(api=api, **facility_overrides)
    set_clock(clock_after_expiry, api=api)
    return get_facility(facility["id"], api=api)


# ---------------------------------------------------------------------------
# Inspections (PRD §3.8)
# ---------------------------------------------------------------------------


def schedule_inspection(facility_id: str, api=api_client, inspector_headers=None, **overrides) -> dict:
    """Schedule a foreign-facility inspection (201). The inspector's X-User-ID
    is recorded as inspector_user_id."""
    return get_success_data(
        api.create_inspection(
            create_inspection_payload(facility_id=facility_id, **overrides),
            inspector_headers or FI_ONE,
        )
    )


def complete_inspection(inspection: dict, findings_violation_count: int, api=api_client, inspector_headers=None) -> dict:
    """Complete a SCHEDULED inspection. Ownership: the caller defaults to the
    inspection's own inspector_user_id (PRD §3.8)."""
    headers = inspector_headers or make_field_inspector_headers(
        inspection["inspector_user_id"]
    )
    return get_success_data(
        api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(findings_violation_count),
            headers,
        )
    )


def refuse_inspection_entry(inspection: dict, facility: dict, api=api_client) -> dict:
    """Facility refuses to permit the inspection: fires the three-link cascade
    (suspend -> detain open entries -> compromise unconsumed notices)."""
    return get_success_data(
        api.refuse_inspection_entry(
            inspection["id"], make_facility_owner_headers(facility["id"])
        )
    )


def create_facility_with_violations(violation_count: int, api=api_client, **facility_overrides) -> dict:
    """FOREIGN facility whose violation_count is raised by completing an
    inspection with that many findings. Returns the refreshed facility."""
    facility_overrides.setdefault("facility_kind", "FOREIGN")
    facility = create_facility(api=api, **facility_overrides)
    inspection = schedule_inspection(facility["id"], api=api)
    complete_inspection(inspection, findings_violation_count=violation_count, api=api)
    return get_facility(facility["id"], api=api)


def setup_suspended_facility(api=api_client, **facility_overrides) -> dict:
    """Facility suspended via the inspection-refusal cascade.
    Returns {"facility": refreshed (SUSPENDED, version 2), "inspection": refused}."""
    facility_overrides.setdefault("facility_kind", "FOREIGN")
    facility = create_facility(api=api, **facility_overrides)
    inspection = schedule_inspection(facility["id"], api=api)
    refused = refuse_inspection_entry(inspection, facility, api=api)
    return {"facility": get_facility(facility["id"], api=api), "inspection": refused}


# ---------------------------------------------------------------------------
# Entry screening and sampling (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


def screen_entry(entry: dict, api=api_client, reviewer_headers=None) -> dict:
    return get_success_data(
        api.screen_entry(entry["id"], reviewer_headers or ER_ONE)
    )


def setup_screened_entry(
    product_risk_class: str = "LOW",
    api=api_client,
    facility_overrides=None,
    importer_overrides=None,
    notice_overrides=None,
    reviewer_headers=None,
) -> dict:
    """Facility + importer + one entry screened once.

    With clean history: LOW scores 10 (RELEASE, terminal), STANDARD scores 30
    (RELEASE, terminal), HIGH scores 60 (SAMPLE, still PENDING).
    Returns {"facility", "importer", "prior_notice", "entry"} where entry is
    the post-screen snapshot.
    """
    facility, importer = setup_facility_and_importer(
        api=api,
        facility_overrides=facility_overrides,
        importer_overrides=importer_overrides,
    )
    notice_kwargs = {"product_risk_class": product_risk_class}
    notice_kwargs.update(notice_overrides or {})
    notice, entry = create_notice_and_entry(importer, facility, api=api, **notice_kwargs)
    screened = screen_entry(entry, api=api, reviewer_headers=reviewer_headers)
    return {
        "facility": facility,
        "importer": importer,
        "prior_notice": notice,
        "entry": screened,
    }


def setup_entry_screened_to_sample(api=api_client, **kwargs) -> dict:
    """HIGH-risk entry on a clean facility: score 60 >= 40 -> SAMPLE."""
    kwargs.setdefault("product_risk_class", "HIGH")
    return setup_screened_entry(api=api, **kwargs)


def order_sample(
    entry: dict,
    lab_code: str,
    sample_units: int = 1,
    analysis_date: str = DEFAULT_ANALYSIS_DATE,
    api=api_client,
    reviewer_headers=None,
) -> dict:
    """Order a lab analysis for a SAMPLE-decision entry (201, SCHEDULED/PENDING)."""
    return get_success_data(
        api.record_sample(
            entry["id"],
            record_sample_payload(lab_code, sample_units, analysis_date),
            reviewer_headers or ER_ONE,
        )
    )


def record_sample_result(sample: dict, result: str = "VIOLATIVE", api=api_client, reviewer_headers=None) -> dict:
    return get_success_data(
        api.record_sample_result(
            sample["id"], record_sample_result_payload(result), reviewer_headers or ER_ONE
        )
    )


def setup_entry_detained_for_cause(
    api=api_client,
    facility_overrides=None,
    importer_overrides=None,
    notice_overrides=None,
    lab_overrides=None,
    analysis_date: str = DEFAULT_ANALYSIS_DATE,
) -> dict:
    """For-cause detention: HIGH entry -> SAMPLE -> VIOLATIVE result ->
    DETAINED with detained_under_alert_id null and a fresh 240 h deadline.
    Returns {"facility", "importer", "laboratory", "prior_notice", "entry",
    "sample"} with the entry refreshed post-detention."""
    ctx = setup_entry_screened_to_sample(
        api=api,
        facility_overrides=facility_overrides,
        importer_overrides=importer_overrides,
        notice_overrides=notice_overrides,
    )
    laboratory = create_laboratory(api=api, **(lab_overrides or {}))
    sample = order_sample(
        ctx["entry"], laboratory["lab_code"], analysis_date=analysis_date, api=api
    )
    record_sample_result(sample, result="VIOLATIVE", api=api)
    ctx["laboratory"] = laboratory
    ctx["sample"] = sample
    ctx["entry"] = get_entry(ctx["entry"]["id"], api=api)
    return ctx


# ---------------------------------------------------------------------------
# Detention resolution (PRD §3.6)
# ---------------------------------------------------------------------------


def release_detained_entry(entry: dict, api=api_client, officer_headers=None) -> dict:
    """ComplianceOfficer releases a DETAINED entry (DWPE evidence accepted)."""
    return get_success_data(
        api.release_entry(entry["id"], officer_headers or CO_TWO)
    )


def release_pending_entry(entry: dict, api=api_client, reviewer_headers=None) -> dict:
    """EntryReviewer releases a PENDING SAMPLE-decision entry that has a
    COMPLIANT sample on file."""
    return get_success_data(
        api.release_entry(entry["id"], reviewer_headers or ER_ONE)
    )


def refuse_entry(entry: dict, api=api_client, officer_headers=None) -> dict:
    """ComplianceOfficer refuses admission of a DETAINED entry."""
    return get_success_data(api.refuse_entry(entry["id"], officer_headers or CO_ONE))


def export_entry(entry: dict, importer: dict, api=api_client) -> dict:
    """Owning importer exports a DETAINED entry before the response deadline."""
    return get_success_data(
        api.export_entry(entry["id"], make_importer_headers(importer["id"]))
    )


def request_reconditioning(entry: dict, importer: dict, lots=None, api=api_client) -> dict:
    """Owning importer requests reconditioning; stores bond_amount_cents.
    Default lot list covers the whole entry at its declared unit value."""
    if lots is None:
        lots = [make_lot(entry["declared_units"], entry["unit_value_cents"])]
    return get_success_data(
        api.request_reconditioning(
            entry["id"],
            request_reconditioning_payload(lots),
            make_importer_headers(importer["id"]),
        )
    )


def record_reconditioning_outcome(
    entry: dict, units_passed: int, units_failed: int, api=api_client, officer_headers=None
) -> dict:
    """ComplianceOfficer records the reconditioning result; units must sum to
    units_held. units_failed == 0 -> RECONDITIONED, else REFUSED."""
    return get_success_data(
        api.record_reconditioning_outcome(
            entry["id"],
            record_reconditioning_outcome_payload(units_passed, units_failed),
            officer_headers or CO_TWO,
        )
    )


# ---------------------------------------------------------------------------
# Import alerts (PRD §3.7)
# ---------------------------------------------------------------------------


def place_import_alert(api=api_client, creator_headers=None, **overrides) -> dict:
    """Place an import alert (201, ACTIVE). The creator defaults to
    COMPLIANCE_OFFICER_ONE — adjudications against its petitions must then use
    a different officer (segregation of duties), e.g. CO_TWO."""
    return get_success_data(
        api.create_import_alert(
            create_import_alert_payload(**overrides), creator_headers or CO_ONE
        )
    )


def setup_entry_detained_by_alert(
    api=api_client,
    facility_overrides=None,
    importer_overrides=None,
    notice_overrides=None,
    alert_reason: str = "Compliance concern",
    creator_headers=None,
) -> dict:
    """Entry auto-detained by a FIRM alert placed after entry creation.
    Returns {"facility", "importer", "prior_notice", "entry", "alert"} with
    the entry refreshed (DETAINED, detained_under_alert_id == alert id,
    response_deadline_at == detained_at + 240 h, units_held == declared_units)."""
    facility, importer = setup_facility_and_importer(
        api=api,
        facility_overrides=facility_overrides,
        importer_overrides=importer_overrides,
    )
    notice, entry = create_notice_and_entry(
        importer, facility, api=api, **(notice_overrides or {})
    )
    alert = place_import_alert(
        api=api,
        creator_headers=creator_headers,
        scope_type="FIRM",
        facility_id=facility["id"],
        reason=alert_reason,
    )
    return {
        "facility": facility,
        "importer": importer,
        "prior_notice": notice,
        "entry": get_entry(entry["id"], api=api),
        "alert": alert,
    }


def setup_entry_with_bond(lots=None, api=api_client, **kwargs) -> dict:
    """Alert-detained entry with a reconditioning bond already requested.
    Returns the setup_entry_detained_by_alert context with the entry refreshed
    post-bond (bond_amount_cents set, still DETAINED)."""
    ctx = setup_entry_detained_by_alert(api=api, **kwargs)
    bonded = request_reconditioning(ctx["entry"], ctx["importer"], lots=lots, api=api)
    ctx["entry"] = bonded
    return ctx


# ---------------------------------------------------------------------------
# Petitions (PRD §3.7)
# ---------------------------------------------------------------------------


def file_petition(
    alert: dict,
    facility: dict,
    evidence_links=None,
    expected_import_alert_version=None,
    api=api_client,
) -> dict:
    """OCC-aware petition filing (201, EVIDENCE_REVIEW). When the expected
    version is None the alert's current version is read first; pass an
    explicit stale value to exercise ERR_STALE_VERSION. Filing increments the
    ALERT's version by 1."""
    if expected_import_alert_version is None:
        expected_import_alert_version = get_import_alert(alert["id"], api=api)["version"]
    return get_success_data(
        api.create_alert_petition(
            alert["id"],
            create_alert_petition_payload(
                expected_import_alert_version=expected_import_alert_version,
                evidence_links=evidence_links if evidence_links is not None else [],
            ),
            make_facility_owner_headers(facility["id"]),
        )
    )


def submit_petition_evidence(petition: dict, facility: dict, evidence_links, api=api_client) -> dict:
    return get_success_data(
        api.submit_petition_evidence(
            petition["id"],
            submit_evidence_payload(evidence_links),
            make_facility_owner_headers(facility["id"]),
        )
    )


def adjudicate_petition(petition: dict, decision: str, api=api_client, officer_headers=None) -> dict:
    """ComplianceOfficer adjudication. Defaults to CO_TWO so it differs from
    the default alert creator CO_ONE (segregation of duties)."""
    return get_success_data(
        api.adjudicate_petition(
            petition["id"], adjudicate_petition_payload(decision), officer_headers or CO_TWO
        )
    )


def build_compliant_streak(
    alert: dict,
    facility: dict,
    importer: dict,
    count: int = REQUIRED_STREAK,
    api=api_client,
    notice_overrides=None,
    releaser_headers=None,
) -> list:
    """File `count` entries in the alert's scope while it is ACTIVE; each
    screens to DETAIN and is released by a ComplianceOfficer, producing a
    trailing run of RELEASED terminal entries completed at/after the alert's
    creation (the petition-approval streak input, PRD §3.7)."""
    entries = []
    for i in range(count):
        notice_kwargs = {"product_code": f"PC-STREAK-{i:03d}"}
        notice_kwargs.update(notice_overrides or {})
        _, entry = create_notice_and_entry(
            importer, facility, api=api, **notice_kwargs
        )
        screen_entry(entry, api=api)  # DETAIN: the ACTIVE alert matches
        entries.append(
            release_detained_entry(entry, api=api, officer_headers=releaser_headers)
        )
    return entries


def setup_alert_with_compliant_streak(
    streak: int = REQUIRED_STREAK,
    evidence_links=None,
    api=api_client,
    facility_overrides=None,
    importer_overrides=None,
    notice_overrides=None,
    alert_reason: str = "Recurring violations",
) -> dict:
    """FIRM alert + `streak` post-alert entries detained and CO-released +
    petition filed (default one evidence link) — approval-ready.
    Returns {"facility", "importer", "alert", "entries", "petition"}.
    The alert is refreshed after filing (filing increments its version)."""
    facility, importer = setup_facility_and_importer(
        api=api,
        facility_overrides=facility_overrides,
        importer_overrides=importer_overrides,
    )
    alert = place_import_alert(
        api=api, scope_type="FIRM", facility_id=facility["id"], reason=alert_reason
    )
    entries = build_compliant_streak(
        alert,
        facility,
        importer,
        count=streak,
        api=api,
        notice_overrides=notice_overrides,
    )
    petition = file_petition(
        alert,
        facility,
        evidence_links=evidence_links if evidence_links is not None else ["doc-corrective"],
        api=api,
    )
    return {
        "facility": facility,
        "importer": importer,
        "alert": get_import_alert(alert["id"], api=api),
        "entries": entries,
        "petition": petition,
    }


def setup_lifted_alert(api=api_client, **kwargs) -> dict:
    """Full approval flow: streak-3 petition APPROVEd by a non-creator officer,
    lifting the alert. Returns the streak context with "alert" refreshed
    (LIFTED) and "petition" refreshed (APPROVED)."""
    ctx = setup_alert_with_compliant_streak(api=api, **kwargs)
    petition = adjudicate_petition(ctx["petition"], "APPROVE", api=api)
    ctx["petition"] = petition
    ctx["alert"] = get_import_alert(ctx["alert"]["id"], api=api)
    return ctx


# ---------------------------------------------------------------------------
# Importer standing history (PRD §3.2)
# ---------------------------------------------------------------------------


def release_low_entry(importer: dict, facility: dict, api=api_client, **notice_overrides) -> dict:
    """LOW-risk entry on a clean-enough facility screened to RELEASE
    (terminal, not a refusal). Returns the screened entry."""
    notice_overrides.setdefault("product_risk_class", "LOW")
    _, entry = create_notice_and_entry(importer, facility, api=api, **notice_overrides)
    return screen_entry(entry, api=api)


def refuse_high_entry_via_violative_sample(
    importer: dict,
    facility: dict,
    lab_code: str,
    api=api_client,
    analysis_date: str = DEFAULT_ANALYSIS_DATE,
    **notice_overrides,
) -> dict:
    """HIGH entry -> SAMPLE -> VIOLATIVE -> DETAINED -> ComplianceOfficer
    refusal. Terminal REFUSED: importer refusal_count += 1 and facility
    violation_count += 1. Returns the refused entry."""
    notice_overrides.setdefault("product_risk_class", "HIGH")
    _, entry = create_notice_and_entry(importer, facility, api=api, **notice_overrides)
    screened = screen_entry(entry, api=api)  # 60+ points -> SAMPLE
    sample = order_sample(screened, lab_code, analysis_date=analysis_date, api=api)
    record_sample_result(sample, result="VIOLATIVE", api=api)
    return refuse_entry(get_entry(entry["id"], api=api), api=api)


def setup_importer_with_history(
    num_releases: int = 0,
    num_refusals: int = 0,
    api=api_client,
    facility_overrides=None,
    importer_overrides=None,
    lab_overrides=None,
) -> dict:
    """Importer with a scripted terminal history on one shared facility:
    `num_releases` LOW releases plus `num_refusals` HIGH refusals (via
    violative samples). Standing after the fact follows PRD §3.2's pinned
    order — e.g. 3 releases + 2 refusals -> PROBATION; a 3rd refusal with 6
    terminal entries -> REVOKED. Note REVOKED blocks further notice filings,
    so compose histories that only reach REVOKED on the last refusal.
    Returns {"facility", "importer", "laboratory", "released_entries",
    "refused_entries"}."""
    facility = create_facility(api=api, **(facility_overrides or {}))
    importer = create_importer(api=api, **(importer_overrides or {}))
    laboratory = create_laboratory(api=api, **(lab_overrides or {}))
    released = [
        release_low_entry(importer, facility, api=api) for _ in range(num_releases)
    ]
    refused = [
        refuse_high_entry_via_violative_sample(
            importer, facility, laboratory["lab_code"], api=api
        )
        for _ in range(num_refusals)
    ]
    return {
        "facility": facility,
        "importer": importer,
        "laboratory": laboratory,
        "released_entries": released,
        "refused_entries": refused,
    }


# ---------------------------------------------------------------------------
# Recalls (PRD §3.9)
# ---------------------------------------------------------------------------


def create_recall(facility: dict, api=api_client, coordinator_headers=None, **overrides) -> dict:
    """Initiate a recall (201, INITIATED, classification NONE)."""
    return get_success_data(
        api.create_recall(
            create_recall_payload(facility_id=facility["id"], **overrides),
            coordinator_headers or RC_ONE,
        )
    )


def classify_recall(recall: dict, classification: str, api=api_client, coordinator_headers=None) -> dict:
    """INITIATED -> CLASSIFIED; a CLASS_I classification activates the entry
    safety gate for the same facility + product_code from that moment."""
    return get_success_data(
        api.classify_recall(
            recall["id"],
            classify_recall_payload(classification),
            coordinator_headers or RC_ONE,
        )
    )


def record_effectiveness_round(
    recall: dict,
    delta_recovered: int = 0,
    delta_corrected: int = 0,
    delta_destroyed: int = 0,
    consignees_contacted: int = 0,
    consignees_total: int = 0,
    api=api_client,
    coordinator_headers=None,
) -> dict:
    return get_success_data(
        api.record_recall_effectiveness(
            recall["id"],
            record_effectiveness_payload(
                delta_recovered=delta_recovered,
                delta_corrected=delta_corrected,
                delta_destroyed=delta_destroyed,
                consignees_contacted=consignees_contacted,
                consignees_total=consignees_total,
            ),
            coordinator_headers or RC_ONE,
        )
    )


def terminate_recall(recall: dict, api=api_client, coordinator_headers=None) -> dict:
    return get_success_data(
        api.terminate_recall(recall["id"], coordinator_headers or RC_ONE)
    )


def setup_classified_recall(
    classification: str = "CLASS_III",
    quantity_distributed: int = 100,
    api=api_client,
    facility_overrides=None,
    **recall_overrides,
) -> dict:
    """Facility + recall classified to the given class.
    Returns {"facility", "recall"} with the recall in CLASSIFIED status."""
    facility_kwargs = {"facility_kind": "DOMESTIC", "country_code": "US"}
    facility_kwargs.update(facility_overrides or {})
    facility = create_facility(api=api, **facility_kwargs)
    recall = create_recall(
        facility, api=api, quantity_distributed=quantity_distributed, **recall_overrides
    )
    recall = classify_recall(recall, classification, api=api)
    return {"facility": facility, "recall": recall}
