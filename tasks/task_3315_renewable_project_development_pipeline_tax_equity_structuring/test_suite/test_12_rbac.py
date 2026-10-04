"""Role-based access control and the authentication-before-existence priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_milestone_payload,
    create_partnership_payload,
    create_project,
    create_project_payload,
    create_supply_agreement,
    get_success_data,
    make_construction_manager_headers,
    validate_error,
    validate_success,
)


def test_unauthenticated_beats_not_found(api, auditor_headers):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). ... These two checks run before any resource lookup or payload
    validation, in that order."

    Design: Corner/validations/unauthenticated_beats_not_found
    """
    # No role header at all — even a nonexistent id must surface 401 first.
    resp = api.get(" /api/projects/8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2".strip(),
                   headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_construction_manager_cannot_certify(
    api, developer_admin_headers, construction_manager_headers, tax_counsel_headers
):
    """PRD §2.1: "`ConstructionManager` — plans milestones and submits work
    evidence; may NOT certify (segregation of duties)."
    PRD §2.1: "A request whose role is authenticated but not permitted for the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/construction_manager_cannot_certify
    """
    project = create_project(name="RBAC Farm", target_capacity_mw=30,
                             resource_class="B")
    milestone = get_success_data(
        api.create_milestone(
            project["id"],
            create_milestone_payload(milestone_type="FOUNDATION", sequence_no=1),
            construction_manager_headers,
        )
    )
    get_success_data(
        api.submit_milestone_evidence(
            milestone["id"],
            {"evidence_uri": "s3://ev/rbac", "work_date": "2027-03-01T00:00:00Z"},
            make_construction_manager_headers("cm-1"),
        )
    )
    # Role denial fires even with a certifier id distinct from the submitter.
    resp = api.certify_milestone(
        milestone["id"], {"decision": "CERTIFIED"},
        make_construction_manager_headers("cm-2"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_investor_manager_cannot_run_distributions(
    api, developer_admin_headers, tax_counsel_headers, investor_manager_headers
):
    """PRD §2.1: "`InvestorManager` — tax equity investor operator; posts
    capital contributions only."
    PRD §2.1: "A request whose role is authenticated but not permitted for the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/investor_manager_cannot_run_distributions
    """
    project = create_project(name="RBAC Farm 2", technology="SOLAR",
                             target_capacity_mw=30, resource_class="B")
    ps = validate_success(
        api.create_partnership(
            project["id"],
            create_partnership_payload(
                investor_name="RBAC TE", commitment_usd=400000.00,
                target_irr_pct=7.0,
            ),
            tax_counsel_headers,
        ),
        expected_status=201,
    )
    resp = api.post_distribution(
        ps["id"],
        {"amount_usd": 1000.00, "period_end_date": "2027-12-31T00:00:00Z"},
        investor_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_auditor_is_read_only(
    api, developer_admin_headers, auditor_headers
):
    """PRD §2.1: "`Auditor` — read-only oversight across all resources."
    PRD §2.1: "A request whose role is authenticated but not permitted for the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/auditor_is_read_only
    """
    project = create_project(name="Audit Farm", technology="HYBRID",
                             target_capacity_mw=90, resource_class="A")
    resp = api.transition_project(project["id"], {"to": "ABANDONED"}, auditor_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = get_success_data(api.get_project(project["id"], auditor_headers))
    assert current["status"] == "PROSPECT"


def test_developer_admin_cannot_manage_procurement(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §2.1: "`DeveloperAdmin` — developer organization administrator; owns
    projects and site control." and "`ProcurementLead` — owns supply agreements
    and procurement orders, including safe-harbor deposits."
    PRD §2.1: "A request whose role is authenticated but not permitted for the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/developer_admin_cannot_manage_procurement
    """
    project = create_project(name="Peer Farm", target_capacity_mw=55)
    sa = create_supply_agreement(
        project["id"], supplier_name="Enercon", total_contract_usd=900000,
    )
    # The project owner cannot place procurement orders.
    resp = api.create_procurement_order(
        sa["id"],
        {"order_amount_usd": 800000, "safe_harbor_method": "FIVE_PERCENT_COST",
         "eligible_cost_basis_usd": 800000},
        developer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    # Procurement cannot transition projects.
    resp2 = api.transition_project(
        project["id"], {"to": "SITE_SECURED"}, procurement_lead_headers
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)
