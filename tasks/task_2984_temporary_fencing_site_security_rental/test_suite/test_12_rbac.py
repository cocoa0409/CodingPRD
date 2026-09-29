"""Who may act: the role matrix, the two identity controls and the front gate.

Covers the six roles of PRD §2.1 driving one rental end to end, the denial
sweep answered by `ERR_FORBIDDEN_ROLE` at rung 2, the four-eyes control of
PRD §2.9 at rung 7, the customer scope control of PRD §2.9 at rung 6, and the
authentication gate of PRD §2.1 at rung 1.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_ACCOUNT_SCOPE_VIOLATION,
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_integer

UNRESOLVABLE_ID = "00000000-0000-4000-8000-0000000000a1"
SEABOARD_SIGNER = "M. Ortiz"


def test_one_rental_passes_through_all_six_roles_without_a_single_refusal(api):
    """PRD §2.1: "`PlatformAdmin` owns reference data ... `AccountManager` is the
    commercial owner ... `CustomerContact` ... holds exactly one write capability —
    accepting an issued quote. `DispatchCoordinator` owns field operations ...
    `MunicipalLiaison` owns permitting ... `YardAuditor` owns returns." Every
    hand-off in the chain is admitted by the role that owns it.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    FX.set_clock(api, C.CLOCK_AUG_01)

    municipality = validate_success(
        api.create_municipality(F.municipality_payload(), U.PLATFORM_ADMIN),
        expected_status=201,
    )
    account = validate_success(
        api.create_account(F.account_payload(), U.ACCOUNT_MANAGER), expected_status=201
    )
    crew = validate_success(
        api.create_crew(F.crew_payload(), U.DISPATCH_COORDINATOR), expected_status=201
    )
    yard = validate_success(
        api.create_jobsite(
            F.jobsite_payload(account["id"], municipality["id"]), U.ACCOUNT_MANAGER
        ),
        expected_status=201,
    )
    dock_street = validate_success(
        api.create_jobsite(
            F.jobsite_payload(
                account["id"],
                municipality["id"],
                site_label="Dock Street North",
                address_line="8 Dock Street",
                site_condition=C.CONDITION_ASPHALT,
                requires_sidewalk_closure=True,
            ),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    # Reference data is the administrator's alone, and it may be registered even
    # after the commercial rows exist.
    validate_success(
        api.create_product(F.panel_product_payload(), U.PLATFORM_ADMIN),
        expected_status=201,
    )

    quote = validate_success(
        api.create_quote(
            yard["id"],
            F.quote_payload(yard["version"], linear_feet=500),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    validate_success(api.issue_quote(quote["id"], U.ACCOUNT_MANAGER))
    customer = U.make_customer_contact_headers(account["id"])
    validate_success(
        api.accept_quote(
            quote["id"], F.accept_payload(C.ACCEPTOR_CONSTRUCTION), customer
        )
    )
    contract = validate_success(
        api.create_contract(
            F.contract_payload(quote["id"], C.ACCEPTOR_CONSTRUCTION), U.ACCOUNT_MANAGER
        ),
        expected_status=201,
    )

    install = validate_success(
        api.create_work_order(
            contract["id"],
            F.work_order_payload(C.WO_DELIVERY_INSTALL, 500),
            U.DISPATCH_COORDINATOR,
        ),
        expected_status=201,
    )
    validate_success(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(crew["id"], "2026-08-03T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    validate_success(
        api.complete_work_order(
            install["id"], F.complete_payload(500), U.DISPATCH_COORDINATOR
        )
    )

    permit = validate_success(
        api.create_permit(F.permit_payload(dock_street["id"]), U.MUNICIPAL_LIAISON),
        expected_status=201,
    )
    validate_success(
        api.submit_permit(permit["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )
    validate_success(
        api.decide_permit(
            permit["id"],
            F.decision_payload(C.DECISION_APPROVE, reviewer_note="closure cleared"),
            U.MUNICIPAL_LIAISON,
        )
    )

    validate_success(
        api.create_payment(account["id"], F.payment_payload(40000), U.ACCOUNT_MANAGER)
    )

    removal = validate_success(
        api.create_work_order(
            contract["id"], F.work_order_payload(C.WO_REMOVAL, 500), U.DISPATCH_COORDINATOR
        ),
        expected_status=201,
    )
    validate_success(
        api.dispatch_work_order(
            removal["id"],
            F.dispatch_payload(crew["id"], "2026-08-05T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    validate_success(
        api.complete_work_order(
            removal["id"], F.complete_payload(500), U.DISPATCH_COORDINATOR
        )
    )

    listed = validate_success(
        api.list_reconciliations(
            U.YARD_AUDITOR,
            params={"work_order_id": removal["id"], "limit": C.MAX_LIMIT},
        )
    )
    assert len(listed) == 1, listed
    certified = validate_success(
        api.finalize_reconciliation(
            listed[0]["id"],
            F.finalize_payload([F.unit_return(C.PANEL_CODE, returned=50)]),
            U.YARD_AUDITOR,
        )
    )

    assert FX.read_quote(api, quote["id"])["status"] == C.QUOTE_CONVERTED
    assert FX.read_permit(api, permit["id"])["status"] == C.PERMIT_APPROVED
    assert FX.read_work_order(api, install["id"])["status"] == C.WO_COMPLETED
    assert FX.read_work_order(api, removal["id"])["status"] == C.WO_COMPLETED
    # ya-001 never reported the removal, so the four-eyes rule stood aside.
    assert certified["status"] == C.REC_FINALIZED
    assert certified["finalized_by_user_id"] == U.YARD_AUDITOR_ID


def test_no_role_may_reach_across_into_another_roles_exclusive_operation(api):
    """PRD §2.1: "no role is a superset of another", `PlatformAdmin` "is deliberately
    barred from every commercial and operational action; it cannot quote, convert,
    dispatch, permit, bill or certify", `MunicipalLiaison` "explicitly cannot
    dispatch against the permit it obtained", and a role outside the endpoint's
    admitted set "is rejected with `ERR_FORBIDDEN_ROLE`" at rung 2 — above the
    request-shape rung.

    Design: Corner/rbac/roles_cannot_invoke_another_roles_exclusive_operations
    """
    world = FX.seed_world(api)
    jobsite_id = world["jobsite"]["id"]
    account_id = world["account"]["id"]
    contract, quote = FX.seed_contract(api, jobsite_id, account_id, linear_feet=500)
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    live_version = FX.jobsite_version(api, jobsite_id)
    customer = U.make_customer_contact_headers(account_id)

    # An administrator may not price work.
    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(live_version, linear_feet=500),
            U.PLATFORM_ADMIN,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The commercial owner may not send a crew.
    validate_error(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(world["crew"]["id"], "2026-08-03T08:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The customer's single write does not extend to permitting.
    validate_error(
        api.create_permit(
            F.permit_payload(jobsite_id, closure_linear_feet=100), customer
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # Permitting does not extend to commercial issuance or conversion.
    validate_error(
        api.issue_quote(quote["id"], U.MUNICIPAL_LIAISON), ERR_FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.create_contract(
            F.contract_payload(quote["id"], C.ACCEPTOR_CONSTRUCTION), U.YARD_AUDITOR
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # Field operations do not extend to billing.
    validate_error(
        api.create_billing_run(
            contract["id"],
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # Rung 2 answers before rung 3, so the impossible 9,999 feet is never reached.
    validate_error(
        api.complete_work_order(
            install["id"], F.complete_payload(9999), U.YARD_AUDITOR
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # Not one refusal left a trace.
    quotes = api.list_quotes(
        U.ACCOUNT_MANAGER, params={"jobsite_id": jobsite_id, "limit": C.MAX_LIMIT}
    ).json()
    assert_integer(quotes["meta"]["total_count"], 1, "total_count")
    assert quotes["data"][0]["id"] == quote["id"]
    assert_integer(FX.jobsite_version(api, jobsite_id), live_version, "version")

    unmoved = FX.read_work_order(api, install["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None

    permits = api.list_permits(
        U.MUNICIPAL_LIAISON, params={"jobsite_id": jobsite_id, "limit": C.MAX_LIMIT}
    ).json()
    assert permits["data"] == [], permits
    assert FX.invoices_for(api, contract["id"], invoice_kind=C.KIND_PERIODIC) == []


def test_the_four_eyes_control_is_keyed_on_the_user_id_and_not_on_the_role(api):
    """PRD §2.9: "Voiding an invoice is refused when `X-User-ID` equals the invoice's
    `issued_by_user_id`. Finalizing a removal reconciliation is refused when
    `X-User-ID` equals the `completed_by_user_id` recorded on the removal work
    order", and both are evaluated at rung 7 — above the state check.

    Design: Corner/rbac/same_user_cannot_reverse_or_certify_their_own_artefact
    """
    world = FX.seed_world(api)
    state = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]

    FX.set_clock(api, "2026-08-29T00:00:00Z")
    periodic = validate_success(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert periodic["issued_by_user_id"] == U.ACCOUNT_MANAGER_ID

    removal = FX.plan_work_order(api, contract_id, C.WO_REMOVAL, 500)
    FX.dispatch(api, removal["id"], world["crew"]["id"], "2026-08-31T08:00:00Z")
    reported = FX.complete(api, removal["id"], 500)
    assert reported["completed_by_user_id"] == U.DISPATCH_COORDINATOR_ID

    reconciliations = validate_success(
        api.list_reconciliations(
            U.YARD_AUDITOR,
            params={"work_order_id": removal["id"], "limit": C.MAX_LIMIT},
        )
    )
    assert len(reconciliations) == 1, reconciliations
    reconciliation = reconciliations[0]
    assert reconciliation["status"] == C.REC_OPEN

    # The issuer holds the right role and is still refused its own reversal.
    validate_error(
        api.void_invoice(periodic["id"], F.void_payload(), U.ACCOUNT_MANAGER),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert FX.read_invoice(api, periodic["id"])["status"] == C.INVOICE_ISSUED

    # A correct YardAuditor role carrying the completer's identifier is refused.
    validate_error(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload([F.unit_return(C.PANEL_CODE, returned=50)]),
            U.make_yard_auditor_headers(U.DISPATCH_COORDINATOR_ID),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    held = FX.read_reconciliation(api, reconciliation["id"])
    assert held["status"] == C.REC_OPEN
    assert held["finalized_by_user_id"] is None

    # The identical calls made by a second identifier of the same role succeed.
    voided = validate_success(
        api.void_invoice(periodic["id"], F.void_payload(), U.ACCOUNT_MANAGER_2)
    )
    assert voided["status"] == C.INVOICE_VOID

    certified = validate_success(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload([F.unit_return(C.PANEL_CODE, returned=50)]),
            U.YARD_AUDITOR,
        )
    )
    assert certified["status"] == C.REC_FINALIZED
    assert certified["finalized_by_user_id"] == U.YARD_AUDITOR_ID


def test_a_customer_may_not_read_or_sign_another_accounts_quote(api):
    """PRD §2.1: "A `CustomerContact` that reads or acts on a row resolving to a
    different account is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION`", and PRD §2.7
    puts that control at rung 6 — above the rung-9 state check, so it answers even
    when the quote's own status would have refused the call anyway.

    Design: Corner/rbac/customer_contact_cannot_read_or_accept_another_accounts_quote
    """
    world = FX.seed_world(api, jobsite={"site_label": "Foundry Road Phase Yard"})
    ridgeline_id = world["account"]["id"]
    seaboard = FX.seed_account(
        api,
        legal_name="Seaboard Events Inc",
        billing_email="ap@seaboard.example",
    )
    festival_lawn = FX.seed_jobsite(
        api,
        seaboard["id"],
        world["municipality"]["id"],
        site_label="Harbor Green Festival Lawn",
        address_line="1 Harbor Green",
    )

    ridgeline_draft = FX.seed_quote(api, world["jobsite"]["id"], linear_feet=300)
    seaboard_quote = FX.seed_quote(
        api, festival_lawn["id"], event=True, linear_feet=500
    )
    seaboard_issued = FX.issue_quote(api, seaboard_quote["id"])
    assert seaboard_issued["status"] == C.QUOTE_ISSUED
    assert ridgeline_draft["status"] == C.QUOTE_DRAFT

    ridgeline_contact = U.make_customer_contact_headers(ridgeline_id)
    seaboard_contact = U.make_customer_contact_headers(seaboard["id"])

    # The row exists and is readable by staff, so this is a scope answer, not a 404.
    validate_error(
        api.get_quote(seaboard_quote["id"], ridgeline_contact),
        ERR_ACCOUNT_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.accept_quote(
            seaboard_quote["id"],
            F.accept_payload(C.ACCEPTOR_CONSTRUCTION),
            ridgeline_contact,
        ),
        ERR_ACCOUNT_SCOPE_VIOLATION,
        403,
    )
    assert FX.read_quote(api, seaboard_quote["id"])["status"] == C.QUOTE_ISSUED

    # Rung 6 outranks rung 9: the DRAFT status of Ridgeline's quote never speaks.
    validate_error(
        api.accept_quote(
            ridgeline_draft["id"], F.accept_payload(SEABOARD_SIGNER), seaboard_contact
        ),
        ERR_ACCOUNT_SCOPE_VIOLATION,
        403,
    )
    untouched = FX.read_quote(api, ridgeline_draft["id"])
    assert untouched["status"] == C.QUOTE_DRAFT
    assert untouched["accepted_by_name"] is None

    signed = validate_success(
        api.accept_quote(
            seaboard_quote["id"], F.accept_payload(SEABOARD_SIGNER), seaboard_contact
        )
    )
    assert signed["status"] == C.QUOTE_ACCEPTED
    assert signed["accepted_by_name"] == SEABOARD_SIGNER


def test_the_identity_headers_are_checked_before_anything_else_in_the_request(api):
    """PRD §2.1: "Both must be present and non-empty; a header supplied as an empty
    string counts as absent and the request is rejected with `ERR_UNAUTHENTICATED`",
    and PRD §2.7 puts "(1) authentication of the two identity headers" at the foot of
    the ladder, below the shape and path-resolution rungs.

    Design: Corner/rbac/missing_or_empty_identity_headers_return_unauthenticated
    """
    world = FX.seed_world(api)
    municipality_id = world["municipality"]["id"]
    live_version = world["jobsite"]["version"]

    # A body that would break the enum rule and the positivity rule at rung 3, on a
    # path id that resolves to nothing at rung 4.
    doomed_quote = {
        "expected_jobsite_version": live_version,
        "contract_type": "FESTIVAL",
        "linear_feet": -40,
        "panel_product_code": C.PANEL_CODE,
        "term_months": 3,
        "wind_screen": C.SCREEN_NONE,
    }

    broken_identities = (
        U.headers_with_blank_user_id(C.ROLE_PLATFORM_ADMIN),
        U.headers_without_user_id(C.ROLE_PLATFORM_ADMIN),
        U.headers_with_blank_role(U.PLATFORM_ADMIN_ID),
        U.headers_without_role(U.PLATFORM_ADMIN_ID),
        U.NO_HEADERS,
    )
    for headers in broken_identities:
        # A read is gated exactly as a write is.
        validate_error(
            api.get_municipality(municipality_id, headers), ERR_UNAUTHENTICATED, 401
        )

    for headers in (
        U.headers_with_blank_user_id(C.ROLE_ACCOUNT_MANAGER),
        U.headers_without_user_id(C.ROLE_ACCOUNT_MANAGER),
        U.headers_with_blank_role(U.ACCOUNT_MANAGER_ID),
        U.headers_without_role(U.ACCOUNT_MANAGER_ID),
    ):
        validate_error(
            api.create_quote(UNRESOLVABLE_ID, doomed_quote, headers),
            ERR_UNAUTHENTICATED,
            401,
        )

    quotes = api.list_quotes(U.ACCOUNT_MANAGER, params={"limit": C.MAX_LIMIT}).json()
    assert quotes["data"] == [], quotes
    assert_integer(quotes["meta"]["total_count"], 0, "total_count")

    # The same path with complete headers answers, so the 401s came from the
    # identity headers alone.
    readable = validate_success(api.get_municipality(municipality_id, U.PLATFORM_ADMIN))
    assert readable["id"] == municipality_id
    assert readable["jurisdiction_code"] == C.HRB_CODE
