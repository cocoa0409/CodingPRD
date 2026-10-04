"""Visibility of a mutation within the request that caused it, and certificate state."""

import pytest

from test_helpers import (
    advance_cycle,
    cancel_package,
    fetch_package_cycles,
    get_success_data,
    issue_certificate,
    pause_package,
    read_member,
    read_pet,
    read_visit_certificate,
    setup_member_with_package,
    setup_visit_with_certificate,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
ANY = TEST_USERS["any_headers"]


def test_cancelling_a_package_voids_the_unbilled_cycles_without_reducing_the_balance(api):
    """Cancellation is atomic within the request and voids rather than refunds.

    PRD §3.8: "Cancellation is available only from `PAUSED` and not directly from
    `ACTIVE`, refused with `ERR_PACKAGE_NOT_PAUSED` otherwise, which means a
    package must be paused before it can be ended. Cancelling a package does four
    things and is terminal: every `PENDING` billing cycle of that package moves to
    `VOID`, so unbilled cycles are abandoned rather than billed or refunded"
    PRD §3.8: "The member's `outstanding_balance_cents` itself follows the
    conservation rule of §2.9 and therefore falls by the whole of the cancelled
    package's `total_price_cents` while the voided cycles contribute nothing to
    the subtracted term"
    PRD §2.9: "Cycles in `PENDING`, `FAILED` or `VOID` contribute nothing to the
    subtracted term, so voiding a cycle never reduces a balance."

    Design: Corner/consistency_model/pending_cycles_are_voided_rather_than_billed_on_cancellation
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0,
        billing_cycle_count=3, monthly_fee_cents=5000,
    )
    store_id = world["store"]["id"]
    member_id = world["member"]["id"]

    billed = advance_cycle(api, store_id, member_id, world["package"], grooming_visits_consumed=2)
    assert billed["cycle_total_cents"] == pytest.approx(5000.00, abs=0.01)
    package = get_success_data(api.get_package(world["package"]["id"], ADMIN))
    paused = pause_package(api, store_id, member_id, package)

    cancelled = cancel_package(api, store_id, member_id, paused)
    assert cancelled["status"] == "CANCELLED"

    # The package leaves the balance's granted term entirely; the one billed
    # cycle was there when it left, so the member owes the difference.
    member = read_member(api, member_id)
    assert member["outstanding_balance_cents"] == 0

    cycles = fetch_package_cycles(api, world["package"]["id"])
    by_status = {}
    for cycle in cycles:
        by_status[cycle["status"]] = by_status.get(cycle["status"], 0) + 1
    assert by_status.get("BILLED") == 1
    # The package prepaid three cycles and billed one, so the two cycles that were
    # never billed are voided rather than left PENDING.
    assert by_status.get("VOID", 0) == 2
    assert by_status.get("PENDING", 0) == 0


def test_the_issuance_response_and_the_pet_read_agree_while_the_certificate_is_effective(api):
    """The provisional and finalized readings of the pet's expiry coincide here.

    PRD §3.7: "The default period for a first-ever vaccination is the county-state
    default: a store registered in `CA` or `FL` defaults to 1095 days, and a store
    registered in `TX` or `NY` defaults to 365 days."
    PRD §3.7: "At the moment of issuance the pet's expiry is stamped provisionally
    from the certificate just written alone — its `expires_at` — without
    subtracting any previously effective certificate that the new issuance has
    superseded."
    PRD §3.7: "an `expires_at` equal to that instant plus the granted day count"
    PRD §3.7: "an `is_effective` flag that is true when the logical clock is at or
    before the expiry instant"

    Design: Corner/consistency_model/certificate_issuance_reports_the_provisional_expiry_before_the_final_read
    """
    world = setup_visit_with_certificate(api, state_code="TX")
    visit = world["visit"]

    assert visit["new_effective_days"] == 365
    assert visit["certificate_expires_at"] == "2027-09-21T09:00:00Z"
    assert visit["certificate_issued_at"] == "2026-09-21T09:00:00Z"
    assert visit["certificate_serial"].startswith("TX-2026-")

    pet = read_pet(api, world["pet"]["id"])
    assert pet["rabies_vaccination_expires_at"] == visit["certificate_expires_at"]

    certificates = read_visit_certificate(api, visit["id"])
    assert len(certificates) == 1
    assert certificates[0]["is_effective"] is True
    assert certificates[0]["effective_days"] == 365
    assert certificates[0]["expires_at"] == "2027-09-21T09:00:00Z"


def test_a_certificate_issued_under_a_california_store_defaults_to_three_years(api):
    """The one-year cap follows the prior certificate, not the issuing state.

    PRD §3.7: "a store registered in `CA` or `FL` defaults to 1095 days"
    PRD §3.7: "The cap therefore follows the prior certificate's own duration
    rather than the issuing store's state: a 365-day certificate issued in Texas
    renews for 365 days even when the renewal is written at a California store
    whose default is 1095 days."
    PRD §3.7: "A first-ever vaccination is never a booster, and its period is
    simply the state default."

    Design: Corner/consistency_model/certificate_issuance_reports_the_provisional_expiry_before_the_final_read
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    from test_helpers import create_clinic, create_visit, open_clinic, set_clock

    set_clock(api, "2026-09-21T09:00:00Z")
    clinic = create_clinic(api, store_id)
    clinic = open_clinic(api, store_id, clinic)
    visit = create_visit(api, store_id, clinic["id"], world["pet"]["id"], vaccine_type="RABIES")
    issued = issue_certificate(api, store_id, visit)

    assert issued["prior_rabies_vaccination_date"] is None
    assert issued["prior_effective_days"] is None
    assert issued["prior_is_booster"] is False
    assert issued["new_effective_days"] == 1095