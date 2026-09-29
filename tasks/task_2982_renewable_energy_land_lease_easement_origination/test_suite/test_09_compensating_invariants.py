"""Invariants broken by a forward action and restored by its compensating one."""

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_ledger_row_shape,
    assert_status,
)
from test_helpers.fixtures import (
    caprock_executed_option,
    extend_option,
    grant_consent,
    leases_for_option,
    ledger_rows,
    publish_setback_rule,
    read_consent,
    read_landowner,
    read_option,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
    revoke_consent,
    withdraw_option,
)
from test_helpers.test_users import PORTFOLIO_MANAGER


def _twice_extended_option():
    """A binding option carrying an initial fee and two unequal extension fees."""
    setup = caprock_executed_option(
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=2,
        extension_fee_per_acre_cents=3000,
        base_rent_per_acre_cents=120000,
    )
    option_id = setup["option"]["id"]
    assert_cents_equals(
        setup["option"]["total_option_paid_cents"], 312500, "post-execution paid"
    )
    first = extend_option(option_id)
    assert_cents_equals(
        first["total_option_paid_cents"], 687500, "paid after one extension"
    )
    second = extend_option(option_id)
    assert_cents_equals(
        second["total_option_paid_cents"], 1118750, "paid after two extensions"
    )
    assert second["extensions_used"] == 2
    return setup, option_id


def _granted_trinity_draw_consent():
    """A hundred-acre tract whose waivable ordinance has been bought back."""
    landowner = register_landowner(
        legal_name="Trinity Draw Family Trust", entity_type="TRUST"
    )
    waivable = publish_setback_rule(
        jurisdiction_code="48375",
        rule_type="PROPERTY_LINE",
        setback_feet=200,
        encumbrance_rate_per_acre=0.2000,
        consent_waivable=True,
    )
    publish_setback_rule(
        jurisdiction_code="48375",
        rule_type="OCCUPIED_DWELLING",
        setback_feet=600,
        encumbrance_rate_per_acre=0.1500,
        consent_waivable=False,
    )
    parcel = register_parcel(
        landowner["id"],
        apn="R-2375-901",
        county_fips="48375",
        gross_acres=100.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    consent = request_consent(
        parcel["id"], waivable["id"], neighbor_name="H. Alvarado", consent_expiry_days=60
    )
    grant_consent(consent["id"])
    return landowner["id"], parcel["id"], consent["id"]


def _conserves(parcel, expected_gross):
    """The three derived acreage figures must add back to the deeded figure."""
    total = (
        parcel["buildable_acres"]
        + parcel["slope_excluded_acres"]
        + parcel["setback_encumbered_acres"]
    )
    assert_acres_equals(total, expected_gross, "conserved deeded acreage")


def test_the_step_up_makes_the_two_extension_fees_unequal():
    """
    Both extensions are priced on the same deeded acreage, but the second is
    fifteen percent dearer per acre than the first, which is what gives the ledger
    two distinct debit rows to reverse.

    PRD: "Each extension is dearer than the last: taking the extension index to be
    the value of `extensions_used` **after** the increment, so that the first
    extension has index 1, the amount is `extension_fee_per_acre_cents` multiplied
    by the parcel's `gross_acres`, multiplied by one-point-one-five raised to the
    power of one less than the index — a fifteen-percent step-up compounding per
    extension — with the result rounded half up to a whole number of cents once."

    Design: Difficulty/compensating_invariant/option_payment_ledger_restored_by_withdraw_refund
    """
    _setup, option_id = _twice_extended_option()

    rows = ledger_rows(option_id)

    assert [row["sequence_no"] for row in rows] == [1, 2, 3]
    assert [row["payment_kind"] for row in rows] == [
        "INITIAL_OPTION_FEE",
        "EXTENSION_FEE",
        "EXTENSION_FEE",
    ]
    assert_cents_equals(rows[0]["amount_cents"], 312500, "initial option fee")
    assert_cents_equals(rows[1]["amount_cents"], 375000, "first extension fee")
    assert_cents_equals(rows[2]["amount_cents"], 431250, "second extension fee")
    for row in rows:
        assert row["ledger_direction"] == "DEBIT_DEVELOPER"
        assert_acres_equals(row["acres_basis"], 125.00, "acres_basis")
        assert_ledger_row_shape(row)


def test_the_refund_is_appended_as_a_fourth_row_and_destroys_nothing():
    """
    The reversal is a new immutable row of the opposite direction carrying the sum
    of the two extension fees on no acreage at all. The three rows that preceded it
    are still there, unaltered.

    PRD: "When that flag is true and `extensions_used` is greater than zero,
    exactly one reversal row is minted: `payment_kind` `REFUND_REVERSAL`,
    `ledger_direction` `CREDIT_DEVELOPER`, `acres_basis` of `0.00` because no
    acreage underlies a reversal, and `amount_cents` equal to the sum of the
    `amount_cents` of this agreement's `EXTENSION_FEE` rows, accumulated in
    `created_at` ascending order."

    Design: Difficulty/compensating_invariant/option_payment_ledger_restored_by_withdraw_refund
    """
    _setup, option_id = _twice_extended_option()
    before = ledger_rows(option_id)

    withdraw_option(option_id, PORTFOLIO_MANAGER, refund_extension_fees=True)

    after = ledger_rows(option_id)
    assert len(after) == 4, f"expected four ledger rows, got {len(after)}"
    assert after[:3] == before, "the pre-existing rows were rewritten by the reversal"
    reversal = after[3]
    assert reversal["sequence_no"] == 4
    assert reversal["payment_kind"] == "REFUND_REVERSAL"
    assert reversal["ledger_direction"] == "CREDIT_DEVELOPER"
    assert_cents_equals(reversal["amount_cents"], 806250, "reversal amount_cents")
    assert_acres_equals(reversal["acres_basis"], 0.00, "reversal acres_basis")
    assert_ledger_row_shape(reversal)


def test_the_withdrawal_restores_the_paid_balance_to_its_post_execution_value():
    """
    Both the agreement's running total and the owner's balance come back to exactly
    what they read the instant after execution, however many extensions were bought
    in between, while the extension counter stays as history.

    PRD: "The consequence is the **option-payment conservation invariant**: after a
    withdrawal from `EXECUTED` with the refund flag set, the owner's
    `total_paid_cents` equals exactly the value it held immediately after that
    agreement's execution, for any number of intervening extensions."

    Design: Difficulty/compensating_invariant/option_payment_ledger_restored_by_withdraw_refund
    """
    setup, option_id = _twice_extended_option()
    landowner_id = setup["landowner"]["id"]
    parcel_id = setup["parcel"]["id"]

    withdrawn = withdraw_option(option_id, PORTFOLIO_MANAGER, refund_extension_fees=True)

    assert_status(withdrawn, "WITHDRAWN", "option")
    assert_cents_equals(
        withdrawn["total_option_paid_cents"], 312500, "total_option_paid_cents"
    )
    assert withdrawn["extensions_used"] == 2
    assert withdrawn["withdraw_reason"] == (
        "interconnection queue position lost; releasing the parcel"
    )
    assert_cents_equals(
        read_landowner(landowner_id)["total_paid_cents"], 312500, "total_paid_cents"
    )
    assert_status(read_parcel(parcel_id), "QUALIFIED", "parcel")
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")
    assert leases_for_option(option_id) == [], "a withdrawn option minted a lease"


def test_the_grant_holds_the_acreage_identity_at_its_shifted_values():
    """
    The buy-back moves two of the three derived figures, and they still add back to
    the deeded acreage exactly.

    PRD: "Whenever `buildable_acres` comes out greater than zero, the three figures
    conserve the deed exactly: `gross_acres` equals `buildable_acres` plus
    `slope_excluded_acres` plus `setback_encumbered_acres`."

    Design: Difficulty/compensating_invariant/acreage_conservation_restored_by_consent_revoke
    """
    _landowner_id, parcel_id, _consent_id = _granted_trinity_draw_consent()

    parcel = read_parcel(parcel_id)

    assert_acres_equals(parcel["consent_released_acres"], 16.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 19.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 81.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")
    _conserves(parcel, 100.00)


def test_revoking_returns_every_derived_figure_to_its_pre_grant_value():
    """
    Revocation is routed through the same derivation rather than through a stored
    delta, so the encumbrance and the buildable figure land back on their original
    values with no drift, and the ordinance accumulation was never disturbed.

    PRD: "Hop one re-derives the acreage and restores `setback_encumbered_acres`
    and `buildable_acres` to exactly the values they held before the grant; this
    **acreage conservation invariant** is the point of routing revocation through
    the same derivation rather than through a stored delta."

    Design: Difficulty/compensating_invariant/acreage_conservation_restored_by_consent_revoke
    """
    _landowner_id, parcel_id, consent_id = _granted_trinity_draw_consent()

    revoked = revoke_consent(consent_id)

    assert_status(revoked, "REVOKED", "consent")
    assert_acres_equals(revoked["released_acres"], 0.00, "released_acres")
    assert_instant_equals(revoked["revoked_at"], "2026-08-01T00:00:00Z", "revoked_at")
    parcel = read_parcel(parcel_id)
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 35.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 65.00, "buildable_acres")
    assert_acres_equals(parcel["raw_setback_acres"], 35.00, "raw_setback_acres")
    _conserves(parcel, 100.00)


def test_revoking_unwinds_both_cascade_hops_without_erasing_the_grant():
    """
    The parcel falls back below the qualification floor and the owner's posture
    follows it down, but the record still shows when the neighbour had signed.

    PRD: "Hop two re-evaluates qualification and may revert the parcel `QUALIFIED →
    SCREENING`."

    Design: Difficulty/compensating_invariant/acreage_conservation_restored_by_consent_revoke
    """
    landowner_id, parcel_id, consent_id = _granted_trinity_draw_consent()
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")

    revoke_consent(consent_id)

    assert_status(read_parcel(parcel_id), "SCREENING", "parcel")
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")
    assert_instant_equals(
        read_consent(consent_id)["granted_at"], "2026-08-01T00:00:00Z", "granted_at"
    )


def test_no_option_or_lease_row_is_touched_by_a_consent_revocation():
    """
    The acreage compensation is a physical-quantity restoration only; it mints no
    money row anywhere, and the owner's paid balance never moved in the first
    place.

    PRD: "Hop three resynchronises the owner and may revert them `ENGAGED →
    PROSPECT`."

    Design: Difficulty/compensating_invariant/acreage_conservation_restored_by_consent_revoke
    """
    landowner_id, _parcel_id, consent_id = _granted_trinity_draw_consent()

    revoke_consent(consent_id)

    landowner = read_landowner(landowner_id)
    assert_status(landowner, "PROSPECT", "landowner")
    assert_cents_equals(landowner["total_paid_cents"], 0, "total_paid_cents")


def test_a_withdrawn_option_keeps_the_agreement_readable_as_history():
    """
    Withdrawal is terminal on the instrument but not destructive: the negotiated
    terms and the whole payment history remain readable after the parcel has been
    released.

    PRD: "That ledger is append-only and immutable: rows are never edited or
    deleted, a reversal is always a new row, and a row carries no `updated_at` and
    no `version` (see §2.4)."

    Design: Difficulty/compensating_invariant/option_payment_ledger_restored_by_withdraw_refund
    """
    _setup, option_id = _twice_extended_option()

    withdraw_option(option_id, PORTFOLIO_MANAGER, refund_extension_fees=True)

    option = read_option(option_id)
    assert_status(option, "WITHDRAWN", "option")
    rows = ledger_rows(option_id)
    debits = sum(
        row["amount_cents"] for row in rows if row["ledger_direction"] == "DEBIT_DEVELOPER"
    )
    credits = sum(
        row["amount_cents"] for row in rows if row["ledger_direction"] == "CREDIT_DEVELOPER"
    )
    assert_cents_equals(debits - credits, 312500, "ledger net of the reversal")
