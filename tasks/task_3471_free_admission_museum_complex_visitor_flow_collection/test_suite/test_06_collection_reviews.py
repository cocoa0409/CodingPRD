"""Collections-committee review: the deaccession-execute cascade, review-kind
field pairing, segregation of duties, review OCC, terminal lockdown, the
active-loan gate, and list pagination (PRD §3.6, §3.5, §2.6, §2.3, §2.8)."""

from test_helpers import (
    ApiErrorId,
    assert_created_at_ascending,
    create_acquisition_review,
    create_deaccession_review,
    create_object,
    create_trust_fund,
    decide_review,
    execute_review,
    expected_final_premium_cents,
    file_condition_report,
    create_agreed_loan,
    get_object,
    make_committee_chair_headers,
    make_curator_headers,
    make_loans_officer_headers,
    reset_clock,
    setup_object_on_active_loan,
    submit_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_deaccession_execute_cascades_loans_and_reports(api):
    """PRD §3.5: "One cascade can interrupt the whole cycle: when a deaccession review executes against the underlying object, every non-terminal agreement for the object — `PROPOSED`, `COUNTERED`, or `AGREED` — is cancelled, and every non-terminal condition report of each cancelled agreement — `SUBMITTED` or `DISPUTED` — is cancelled in turn."
    PRD §3.6: "the object then leaves the collection, moving to `DEACCESSIONED`, or to `REPATRIATED` when the `disposal_method` is `REPATRIATION`"

    Design: Difficulty/transitive_cascade/deaccession_execute_cascades_loans_and_reports
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0005", title="Patent Model Collection", declared_value_cents=80000000
    )
    loan = create_agreed_loan(
        obj["id"], borrower_institution="Science Museum London",
        loan_start_date="2026-10-01", loan_end_date="2027-01-01",
        declared_value_cents=80000000, coverage_type="INSURANCE", courier_required=False,
    )
    report = file_condition_report(
        loan["id"], report_kind="OUTBOUND",
        condition_summary="Stable; crate-ready.", damage_noted=False, as_borrower=True,
    )
    review = create_deaccession_review(
        obj["id"], curator_user_id="cur-9",
        disposal_method="TRANSFER", cultural_property_review_completed=False,
    )
    review = submit_review(review, curator_user_id="cur-9")
    review = decide_review(review, "APPROVED", chair_user_id="chair-2")
    assert review["status"] == "APPROVED"
    assert get_object(obj["id"])["status"] == "PENDING_DEACCESSION"
    executed = execute_review(review["id"])
    assert executed["status"] == "EXECUTED"
    # Link 1: the object leaves the collection.
    assert get_object(obj["id"])["status"] == "DEACCESSIONED"
    # Link 2: the object's departure cancels the AGREED loan.
    loans, _ = validate_paginated(
        api.list_loan_agreements(
            headers=make_loans_officer_headers(), params={"object_id": obj["id"]}
        )
    )
    loan_after = {row["id"]: row for row in loans}[loan["id"]]
    assert loan_after["status"] == "CANCELLED"
    # The premium locked at accept survives the cascade.
    assert loan_after["premium_cents"] == expected_final_premium_cents(80000000, "INSURANCE", False) == 480000
    # Link 3: the loan's cancellation cancels its still-SUBMITTED report.
    reports, _ = validate_paginated(
        api.list_condition_reports(
            headers=make_loans_officer_headers(), params={"loan_id": loan["id"]}
        )
    )
    report_after = {row["id"]: row for row in reports}[report["id"]]
    assert report_after["status"] == "CANCELLED"


def test_cultural_property_safety_beats_referential_rejected(api):
    """PRD §2.8: "When several checks would fail, the earliest check in this order produces the error, and later checks are never evaluated:"
    PRD §2.8: "8. **Cultural property clearance** — deaccession of an object flagged as cultural property requires the cultural-property review to be complete, else `ERR_CULTURAL_PROPERTY_REVIEW_PENDING`." (ordered before item 18)
    PRD §2.8: "18. **Object availability for deaccession and research** — no active loan on the object at deaccession decision or execution (`ERR_OBJECT_ON_ACTIVE_LOAN`), and no visit-visit or visit-loan overlap at research approval (`ERR_RESEARCH_VISIT_CONFLICT`, `ERR_OBJECT_RESERVED_FOR_LOAN`)."

    Design: Difficulty/priority_pair_validation_conflict/cultural_property_safety_beats_referential_rejected
    """
    reset_clock()
    built = setup_object_on_active_loan(
        object_overrides={
            "accession_number": "1978.0110", "title": "Ancestral Funerary Mask",
            "declared_value_cents": 600000000, "is_cultural_property": True,
        },
        borrower_institution="British Museum",
        loan_start_date="2026-10-01", loan_end_date="2027-06-01",
        declared_value_cents=600000000, coverage_type="INSURANCE", courier_required=True,
    )
    obj = built["object"]
    review = create_deaccession_review(
        obj["id"], curator_user_id="cur-3",
        disposal_method="REPATRIATION", cultural_property_review_completed=False,
    )
    review = submit_review(review, curator_user_id="cur-3")
    # Both the cultural-property gate and the active-loan gate would fail; the
    # earlier safety check must be the one reported.
    resp = api.decide_collection_review(
        review["id"], "APPROVED", review["version"],
        headers=make_committee_chair_headers("chair-9"),
    )
    validate_error(resp, ApiErrorId.ERR_CULTURAL_PROPERTY_REVIEW_PENDING)
    after = validate_success(
        api.get_collection_review(review["id"], headers=make_committee_chair_headers("chair-9"))
    )
    assert after["status"] == "SUBMITTED"
    assert get_object(obj["id"])["status"] == "OUT_ON_LOAN"


def test_review_terminal_states_lock_down(api):
    """PRD §3.6: "Rejection needs no further gate and lands the review in terminal `REJECTED`."
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_terminal_states_lock_down
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=1000000)
    review = create_acquisition_review(
        fund["id"], curator_user_id="cur-5",
        proposed_object_title="Daguerreotype Camera", estimated_cost_cents=1000,
    )
    review = submit_review(review, curator_user_id="cur-5")
    rejected = decide_review(review, "REJECTED", chair_user_id="chair-5")
    assert rejected["status"] == "REJECTED"
    resp_submit = api.submit_collection_review(
        rejected["id"], headers=make_curator_headers("cur-5")
    )
    validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)
    resp_decide = api.decide_collection_review(
        rejected["id"], "APPROVED", rejected["version"],
        headers=make_committee_chair_headers("chair-5"),
    )
    validate_error(resp_decide, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(
        api.get_collection_review(rejected["id"], headers=make_committee_chair_headers("chair-5"))
    )
    assert after["status"] == "REJECTED"


def test_review_kind_field_pairing_enforced(api):
    """PRD §3.6: "An `ACQUISITION` review must carry a `fund_id` naming the paying fund, an `estimated_cost_cents` of at least 1, and a `proposed_object_title`, and its `object_id` must be null — the object does not exist yet. A `DEACCESSION` review must carry an `object_id` and a `disposal_method` of `TRANSFER`, `SALE`, `DESTRUCTION`, or `REPATRIATION`, and its `fund_id` must be null. Either pairing violation is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/review_kind_field_pairing_enforced
    """
    reset_clock()
    obj = create_object(accession_number="2026.0020", title="Pairing Object", declared_value_cents=1000000)
    fund = create_trust_fund(appropriation_cents=1000000)
    # ACQUISITION carrying object_id violates the pairing even though the id exists.
    resp_acq = api.create_collection_review(
        {
            "review_kind": "ACQUISITION", "object_id": obj["id"], "fund_id": fund["id"],
            "proposed_object_title": "Should Not Pair", "estimated_cost_cents": 1000,
        },
        headers=make_curator_headers("cur-p"),
    )
    validate_error(resp_acq, ApiErrorId.ERR_INVALID_REQUEST)
    # DEACCESSION carrying fund_id violates the pairing the other way.
    resp_deac = api.create_collection_review(
        {
            "review_kind": "DEACCESSION", "object_id": obj["id"],
            "fund_id": fund["id"], "disposal_method": "TRANSFER",
        },
        headers=make_curator_headers("cur-p"),
    )
    validate_error(resp_deac, ApiErrorId.ERR_INVALID_REQUEST)


def test_segregation_of_duties_same_user_rejected(api):
    """PRD §3.6: "Segregation of duties is absolute: the chair's `X-User-ID` must differ from the review's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — no one decides their own submission."

    Design: Corner/validations/segregation_of_duties_same_user_rejected
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=1000000)
    review = create_acquisition_review(
        fund["id"], curator_user_id="cur-6",
        proposed_object_title="SoD Target", estimated_cost_cents=1000,
    )
    review = submit_review(review, curator_user_id="cur-6")
    # A correctly-roled CommitteeChair whose X-User-ID equals the submitter's.
    resp = api.decide_collection_review(
        review["id"], "APPROVED", review["version"],
        headers=make_committee_chair_headers("cur-6"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    after = validate_success(
        api.get_collection_review(review["id"], headers=make_committee_chair_headers("cur-6"))
    )
    assert after["status"] == "SUBMITTED"


def test_review_decide_stale_version_rejected(api):
    """PRD §2.6: "Deciding a collection review requires `expected_review_version` matching the review's current `version`. If the review's version has advanced since the chair last read it — for example because the curator re-submitted amended terms, which bumps the version — the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412)."

    Design: Corner/validations/review_decide_stale_version_rejected
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=1000000)
    review = create_acquisition_review(
        fund["id"], curator_user_id="cur-8",
        proposed_object_title="OCC Target", estimated_cost_cents=1000,
    )
    assert review["version"] == 1
    review = submit_review(review, curator_user_id="cur-8")
    assert review["version"] == 2, "the submit bumps the version"
    # The chair decides from the pre-submit read: version 1 is stale.
    resp = api.decide_collection_review(
        review["id"], "APPROVED", 1, headers=make_committee_chair_headers("chair-8")
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REVIEW_VERSION)
    after = validate_success(
        api.get_collection_review(review["id"], headers=make_committee_chair_headers("chair-8"))
    )
    assert after["status"] == "SUBMITTED"


def test_active_loan_blocks_deaccession_decide(api):
    """PRD §3.6: "Approval of a deaccession is also blocked while any `ACTIVE` loan exists for the object, failing with `ERR_OBJECT_ON_ACTIVE_LOAN`; loans still in negotiation or merely agreed — `PROPOSED`, `COUNTERED`, or `AGREED` — do not block approval, because execution will cancel them."

    Design: Corner/errors/active_loan_blocks_deaccession_decide
    """
    reset_clock()
    built = setup_object_on_active_loan(
        object_overrides={
            "accession_number": "1979.0201", "title": "Ceremonial Robe",
            "declared_value_cents": 600000000, "is_cultural_property": True,
        },
        borrower_institution="Ethnological Museum",
        loan_start_date="2026-10-01", loan_end_date="2027-06-01",
        declared_value_cents=600000000, coverage_type="INSURANCE", courier_required=True,
    )
    obj = built["object"]
    # The cultural-property gate is satisfied, isolating the active-loan gate.
    review = create_deaccession_review(
        obj["id"], curator_user_id="cur-d",
        disposal_method="REPATRIATION", cultural_property_review_completed=True,
    )
    review = submit_review(review, curator_user_id="cur-d")
    resp = api.decide_collection_review(
        review["id"], "APPROVED", review["version"],
        headers=make_committee_chair_headers("chair-d"),
    )
    validate_error(resp, ApiErrorId.ERR_OBJECT_ON_ACTIVE_LOAN)
    after = validate_success(
        api.get_collection_review(review["id"], headers=make_committee_chair_headers("chair-d"))
    )
    assert after["status"] == "SUBMITTED"
    assert get_object(obj["id"])["status"] == "OUT_ON_LOAN"


def test_collection_reviews_list_paginates_with_envelope_fields(api):
    """PRD §2.3: "List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List results are always sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/collection_reviews_list_paginates_with_envelope_fields
    """
    reset_clock()
    methods = ["TRANSFER", "SALE", "DESTRUCTION"]
    for n in range(3):
        obj = create_object(
            accession_number=f"2026.003{n}", title=f"Page Object {n}", declared_value_cents=1000
        )
        create_deaccession_review(obj["id"], curator_user_id="cur-pg", disposal_method=methods[n])
    page1, meta1 = validate_paginated(
        api.list_collection_reviews(
            headers=make_committee_chair_headers(), params={"limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3, "total_count counts the full filtered set, not the page"
    assert meta1["has_more"] is True
    assert_created_at_ascending(page1)
    page2, meta2 = validate_paginated(
        api.list_collection_reviews(
            headers=make_committee_chair_headers(), params={"limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
