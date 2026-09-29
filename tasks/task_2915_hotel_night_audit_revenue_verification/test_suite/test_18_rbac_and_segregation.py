"""The role matrix: exclusives, denials, shared endpoints and segregation of duties.

Covers PRD section 2.1 (the six operator roles and the endpoint role lists of
PRD section 4), PRD section 2.12 (authorization before every other check) and
PRD section 2.10 (the originator of a record is locked out of deciding it).
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_null_fields,
    assert_row_count,
    find_by,
    single,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_headers,
    make_outlet_manager_headers,
)

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_every_role_can_run_its_own_declared_exclusive_operations(api):
    """One walk in which each role's exclusive endpoints all answer successfully.

    PRD section 4 gives the eight pipeline and settlement operations of the night
    audit — the room-and-tax pass, sealing charges, verifying settlements, sweeping the
    city ledger, balancing, closing, requesting a recount and capturing an
    authorization — to the NightAuditor alone; registering a property, registering an
    outlet and suspending one to the PropertyAdmin alone; reopening a day, revoking a
    document and tying out a period to the Controller alone; and reserves the
    RevenueManager's decision set of accepting a variance, reviewing paperwork,
    distributing a report and rejecting, returning or reversing an allowance. PRD
    section 3.4 lets an OutletManager open, close and void its own checks and declare
    and redeclare its own batches.

    Design: Corner/rbac/rbac_exclusive_operations_every_role_can_run_its_own_declared_exclusives
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = validate_success(
        api.create_property(f.build_property_payload(), ADMIN), expected_status=201
    )
    lounge = validate_success(
        api.create_outlet(
            f.build_outlet_payload(
                prop["id"],
                outlet_code="LOBBY",
                outlet_name="Lobby Lounge",
                outlet_type="FB_OUTLET",
                requires_shift_settlement=True,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RB1",
        guest_name="Nils Aakre",
        room_number="1301",
        credit_limit_amount=5000.00,
    )
    fx.check_in(api, folio["id"])
    manager = make_outlet_manager_headers(lounge["id"])

    kept = validate_success(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                lounge["id"], bd["id"], 100.00, ticket_number="T-RB-1"
            ),
            manager,
        ),
        expected_status=201,
    )
    validate_success(
        api.close_outlet_ticket(
            kept["id"], manager, f.build_close_ticket_payload("2026-08-01T09:00:00.000Z")
        )
    )
    scrapped = validate_success(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                lounge["id"], bd["id"], 60.00, ticket_number="T-RB-2"
            ),
            manager,
        ),
        expected_status=201,
    )
    validate_success(
        api.close_outlet_ticket(
            scrapped["id"],
            manager,
            f.build_close_ticket_payload("2026-08-01T09:00:00.000Z"),
        )
    )
    voided = validate_success(api.void_outlet_ticket(scrapped["id"], manager))
    assert_fields(voided, {"status": "VOID"})
    batch = validate_success(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(bd["id"], lounge["id"], 100.00), manager
        ),
        expected_status=201,
    )

    authorization = fx.create_card_authorization(api, folio["id"], 500.00)
    to_reject = fx.create_allowance(api, folio["id"], bd["id"], 200.00)
    to_return = fx.create_allowance(api, folio["id"], bd["id"], 200.00)
    to_reverse = fx.create_allowance(api, folio["id"], bd["id"], 200.00)
    for allowance in [to_reject, to_return, to_reverse]:
        validate_success(api.submit_allowance(allowance["id"], FRONT_DESK))

    assert_fields(
        validate_success(api.post_room_and_tax(bd["id"], AUDITOR)),
        {"status": "ROOM_POSTING"},
    )
    validate_success(
        api.capture_card_authorization(
            authorization["id"], f.build_capture_payload(100.00, bd["id"]), AUDITOR
        )
    )
    validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))

    assert_fields(
        validate_success(api.reject_allowance(to_reject["id"], REVENUE_MANAGER)),
        {"status": "REJECTED"},
    )
    assert_fields(
        validate_success(
            api.return_allowance_for_revision(to_return["id"], REVENUE_MANAGER)
        ),
        {"status": "RETURNED_FOR_REVISION"},
    )
    validate_success(
        api.approve_allowance(to_reverse["id"], f.build_approve_payload(200.00), AUDITOR)
    )
    get_success_data(api.reverse_allowance(to_reverse["id"], REVENUE_MANAGER))

    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-02",
    )
    assert_fields(
        validate_success(
            api.review_authorization_document(
                document["id"], f.build_review_payload("APPROVE"), REVENUE_MANAGER
            )
        ),
        {"status": "ACTIVE"},
    )
    assert_fields(
        validate_success(api.revoke_authorization_document(document["id"], CONTROLLER)),
        {"status": "REVOKED"},
    )

    assert_fields(
        validate_success(api.seal_charges(bd["id"], AUDITOR)), {"status": "CHARGES_SEALED"}
    )
    assert_fields(
        validate_success(api.verify_settlements(bd["id"], AUDITOR)),
        {"status": "SETTLEMENT_REVIEW"},
    )
    assert_fields(
        validate_success(api.request_recount(batch["id"], AUDITOR)),
        {"status": "RECOUNT_REQUESTED"},
    )
    assert_fields(
        validate_success(
            api.redeclare_batch(batch["id"], f.build_redeclare_payload(100.00), manager)
        ),
        {"status": "DECLARED"},
    )
    validate_success(api.verify_settlements(bd["id"], AUDITOR))
    assert_fields(
        validate_success(api.accept_variance(batch["id"], REVENUE_MANAGER)),
        {"status": "ACCEPTED_WITH_VARIANCE"},
    )

    def publish():
        report = validate_success(
            api.create_revenue_report(
                f.build_revenue_report_payload(
                    bd["id"], fx.business_date_version(api, bd["id"]), ["Controller"]
                ),
                REVENUE_MANAGER,
            ),
            expected_status=201,
        )
        assert_fields(
            validate_success(
                api.distribute_revenue_report(report["id"], REVENUE_MANAGER)
            ),
            {"status": "DISTRIBUTED"},
        )

    publish()
    assert_fields(
        validate_success(api.balance_business_date(bd["id"], AUDITOR)),
        {"status": "BALANCED"},
    )
    assert_fields(
        validate_success(api.close_business_date(bd["id"], AUDITOR)), {"status": "CLOSED"}
    )

    assert_fields(
        validate_success(api.reopen_business_date(bd["id"], CONTROLLER)),
        {"status": "REOPENED"},
    )
    publish()
    validate_success(api.balance_business_date(bd["id"], AUDITOR))
    reclosed = validate_success(api.close_business_date(bd["id"], AUDITOR))
    assert_fields(reclosed, {"status": "CLOSED"})

    tied_out = validate_success(
        api.tie_out_period(
            bd["accounting_period_id"],
            f.build_tie_out_payload(reclosed["total_revenue_amount"]),
            CONTROLLER,
        )
    )
    assert_fields(tied_out, {"status": "TIED_OUT"})

    suspended = validate_success(api.suspend_outlet(lounge["id"], ADMIN))
    assert_fields(suspended, {"status": "SUSPENDED"})


def _matrix_scenario(api):
    """An OPEN day with one reserved account, one open check, one PENDING document
    and one SUBMITTED allowance, ready to be poked by the wrong roles."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RB2",
        guest_name="Pia Rekdal",
        room_number="1401",
    )
    ticket = fx.create_outlet_ticket(
        api, lounge["id"], bd["id"], 100.00, ticket_number="T-RB-9"
    )
    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-02",
    )
    allowance = fx.create_allowance(api, folio["id"], bd["id"], 200.00)
    validate_success(api.submit_allowance(allowance["id"], FRONT_DESK))
    authorization = fx.create_card_authorization(api, folio["id"], 500.00)
    return prop, lounge, bd, folio, ticket, document, allowance, authorization


def test_no_role_can_reach_another_roles_exclusive_operations(api):
    """Every off-matrix call is refused 403 ERR_UNAUTHORIZED and moves nothing.

    PRD section 2.12 places the authorization check second, ahead of request shape and
    ahead of path existence, so an operator outside an endpoint's role list is refused
    ERR_UNAUTHORIZED (HTTP 403) even when the rest of the call is unusable. PRD section 4
    keeps the Controller out of the audit pipeline and the guest-facing desk, the
    RevenueManager out of reopening, revoking and tying out, the NightAuditor out of the
    revenue decisions, the PropertyAdmin out of the ledger and the allowance ladder, the
    FrontDeskAgent out of the pipeline and the outlet registry, and the OutletManager out
    of everything but its own checks and batches. PRD section 2.3 only bumps `version` on
    a write that lands, so every target row is untouched.

    Design: Corner/rbac/rbac_unauthorized_denial_no_role_reaches_another_roles_exclusives
    """
    prop, lounge, bd, folio, ticket, document, allowance, authorization = (
        _matrix_scenario(api)
    )
    allowance_version = fx.read_allowance(api, allowance["id"])["version"]
    capture = f.build_capture_payload(100.00, bd["id"])
    posting = f.build_journal_posting_payload(bd["id"], amount=25.00, folio_id=folio["id"])

    refusals = [
        # The Controller audits the books; the Controller does not run the audit.
        api.post_room_and_tax(bd["id"], CONTROLLER),
        api.seal_charges(bd["id"], CONTROLLER),
        api.verify_settlements(bd["id"], CONTROLLER),
        api.city_ledger_sweep(bd["id"], CONTROLLER),
        api.balance_business_date(bd["id"], CONTROLLER),
        api.close_business_date(bd["id"], CONTROLLER),
        api.request_recount(MISSING_UUID, CONTROLLER),
        api.capture_card_authorization(authorization["id"], capture, CONTROLLER),
        api.check_in(folio["id"], CONTROLLER),
        api.close_outlet_ticket(
            ticket["id"], CONTROLLER, f.build_close_ticket_payload("2026-08-01T09:00:00.000Z")
        ),
        # The RevenueManager decides; the RevenueManager does not unwind or certify.
        api.reopen_business_date(bd["id"], REVENUE_MANAGER),
        api.revoke_authorization_document(document["id"], REVENUE_MANAGER),
        api.tie_out_period(
            bd["accounting_period_id"], f.build_tie_out_payload(0.00), REVENUE_MANAGER
        ),
        # The NightAuditor executes; the NightAuditor does not adjudicate.
        api.reject_allowance(allowance["id"], AUDITOR),
        api.return_allowance_for_revision(allowance["id"], AUDITOR),
        api.reverse_allowance(allowance["id"], AUDITOR),
        api.accept_variance(MISSING_UUID, AUDITOR),
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), AUDITOR
        ),
        api.distribute_revenue_report(MISSING_UUID, AUDITOR),
        # The PropertyAdmin configures; the PropertyAdmin does not transact.
        api.create_journal_posting(posting, ADMIN),
        api.check_in(folio["id"], ADMIN),
        api.seal_charges(bd["id"], ADMIN),
        api.close_business_date(bd["id"], ADMIN),
        api.create_allowance(
            f.build_allowance_payload(folio["id"], bd["id"], 50.00), ADMIN
        ),
        api.submit_allowance(allowance["id"], ADMIN),
        api.approve_allowance(allowance["id"], f.build_approve_payload(200.00), ADMIN),
        # The FrontDeskAgent serves guests; the FrontDeskAgent does not run nights.
        api.post_room_and_tax(bd["id"], FRONT_DESK),
        api.balance_business_date(bd["id"], FRONT_DESK),
        api.close_business_date(bd["id"], FRONT_DESK),
        api.create_outlet(
            f.build_outlet_payload(prop["id"], outlet_code="SPA"), FRONT_DESK
        ),
        api.suspend_outlet(lounge["id"], FRONT_DESK),
        # The OutletManager owns one capture point and nothing else.
        api.create_journal_posting(posting, make_outlet_manager_headers(lounge["id"])),
        api.post_room_and_tax(bd["id"], make_outlet_manager_headers(lounge["id"])),
        api.seal_charges(bd["id"], make_outlet_manager_headers(lounge["id"])),
        api.close_business_date(bd["id"], make_outlet_manager_headers(lounge["id"])),
    ]
    for response in refusals:
        validate_error(response, E.ERR_UNAUTHORIZED, expected_status=403)

    day = fx.read_business_date(api, bd["id"])
    assert_fields(day, {"status": "OPEN", "version": 1})
    assert_money(day["total_revenue_amount"], 0.00, "total_revenue_amount")
    assert_fields(
        fx.read_folio(api, folio["id"]), {"stay_status": "RESERVED", "version": 1}
    )
    assert_fields(fx.read_ticket(api, ticket["id"]), {"status": "OPEN", "version": 1})
    assert_fields(fx.read_document(api, document["id"]), {"status": "PENDING", "version": 1})
    assert_null_fields(fx.read_document(api, document["id"]), ["reviewed_by_user_id"])
    assert_fields(
        fx.read_allowance(api, allowance["id"]),
        {"status": "SUBMITTED", "version": allowance_version},
    )
    assert_fields(
        validate_success(api.get_outlet(lounge["id"], ADMIN)),
        {"status": "ACTIVE", "version": 1},
    )
    assert_fields(
        fx.read_period(api, bd["accounting_period_id"]),
        {"status": "OPEN"},
    )
    assert_row_count(
        validate_success(api.list_outlets(ADMIN, property_id=prop["id"])), 1, "outlets"
    )
    assert_row_count(
        validate_success(api.list_journal_postings(AUDITOR, business_date_id=bd["id"])),
        0,
        "journal lines",
    )


def test_a_shared_endpoint_admits_every_role_it_names_and_attributes_each_call(api):
    """Three roles post the same charge and earn three separately attributed lines.

    PRD section 4 shares the journal with the NightAuditor, the FrontDeskAgent and the
    Controller, the reversal with the NightAuditor and the Controller, the operating-day
    registry with the PropertyAdmin and the NightAuditor, outlet checks with the
    OutletManager and the NightAuditor, ledger accounts with the PropertyAdmin and the
    Controller, and the rebate ladder's entry point with the NightAuditor, the
    FrontDeskAgent and the RevenueManager. PRD section 2.1 records the acting
    `X-User-ID` as `posted_by_user_id` and `requested_by_user_id`, so a shared permission
    still yields a per-operator attribution — and per PRD section 2.1 the outlet-scope
    comparison is written for the OutletManager alone, which is why a NightAuditor may
    work any outlet's check.

    Design: Corner/rbac/rbac_shared_operations_each_listed_role_reaches_the_shared_endpoint
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RB3",
        guest_name="Tor Vangen",
        room_number="1501",
        credit_limit_amount=5000.00,
    )
    fx.check_in(api, folio["id"])
    assert_money(
        fx.read_folio(api, folio["id"])["charges_total_amount"],
        0.00,
        "charges_total_amount before the shared postings",
    )

    posted = {}
    for role_headers, user_id in [
        (AUDITOR, "u_na_1"),
        (FRONT_DESK, "u_fd_1"),
        (CONTROLLER, "u_ctl_1"),
    ]:
        line = validate_success(
            api.create_journal_posting(
                f.build_journal_posting_payload(
                    bd["id"], charge_type="MISC_CHARGE", amount=10.00, folio_id=folio["id"]
                ),
                role_headers,
            ),
            expected_status=201,
        )
        assert_fields(line, {"posted_by_user_id": user_id})
        posted[user_id] = line

    rows = validate_success(
        api.list_journal_postings(
            AUDITOR, folio_id=folio["id"], charge_type="MISC_CHARGE"
        )
    )
    assert_row_count(rows, 3, "shared MISC_CHARGE lines")
    for user_id in ["u_na_1", "u_fd_1", "u_ctl_1"]:
        assert_row_count(
            find_by(rows, posted_by_user_id=user_id), 1, f"lines posted by {user_id}"
        )
    assert_money(
        fx.read_folio(api, folio["id"])["charges_total_amount"],
        30.00,
        "charges_total_amount after the shared postings",
    )

    # The operating-day registry is shared between the configurer and the auditor.
    for headers, business_date in [(ADMIN, "2026-08-02"), (AUDITOR, "2026-08-03")]:
        validate_success(
            api.create_business_date(
                f.build_business_date_payload(
                    prop["id"], business_date, out_of_order_room_count=4
                ),
                headers,
            ),
            expected_status=201,
        )

    # An outlet check may be raised and closed by its own outlet or by the auditor.
    manager = make_outlet_manager_headers(lounge["id"])
    for headers, number in [(manager, "T-SH-1"), (AUDITOR, "T-SH-2")]:
        ticket = validate_success(
            api.create_outlet_ticket(
                f.build_outlet_ticket_payload(
                    lounge["id"], bd["id"], 100.00, ticket_number=number
                ),
                headers,
            ),
            expected_status=201,
        )
        closed = validate_success(
            api.close_outlet_ticket(
                ticket["id"],
                headers,
                f.build_close_ticket_payload("2026-08-01T18:00:00.000Z"),
            )
        )
        assert_fields(closed, {"status": "CLOSED"})

    # Ledger accounts are shared between the configurer and the certifier.
    for headers in [ADMIN, CONTROLLER]:
        validate_success(
            api.create_ledger_account(f.build_ledger_account_payload(prop["id"]), headers),
            expected_status=201,
        )

    # Reversal is shared between the auditor and the certifier, and neither one
    # reverses a line of their own.
    first_reversal = validate_success(
        api.reverse_journal_posting(posted["u_fd_1"]["id"], AUDITOR), expected_status=201
    )
    assert_fields(first_reversal, {"reverses_posting_id": posted["u_fd_1"]["id"]})
    second_reversal = validate_success(
        api.reverse_journal_posting(posted["u_na_1"]["id"], CONTROLLER),
        expected_status=201,
    )
    assert_fields(second_reversal, {"reverses_posting_id": posted["u_na_1"]["id"]})

    # The rebate's entry point is shared between three roles, and each keeps its author.
    for headers, user_id in [
        (AUDITOR, "u_na_1"),
        (FRONT_DESK, "u_fd_1"),
        (REVENUE_MANAGER, "u_rm_1"),
    ]:
        allowance = validate_success(
            api.create_allowance(
                f.build_allowance_payload(folio["id"], bd["id"], 100.00), headers
            ),
            expected_status=201,
        )
        assert_fields(allowance, {"requested_by_user_id": user_id, "status": "DRAFT"})
        submitted = validate_success(api.submit_allowance(allowance["id"], headers))
        assert_fields(
            submitted, {"status": "SUBMITTED", "requested_by_user_id": user_id}
        )


def test_the_originator_of_a_record_is_locked_out_of_deciding_it(api):
    """Paperwork, a journal line and a cash drawer all refuse their own author.

    PRD section 2.10 bars the operator recorded in `filed_by_user_id` from reviewing
    approval paperwork and the operator recorded in `declared_by_user_id` from accepting a
    batch variance, both with ERR_SELF_APPROVAL_FORBIDDEN (HTTP 403), while PRD section 2.8
    gives the poster's own reversal its own code, ERR_SELF_REVERSAL_FORBIDDEN (HTTP 403).
    PRD section 2.1 stresses that role authority never overrides that bar and that the
    comparison is against the recorded identity, so the same Controller role that is
    refused on its own document reviews another operator's freely, and a second identity
    of the same role signs off where the declarer cannot. PRD section 2.12 keeps
    authorization ahead of the segregation check, so an operator outside the endpoint's
    role list never reaches the identity comparison at all.

    Design: Corner/rbac/rbac_segregation_of_duties_the_originator_is_locked_out_of_the_decision
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RB4",
        guest_name="Idun Sagen",
        room_number="1601",
        credit_limit_amount=5000.00,
    )
    fx.check_in(api, folio["id"])
    document = fx.create_authorization_document(
        api,
        prop["id"],
        headers=CONTROLLER,
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-02",
    )
    assert_fields(document, {"filed_by_user_id": "u_ctl_1"})
    posting = fx.post_journal_line(
        api,
        bd["id"],
        charge_type="MISC_CHARGE",
        amount=25.00,
        headers=CONTROLLER,
        folio_id=folio["id"],
    )
    assert_fields(posting, {"posted_by_user_id": "u_ctl_1"})

    # The filer may not review its own paperwork, whatever its role entitles.
    validate_error(
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), CONTROLLER
        ),
        E.ERR_SELF_APPROVAL_FORBIDDEN,
        expected_status=403,
    )
    unmoved = fx.read_document(api, document["id"])
    assert_fields(unmoved, {"status": "PENDING", "version": 1})
    assert_null_fields(unmoved, ["reviewed_by_user_id"])

    reviewed = validate_success(
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), REVENUE_MANAGER
        )
    )
    assert_fields(reviewed, {"status": "ACTIVE", "reviewed_by_user_id": "u_rm_1"})

    # The poster may not reverse its own line, and that clash carries its own code.
    validate_error(
        api.reverse_journal_posting(posting["id"], CONTROLLER),
        E.ERR_SELF_REVERSAL_FORBIDDEN,
        expected_status=403,
    )
    reversal = validate_success(
        api.reverse_journal_posting(posting["id"], AUDITOR), expected_status=201
    )
    assert_fields(reversal, {"posted_by_user_id": "u_na_1"})
    assert_money(reversal["amount"], -25.00, "the reversing amount")
    assert_fields(
        single(
            validate_success(
                api.list_journal_postings(AUDITOR, reverses_posting_id=posting["id"])
            ),
            "reversing line",
        ),
        {"id": reversal["id"]},
    )

    manager = make_outlet_manager_headers(lounge["id"])
    ticket = fx.create_outlet_ticket(
        api, lounge["id"], bd["id"], 100.00, ticket_number="T-SD-1"
    )
    fx.close_outlet_ticket(api, ticket["id"], lounge["id"])
    batch = validate_success(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(bd["id"], lounge["id"], 100.00), manager
        ),
        expected_status=201,
    )
    assert_fields(batch, {"declared_by_user_id": lounge["id"]})
    fx.drive_to_settlement_review(api, bd["id"])
    flagged = fx.read_batch(api, batch["id"])
    assert_fields(flagged, {"status": "VARIANCE_FLAGGED"})
    assert_money(flagged["variance_amount"], -25.38, "variance_amount")

    # The declarer cannot even reach the identity check when the endpoint excludes it.
    validate_error(
        api.accept_variance(batch["id"], AUDITOR), E.ERR_UNAUTHORIZED, expected_status=403
    )
    # An admitted role carrying the declarer's identity is stopped by the identity check.
    validate_error(
        api.accept_variance(batch["id"], make_headers("Controller", lounge["id"])),
        E.ERR_SELF_APPROVAL_FORBIDDEN,
        expected_status=403,
    )
    still_flagged = fx.read_batch(api, batch["id"])
    assert_fields(still_flagged, {"status": "VARIANCE_FLAGGED"})
    assert_null_fields(still_flagged, ["accepted_by_user_id"])

    accepted = validate_success(api.accept_variance(batch["id"], CONTROLLER))
    assert_fields(
        accepted,
        {"status": "ACCEPTED_WITH_VARIANCE", "accepted_by_user_id": "u_ctl_1"},
    )
