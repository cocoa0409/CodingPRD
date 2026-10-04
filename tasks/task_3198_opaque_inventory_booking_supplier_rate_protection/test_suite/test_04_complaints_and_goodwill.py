"""Complaint intake, resolution rules, and goodwill handling tests."""
from test_helpers import (
    ADMIN,
    CS,
    ApiErrorId,
    api_client,
    create_customer,
    get_success_data,
    make_customer_headers,
    open_complaint,
    resolve_case,
    setup_accepted_booking,
    setup_inventory,
    place_bid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDuplicateComplaint:
    def test_duplicate_open_complaint_on_same_booking_returns_409(self):
        """PRD §3.5: "The case is created against an existing booking owned by
        the calling customer, and the platform enforces at most one live case
        per booking: if an `OPEN` or `UNDER_REVIEW` case already exists for
        that booking, creation is rejected with `ERR_DUPLICATE_COMPLAINT`
        (HTTP 409)."

        Design: Corner/endpoints/duplicate_open_complaint_on_same_booking_returns_409
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB34")
        first = open_complaint(customer, booking, category="OTHER", description="first")
        assert first["status"] == "OPEN"

        resp = api_client.create_complaint_case(
            {
                "booking_id": booking["id"],
                "category": "DISSATISFIED_REVEAL",
                "description": "second",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPLAINT)
        rows, meta = validate_paginated(
            api_client.list_complaint_cases(ADMIN, params={"booking_id": booking["id"]})
        )
        assert len(rows) == 1


class TestComplaintTerminalStates:
    def test_rejected_case_cannot_restart_review_and_new_case_allowed(self):
        """PRD §3.5: "The case is created against an existing booking owned by
        the calling customer, and the platform enforces at most one live case
        per booking: if an `OPEN` or `UNDER_REVIEW` case already exists for
        that booking, creation is rejected with `ERR_DUPLICATE_COMPLAINT`
        (HTTP 409)."
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/complaint_case_reopen_after_rejected_is_impossible
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB24")
        case = open_complaint(customer, booking, category="OTHER", description="noise")
        get_success_data(api_client.start_review_complaint_case(case["id"], CS))
        rejected = get_success_data(api_client.reject_complaint_case(case["id"], CS))
        assert rejected["status"] == "REJECTED"

        resp = api_client.start_review_complaint_case(case["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # A REJECTED case is terminal, so it does not trip the duplicate rule.
        resp = api_client.create_complaint_case(
            {"booking_id": booking["id"], "category": "OTHER", "description": "second attempt"},
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "OPEN"


class TestDissatisfiedRevealRule:
    def test_dissatisfied_reveal_cannot_resolve_full_refund(self):
        """PRD §3.5: "Resolution requires the operator to supply a `resolution`
        of `GOODWILL_CREDIT` or `FULL_REFUND`, with one hard rule rooted in the
        non-refundable terms: a case in category `DISSATISFIED_REVEAL` — the
        customer simply dislikes the revealed property — must resolve as
        `GOODWILL_CREDIT` and may never earn a `FULL_REFUND`."

        Design: Corner/state_machines/resolve_dissatisfied_reveal_with_full_refund_is_rejected
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB22")
        case = open_complaint(customer, booking, category="DISSATISFIED_REVEAL",
                              description="expected a nicer brand")
        get_success_data(api_client.start_review_complaint_case(case["id"], CS))

        resp = api_client.resolve_complaint_case(case["id"], {"resolution": "FULL_REFUND"}, CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        refreshed = get_success_data(api_client.get_complaint_case(case["id"], ADMIN))
        assert refreshed["status"] == "UNDER_REVIEW"
        assert refreshed["resolution"] == "NONE"


class TestGoodwillAmountBounds:
    def test_goodwill_must_be_strictly_between_zero_and_charged(self):
        """PRD §3.4: "The goodwill path — a `CustomerService` operator granting
        goodwill on a `CONFIRMED` booking — requires a `RESOLVED` complaint
        case with resolution `GOODWILL_CREDIT` and a `goodwill_credit_cents`
        amount strictly greater than zero and strictly less than the booking's
        `charged_price_cents`; an amount outside that exclusive range is
        rejected with `ERR_INVALID_GOODWILL_AMOUNT` (HTTP 422)."

        Design: Corner/validations/goodwill_amount_must_be_strictly_between_zero_and_charged
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB31")
        assert booking["charged_price_cents"] == 27000
        case = open_complaint(customer, booking, category="DISSATISFIED_REVEAL",
                              description="meh")
        get_success_data(api_client.start_review_complaint_case(case["id"], CS))

        for bad_amount in (27000, 0):
            resp = api_client.resolve_complaint_case(
                case["id"],
                {"resolution": "GOODWILL_CREDIT", "goodwill_credit_cents": bad_amount},
                CS,
            )
            validate_error(resp, ApiErrorId.ERR_INVALID_GOODWILL_AMOUNT)
        refreshed = get_success_data(api_client.get_complaint_case(case["id"], ADMIN))
        assert refreshed["status"] == "UNDER_REVIEW"
