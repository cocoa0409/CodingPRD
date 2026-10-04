"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints —
the runner restarts the server (fresh database) before every test. Setup calls
use get_success_data() so failures surface as clear "Setup failed" errors.
OrgOwner identity is threaded through make_org_owner_headers(org_id) on every
ownership-gated call.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import PERSONAL_TIER, PRO_TIER, ENTERPRISE_TIER, EDUCATION_TIER
from .factories import (
    create_org_payload,
    create_revenue_declaration_payload,
    create_editor_version_payload,
    create_project_payload,
    create_install_report_payload,
    create_seat_subscription_payload,
    create_asset_listing_payload,
    create_export_agreement_payload,
    create_migration_assessment_payload,
)
from .test_users import TEST_USERS, make_org_owner_headers

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Tier configs
# ---------------------------------------------------------------------------

def setup_personal_and_pro_tiers():
    """Create the canonical PERSONAL + PRO tier configs. Returns both."""
    personal = get_success_data(api_client.create_tier(dict(PERSONAL_TIER), ADMIN), 201)
    pro = get_success_data(api_client.create_tier(dict(PRO_TIER), ADMIN), 201)
    return personal, pro


def setup_all_tiers():
    """PERSONAL + PRO + ENTERPRISE tier configs."""
    personal, pro = setup_personal_and_pro_tiers()
    enterprise = get_success_data(api_client.create_tier(dict(ENTERPRISE_TIER), ADMIN), 201)
    return personal, pro, enterprise


# ---------------------------------------------------------------------------
# Orgs, editor versions, projects
# ---------------------------------------------------------------------------

def create_org(declared_tier_code="PRO", **overrides):
    org = get_success_data(
        api_client.create_org(create_org_payload(declared_tier_code=declared_tier_code, **overrides), ADMIN),
        201,
    )
    return org


def create_editor_version(version_string="2022.3.1f1", major_line="2022.3", released_on="2025-09-01", **overrides):
    return get_success_data(
        api_client.create_editor_version(
            create_editor_version_payload(
                version_string=version_string,
                major_line=major_line,
                released_on=released_on,
                **overrides,
            ),
            ADMIN,
        ),
        201,
    )


def declare_revenue(org_id, period_month="2026-01", gross_revenue_cents=160_000_000, funding_received_cents=0):
    headers = make_org_owner_headers(org_id)
    return get_success_data(
        api_client.create_revenue_declaration(
            org_id,
            create_revenue_declaration_payload(
                period_month=period_month,
                gross_revenue_cents=gross_revenue_cents,
                funding_received_cents=funding_received_cents,
            ),
            headers,
        ),
        201,
    )


def create_project(org, editor_version_id, **overrides):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(
        api_client.create_project(org["id"], create_project_payload(editor_version_id, **overrides), headers),
        201,
    )


def ship_project(org, project):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(api_client.ship_project(project["id"], headers), 200)


def setup_org_with_project(declared_tier_code="PRO", version_string="2022.3.1f1",
                           major_line="2022.3", released_on="2025-09-01",
                           with_tiers=True, **project_overrides):
    """Org + editor version + DEVELOPMENT project. Returns (org, editor_version, project)."""
    if with_tiers:
        setup_personal_and_pro_tiers()
    org = create_org(declared_tier_code)
    ev = create_editor_version(version_string, major_line, released_on)
    project = create_project(org, ev["id"], **project_overrides)
    return org, ev, project


def setup_shipped_project(declared_tier_code="PRO", revenue_cents=None, version_string="2022.3.1f1",
                          major_line="2022.3", released_on="2025-09-01", with_tiers=True,
                          **project_overrides):
    """Org (+ optional revenue declaration) + editor version + SHIPPED project."""
    org, ev, project = setup_org_with_project(
        declared_tier_code, version_string, major_line, released_on, with_tiers, **project_overrides
    )
    if revenue_cents is not None:
        declare_revenue(org["id"], gross_revenue_cents=revenue_cents)
    project = ship_project(org, project)
    return org, ev, project


# ---------------------------------------------------------------------------
# Install reports & invoices
# ---------------------------------------------------------------------------

def get_project_version(project_id, headers=None):
    project = get_success_data(api_client.get_project(project_id, headers or ADMIN), 200)
    return project["version"]


def create_report(org, project_id, period_month, new_device_installs, reinstalls=0, bundle_installs=0):
    """Create an install report carrying the project's CURRENT version (OCC)."""
    headers = make_org_owner_headers(org["id"])
    version = get_project_version(project_id, headers)
    return get_success_data(
        api_client.create_install_report(
            project_id,
            create_install_report_payload(
                version,
                period_month=period_month,
                new_device_installs=new_device_installs,
                reinstalls=reinstalls,
                bundle_installs=bundle_installs,
            ),
            headers,
        ),
        201,
    )


def submit_report(org, report_id):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(api_client.submit_install_report(report_id, headers), 200)


def review_report(report_id, action, review_note=None):
    payload = {"action": action}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_install_report(report_id, payload, REVIEWER), 200)


def create_and_submit_report(org, project_id, period_month, new_device_installs,
                             reinstalls=0, bundle_installs=0):
    """DRAFT -> SUBMITTED; creates the PROVISIONAL invoice. Returns the report."""
    report = create_report(org, project_id, period_month, new_device_installs, reinstalls, bundle_installs)
    submit_report(org, report["id"])
    return get_success_data(api_client.get_install_report(report["id"], ADMIN), 200)


def create_and_accept_report(org, project_id, period_month, new_device_installs,
                             reinstalls=0, bundle_installs=0):
    """DRAFT -> SUBMITTED -> UNDER_REVIEW -> ACCEPTED; invoice FINALIZED. Returns the report."""
    report = create_and_submit_report(org, project_id, period_month, new_device_installs,
                                      reinstalls, bundle_installs)
    review_report(report["id"], "REVIEW")
    review_report(report["id"], "ACCEPT")
    return get_success_data(api_client.get_install_report(report["id"], ADMIN), 200)


def create_and_dispute_report(org, project_id, period_month, new_device_installs, note="disputed"):
    """DRAFT -> SUBMITTED -> UNDER_REVIEW -> DISPUTED; invoice DISPUTED. Returns the report."""
    report = create_and_submit_report(org, project_id, period_month, new_device_installs)
    review_report(report["id"], "REVIEW")
    review_report(report["id"], "DISPUTE", review_note=note)
    return get_success_data(api_client.get_install_report(report["id"], ADMIN), 200)


def get_invoice_for_report(report_id):
    """Reverse-lookup the invoice a report spawned (PRD §3.4 invoice filters)."""
    data, _meta = validate_paginated(api_client.list_invoices(ADMIN, params={"report_id": report_id}))
    assert len(data) == 1, f"expected exactly one invoice for report {report_id}, got {len(data)}"
    return data[0]


def get_project_invoice(project_id):
    data, _meta = validate_paginated(api_client.list_project_invoices(project_id, ADMIN))
    assert len(data) >= 1, f"expected at least one invoice for project {project_id}"
    return data[0]


def setup_shipped_project_with_lifetime(lifetime_installs, revenue_cents=160_000_000,
                                        version_string="2022.3.1f1", **project_overrides):
    """PRO org, revenue gate met, SHIPPED project whose lifetime_installs already
    equals `lifetime_installs` via one ACCEPTED report. Returns (org, ev, project, report1)."""
    org, ev, project = setup_shipped_project(
        revenue_cents=revenue_cents, version_string=version_string, **project_overrides
    )
    report1 = create_and_accept_report(org, project["id"], "2026-01", lifetime_installs)
    project = get_success_data(api_client.get_project(project["id"], ADMIN), 200)
    return org, ev, project, report1


# ---------------------------------------------------------------------------
# Seat subscriptions
# ---------------------------------------------------------------------------

def create_subscription(org, purchased_seats=2, coverage_start="2026-09-01",
                        coverage_end="2027-09-01", tier_code="PRO"):
    headers = make_org_owner_headers(org["id"])
    org_now = get_success_data(api_client.get_org(org["id"], headers), 200)
    return get_success_data(
        api_client.create_seat_subscription(
            org["id"],
            create_seat_subscription_payload(
                org_now["version"],
                tier_code=tier_code,
                purchased_seats=purchased_seats,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
            ),
            headers,
        ),
        201,
    )


def assign_seat(org, sub_id, member_label):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(api_client.assign_seat(sub_id, {"member_label": member_label}, headers), 200)


def setup_exhausted_subscription(purchased_seats=1):
    """PRO org + one subscription with every seat assigned (EXHAUSTED). Returns (org, sub)."""
    setup_personal_and_pro_tiers()
    org = create_org("PRO")
    sub = create_subscription(org, purchased_seats=purchased_seats)
    for i in range(purchased_seats):
        sub = assign_seat(org, sub["id"], f"dev{i}")
    return org, sub


# ---------------------------------------------------------------------------
# Asset marketplace
# ---------------------------------------------------------------------------

def setup_approved_listing(price_cents=200_000, title="Toolkit", creator_name="Creator Co",
                           creator_email="creator@example.com"):
    """Creator PRO org with an APPROVED listing. Returns (creator_org, listing)."""
    setup_personal_and_pro_tiers()
    creator = create_org("PRO", legal_name=creator_name, contact_email=creator_email)
    creator_headers = make_org_owner_headers(creator["id"])
    listing = get_success_data(
        api_client.create_asset_listing(
            creator["id"], create_asset_listing_payload(title=title, price_cents=price_cents), creator_headers
        ),
        201,
    )
    get_success_data(api_client.submit_listing_review(listing["id"], creator_headers), 200)
    listing = get_success_data(api_client.review_asset_listing(listing["id"], {"action": "APPROVE"}, REVIEWER), 200)
    return creator, listing


def setup_purchase(price_cents=200_000):
    """Creator org with APPROVED listing + distinct buyer org + COMPLETED purchase.
    Returns (creator_org, buyer_org, listing, purchase)."""
    creator, listing = setup_approved_listing(price_cents=price_cents)
    buyer = create_org("PRO", legal_name="Buyer Co", contact_email="buyer@example.com")
    purchase = get_success_data(
        api_client.purchase_asset_listing(listing["id"], make_org_owner_headers(buyer["id"])),
        201,
    )
    return creator, buyer, listing, purchase


# ---------------------------------------------------------------------------
# Export agreements & builds
# ---------------------------------------------------------------------------

def create_agreement(org, platform_code="CONSOLE_A", term_start="2026-01-01", term_end="2026-12-31"):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(
        api_client.create_export_agreement(
            org["id"],
            create_export_agreement_payload(
                platform_code=platform_code, term_start=term_start, term_end=term_end
            ),
            headers,
        ),
        201,
    )


def setup_active_agreement(platform_code="CONSOLE_A"):
    """PRO org + SHIPPED project + ACTIVE agreement. Returns (org, ev, project, agreement)."""
    org, ev, project = setup_shipped_project()
    agreement = create_agreement(org, platform_code=platform_code)
    agreement = get_success_data(api_client.activate_export_agreement(agreement["id"], ADMIN), 200)
    return org, ev, project, agreement


# ---------------------------------------------------------------------------
# Audit cases
# ---------------------------------------------------------------------------

def open_audit_case(org, trigger_reason="MANUAL"):
    return get_success_data(
        api_client.create_audit_case(org["id"], {"trigger_reason": trigger_reason}, AUDITOR), 201
    )


def setup_converted_org(resolved_tier_code="PRO", revenue_cents=25_000_000, period_month="2026-01"):
    """PERSONAL org converted to `resolved_tier_code` by audit. Returns (org, case)."""
    setup_personal_and_pro_tiers()
    org = create_org("PERSONAL")
    declare_revenue(org["id"], period_month=period_month, gross_revenue_cents=revenue_cents)
    case = open_audit_case(org, trigger_reason="REVENUE_CEILING_BREACH")
    get_success_data(api_client.request_audit_evidence(case["id"], AUDITOR), 200)
    case = get_success_data(
        api_client.resolve_audit_case(
            case["id"], {"outcome": "CONVERT", "resolved_tier_code": resolved_tier_code}, AUDITOR
        ),
        200,
    )
    org = get_success_data(api_client.get_org(org["id"], ADMIN), 200)
    return org, case


# ---------------------------------------------------------------------------
# Migration assessments
# ---------------------------------------------------------------------------

def create_migration(org, target_engine="OtherEngine"):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(
        api_client.create_migration_assessment(
            org["id"], create_migration_assessment_payload(target_engine=target_engine), headers
        ),
        201,
    )


def advance_migration(org, assessment_id, target):
    headers = make_org_owner_headers(org["id"])
    return get_success_data(
        api_client.advance_migration_assessment(assessment_id, {"target": target}, headers), 200
    )


def setup_cooling_off_migration(org):
    """Advance the org's fresh assessment to COOLING_OFF. Returns the assessment."""
    assessment = create_migration(org)
    advance_migration(org, assessment["id"], "EXPORT_READY")
    return advance_migration(org, assessment["id"], "COOLING_OFF")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), 200)
