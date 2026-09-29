"""Endpoint shapes: the create-read-list triangle on a clinic and its roster,
the supplier attestation action, the fabrication order as a two-ended link, and
the computed dispensing summary.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CATEGORY_CUSTOM_FABRICATED,
    CLINICAL_AWAITING_DEVICE,
    DEFAULT_LIMIT,
    DISPENSING_ACTIVE,
    FAB_SUBMITTED,
    FINANCIAL_UNVERIFIED,
    SUPERVISION_GENERAL,
    assert_calendar_date,
    assert_clinic_posture,
    assert_encounter_states,
    assert_identity_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_money,
    assert_unit_ledger_balances,
    assert_version_is,
    build_practice,
    compliance_officer_headers,
    create_clinic,
    create_supplier,
    inventory_manager_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
    read_clinic,
    read_encounter,
    read_summary,
    read_supplier,
)
from test_helpers import factories as f


def test_a_clinic_and_its_roster_agree_across_create_read_and_list(api):
    """A registered site echoes all six declared inputs, seeds its two computed
    fields before any shelf exists, and its roster lists only its own
    physicians, narrows by specialty and pages inside that filter.

    PRD: "A clinic's physician roster can be listed and optionally narrowed by
    `specialty`." ... "Both are reflected back in the `meta` object of the
    response alongside `total_count`, the number of rows matching the filter
    before paging is applied, and `has_more`, a boolean that is true when rows
    remain beyond the current page."

    Design: Corner/endpoints/corner_clinic_and_roster_create_read_list_round_trip
    """
    created = validate_success(
        api.create_clinic(
            f.clinic_payload(
                name="Riverbend Orthopedics",
                state_code="OH",
                accreditation_body="BOC",
                accreditation_expires_on="2027-06-30",
                ioas_supervision_level=SUPERVISION_GENERAL,
                dispensing_specialties=["SPINE", "HAND"],
            ),
            practice_admin_headers(),
        ),
        201,
    )
    assert_identity_fields(created, expected_version=1)
    assert created["name"] == "Riverbend Orthopedics"
    assert created["state_code"] == "OH"
    assert created["accreditation_body"] == "BOC"
    assert created["accreditation_expires_on"] == "2027-06-30"
    assert created["ioas_supervision_level"] == SUPERVISION_GENERAL
    assert created["dispensing_specialties"] == ["SPINE", "HAND"]
    assert_clinic_posture(
        created, dispensing_status=DISPENSING_ACTIVE, stockout_par_level_count=0
    )
    assert_clinic_posture(
        read_clinic(api, created["id"]),
        dispensing_status=DISPENSING_ACTIVE,
        stockout_par_level_count=0,
    )

    other_clinic = create_clinic(api, name="Lakeside Orthopedics")
    spine_one = validate_success(
        api.create_physician(
            created["id"],
            f.physician_payload(full_name="Ora Vance", specialty="SPINE"),
            practice_admin_headers(),
        ),
        201,
    )
    spine_two = validate_success(
        api.create_physician(
            created["id"],
            f.without(
                f.physician_payload(full_name="Dov Reyes", specialty="SPINE"),
                "group_member",
                "stark_disclosure_on_file",
            ),
            practice_admin_headers(),
        ),
        201,
    )
    validate_success(
        api.create_physician(
            created["id"],
            f.physician_payload(full_name="Nia Frost", specialty="HAND"),
            practice_admin_headers(),
        ),
        201,
    )

    assert spine_one["clinic_id"] == created["id"]
    assert spine_two["group_member"] is True
    assert spine_two["stark_disclosure_on_file"] is False

    assert_list_meta(
        api.list_physicians(created["id"], practice_admin_headers()),
        expected_total=3,
        expected_limit=DEFAULT_LIMIT,
        expected_offset=0,
        expected_has_more=False,
    )
    spine_rows, _spine_meta = assert_list_meta(
        api.list_physicians(created["id"], practice_admin_headers(), {"specialty": "SPINE"}),
        expected_total=2,
        expected_has_more=False,
    )
    assert {row["id"] for row in spine_rows} == {spine_one["id"], spine_two["id"]}
    paged_rows, _paged_meta = assert_list_meta(
        api.list_physicians(
            created["id"],
            make_ortho_physician_headers(spine_one["id"]),
            {"specialty": "SPINE", "limit": 1, "offset": 1},
        ),
        expected_total=2,
        expected_limit=1,
        expected_offset=1,
        expected_has_more=False,
    )
    assert len(paged_rows) == 1
    assert_list_meta(
        api.list_physicians(other_clinic["id"], practice_admin_headers()), expected_total=0
    )


def test_the_standards_attestation_action_updates_only_what_it_is_given(api):
    """Two attestations flip the two required booleans, leave the accreditation
    date alone when it is omitted and replace it when it is supplied, never
    touch the fabrication capability or the computed turnaround pair, and each
    advances the supplier's version exactly once.

    PRD: "That operation carries `dmepos_standards_attested` and `quality_hold`
    as required inputs and an optional `accreditation_expires_on` that replaces
    the stored date when supplied, and it answers 200 OK with the updated
    supplier."

    Design: Corner/endpoints/corner_standards_attestation_action_toggles_supplier_posture
    """
    supplier = create_supplier(
        api, accreditation_expires_on="2027-03-31", promised_turnaround_days=12
    )
    assert_version_is(supplier, 1, "supplier")
    assert supplier["turnaround_score"] == 100
    assert supplier["accepted_fab_order_count"] == 0

    held = validate_success(
        api.standards_attestation(
            supplier["id"],
            f.standards_attestation_payload(dmepos_standards_attested=False, quality_hold=True),
            compliance_officer_headers(),
        ),
        200,
    )
    assert held["dmepos_standards_attested"] is False
    assert held["quality_hold"] is True
    assert held["accreditation_expires_on"] == "2027-03-31"
    assert held["custom_fab_capable"] is True
    assert held["turnaround_score"] == 100
    assert held["accepted_fab_order_count"] == 0
    assert_version_is(held, 2, "supplier")

    cleared = validate_success(
        api.standards_attestation(
            supplier["id"],
            f.standards_attestation_payload(
                dmepos_standards_attested=True,
                quality_hold=False,
                accreditation_expires_on="2028-03-31",
            ),
            compliance_officer_headers(),
        ),
        200,
    )
    assert cleared["dmepos_standards_attested"] is True
    assert cleared["quality_hold"] is False
    assert cleared["accreditation_expires_on"] == "2028-03-31"
    assert_version_is(cleared, 3, "supplier")

    stored = read_supplier(api, supplier["id"])
    assert stored["dmepos_standards_attested"] is True
    assert stored["quality_hold"] is False
    assert stored["accreditation_expires_on"] == "2028-03-31"
    assert stored["promised_turnaround_days"] == 12


def test_a_fabrication_order_is_navigable_from_both_of_its_two_ends(api):
    """The order takes its encounter from the path and its supplier from the
    body, snapshots the promise of the supplier that was actually named rather
    than the product's own supplier, and is listable from either end while
    staying invisible under a supplier that was never asked.

    PRD: "`promised_turnaround_days_snapshot`, copied from the supplier's
    `promised_turnaround_days`, and `promised_delivery_on`, derived as the
    calendar date of `submitted_at` advanced by that many whole days." ...
    "Fabrication orders can be read individually — an unresolvable identifier
    yields `ERR_FAB_ORDER_NOT_FOUND` — and listed with optional `encounter_id`,
    `supplier_id` and `status` filters."

    Design: Corner/endpoints/corner_custom_fab_order_links_encounter_and_supplier
    """
    practice = build_practice(
        api,
        supplier={"promised_turnaround_days": 10},
        product_factory=lambda supplier_id: f.product_payload(
            supplier_id,
            hcpcs_code="L1940",
            description="Ankle foot orthosis, custom fabricated",
            category=CATEGORY_CUSTOM_FABRICATED,
            specialty="HAND",
            same_or_similar_group="AFO_CUSTOM",
            allowed_amount_cents=42000,
            cash_price_cents=49999,
            unit_cost_cents=20000,
        ),
        with_shelf=False,
    )
    fabricator = create_supplier(
        api, name="Meridian Fabrication", promised_turnaround_days=25
    )
    encounter_id = practice.documented_encounter()

    order = validate_success(
        api.create_custom_fab_order(
            encounter_id, f.custom_fab_order_payload(fabricator["id"]), practice.fitter_headers
        ),
        201,
    )

    assert order["encounter_id"] == encounter_id
    assert order["supplier_id"] == fabricator["id"]
    assert order["status"] == FAB_SUBMITTED
    assert_version_is(order, 1, "fabrication order")
    assert_instant_equals(order["submitted_at"], "2026-08-01T00:00:00Z")
    assert order["promised_turnaround_days_snapshot"] == 25
    assert_calendar_date(order["promised_delivery_on"], "promised_delivery_on")
    assert order["promised_delivery_on"] == "2026-08-26"
    assert order["adjustment_rounds"] == 0
    assert order["first_delivered_at"] is None
    assert order["projected_turnaround_score"] is None

    by_encounter, _by_encounter_meta = assert_list_meta(
        api.list_custom_fab_orders(inventory_manager_headers(), {"encounter_id": encounter_id}),
        expected_total=1,
    )
    assert by_encounter[0]["id"] == order["id"]
    by_supplier, _by_supplier_meta = assert_list_meta(
        api.list_custom_fab_orders(
            inventory_manager_headers(),
            {"supplier_id": fabricator["id"], "status": FAB_SUBMITTED},
        ),
        expected_total=1,
    )
    assert by_supplier[0]["id"] == order["id"]
    assert_list_meta(
        api.list_custom_fab_orders(
            inventory_manager_headers(), {"supplier_id": practice.supplier_id}
        ),
        expected_total=0,
    )

    encounter = read_encounter(api, encounter_id)
    assert_encounter_states(
        encounter,
        clinical_status=CLINICAL_AWAITING_DEVICE,
        financial_status=FINANCIAL_UNVERIFIED,
    )
    assert_version_is(encounter, 3, "encounter")


def test_the_dispensing_summary_reports_all_fourteen_fields_in_agreement(api):
    """Four readings of the same clinic — stocked, reserved, delivered and
    restocked — each report every declared field, and the two ledger identities
    hold at each of them: a reserved unit is a subset of on-hand rather than an
    addend, and a restocked unit is counted twice and netted once.

    PRD: "`units_accounted_total` is then `units_on_hand_total` plus
    `units_dispensed_total` less `units_restocked_total`." ...
    "`net_cash_position_cents` is `gross_charged_cents` less `refunded_cents`."

    Design: Corner/endpoints/corner_dispensing_summary_computed_read_reports_every_declared_field
    """
    practice = build_practice(
        api, par_level={"par_min_qty": 2, "par_max_qty": 20}, received_qty=5
    )

    stocked = read_summary(api, practice.clinic_id)
    assert stocked["clinic_id"] == practice.clinic_id
    assert stocked["dispensing_status"] == DISPENSING_ACTIVE
    assert stocked["stockout_par_level_count"] == 0
    assert stocked["units_received_total"] == 5
    assert stocked["units_on_hand_total"] == 5
    assert stocked["units_reserved_total"] == 0
    assert stocked["units_dispensed_total"] == 0
    assert stocked["units_restocked_total"] == 0
    assert stocked["units_destroyed_total"] == 0
    assert stocked["units_accounted_total"] == 5
    assert_money(stocked, "gross_charged_cents", 0)
    assert_money(stocked, "refunded_cents", 0)
    assert_money(stocked, "restock_fee_retained_cents", 0)
    assert_money(stocked, "net_cash_position_cents", 0)
    assert_unit_ledger_balances(stocked)

    encounter_id = practice.verified_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    practice.reserve(encounter_id)

    reserved = read_summary(api, practice.clinic_id)
    assert reserved["units_reserved_total"] == 1
    assert reserved["units_on_hand_total"] == 5
    assert reserved["units_dispensed_total"] == 0
    assert reserved["units_accounted_total"] == 5
    assert_money(reserved, "gross_charged_cents", 0)
    assert_unit_ledger_balances(reserved)

    practice.fit(encounter_id, "2026-08-01T09:00:00Z", "2026-08-01T09:45:00Z")
    delivered = practice.dispense(encounter_id)
    assert_money(delivered, "patient_responsibility_cents", 10300)

    handed_over = read_summary(api, practice.clinic_id)
    assert handed_over["units_on_hand_total"] == 4
    assert handed_over["units_reserved_total"] == 0
    assert handed_over["units_dispensed_total"] == 1
    assert handed_over["units_restocked_total"] == 0
    assert handed_over["units_accounted_total"] == 5
    assert_money(handed_over, "gross_charged_cents", 10300)
    assert_money(handed_over, "refunded_cents", 0)
    assert_money(handed_over, "net_cash_position_cents", 10300)
    assert_unit_ledger_balances(handed_over)

    opened = practice.open_return(
        encounter_id, reason="POOR_FIT", return_note="rides up when seated"
    )
    inspected = practice.inspect_return(opened["id"], condition="SELLABLE")
    assert_money(inspected, "refund_cents", 9348)
    assert_money(inspected, "restock_fee_cents", 952)

    restocked = read_summary(api, practice.clinic_id)
    assert restocked["dispensing_status"] == DISPENSING_ACTIVE
    assert restocked["stockout_par_level_count"] == 0
    assert restocked["units_received_total"] == 5
    assert restocked["units_on_hand_total"] == 5
    assert restocked["units_reserved_total"] == 0
    assert restocked["units_dispensed_total"] == 1
    assert restocked["units_restocked_total"] == 1
    assert restocked["units_destroyed_total"] == 0
    assert restocked["units_accounted_total"] == 5
    assert_money(restocked, "gross_charged_cents", 10300)
    assert_money(restocked, "refunded_cents", 9348)
    assert_money(restocked, "restock_fee_retained_cents", 952)
    assert_money(restocked, "net_cash_position_cents", 952)
    assert restocked["net_cash_position_cents"] == restocked["restock_fee_retained_cents"]
    assert_unit_ledger_balances(restocked)
