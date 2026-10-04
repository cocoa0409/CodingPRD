"""Composite setup helpers (PRD §2.5, §2.9, §3).

Every fixture builds its preconditions from scratch through the public API —
the test harness restarts the server before every test, so each test starts
against an empty database with the logical clock at 2026-09-01T00:00:00Z.

Setup calls use the framework's lenient get_success_data(); any failure is
re-raised as an AssertionError prefixed "Setup failed:" with the HTTP status
and a body excerpt, so a broken precondition never masquerades as a broken
assertion.

Identity threading (PRD §2.8 priority 3): Specifier-owned creates pass the
owning identity explicitly; Installer-side actions always build headers from
the site's recorded contractor_name; segregation-of-duties chains submit as
the manager identity and clear/review as distinct verifier/approver
identities.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT, TILE_MASS_KG_PER_M2
from .factories import (
    create_allocate_payload,
    create_batch_payload,
    create_carbon_claim_payload,
    create_collect_payload,
    create_collection_payload,
    create_feedstock_lot_payload,
    create_manufacturing_target_payload,
    create_offset_payload,
    create_pcf_report_payload,
    create_qc_payload,
    create_reading_payload,
    create_replacement_order_payload,
    create_review_payload,
    create_schedule_payload,
    create_site_payload,
    create_sort_payload,
    create_spec_package_payload,
    create_takeback_request_payload,
    create_verification_payload,
    create_zone_payload,
)
from .test_users import (
    DEFAULT_APPROVER_ID,
    DEFAULT_MANAGER_ID,
    DEFAULT_SPECIFIER_ID,
    DEFAULT_VERIFIER_ID,
    TEST_USERS,
    make_approver_headers,
    make_installer_headers,
    make_manager_headers,
    make_specifier_headers,
    make_verifier_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _ok(resp, context: str):
    """Lenient setup validation: accept any 2xx, else fail with context."""
    try:
        return get_success_data(resp)
    except Exception as exc:
        body = getattr(resp, "text", "")
        raise AssertionError(
            f"Setup failed ({context}): HTTP {resp.status_code} {body[:400]}"
        ) from exc


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5) — endpoint lives outside the /carpetloop prefix.
# ---------------------------------------------------------------------------
def set_clock(current_utc: str = LOGICAL_CLOCK_DEFAULT) -> dict:
    """Advance the server logical clock; returns the echoed current_utc."""
    return _ok(api_client.set_clock(current_utc, ADMIN), f"set_clock({current_utc})")


# ---------------------------------------------------------------------------
# Fresh reads / OCC version capture (PRD §2.7)
# ---------------------------------------------------------------------------
def get_collection(collection_id: str) -> dict:
    return _ok(api_client.get_collection(collection_id, ADMIN), "get_collection")


def get_collection_version(collection_id: str) -> int:
    """Fresh collection version for expected_collection_version payloads."""
    return get_collection(collection_id)["version"]


def get_site(site_id: str) -> dict:
    return _ok(api_client.get_site(site_id, ADMIN), "get_site")


def get_site_version(site_id: str) -> int:
    """Fresh site version for expected_site_version payloads."""
    return get_site(site_id)["version"]


# ---------------------------------------------------------------------------
# ProductCollection (PRD §3.1)
# ---------------------------------------------------------------------------
def create_collection(**overrides) -> dict:
    """Create a collection (ACTIVE, version 1). claim_intent defaults to the
    PRD server-side default unless passed explicitly."""
    resp = api_client.create_collection(create_collection_payload(**overrides), ADMIN)
    return _ok(resp, "create_collection")


def sunset_collection(collection_id: str) -> dict:
    return _ok(api_client.sunset_collection(collection_id, ADMIN), "sunset_collection")


# ---------------------------------------------------------------------------
# FeedstockLot (PRD §3.2)
# ---------------------------------------------------------------------------
def create_lot(**overrides) -> dict:
    """Register a feedstock lot (RECEIVED, reliability stamped at creation)."""
    resp = api_client.create_feedstock_lot(create_feedstock_lot_payload(**overrides), ADMIN)
    return _ok(resp, "create_lot")


def qc_lot(lot_id: str, outcome: str = "PASS") -> dict:
    resp = api_client.qc_feedstock_lot(lot_id, create_qc_payload(outcome), ADMIN)
    return _ok(resp, f"qc_lot({outcome})")


def create_qc_passed_lot(**overrides) -> dict:
    """Register a lot and QC-PASS it. Returns the QC_PASSED lot."""
    lot = create_lot(**overrides)
    return qc_lot(lot["id"], "PASS")


def create_qc_failed_lot(**overrides) -> dict:
    lot = create_lot(**overrides)
    return qc_lot(lot["id"], "FAIL")


def allocate_to_batch(lot_id: str, batch_id: str, quantity_kg, manager_id: str = None) -> dict:
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.allocate_feedstock(
        lot_id, create_allocate_payload(batch_id, quantity_kg), headers
    )
    return _ok(resp, f"allocate_to_batch({quantity_kg} kg)")


def deallocate_from_batch(lot_id: str, batch_id: str, quantity_kg, manager_id: str = None) -> dict:
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.deallocate_feedstock(
        lot_id, create_allocate_payload(batch_id, quantity_kg), headers
    )
    return _ok(resp, f"deallocate_from_batch({quantity_kg} kg)")


def find_lots_by_origin_takeback(takeback_id: str) -> list:
    """Traceability channel: lots created by the sort cascade for a take-back
    (GET /carpetloop/feedstock-lots?origin_takeback_id=...)."""
    resp = api_client.list_feedstock_lots(
        ADMIN, params={"origin_takeback_id": takeback_id}
    )
    rows, _meta = validate_paginated(resp)
    return rows


# ---------------------------------------------------------------------------
# TileBatch (PRD §3.2)
# ---------------------------------------------------------------------------
def create_batch(collection_id: str, **overrides) -> dict:
    """Create a dye-lot batch in QUARANTINE (full availability, empty mix)."""
    resp = api_client.create_batch(
        collection_id, create_batch_payload(**overrides), ADMIN
    )
    return _ok(resp, "create_batch")


def release_batch(batch_id: str) -> dict:
    return _ok(api_client.release_batch(batch_id, ADMIN), "release_batch")


def create_released_batch(collection_id: str, mix: list = None, manager_id: str = None,
                          **batch_overrides) -> dict:
    """Create a batch, fill its mix to exact mass balance, QC-passing every
    source lot, then release it.

    ``mix`` is a list of (quantity_kg, carbon_factor, source_type, supplier)
    tuples; the default is the canonical 100 m2 mix: 200 kg reclaimed fishing
    net @0.50 plus 200 kg virgin @2.10 (stored embodied 6.400). The mix
    quantities must sum to produced_m2 x 4.0 kg or the release gate would
    reject — this helper fails fast on a misbalanced mix.
    Returns {"batch": <RELEASED batch>, "lots": [<lot>, ...]}.
    """
    produced_m2 = batch_overrides.get("produced_m2", 100)
    if mix is None:
        mix = [
            (200, 0.50, "RECLAIMED_FISHING_NET", "NETCO"),
            (200, 2.10, "VIRGIN", "POLYCO"),
        ]
    required = round(produced_m2 * TILE_MASS_KG_PER_M2, 2)
    supplied = round(sum(entry[0] for entry in mix), 2)
    assert supplied == required, (
        f"fixture misuse: mix sums to {supplied} kg but the release gate "
        f"requires {required} kg for produced_m2={produced_m2}"
    )
    batch = create_batch(collection_id, **batch_overrides)
    lots = []
    for quantity_kg, factor, source_type, supplier in mix:
        lot = create_qc_passed_lot(
            supplier_name=supplier,
            source_type=source_type,
            quantity_kg=quantity_kg,
            carbon_factor_kgco2e_per_kg=factor,
        )
        lots.append(lot)
        allocate_to_batch(lot["id"], batch["id"], quantity_kg, manager_id=manager_id)
    batch = release_batch(batch["id"])
    return {"batch": batch, "lots": lots}


def setup_collection_with_batch(collection_overrides: dict = None,
                                mix: list = None, **batch_overrides) -> dict:
    """Collection plus one released batch. Returns
    {"collection": ..., "batch": ..., "lots": [...]}."""
    collection = create_collection(**(collection_overrides or {}))
    built = create_released_batch(collection["id"], mix=mix, **batch_overrides)
    return {"collection": collection, "batch": built["batch"], "lots": built["lots"]}


# ---------------------------------------------------------------------------
# CustomerSite and InstalledZone (PRD §3.3)
# ---------------------------------------------------------------------------
def create_site(specifier_id: str = DEFAULT_SPECIFIER_ID, **overrides) -> dict:
    """Register a site (PLANNED); created_by records the specifier identity."""
    headers = make_specifier_headers(specifier_id)
    resp = api_client.create_site(create_site_payload(**overrides), headers)
    return _ok(resp, "create_site")


def install_site(site: dict) -> dict:
    """Mark a PLANNED site installed, as the site's recorded contractor."""
    headers = make_installer_headers(site["contractor_name"])
    return _ok(api_client.install_site(site["id"], headers), "install_site")


def create_installed_site(specifier_id: str = DEFAULT_SPECIFIER_ID, **overrides) -> dict:
    return install_site(create_site(specifier_id=specifier_id, **overrides))


def lay_zone(site: dict, batch_id: str, zone_code: str = "Z-1", area_m2=10) -> dict:
    """Lay a zone from a released batch, as the site's contractor. The first
    zone of an INSTALLED site bubbles it to IN_SERVICE (PRD §2.9)."""
    headers = make_installer_headers(site["contractor_name"])
    payload = create_zone_payload(batch_id, zone_code=zone_code, area_m2=area_m2)
    resp = api_client.create_zone(site["id"], payload, headers)
    return _ok(resp, f"lay_zone({zone_code})")


def setup_site_with_zone(collection_overrides: dict = None, mix: list = None,
                         zone_code: str = "Z-1", zone_area_m2=10,
                         site_overrides: dict = None, **batch_overrides) -> dict:
    """Full demand-side chain: collection + released batch + installed site +
    first zone laid (site lands IN_SERVICE). Returns
    {"collection", "batch", "lots", "site", "zone"}."""
    built = setup_collection_with_batch(collection_overrides, mix=mix, **batch_overrides)
    site = create_installed_site(**(site_overrides or {}))
    zone = lay_zone(site, built["batch"]["id"], zone_code=zone_code, area_m2=zone_area_m2)
    site = get_site(site["id"])
    return {**built, "site": site, "zone": zone}


# ---------------------------------------------------------------------------
# TakeBackRequest (PRD §3.5) — create/cancel are Specifier-owned; schedule and
# collect run as the site's contractor; sort is a SustainabilityManager act.
# ---------------------------------------------------------------------------
def create_takeback(site: dict, collection_id: str, specifier_id: str = None,
                    **overrides) -> dict:
    """Open a take-back (REQUESTED). This is a site-scoped Specifier create,
    so the caller defaults to the site's creator (created_by ownership)."""
    headers = make_specifier_headers(specifier_id or site["created_by"])
    payload = create_takeback_request_payload(site["id"], collection_id, **overrides)
    return _ok(api_client.create_takeback_request(payload, headers), "create_takeback")


def schedule_takeback(takeback: dict, site: dict, **window_overrides) -> dict:
    headers = make_installer_headers(site["contractor_name"])
    payload = create_schedule_payload(**window_overrides)
    resp = api_client.schedule_takeback(takeback["id"], payload, headers)
    return _ok(resp, "schedule_takeback")


def collect_takeback(takeback: dict, site: dict, collected_kg=160) -> dict:
    headers = make_installer_headers(site["contractor_name"])
    resp = api_client.collect_takeback(
        takeback["id"], create_collect_payload(collected_kg), headers
    )
    return _ok(resp, "collect_takeback")


def sort_takeback(takeback: dict, manager_id: str = None, **sort_overrides) -> dict:
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.sort_takeback(
        takeback["id"], create_sort_payload(**sort_overrides), headers
    )
    return _ok(resp, "sort_takeback")


def cancel_takeback(takeback: dict, specifier_id: str = None) -> dict:
    headers = make_specifier_headers(specifier_id or takeback["created_by"])
    return _ok(api_client.cancel_takeback(takeback["id"], headers), "cancel_takeback")


def setup_collected_takeback(site: dict, collection_id: str, collected_kg=160,
                             collect_clock: str = "2026-09-12T06:00:00Z",
                             specifier_id: str = None, **takeback_overrides) -> dict:
    """Take-back driven to COLLECTED: request -> schedule into the default
    future window -> advance the logical clock into the window -> collect."""
    takeback = create_takeback(site, collection_id, specifier_id=specifier_id,
                               **takeback_overrides)
    takeback = schedule_takeback(takeback, site)
    set_clock(collect_clock)
    return collect_takeback(takeback, site, collected_kg=collected_kg)


def setup_credited_takeback(site: dict, collection_id: str, collected_kg=160,
                            collect_clock: str = "2026-09-12T06:00:00Z",
                            specifier_id: str = None, manager_id: str = None,
                            sort_overrides: dict = None,
                            **takeback_overrides) -> dict:
    """Take-back driven to its terminal CREDITED state (sort included; fires
    the depolymerization feedstock cascade when depolymerize_kg > 0)."""
    takeback = setup_collected_takeback(
        site, collection_id, collected_kg=collected_kg,
        collect_clock=collect_clock, specifier_id=specifier_id,
        **takeback_overrides,
    )
    return sort_takeback(takeback, manager_id=manager_id, **(sort_overrides or {}))


# ---------------------------------------------------------------------------
# ReplacementOrder (PRD §3.4) — create is a Specifier-owned create-with-
# supersede carrying expected_site_version (PRD §2.7); match/complete run as
# the site's contractor; cancel runs as the order's creator.
# ---------------------------------------------------------------------------
def create_order(site: dict, zone: dict, expected_site_version: int = None,
                 specifier_id: str = None, **overrides) -> dict:
    """Open a replacement order (DRAFT). When expected_site_version is not
    given, the site's version is re-read immediately before the create — the
    canonical optimistic-concurrency flow."""
    version = expected_site_version
    if version is None:
        version = get_site_version(site["id"])
    headers = make_specifier_headers(specifier_id or site["created_by"])
    payload = create_replacement_order_payload(site["id"], zone["id"], version,
                                               **overrides)
    return _ok(api_client.create_replacement_order(payload, headers), "create_order")


def match_order(order: dict, site: dict) -> dict:
    """Run dye-lot matching as the site's contractor. May land MATCHED or
    MATCH_FAILED depending on the candidate pool — both are success paths."""
    headers = make_installer_headers(site["contractor_name"])
    resp = api_client.match_replacement_order(order["id"], headers)
    return _ok(resp, "match_order")


def complete_order(order: dict, site: dict) -> dict:
    headers = make_installer_headers(site["contractor_name"])
    resp = api_client.complete_replacement_order(order["id"], headers)
    return _ok(resp, "complete_order")


def cancel_order(order: dict, specifier_id: str = None) -> dict:
    headers = make_specifier_headers(specifier_id or order["created_by"])
    resp = api_client.cancel_replacement_order(order["id"], headers)
    return _ok(resp, "cancel_order")


def setup_matched_order(site: dict, zone: dict, specifier_id: str = None,
                        **order_overrides) -> dict:
    """Order created and matched (requires a released candidate batch with
    enough availability — the caller guarantees the pool)."""
    order = create_order(site, zone, specifier_id=specifier_id, **order_overrides)
    order = match_order(order, site)
    assert order["status"] == "MATCHED", (
        f"Setup failed (setup_matched_order): expected MATCHED, got {order['status']}"
    )
    return order


# ---------------------------------------------------------------------------
# PCFReport (PRD §3.6) — create carries expected_collection_version (PRD §2.7).
# Segregation of duties: the verifier who CLEARs/FAILs must differ from the
# submitter; the default manager/verifier identities already differ.
# ---------------------------------------------------------------------------
def create_report(collection_id: str, expected_collection_version: int = None,
                  manager_id: str = None, **overrides) -> dict:
    """Open a report (DRAFT). When expected_collection_version is not given,
    the collection's version is re-read immediately before the create."""
    version = expected_collection_version
    if version is None:
        version = get_collection_version(collection_id)
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    payload = create_pcf_report_payload(collection_id, version, **overrides)
    return _ok(api_client.create_pcf_report(payload, headers), "create_report")


def submit_report(report: dict, manager_id: str = None) -> dict:
    """Submit a DRAFT report; computes and stores both footprint variants."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.submit_pcf_report(report["id"], headers)
    return _ok(resp, "submit_report")


def revise_report(report: dict, manager_id: str = None) -> dict:
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.revise_pcf_report(report["id"], headers)
    return _ok(resp, "revise_report")


def assign_report(report: dict, verifier_org: str = "EcoAssure",
                  manager_id: str = None) -> dict:
    """ASSIGN (SustainabilityManager action): SUBMITTED -> IN_VERIFICATION."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    payload = create_verification_payload("ASSIGN", verifier_org=verifier_org)
    resp = api_client.verify_pcf_report(report["id"], payload, headers)
    return _ok(resp, "assign_report")


def clear_report(report: dict, verifier_id: str = DEFAULT_VERIFIER_ID) -> dict:
    """CLEAR (Verifier action): IN_VERIFICATION -> VERIFIED. The verifier
    identity must differ from the report's submitted_by (PRD §2.8 rule 8)."""
    headers = make_verifier_headers(verifier_id)
    resp = api_client.verify_pcf_report(
        report["id"], create_verification_payload("CLEAR"), headers
    )
    return _ok(resp, "clear_report")


def fail_report(report: dict, findings_count: int = 1,
                verifier_id: str = DEFAULT_VERIFIER_ID) -> dict:
    """FAIL (Verifier action): IN_VERIFICATION -> REJECTED."""
    headers = make_verifier_headers(verifier_id)
    resp = api_client.verify_pcf_report(
        report["id"], create_verification_payload("FAIL", findings_count=findings_count),
        headers,
    )
    return _ok(resp, "fail_report")


def publish_report(report: dict, manager_id: str = None) -> dict:
    """Publish a VERIFIED report; fires cascade A (supersede/retire/revoke)."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.publish_pcf_report(report["id"], headers)
    return _ok(resp, "publish_report")


def setup_published_report(collection_id: str, manager_id: str = None,
                           verifier_id: str = DEFAULT_VERIFIER_ID,
                           **report_overrides) -> dict:
    """Full verification pipeline: create -> submit -> ASSIGN -> CLEAR ->
    publish. Returns the PUBLISHED report."""
    report = create_report(collection_id, manager_id=manager_id, **report_overrides)
    report = submit_report(report, manager_id=manager_id)
    report = assign_report(report, manager_id=manager_id)
    report = clear_report(report, verifier_id=verifier_id)
    return publish_report(report, manager_id=manager_id)


# ---------------------------------------------------------------------------
# CarbonClaim and OffsetRetirement (PRD §3.7)
# ---------------------------------------------------------------------------
def create_claim(collection_id: str, report_id: str, manager_id: str = None,
                 **overrides) -> dict:
    """Draft a claim (DRAFT, offset_coverage NONE, retired_kgco2e 0)."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    payload = create_carbon_claim_payload(collection_id, report_id, **overrides)
    return _ok(api_client.create_carbon_claim(payload, headers), "create_claim")


def submit_claim(claim: dict, manager_id: str = None) -> dict:
    """Submit (or resubmit) a claim; computes required_offset_kgco2e."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.submit_carbon_claim(claim["id"], headers)
    return _ok(resp, "submit_claim")


def review_claim(claim: dict, decision: str = "APPROVE",
                 approver_id: str = DEFAULT_APPROVER_ID) -> dict:
    """ClaimsApprover review; the reviewer identity must differ from the
    claim's created_by (PRD §2.8 rule 8)."""
    headers = make_approver_headers(approver_id)
    resp = api_client.review_carbon_claim(
        claim["id"], create_review_payload(decision), headers
    )
    return _ok(resp, f"review_claim({decision})")


def publish_claim(claim: dict, manager_id: str = None) -> dict:
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.publish_carbon_claim(claim["id"], headers)
    return _ok(resp, "publish_claim")


def retire_offset(claim_id: str, quantity_kgco2e=100, manager_id: str = None,
                  **overrides) -> dict:
    """Retire offsets against an IN_REVIEW or APPROVED claim (immediate)."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    payload = create_offset_payload(quantity_kgco2e=quantity_kgco2e, **overrides)
    resp = api_client.create_offset_retirement(claim_id, payload, headers)
    return _ok(resp, f"retire_offset({quantity_kgco2e})")


def setup_claim_in_review(collection_id: str, report_id: str,
                          manager_id: str = None, **claim_overrides) -> dict:
    """Claim created and submitted (IN_REVIEW) against a PUBLISHED report."""
    claim = create_claim(collection_id, report_id, manager_id=manager_id,
                         **claim_overrides)
    return submit_claim(claim, manager_id=manager_id)


def setup_published_claim(collection_id: str, report_id: str,
                          manager_id: str = None,
                          approver_id: str = DEFAULT_APPROVER_ID,
                          offset_quantities: list = None,
                          **claim_overrides) -> dict:
    """Claim driven to PUBLISHED: create -> submit -> retire offsets to FULL
    coverage -> APPROVE -> publish. When offset_quantities is omitted, exactly
    the claim's required_offset_kgco2e is retired in a single retirement."""
    claim = setup_claim_in_review(collection_id, report_id, manager_id=manager_id,
                                  **claim_overrides)
    if offset_quantities is None:
        required = claim["required_offset_kgco2e"]
        # Offset quantities must be positive; a zero requirement is covered
        # (FULL) by any positive retirement.
        offset_quantities = [required if required and required > 0 else 1]
    for quantity in offset_quantities:
        retire_offset(claim["id"], quantity_kgco2e=quantity, manager_id=manager_id)
    claim = review_claim(claim, "APPROVE", approver_id=approver_id)
    return publish_claim(claim, manager_id=manager_id)


# ---------------------------------------------------------------------------
# ManufacturingTarget (PRD §3.7)
# ---------------------------------------------------------------------------
def create_target(**overrides) -> dict:
    """Create a target: current intensity starts at the baseline, posture
    AT_RISK, readings_log empty."""
    resp = api_client.create_manufacturing_target(
        create_manufacturing_target_payload(**overrides), ADMIN
    )
    return _ok(resp, "create_target")


def post_reading(target_id: str, manager_id: str = None, **reading_overrides) -> dict:
    """Append a period reading; recomputes current intensity and posture and
    fires the breach cascade when the posture enters BREACHED."""
    headers = make_manager_headers(manager_id or DEFAULT_MANAGER_ID)
    resp = api_client.create_target_reading(
        target_id, create_reading_payload(**reading_overrides), headers
    )
    return _ok(resp, "post_reading")


# ---------------------------------------------------------------------------
# SpecPackage (PRD §3.8) — create carries expected_collection_version and
# supersedes the prior ISSUED package of the same firm+collection pair.
# ---------------------------------------------------------------------------
def issue_package(collection_id: str, report_id: str,
                  expected_collection_version: int = None,
                  architect_firm: str = "FIRM-A", claim_id: str = None,
                  specifier_id: str = DEFAULT_SPECIFIER_ID) -> dict:
    """Issue a spec package (ISSUED). When expected_collection_version is not
    given, the collection's version is re-read immediately before the create."""
    version = expected_collection_version
    if version is None:
        version = get_collection_version(collection_id)
    overrides = {"architect_firm": architect_firm}
    if claim_id is not None:
        overrides["claim_id"] = claim_id
    payload = create_spec_package_payload(collection_id, report_id, version, **overrides)
    headers = make_specifier_headers(specifier_id)
    return _ok(api_client.create_spec_package(payload, headers), "issue_package")
