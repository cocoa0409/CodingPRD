"""Initial states, refused transitions, terminal lockdown and transition side effects."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_PARCEL_NOT_QUALIFIED,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_ledger_row_shape,
    assert_score_equals,
    assert_status,
    assert_version_is,
)
from test_helpers.fixtures import (
    accept_option,
    client,
    draft_option,
    execute_option,
    grant_consent,
    ledger_rows,
    publish_setback_rule,
    raise_curative,
    read_consent,
    read_curative,
    read_landowner,
    read_option,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
    revoke_consent,
    send_option,
    withdraw_option,
)
from test_helpers.test_users import (
    LAND_AGENT,
    PORTFOLIO_MANAGER,
    PORTFOLIO_MANAGER_USER_ID,
    TITLE_COUNSEL,
    TITLE_COUNSEL_2,
    TITLE_COUNSEL_USER_ID_2,
)

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"


def _sandhill_parcel(apn: str, gross_acres: float):
    """An owner and one tract of the requested size in an unregulated county."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    parcel = register_parcel(
        landowner_id,
        apn=apn,
        county_fips=CLEAN_COUNTY,
        gross_acres=gross_acres,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    return landowner_id, parcel


def _revoked_consent():
    """A quarter-acre-per-acre ordinance bought back and then given back."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    rule = publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="OCCUPIED_DWELLING",
        setback_feet=1200,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )
    parcel = register_parcel(
        landowner_id,
        apn="R-9002-100",
        county_fips=CLEAN_COUNTY,
        gross_acres=100.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    assert_acres_equals(parcel["raw_setback_acres"], 25.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 75.00, "buildable_acres")
    assert_status(parcel, "SCREENING", "parcel")
    consent = request_consent(
        parcel["id"], rule["id"], neighbor_name="H. Vaughn", consent_expiry_days=90
    )
    granted = grant_consent(consent["id"])
    assert_acres_equals(granted["released_acres"], 20.00, "released_acres")
    assert_status(read_parcel(parcel["id"]), "QUALIFIED", "parcel")
    revoked = revoke_consent(consent["id"])
    assert_status(revoked, "REVOKED", "consent")
    return landowner_id, parcel["id"], revoked


def _withdrawn_from_sent():
    """An agreement withdrawn before it ever became binding."""
    landowner_id, parcel = _sandhill_parcel("R-9001-001", 200.00)
    assert_status(parcel, "QUALIFIED", "parcel")
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        base_rent_per_acre_cents=120000,
    )
    assert_status(option, "DRAFT", "option")
    send_option(option["id"])
    withdrawn = withdraw_option(
        option["id"], LAND_AGENT, withdraw_reason="Landowner declined the terms"
    )
    assert_status(withdrawn, "WITHDRAWN", "option")
    return landowner_id, parcel["id"], option["id"]


def _accepted_two_hundred_acre_option():
    """A two-hundred-acre deal sitting one hop short of binding."""
    landowner_id, parcel = _sandhill_parcel("R-9001-001", 200.00)
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        base_rent_per_acre_cents=120000,
    )
    send_option(option["id"])
    accepted = accept_option(option["id"], landowner_id)
    assert_status(accepted, "ACCEPTED", "option")
    return landowner_id, parcel["id"], option["id"]


def _blocked_pair_on_a_clean_parcel():
    """A blocking defect and a second defect waiting behind it."""
    landowner_id, parcel = _sandhill_parcel("R-9001-001", 200.00)
    first = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=250000,
    )
    second = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MORTGAGE_SUBORDINATION",
        severity="BLOCKING",
        curative_cost_cents=180000,
        blocks_item_id=first["id"],
    )
    assert_status(first, "OPEN", "item A")
    assert_status(second, "BLOCKED", "item B")
    return landowner_id, parcel["id"], first, second


def test_a_priority_parcel_below_the_acreage_floor_stays_in_screening():
    """
    Sixty acres of unencumbered ground score at the top tier and still fail to
    qualify, because the gate is the acreage floor and not the score. The intake
    cascade therefore leaves the parcel in the state it was created in.

    PRD: "A parcel sitting in `SCREENING` is promoted `SCREENING → QUALIFIED` when
    its `buildable_acres` is at least 80.00 acres, its `screening_tier` is
    `PRIORITY` or `STANDARD`, and its `blocking_curative_open_count` is zero."

    Design: Corner/state_machines/parcel_below_minimum_buildable_stays_in_initial_screening_state
    """
    _landowner_id, parcel = _sandhill_parcel("R-9001-060", 60.00)

    assert_acres_equals(parcel["buildable_acres"], 60.00, "buildable_acres")
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY", parcel["screening_tier"]
    assert_status(parcel, "SCREENING", "parcel")
    assert_status(read_parcel(parcel["id"]), "SCREENING", "re-read parcel")


def test_the_owner_of_an_unqualified_parcel_stays_a_prospect():
    """
    The posture sync ran inside the same request and found nothing to promote on,
    so the owner is left where registration put them.

    PRD: "A brand-new parcel can therefore land in `SCREENING`, be promoted straight
    to `QUALIFIED`, or — if its screening tier comes out `REJECTED` — be sent to the
    terminal `DISQUALIFIED` status without any further operator action."

    Design: Corner/state_machines/parcel_below_minimum_buildable_stays_in_initial_screening_state
    """
    landowner_id, parcel = _sandhill_parcel("R-9001-060", 60.00)

    assert_status(parcel, "SCREENING", "parcel")
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")


def test_a_second_revocation_of_the_same_consent_is_refused():
    """
    The compensating transition has already run and its target state is final for
    this consent: the repeat is refused rather than treated as harmless, and the row
    is not even touched.

    PRD: "The parcel must not be `LEASED` — a revocation against a conveyed parcel
    is `ERR_INVALID_STATE` — and the consent must be in `GRANTED`, else the same
    code answers."

    Design: Corner/state_machines/revoked_consent_cannot_be_revoked_twice_returns_invalid_state
    """
    _landowner_id, _parcel_id, revoked = _revoked_consent()

    response = client().revoke_neighbor_consent(revoked["id"], {}, LAND_AGENT)

    validate_error(response, ERR_INVALID_STATE, 409)
    consent = read_consent(revoked["id"])
    assert_status(consent, "REVOKED", "consent")
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")
    assert_version_is(consent, revoked["version"], "consent")


def test_the_refused_second_revocation_leaves_the_restored_acreage_alone():
    """
    A rejected call must not re-run the derivation, so the buildable figure stays on
    the value the first revocation restored it to instead of drifting a second time.

    PRD: "It also rewrites `released_acres` on every neighbor consent of that
    parcel: a consent that is currently `GRANTED` and whose rule is consent-waivable
    receives its own rounded release term, and every other consent of the parcel
    receives `0.00`."

    Design: Corner/state_machines/revoked_consent_cannot_be_revoked_twice_returns_invalid_state
    """
    landowner_id, parcel_id, revoked = _revoked_consent()
    before = read_parcel(parcel_id)
    assert_acres_equals(before["buildable_acres"], 75.00, "buildable_acres")

    response = client().revoke_neighbor_consent(revoked["id"], {}, LAND_AGENT)
    validate_error(response, ERR_INVALID_STATE, 409)

    parcel = read_parcel(parcel_id)
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 25.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 75.00, "buildable_acres")
    assert_status(parcel, "SCREENING", "parcel")
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")
    assert_version_is(parcel, before["version"], "parcel")


def test_a_withdrawn_agreement_cannot_be_returned_to_the_negotiation_loop():
    """
    Withdrawal reached from the pre-execution side is just as terminal as
    withdrawal from a binding option: re-sending the same terms is refused on the
    from-state.

    PRD: "Sending is admitted only from `DRAFT` or `REVISED` — any other status is
    `ERR_INVALID_STATE` (409) — and additionally requires the underlying parcel to
    be in `QUALIFIED` **at that instant**, meaning its `buildable_acres` is at least
    eighty acres, its `screening_tier` is `PRIORITY` or `STANDARD`, and it carries no
    open blocking curative item."

    Design: Corner/state_machines/withdrawn_option_is_terminal_and_cannot_be_sent_again
    """
    _landowner_id, _parcel_id, option_id = _withdrawn_from_sent()

    response = client().send_option(option_id, {}, LAND_AGENT)

    validate_error(response, ERR_INVALID_STATE, 409)
    option = read_option(option_id)
    assert_status(option, "WITHDRAWN", "option")
    assert option["withdraw_reason"] == "Landowner declined the terms"


def test_a_pre_execution_withdrawal_moves_no_money_and_releases_no_land():
    """
    Because the instrument never became binding, the withdrawal is inert: the
    negotiation counter is where the draft left it, no consideration was ever paid,
    the ledger is empty, and the land was never taken off the market.

    PRD: "From the five pre-execution statuses the withdrawal does nothing but set
    the status to `WITHDRAWN` and store the reason; withdrawal from `EXECUTED`
    carries the far heavier consequences described in §3.6. `EXERCISED`, `EXPIRED`
    and `WITHDRAWN` are the three terminal statuses of the option lifecycle."

    Design: Corner/state_machines/withdrawn_option_is_terminal_and_cannot_be_sent_again
    """
    landowner_id, parcel_id, option_id = _withdrawn_from_sent()

    option = read_option(option_id)

    assert option["round_index"] == 0, option["round_index"]
    assert_cents_equals(
        option["total_option_paid_cents"], 0, "total_option_paid_cents"
    )
    assert ledger_rows(option_id) == [], "a pre-execution withdrawal minted a ledger row"
    assert_status(read_parcel(parcel_id), "QUALIFIED", "parcel")
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")


def test_sending_terms_over_an_unqualified_parcel_is_refused():
    """
    Drafting against a tract still in screening is admitted, because only the send
    carries the qualification precondition, and the send is then refused while the
    agreement stays in the state the draft opened in.

    PRD: "A parcel that has drifted out of qualification since the draft was written
    blocks the send with `ERR_PARCEL_NOT_QUALIFIED` (422)."

    Design: Corner/state_machines/send_option_terms_requires_the_parcel_to_be_qualified
    """
    landowner_id, parcel = _sandhill_parcel("R-9001-060", 60.00)
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        base_rent_per_acre_cents=120000,
    )
    assert_status(option, "DRAFT", "option")

    response = client().send_option(option["id"], {}, LAND_AGENT)

    validate_error(response, ERR_PARCEL_NOT_QUALIFIED, 422)
    assert_status(read_option(option["id"]), "DRAFT", "option")
    parcel_after = read_parcel(parcel["id"])
    assert_status(parcel_after, "SCREENING", "parcel")
    assert_acres_equals(parcel_after["buildable_acres"], 60.00, "buildable_acres")


def test_execution_stamps_the_expiry_from_the_term_in_days():
    """
    One action turns the deal binding and dates it: the acting manager is recorded,
    the execution instant comes from the logical clock, and a three-hundred-and-
    sixty-five-day term lands the expiry a year out to the day.

    PRD: "On success the agreement moves `ACCEPTED → EXECUTED`, `executed_at` is
    stamped from the logical clock, `executed_by_user_id` is stamped from the acting
    `X-User-ID`, and `option_expiry_at` is set to `executed_at` advanced by
    `option_term_days` days."

    Design: Corner/state_machines/execute_option_side_effects_mint_ledger_row_and_advance_two_parents
    """
    _landowner_id, _parcel_id, option_id = _accepted_two_hundred_acre_option()

    response = client().execute_option(option_id, {}, PORTFOLIO_MANAGER)

    option = validate_success(response, 200)
    assert_status(option, "EXECUTED", "option")
    assert option["executed_by_user_id"] == PORTFOLIO_MANAGER_USER_ID
    assert_instant_equals(option["executed_at"], "2026-08-01T00:00:00Z", "executed_at")
    assert_instant_equals(
        option["option_expiry_at"], "2027-08-01T00:00:00Z", "option_expiry_at"
    )


def test_execution_mints_exactly_one_ledger_row_on_the_deeded_acreage():
    """
    The same request that made the deal binding also opened its payment history with
    a single debit row, priced at twenty-five dollars against all two hundred deeded
    acres.

    PRD: "The row minted by execution has `payment_kind` `INITIAL_OPTION_FEE`,
    `ledger_direction` `DEBIT_DEVELOPER`, `sequence_no` 1, and `acres_basis` set to a
    snapshot of the parcel's `gross_acres`."

    Design: Corner/state_machines/execute_option_side_effects_mint_ledger_row_and_advance_two_parents
    """
    _landowner_id, _parcel_id, option_id = _accepted_two_hundred_acre_option()

    execute_option(option_id)

    rows = ledger_rows(option_id)
    assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
    row = rows[0]
    assert row["payment_kind"] == "INITIAL_OPTION_FEE", row["payment_kind"]
    assert row["ledger_direction"] == "DEBIT_DEVELOPER", row["ledger_direction"]
    assert row["sequence_no"] == 1, row["sequence_no"]
    assert_acres_equals(row["acres_basis"], 200.00, "acres_basis")
    assert_cents_equals(row["amount_cents"], 500000, "amount_cents")
    assert_ledger_row_shape(row)


def test_execution_advances_both_parents_and_both_paid_balances():
    """
    Five effects across four entities land in the one request: the agreement's own
    total, the owner's ledger balance, the parcel taken off the market and the
    owner's posture jumping straight past engaged.

    PRD: "The agreement's `total_option_paid_cents` and the owner's
    `total_paid_cents` are then recomputed per §3.1, the parcel moves `QUALIFIED →
    OPTIONED`, and the owner's posture advances `ENGAGED → UNDER_OPTION`."

    Design: Corner/state_machines/execute_option_side_effects_mint_ledger_row_and_advance_two_parents
    """
    landowner_id, parcel_id, option_id = _accepted_two_hundred_acre_option()

    executed = execute_option(option_id)

    assert_cents_equals(
        executed["total_option_paid_cents"], 500000, "total_option_paid_cents"
    )
    landowner = read_landowner(landowner_id)
    assert_cents_equals(landowner["total_paid_cents"], 500000, "total_paid_cents")
    assert_status(landowner, "UNDER_OPTION", "landowner")
    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")


def test_waiving_releases_the_successor_exactly_as_clearing_would():
    """
    Accepting the defect on the record rather than curing it still unblocks the item
    waiting behind it, so the parcel is left blocked by one open item and stays out
    of qualification.

    PRD: "Successors are then promoted `BLOCKED → OPEN` in `created_at` ascending
    order **exactly as in the clearing branch**, the parcel's
    `blocking_curative_open_count` and `waived_blocking_count` are recounted,
    screening is re-computed under the persisted variant, and qualification is
    re-evaluated with its possible landowner cascade."

    Design: Corner/state_machines/waive_curative_item_releases_successor_without_capitalising_cost
    """
    landowner_id, parcel_id, first, second = _blocked_pair_on_a_clean_parcel()

    response = client().waive_curative_item(
        first["id"],
        {"waiver_note": "Mineral owner non-development letter accepted by counsel"},
        TITLE_COUNSEL_2,
    )

    waived = validate_success(response, 200)
    assert_status(waived, "WAIVED", "item A")
    assert waived["cleared_by_user_id"] == TITLE_COUNSEL_USER_ID_2
    assert_instant_equals(waived["cleared_at"], "2026-08-01T00:00:00Z", "cleared_at")
    assert_status(read_curative(second["id"]), "OPEN", "item B")
    parcel = read_parcel(parcel_id)
    assert parcel["blocking_curative_open_count"] == 1, (
        f"blocking_curative_open_count: {parcel['blocking_curative_open_count']}"
    )
    assert parcel["waived_blocking_count"] == 1, parcel["waived_blocking_count"]
    assert_status(parcel, "SCREENING", "parcel")
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")


def test_a_waiver_capitalises_no_curative_cost():
    """
    This is the one place the waiver branch diverges from the clearing branch: two
    and a half thousand dollars of defect was accepted rather than cured, so nothing
    is added to the parcel's capitalised curative spend.

    PRD: "The one place the waiver branch diverges from the clearing branch is cost:
    **the parcel's `curative_cost_cents` is not increased by a waiver.**"

    Design: Corner/state_machines/waive_curative_item_releases_successor_without_capitalising_cost
    """
    _landowner_id, parcel_id, first, _second = _blocked_pair_on_a_clean_parcel()
    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 0, "curative_cost_cents"
    )

    client().waive_curative_item(
        first["id"],
        {"waiver_note": "Mineral owner non-development letter accepted by counsel"},
        TITLE_COUNSEL_2,
    )

    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 0, "curative_cost_cents"
    )
    assert_cents_equals(
        read_curative(first["id"])["curative_cost_cents"], 250000, "item curative_cost_cents"
    )
