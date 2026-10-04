"""Role-based access control denials."""
from test_helpers import (
    ApiErrorId,
    create_contract_payload,
    create_hospital_partnership_payload,
    create_partnership_milestone_payload,
    create_source_organization_payload,
    get_success_data,
    make_contract_manager_headers,
    make_donor_relations_headers,
    make_hospital_partner_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
    set_clock,
    setup_standard_priced,
    validate_error,
    validate_success,
)


class TestContractRoleExclusivity:
    def test_portfolio_analyst_cannot_execute_contract(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "Execution, also by a `ContractManager`, enforces four checks"

        Design: Corner/rbac/portfolio_analyst_cannot_execute_contract_forbidden
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers()
        contract = get_success_data(
            api.create_contract(
                pf["id"], create_contract_payload(pf["version"]), cm
            )
        )
        resp = api.execute_contract(
            contract["id"], make_portfolio_analyst_headers()
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        fetched = get_success_data(api.get_contract(contract["id"], cm))
        assert fetched["status"] == "DRAFT"

    def test_contract_manager_cannot_settle(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "Settlement belongs to a `FinanceOfficer` — and segregation of
        duties is enforced: the settler's `X-User-ID` must differ from
        `executed_by`, or the settle is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/contract_manager_cannot_settle_forbidden
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers("cm-1")
        contract = get_success_data(
            api.create_contract(
                pf["id"], create_contract_payload(pf["version"]), cm
            )
        )
        get_success_data(api.execute_contract(contract["id"], cm))
        # A ContractManager is not permitted to settle at all, even under a
        # different user id (this is role denial, not segregation of duties).
        resp = api.settle_contract(
            contract["id"], make_contract_manager_headers("cm-2")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        fetched = get_success_data(api.get_contract(contract["id"], cm))
        assert fetched["status"] == "EXECUTED"


class TestHospitalPartnerOwnership:
    def test_hospital_partner_marks_only_own_org_milestone(self, api):
        """PRD §3.9: "marking a milestone met — available to the officer, and to
        a `HospitalPartner` only when the caller's `X-User-ID` equals the
        partnership's `source_org_id` (`ERR_FORBIDDEN` otherwise) — moves it
        from `PENDING` or `MISSED` to terminal `MET`"
        PRD §2.1: "When `X-User-Role` is `HospitalPartner`, `X-User-ID` is the
        `id` of the acting `SourceOrganization`; ownership checks on any
        resource that references a `SourceOrganization` — concretely, the
        milestone mark-met operation — compare the resource's foreign-key field
        to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/hospital_partner_marks_only_own_org_milestone
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        org_b = get_success_data(
            api.create_source_organization(
                create_source_organization_payload(
                    name="County General", state_code="OK"
                ),
                admin,
            )
        )
        hp = get_success_data(
            api.create_hospital_partnership(
                create_hospital_partnership_payload(
                    org["id"], fap_baseline_score=10, fap_target_score=90
                ),
                dro,
            )
        )
        get_success_data(api.activate_hospital_partnership(hp["id"], dro))
        milestone = get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                create_partnership_milestone_payload(
                    "FAP-1", description="own", weight=100
                ),
                dro,
            )
        )
        # Another organization's id is rejected.
        resp = api.mark_milestone_met(
            milestone["id"], make_hospital_partner_headers(org_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        # The owning organization's id succeeds.
        resp = api.mark_milestone_met(
            milestone["id"], make_hospital_partner_headers(org["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "MET"
