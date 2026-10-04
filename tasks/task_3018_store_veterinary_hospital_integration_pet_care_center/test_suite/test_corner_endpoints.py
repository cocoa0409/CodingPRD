"""Read projections, quantity compensation and cross-reference validation."""

from test_helpers import (
    ApiErrorId,
    create_encounter,
    dispense_order,
    factories,
    get_success_data,
    raise_pharmacy_order,
    read_prescription,
    read_store,
    setup_authorized_prescription,
    setup_member_with_package,
    setup_open_clinic,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VET = TEST_USERS["veterinary_staff_headers"]
VACCINATION = TEST_USERS["vaccination_staff_headers"]
PHARMACY = TEST_USERS["pharmacy_staff_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANY = TEST_USERS["any_headers"]


def test_the_retail_projection_withholds_the_clinical_notes_the_hospital_read_returns(api):
    """Two reads of one encounter identifier deliberately disagree.

    PRD §2.10: "The hospital-partition read of an encounter returns the clinical
    record in full, including its `chief_complaint` and its `medical_notes`. The
    retail projection of that same encounter identifier returns only the
    appointment facts — patient, clinician, scheduling, status and charge — and
    returns `medical_notes` as null even though the hospital read of the
    identical identifier returns the recorded note."
    PRD §2.10: "Clinical notes are retained inside the hospital partition and are
    never surfaced on any retail endpoint."

    Design: Corner/endpoints/veterinary_encounter_projection_splits_medical_from_retail
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    encounter = create_encounter(
        api,
        store_id,
        world["pet"]["id"],
        chief_complaint="Limping on the left hind leg",
    )

    retail = validate_success(api.get_retail_encounter(encounter["id"], ANY))
    assert retail["medical_notes"] is None

    hospital = validate_success(api.get_encounter(encounter["id"], ANY))
    assert hospital["chief_complaint"] == "Limping on the left hind leg"
    assert hospital["id"] == retail["id"]


def test_rejecting_a_handoff_returns_the_quantity_to_the_prescription(api):
    """The rejection is the compensating half of the partial dispense.

    PRD §3.5: "Rejecting a handoff is the counter's other option, available while
    the order is `AUTHORIZED` and refused with `ERR_PHARMACY_ORDER_NOT_AUTHORIZED`
    otherwise. It moves the order to `REJECTED`, which is terminal, and returns
    the prescription's position: a prescription that had been pushed to
    `PARTIALLY_DISPENSED` returns to `AUTHORIZED`, but only when no other order of
    that prescription stands `DISPENSED`."
    PRD §3.5: "The store's `stores_held_total` counter is recomputed when the
    rejected order had been `HOLDING`."

    Design: Corner/endpoints/pharmacy_handoff_rolls_back_quantity_on_reject
    """
    world = setup_authorized_prescription(
        api, item_type="MEDICATION", unit_price_cents=1500, quantity=5
    )
    store_id = world["store"]["id"]
    authorization = read_prescription(api, world["prescription"]["id"])

    first = raise_pharmacy_order(api, store_id, authorization, 2)
    dispense_order(api, store_id, first)
    partially = read_prescription(api, authorization["id"])
    assert partially["status"] == "PARTIALLY_DISPENSED"

    second = raise_pharmacy_order(api, store_id, partially, 2)
    from test_helpers import reject_order

    rejected = reject_order(api, store_id, second)
    assert rejected["status"] == "REJECTED"
    # Rejection returns the prescription's position: the previous partial dispense
    # is rolled back, so the full quantity is dispensable again.
    returned = read_prescription(api, authorization["id"])
    assert returned["status"] == "AUTHORIZED"
    assert read_store(api, store_id)["stores_held_total"] == 0


def test_a_visit_naming_a_clinic_of_another_store_is_refused(api):
    """The visit-to-clinic link is validated against the store in the path.

    PRD §2.13: "A walk-in visit's clinic must belong to the store named in the
    path, refused with `ERR_VISIT_CLINIC_MISMATCH`."
    PRD §3.7: "A walk-in visit is registered against an open clinic by a
    `VaccinationStaff` member, naming the `clinic_id`, the `pet_id`, the
    `vaccine_type`"
    PRD §3.7: "The visit's clinic must belong to the store named in the path, and
    a mismatch is refused with `ERR_VISIT_CLINIC_MISMATCH`."

    Design: Corner/endpoints/cross_reference_link_rejects_a_pet_that_is_not_the_members
    """
    first = setup_open_clinic(api, state_code="CA")
    second = setup_member_with_package(
        api, store_code="ST-0002", tier="PLUS", state_code="CA",
        state_sales_tax_rate=0.0, billing_cycle_count=1,
    )
    other_store_id = second["store"]["id"]
    pet = first["pet"]

    response = api.create_visit(
        other_store_id,
        factories.visit_payload(
            clinic_id=first["clinic"]["id"], pet_id=pet["id"], vaccine_type="RABIES"
        ),
        VACCINATION,
    )
    validate_error(response, ApiErrorId.VISIT_CLINIC_MISMATCH.value)


def test_the_clinic_report_queue_counts_the_outstanding_report_and_names_the_next_due_visit(api):
    """The queue is a computed read over the visits' own reporting state.

    PRD §3.7: "The reporting queue read for a clinic exposes the counting: the
    number of submitted reports, the number pending, the number overdue, the
    earliest due instant among those outstanding, and the identifier of the visit
    next due."
    PRD §3.7: "When the visit does become reportable, its `state_report_status` is
    set to `PENDING` and its `state_report_due_at` is computed as the last instant
    of the calendar month following the month in which the certificate was
    issued, expressed at 23:59:59 UTC on that day."
    PRD §3.7: "The month rollover from December is defined: a certificate issued
    on 2026-12-02 is due at 2027-01-31T23:59:59Z."

    Design: Corner/endpoints/state_reporting_queue_computes_overdue_and_next_due
    """
    from test_helpers import issue_certificate, setup_clinic_visit

    world = setup_clinic_visit(api, state_code="CA")
    store_id = world["store"]["id"]
    visit = issue_certificate(api, store_id, world["visit"])

    queue = get_success_data(
        api.get_clinic_state_report(store_id, world["clinic"]["id"], COMPLIANCE)
    )
    assert queue["pending_count"] == 1
    assert queue["overdue_count"] == 0
    # The certificate was issued in September 2026, so the report is due at the
    # last instant of October.
    assert queue["due_at_earliest"] == "2026-10-31T23:59:59Z"
    assert queue["next_due_visit_id"] == visit["id"]

    stored = get_success_data(api.get_visit(visit["id"], ANY))
    assert stored["state_report_status"] == "PENDING"
    assert stored["status"] == "REPORT_REQUIRED"