"""Endpoint surface: what a listing filter partitions, what an action writes, what a read exposes.

The listings here are asked to separate rows that differ on one axis only, and each action
endpoint is checked for the whole set of side effects it is specified to have.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_ALT_HEADERS,
    APPROVER_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    build_user_headers,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    ComponentType,
    DriverType,
    EscrowTxnType,
    MileageGuide,
    MovementStatus,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
    UserRole,
)


class TestLoadListing:
    """The two axes are separate filters over the same rows."""

    def test_the_movement_and_pay_filters_partition_the_same_three_loads_differently(self):
        """One delivered load, one in transit and one merely tendered: filtering on DELIVERED
        returns the first alone, while filtering on UNPAID returns the other two, because delivery
        moved the money axis to ACCRUED.

        PRD 4: "List loads, filterable by driver, settlement, snapshotted pay package, movement
        status or pay status."
        PRD 2.9 rung 8: "`ERR_LOAD_NOT_FOUND` — the load addressed by the path, or named by
        `load_id` in the body, exists."

        Design: Corner/endpoints/load_listing_filters_partition_the_two_axes_and_an_unknown_id_is_404
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Load Listing",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Cara Crud",
            home_state="TX",
        )
        delivered = fixtures.tender_load(driver["id"], stop_count=1)
        rolling = fixtures.tender_load(
            driver["id"],
            practical_miles=620,
            hhg_miles=600,
            linehaul_revenue_cents=100000,
            stop_count=1,
        )
        parked = fixtures.tender_load(
            driver["id"],
            practical_miles=250,
            hhg_miles=240,
            linehaul_revenue_cents=40000,
            stop_count=1,
        )
        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(delivered["id"])
        fixtures.set_clock(fixtures.TS_DELIVER)
        fixtures.deliver(delivered["id"])
        fixtures.dispatch(rolling["id"])

        by_movement, movement_meta = validate_paginated(
            api_client.list_loads(
                AUDITOR_HEADERS,
                {"driver_id": driver["id"], "movement_status": MovementStatus.DELIVERED},
            )
        )
        assert movement_meta["total_count"] == 1
        assert [row["id"] for row in by_movement] == [delivered["id"]]

        by_pay, pay_meta = validate_paginated(
            api_client.list_loads(
                AUDITOR_HEADERS,
                {"driver_id": driver["id"], "pay_status": PayStatus.UNPAID},
            )
        )
        assert pay_meta["total_count"] == 2
        unpaid_ids = {row["id"] for row in by_pay}
        assert unpaid_ids == {rolling["id"], parked["id"]}
        assert delivered["id"] not in unpaid_ids, "the delivered load is ACCRUED, not UNPAID"

        single = validate_success(api_client.get_load(delivered["id"], AUDITOR_HEADERS))
        assert single["paid_miles"] == 780
        assert single["linehaul_pay_cents"] == 46080
        assert single["pay_status"] == PayStatus.ACCRUED

        unknown = api_client.get_load(NON_EXISTENT_UUID, AUDITOR_HEADERS)
        validate_error(unknown, ApiErrorId.LOAD_NOT_FOUND, 404)
        _all_rows, all_meta = validate_paginated(
            api_client.list_loads(AUDITOR_HEADERS, {"driver_id": driver["id"]})
        )
        assert all_meta["total_count"] == 3


class TestPackageRevision:
    """Revise has three side effects, and only one revision may be open at a time."""

    def test_a_revision_opens_a_draft_successor_and_a_second_revision_is_refused(self):
        """The successor is a DRAFT copy pointing back at its predecessor, the predecessor is
        flagged and version-bumped, and a second revise fails on the pending-revision guard rather
        than the stale-version guard because the expected version was just read.

        PRD 3.1: "Opening a revision sets the predecessor's `has_pending_revision` to true and bumps
        the predecessor's `version`; a package that already has a `DRAFT` successor open cannot be
        revised again, and the second attempt is rejected with `ERR_PAY_PACKAGE_REVISION_PENDING`
        (HTTP 409)."
        PRD 3.1: "a new `DRAFT` package whose `supersedes_pay_package_id` points at the predecessor
        and which starts life with a copy of the predecessor's components"
        PRD 3.1: "because its `supersedes_pay_package_id` is not null, the predecessor is driven
        `ACTIVE` → `RETIRED` in the same operation — its `retired_at` is stamped from the logical
        clock, its `has_pending_revision` is cleared back to false, and its `version` is incremented
        by 1."

        Design: Corner/endpoints/revise_creates_a_draft_successor_and_blocks_a_second_revision
        """
        fixtures.reset_clock()
        predecessor = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Revision Chain",
        )
        observed_version = predecessor["version"]

        successor = validate_success(
            api_client.revise_pay_package(
                predecessor["id"],
                factories.revise_payload(
                    observed_version,
                    name="Leased Revision Chain v2",
                    escrow_target_cents=300000,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert successor["status"] == PayPackageStatus.DRAFT
        assert successor["supersedes_pay_package_id"] == predecessor["id"]
        assert successor["escrow_target_cents"] == 300000
        assert successor["component_count"] == 2, "the components are copied forward"
        flagged = get_success_data(
            api_client.get_pay_package(predecessor["id"], ADMIN_HEADERS)
        )
        assert flagged["has_pending_revision"] is True
        assert flagged["status"] == PayPackageStatus.ACTIVE
        assert flagged["version"] == observed_version + 1

        second = api_client.revise_pay_package(
            predecessor["id"],
            factories.revise_payload(
                flagged["version"], name="Leased Revision Chain v3"
            ),
            ADMIN_HEADERS,
        )

        validate_error(second, ApiErrorId.PAY_PACKAGE_REVISION_PENDING, 409)
        assert second.json()["data"]["error_id"] != ApiErrorId.STALE_PAY_PACKAGE_VERSION, (
            "the expected version was read immediately before the attempt"
        )

        activated = validate_success(
            api_client.activate_pay_package(successor["id"], ADMIN_HEADERS)
        )
        assert activated["status"] == PayPackageStatus.ACTIVE
        components = get_success_data(
            api_client.list_components(successor["id"], ADMIN_HEADERS)
        )
        assert len(components) == 2
        assert components[0]["component_type"] == ComponentType.PER_MILE
        assert components[0]["rate_value"] == 58

        retired = get_success_data(
            api_client.get_pay_package(predecessor["id"], ADMIN_HEADERS)
        )
        assert retired["status"] == PayPackageStatus.RETIRED
        assert retired["has_pending_revision"] is False
        assert_timestamps_equal(retired["retired_at"], CLOCK_EPOCH, "retired_at")


def _prepared_by_admin(name: str, legal_name: str):
    """One delivered load swept into a PREPARED settlement, prepared by admin-01."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name=name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    prepared = get_success_data(
        api_client.prepare_settlement(settlement["id"], None, ADMIN_HEADERS)
    )
    return driver, prepared


class TestSegregationOfDutiesIsAnIdentityCheck:
    """Three signatures, three identities — and the refusals are not about roles."""

    def test_the_preparer_may_not_approve_and_the_approver_may_not_pay(self):
        """admin-01 is a role that may approve, yet it prepared this statement and is refused;
        approver-01 then approves and is refused on pay for the mirror reason, so admin-02 has to
        release the money.

        PRD 2.10: "The `X-User-ID` that prepares a settlement is recorded as `prepared_by_user_id`;
        the approver's `X-User-ID` must differ from it, and is recorded as `approved_by_user_id`; the
        payer's `X-User-ID` must differ from `approved_by_user_id`. A violation at either hop is
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD 2.10: "Because `PayrollAdmin` may act at every hop, these identity comparisons — not
        role membership — are what actually keep the chain honest."

        Design: Corner/endpoints/the_same_identity_may_not_approve_what_it_prepared_or_pay_what_it_approved
        """
        fixtures.reset_clock()
        _driver, prepared = _prepared_by_admin("Leased Duties", "Sam Signature")
        assert prepared["status"] == SettlementStatus.PREPARED
        assert prepared["prepared_by_user_id"] == ADMIN_HEADERS["X-User-ID"]

        self_approval = api_client.approve_settlement(prepared["id"], ADMIN_HEADERS)

        validate_error(self_approval, ApiErrorId.SEGREGATION_OF_DUTIES, 409)
        assert self_approval.json()["data"]["error_id"] != ApiErrorId.FORBIDDEN_ROLE, (
            "PayrollAdmin is authorized on the approve endpoint; it is the identity that collides"
        )

        approved = validate_success(
            api_client.approve_settlement(prepared["id"], APPROVER_HEADERS)
        )
        assert approved["approved_by_user_id"] == APPROVER_HEADERS["X-User-ID"]

        approver_as_admin = build_user_headers(
            APPROVER_HEADERS["X-User-ID"], UserRole.PAYROLL_ADMIN
        )
        self_payment = api_client.pay_settlement(
            prepared["id"], factories.pay_payload("ACH-SOD-BAD"), approver_as_admin
        )

        validate_error(self_payment, ApiErrorId.SEGREGATION_OF_DUTIES, 409)
        unpaid = fixtures.read_settlement(prepared["id"])
        assert unpaid["status"] == SettlementStatus.APPROVED
        assert unpaid["payment_reference"] != "ACH-SOD-BAD"

        paid = validate_success(
            api_client.pay_settlement(
                prepared["id"], factories.pay_payload("ACH-SOD-OK"), ADMIN_ALT_HEADERS
            )
        )

        assert paid["status"] == SettlementStatus.PAID
        assert paid["payment_reference"] == "ACH-SOD-OK"
        assert_timestamps_equal(paid["paid_at"], fixtures.TS_SETTLE, "paid_at")


def _escrow_statement_environment(name: str, legal_name: str, second_claim: bool = False):
    """A tarped, delivered load with one or two approved claims, on an escrow package."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=True,
        escrow_target_cents=250000,
        escrow_monthly_deduction_cents=40000,
        name=name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1, tarp_required=True)
    tarping = fixtures.approved_claim(
        load["id"],
        driver["id"],
        AccessorialType.TARPING,
        "2026-08-04T10:00:00Z",
        "2026-08-04T11:00:00Z",
        "doc://tarp-endpoint",
    )
    claims = [tarping]
    if second_claim:
        claims.append(
            fixtures.approved_claim(
                load["id"],
                driver["id"],
                AccessorialType.DETENTION,
                "2026-08-04T12:00:00Z",
                "2026-08-04T15:00:00Z",
                "doc://det-endpoint",
            )
        )
    return {"driver": driver, "load": load, "claims": claims}


class TestSettlementRead:
    """Every total on the statement header is derived, and they must agree with each other."""

    def test_the_read_exposes_a_mutually_consistent_set_of_derived_totals(self):
        """46080 of linehaul plus 7500 of tarping is 53580 gross, escrow accrues on the linehaul
        line alone at 3686, and net is what is left after that single deduction.

        PRD 3.7: "Accessorial and retroactive-correction lines never accrue escrow."
        PRD 3.7: "`deduction_total_cents` is `escrow_deduction_cents` plus `advance_recovery_cents`,
        and `net_pay_cents` is `gross_pay_cents` less `deduction_total_cents`."
        PRD 2.9 rung 11: "`ERR_SETTLEMENT_NOT_FOUND` — the settlement addressed by the path, or
        named by `settlement_id` or `origin_settlement_id` in the body, exists."

        Design: Corner/endpoints/settlement_read_exposes_every_derived_total_consistently
        """
        fixtures.reset_clock()
        env = _escrow_statement_environment("Leased Computed Read", "Cleo Compute")
        settlement = fixtures.prepared_settlement(env["driver"]["id"])

        read = validate_success(
            api_client.get_settlement(settlement["id"], AUDITOR_HEADERS)
        )

        assert read["status"] == SettlementStatus.PREPARED
        assert read["linehaul_total_cents"] == 46080
        assert read["accessorial_total_cents"] == 7500
        assert read["retro_correction_total_cents"] == 0
        assert read["gross_pay_cents"] == 53580
        assert read["escrow_deduction_cents"] == 3686
        assert read["escrow_deduction_cents"] != 4286, "the accessorial line accrues nothing"
        assert read["advance_recovery_cents"] == 0
        assert read["deduction_total_cents"] == 3686
        assert read["net_pay_cents"] == 49894
        assert read["taxable_wages_cents"] == 53580
        assert read["line_count"] == 3
        assert read["itemization_required"] is True, "a leased operator sees every charge"

        unknown = api_client.get_settlement(NON_EXISTENT_UUID, AUDITOR_HEADERS)
        validate_error(unknown, ApiErrorId.SETTLEMENT_NOT_FOUND, 404)


class TestChildCollectionsAreReachableFromEitherParent:
    """A claim hangs off both a load and a statement; a ledger row off both a driver and one."""

    def test_claims_and_ledger_rows_are_found_by_load_by_settlement_and_by_driver(self):
        """The same two claims come back whether the filter names their load or the statement that
        swept them, and the deposit written at approval is reachable by settlement.

        PRD 4: "List accessorial claims, filterable by driver, load, settlement, status or type."
        PRD 4: "List escrow ledger entries, filterable by driver, by the settlement that generated
        them, by the transaction they reverse, or by type."
        PRD 3.7: "every swept accessorial claim moves `APPROVED` → `PAID` with its `settlement_id`
        set and its `version` incremented by 1."

        Design: Corner/endpoints/child_collections_are_reachable_from_both_parents_by_filter
        """
        fixtures.reset_clock()
        env = _escrow_statement_environment(
            "Leased Cross Reference", "Xena Reference", second_claim=True
        )
        tarping, detention = env["claims"]
        settlement = fixtures.approved_settlement(env["driver"]["id"])

        by_load, load_meta = validate_paginated(
            api_client.list_accessorial_claims(
                AUDITOR_HEADERS, {"load_id": env["load"]["id"]}
            )
        )
        assert load_meta["total_count"] == 2
        assert {row["id"] for row in by_load} == {tarping["id"], detention["id"]}

        by_settlement, settlement_meta = validate_paginated(
            api_client.list_accessorial_claims(
                AUDITOR_HEADERS, {"settlement_id": settlement["id"]}
            )
        )
        assert settlement_meta["total_count"] == 2
        assert {row["id"] for row in by_settlement} == {tarping["id"], detention["id"]}
        for row in by_settlement:
            assert row["status"] == ClaimStatus.PAID
            assert row["settlement_id"] == settlement["id"]
        amounts = {row["id"]: row["amount_cents"] for row in by_settlement}
        assert amounts[tarping["id"]] == 7500
        assert amounts[detention["id"]] == 2000
        assert settlement["gross_pay_cents"] == 55580
        assert settlement["accessorial_total_cents"] == 9500

        ledger, ledger_meta = validate_paginated(
            api_client.list_escrow_transactions(
                AUDITOR_HEADERS, {"settlement_id": settlement["id"]}
            )
        )
        assert ledger_meta["total_count"] == 1
        assert ledger[0]["txn_type"] == EscrowTxnType.DEPOSIT
        assert ledger[0]["amount_cents"] == 3686
        assert ledger[0]["driver_id"] == env["driver"]["id"]

        validate_error(
            api_client.get_accessorial_claim(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ApiErrorId.ACCESSORIAL_CLAIM_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_escrow_transaction(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ApiErrorId.ESCROW_TRANSACTION_NOT_FOUND,
            404,
        )


class TestASweptClaimIsFrozen:
    """Being on a statement outranks being in the wrong status."""

    def test_reject_approve_and_document_are_all_refused_as_already_settled(self):
        """All three write endpoints on a PAID claim answer with the settled error rather than the
        status error, and the claim's priced amount and null rejection survive every attempt.

        PRD 2.9 rung 23: "`ERR_CLAIM_ALREADY_SETTLED` — the accessorial claim is not already
        attached to a settlement, that is its `status` is not `PAID` and its `settlement_id` is null.
        This referential check deliberately outranks the claim-status check at rung 49: a claim swept
        onto a settlement is frozen, and the caller must be told that it is settled rather than that
        its status is wrong."

        Design: Corner/endpoints/a_swept_claim_is_frozen_against_approve_reject_and_documents
        """
        fixtures.reset_clock()
        env = _escrow_statement_environment("Leased Already Settled", "Ada Settled")
        claim = env["claims"][0]
        settlement = fixtures.prepared_settlement(env["driver"]["id"])
        swept = fixtures.read_claim(claim["id"])
        assert swept["status"] == ClaimStatus.PAID
        assert swept["settlement_id"] == settlement["id"]

        rejection = api_client.reject_accessorial_claim(
            claim["id"], factories.claim_reject_payload(), CLERK_HEADERS
        )
        approval = api_client.approve_accessorial_claim(claim["id"], CLERK_HEADERS)
        document = api_client.attach_claim_document(
            claim["id"], factories.claim_document_payload("doc://late-add"), CLERK_HEADERS
        )

        for response in (rejection, approval, document):
            validate_error(response, ApiErrorId.CLAIM_ALREADY_SETTLED, 409)
            assert response.json()["data"]["error_id"] != ApiErrorId.CLAIM_NOT_SUBMITTED, (
                "the caller is told the claim is on a statement, not that its status is wrong"
            )

        frozen = fixtures.read_claim(claim["id"])
        assert frozen["status"] == ClaimStatus.PAID
        assert frozen["amount_cents"] == 7500
        assert frozen["reject_reason_code"] is None
        assert frozen["document_ref"] == "doc://tarp-endpoint"
        assert frozen["document_ref"] != "doc://late-add"
