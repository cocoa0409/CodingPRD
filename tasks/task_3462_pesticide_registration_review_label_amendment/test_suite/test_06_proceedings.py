"""Cancellation/suspension proceedings: step gates, segregation of duties at
order issuance, the duplicate-open constraint, FIXED vs DEPLETION stocks
deadlines, and reinstatement gates (PRD §3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_iso_instant_equal,
    assert_proceeding,
    create_registered_product,
    get_product,
    get_proceeding,
    hold_hearing,
    initiate_proceeding,
    issue_cancellation_order,
    issue_suspension_order,
    make_fixed_order_payload,
    make_proceeding_payload,
    make_vacatur_payload,
    reinstate_product,
    set_clock,
    setup_suspended_product,
    vacate_proceeding,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
REVIEWER_B = TEST_USERS["reviewer_2_headers"]


def test_proceeding_hear_on_suspension_returns_invalid_step(api):
    """PRD §3.8: "the reviewer first holds the hearing — hearings exist only for
    cancellations, and hearing a suspension or a proceeding no longer `INITIATED`
    fails `ERR_PROCEEDING_INVALID_STEP`"

    Design: Corner/state_machines/proceeding_hear_on_suspension_returns_invalid_step
    """
    ctx = create_registered_product()
    proceeding = initiate_proceeding(ctx["product"]["id"], "SUSPENSION",
                                     "IMMINENT_HAZARD", REVIEWER)
    resp = api_client.hear_proceeding(proceeding["id"], REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_PROCEEDING_INVALID_STEP)

    proceeding = get_proceeding(proceeding["id"])
    assert proceeding["status"] == "INITIATED"
    assert proceeding["hearing_held_at"] is None


def test_proceeding_second_vacate_returns_invalid_step(api):
    """PRD §3.8: "A reviewer vacates a proceeding in `INITIATED`, `HEARING_HELD`,
    or `EFFECTIVE`, supplying `vacatur_reason`; vacating a proceeding in any other
    status fails `ERR_PROCEEDING_INVALID_STEP`."

    Design: Corner/state_machines/proceeding_second_vacate_returns_invalid_step
    """
    ctx = create_registered_product()
    proceeding = initiate_proceeding(ctx["product"]["id"], "CANCELLATION",
                                     "RISK_FINDING", REVIEWER)
    vacate_proceeding(proceeding["id"], reviewer_headers=REVIEWER,
                      vacatur_reason="settled before hearing")

    resp = api_client.vacate_proceeding(
        proceeding["id"], make_vacatur_payload(vacatur_reason="second attempt"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_PROCEEDING_INVALID_STEP)

    assert get_proceeding(proceeding["id"])["status"] == "VACATED"
    # Nothing ever took effect, so the product was never cancelled.
    assert get_product(ctx["product"]["id"])["status"] == "REGISTERED"


def test_proceeding_initiator_cannot_issue_own_order(api):
    """PRD §3.8: "segregation of duties applies at the order: the issuing
    reviewer's `X-User-ID` must differ from the proceeding's `initiated_by_ref`,
    else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/validations/proceeding_initiator_cannot_issue_own_order
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    proceeding = initiate_proceeding(product_id, "CANCELLATION", "RISK_FINDING",
                                     REVIEWER)
    hold_hearing(proceeding["id"], REVIEWER)

    resp = api_client.issue_order(
        proceeding["id"], REVIEWER, payload=make_fixed_order_payload(100))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    assert get_proceeding(proceeding["id"])["status"] == "HEARING_HELD"

    issued = issue_cancellation_order(proceeding["id"], issuer_headers=REVIEWER_B,
                                      authorized_units=100, stocks_method="FIXED")
    assert issued["status"] == "EFFECTIVE"
    assert get_product(product_id)["status"] == "CANCELLED"


def test_second_open_proceeding_returns_duplicate_open_proceeding(api):
    """PRD §3.8: "The manual route admits at most one non-terminal proceeding per
    product — while another is `INITIATED`, `HEARING_HELD`, or `EFFECTIVE`, the
    create fails `ERR_DUPLICATE_OPEN_PROCEEDING`"

    Design: Corner/errors/second_open_proceeding_returns_duplicate_open_proceeding
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    first = initiate_proceeding(product_id, "CANCELLATION", "RISK_FINDING", REVIEWER)

    resp = api_client.create_proceeding(
        make_proceeding_payload(product_id, "SUSPENSION", "IMMINENT_HAZARD"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_PROCEEDING)

    assert get_proceeding(first["id"])["status"] == "INITIATED"
    rows, meta = validate_paginated(
        api_client.list_proceedings(REVIEWER, params={"product_id": product_id}))
    assert meta["total_count"] == 1 and rows[0]["id"] == first["id"]


def test_reinstate_blocked_while_proceeding_effective(api):
    """PRD §3.8: "Two blockers refuse with `ERR_REINSTATEMENT_BLOCKED`: any
    proceeding of the product still `EFFECTIVE`, and any data call-in of any case
    of the product still in `ISSUED`, `RESPONDED`, `DEFICIENT`, or `DELINQUENT`."

    Design: Corner/validations/reinstate_blocked_while_proceeding_effective
    """
    ctx = setup_suspended_product()
    product_id = ctx["product"]["id"]
    resp = api_client.reinstate_product(product_id, REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_BLOCKED)
    assert get_product(product_id)["status"] == "SUSPENDED"


def test_product_reinstate_when_registered_returns_not_suspended(api):
    """PRD §3.8: "A reviewer reinstates a product that is `SUSPENDED`; calling it
    on a product in any other status fails `ERR_PRODUCT_NOT_SUSPENDED`."

    Design: Corner/state_machines/product_reinstate_when_registered_returns_not_suspended
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    resp = api_client.reinstate_product(product_id, REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SUSPENDED)
    assert get_product(product_id)["status"] == "REGISTERED"


def test_existing_stocks_fixed_vs_depletion_deadline(api):
    """PRD §3.8: "Under `FIXED`, the deadlines are statutory and independent of
    quantity: `allow_sale_until` is 365 days after `effective_at`, and
    `allow_use_until` is 730 days after."
    PRD §3.8: "Under `DEPLETION`, the sale window in days is the authorized units
    divided by the declared monthly depletion rate, multiplied by thirty, and
    rounded up to a whole number of days; `allow_sale_until` is that many days
    after `effective_at`, and `allow_use_until` is exactly twice that many days."

    Design: Difficulty/dual_variant_calc/existing_stocks_fixed_vs_depletion_deadline
    """
    ctx1 = create_registered_product(product_overrides={"product_name": "Nominex G"})
    ctx2 = create_registered_product(product_overrides={"product_name": "Nominex WP"})
    set_clock("2027-03-01T00:00:00Z")

    pr_fixed = initiate_proceeding(ctx1["product"]["id"], "CANCELLATION",
                                   "RISK_FINDING", REVIEWER)
    hold_hearing(pr_fixed["id"], REVIEWER)
    pr_depl = initiate_proceeding(ctx2["product"]["id"], "CANCELLATION",
                                  "RISK_FINDING", REVIEWER)
    hold_hearing(pr_depl["id"], REVIEWER)

    issue_cancellation_order(pr_fixed["id"], issuer_headers=REVIEWER_B,
                             authorized_units=12000, stocks_method="FIXED")
    issue_cancellation_order(pr_depl["id"], issuer_headers=REVIEWER_B,
                             authorized_units=12000, stocks_method="DEPLETION",
                             depletion_rate_units_per_month=2000)

    fixed = get_proceeding(pr_fixed["id"])
    assert_proceeding(fixed)
    assert fixed["status"] == "EFFECTIVE"
    assert_iso_instant_equal(fixed["effective_at"], "2027-03-01T00:00:00Z",
                             "effective_at")
    assert_iso_instant_equal(fixed["allow_sale_until"], "2028-02-29T00:00:00Z",
                             "allow_sale_until")
    assert_iso_instant_equal(fixed["allow_use_until"], "2029-02-28T00:00:00Z",
                             "allow_use_until")

    depl = get_proceeding(pr_depl["id"])
    assert_proceeding(depl)
    assert depl["status"] == "EFFECTIVE"
    assert_iso_instant_equal(depl["effective_at"], "2027-03-01T00:00:00Z",
                             "effective_at")
    # ceil(12000 / 2000 * 30) = 180-day sale window; use window exactly twice.
    assert_iso_instant_equal(depl["allow_sale_until"], "2027-08-28T00:00:00Z",
                             "allow_sale_until")
    assert_iso_instant_equal(depl["allow_use_until"], "2028-02-24T00:00:00Z",
                             "allow_use_until")
