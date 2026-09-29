"""Customs audits: the review loop, the tolerance fork and the shrinkage cascade."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUDIT_NOT_SUBMITTED,
    ERR_AUDIT_PERIOD_NOT_CLOSED,
    ERR_COUNTED_QTY_EXCEEDS_EXPECTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_instant,
    assert_movement_shape,
    assert_nulls,
    assert_stock_quantities,
    ok,
    page,
)
from test_helpers.test_users import (
    CUSTOMS_AUDITOR_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
    USER_AUDITOR,
    USER_STOCK,
    customs_auditor_headers,
)

PERIOD_END = "2026-09-01T00:00:00Z"


def _audited_liquor_ledger(api, receipt_qty=100, with_agreement=True):
    """A hundred bonded litre bottles at 8000 cents and 2400 bps, with a DRAFT audit open."""
    estate = fx.liquor_estate(api, receipt_qty=receipt_qty, with_agreement=with_agreement)
    audit = fx.open_audit(api, estate.terminal["id"], estate.stock_item["id"])
    assert audit["status"] == "DRAFT"
    assert audit["preparer_user_id"] == USER_STOCK
    return estate, audit


def _watch_estate(api):
    """A hundred bonded watches at 20000 cents and 700 bps under an ACTIVE agreement."""
    terminal = fx.register_terminal(api, iata_code="HKG", country_code="HK")
    brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    stock_item = fx.stocked_ledger(api, terminal["id"], watch["id"], 100)
    agreement = fx.active_agreement(api, terminal["id"])
    return terminal, stock_item, agreement


def _watch_ledger_with_a_submitted_count(api, counted_qty=90):
    """The watch estate with one audit already counted and submitted by the preparer."""
    terminal, stock_item, agreement = _watch_estate(api)
    audit = fx.open_audit(api, terminal["id"], stock_item["id"])
    submitted = fx.submit_count(api, audit["id"], counted_qty)
    assert submitted["status"] == "SUBMITTED"
    return terminal, stock_item, agreement, audit


def _settle_the_period(api, agreement):
    """Move the clock past the period end and close the covering agreement."""
    fx.advance_clock(api, PERIOD_END)
    closed = fx.close_agreement(api, agreement["id"])
    assert closed["status"] == "CLOSED"
    return closed


def test_a_finding_that_needed_three_rounds_is_priced_at_the_doubled_levy(api):
    """The loop counter reaching three is what doubles the levy: the same eight assessable
    units are charged 30720 cents rather than 15360.

    PRD 3.9: "A repeat-finding penalty applies when the count needed three or more rounds: the multiplier is 2 when the audit's `round_count` is at least 3, and 1 otherwise."

    Design: Difficulty/boundary_precision_check/shrinkage_penalty_multiplier_after_third_submission_round
    """
    estate, audit = _audited_liquor_ledger(api)

    fx.submit_count(api, audit["id"], 90)
    fx.request_more_info(api, audit["id"], note="Round two: attach the cage tally sheet.")
    second = fx.submit_count(api, audit["id"], 90)
    assert second["round_count"] == 2
    fx.request_more_info(api, audit["id"], note="Round three: reconcile the shelf tally.")
    third = fx.submit_count(api, audit["id"], 90)
    assert third["round_count"] == 3
    assert third["expected_qty_snapshot"] == 100

    _settle_the_period(api, estate.agreement)
    closed = fx.adjudicate_audit(api, audit["id"])

    assert closed["status"] == "CLOSED_ASSESSED"
    assert closed["round_count"] == 3
    assert closed["expected_qty_snapshot"] == 100
    assert closed["shrinkage_qty"] == 10
    assert closed["assessable_qty"] == 8
    assert closed["assessed_duty_cents"] == 30720
    assert closed["assessed_duty_cents"] != 15360
    assert closed["auditor_user_id"] == USER_AUDITOR
    assert_instant(closed["closed_at"], PERIOD_END, "closed_at")

    terminal = ok(api.get_terminal(estate.terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert terminal["unaccounted_duty_liability_cents"] == 30720

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=90, reserved=0, available=90)
    assert ledger["duty_suspended_value_cents"] == 172800


def test_the_same_count_settled_in_two_rounds_keeps_the_single_multiplier(api):
    """One round short of the threshold the multiplier is still 1, so the identical
    shortfall of ten units costs 15360 cents.

    PRD 3.9: "`assessed_duty_cents` is the `assessable_qty` multiplied by that per-unit levy, multiplied by the penalty multiplier, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/shrinkage_penalty_multiplier_after_third_submission_round
    """
    estate, audit = _audited_liquor_ledger(api)

    fx.submit_count(api, audit["id"], 90)
    fx.request_more_info(api, audit["id"], note="Round two: attach the cage tally sheet.")
    second = fx.submit_count(api, audit["id"], 90)
    assert second["round_count"] == 2

    _settle_the_period(api, estate.agreement)
    closed = fx.adjudicate_audit(api, audit["id"])

    assert closed["status"] == "CLOSED_ASSESSED"
    assert closed["round_count"] == 2
    assert closed["shrinkage_qty"] == 10
    assert closed["assessable_qty"] == 8
    assert closed["assessed_duty_cents"] == 15360
    assert closed["assessed_duty_cents"] != 30720

    terminal = ok(api.get_terminal(estate.terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert terminal["unaccounted_duty_liability_cents"] == 15360

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=90, reserved=0, available=90)
    assert ledger["duty_suspended_value_cents"] == 172800


def test_each_re_submission_re_takes_the_snapshot_and_climbs_the_round_counter(api):
    """The book figure moves by minus five between rounds, so the second and third
    submissions freeze 95 where the first froze 100.

    PRD 3.9: "On a first submit the audit moves `DRAFT → SUBMITTED` and `round_count` stays at 1; on a re-submit after an information request it moves `INFO_REQUESTED → SUBMITTED`, re-takes the snapshot from the item's current `on_hand_qty`, and increments `round_count` by 1."

    Design: Difficulty/non_linear_state_machine/customs_audit_info_request_cycle_retakes_expected_quantity_snapshot
    """
    estate, audit = _audited_liquor_ledger(api, with_agreement=False)

    first = fx.submit_count(api, audit["id"], 90)
    assert first["status"] == "SUBMITTED"
    assert first["round_count"] == 1
    assert first["expected_qty_snapshot"] == 100
    assert first["counted_qty"] == 90

    returned = fx.request_more_info(api, audit["id"], note="Round two: attach the cage tally sheet.")
    assert returned["status"] == "INFO_REQUESTED"

    fx.post_adjustment(api, estate.stock_item["id"], -5)

    second = fx.submit_count(api, audit["id"], 90)
    assert second["status"] == "SUBMITTED"
    assert second["round_count"] == 2
    assert second["expected_qty_snapshot"] == 95

    fx.request_more_info(api, audit["id"], note="Round three: reconcile the minus five adjustment.")

    third = fx.submit_count(api, audit["id"], 92)
    assert third["status"] == "SUBMITTED"
    assert third["round_count"] == 3
    assert third["counted_qty"] == 92
    assert third["expected_qty_snapshot"] == 95

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=95, reserved=0, available=95)


def test_the_review_request_stores_its_note_and_cannot_be_repeated_mid_cycle(api):
    """Each pass through the loop replaces the note, and a second request while the audit
    already waits for information is refused.

    PRD 3.9: "The cycle `SUBMITTED → INFO_REQUESTED → SUBMITTED` may run any number of times, and `round_count` is the loop counter that survives it"

    Design: Difficulty/non_linear_state_machine/customs_audit_info_request_cycle_retakes_expected_quantity_snapshot
    """
    _estate, audit = _audited_liquor_ledger(api, with_agreement=False)

    submitted = fx.submit_count(api, audit["id"], 90)
    assert_nulls(submitted, "info_request_note", "auditor_user_id", "closed_at")
    version_after_submit = submitted["version"]

    returned = fx.request_more_info(api, audit["id"], note="Round two: attach the cage tally sheet.")
    assert returned["status"] == "INFO_REQUESTED"
    assert returned["info_request_note"] == "Round two: attach the cage tally sheet."
    assert returned["counted_qty"] == 90
    assert returned["version"] == version_after_submit + 1

    validate_error(
        api.request_audit_info(
            audit["id"],
            {"info_request_note": "Round two again: the tally sheet is still missing."},
            CUSTOMS_AUDITOR_HEADERS,
        ),
        ERR_AUDIT_NOT_SUBMITTED,
    )
    unchanged = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert unchanged["status"] == "INFO_REQUESTED"
    assert unchanged["info_request_note"] == "Round two: attach the cage tally sheet."
    assert unchanged["version"] == version_after_submit + 1

    resubmitted = fx.submit_count(api, audit["id"], 90)
    assert resubmitted["round_count"] == 2

    returned_again = fx.request_more_info(api, audit["id"], note="Round three: reconcile the shelf tally.")
    assert returned_again["status"] == "INFO_REQUESTED"
    assert returned_again["info_request_note"] == "Round three: reconcile the shelf tally."
    assert returned_again["round_count"] == 2


def _audit_over_a_reserved_ledger(api):
    """A hundred bonded units with sixty reserved, counted at thirty and submitted."""
    estate = fx.liquor_estate(api, receipt_qty=100)
    itinerary = fx.record_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T00:00:00Z")
    reservation = fx.place_reservation(
        api,
        itinerary["id"],
        estate.stock_item,
        60,
        reservation_window_start="2026-08-10T00:00:00Z",
        reservation_window_end="2026-08-12T00:00:00Z",
    )
    assert reservation["status"] == "RESERVED"
    audit = fx.open_audit(api, estate.terminal["id"], estate.stock_item["id"])
    submitted = fx.submit_count(api, audit["id"], 30)
    assert submitted["expected_qty_snapshot"] == 100
    return estate, reservation, audit


def test_the_adjudication_books_the_liability_then_writes_the_missing_units_off(api):
    """Levels one and two: the assessment lands on the terminal, and the whole missing
    quantity leaves the books through a single write-off entry.

    PRD 3.9: "The audit moves `SUBMITTED → CLOSED_ASSESSED`, recording `shrinkage_qty`, `assessable_qty` and `assessed_duty_cents`, setting `auditor_user_id` and `closed_at`, and the audited terminal's `unaccounted_duty_liability_cents` increases by the `assessed_duty_cents` just assessed."

    Design: Difficulty/transitive_cascade/audit_assessment_cascade_depth_three_liability_to_writeoff_to_reservation_release
    """
    estate, _reservation, audit = _audit_over_a_reserved_ledger(api)

    before = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(before, on_hand=100, reserved=60, available=40)
    assert before["duty_suspended_value_cents"] == 192000

    _settle_the_period(api, estate.agreement)
    closed = fx.adjudicate_audit(api, audit["id"])

    assert closed["status"] == "CLOSED_ASSESSED"
    assert closed["shrinkage_qty"] == 70
    assert closed["assessable_qty"] == 68
    assert closed["assessed_duty_cents"] == 130560

    terminal = ok(api.get_terminal(estate.terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert terminal["unaccounted_duty_liability_cents"] == 130560

    write_offs, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "SHRINKAGE_WRITE_OFF"},
        )
    )
    assert len(write_offs) == 1
    assert_movement_shape(write_offs[0])
    assert write_offs[0]["qty_delta"] == -70
    assert write_offs[0]["affects"] == "ON_HAND"
    assert write_offs[0]["source_ref_type"] == "CUSTOMS_AUDIT"
    assert write_offs[0]["source_ref_id"] == audit["id"]

    after = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert after["on_hand_qty"] == 30
    assert_instant(after["last_reconciled_at"], PERIOD_END, "last_reconciled_at")


def test_the_write_off_forces_the_reservation_that_no_longer_has_cover(api):
    """Level three: thirty units cannot cover a sixty-unit hold, so the reservation is
    released until the books balance and the exposure is re-derived.

    PRD 3.9: "The loop stops as soon as `reserved_qty` is less than or equal to `on_hand_qty`, so no more reservations are sacrificed than the shortfall requires."

    Design: Difficulty/transitive_cascade/audit_assessment_cascade_depth_three_liability_to_writeoff_to_reservation_release
    """
    estate, reservation, audit = _audit_over_a_reserved_ledger(api)

    _settle_the_period(api, estate.agreement)
    fx.adjudicate_audit(api, audit["id"])

    released = ok(api.get_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS))
    assert released["status"] == "RELEASED"
    assert_instant(released["closed_at"], PERIOD_END, "closed_at")
    assert released["version"] == reservation["version"] + 1

    releases, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "RESERVATION_RELEASE"},
        )
    )
    assert len(releases) == 1
    assert releases[0]["qty_delta"] == -60
    assert releases[0]["affects"] == "RESERVED"

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=30, reserved=0, available=30)
    assert ledger["duty_suspended_value_cents"] == 57600


def test_the_close_is_refused_while_the_settlement_period_is_still_open(api):
    """A count that is complete in every other respect cannot be adjudicated until the
    concession agreement covering its terminal and period is closed.

    PRD 3.9: "It requires the audit to be `SUBMITTED` (`ERR_AUDIT_NOT_SUBMITTED`), an operator identifier different from `preparer_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the concession agreement covering the audit's own `terminal_id` and `period_code` to exist and to be in `CLOSED` standing (`ERR_AUDIT_PERIOD_NOT_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/customs_audit_close_gated_on_concession_agreement_period_closure
    """
    terminal, stock_item, agreement, audit = _watch_ledger_with_a_submitted_count(api)

    assert ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))["status"] == "ACTIVE"

    validate_error(api.close_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS), ERR_AUDIT_PERIOD_NOT_CLOSED)

    refused = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert refused["status"] == "SUBMITTED"
    assert refused["assessed_duty_cents"] == 0
    assert refused["shrinkage_qty"] == 0
    assert_nulls(refused, "auditor_user_id", "closed_at")

    assert ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["unaccounted_duty_liability_cents"] == 0

    ledger = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=100, reserved=0, available=100)
    assert_nulls(ledger, "last_reconciled_at")


def test_the_same_close_adjudicates_once_the_period_has_been_settled(api):
    """With the agreement in CLOSED standing the identical call assesses the shortfall of
    ten units against the eight that fall outside the tolerance.

    PRD 3.9: "`assessable_qty` is the shrinkage in excess of that tolerance when positive, and 0 otherwise."

    Design: Difficulty/cross_entity_state_dependency/customs_audit_close_gated_on_concession_agreement_period_closure
    """
    terminal, stock_item, agreement, audit = _watch_ledger_with_a_submitted_count(api)

    validate_error(api.close_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS), ERR_AUDIT_PERIOD_NOT_CLOSED)

    _settle_the_period(api, agreement)
    closed = fx.adjudicate_audit(api, audit["id"])

    assert closed["status"] == "CLOSED_ASSESSED"
    assert closed["expected_qty_snapshot"] == 100
    assert closed["shrinkage_qty"] == 10
    assert closed["assessable_qty"] == 8
    assert closed["assessed_duty_cents"] == 11200
    assert closed["auditor_user_id"] == USER_AUDITOR

    assert (
        ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["unaccounted_duty_liability_cents"]
        == 11200
    )

    ledger = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=90, reserved=0, available=90)
    assert ledger["duty_suspended_value_cents"] == 126000
    assert_instant(ledger["last_reconciled_at"], PERIOD_END, "last_reconciled_at")


def test_a_shrinkage_of_exactly_two_percent_is_absorbed_while_one_more_unit_is_assessed(api):
    """Two missing units out of a hundred fall inside the statutory tolerance and close the
    audit clean; three missing units cross it, and the write-off takes all three.

    PRD 3.9: "When `assessable_qty` comes out at 0 the audit closes clean: it moves `SUBMITTED → CLOSED_CLEAN`, records the computed `shrinkage_qty` and an `assessable_qty` of 0, leaves `assessed_duty_cents` at 0, sets `auditor_user_id` to the acting operator identifier and `closed_at` to the logical clock, and sets the audited item's `last_reconciled_at` to the logical clock."

    Design: Corner/calculations/shrinkage_tolerance_at_exactly_two_percent_closes_the_audit_clean
    """
    terminal, stock_item, agreement = _watch_estate(api)
    clean = fx.open_audit(api, terminal["id"], stock_item["id"])
    assessed = fx.open_audit(api, terminal["id"], stock_item["id"])
    _settle_the_period(api, agreement)

    validate_error(
        api.submit_audit(clean["id"], {"counted_qty": 101}, STOCK_CONTROLLER_HEADERS),
        ERR_COUNTED_QTY_EXCEEDS_EXPECTED,
    )
    rejected = ok(api.get_audit(clean["id"], STOCK_CONTROLLER_HEADERS))
    assert rejected["status"] == "DRAFT"
    assert rejected["round_count"] == 1

    submitted = fx.submit_count(api, clean["id"], 98)
    assert submitted["expected_qty_snapshot"] == 100
    assert submitted["round_count"] == 1

    clean_closed = fx.adjudicate_audit(api, clean["id"])
    assert clean_closed["status"] == "CLOSED_CLEAN"
    assert clean_closed["shrinkage_qty"] == 2
    assert clean_closed["assessable_qty"] == 0
    assert clean_closed["assessed_duty_cents"] == 0
    assert clean_closed["auditor_user_id"] == USER_AUDITOR
    assert_instant(clean_closed["closed_at"], PERIOD_END, "closed_at")

    assert ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["unaccounted_duty_liability_cents"] == 0
    after_clean = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(after_clean, on_hand=100, reserved=0, available=100)
    assert_instant(after_clean["last_reconciled_at"], PERIOD_END, "last_reconciled_at")
    write_offs, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "SHRINKAGE_WRITE_OFF"},
        )
    )
    assert write_offs == []

    fx.submit_count(api, assessed["id"], 97)
    assessed_closed = fx.adjudicate_audit(api, assessed["id"])
    assert assessed_closed["status"] == "CLOSED_ASSESSED"
    assert assessed_closed["shrinkage_qty"] == 3
    assert assessed_closed["assessable_qty"] == 1
    assert assessed_closed["assessed_duty_cents"] == 1400

    assert (
        ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["unaccounted_duty_liability_cents"]
        == 1400
    )
    after_assessment = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(after_assessment, on_hand=97, reserved=0, available=97)
    assert after_assessment["duty_suspended_value_cents"] == 135800
    written_off, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "SHRINKAGE_WRITE_OFF"},
        )
    )
    assert len(written_off) == 1
    assert written_off[0]["qty_delta"] == -3


def test_the_preparer_may_neither_return_nor_close_their_own_count(api):
    """Separation is enforced on the acting identifier, so the auditor role is no help to the
    operator who opened the audit, while a different auditor adjudicates it.

    PRD 2.10: "A customs audit stores the operator identifier that opened it in `preparer_user_id`; the identifier that later requests more information about the count, or closes it, is compared against that value and must differ, otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES` (409)."

    Design: Corner/validations/the_preparer_of_an_audit_cannot_review_or_close_it
    """
    terminal, _stock_item, agreement, audit = _watch_ledger_with_a_submitted_count(api)
    _settle_the_period(api, agreement)
    preparer_as_auditor = customs_auditor_headers(USER_STOCK)

    validate_error(
        api.request_audit_info(
            audit["id"], {"info_request_note": "Recount the display cabinet."}, preparer_as_auditor
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(api.close_audit(audit["id"], preparer_as_auditor), ERR_SEGREGATION_OF_DUTIES)

    refused = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert refused["status"] == "SUBMITTED"
    assert refused["preparer_user_id"] == USER_STOCK
    assert_nulls(refused, "info_request_note", "auditor_user_id", "closed_at")

    closed = fx.adjudicate_audit(api, audit["id"])
    assert closed["status"] == "CLOSED_ASSESSED"
    assert closed["auditor_user_id"] == USER_AUDITOR
    assert closed["assessed_duty_cents"] == 11200

    assert (
        ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["unaccounted_duty_liability_cents"]
        == 11200
    )
