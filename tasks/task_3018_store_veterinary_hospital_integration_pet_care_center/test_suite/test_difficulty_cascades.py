"""Posture cascades that reach beyond the entity that was changed.

Two chains live here. The first runs from a store's posture through its clinic
and its visits to the certificates those visits issued and finally to the pet
that owns them. The second runs from an examination's completion through the
prescription it authorized to the pharmacy handoff waiting on it.
"""

from test_helpers import (
    EXAM_CHARGE_CENTS,
    check_in,
    complete_exam,
    create_encounter,
    create_prescription,
    get_success_data,
    raise_pharmacy_order,
    read_pet,
    read_prescription,
    read_store,
    read_visit,
    read_visit_certificate,
    restrict_store,
    saturate_to_capacity,
    setup_member_with_package,
    setup_visit_with_certificate,
    start_exam,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
VET = TEST_USERS["veterinary_staff_headers"]
PHARMACY = TEST_USERS["pharmacy_staff_headers"]


def test_restricting_a_store_blocks_the_visit_and_nulls_the_pet_expiry(api):
    """The posture change reaches the visit, then the certificate, then the pet.

    PRD §3.3: "Because freezing a clinic blocks the visits standing on it, each
    of those clinic's visits whose status is `REGISTERED`, `CERTIFICATE_ISSUED`
    or `REPORT_REQUIRED` moves to `BLOCKED`, and every rabies certificate
    belonging to a blocked visit has its `is_effective` flag set to false."
    PRD §3.3: "Each affected pet then has its `rabies_vaccination_expires_at`
    recomputed from the certificates that remain effective, which is null when
    none does."
    PRD §3.7: "A pet whose only certificate was suspended by a freeze therefore
    reports null on a read — no effective rabies protection — while the response
    to the issuance that created the certificate still reported a future expiry."

    Design: Difficulty/transitive_cascade/clinic_freeze_blocks_visits_and_invalidates_certificates
    """
    world = setup_visit_with_certificate(api, state_code="CA", hospital_capacity=1)
    store_id = world["store"]["id"]
    visit = world["visit"]

    # Before the posture change the certificate is effective and the pet read
    # reports the future expiry.
    assert visit["status"] == "REPORT_REQUIRED"
    assert read_pet(api, world["pet"]["id"])["rabies_vaccination_expires_at"] == visit[
        "certificate_expires_at"
    ]

    # The occupancy threshold has already been met by the SCHEDULED encounters.
    store = saturate_to_capacity(api, store_id, hospital_capacity=1)
    restrict_store(api, store_id, store["version"])

    assert read_visit(api, visit["id"])["status"] == "BLOCKED"
    assert read_pet(api, world["pet"]["id"])["rabies_vaccination_expires_at"] is None


def test_restricting_a_store_flips_the_certificate_effective_flag_without_moving_its_expiry(api):
    """The certificate keeps its expiry instant; only its effectiveness changes.

    PRD §3.7: "an `is_effective` flag that is true when the logical clock is at
    or before the expiry instant"
    PRD §3.3: "every rabies certificate belonging to a blocked visit has its
    `is_effective` flag set to false"
    PRD §3.7: "A pet whose only certificate was suspended by a freeze therefore
    reports null on a read"

    Design: Difficulty/transitive_cascade/clinic_freeze_blocks_visits_and_invalidates_certificates
    """
    world = setup_visit_with_certificate(api, state_code="CA", hospital_capacity=1)
    store_id = world["store"]["id"]
    visit = world["visit"]
    issued_expiry = visit["certificate_expires_at"]

    store = saturate_to_capacity(api, store_id, hospital_capacity=1)
    restrict_store(api, store_id, store["version"])

    certificates = read_visit_certificate(api, visit["id"])
    assert len(certificates) == 1
    assert certificates[0]["is_effective"] is False
    assert certificates[0]["expires_at"] == issued_expiry


def test_completing_an_exam_authorizes_the_prescription_and_releases_its_order(api):
    """The handoff moves to AUTHORIZED because the prescription did, not the exam.

    PRD §3.4: "Every prescription of that encounter still in `PENDING_EXAM` moves
    to `AUTHORIZED`, each stamped with an `authorized_at` instant, an
    `expires_at` computed from that instant plus the item-type window described
    in §3.5, and a `price_at_authorization_cents` equal to the prescribed
    `unit_price_cents` multiplied by the prescribed `quantity`."
    PRD §3.4: "Every pharmacy order linked to those prescriptions, currently
    sitting in `REQUESTED`, moves to `AUTHORIZED`, which is the release that lets
    the retail counter act."
    PRD §3.5: "a medication is valid for 30 days from authorization, a diet for
    90 days, and a treatment for 60 days."

    Design: Difficulty/transitive_cascade/exam_completion_authorizes_prescriptions_and_raises_pharmacy_orders
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="TX", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    pet_id = world["pet"]["id"]
    encounter = check_in(api, store_id, create_encounter(api, store_id, pet_id))
    encounter = start_exam(api, store_id, encounter)
    prescription = create_prescription(
        api, store_id, pet_id, encounter["id"],
        item_type="MEDICATION", unit_price_cents=3200, quantity=3,
    )
    encounter = complete_exam(api, store_id, encounter)

    authorization = read_prescription(api, prescription["id"])
    assert authorization["status"] == "AUTHORIZED"
    assert authorization["price_at_authorization_cents"] == 9600
    assert authorization["authorized_at"] is not None
    assert authorization["expires_at"] is not None
    # PRD §3.5 requires the prescription to be AUTHORIZED before the counter may
    # raise a handoff against it; the release of §3.4 is what lets that handoff
    # stand at the counter rather than being parked.
    order = raise_pharmacy_order(api, store_id, authorization, 3)
    released = get_success_data(api.get_pharmacy_order(order["id"], ADMIN))
    assert released["status"] == "AUTHORIZED"
    assert released["on_hold"] == "NONE"


def test_completing_an_exam_charges_the_encounter_for_the_authorized_prescription(api):
    """The completed encounter's charge is the exam charge plus the frozen price.

    PRD §3.4: "The encounter's `charge_total_cents` at the moment of completion
    is the examination charge plus the sum of `price_at_authorization_cents`
    across that encounter's prescriptions whose status is `AUTHORIZED` or
    `PARTIALLY_DISPENSED`."
    PRD §3.4: "The examination charge is a fixed 8500 cents."
    PRD §3.4: "its status becomes `COMPLETED`, the store's `hospital_occupancy`
    is recomputed and the store's version advanced."
    PRD §2.7: "Completed and cancelled encounters count toward neither figure."

    Design: Difficulty/transitive_cascade/exam_completion_authorizes_prescriptions_and_raises_pharmacy_orders
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="TX", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    pet_id = world["pet"]["id"]
    encounter = check_in(api, store_id, create_encounter(api, store_id, pet_id))
    encounter = start_exam(api, store_id, encounter)
    create_prescription(
        api, store_id, pet_id, encounter["id"],
        item_type="MEDICATION", unit_price_cents=3200, quantity=3,
    )
    before = read_store(api, store_id)
    encounter = complete_exam(api, store_id, encounter)

    assert encounter["status"] == "COMPLETED"
    assert encounter["charge_total_cents"] == EXAM_CHARGE_CENTS + 9600
    store = read_store(api, store_id)
    # PRD §2.7: "Completed and cancelled encounters count toward neither figure,"
    # so completing the examination releases the capacity slot it was holding.
    assert store["hospital_occupancy"] == 0
    assert store["version"] > before["version"]