"""Gate arithmetic: money gates, cross-entity evidence, windows and running limits.

Covers the cancellation balance gate of PRD section 3.2, the arrival rate-variance
gate of PRD section 3.2, the interval rules of PRD sections 3.2 and 3.5, the
credit cap of PRD section 2.7, the submit-time documentation rules of PRD section
3.5, and the two-clause settlement rule spanning PRD sections 3.5 and 3.8.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_null_fields,
    assert_page_meta,
    assert_row_count,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)


def test_a_reservation_that_owes_money_cannot_be_cancelled_until_the_line_is_reversed(api):
    """The cancel gate is on the balance, and a pre-arrival charge is legitimately there.

    PRD section 3.7 puts no stay-status gate on a hand-posted line, so a RESERVED
    account may carry a charge before the guest ever appears; PRD section 3.2 then
    requires `balance_amount` to be exactly 0.00 to cancel and refuses anything else
    with ERR_FOLIO_BALANCE_NOT_ZERO. PRD section 2.8 corrects the charge by appending
    a reversal rather than deleting it, which returns the balance to 0.00 and lets the
    identical cancel through while the history stays on the account. PRD section 3.3
    skips a CANCELLED account in every later room-and-tax run.

    Design: Corner/validations/validation_violation_to_error_cancelling_a_folio_that_owes_money
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-CX1",
        guest_name="Kai Osei",
        room_number="801",
        contracted_rate_amount=200.00,
    )
    charge = fx.post_journal_line(
        api,
        bd["id"],
        "MISC_CHARGE",
        75.00,
        headers=FRONT_DESK,
        folio_id=folio["id"],
        memo="Pre-arrival transfer fee",
    )

    validate_error(api.cancel_folio(folio["id"], FRONT_DESK), E.ERR_FOLIO_BALANCE_NOT_ZERO)

    unchanged = fx.read_folio(api, folio["id"])
    assert_fields(unchanged, {"stay_status": "RESERVED"})
    assert_money(unchanged["balance_amount"], 75.00, "balance_amount after the refusal")

    get_success_data(api.reverse_journal_posting(charge["id"], AUDITOR))
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 0.00, "balance_amount"
    )

    cancelled = validate_success(api.cancel_folio(folio["id"], FRONT_DESK))
    assert_fields(cancelled, {"stay_status": "CANCELLED"})
    assert_row_count(
        fx.list_postings(api, folio_id=folio["id"]), 2, "journal lines after the cancel"
    )

    day = fx.post_room_and_tax(api, bd["id"])
    assert_int(day["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "CANCELLED"})


def test_a_balance_that_nets_to_exactly_zero_cancels_on_the_first_attempt(api):
    """An untouched reservation and an offset one both satisfy the exact-zero comparison.

    PRD section 3.2 admits a cancellation when `balance_amount` is exactly 0.00, and PRD
    section 3.7 derives that balance as the signed sum of the account's lines, so an
    account whose charge has been fully tendered nets to zero and passes the same gate
    despite having history — it reads SETTLED by the strict ordering of PRD section 3.7.
    Cancellation increments the account's `version`, and PRD section 3.3 turns neither
    cancelled reservation into a no-show, leaving the day's revenue at 0.00.

    Design: Corner/validations/validation_satisfaction_to_pass_a_zero_balance_reservation_cancels_cleanly
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    clean = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-OK1",
        guest_name="Lia Grant",
        room_number="901",
        contracted_rate_amount=200.00,
    )
    offset = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-OK2",
        guest_name="Moe Vance",
        room_number="902",
        contracted_rate_amount=200.00,
    )
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 33.33, folio_id=offset["id"], memo="Deposit fee"
    )
    get_success_data(
        api.post_payment(
            offset["id"],
            f.build_payment_payload(bd["id"], 33.33, memo="Deposit fee refunded"),
            FRONT_DESK,
        )
    )

    cancelled = validate_success(api.cancel_folio(clean["id"], FRONT_DESK))
    assert_fields(cancelled, {"stay_status": "CANCELLED"})
    assert_money(cancelled["balance_amount"], 0.00, "balance_amount")
    assert_int(cancelled["version"], 2, "version after the cancel")

    settled = fx.read_folio(api, offset["id"])
    assert_money_fields(
        settled,
        {
            "charges_total_amount": 33.33,
            "credits_total_amount": -33.33,
            "balance_amount": 0.00,
        },
    )
    assert_fields(settled, {"settlement_status": "SETTLED"})
    assert_fields(
        validate_success(api.cancel_folio(offset["id"], FRONT_DESK)),
        {"stay_status": "CANCELLED"},
    )

    rows, meta = validate_paginated(
        api.list_folios(FRONT_DESK, property_id=prop["id"], stay_status="CANCELLED")
    )
    assert_row_count(rows, 2, "cancelled accounts")
    assert_page_meta(meta, total_count=2)

    day = fx.post_room_and_tax(api, bd["id"])
    assert_money(day["total_revenue_amount"], 0.00, "total_revenue_amount")
    for folio in (clean, offset):
        assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "CANCELLED"})


def test_a_deep_discount_arrives_only_once_its_rate_override_is_active(api):
    """A PENDING waiver satisfies nothing; the APPROVE review unblocks the identical call.

    PRD section 3.2 derives `rate_variance_pct` from the contracted rate against the
    property's rack rate alone, and refuses an arrival whose absolute variance strictly
    exceeds `rate_variance_tolerance_pct` unless an ACTIVE RATE_OVERRIDE document names
    the account and covers the arrival day, with ERR_RATE_VARIANCE_UNAUTHORIZED. PRD
    section 3.2 states that a PENDING document satisfies no gate whatsoever and that
    revocation makes every later evaluation treat the paperwork as absent, while a
    variance at or below the tolerance needs no paperwork at all.

    Design: Corner/validations/validation_cross_entity_validation_deep_discount_needs_an_active_rate_override
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api, rate_variance_tolerance_pct=95.0)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RV1",
        guest_name="Nils Braga",
        room_number="1001",
        contracted_rate_amount=5.00,
        rate_plan_code="STAFF",
        market_segment="CORPORATE",
    )
    # round((5.00 - 200.00) * 100 / 200.00, 2) == -97.50, whose magnitude beats 95.0
    assert_money(folio["rate_variance_pct"], -97.50, "rate_variance_pct")
    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="RATE_OVERRIDE",
        authorized_by_name="P. Halvorsen",
        document_reference="RO-2026-0801",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-05",
        folio_id=folio["id"],
        authorized_rate_amount=5.00,
    )
    assert_fields(document, {"status": "PENDING"})

    validate_error(api.check_in(folio["id"], FRONT_DESK), E.ERR_RATE_VARIANCE_UNAUTHORIZED)
    assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "RESERVED"})

    reviewed = validate_success(
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), REVENUE_MANAGER
        )
    )
    assert_fields(reviewed, {"status": "ACTIVE"})
    assert reviewed["reviewed_by_user_id"] is not None, (
        "expected reviewed_by_user_id to be stamped, got None"
    )

    assert_fields(
        validate_success(api.check_in(folio["id"], FRONT_DESK)), {"stay_status": "IN_HOUSE"}
    )

    assert_fields(
        validate_success(api.revoke_authorization_document(document["id"], CONTROLLER)),
        {"status": "REVOKED"},
    )
    bare = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RV2",
        guest_name="Ola Reid",
        room_number="1002",
        contracted_rate_amount=5.00,
        rate_plan_code="STAFF",
        market_segment="CORPORATE",
    )
    validate_error(api.check_in(bare["id"], FRONT_DESK), E.ERR_RATE_VARIANCE_UNAUTHORIZED)

    inside = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RV3",
        guest_name="Pia Nunes",
        room_number="1003",
        contracted_rate_amount=15.00,
        rate_plan_code="STAFF",
        market_segment="CORPORATE",
    )
    # round((15.00 - 200.00) * 100 / 200.00, 2) == -92.50, inside the tolerance
    assert_money(inside["rate_variance_pct"], -92.50, "rate_variance_pct")
    assert_fields(
        validate_success(api.check_in(inside["id"], FRONT_DESK)), {"stay_status": "IN_HOUSE"}
    )


def test_a_backwards_window_is_refused_on_the_batch_and_the_single_day_document_stands(api):
    """One error code, two entities, two strictness rules — strictly before versus at-or-before.

    PRD section 3.5 requires a batch's `shift_start_at` to be strictly before its
    `shift_end_at` and refuses anything else with ERR_SHIFT_WINDOW_INVALID (HTTP 422),
    so equal endpoints fail. PRD section 3.2 guards paperwork with the same code but a
    looser rule — `valid_from_date` at or before `valid_to_date` — so a single-day
    interval is well formed while a backwards one is not. Neither refusal creates a row.

    Design: Corner/validations/validation_temporal_validation_backwards_windows_are_refused_on_both_entities
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-TW1",
        guest_name="Ola Frisk",
        room_number="1101",
        contracted_rate_amount=200.00,
    )
    manager = make_outlet_manager_headers(outlet["id"])

    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                100.00,
                shift_start_at="2026-08-01T22:00:00.000Z",
                shift_end_at="2026-08-01T14:00:00.000Z",
            ),
            manager,
        ),
        E.ERR_SHIFT_WINDOW_INVALID,
    )
    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                100.00,
                shift_start_at="2026-08-01T14:00:00.000Z",
                shift_end_at="2026-08-01T14:00:00.000Z",
            ),
            manager,
        ),
        E.ERR_SHIFT_WINDOW_INVALID,
    )
    rows, meta = validate_paginated(
        api.list_settlement_batches(AUDITOR, business_date_id=bd["id"])
    )
    assert_empty(rows, "settlement batches after two rejected windows")
    assert_page_meta(meta, total_count=0)

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                "COMP_ROOM",
                valid_from_date="2026-08-05",
                valid_to_date="2026-08-01",
                folio_id=folio["id"],
                authorized_by_name="P. Halvorsen",
                document_reference="CMP-2026-0801",
            ),
            FRONT_DESK,
        ),
        E.ERR_SHIFT_WINDOW_INVALID,
    )
    same_day = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-01",
        folio_id=folio["id"],
        authorized_by_name="P. Halvorsen",
        document_reference="CMP-2026-0802",
    )
    assert_fields(same_day, {"status": "PENDING"})
    assert_fields(
        same_day, {"valid_from_date": "2026-08-01", "valid_to_date": "2026-08-01"}
    )

    ordered = fx.create_settlement_batch(
        api,
        bd["id"],
        outlet["id"],
        100.00,
        shift_start_at="2026-08-01T14:00:00.000Z",
        shift_end_at="2026-08-01T22:00:00.000Z",
    )
    assert_fields(ordered, {"status": "DECLARED"})


def test_two_individually_legal_charges_breach_the_credit_cap_together(api):
    """The cap is on the running balance, so 300.00 twice is refused where 300.00 once is not.

    PRD section 2.7 caps the balance a guest account may hold after a charge at its
    `credit_limit_amount`, which defaults to 500.00, and the catalogue of PRD section 4
    answers a breach with ERR_CREDIT_LIMIT_EXCEEDED (HTTP 409). PRD section 3.7 derives
    that balance as a running signed sum, so the cap tracks the live balance rather than
    lifetime charges: landing exactly on the limit is allowed, one cent past it is not,
    and a tender that brings the balance back down makes room for a further charge. A
    refused line is never written.

    Design: Corner/validations/validation_aggregate_validation_two_legal_charges_breach_the_credit_limit_together
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-CL1",
        guest_name="Pim Aalto",
        room_number="1201",
        contracted_rate_amount=200.00,
    )
    assert_money(folio["credit_limit_amount"], 500.00, "the default credit_limit_amount")
    fx.check_in(api, folio["id"])
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 300.00, folio_id=folio["id"], memo="Spa package"
    )

    def hand_post(amount, memo):
        return api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"], "MISC_CHARGE", amount, folio_id=folio["id"], memo=memo
            ),
            FRONT_DESK,
        )

    validate_error(hand_post(300.00, "Second spa package"), E.ERR_CREDIT_LIMIT_EXCEEDED)
    refused = fx.read_folio(api, folio["id"])
    assert_money_fields(
        refused, {"charges_total_amount": 300.00, "balance_amount": 300.00}
    )
    assert_row_count(
        fx.list_postings(api, folio_id=folio["id"]), 1, "journal lines after the refusal"
    )

    get_success_data(hand_post(200.00, "Exactly to the limit"))
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 500.00, "balance_amount"
    )

    validate_error(hand_post(0.01, "One cent past the limit"), E.ERR_CREDIT_LIMIT_EXCEEDED)
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 500.00, "balance_amount"
    )

    get_success_data(
        api.post_payment(
            folio["id"], f.build_payment_payload(bd["id"], 300.00), FRONT_DESK
        )
    )
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 200.00, "balance_amount"
    )

    get_success_data(hand_post(250.00, "Room made by the tender"))
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 450.00, "balance_amount"
    )


def test_only_a_rate_error_allowance_must_name_its_supporting_paperwork(api):
    """The extra requirement rides on one enum value and bites only at submit.

    PRD section 3.5 leaves `reason_code` and `supporting_document_reference` optional at
    creation and enforces two rules at submit and nowhere else: a still-null
    `reason_code` is refused with ERR_REASON_CODE_REQUIRED and a `reason_code` of
    RATE_ERROR with an empty or absent `supporting_document_reference` is refused with
    ERR_SUPPORTING_DOCUMENT_REQUIRED, both HTTP 422. A submit may replace those fields
    on the way in, and a failed submit stores nothing — the draft keeps its null reason
    code. An allowance already carrying GUEST_DISPUTE submits with an empty body.

    Design: Corner/validations/validation_conditional_validation_rate_error_allowances_need_a_document_reference
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-AL1",
        guest_name="Quin Hale",
        room_number="1301",
        contracted_rate_amount=380.00,
        rate_plan_code="SUITE",
        credit_limit_amount=2000.00,
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])

    def bare_draft(memo_free_payload):
        return get_success_data(api.create_allowance(memo_free_payload, FRONT_DESK))

    bare_payload = f.without(
        f.build_allowance_payload(folio["id"], bd["id"], 40.00), "reason_code", "narrative"
    )
    bare = bare_draft(bare_payload)
    assert_fields(bare, {"status": "DRAFT"})
    assert_null_fields(bare, ["reason_code"])
    dispute = fx.create_allowance(
        api,
        folio["id"],
        bd["id"],
        40.00,
        reason_code="GUEST_DISPUTE",
        narrative="Noise from adjacent suite.",
    )
    third = bare_draft(dict(bare_payload))

    validate_error(
        api.submit_allowance(
            bare["id"],
            AUDITOR,
            {"reason_code": "RATE_ERROR", "narrative": "Wrong rate plan loaded"},
        ),
        E.ERR_SUPPORTING_DOCUMENT_REQUIRED,
    )
    still_draft = fx.read_allowance(api, bare["id"])
    assert_fields(still_draft, {"status": "DRAFT"})
    assert_null_fields(still_draft, ["reason_code"])

    submitted = validate_success(
        api.submit_allowance(
            bare["id"],
            AUDITOR,
            {
                "reason_code": "RATE_ERROR",
                "narrative": "Wrong rate plan loaded",
                "supporting_document_reference": "RATE-FIX-77",
            },
        )
    )
    assert_fields(submitted, {"status": "SUBMITTED", "reason_code": "RATE_ERROR"})

    assert_fields(
        validate_success(api.submit_allowance(dispute["id"], AUDITOR)),
        {"status": "SUBMITTED", "reason_code": "GUEST_DISPUTE"},
    )

    validate_error(api.submit_allowance(third["id"], AUDITOR), E.ERR_REASON_CODE_REQUIRED)
    validate_error(
        api.submit_allowance(
            third["id"],
            AUDITOR,
            {"reason_code": "RATE_ERROR", "supporting_document_reference": ""},
        ),
        E.ERR_SUPPORTING_DOCUMENT_REQUIRED,
    )
    assert_fields(fx.read_allowance(api, third["id"]), {"status": "DRAFT"})


def test_settlement_resolution_can_only_be_judged_after_reconciliation_has_run(api):
    """The coverage clause fires at verify-settlements, the resolution clause at balance.

    PRD section 3.8 checks mandatory coverage before it reconciles anything — every
    ACTIVE outlet whose `requires_shift_settlement` is true must have declared at least
    one batch for the day, else the whole run fails with ERR_SETTLEMENTS_UNRESOLVED — and
    only once it has stamped each batch's `system_amount` and `variance_amount` can the
    balancing step of PRD section 3.8 ask whether any batch is still unresolved. PRD
    section 3.5 reconciles a batch with no matching closed check to a system amount of
    0.00, flags it because the variance strictly exceeds the tolerance, and keeps the
    absolute variance visible on the day even after PRD section 3.5 lets management accept
    it. A SUSPENDED outlet is no longer a mandatory settler.

    Design: Corner/validations/validation_cascading_validation_settlement_resolution_can_only_be_judged_after_reconciliation
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api, settlement_variance_tolerance_amount=5.00)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bd1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    bd2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    batch = fx.create_settlement_batch(
        api,
        bd2["id"],
        outlet["id"],
        160.48,
        shift_start_at="2026-08-02T14:00:00.000Z",
        shift_end_at="2026-08-02T22:00:00.000Z",
    )
    for day in (bd1, bd2):
        fx.post_room_and_tax(api, day["id"])
        fx.seal_charges(api, day["id"])
    sealed_version = fx.business_date_version(api, bd1["id"])

    validate_error(api.verify_settlements(bd1["id"], AUDITOR), E.ERR_SETTLEMENTS_UNRESOLVED)
    uncovered = fx.read_business_date(api, bd1["id"])
    assert_fields(uncovered, {"status": "CHARGES_SEALED"})
    assert_int(uncovered["version"], sealed_version, "version after the refused run")

    assert_fields(
        validate_success(api.verify_settlements(bd2["id"], AUDITOR)),
        {"status": "SETTLEMENT_REVIEW"},
    )
    reconciled = fx.read_batch(api, batch["id"])
    assert_fields(reconciled, {"status": "VARIANCE_FLAGGED"})
    assert_money_fields(
        reconciled, {"system_amount": 0.00, "variance_amount": 160.48}
    )
    reviewed_day = fx.read_business_date(api, bd2["id"])
    assert_int(
        reviewed_day["unresolved_settlement_batch_count"],
        1,
        "unresolved_settlement_batch_count",
    )
    assert_money(
        reviewed_day["settlement_variance_total_amount"],
        160.48,
        "settlement_variance_total_amount",
    )

    validate_error(
        api.balance_business_date(bd2["id"], AUDITOR), E.ERR_SETTLEMENTS_UNRESOLVED
    )

    assert_fields(
        validate_success(api.accept_variance(batch["id"], REVENUE_MANAGER)),
        {"status": "ACCEPTED_WITH_VARIANCE"},
    )
    accepted_day = fx.read_business_date(api, bd2["id"])
    assert_int(
        accepted_day["unresolved_settlement_batch_count"],
        0,
        "unresolved_settlement_batch_count",
    )
    assert_money(
        accepted_day["settlement_variance_total_amount"],
        160.48,
        "settlement_variance_total_amount",
    )
    assert_fields(
        validate_success(api.balance_business_date(bd2["id"], AUDITOR)),
        {"status": "BALANCED"},
    )

    assert_fields(
        validate_success(api.suspend_outlet(outlet["id"], ADMIN)), {"status": "SUSPENDED"}
    )
    assert_fields(
        validate_success(api.verify_settlements(bd1["id"], AUDITOR)),
        {"status": "SETTLEMENT_REVIEW"},
    )
