"""Who may act, on whose rows, and in which order those two questions are asked.

Authentication precedes authorization, authorization precedes scope, and all three precede
existence — so an unauthorised caller never learns whether the record it named is real.
"""

from test_helpers import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    build_user_headers,
    factories,
    fixtures,
    get_success_data,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    DriverType,
    EscrowTxnType,
    LineType,
    MileageGuide,
    PerDiemMethod,
    SettlementStatus,
    UserRole,
    VoidReasonCode,
)

UNKNOWN_DRIVER_ID = "00000000-0000-4000-8000-000000000021"
UNKNOWN_SETTLEMENT_ID = "00000000-0000-4000-8000-000000000022"
DISPATCHER_HEADERS = build_user_headers("dispatch-01", "Dispatcher")


def _leased_driver(name: str, legal_name: str, **package_overrides):
    """An ACTIVE leased operator on a PRACTICAL package carrying both linehaul legs."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        name=name,
        **package_overrides,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    return package, driver


class TestUndeclaredRoleIsUnauthenticated:
    """A plausible trucking role that this domain does not grant is not merely forbidden."""

    def test_a_dispatcher_header_is_401_on_a_read_and_on_a_write(self):
        """`Dispatcher` is not one of the five declared names, so the request never reaches the
        endpoint's own role list — and reads are authenticated just as writes are.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the five role names
        declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.9 rung 1: "`ERR_UNAUTHENTICATED` — `X-User-ID` and `X-User-Role` are both present and
        the role is one of the five declared names."

        Design: Corner/rbac/an_undeclared_role_header_is_unauthenticated_before_anything_else
        """
        fixtures.reset_clock()

        listing = api_client.list_drivers(DISPATCHER_HEADERS)
        create = api_client.create_pay_package(
            factories.pay_package_payload(
                name="No Auth",
                driver_type=DriverType.LEASED_OPERATOR,
                mileage_guide=MileageGuide.PRACTICAL,
                per_diem_method=PerDiemMethod.NONE,
                escrow_required=False,
            ),
            DISPATCHER_HEADERS,
        )

        validate_error(listing, ApiErrorId.UNAUTHENTICATED, 401)
        validate_error(create, ApiErrorId.UNAUTHENTICATED, 401)
        for response in (listing, create):
            assert response.json()["data"]["error_id"] != ApiErrorId.FORBIDDEN_ROLE, (
                "an undeclared role is rejected before any endpoint role list is consulted"
            )
        _, packages = validate_paginated(api_client.list_pay_packages(ADMIN_HEADERS))
        assert packages["total_count"] == 0


class TestRoleAuthorizationPrecedesExistence:
    """Five probes at five endpoints, three of them naming ids that do not exist."""

    def test_every_role_is_refused_on_another_roles_exclusive_operation_with_403_not_404(self):
        """The database is deliberately empty, so a handler that looked the record up first would
        answer 404 and leak the fact that it is missing.

        PRD 2.9 rung 2: "`ERR_FORBIDDEN_ROLE` — the acting role is authorized for the addressed
        endpoint."
        PRD 4: "The `Authorized Role(s)` column is exhaustive: an authenticated caller whose
        `X-User-Role` is absent from a row receives `ERR_FORBIDDEN_ROLE`"

        Design: Corner/rbac/each_role_is_refused_on_another_roles_exclusive_operation_before_existence
        """
        fixtures.reset_clock()

        auditor_configures = api_client.create_pay_package(
            factories.pay_package_payload(
                name="Auditor Overreach",
                driver_type=DriverType.LEASED_OPERATOR,
                mileage_guide=MileageGuide.PRACTICAL,
                per_diem_method=PerDiemMethod.NONE,
                escrow_required=False,
            ),
            AUDITOR_HEADERS,
        )
        driver_books = api_client.create_load(
            factories.load_payload(UNKNOWN_DRIVER_ID),
            make_driver_headers(UNKNOWN_DRIVER_ID),
        )
        approver_opens = api_client.create_settlement(
            factories.settlement_payload(
                UNKNOWN_DRIVER_ID, fixtures.PERIOD_START, fixtures.PERIOD_END
            ),
            APPROVER_HEADERS,
        )
        clerk_pays = api_client.pay_settlement(
            UNKNOWN_SETTLEMENT_ID, factories.pay_payload("ACH-NOPE"), CLERK_HEADERS
        )
        auditor_disburses = api_client.return_escrow(
            UNKNOWN_DRIVER_ID,
            AUDITOR_HEADERS,
            factories.escrow_return_payload("ACH-NOPE-2"),
        )

        probes = (
            auditor_configures,
            driver_books,
            approver_opens,
            clerk_pays,
            auditor_disburses,
        )
        for response in probes:
            validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)
            error_id = response.json()["data"]["error_id"]
            assert error_id != ApiErrorId.DRIVER_NOT_FOUND
            assert error_id != ApiErrorId.SETTLEMENT_NOT_FOUND
            assert error_id != ApiErrorId.SEGREGATION_OF_DUTIES
            assert error_id != ApiErrorId.SETTLEMENT_STATE_INVALID

        for listing in (
            api_client.list_pay_packages(ADMIN_HEADERS),
            api_client.list_loads(ADMIN_HEADERS),
            api_client.list_settlements(ADMIN_HEADERS),
        ):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == 0, "a refused write stores nothing"


class TestDriverScopeIsEntityBacked:
    """`X-User-ID` is itself a driver id, so the ownership check has something to compare."""

    def test_a_driver_reads_itself_and_is_refused_on_every_surface_of_a_peer(self):
        """Two drivers and two loads all exist, so none of the four refusals can be a disguised
        not-found — and on the two writes the offending id is in the payload, not in the path.

        PRD 2.1: "A `Driver` that addresses another driver's row — for reading or for writing — is
        rejected with `ERR_DRIVER_SCOPE_VIOLATION` (HTTP 403). This scope check is evaluated after
        role authorization and before any existence, state or money check, so a driver probing
        another driver's settlement learns only that it is out of scope."
        PRD 2.9 rung 3: "`ERR_DRIVER_SCOPE_VIOLATION` — when the acting role is `Driver`,
        `X-User-ID` equals the driver reference of the addressed resource."

        Design: Corner/rbac/a_driver_identity_is_confined_to_its_own_rows_on_reads_and_writes
        """
        fixtures.reset_clock()
        _, own = _leased_driver("Leased Scope A", "Ada Ownrow")
        own_load = fixtures.delivered_load(own["id"], stop_count=1)
        _, peer = _leased_driver("Leased Scope B", "Bob Otherrow")
        peer_load = fixtures.delivered_load(
            peer["id"],
            dispatched_at="2026-08-05T08:00:00Z",
            delivered_at="2026-08-06T18:00:00Z",
            stop_count=1,
        )
        fixtures.set_clock("2026-08-07T09:00:00Z")
        acting = make_driver_headers(own["id"])

        mine = validate_success(api_client.get_driver(own["id"], acting))
        assert mine["id"] == own["id"]

        peer_read = api_client.get_driver(peer["id"], acting)
        peer_load_read = api_client.get_load(peer_load["id"], acting)
        peer_claim = api_client.create_accessorial_claim(
            factories.accessorial_claim_payload(
                peer_load["id"],
                peer["id"],
                AccessorialType.TARPING,
                "2026-08-06T10:00:00Z",
                "2026-08-06T11:00:00Z",
                document_ref="doc://sc-tarp",
            ),
            acting,
        )
        peer_dispute = api_client.create_dispute(
            factories.mileage_dispute_payload(
                peer["id"],
                peer_load["id"],
                MileageGuide.HHG,
                742,
                narrative="Not my load.",
                evidence_doc_ref="doc://sc-dsp",
            ),
            acting,
        )

        for response in (peer_read, peer_load_read, peer_claim, peer_dispute):
            validate_error(response, ApiErrorId.DRIVER_SCOPE_VIOLATION, 403)
            error_id = response.json()["data"]["error_id"]
            assert error_id != ApiErrorId.DRIVER_NOT_FOUND
            assert error_id != ApiErrorId.LOAD_NOT_FOUND

        _, claims_meta = validate_paginated(
            api_client.list_accessorial_claims(ADMIN_HEADERS)
        )
        _, disputes_meta = validate_paginated(api_client.list_disputes(ADMIN_HEADERS))
        assert claims_meta["total_count"] == 0
        assert disputes_meta["total_count"] == 0

        mine_only, meta = validate_paginated(
            api_client.list_loads(acting, {"driver_id": own["id"]})
        )
        assert meta["total_count"] == 1
        assert mine_only[0]["id"] == own_load["id"]
        untouched = fixtures.read_load(peer_load["id"])
        assert untouched["driver_id"] == peer["id"]
        assert untouched["version"] == peer_load["version"]


class TestPayrollAdminIsTheBreakGlassRole:
    """One role may do everything, but not one identity."""

    def test_the_whole_chain_runs_under_one_role_across_three_distinct_identities(self):
        """Booking, delivering, pricing the claim, preparing, approving and paying all succeed under
        `PayrollAdmin`, which is the positive control that keeps the refusals elsewhere from being a
        blanket denial — and three identities are still required.

        PRD 2.1: "it is the break-glass role: it may perform any clerk or approver operation, while
        remaining subject to the same segregation-of-duties rules that forbid approving what it
        prepared and paying what it approved."
        PRD 2.10: "The `X-User-ID` that prepares a settlement is recorded as `prepared_by_user_id`;
        the approver's `X-User-ID` must differ from it, and is recorded as `approved_by_user_id`; the
        payer's `X-User-ID` must differ from `approved_by_user_id`."
        PRD 3.8: "The driver's `ytd_gross_pay_cents`, `ytd_taxable_wages_cents` and
        `ytd_per_diem_non_taxable_cents` are recomputed, because this settlement now counts toward
        them."

        Design: Corner/rbac/payroll_admin_alone_can_walk_the_whole_chain_with_three_identities
        """
        fixtures.reset_clock()
        _, driver = _leased_driver("Leased Break Glass", "Bree Breakglass")
        load = fixtures.delivered_load(driver["id"], stop_count=1, tarp_required=True)
        assert load["linehaul_pay_cents"] == 46080

        claim = validate_success(
            api_client.create_accessorial_claim(
                factories.accessorial_claim_payload(
                    load["id"],
                    driver["id"],
                    AccessorialType.TARPING,
                    "2026-08-04T10:00:00Z",
                    "2026-08-04T11:00:00Z",
                    document_ref="doc://bg-tarp",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        priced = validate_success(
            api_client.approve_accessorial_claim(claim["id"], ADMIN_HEADERS)
        )
        assert priced["status"] == ClaimStatus.APPROVED
        assert priced["amount_cents"] == 7500

        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = validate_success(
            api_client.create_settlement(
                factories.settlement_payload(
                    driver["id"], fixtures.PERIOD_START, fixtures.PERIOD_END
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        prepared = validate_success(
            api_client.prepare_settlement(settlement["id"], None, ADMIN_HEADERS)
        )
        approved = validate_success(
            api_client.approve_settlement(settlement["id"], ADMIN_ALT_HEADERS)
        )
        third_identity = build_user_headers("admin-03", UserRole.PAYROLL_ADMIN)
        paid = validate_success(
            api_client.pay_settlement(
                settlement["id"], factories.pay_payload("ACH-BG-1"), third_identity
            )
        )

        assert prepared["prepared_by_user_id"] == ADMIN_HEADERS["X-User-ID"]
        assert approved["approved_by_user_id"] == ADMIN_ALT_HEADERS["X-User-ID"]
        assert approved["approved_by_user_id"] != prepared["prepared_by_user_id"]
        assert paid["status"] == SettlementStatus.PAID
        assert paid["payment_reference"] == "ACH-BG-1"
        assert_timestamps_equal(paid["paid_at"], fixtures.TS_SETTLE, "paid_at")
        assert paid["linehaul_total_cents"] == 46080
        assert paid["accessorial_total_cents"] == 7500
        assert paid["gross_pay_cents"] == 53580
        assert paid["escrow_deduction_cents"] == 0
        assert paid["net_pay_cents"] == 53580

        settled_driver = fixtures.read_driver(driver["id"])
        assert settled_driver["ytd_gross_pay_cents"] == 53580
        assert settled_driver["ytd_taxable_wages_cents"] == 53580


class TestComplianceAuditorReadsEverythingAndWritesNothing:
    """An opaque read-only identity, with no scope restriction and no write anywhere."""

    def test_the_auditor_reads_another_partys_statement_ledger_and_claims_but_writes_none_of_them(
        self,
    ):
        """Every read is a 200 across a driver the auditor has nothing to do with, and the three
        writes are refused against rows that genuinely exist.

        PRD 2.1: "A `ComplianceAuditor` is a read-only auditor of pay compliance. It reads pay
        packages, settlement statements, escrow ledgers and dispute histories across all drivers and
        writes nothing anywhere in the domain."
        PRD 2.9 rung 2: "`ERR_FORBIDDEN_ROLE` — the acting role is authorized for the addressed
        endpoint."

        Design: Corner/rbac/the_compliance_auditor_reads_every_collection_and_writes_none
        """
        fixtures.reset_clock()
        _, driver = _leased_driver(
            "Leased Auditor View",
            "Cy Auditee",
            escrow_required=True,
            escrow_target_cents=250000,
            escrow_monthly_deduction_cents=40000,
        )
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock("2026-08-05T09:00:00Z")
        claim = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.DETENTION,
            "2026-08-04T12:00:00Z",
            "2026-08-04T15:00:00Z",
            "doc://aud-det",
            CLERK_HEADERS,
        )
        settlement = fixtures.approved_settlement(driver["id"])
        observed = fixtures.read_driver(driver["id"])
        assert observed["escrow_balance_cents"] == 3686

        statement = validate_success(
            api_client.get_settlement(settlement["id"], AUDITOR_HEADERS)
        )
        lines = get_success_data(
            api_client.list_settlement_lines(settlement["id"], AUDITOR_HEADERS)
        )
        ledger, ledger_meta = validate_paginated(
            api_client.list_escrow_transactions(
                AUDITOR_HEADERS, {"driver_id": driver["id"]}
            )
        )
        claims, claims_meta = validate_paginated(
            api_client.list_accessorial_claims(
                AUDITOR_HEADERS, {"driver_id": driver["id"]}
            )
        )

        assert statement["status"] == SettlementStatus.APPROVED
        assert statement["gross_pay_cents"] == 46080
        assert len(lines) == 2
        by_type = {line["line_type"]: line for line in lines}
        assert by_type[LineType.LINEHAUL_PER_MILE]["amount_cents"] == 46080
        assert abs(by_type[LineType.ESCROW_DEDUCTION]["amount_cents"]) == 3686
        assert ledger_meta["total_count"] == 1
        assert ledger[0]["txn_type"] == EscrowTxnType.DEPOSIT
        assert ledger[0]["amount_cents"] == 3686
        assert claims_meta["total_count"] == 1
        assert claims[0]["status"] == ClaimStatus.SUBMITTED

        void = api_client.void_settlement(
            settlement["id"],
            factories.void_payload(VoidReasonCode.CLERICAL_ERROR),
            AUDITOR_HEADERS,
        )
        approve = api_client.approve_accessorial_claim(claim["id"], AUDITOR_HEADERS)
        deduct = api_client.create_escrow_deduction(
            driver["id"],
            factories.escrow_deduction_payload(
                500, observed["version"], document_ref="doc://aud-ded"
            ),
            AUDITOR_HEADERS,
        )

        for response in (void, approve, deduct):
            validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

        after = fixtures.read_settlement(settlement["id"])
        assert after["status"] == SettlementStatus.APPROVED
        assert after["voided_at"] is None
        still_submitted = fixtures.read_claim(claim["id"])
        assert still_submitted["status"] == ClaimStatus.SUBMITTED
        assert still_submitted["amount_cents"] == 0
        unchanged = fixtures.read_driver(driver["id"])
        assert unchanged["escrow_balance_cents"] == 3686
        assert unchanged["version"] == observed["version"]
