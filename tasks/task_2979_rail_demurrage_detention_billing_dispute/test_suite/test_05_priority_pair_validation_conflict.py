"""Queue A - rule ``priority_pair_validation_conflict``.

Three instances, each arming two validation bands at once on one request and
proving the shadowed band is genuinely live by disarming only the winner.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_FACILITY_EMBARGOED,
    ERR_INVOICE_NOT_DISPUTABLE,
    ERR_INVOICE_NOT_FOUND,
    ERR_ROLE_FORBIDDEN,
    ERR_TARIFF_RULE_SET_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_error_meta_is_minimal,
    error_id_of,
    assert_instant_eq,
    assert_request_id_prefixed,
    assert_subset_equal,
)
from test_helpers.constants import (
    ACCESS_MODE_EMBARGOED,
    ACCESS_MODE_OPEN,
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    BILLING_POSTURE_CREDIT_HOLD,
    BILLING_SETTLED,
    CHARGE_FINAL,
    CHARGE_PROVISIONAL,
    CYCLE_A_GROSS_CENTS,
    DISPUTE_DRAFT,
    INVOICE_CLOSED,
    INVOICE_ISSUED,
    MOVEMENT_ACTUALLY_PLACED,
    SCOPE_WHOLE_INVOICE,
    TARIFF_STATUS_DRAFT,
)
from test_helpers.test_users import ADMIN, AGENT, OFFICER, make_customer_headers

# --- instance 12 literals --------------------------------------------------
ISSUE_CLOCK_R5I1 = "2026-08-15T00:00:00.000Z"
DEADLINE_R5I1 = "2026-09-14T23:59:59.999Z"
CLOCK_PAST_DEADLINE = "2026-09-20T00:00:00.000Z"

# --- instance 13 literals --------------------------------------------------
CLOCK_AT_RELEASE_ATTEMPT = "2026-08-10T16:00:00.000Z"

# --- instance 14 literals --------------------------------------------------
ABSENT_INVOICE_ID = "00000000-0000-0000-0000-00000000dead"
ABSENT_TARIFF_ID = NON_EXISTENT_UUID


def _closed_invoice_with_a_draft_dispute(api):
    """An invoice CLOSED while no line was disputed, plus a DRAFT dispute on it.

    The dispute is filed before the close because PRD 3.7 refuses to close an
    invoice carrying a ``DISPUTED`` line - filing alone does not disturb the
    lines, so the two facts can coexist.
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_R5I1)
    assert invoice["status"] == INVOICE_ISSUED
    assert_instant_eq(
        invoice["dispute_deadline_at"], DEADLINE_R5I1, "dispute_deadline_at"
    )

    dispute = fx.evidenced_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert dispute["status"] == DISPUTE_DRAFT

    closed = fx.close_invoice(api, invoice["id"])
    assert closed["status"] == INVOICE_CLOSED
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_SETTLED
    return world, cycle, invoice, dispute


# ===========================================================================
# instance: closed_invoice_state_409_outranks_expired_dispute_window_422
# ===========================================================================
def test_closed_invoice_conflict_shadows_the_expired_dispute_window(api):
    """Both bands are armed; the state band answers and the temporal one is silent.

    PRD 3.8: "Because the state band of §2.8 sits above the temporal band, a
    `CLOSED` invoice whose dispute window has *also* expired reports
    `ERR_INVOICE_NOT_DISPUTABLE` and not `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_invoice_state_409_outranks_expired_dispute_window_422
    """
    world, cycle, invoice, dispute = _closed_invoice_with_a_draft_dispute(api)

    fx.set_clock(api, CLOCK_PAST_DEADLINE)
    # Both preconditions are demonstrably true at the moment of the attempt.
    settled = fx.get_invoice(api, invoice["id"])
    assert settled["status"] == INVOICE_CLOSED
    assert CLOCK_PAST_DEADLINE > settled["dispute_deadline_at"]

    response = api.submit_dispute(
        dispute["id"], make_customer_headers(world["customer_id"])
    )
    validate_error(response, ERR_INVOICE_NOT_DISPUTABLE)
    assert response.status_code == 409
    assert error_id_of(response) != ERR_DISPUTE_WINDOW_CLOSED
    assert response.status_code != 422
    assert_error_meta_is_minimal(response)
    assert_request_id_prefixed(response)

    # Nothing moved.
    unchanged = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        unchanged,
        {
            "status": DISPUTE_DRAFT,
            "submitted_at": None,
            "adjudication_due_at": None,
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_FINAL
    assert fx.get_invoice(api, invoice["id"])["total_credit_cents"] == 0


def test_the_shadowed_dispute_window_is_the_answer_on_a_still_issued_invoice(api):
    """Disarm only the state band and the 422 the ladder was hiding surfaces.

    PRD 3.8: "The logical clock must be at or before the invoice's
    `dispute_deadline_at`, or `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_invoice_state_409_outranks_expired_dispute_window_422
    """
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_R5I1)
    dispute = fx.evidenced_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        scope=SCOPE_WHOLE_INVOICE,
    )

    fx.set_clock(api, CLOCK_PAST_DEADLINE)
    # The invoice is left ISSUED this time: only the temporal band is armed.
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_ISSUED

    response = api.submit_dispute(
        dispute["id"], make_customer_headers(world["customer_id"])
    )
    validate_error(response, ERR_DISPUTE_WINDOW_CLOSED)
    assert response.status_code == 422
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_DRAFT


def _spotted_cycle_with_both_bands_armed(api):
    """One ACTUALLY_PLACED cycle whose facility is EMBARGOED and whose consignee is on hold.

    Both postures are applied *after* the spot, because PRD 3.4 requires the
    facility to be exactly ``OPEN`` at the moment of actual placement - the two
    blockers can only be armed once the car is already standing on the track.
    """
    world = fx.reference_world(api)
    agreement = fx.open_agreement(
        api, world["customer_id"], agreement_month=AGREEMENT_MONTH
    )
    cycle = fx.actually_placed_cycle(api, world)
    assert cycle["movement_status"] == MOVEMENT_ACTUALLY_PLACED

    facility = fx.embargo_facility(api, world["facility_id"])
    assert facility["access_mode"] == ACCESS_MODE_EMBARGOED
    customer = fx.put_on_credit_hold(api, world["customer_id"])
    assert customer["billing_posture"] == BILLING_POSTURE_CREDIT_HOLD

    fx.set_clock(api, CLOCK_AT_RELEASE_ATTEMPT)
    return world, agreement, cycle


def _assert_release_changed_nothing(api, world, agreement, cycle):
    """The cycle, its charge and the month ledger are all exactly where they were."""
    frozen = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "released_at": None,
            "chargeable_days": 0,
            "early_release_days": 0,
            "version": cycle["version"],
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_PROVISIONAL
    ledger = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        ledger,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
        },
    )


# ===========================================================================
# instance: facility_embargo_409_outranks_customer_credit_hold_402
# ===========================================================================
def test_embargoed_track_shadows_the_credit_hold_on_the_same_release(api):
    """Physical safety answers first; the 402 the consignee also earned stays hidden.

    PRD 2.8: "Physical safety outranks money in this ladder: an embargoed track
    blocks a release even when the consignee is simultaneously on credit hold."

    Design: Difficulty/priority_pair_validation_conflict/facility_embargo_409_outranks_customer_credit_hold_402
    """
    world, agreement, cycle = _spotted_cycle_with_both_bands_armed(api)

    response = api.release(
        cycle["id"],
        f.release_payload(CLOCK_AT_RELEASE_ATTEMPT),
        make_customer_headers(world["customer_id"]),
    )
    validate_error(response, ERR_FACILITY_EMBARGOED)
    assert response.status_code == 409
    assert error_id_of(response) != ERR_CUSTOMER_CREDIT_HOLD
    assert response.status_code != 402
    assert_error_meta_is_minimal(response)
    assert_request_id_prefixed(response)

    _assert_release_changed_nothing(api, world, agreement, cycle)


def test_lifting_only_the_embargo_reveals_the_shadowed_credit_hold(api):
    """Reopen the track and the identical request drops one band to the 402.

    PRD 2.8: "Release requires the consignee's `billing_posture` to be `CURRENT`,
    or `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402). Being the lowest band in the ladder,
    it surfaces only when the facility is releasable and every other check has
    already passed."

    Design: Difficulty/priority_pair_validation_conflict/facility_embargo_409_outranks_customer_credit_hold_402
    """
    world, agreement, cycle = _spotted_cycle_with_both_bands_armed(api)

    first = api.release(
        cycle["id"],
        f.release_payload(CLOCK_AT_RELEASE_ATTEMPT),
        make_customer_headers(world["customer_id"]),
    )
    validate_error(first, ERR_FACILITY_EMBARGOED)

    reopened = fx.set_access_mode(api, world["facility_id"], ACCESS_MODE_OPEN)
    assert reopened["access_mode"] == ACCESS_MODE_OPEN
    # The hold itself was never touched.
    assert (
        fx.get_customer(api, world["customer_id"])["billing_posture"]
        == BILLING_POSTURE_CREDIT_HOLD
    )

    second = api.release(
        cycle["id"],
        f.release_payload(CLOCK_AT_RELEASE_ATTEMPT),
        make_customer_headers(world["customer_id"]),
    )
    validate_error(second, ERR_CUSTOMER_CREDIT_HOLD)
    assert second.status_code == 402
    assert_error_meta_is_minimal(second)

    _assert_release_changed_nothing(api, world, agreement, cycle)


# ===========================================================================
# instance: role_forbidden_403_outranks_missing_invoice_404
# ===========================================================================
def test_authorization_answers_before_existence_on_an_absent_invoice(api):
    """An unauthorized role learns it is unauthorized, not that the row is gone.

    PRD 2.8: "The caller's role must appear in the endpoint's authorized-role
    list, or `ERR_ROLE_FORBIDDEN`. This applies to every endpoint."

    Design: Difficulty/priority_pair_validation_conflict/role_forbidden_403_outranks_missing_invoice_404
    """
    forbidden = api.get_invoice(ABSENT_INVOICE_ID, AGENT)
    validate_error(forbidden, ERR_ROLE_FORBIDDEN)
    assert forbidden.status_code == 403
    assert error_id_of(forbidden) != ERR_INVOICE_NOT_FOUND
    assert forbidden.status_code != 404
    assert_error_meta_is_minimal(forbidden)
    assert_request_id_prefixed(forbidden)

    # The same identifier really is absent: an authorized role says so.
    missing = api.get_invoice(ABSENT_INVOICE_ID, ADMIN)
    validate_error(missing, ERR_INVOICE_NOT_FOUND)
    assert missing.status_code == 404
    assert_error_meta_is_minimal(missing)

    # Neither rejected read left anything behind.
    still_forbidden = api.get_invoice(ABSENT_INVOICE_ID, AGENT)
    validate_error(still_forbidden, ERR_ROLE_FORBIDDEN)


def test_the_same_inversion_holds_on_the_publish_capability(api):
    """A different endpoint, a different not-found code, the same band order.

    PRD 2.8: "Every identifier appearing in the URL path must resolve to a live
    row, resolved left to right along the path, or the addressed entity's own
    not-found code at HTTP 404."

    Design: Difficulty/priority_pair_validation_conflict/role_forbidden_403_outranks_missing_invoice_404
    """
    live_draft = fx.make_draft_tariff(api)
    assert live_draft["status"] == TARIFF_STATUS_DRAFT

    forbidden = api.publish_tariff_rule_set(
        ABSENT_TARIFF_ID, make_customer_headers("cust-403-probe")
    )
    validate_error(forbidden, ERR_ROLE_FORBIDDEN)
    assert forbidden.status_code == 403
    assert error_id_of(forbidden) != ERR_TARIFF_RULE_SET_NOT_FOUND

    missing = api.publish_tariff_rule_set(ABSENT_TARIFF_ID, OFFICER)
    validate_error(missing, ERR_TARIFF_RULE_SET_NOT_FOUND)
    assert missing.status_code == 404

    # The rule set that does exist was never the target and never moved.
    assert fx.get_tariff(api, live_draft["id"])["status"] == TARIFF_STATUS_DRAFT
    assert fx.get_tariff(api, live_draft["id"])["version"] == live_draft["version"]
