"""Booking the retail contract and assembling the funding package."""
from test_helpers import (
    ADMIN, ANALYST, FUNDER, ApiErrorId, BASE_REQUIRED_DOC_TYPES, CLOCK_START,
    api_client, assert_contract, assert_document, book_contract, decision_application,
    make_dealer_principal_headers, read_application, read_contract, read_dealer,
    resubmit_application, setup_booked_contract, setup_program, submit_and_approve,
    submit_application, upload_package, validate_error, validate_paginated,
    validate_success, verify_document,
)


def test_contract_derives_every_commercial_field_from_the_application(api):
    """PRD 3.4: "The contract copies forward from the application its `dealer_id`,
    its pinned `agreement_id`, its `amount_financed_cents`, its `term_months`, its
    `buy_rate_apr_bps`, and its `monitoring_cohort`, and it copies
    `acquisition_fee_cents` from the assigned tier row."
    PRD 3.4: "Two values are computed at creation: `markup_bps`, which is
    `contract_apr_bps` less `buy_rate_apr_bps`, and `required_doc_types`, the array
    of document types the funding package must contain."
    PRD 3.4: "The base requirement is three types — `RETAIL_INSTALLMENT_CONTRACT`,
    `TITLE_APPLICATION`, and `INSURANCE_BINDER` — and a fourth,
    `INCOME_VERIFICATION`, is added when the originating application's
    `stipulation_count` is greater than zero."
    PRD 3.4: "Booking a contract advances the application `APPROVED → CONTRACTED`
    and creates the contract with `funding_status` at `PENDING_DOCS` and
    `reserve_status` at `NONE`."

    Design: Corner/entities/contract_computed_fields_copied_from_application
    """
    program = setup_program()
    application = submit_and_approve(program["dealer_id"], applicant_reference="APP-cc")

    response = api.create_contract(
        {
            "application_id": application["id"],
            "contract_apr_bps": 749,
            "contract_date": CLOCK_START,
        },
        program["dealer_headers"],
    )
    contract = validate_success(response, 201)
    assert_contract(contract)

    assert contract["amount_financed_cents"] == 2801000
    assert contract["term_months"] == 60
    assert contract["buy_rate_apr_bps"] == 549
    assert contract["markup_bps"] == 200
    assert contract["acquisition_fee_cents"] == 15000
    assert contract["monitoring_cohort"] == "CONTROL"
    assert contract["dealer_id"] == program["dealer_id"]
    assert contract["agreement_id"] == program["agreement"]["id"]
    assert list(contract["required_doc_types"]) == BASE_REQUIRED_DOC_TYPES, (
        "stipulation_count is 0, so only the three base types are required"
    )
    assert contract["funding_status"] == "PENDING_DOCS"
    assert contract["reserve_status"] == "NONE"
    assert contract["verified_doc_count"] == 0
    assert contract["doc_defect_count"] == 0
    assert contract["funded_at"] is None
    assert contract["funded_by_user_id"] is None
    assert read_application(application["id"])["status"] == "CONTRACTED"


def test_a_stipulated_file_adds_income_verification_to_the_package(api):
    """PRD 3.4: "a fourth, `INCOME_VERIFICATION`, is added when the originating
    application's `stipulation_count` is greater than zero."
    PRD 3.3: "An approval issued from `RESUBMITTED` behaves identically to one
    issued from `SUBMITTED` and retains the `stipulation_count` set by the earlier
    conditioning — which is what causes an income document to be required at funding."
    PRD 3.5: "The contract's `funding_status` must be `DOCS_VERIFIED`, meaning every
    type in `required_doc_types` has a document in `VERIFIED`; otherwise
    `ERR_DOCS_NOT_VERIFIED` (HTTP 409)."

    Design: Corner/entities/conditioned_application_adds_income_verification_to_required_docs
    """
    program = setup_program()
    application = submit_application(program["dealer_id"], applicant_reference="APP-st")
    decision_application(
        application["id"], "CONDITION", stipulation_count=1,
        decision_note="PROOF_OF_INCOME",
    )
    resubmit_application(application["id"], program["dealer_id"], credit_score=725)
    decision_application(application["id"], "APPROVE")

    contract = book_contract(application["id"], program["dealer_id"])
    assert list(contract["required_doc_types"]) == BASE_REQUIRED_DOC_TYPES + [
        "INCOME_VERIFICATION"
    ]

    documents = upload_package(contract["id"], program["dealer_id"], prefix="IMG-st")
    for document in documents.values():
        verify_document(document["id"])

    refreshed = read_contract(contract["id"])
    assert refreshed["verified_doc_count"] == len(BASE_REQUIRED_DOC_TYPES)
    assert refreshed["funding_status"] == "PENDING_DOCS"

    response = api.fund_contract(
        contract["id"], {"funding_date": CLOCK_START}, FUNDER
    )
    validate_error(response, ApiErrorId.ERR_DOCS_NOT_VERIFIED.value, 409)


def test_contract_apr_above_the_pinned_ceiling_is_refused(api):
    """PRD 3.4: "First, `contract_apr_bps` must be at or above the application's
    pinned `buy_rate_apr_bps` and at or below its pinned `max_contract_apr_bps`; a
    rate below the buy rate or above the participation ceiling is refused with
    `ERR_MARKUP_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/contract_apr_above_pinned_cap_returns_markup_cap_exceeded
    """
    program = setup_program()
    application = submit_and_approve(program["dealer_id"], applicant_reference="APP-mc")
    assert application["max_contract_apr_bps"] == 749

    response = api.create_contract(
        {
            "application_id": application["id"],
            "contract_apr_bps": 800,
            "contract_date": CLOCK_START,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MARKUP_CAP_EXCEEDED.value, 422)

    unchanged = read_application(application["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["max_contract_apr_bps"] == 749
    _, meta = validate_paginated(
        api.list_contracts(ADMIN, params={"application_id": application["id"]})
    )
    assert meta["total_count"] == 0


def test_amount_financed_above_the_assigned_tier_advance_limit_is_refused(api):
    """PRD 3.4: "Second, the advance limit: the application's
    `amount_financed_cents` must be at or below the applicant's
    `collateral_value_cents` multiplied by the **assigned** tier's
    `advance_rate_pct`, divided by 100 and rounded half up — the tier used is the
    post-demotion tier the decision assigned, never the base tier. Exceeding it is
    `ERR_ADVANCE_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/contract_amount_above_tier_advance_limit_returns_advance_limit_exceeded
    """
    program = setup_program()
    application = submit_and_approve(
        program["dealer_id"], applicant_reference="APP-al",
        monthly_income_cents=900000, monthly_debt_cents=200000,
        amount_financed_cents=3000001, collateral_value_cents=2500000,
    )
    assert application["ltv_pct"] == 120.00
    assert application["demotion_count"] == 0
    assert application["assigned_tier_code"] == "T1"

    response = api.create_contract(
        {
            "application_id": application["id"],
            "contract_apr_bps": 749,
            "contract_date": CLOCK_START,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ADVANCE_LIMIT_EXCEEDED.value, 422)
    assert read_application(application["id"])["status"] == "APPROVED"


def test_booking_against_a_file_that_is_not_approved_is_refused(api):
    """PRD 3.4: "The application must be in `APPROVED`; a file in any other status —
    including one already `CONTRACTED` — is refused with
    `ERR_APPLICATION_NOT_APPROVED` (HTTP 409)."

    Design: Corner/errors/contract_from_non_approved_application_returns_application_not_approved
    """
    program = setup_program()
    application = submit_application(program["dealer_id"], applicant_reference="APP-na")

    response = api.create_contract(
        {
            "application_id": application["id"],
            "contract_apr_bps": 749,
            "contract_date": CLOCK_START,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value, 409)

    assert read_application(application["id"])["status"] == "SUBMITTED"
    _, meta = validate_paginated(
        api.list_contracts(ADMIN, params={"application_id": application["id"]})
    )
    assert meta["total_count"] == 0


def test_contract_reaches_docs_verified_only_when_the_last_type_is_verified(api):
    """PRD 3.4: "When the document's `doc_type` is in the contract's
    `required_doc_types`, the contract's `verified_doc_count` increases by one; and
    when that verification brings every type in `required_doc_types` to `VERIFIED`,
    the contract advances `PENDING_DOCS → DOCS_VERIFIED`, with `verified_doc_count`
    then equal to the number of required types."
    PRD 3.5: "The contract's `funding_status` must be `DOCS_VERIFIED`, meaning every
    type in `required_doc_types` has a document in `VERIFIED`; otherwise
    `ERR_DOCS_NOT_VERIFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/funding_requires_all_required_documents_verified
    """
    program = setup_program()
    booked = setup_booked_contract(program, doc_prefix="IMG-dv")
    contract_id = booked["contract"]["id"]
    documents = booked["documents"]

    verify_document(documents["RETAIL_INSTALLMENT_CONTRACT"]["id"])
    partial = read_contract(contract_id)
    assert partial["funding_status"] == "PENDING_DOCS"
    assert partial["verified_doc_count"] == 1

    validate_error(
        api.fund_contract(contract_id, {"funding_date": CLOCK_START}, FUNDER),
        ApiErrorId.ERR_DOCS_NOT_VERIFIED.value, 409,
    )

    verify_document(documents["TITLE_APPLICATION"]["id"])
    verify_document(documents["INSURANCE_BINDER"]["id"])

    ready = read_contract(contract_id)
    assert ready["funding_status"] == "DOCS_VERIFIED"
    assert ready["verified_doc_count"] == len(BASE_REQUIRED_DOC_TYPES)


def test_rejecting_a_verified_required_document_reverts_the_contract(api):
    """PRD 3.4: "The contract's `doc_defect_count` increases by one — and never
    decreases, because it is a permanent record of how much rework this package took,
    and §3.7 reads it."
    PRD 3.4: "When the rejected document had been `VERIFIED`, the contract's
    `verified_doc_count` decreases by one; and when that document's `doc_type` is in
    `required_doc_types`, the contract reverts `DOCS_VERIFIED → PENDING_DOCS`."
    PRD 3.4: "The document moves to `REJECTED` and its `defect_code` is set to the
    supplied value, or to the sentinel `UNSPECIFIED_DEFECT` when none was supplied"

    Design: Difficulty/cross_entity_state_dependency/funding_requires_all_required_documents_verified
    """
    program = setup_program()
    booked = setup_booked_contract(program, doc_prefix="IMG-rev")
    contract_id = booked["contract"]["id"]
    documents = booked["documents"]
    for document in documents.values():
        verify_document(document["id"])
    assert read_contract(contract_id)["funding_status"] == "DOCS_VERIFIED"

    response = api.verify_document(
        documents["RETAIL_INSTALLMENT_CONTRACT"]["id"],
        {"outcome": "REJECT", "defect_code": "MISSING_SIGNATURE"}, FUNDER,
    )
    rejected = validate_success(response, 200)
    assert_document(rejected)
    assert rejected["status"] == "REJECTED"
    assert rejected["defect_code"] == "MISSING_SIGNATURE"

    reverted = read_contract(contract_id)
    assert reverted["funding_status"] == "PENDING_DOCS"
    assert reverted["verified_doc_count"] == len(BASE_REQUIRED_DOC_TYPES) - 1
    assert reverted["doc_defect_count"] == 1

    validate_error(
        api.fund_contract(contract_id, {"funding_date": CLOCK_START}, FUNDER),
        ApiErrorId.ERR_DOCS_NOT_VERIFIED.value, 409,
    )
    assert read_contract(contract_id)["funded_at"] is None
    assert read_dealer(program["dealer_id"])["total_funded_ever_count"] == 0
