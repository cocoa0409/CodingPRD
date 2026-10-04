"""The recurring review cycle and the delinquency cascade: case opening, cycle
succession, DCI obligation ledger partitioning, referral-driven auto-suspension,
state-registration interaction, and reinstatement (PRD §3.7–§3.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_study,
    api_client,
    apply_state_registration,
    assert_dci_ledger_partition,
    assert_iso_instant_equal,
    complete_case,
    create_dci_study,
    create_manual_review_case,
    create_registered_product,
    expected_next_cycle_opened_at,
    get_dci,
    get_proceeding,
    get_product,
    get_review_case,
    get_state_registration,
    initiate_proceeding,
    issue_suspension_order,
    list_product_review_cases,
    make_state_decision_payload,
    reject_study,
    reinstate_product,
    respond_dci,
    set_clock,
    setup_case_with_dci,
    setup_delinquent_dci,
    vacate_proceeding,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
REVIEWER_B = TEST_USERS["reviewer_2_headers"]
ASSESSOR = TEST_USERS["assessor_1_headers"]
ASSESSOR_B = TEST_USERS["assessor_2_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]


def test_product_review_suspension_reinstatement_cycles(api):
    """PRD §2.4: "Every registration review case still `SCHEDULED` whose
    `opened_at` is at or before the new time opens — `SCHEDULED` → `OPEN` — and
    when the case's product is `REGISTERED` the product moves to `UNDER_REVIEW`"
    PRD §3.7: "Completion stamps `completed_at`, returns the product from
    `UNDER_REVIEW` to `REGISTERED` when no other non-terminal case of the product
    remains, and auto-schedules the next cycle: a fresh `SCHEDULED` case with the
    next `cycle_number`, `opened_at` exactly 5,475 days after the completion
    instant, and `due_at` 180 days after it opens."
    PRD §3.8: "Vacating an `EFFECTIVE` suspension restores nothing at all — the
    product simply remains `SUSPENDED` until reinstatement."
    PRD §3.8: "A clean reinstatement returns the product to `REGISTERED`"

    Design: Difficulty/non_linear_state_machine/product_review_suspension_reinstatement_cycles
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    case1 = ctx["review_case"]

    # Loop 1: the cycle-1 case opens on schedule and completes.
    set_clock("2041-08-28T00:00:00Z")
    case1 = get_review_case(case1["id"])
    assert case1["status"] == "OPEN"
    assert get_product(product_id)["status"] == "UNDER_REVIEW"

    completed = complete_case(case1["id"], REVIEWER)
    assert completed["status"] == "COMPLETED"
    assert_iso_instant_equal(completed["completed_at"], "2041-08-28T00:00:00Z",
                             "completed_at")
    assert get_product(product_id)["status"] == "REGISTERED"
    cases = list_product_review_cases(product_id)
    assert len(cases) == 2
    successor = [c for c in cases if c["cycle_number"] == 2][0]
    assert successor["status"] == "SCHEDULED"
    assert_iso_instant_equal(successor["opened_at"], "2056-08-24T00:00:00Z",
                             "successor.opened_at")
    assert_iso_instant_equal(
        successor["opened_at"], expected_next_cycle_opened_at("2041-08-28T00:00:00Z"),
        "successor.opened_at")

    # Loop 2: suspension, vacatur (no restore), reinstatement.
    proceeding = initiate_proceeding(product_id, "SUSPENSION", "IMMINENT_HAZARD",
                                     REVIEWER)
    issue_suspension_order(proceeding["id"], issuer_headers=REVIEWER_B)
    assert get_proceeding(proceeding["id"])["status"] == "EFFECTIVE"
    assert get_product(product_id)["status"] == "SUSPENDED"

    vacate_proceeding(proceeding["id"], reviewer_headers=REVIEWER,
                      vacatur_reason="order withdrawn pending settlement")
    assert get_proceeding(proceeding["id"])["status"] == "VACATED"
    assert get_product(product_id)["status"] == "SUSPENDED"

    reinstated = reinstate_product(product_id, REVIEWER)
    assert reinstated["status"] == "REGISTERED"


def test_dci_delinquency_auto_suspension_chain(api):
    """PRD §3.7: "When sweep step 2 (§2.4) finds a call-in in `ISSUED`,
    `RESPONDED`, or `DEFICIENT` whose `response_deadline` is now strictly past,
    the call-in becomes `DELINQUENT` and its case — whether that case sits in
    `DCI_PENDING` or `UNDER_REVIEW`, the cascade is identical — becomes
    `REFERRED`, firing a four-hop cascade: unless the product is already
    `SUSPENDED` or `CANCELLED`, the system creates a suspension proceeding with
    `proceeding_type` `SUSPENSION`, `reason` `DCI_DELINQUENCY`, status already
    `EFFECTIVE`, `auto_created` true, `initiated_by_ref` the literal string
    `system`, `effective_at` stamped from the clock, and every existing-stocks
    field null; that effective suspension moves the product from `REGISTERED` or
    `UNDER_REVIEW` to `SUSPENDED`; and the suspension in turn denies each of the
    product's `SUBMITTED` state registrations."

    Design: Difficulty/transitive_cascade/dci_delinquency_auto_suspension_chain
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    sreg = apply_state_registration(product_id, "IA", REGISTRANT)

    bundle = setup_delinquent_dci(product_id, ["TOXICOLOGY"],
                                  response_deadline="2027-02-09T00:00:00Z",
                                  past_deadline="2027-02-10T00:00:00Z")
    # Hop 1: the call-in is delinquent (deadline 2027-02-09 < clock 2027-02-10).
    assert bundle["dci"]["status"] == "DELINQUENT"
    # Hop 2: the case is referred.
    assert bundle["case"]["status"] == "REFERRED"

    # Hop 3: exactly one auto-created EFFECTIVE suspension proceeding.
    rows, meta = validate_paginated(
        api_client.list_proceedings(REVIEWER, params={"product_id": product_id}))
    assert meta["total_count"] == 1
    proceeding = rows[0]
    assert proceeding["auto_created"] is True
    assert proceeding["proceeding_type"] == "SUSPENSION"
    assert proceeding["reason"] == "DCI_DELINQUENCY"
    assert proceeding["status"] == "EFFECTIVE"
    assert proceeding["initiated_by_ref"] == "system"
    assert_iso_instant_equal(proceeding["effective_at"], "2027-02-10T00:00:00Z",
                             "effective_at")
    assert proceeding["existing_stocks_authorized_units"] is None

    # Hop 4: the product suspends and the SUBMITTED state registration denies.
    assert bundle["product"]["status"] == "SUSPENDED"
    assert get_state_registration(sreg["id"])["status"] == "DENIED"


def test_dci_obligation_partition_survives_response_and_rejection(api):
    """PRD §3.7: "`satisfied_study_types` are the required types with at least one
    `ACCEPTED` study bearing this call-in, `pending_study_types` are the required
    types with no accepted study but at least one still `RECEIVED`, and
    `outstanding_study_types` are the remainder. The three sets partition
    `required_study_types` exactly at all times — every required type is in
    precisely one of them."
    PRD §3.7: "a rejection of a linked study while its call-in is `RESPONDED`
    knocks the call-in back to `DEFICIENT`."
    PRD §3.7: "once every call-in of a `DCI_PENDING` case has reached `SATISFIED`,
    the case returns to `UNDER_REVIEW`."

    Design: Difficulty/compensating_invariant/dci_obligation_partition_survives_response_and_rejection
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    bundle = setup_case_with_dci(product_id, ["TOXICOLOGY", "RESIDUE_CHEMISTRY"],
                                 response_deadline="2028-01-01T00:00:00Z")
    dci_id = bundle["dci"]["id"]

    def ledger():
        dci = get_dci(dci_id)
        assert_dci_ledger_partition(dci)
        return dci

    s1 = create_dci_study(dci_id, "TOXICOLOGY", REGISTRANT)
    respond_dci(dci_id, [s1["id"]], REGISTRANT)
    dci = ledger()
    assert dci["status"] == "RESPONDED"
    assert set(dci["satisfied_study_types"]) == set()
    assert set(dci["pending_study_types"]) == {"TOXICOLOGY"}
    assert set(dci["outstanding_study_types"]) == {"RESIDUE_CHEMISTRY"}

    # The compensating hop: rejecting the pending study bounces it to outstanding.
    reject_study(s1["id"], ASSESSOR)
    dci = ledger()
    assert dci["status"] == "DEFICIENT"
    assert set(dci["satisfied_study_types"]) == set()
    assert set(dci["pending_study_types"]) == set()
    assert set(dci["outstanding_study_types"]) == {"TOXICOLOGY", "RESIDUE_CHEMISTRY"}

    s2 = create_dci_study(dci_id, "RESIDUE_CHEMISTRY", REGISTRANT,
                          commodity_code="CORN", field_trial_residue_ppm=0.01)
    s3 = create_dci_study(dci_id, "TOXICOLOGY", REGISTRANT)
    respond_dci(dci_id, [s2["id"], s3["id"]], REGISTRANT)
    dci = ledger()
    assert dci["status"] == "RESPONDED"
    assert set(dci["satisfied_study_types"]) == set()
    assert set(dci["pending_study_types"]) == {"TOXICOLOGY", "RESIDUE_CHEMISTRY"}
    assert set(dci["outstanding_study_types"]) == set()

    accept_study(s2["id"], ASSESSOR_B)
    dci = ledger()
    assert dci["status"] == "RESPONDED", "pending is not yet satisfied"
    assert set(dci["satisfied_study_types"]) == {"RESIDUE_CHEMISTRY"}

    accept_study(s3["id"], ASSESSOR_B)
    dci = ledger()
    assert dci["status"] == "SATISFIED"
    assert set(dci["satisfied_study_types"]) == {"TOXICOLOGY", "RESIDUE_CHEMISTRY"}
    assert get_review_case(bundle["case"]["id"])["status"] == "UNDER_REVIEW"


def test_state_grant_blocked_while_product_under_review(api):
    """PRD §3.9: "it re-checks that the product is `REGISTERED` at decision time,
    not merely at filing (`ERR_PRODUCT_NOT_REGISTERED`)"
    PRD §3.9: "A successful grant stamps `granted_at`, sets `renewal_due_at` 365
    days out, records the payload's `additional_restrictions` array (defaulting to
    empty), and stamps `annual_fee_cents` as the state's base fee"

    Design: Difficulty/cross_entity_state_dependency/state_grant_blocked_while_product_under_review
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    sreg = apply_state_registration(product_id, "IA", REGISTRANT)
    case = create_manual_review_case(product_id, "2027-01-05T00:00:00Z",
                                     "2027-07-04T00:00:00Z", REVIEWER)
    set_clock("2027-01-05T00:00:00Z")  # case opens; product -> UNDER_REVIEW
    assert get_product(product_id)["status"] == "UNDER_REVIEW"

    resp = api_client.decide_state_registration(
        sreg["id"], make_state_decision_payload("GRANT"), STATE_AGENCY)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_REGISTERED)
    assert get_state_registration(sreg["id"])["status"] == "SUBMITTED"

    complete_case(case["id"], REVIEWER)
    assert get_product(product_id)["status"] == "REGISTERED"

    granted = validate_success(api_client.decide_state_registration(
        sreg["id"], make_state_decision_payload("GRANT"), STATE_AGENCY))
    assert granted["status"] == "GRANTED"
    assert_iso_instant_equal(granted["granted_at"], "2027-01-05T00:00:00Z",
                             "granted_at")
    assert_iso_instant_equal(granted["renewal_due_at"], "2028-01-05T00:00:00Z",
                             "renewal_due_at")
    assert granted["annual_fee_cents"] == 18000  # IA base, no RUP surcharge


def test_auto_suspension_proceeding_carries_no_stocks_provision(api):
    """PRD §3.7: "the system creates a suspension proceeding with
    `proceeding_type` `SUSPENSION`, `reason` `DCI_DELINQUENCY`, status already
    `EFFECTIVE`, `auto_created` true, `initiated_by_ref` the literal string
    `system`, `effective_at` stamped from the clock, and every existing-stocks
    field null"
    PRD §3.8: "Recording one requires the proceeding to be `EFFECTIVE` with a
    stocks provision — a disposal against any other proceeding fails
    `ERR_PROCEEDING_INVALID_STEP`."

    Design: Corner/cross_cutting_layers/auto_suspension_proceeding_carries_no_stocks_provision
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    setup_delinquent_dci(product_id, ["TOXICOLOGY"])

    rows, meta = validate_paginated(
        api_client.list_proceedings(REVIEWER, params={"product_id": product_id}))
    assert meta["total_count"] == 1
    proceeding = rows[0]
    assert proceeding["auto_created"] is True
    assert proceeding["proceeding_type"] == "SUSPENSION"
    assert proceeding["reason"] == "DCI_DELINQUENCY"
    assert proceeding["status"] == "EFFECTIVE"
    assert proceeding["initiated_by_ref"] == "system"
    assert proceeding["existing_stocks_authorized_units"] is None
    assert proceeding["stocks_method"] is None
    assert proceeding["allow_sale_until"] is None
    assert proceeding["allow_use_until"] is None

    resp = api_client.record_disposal(
        proceeding["id"], {"units": 10, "method": "DESTRUCTION"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_PROCEEDING_INVALID_STEP)
