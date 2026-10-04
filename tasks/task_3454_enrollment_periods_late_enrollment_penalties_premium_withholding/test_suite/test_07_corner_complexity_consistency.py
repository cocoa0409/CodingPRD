"""Corner coverage: concurrency, cascading side effects, and read-your-write."""

from test_helpers import (
    ApiErrorId,
    advance_clock_and_run_cycle,
    assert_coverage_enrollment,
    assert_single_governing_election,
    beneficiary_version,
    create_election,
    election_payload,
    enroll,
    enrollment_payload,
    list_elections,
    list_invoices,
    make_beneficiary_headers,
    pay_invoice_in_full,
    publish_rate_schedule,
    read_enrollment,
    register_beneficiary,
    set_clock,
    setup_beneficiary_with_enrollment,
    setup_delinquent_enrollment,
    setup_withholding_shortfall,
    validate_error,
    validate_success,
)


def test_occ_stale_version_election_rejected(client):
    """PRD section 2.7: "If the value does not match the Beneficiary's current
    `version` — meaning another writer has advanced the beneficiary's version
    since the client last read it — the request is rejected with
    `ERR_STALE_BENEFICIARY_VERSION` (HTTP 412)". PRD section 2.7: "A
    successful election creation increments the Beneficiary's `version` by 1."

    Design: Corner/complexity_layers/occ_stale_version_election_rejected
    """
    set_clock(client, "2025-01-10T00:00:00Z")
    beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
    enroll(client, beneficiary, part="PART_B")
    set_clock(client, "2026-10-20T00:00:00Z")

    stale_version = beneficiary_version(client, beneficiary["id"])
    first = create_election(client, beneficiary, "AEP", "MA")
    assert first["status"] == "GOVERNING"
    assert (
        beneficiary_version(client, beneficiary["id"]) == stale_version + 1
    ), "the first election advanced the version, making the captured one stale"

    response = client.create_election(
        election_payload(beneficiary["id"], "AEP", "MA", stale_version),
        headers=make_beneficiary_headers(beneficiary["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_BENEFICIARY_VERSION)

    elections = list_elections(client, beneficiary)
    assert len(elections) == 1, "the rejected election is not stored"
    assert_single_governing_election(elections, "AEP-2026")


def test_withholding_shortfall_triggers_suspension_cascade(client):
    """PRD section 3.7: "When any part comes up short, three things happen
    together: the arrangement flips from `ACTIVE` to `SUSPENDED`; every
    `WITHHOLDING` enrollment of that beneficiary flips to `DIRECT_BILL` (a
    cascade across all of them, not just the shortfall part); and one arrears
    PremiumInvoice is issued per shortfall part, marked `is_arrears` true,
    carrying the shortfall amount, with its `due_date` set thirty days after
    the cycle date. With a benefit of 21000 cents against a Part B due of
    18500 and a Part D due of 3450, Part B receives its full 18500, Part D
    receives 2500, the 950-cent Part D shortfall suspends the arrangement and
    becomes an arrears invoice."

    Design: Corner/complexity_layers/withholding_shortfall_triggers_suspension_cascade
    """
    state = setup_withholding_shortfall(client)
    assert state["arrangement"]["status"] == "SUSPENDED"
    assert state["enrollment_b"]["enrollment_status"] == "ACTIVE"
    assert state["enrollment_b"]["collection_status"] == "DIRECT_BILL"
    assert state["enrollment_d"]["enrollment_status"] == "ACTIVE"
    assert state["enrollment_d"]["collection_status"] == "DIRECT_BILL"

    arrears = [inv for inv in state["invoices"] if inv["is_arrears"]]
    assert len(arrears) == 1, "exactly one arrears invoice for the shortfall part"
    assert arrears[0]["part"] == "PART_D"
    assert arrears[0]["amount_cents"] == 950
    assert arrears[0]["due_date"] == "2026-07-05", "cycle date + 30 days"


def test_delinquency_termination_after_third_past_due(client):
    """PRD section 3.7: "Once an enrollment carries three or more `PAST_DUE`
    invoices, the enrollment itself is terminated: `enrollment_status` becomes
    `TERMINATED` with `end_month` set to the clock month, every non-`PAID`
    invoice on it — `ISSUED` or `PAST_DUE` — becomes `WRITTEN_OFF`, and its
    collection status closes."

    Design: Corner/complexity_layers/delinquency_termination_after_third_past_due
    """
    publish_rate_schedule(client, 2026)
    beneficiary, enrollment = setup_beneficiary_with_enrollment(client)
    advance_clock_and_run_cycle(client, "2026-06-15T00:00:00Z")
    advance_clock_and_run_cycle(client, "2026-07-15T00:00:00Z")
    advance_clock_and_run_cycle(client, "2026-08-15T00:00:00Z")
    summary = advance_clock_and_run_cycle(client, "2026-09-15T00:00:00Z")
    assert summary["enrollments_terminated"] >= 1

    terminated = read_enrollment(client, enrollment["id"])
    assert terminated["enrollment_status"] == "TERMINATED"
    assert terminated["end_month"] == "2026-09"
    assert terminated["collection_status"] == "CLOSED"

    invoices = list_invoices(client, beneficiary)
    billed = {inv["service_month"]: inv for inv in invoices}
    for month in ("2026-06", "2026-07", "2026-08"):
        assert billed[month]["status"] == "WRITTEN_OFF", (
            "invoice for {0} must be written off".format(month)
        )
    assert billed["2026-06"]["amount_cents"] == 18500, (
        "IRMAA-free fallback: base premium plus penalty, no determination"
    )
    for invoice in invoices:
        assert invoice["status"] not in ("ISSUED", "PAST_DUE"), (
            "no payable invoice survives the write-off cascade"
        )


def test_cure_past_due_restores_direct_bill(client):
    """PRD section 3.7: "Payment also triggers the delinquency cure re-check:
    if the enrollment was `DELINQUENT` and no `PAST_DUE` invoices remain for
    it, its collection status returns to `DIRECT_BILL`." PRD section 3.7: "A
    successful payment moves the invoice to `PAID` and sets `paid_cents` and
    `applied_cents` to the paid amount and `outstanding_cents` to zero."

    Design: Corner/complexity_layers/cure_past_due_restores_direct_bill
    """
    beneficiary, enrollment, invoices = setup_delinquent_enrollment(
        client, past_due_count=2
    )
    assert enrollment["collection_status"] == "DELINQUENT"
    past_due = [inv for inv in invoices if inv["status"] == "PAST_DUE"]
    assert len(past_due) == 2

    pay_invoice_in_full(client, past_due[0])
    midway = read_enrollment(client, enrollment["id"])
    assert midway["collection_status"] == "DELINQUENT", (
        "one past-due invoice remains: no cure yet"
    )

    pay_invoice_in_full(client, past_due[1])
    cured = read_enrollment(client, enrollment["id"])
    assert cured["collection_status"] == "DIRECT_BILL"
    assert cured["enrollment_status"] == "ACTIVE"

    settled = {
        inv["id"]: inv for inv in list_invoices(client, beneficiary)
    }
    for invoice in past_due:
        assert settled[invoice["id"]]["status"] == "PAID"
        assert settled[invoice["id"]]["paid_cents"] == 18500
        assert settled[invoice["id"]]["outstanding_cents"] == 0


def test_enrollment_create_response_immediately_shows_computed_fields(client):
    """PRD section 2.5: "Consistency is immediate: every mutation performed by
    a request is visible in that same request's response body." PRD
    section 3.2: "enrolling during `T` yields the month after enrollment" and
    "A new CoverageEnrollment starts with `enrollment_status` `PENDING` and
    `collection_status` `PENDING_SETUP`, and with `end_month` null while the
    coverage is open-ended."

    Design: Corner/consistency_model/enrollment_create_response_immediately_shows_computed_fields
    """
    beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
    set_clock(client, "2026-12-10T00:00:00Z")
    response = client.create_enrollment(
        enrollment_payload(beneficiary["id"], "PART_B"),
        headers=make_beneficiary_headers(beneficiary["id"]),
    )
    created = validate_success(response, 201)
    assert_coverage_enrollment(created)
    assert created["effective_month"] == "2027-01"
    assert created["enrollment_status"] == "PENDING"
    assert created["collection_status"] == "PENDING_SETUP"
    assert created["enrolled_via_window"] == "IEP"
    assert created["end_month"] is None
