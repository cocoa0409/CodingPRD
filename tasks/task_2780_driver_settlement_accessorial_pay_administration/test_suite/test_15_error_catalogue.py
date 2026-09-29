"""One error id per aggregate, per interval and per whitelist.

The catalogue is deliberately fine-grained, so each of these tests pins down which id a
request earns and, where a neighbouring id is plausible, which id it does not earn.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    ComponentType,
    CorrectionStatus,
    CorrectionType,
    DisputeStatus,
    DriverType,
    EscrowReasonCode,
    EscrowStatus,
    EscrowTxnType,
    LineType,
    MileageGuide,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
)

MISSING_ADVANCE_ID = "00000000-0000-4000-8000-000000000011"
MISSING_DISPUTE_ID = "00000000-0000-4000-8000-000000000012"
MISSING_CORRECTION_ID = "00000000-0000-4000-8000-000000000013"


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


class TestNotFoundIsPerAggregate:
    """Three well-formed but unknown ids, three different answers."""

    def test_advance_dispute_and_correction_reads_each_name_their_own_aggregate(self):
        """Nothing exists at all, so the only thing that can distinguish these three reads is
        which collection was addressed.

        PRD 2.9 rung 10: "`ERR_ADVANCE_NOT_FOUND` — the advance addressed by the path exists."
        PRD 2.9 rung 12: "`ERR_DISPUTE_NOT_FOUND` — the dispute addressed by the path exists."
        PRD 2.9 rung 13: "`ERR_RETRO_CORRECTION_NOT_FOUND` — the retroactive correction addressed
        by the path exists."

        Design: Corner/errors/unknown_ids_on_advance_dispute_and_correction_reads_yield_distinct_404s
        """
        fixtures.reset_clock()

        advance = api_client.get_advance(MISSING_ADVANCE_ID, AUDITOR_HEADERS)
        dispute = api_client.get_dispute(MISSING_DISPUTE_ID, AUDITOR_HEADERS)
        correction = api_client.get_retro_correction(MISSING_CORRECTION_ID, AUDITOR_HEADERS)

        validate_error(advance, ApiErrorId.ADVANCE_NOT_FOUND, 404)
        validate_error(dispute, ApiErrorId.DISPUTE_NOT_FOUND, 404)
        validate_error(correction, ApiErrorId.RETRO_CORRECTION_NOT_FOUND, 404)

        ids = [
            response.json()["data"]["error_id"]
            for response in (advance, dispute, correction)
        ]
        assert len(set(ids)) == 3, "no two aggregates may share a not-found id"
        for response in (advance, dispute, correction):
            body = response.json()["data"]
            assert body["error_id"].startswith("ERR_")
            assert isinstance(body["message"], str) and body["message"], (
                "the standard error envelope carries a message alongside the id"
            )


class TestDegenerateIntervals:
    """One id guards two endpoints, and both comparisons are strict."""

    def test_a_zero_length_claim_and_a_zero_length_pay_period_are_both_rejected(self):
        """An empty half-open period would simply sweep nothing rather than break anything, and
        it is refused all the same; widening either interval then succeeds.

        PRD 3.5: "`end_at` must be strictly after `start_at`, and an interval that fails this is
        rejected with `ERR_INTERVAL_INVALID` (HTTP 422)."
        PRD 3.7: "`period_start` is the inclusive lower bound and `period_end` the exclusive upper
        bound, and `period_end` must be strictly after `period_start` or the request is rejected
        with `ERR_INTERVAL_INVALID`."

        Design: Corner/errors/a_degenerate_interval_is_rejected_on_both_claims_and_settlement_periods
        """
        fixtures.reset_clock()
        _, driver = _leased_driver("Leased Interval Guard", "Ivy Interval")
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock(fixtures.TS_SETTLE)

        degenerate_claim = api_client.create_accessorial_claim(
            factories.accessorial_claim_payload(
                load["id"],
                driver["id"],
                AccessorialType.TARPING,
                "2026-08-04T12:00:00Z",
                "2026-08-04T12:00:00Z",
                document_ref="doc://tarp-ivl",
            ),
            CLERK_HEADERS,
        )
        degenerate_period = api_client.create_settlement(
            factories.settlement_payload(
                driver["id"], "2026-08-10T00:00:00Z", "2026-08-10T00:00:00Z"
            ),
            CLERK_HEADERS,
        )

        validate_error(degenerate_claim, ApiErrorId.INTERVAL_INVALID, 422)
        validate_error(degenerate_period, ApiErrorId.INTERVAL_INVALID, 422)
        _, empty_claims = validate_paginated(
            api_client.list_accessorial_claims(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        _, empty_settlements = validate_paginated(
            api_client.list_settlements(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert empty_claims["total_count"] == 0
        assert empty_settlements["total_count"] == 0

        claim = validate_success(
            api_client.create_accessorial_claim(
                factories.accessorial_claim_payload(
                    load["id"],
                    driver["id"],
                    AccessorialType.TARPING,
                    "2026-08-04T12:00:00Z",
                    "2026-08-04T13:00:00Z",
                    document_ref="doc://tarp-ivl",
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        settlement = validate_success(
            api_client.create_settlement(
                factories.settlement_payload(
                    driver["id"], fixtures.PERIOD_START, fixtures.PERIOD_END
                ),
                CLERK_HEADERS,
            ),
            201,
        )

        assert claim["status"] == ClaimStatus.SUBMITTED
        assert settlement["status"] == SettlementStatus.DRAFT
        _, claims_meta = validate_paginated(
            api_client.list_accessorial_claims(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        _, settlements_meta = validate_paginated(
            api_client.list_settlements(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert claims_meta["total_count"] == 1
        assert settlements_meta["total_count"] == 1


class TestComponentLegalityMatrix:
    """Which component types a package may hold is a function of who it pays."""

    def test_hourly_is_refused_on_leased_revenue_percent_on_company_and_the_bodies_are_otherwise_legal(
        self,
    ):
        """The very same HOURLY body that the leased package refuses is accepted by the company
        package, so neither rejection can be a complaint about the field values.

        PRD 3.1: "an `HOURLY` component may not be added to a package whose `driver_type` is
        `OWNER_OPERATOR` or `LEASED_OPERATOR`."
        PRD 3.1: "a `REVENUE_PERCENT` component may not be added to a package whose `driver_type`
        is `COMPANY_SOLO` or `COMPANY_TEAM`. Either attempt is rejected with
        `ERR_COMPONENT_TYPE_NOT_ALLOWED` (HTTP 422)."

        Design: Corner/errors/component_type_legality_is_a_function_of_the_package_driver_type
        """
        fixtures.reset_clock()
        leased = fixtures.create_package(
            activate=False,
            name="Leased Legality",
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
        )
        company = fixtures.create_package(
            activate=False,
            name="Company Legality",
            driver_type=DriverType.COMPANY_SOLO,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
        )
        assert leased["status"] == PayPackageStatus.DRAFT
        assert company["status"] == PayPackageStatus.DRAFT
        hourly_body = factories.hourly_component(rate_value=2200, sequence=1)

        hourly_on_leased = api_client.add_component(
            leased["id"], hourly_body, ADMIN_HEADERS
        )
        revenue_on_company = api_client.add_component(
            company["id"],
            factories.revenue_percent_component(rate_value=2500, sequence=1),
            ADMIN_HEADERS,
        )

        validate_error(hourly_on_leased, ApiErrorId.COMPONENT_TYPE_NOT_ALLOWED, 422)
        validate_error(revenue_on_company, ApiErrorId.COMPONENT_TYPE_NOT_ALLOWED, 422)
        for response in (hourly_on_leased, revenue_on_company):
            assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_FIELD_VALUE, (
                "the component type and its unit are declared members, correctly paired"
            )

        validate_success(
            api_client.add_component(company["id"], hourly_body, ADMIN_HEADERS), 201
        )
        validate_success(
            api_client.add_component(
                leased["id"],
                factories.per_mile_component(rate_value=58, sequence=1),
                ADMIN_HEADERS,
            ),
            201,
        )

        for package_id in (leased["id"], company["id"]):
            reread = get_success_data(
                api_client.get_pay_package(package_id, ADMIN_HEADERS)
            )
            assert reread["component_count"] == 1
        leased_components = get_success_data(
            api_client.list_components(leased["id"], ADMIN_HEADERS)
        )
        assert [row["component_type"] for row in leased_components] == [
            ComponentType.PER_MILE
        ]


class TestDisputeFilingGuards:
    """Three independent filters sit on one create endpoint."""

    def test_unchanged_duplicate_and_late_mileage_claims_each_earn_their_own_id(self):
        """Claiming exactly what the load already paid, claiming twice while the first is open,
        and claiming 35 days after delivery are three different refusals, and only the genuinely
        different claim survives.

        PRD 3.9: "if the pair of `claimed_guide` and `claimed_miles` equals the load's current
        `applied_mileage_guide` and `base_guide_miles`, there is no dispute to adjudicate and the
        filing is rejected with `ERR_MILEAGE_CLAIM_UNCHANGED` (HTTP 422)."
        PRD 3.9: "A dispute must be filed within 30 days of its reference instant, which is the
        load's `delivered_at` for a mileage dispute on a load that has not been settled"
        PRD 3.9: "no second dispute of the same `dispute_kind` may be filed against the same load
        or the same origin settlement while an existing one is still `OPEN` or `UNDER_REVIEW`; the
        duplicate is rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/errors/dispute_filing_rejects_unchanged_duplicate_and_late_mileage_claims
        """
        fixtures.reset_clock()
        _, driver = _leased_driver("Leased Dispute Window", "Dora Window")
        first = fixtures.delivered_load(driver["id"], stop_count=1)
        second = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-05T08:00:00Z",
            delivered_at="2026-08-06T18:00:00Z",
            practical_miles=900,
            hhg_miles=860,
            stop_count=1,
        )
        assert first["applied_mileage_guide"] == MileageGuide.PRACTICAL
        assert first["base_guide_miles"] == 780
        fixtures.set_clock(fixtures.TS_SETTLE)

        unchanged = api_client.create_dispute(
            factories.mileage_dispute_payload(
                driver["id"],
                first["id"],
                MileageGuide.PRACTICAL,
                780,
                narrative="Same as paid.",
                evidence_doc_ref="doc://dw-same",
            ),
            CLERK_HEADERS,
        )
        validate_error(unchanged, ApiErrorId.MILEAGE_CLAIM_UNCHANGED, 422)

        filed = validate_success(
            api_client.create_dispute(
                factories.mileage_dispute_payload(
                    driver["id"],
                    first["id"],
                    MileageGuide.HHG,
                    742,
                    narrative="Short-line should apply.",
                    evidence_doc_ref="doc://dw-hhg",
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        assert filed["status"] == DisputeStatus.OPEN
        assert filed["reopen_count"] == 0
        assert filed["claimed_guide"] == MileageGuide.HHG
        assert filed["claimed_miles"] == 742

        duplicate = api_client.create_dispute(
            factories.mileage_dispute_payload(
                driver["id"],
                first["id"],
                MileageGuide.HHG,
                700,
                narrative="Second bite.",
                evidence_doc_ref="doc://dw-dup",
            ),
            CLERK_HEADERS,
        )
        validate_error(duplicate, ApiErrorId.DISPUTE_ALREADY_OPEN, 409)

        fixtures.set_clock("2026-09-10T09:00:00Z")
        late = api_client.create_dispute(
            factories.mileage_dispute_payload(
                driver["id"],
                second["id"],
                MileageGuide.HHG,
                860,
                narrative="Filed too late.",
                evidence_doc_ref="doc://dw-late",
            ),
            CLERK_HEADERS,
        )
        validate_error(late, ApiErrorId.DISPUTE_WINDOW_CLOSED, 422)
        assert late.json()["data"]["error_id"] != ApiErrorId.DISPUTE_ALREADY_OPEN, (
            "no dispute has ever been filed against the second load"
        )

        disputes, meta = validate_paginated(
            api_client.list_disputes(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 1
        assert disputes[0]["id"] == filed["id"]
        assert disputes[0]["load_id"] == first["id"]


class TestItemizationGateIsKeyedOnDriverType:
    """An undocumented layover is legal everywhere except on a leased operator's statement."""

    def test_the_leased_prepare_is_refused_while_the_company_control_prepares_cleanly(self):
        """LAYOVER never needs a document, so the claim is submitted and approved at 12500 with
        `document_ref` null on both drivers, and only the leased statement is refused.

        PRD 3.5: "`documentation_required` is computed at submission as true when
        `accessorial_type` is `DETENTION`, `TARPING` or `BREAKDOWN`, and false for `LAYOVER` and
        `STOP_OFF`."
        PRD 3.7: "every `ACCESSORIAL` line's source claim must carry a non-null `document_ref`, so
        that every accessorial charge on a leased-operator statement is evidenced. Any gap is
        rejected with `ERR_ITEMIZATION_INCOMPLETE` (HTTP 422)."
        PRD 3.7: "`itemization_required` is computed once: it is true when the settled driver's
        `driver_type` is `LEASED_OPERATOR` and false otherwise."

        Design: Corner/errors/leased_statements_require_a_document_on_every_accessorial_line
        """
        fixtures.reset_clock()
        _, leased_driver = _leased_driver("Leased Itemization", "Ike Itemized")
        leased_load = fixtures.delivered_load(leased_driver["id"], stop_count=1)

        company_package = fixtures.active_package(
            driver_type=DriverType.COMPANY_SOLO,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            revenue_bps=None,
            name="Company Itemization Control",
        )
        company_driver = fixtures.active_driver(
            company_package["id"],
            driver_type=DriverType.COMPANY_SOLO,
            per_diem_elected=False,
            legal_name="Cass Company",
            home_state="TX",
        )
        company_load = fixtures.delivered_load(company_driver["id"], stop_count=1)
        assert leased_load["linehaul_pay_cents"] == 46080
        assert company_load["linehaul_pay_cents"] == 46080

        fixtures.set_clock("2026-08-07T09:00:00Z")
        leased_claim = fixtures.approved_claim(
            leased_load["id"],
            leased_driver["id"],
            AccessorialType.LAYOVER,
            "2026-08-05T20:00:00Z",
            "2026-08-06T08:00:00Z",
        )
        company_claim = fixtures.approved_claim(
            company_load["id"],
            company_driver["id"],
            AccessorialType.LAYOVER,
            "2026-08-05T20:00:00Z",
            "2026-08-06T08:00:00Z",
        )
        for claim in (leased_claim, company_claim):
            assert claim["status"] == ClaimStatus.APPROVED
            assert claim["billable_units"] == 1
            assert claim["amount_cents"] == 12500
            assert claim["document_ref"] is None
            assert claim["documentation_required"] is False

        fixtures.set_clock(fixtures.TS_SETTLE)
        leased_settlement = fixtures.open_settlement(leased_driver["id"])
        company_settlement = fixtures.open_settlement(company_driver["id"])
        assert leased_settlement["itemization_required"] is True

        refused = api_client.prepare_settlement(
            leased_settlement["id"], None, CLERK_HEADERS
        )

        validate_error(refused, ApiErrorId.ITEMIZATION_INCOMPLETE, 422)
        assert refused.json()["data"]["error_id"] != ApiErrorId.DOCUMENTATION_MISSING, (
            "the claim itself never needed a document; the statement does"
        )
        still_draft = fixtures.read_settlement(leased_settlement["id"])
        assert still_draft["status"] == SettlementStatus.DRAFT
        assert still_draft["prepared_at"] is None
        assert still_draft["line_count"] == 0
        untouched = fixtures.read_claim(leased_claim["id"])
        assert untouched["status"] == ClaimStatus.APPROVED
        assert untouched["settlement_id"] is None

        prepared = validate_success(
            api_client.prepare_settlement(company_settlement["id"], None, CLERK_HEADERS)
        )

        assert prepared["status"] == SettlementStatus.PREPARED
        assert prepared["itemization_required"] is False
        assert prepared["line_count"] == 2
        assert prepared["gross_pay_cents"] == 58580
        assert prepared["accessorial_total_cents"] == 12500


class TestNetPayFloor:
    """A down-grade bigger than the next period's earnings cannot be handed to the driver."""

    def test_a_swept_negative_correction_alone_on_a_period_blocks_the_prepare(self):
        """Re-grading a paid 780-mile haul down to 250 short-line miles leaves a −31580 correction
        that is the only activity in the next period, so the preparation is refused outright rather
        than stored or clamped to zero.

        PRD 3.7: "if `net_pay_cents` would be below zero — the usual cause being a retroactive
        down-grade larger than the period's earnings — the whole preparation is rejected with
        `ERR_NEGATIVE_NET_PAY` (HTTP 422) and **no lines are kept**"
        PRD 3.7: "If there is no eligible load, no eligible claim, and no `RETRO_CORRECTION` line
        already swept onto the settlement, there is nothing to settle and the prepare is rejected
        with `ERR_NO_SETTLEABLE_ACTIVITY` (HTTP 422)."
        PRD 3.7: "`RETRO_CORRECTION` lines swept earlier keep the numbers they were given and are
        never renumbered or deleted by preparation."

        Design: Corner/errors/a_retro_downgrade_larger_than_the_period_earnings_blocks_the_prepare
        """
        fixtures.reset_clock()
        _, driver = _leased_driver(
            "Leased Negative Net", "Nora Negative", revenue_bps=None
        )
        load = fixtures.delivered_load(
            driver["id"], stop_count=1, practical_miles=780, hhg_miles=250
        )
        assert load["linehaul_pay_cents"] == 46080

        paid = fixtures.paid_settlement(driver["id"], payment_reference="ACH-NEG-1")
        assert paid["status"] == SettlementStatus.PAID
        assert paid["gross_pay_cents"] == 46080

        fixtures.set_clock("2026-08-11T09:00:00Z")
        dispute = fixtures.file_mileage_dispute(
            driver["id"],
            load["id"],
            MileageGuide.HHG,
            250,
            headers=CLERK_HEADERS,
            evidence_doc_ref="doc://neg-hhg",
        )
        fixtures.review(dispute["id"], CLERK_HEADERS)
        upheld = fixtures.resolve(
            dispute["id"], "UPHOLD", resolution_note="Short-line confirmed."
        )
        assert upheld["status"] == DisputeStatus.UPHELD
        assert upheld["adjustment_cents"] == -31580

        regraded = fixtures.read_load(load["id"])
        assert regraded["pay_status"] == PayStatus.ADJUSTED
        assert regraded["linehaul_pay_cents"] == 14500
        correction = fixtures.read_correction(upheld["resolution_correction_id"])
        assert correction["delta_gross_cents"] == -31580
        assert correction["correction_type"] == CorrectionType.MILEAGE_REGRADE
        held = fixtures.read_driver(driver["id"])
        assert held["pending_retro_correction_cents"] == -31580
        assert held["settlement_hold"] is False

        fixtures.set_clock("2026-08-12T09:00:00Z")
        next_period = fixtures.open_settlement(
            driver["id"], "2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z"
        )
        validate_success(
            api_client.apply_corrections(
                next_period["id"],
                factories.apply_corrections_payload(next_period["version"]),
                CLERK_HEADERS,
            )
        )
        swept = fixtures.read_correction(correction["id"])
        assert swept["status"] == CorrectionStatus.APPLIED
        assert swept["applied_settlement_id"] == next_period["id"]

        refused = api_client.prepare_settlement(next_period["id"], None, CLERK_HEADERS)

        validate_error(refused, ApiErrorId.NEGATIVE_NET_PAY, 422)
        assert refused.json()["data"]["error_id"] != ApiErrorId.NO_SETTLEABLE_ACTIVITY, (
            "the swept correction line is itself activity"
        )
        unprepared = fixtures.read_settlement(next_period["id"])
        assert unprepared["status"] == SettlementStatus.DRAFT
        assert unprepared["prepared_at"] is None
        lines = fixtures.read_settlement_lines(next_period["id"])
        assert len(lines) == 1
        assert lines[0]["line_type"] == LineType.RETRO_CORRECTION
        assert lines[0]["amount_cents"] == -31580
        assert not [
            line for line in lines if line["line_type"] == LineType.LINEHAUL_PER_MILE
        ], "the refused preparation kept none of its own lines"


class TestSweepingNothingIsAConflict:
    """apply-corrections is not idempotent by emptiness."""

    def test_a_driver_with_no_pending_correction_earns_a_409_and_no_version_bump(self):
        """The version handed in was read immediately beforehand, so the refusal cannot be the
        stale-version path, and the settlement is left exactly as it was.

        PRD 3.7: "A sweep against a driver holding no `PENDING` correction, or one whose
        corrections do not belong to the settlement's driver, is rejected with
        `ERR_NO_PENDING_CORRECTIONS` (HTTP 409)"
        PRD 2.8: "`POST /driver-pay/settlements/{id}/apply-corrections` requires
        `expected_settlement_version`, carrying the client's last observed `version` of the target
        settlement. A mismatch with the settlement's current `version` is rejected with
        `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412)."

        Design: Corner/errors/apply_corrections_with_nothing_pending_is_a_conflict_not_a_no_op
        """
        fixtures.reset_clock()
        _, driver = _leased_driver("Leased No Pending", "Nils Nopending")
        fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])
        observed = fixtures.read_settlement(settlement["id"])

        response = api_client.apply_corrections(
            settlement["id"],
            factories.apply_corrections_payload(observed["version"]),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.NO_PENDING_CORRECTIONS, 409)
        assert response.status_code != 200
        assert response.json()["data"]["error_id"] != ApiErrorId.STALE_SETTLEMENT_VERSION, (
            "the version was read immediately before the sweep"
        )
        assert fixtures.read_driver(driver["id"])["pending_retro_correction_cents"] == 0
        _, meta = validate_paginated(
            api_client.list_retro_corrections(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 0
        unchanged = fixtures.read_settlement(settlement["id"])
        assert unchanged["status"] == SettlementStatus.DRAFT
        assert unchanged["line_count"] == 0
        assert unchanged["retro_correction_total_cents"] == 0
        assert unchanged["version"] == observed["version"]


class TestManualDeductionWhitelist:
    """The declared enumeration is wider than the list a manual deduction may cite."""

    def test_advance_default_is_impermissible_while_tractor_lease_with_the_same_amount_is_taken(
        self,
    ):
        """The balance is 3686 and the magnitude 1000, so nothing but the reason code can be
        standing in the way, and swapping the code through takes the balance to 2686.

        PRD 3.3: "a manually recorded deduction may only cite one of six permissible reasons:
        `ESCROW_FUNDING`, `TRACTOR_LEASE`, `INSURANCE_PREMIUM`, `PERMIT_FEE`,
        `CARGO_CLAIM_DAMAGE` or `FUEL_TAX_TRUEUP`. Any other member of the enumeration is an
        impermissible deduction from a leased-operator escrow and is rejected with
        `ERR_DEDUCTION_NOT_PERMISSIBLE` (HTTP 422)."
        PRD 3.3: "A `PERMISSIBLE_DEDUCTION` is negative: the request supplies a positive magnitude
        and the server negates it."

        Design: Corner/errors/manual_escrow_deductions_are_restricted_to_the_permissible_reason_list
        """
        fixtures.reset_clock()
        _, driver = _leased_driver(
            "Leased Deduction Whitelist",
            "Dev Deduction",
            escrow_required=True,
            escrow_target_cents=250000,
            escrow_monthly_deduction_cents=40000,
        )
        fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.approved_settlement(driver["id"])
        funded = fixtures.read_driver(driver["id"])
        assert funded["escrow_balance_cents"] == 3686
        version = funded["version"]

        impermissible = api_client.create_escrow_deduction(
            driver["id"],
            factories.escrow_deduction_payload(
                1000,
                version,
                reason_code=EscrowReasonCode.ADVANCE_DEFAULT,
                document_ref="doc://ded-bad",
            ),
            ADMIN_HEADERS,
        )

        validate_error(impermissible, ApiErrorId.DEDUCTION_NOT_PERMISSIBLE, 422)
        rejected_id = impermissible.json()["data"]["error_id"]
        assert rejected_id != ApiErrorId.INVALID_FIELD_VALUE
        assert rejected_id != ApiErrorId.ESCROW_INSUFFICIENT_BALANCE
        assert rejected_id != ApiErrorId.STALE_DRIVER_VERSION

        taken = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    1000,
                    version,
                    reason_code=EscrowReasonCode.TRACTOR_LEASE,
                    document_ref="doc://ded-ok",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert taken["txn_type"] == EscrowTxnType.PERMISSIBLE_DEDUCTION
        assert taken["amount_cents"] == -1000
        assert taken["balance_after_cents"] == 2686
        after = fixtures.read_driver(driver["id"])
        assert after["escrow_balance_cents"] == 2686
        assert after["escrow_status"] == EscrowStatus.COLLECTING

        ledger, meta = validate_paginated(
            api_client.list_escrow_transactions(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 2
        assert {(row["txn_type"], row["amount_cents"]) for row in ledger} == {
            (EscrowTxnType.DEPOSIT, 3686),
            (EscrowTxnType.PERMISSIBLE_DEDUCTION, -1000),
        }
        assert not [
            row
            for row in ledger
            if row["reason_code"] == EscrowReasonCode.ADVANCE_DEFAULT
        ], "the refused deduction left no ledger entry behind"


class TestReopenLimitBoundary:
    """The guard is read before the increment, so the boundary sits at the third attempt."""

    def test_two_reopens_are_allowed_and_the_third_is_refused_with_the_dispute_left_denied(self):
        """Each denial is money-neutral, the reopens at counts 0 and 1 succeed, and the attempt at
        count 2 is refused without flipping the dispute back to OPEN.

        PRD 3.9: "Reopening is allowed only while `reopen_count` is strictly below 2, so the same
        dispute row may traverse `OPEN` → `UNDER_REVIEW` → `DENIED` → `OPEN` twice before a third
        attempt is rejected with `ERR_DISPUTE_REOPEN_LIMIT` (HTTP 409)."
        PRD 3.9: "A denial advances the dispute `UNDER_REVIEW` → `DENIED`, records the
        `resolution_note` and the `resolved_by_user_id`, leaves `adjustment_cents` null, creates no
        correction and touches no load or settlement money field"

        Design: Corner/errors/the_third_reopen_of_a_denied_dispute_hits_the_reopen_limit
        """
        fixtures.reset_clock()
        _, driver = _leased_driver("Leased Reopen Limit", "Rob Reopen")
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock("2026-08-06T09:00:00Z")
        dispute = fixtures.file_mileage_dispute(
            driver["id"],
            load["id"],
            MileageGuide.HHG,
            742,
            headers=CLERK_HEADERS,
            narrative="First filing.",
            evidence_doc_ref="doc://rop-1",
        )
        fixtures.review(dispute["id"], CLERK_HEADERS)
        fixtures.resolve(
            dispute["id"], "DENY", resolution_note="Log does not support it."
        )

        first = validate_success(
            api_client.reopen_dispute(
                dispute["id"],
                factories.reopen_payload("Second try.", evidence_doc_ref="doc://rop-2"),
                ADMIN_HEADERS,
            )
        )
        assert first["status"] == DisputeStatus.OPEN
        assert first["reopen_count"] == 1
        assert first["resolution_note"] is None
        assert first["resolved_by_user_id"] is None
        assert first["reviewed_by_user_id"] is None

        fixtures.review(dispute["id"], CLERK_HEADERS)
        fixtures.resolve(dispute["id"], "DENY", resolution_note="Still unsupported.")
        second = validate_success(
            api_client.reopen_dispute(
                dispute["id"],
                factories.reopen_payload("Third try.", evidence_doc_ref="doc://rop-3"),
                ADMIN_HEADERS,
            )
        )
        assert second["status"] == DisputeStatus.OPEN
        assert second["reopen_count"] == 2

        fixtures.review(dispute["id"], CLERK_HEADERS)
        fixtures.resolve(dispute["id"], "DENY", resolution_note="Final denial.")

        refused = api_client.reopen_dispute(
            dispute["id"],
            factories.reopen_payload("Fourth try.", evidence_doc_ref="doc://rop-4"),
            ADMIN_HEADERS,
        )

        validate_error(refused, ApiErrorId.DISPUTE_REOPEN_LIMIT, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.DISPUTE_STATE_INVALID, (
            "the dispute is legitimately DENIED; it is the count that is spent"
        )
        frozen = fixtures.read_dispute(dispute["id"])
        assert frozen["status"] == DisputeStatus.DENIED
        assert frozen["reopen_count"] == 2
        assert frozen["narrative"] == "Third try."
        assert frozen["evidence_doc_ref"] == "doc://rop-3"
        assert frozen["evidence_doc_ref"] != "doc://rop-4"
        untouched = fixtures.read_load(load["id"])
        assert untouched["pay_status"] == PayStatus.ACCRUED
        assert untouched["linehaul_pay_cents"] == 46080
