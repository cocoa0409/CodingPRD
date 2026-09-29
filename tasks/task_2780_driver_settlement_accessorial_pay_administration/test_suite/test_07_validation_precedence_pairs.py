"""Precedence between simultaneously violated checks.

When one request breaks several rules at once, exactly one error may come back, and the
rung it comes from is fully determined by the ladder rather than by the order the server
happens to evaluate things in.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    DriverType,
    EmploymentStatus,
    EscrowReasonCode,
    EscrowStatus,
    MileageGuide,
    PayStatus,
    PerDiemMethod,
)


def _terminated_driver_without_escrow():
    """An owner-operator on an escrow-free package, terminated, so that a manual escrow
    deduction violates the employment check, the escrow check and the balance check at once."""
    package = fixtures.active_package(
        driver_type=DriverType.OWNER_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Owner No Escrow",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.OWNER_OPERATOR,
        per_diem_elected=False,
        legal_name="Kip Kaput",
        home_state="OK",
    )
    fixtures.set_clock("2026-08-06T12:00:00Z")
    fixtures.set_driver_status(driver["id"], EmploymentStatus.TERMINATED)
    current = fixtures.read_driver(driver["id"])
    assert current["employment_status"] == EmploymentStatus.TERMINATED
    assert current["escrow_status"] == EscrowStatus.NOT_REQUIRED
    assert current["escrow_balance_cents"] == 0
    return current


class TestStateChecksOutrankFiscalChecksOnEscrowDeduction:
    """Rung 20 wins over rung 21 and rung 53 on one triply invalid request."""

    def test_employment_state_error_surfaces_and_not_the_balance_error(self):
        """The deduction breaks the employment check, the escrow-status check and the balance
        check simultaneously, and the lowest-numbered of the three is the one reported.

        PRD 2.9 rung 20: "`ERR_DRIVER_NOT_ACTIVE` — the driver's `employment_status` is the one
        the operation needs: `ACTIVE` to book a load, submit an accessorial claim, issue an
        advance, open a settlement or record an escrow deduction".
        PRD 2.9: "Checks are evaluated in the fixed order below and the first failure is
        reported."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_over_fiscal_on_escrow_deduction
        """
        driver = _terminated_driver_without_escrow()

        response = api_client.create_escrow_deduction(
            driver["id"],
            factories.escrow_deduction_payload(
                5000,
                driver["version"],
                reason_code=EscrowReasonCode.TRACTOR_LEASE,
                document_ref="doc://lease-invoice-9",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.DRIVER_NOT_ACTIVE, 409)
        error_id = response.json()["data"]["error_id"]
        assert error_id != ApiErrorId.ESCROW_INSUFFICIENT_BALANCE, (
            "the money limits sit at the bottom of the ladder"
        )
        assert error_id != ApiErrorId.ESCROW_NOT_ACTIVE
        assert error_id != ApiErrorId.STALE_DRIVER_VERSION, (
            "the supplied expected_driver_version is the current one"
        )

    def test_the_refused_deduction_writes_nothing_at_all(self):
        """A rejected deduction leaves the ledger empty, the balance at zero, the escrow axis
        untouched and the driver's version exactly where it was.

        PRD 2.11: "A driver's `escrow_balance_cents` is at all times the sum of `amount_cents`
        across every escrow ledger entry whose `driver_id` is that driver, with no filtering by
        any status, because the ledger is append-only; it is 0 when the ledger is empty."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_over_fiscal_on_escrow_deduction
        """
        driver = _terminated_driver_without_escrow()

        api_client.create_escrow_deduction(
            driver["id"],
            factories.escrow_deduction_payload(5000, driver["version"]),
            ADMIN_HEADERS,
        )

        entries, meta = validate_paginated(
            api_client.list_escrow_transactions(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 0
        assert entries == []
        after = fixtures.read_driver(driver["id"])
        assert after["escrow_balance_cents"] == 0
        assert after["escrow_status"] == EscrowStatus.NOT_REQUIRED
        assert after["version"] == driver["version"], "a refused request is not a mutation"


def _undocumented_claim_on_a_settled_load():
    """A DETENTION claim with no document, sitting on a load that has already been paid out,
    so that the documentation check and the already-settled check both fail."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Priority Pair",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Lou Layover",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    fixtures.prepare(settlement["id"])
    fixtures.approve(settlement["id"])
    fixtures.pay(settlement["id"], "ACH-2026-08-10-0003")
    assert fixtures.read_load(load["id"])["pay_status"] == PayStatus.SETTLED

    fixtures.set_clock("2026-08-11T09:00:00Z")
    claim = fixtures.submit_claim(
        load["id"],
        driver["id"],
        AccessorialType.DETENTION,
        "2026-08-04T18:00:00Z",
        "2026-08-04T20:30:00Z",
        headers=make_driver_headers(driver["id"]),
    )
    assert claim["documentation_required"] is True
    assert claim["document_ref"] is None
    return {"driver": driver, "load": load, "settlement": settlement, "claim": claim}


class TestDocumentationChecksOutrankReferentialChecksOnClaimApproval:
    """Rung 29 wins over rung 48, and curing rung 29 then exposes rung 48."""

    def test_missing_document_is_reported_before_the_settled_load(self):
        """Both failures are present on the first approval attempt, and the documentation error
        is the one that surfaces.

        PRD 2.9 rung 29: "`ERR_DOCUMENTATION_MISSING` — a claim whose `accessorial_type` is
        `DETENTION`, `TARPING` or `BREAKDOWN` carries a non-null `document_ref` before it may be
        approved. The documentation requirement is evaluated before any bookkeeping question
        about the underlying load."

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_over_referential_on_claim_approve
        """
        env = _undocumented_claim_on_a_settled_load()

        response = api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)

        validate_error(response, ApiErrorId.DOCUMENTATION_MISSING, 422)
        assert response.json()["data"]["error_id"] != ApiErrorId.LOAD_ALREADY_SETTLED

    def test_attaching_the_document_exposes_the_already_settled_load(self):
        """The second rule was always there: with the document supplied, the very same endpoint
        now refuses the claim because the load's money has already gone out.

        PRD 3.5: "A load already attached to a settlement is refused with
        `ERR_LOAD_ALREADY_SETTLED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_over_referential_on_claim_approve
        """
        env = _undocumented_claim_on_a_settled_load()
        validate_error(
            api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS),
            ApiErrorId.DOCUMENTATION_MISSING,
            422,
        )

        validate_success(
            api_client.attach_claim_document(
                env["claim"]["id"],
                factories.claim_document_payload("doc://detention-signin-sheet-77"),
                CLERK_HEADERS,
            )
        )
        response = api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)

        validate_error(response, ApiErrorId.LOAD_ALREADY_SETTLED, 409)

    def test_neither_refusal_prices_the_claim_or_touches_the_paid_statement(self):
        """Two refused approvals leave the claim SUBMITTED and unpriced, and the paid statement
        carries no accessorial money.

        PRD 3.5: "A new claim is `SUBMITTED`, its `billable_units` and `amount_cents` are 0 until
        approval, its `settlement_id` and `approved_by_user_id` are null".

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_over_referential_on_claim_approve
        """
        env = _undocumented_claim_on_a_settled_load()
        api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)
        validate_success(
            api_client.attach_claim_document(
                env["claim"]["id"],
                factories.claim_document_payload("doc://detention-signin-sheet-77"),
                CLERK_HEADERS,
            )
        )
        api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)

        claim = fixtures.read_claim(env["claim"]["id"])
        assert claim["status"] == ClaimStatus.SUBMITTED
        assert claim["amount_cents"] == 0
        assert claim["billable_units"] == 0
        assert claim["approved_by_user_id"] is None
        assert claim["settlement_id"] is None
        assert claim["documentation_required"] is True

        settlement = fixtures.read_settlement(env["settlement"]["id"])
        assert settlement["gross_pay_cents"] == 46080
        assert settlement["accessorial_total_cents"] == 0
