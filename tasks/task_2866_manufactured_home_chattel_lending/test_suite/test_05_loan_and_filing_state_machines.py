"""Two non-linear machines: the loan's state triple and the filing's cyclic status.

The loan's perfection dimension walks backwards then forwards
(PERFECTED -> RE_PERFECTION_REQUIRED -> FILING_SUBMITTED -> PERFECTED) while its
other two dimensions hold still (PRD §3.5, §3.8), and one filing visits
SUBMITTED twice with a different attempt count each time.
"""

from test_helpers import (
    assert_lien_filing,
    factories,
    fixtures,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ESCROW_TARGET_CENTS = 200000
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240

# Dana Whitfield, credit score 705, so the credit-tier spread is exactly zero.
DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}

# 8000 bps of the 6698330-cent insurable value beats the 4600000-cent exposure,
# so 5400000 cents of dwelling cover clears the personal-property requirement.
DWELLING_COVERAGE_CENTS = 5400000

TITLE_LIEN_DOCUMENTS = ["TITLE_APPLICATION", "LIEN_ENTRY_FORM"]
DEED_OF_TRUST_REFERENCE = "GA-DT-2026-11902"
TITLE_LIEN_REFERENCE = "GA-TL-2026-90013"


def _funded_private_land_loan_perfected_by_title_lien(api):
    """A FUNDED chattel loan on the borrower's own land, PERFECTED by title lien."""
    scenario = fixtures.setup_funded_private_land_loan(
        api,
        clock=CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
        escrow_target_cents=ESCROW_TARGET_CENTS,
        borrower_overrides=DANA,
    )
    loan = scenario["loan"]
    assert loan["underwriting_state"] == "FUNDED"
    assert loan["servicing_state"] == "CURRENT"
    assert loan["perfection_state"] == "PERFECTED"
    assert loan["collateral_classification"] == "PERSONAL_PROPERTY"
    return scenario


def _community_loan_with_submitted_title_lien(api):
    """A DRAFT community application carrying one SUBMITTED title lien."""
    scenario = fixtures.setup_community_collateral(
        api, clock=CLOCK, agreement="EXECUTED"
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"], "ORIGINATION"
    )
    scenario["loan"] = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        scenario["valuation"]["id"],
        PRINCIPAL_CENTS,
        REQUESTED_TERM_MONTHS,
    )
    scenario["filing"] = fixtures.tender_filing(
        api, factories.title_lien_payload(scenario["loan"]["id"])
    )
    return scenario


def test_conversion_pushes_only_the_perfection_dimension_backwards(api):
    """PRD §3.8: "Every non-terminal loan on the unit has its
    `collateral_classification` rewritten to `REAL_PROPERTY`, and any such loan
    whose lien dimension stood at `PERFECTED` is moved to
    `RE_PERFECTION_REQUIRED` — the loan is now unsecured in substance until a
    deed of trust is recorded."
    PRD §3.8: "Every filing on the unit that is a `RECORDED` `TITLE_LIEN` moves
    to `RELEASED` with `released_at` stamped, because a title lien has nothing
    left to attach to."

    Design: Difficulty/non_linear_state_machine/loan_three_state_dimensions_advance_independently
    """
    scenario = _funded_private_land_loan_perfected_by_title_lien(api)

    unit = fixtures.complete_conversion(api, scenario["unit"]["id"])
    assert unit["classification"] == "REAL_PROPERTY"

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["perfection_state"] == "RE_PERFECTION_REQUIRED"
    assert loan["collateral_classification"] == "REAL_PROPERTY"
    assert loan["underwriting_state"] == "FUNDED", (
        "the conversion cascade never touches the underwriting dimension"
    )
    assert loan["servicing_state"] == "CURRENT", (
        "the conversion cascade never touches the servicing dimension"
    )

    filing = fixtures.read_filing(api, scenario["filing"]["id"])
    assert filing["status"] == "RELEASED"
    assert filing["released_at"] is not None


def test_re_perfection_tender_moves_the_lien_dimension_forward_again(api):
    """PRD §3.8: "A loan sitting at `RE_PERFECTION_REQUIRED` is re-perfected by
    tendering a fresh `LAND_HOME_DEED_OF_TRUST` filing — a second filing on the
    same loan, coexisting with the released title lien — which moves the lien
    dimension from `RE_PERFECTION_REQUIRED` to `FILING_SUBMITTED` and then, on a
    recorded outcome, to `PERFECTED`."
    PRD §3.5: "The platform records the shortfall in `missing_documents`, which
    holds exactly those required codes for the chosen `filing_type` that are
    absent from `submitted_documents`."

    Design: Difficulty/non_linear_state_machine/loan_three_state_dimensions_advance_independently
    """
    scenario = _funded_private_land_loan_perfected_by_title_lien(api)
    loan_id = scenario["loan"]["id"]
    fixtures.complete_conversion(api, scenario["unit"]["id"])

    deed = fixtures.tender_filing(api, factories.deed_of_trust_payload(loan_id))

    assert_lien_filing(deed)
    assert deed["filing_type"] == "LAND_HOME_DEED_OF_TRUST"
    assert deed["status"] == "SUBMITTED"
    assert deed["attempt_number"] == 1, (
        "the second instrument on the loan opens its own attempt count at 1"
    )
    assert deed["missing_documents"] == []
    assert deed["unit_id"] == scenario["unit"]["id"], (
        "the caller never supplies unit_id; it is copied from the loan's collateral"
    )

    loan = fixtures.read_loan(api, loan_id)
    assert loan["perfection_state"] == "FILING_SUBMITTED"
    assert loan["underwriting_state"] == "FUNDED"
    assert loan["servicing_state"] == "CURRENT"


def test_recorded_deed_of_trust_perfects_without_re_encumbering_the_title(api):
    """PRD §3.5: "When the recorded instrument is a `TITLE_LIEN`, it additionally
    moves the unit's `title_status` from `ACTIVE_TITLE` to `TITLE_ENCUMBERED`,
    because the state has now noted the lender on the certificate of title."
    PRD §3.8: "The unit's `title_status` moves to `TITLE_SURRENDERED`, since the
    certificate of title is handed back to the state."

    Design: Difficulty/non_linear_state_machine/loan_three_state_dimensions_advance_independently
    """
    scenario = _funded_private_land_loan_perfected_by_title_lien(api)
    loan_id = scenario["loan"]["id"]
    unit_id = scenario["unit"]["id"]
    fixtures.complete_conversion(api, unit_id)
    deed = fixtures.tender_filing(api, factories.deed_of_trust_payload(loan_id))

    recorded = fixtures.record_filing_outcome(
        api, deed["id"], agency_reference=DEED_OF_TRUST_REFERENCE
    )

    assert recorded["status"] == "RECORDED"
    assert recorded["agency_reference"] == DEED_OF_TRUST_REFERENCE
    assert recorded["recorded_at"] is not None

    loan = fixtures.read_loan(api, loan_id)
    assert loan["perfection_state"] == "PERFECTED", (
        "the lien dimension has now returned to where it started"
    )
    assert loan["underwriting_state"] == "FUNDED"
    assert loan["servicing_state"] == "CURRENT"

    unit = fixtures.read_unit(api, unit_id)
    assert unit["title_status"] == "TITLE_SURRENDERED", (
        "only a recorded title lien encumbers a certificate of title, and this "
        "unit surrendered its certificate at conversion"
    )


def test_rejection_returns_the_lien_dimension_to_unperfected(api):
    """PRD §3.5: "A `REJECTED` outcome moves the filing from `SUBMITTED` to
    `REJECTED`, stores the supplied `rejection_code` — one of `MISSING_DOCUMENT`,
    `NAME_MISMATCH` or `FEE_SHORTFALL` — and returns the loan's lien dimension
    from `FILING_SUBMITTED` to `UNPERFECTED`."
    PRD §3.5: "A successful tender copies `unit_id` onto the filing from the
    loan's collateral — the caller never supplies it — computes
    `missing_documents`, opens the filing at `status` `SUBMITTED` with
    `attempt_number` 1, and advances the loan's lien dimension from `UNPERFECTED`
    to `FILING_SUBMITTED` while incrementing the loan's `version`."

    Design: Difficulty/non_linear_state_machine/lien_filing_reject_resubmit_cycle_returns_to_recorded
    """
    scenario = _community_loan_with_submitted_title_lien(api)
    filing_id = scenario["filing"]["id"]
    assert scenario["filing"]["status"] == "SUBMITTED"
    assert scenario["filing"]["attempt_number"] == 1
    assert fixtures.read_loan(api, scenario["loan"]["id"])[
        "perfection_state"
    ] == "FILING_SUBMITTED"

    rejected = fixtures.record_filing_outcome(
        api, filing_id, outcome="REJECTED", rejection_code="NAME_MISMATCH"
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_code"] == "NAME_MISMATCH"
    assert rejected["attempt_number"] == 1
    assert rejected["recorded_at"] is None

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["perfection_state"] == "UNPERFECTED"
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["title_status"] == "ACTIVE_TITLE", (
        "a rejected filing never noted the lender on the certificate of title"
    )


def test_resubmitted_filing_re_enters_submitted_on_a_second_attempt(api):
    """PRD §3.5: "A `ClosingAgent` re-tenders a `REJECTED` filing with a
    corrected `submitted_documents` list, which moves the filing back from
    `REJECTED` to `SUBMITTED`, increases `attempt_number` by exactly one, clears
    `rejection_code` back to null, recomputes `missing_documents` from the new
    list, and returns the loan's lien dimension from `UNPERFECTED` to
    `FILING_SUBMITTED`, incrementing the loan's `version`."
    PRD §3.5: "A `RECORDED` outcome — which requires that `missing_documents` be
    empty — moves the filing from `SUBMITTED` to `RECORDED`, stores the supplied
    `agency_reference`, stamps `recorded_at` with the logical clock, and advances
    the loan's lien dimension from `FILING_SUBMITTED` to `PERFECTED`."

    Design: Difficulty/non_linear_state_machine/lien_filing_reject_resubmit_cycle_returns_to_recorded
    """
    scenario = _community_loan_with_submitted_title_lien(api)
    filing_id = scenario["filing"]["id"]
    loan_id = scenario["loan"]["id"]
    fixtures.record_filing_outcome(
        api, filing_id, outcome="REJECTED", rejection_code="NAME_MISMATCH"
    )

    resubmitted = validate_success(
        api.resubmit_lien_filing(
            filing_id, factories.resubmit_payload(TITLE_LIEN_DOCUMENTS), fixtures.CLOSER
        )
    )

    assert resubmitted["status"] == "SUBMITTED", (
        "the same status is visited a second time, with a different attempt count"
    )
    assert resubmitted["attempt_number"] == 2
    assert resubmitted["rejection_code"] is None
    assert resubmitted["missing_documents"] == []
    assert fixtures.read_loan(api, loan_id)["perfection_state"] == "FILING_SUBMITTED"

    recorded = fixtures.record_filing_outcome(
        api, filing_id, agency_reference=TITLE_LIEN_REFERENCE
    )

    assert recorded["status"] == "RECORDED"
    assert recorded["attempt_number"] == 2, "recording does not touch the attempt count"
    assert recorded["agency_reference"] == TITLE_LIEN_REFERENCE
    assert recorded["recorded_at"] is not None

    loan = fixtures.read_loan(api, loan_id)
    assert loan["perfection_state"] == "PERFECTED"
    assert loan["underwriting_state"] == "DRAFT", (
        "the whole perfection cycle never touched the underwriting dimension"
    )
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["title_status"] == "TITLE_ENCUMBERED"
