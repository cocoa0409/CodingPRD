"""Rejection precedence: which of two simultaneously true refusals wins.

Covers PRD section 2.12 (the fixed rejection precedence, from authentication and
authorization through existence, state, business safety and the fiscal checks
last) together with PRD section 2.1 (role authorization).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_int,
    assert_money,
    assert_null_fields,
)
from test_helpers.test_users import AUDITOR, AUDITOR_2, CONTROLLER, FRONT_DESK

MISSING_FOLIO_ID = "00000000-0000-4000-8000-00000000dead"
MISSING_BUSINESS_DATE_ID = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# The sealed-day state gate against the authorization shortfall on check-out
# ---------------------------------------------------------------------------


def _sealed_day_with_an_inadequate_authorization(api):
    """A CHARGES_SEALED day and a card account whose 10.00 hold cannot cover 217.75."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9001",
        guest_name="Mel Yao",
        room_number="901",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    auth = fx.create_card_authorization(
        api, folio["id"], 10.00, "2026-08-01T08:00:00.000Z"
    )
    fx.post_room_and_tax(api, bd["id"])
    fx.seal_charges(api, bd["id"])
    return prop, bd, folio, auth


def test_the_sealed_day_state_gate_outranks_the_authorization_shortfall(api):
    """Both refusals are 409, so only the code shows which band ran first.

    PRD section 2.12 places endpoint state preconditions ahead of the fiscal checks,
    which run last, so a check-out against a sealed day reports
    ERR_CHARGES_ALREADY_SEALED even though the credit-card sufficiency test of PRD
    section 3.7 is independently violated: the account carries 217.75 against a 10.00
    hold.

    Design: Difficulty/priority_pair_validation_conflict/sealed_date_state_gate_outranks_authorization_shortfall_on_checkout
    """
    _prop, bd, folio, auth = _sealed_day_with_an_inadequate_authorization(api)
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "CHARGES_SEALED"})
    assert_money(fx.read_folio(api, folio["id"])["balance_amount"], 217.75, "balance_amount")
    assert_money(
        fx.read_card_authorization(api, auth["id"])["authorized_amount"],
        10.00,
        "authorized_amount",
    )

    validate_error(
        api.check_out(folio["id"], {"business_date_id": bd["id"]}, FRONT_DESK),
        E.ERR_CHARGES_ALREADY_SEALED,
    )


def test_the_refused_check_out_writes_nothing_at_all(api):
    """A refusal leaves the stay dimension and the journal exactly as they were.

    PRD section 3.7 stamps `actual_checkout_at` and moves the stay dimension only on
    success, and PRD section 2.12 requires a rejected request to have no effect, so
    no LATE_CHECKOUT line is appended either.

    Design: Difficulty/priority_pair_validation_conflict/sealed_date_state_gate_outranks_authorization_shortfall_on_checkout
    """
    _prop, bd, folio, _auth = _sealed_day_with_an_inadequate_authorization(api)

    validate_error(
        api.check_out(folio["id"], {"business_date_id": bd["id"]}, FRONT_DESK),
        E.ERR_CHARGES_ALREADY_SEALED,
    )

    account = fx.read_folio(api, folio["id"])
    assert_fields(account, {"stay_status": "IN_HOUSE"})
    assert_null_fields(account, ["actual_checkout_at"])
    assert_empty(
        validate_success(
            api.list_journal_postings(
                AUDITOR, folio_id=folio["id"], charge_type="LATE_CHECKOUT"
            )
        ),
        "LATE_CHECKOUT lines",
    )


# ---------------------------------------------------------------------------
# Segregation of duties against the approved-amount ceiling
# ---------------------------------------------------------------------------


def _self_submitted_allowance(api):
    """A 100.00 allowance raised and submitted by the same night auditor."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9101",
        guest_name="Noa Zibri",
        room_number="902",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    allowance = fx.submitted_allowance(
        api,
        folio["id"],
        bd["id"],
        100.00,
        AUDITOR,
        reason_code="POSTING_ERROR",
        narrative="Duplicate parking charge.",
    )
    return prop, bd, folio, allowance


def test_self_approval_outranks_the_approved_amount_ceiling(api):
    """The 403 safety refusal wins over the 422 fiscal one, and nothing is granted.

    PRD section 2.12 orders business safety and segregation of duties ahead of the
    business constraints and fiscal checks, so an approver who is the allowance's own
    `requested_by_user_id` gets ERR_SELF_APPROVAL_FORBIDDEN even when the supplied
    `approved_amount` of 500.00 also breaches the 100.00 request ceiling of PRD
    section 3.6. The allowance stays SUBMITTED with nothing stamped, no journal line
    is minted and the account still reads 217.75.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_approved_amount_ceiling_on_allowance_approve
    """
    _prop, _bd, folio, allowance = _self_submitted_allowance(api)

    validate_error(
        api.approve_allowance(allowance["id"], f.build_approve_payload(500.00), AUDITOR),
        E.ERR_SELF_APPROVAL_FORBIDDEN,
    )

    row = fx.read_allowance(api, allowance["id"])
    assert_fields(row, {"status": "SUBMITTED"})
    assert_null_fields(row, ["approved_amount", "approved_by_user_id", "approved_at"])
    assert_empty(
        validate_success(api.list_journal_postings(AUDITOR, allowance_id=allowance["id"])),
        "allowance journal lines",
    )
    assert_money(fx.read_folio(api, folio["id"])["balance_amount"], 217.75, "balance_amount")


def test_the_amount_ceiling_is_live_once_a_different_approver_calls(api):
    """The outranked fiscal rule fires as soon as the safety rule is satisfied.

    PRD section 3.6 caps `approved_amount` at `requested_amount` and refuses a larger
    grant with ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST (HTTP 422), which is exactly what a
    second night auditor receives for the same over-request.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_approved_amount_ceiling_on_allowance_approve
    """
    _prop, _bd, _folio, allowance = _self_submitted_allowance(api)

    validate_error(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(500.00), AUDITOR_2
        ),
        E.ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST,
    )
    assert_fields(fx.read_allowance(api, allowance["id"]), {"status": "SUBMITTED"})


# ---------------------------------------------------------------------------
# Body reference existence against the sealed-day state gate
# ---------------------------------------------------------------------------


def _sealed_day_with_a_posted_account(api):
    """A CHARGES_SEALED day carrying one in-house cash account."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9201",
        guest_name="Oma Bex",
        room_number="903",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    fx.seal_charges(api, bd["id"])
    return prop, bd, folio


def test_an_unresolvable_body_reference_outranks_the_sealed_day_state(api):
    """A 404 from the body-reference band beats the 409 from the state band.

    PRD section 2.12 resolves body references — `property_id`, `business_date_id`,
    then `folio_id` — before it reaches the archived-day refusal, the charge-seal gate
    and the endpoint state preconditions. A hand-posted line naming a well-formed but
    unknown `folio_id` against a sealed day therefore reports ERR_FOLIO_NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/body_existence_outranks_sealed_date_state_on_manual_posting
    """
    _prop, bd, _folio = _sealed_day_with_a_posted_account(api)
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "CHARGES_SEALED"})

    validate_error(
        api.create_journal_posting(
            {
                "business_date_id": bd["id"],
                "folio_id": MISSING_FOLIO_ID,
                "charge_type": "MISC_CHARGE",
                "amount": 25.00,
            },
            AUDITOR,
        ),
        E.ERR_FOLIO_NOT_FOUND,
    )


def test_the_seal_gate_is_live_once_the_body_reference_resolves(api):
    """Naming the real account exposes the outranked charge-seal refusal.

    PRD section 2.12 refuses a charge-bearing write against a day in CHARGES_SEALED
    with ERR_CHARGES_ALREADY_SEALED, and neither attempt leaves a MISC_CHARGE line
    behind.

    Design: Difficulty/priority_pair_validation_conflict/body_existence_outranks_sealed_date_state_on_manual_posting
    """
    _prop, bd, folio = _sealed_day_with_a_posted_account(api)

    validate_error(
        api.create_journal_posting(
            {
                "business_date_id": bd["id"],
                "folio_id": MISSING_FOLIO_ID,
                "charge_type": "MISC_CHARGE",
                "amount": 25.00,
            },
            AUDITOR,
        ),
        E.ERR_FOLIO_NOT_FOUND,
    )
    validate_error(
        api.create_journal_posting(
            {
                "business_date_id": bd["id"],
                "folio_id": folio["id"],
                "charge_type": "MISC_CHARGE",
                "amount": 25.00,
            },
            AUDITOR,
        ),
        E.ERR_CHARGES_ALREADY_SEALED,
    )

    assert_empty(
        validate_success(
            api.list_journal_postings(
                AUDITOR, business_date_id=bd["id"], charge_type="MISC_CHARGE"
            )
        ),
        "MISC_CHARGE lines",
    )


# ---------------------------------------------------------------------------
# Role authorization against path existence
# ---------------------------------------------------------------------------


def test_role_authorization_outranks_path_existence_on_reopen(api):
    """An unlisted role learns nothing about whether the path id exists.

    PRD section 2.12 runs authorization before any path lookup, and PRD section 3.8
    reserves reopening to the Controller, so a FrontDeskAgent naming an id that
    matches no operating day receives ERR_UNAUTHORIZED (HTTP 403) rather than a 404.
    The Controller naming the same id does get ERR_BUSINESS_DATE_NOT_FOUND, which
    proves the existence check was merely outranked.

    Design: Difficulty/priority_pair_validation_conflict/role_authorization_outranks_path_existence_on_reopen
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    validate_error(
        api.reopen_business_date(MISSING_BUSINESS_DATE_ID, FRONT_DESK),
        E.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.reopen_business_date(MISSING_BUSINESS_DATE_ID, CONTROLLER),
        E.ERR_BUSINESS_DATE_NOT_FOUND,
    )


def test_the_state_band_runs_last_of_the_three_on_reopen(api):
    """Authorization, then existence, then state — in that order.

    PRD section 3.8 refuses a reopen of a day that is not CLOSED with
    ERR_DATE_NOT_CLOSED (HTTP 409), so the Controller naming a real but still-OPEN day
    reaches the third band. The refused call leaves the day OPEN with `reopen_count`
    at zero.

    Design: Difficulty/priority_pair_validation_conflict/role_authorization_outranks_path_existence_on_reopen
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    validate_error(
        api.reopen_business_date(bd["id"], CONTROLLER), E.ERR_DATE_NOT_CLOSED
    )

    day = fx.read_business_date(api, bd["id"])
    assert_fields(day, {"status": "OPEN"})
    assert_int(day["reopen_count"], 0, "reopen_count")
