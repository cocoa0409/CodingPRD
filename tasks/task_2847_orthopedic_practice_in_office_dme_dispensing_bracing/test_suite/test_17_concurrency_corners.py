"""The two optimistic-concurrency guards, each protecting a parent that is not
the endpoint's own output.

A reservation returns an encounter while the version it quotes belongs to the
shelf, and a beneficiary notice quotes the encounter's version because issuance
supersedes every notice already outstanding on it. Both comparisons are equality
tests, so a number from ahead of the store is refused exactly like one from
behind, and both refusals must leave their parent untouched.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ABN_ISSUED,
    ApiErrors,
    CLINICAL_DOCUMENTED,
    CLINICAL_RESERVED,
    FINANCIAL_ABN_ISSUED,
    FINANCIAL_NON_COVERED,
    POSTURE_OK,
    SUPERVISION_DIRECT,
    assert_encounter_states,
    assert_error,
    assert_list_meta,
    assert_money,
    assert_shelf,
    build_practice,
    create_clinic,
    create_patient,
    create_physician,
    create_supplier,
    insurance_coordinator_headers,
    inventory_manager_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
    read_encounter,
    read_shelf,
)
from test_helpers import factories as f


def test_a_reservation_quotes_the_shelf_version_and_only_the_exact_one_is_accepted(api):
    """One shelf of three units serves three encounters. The first reservation succeeds
    on a freshly read version and bumps the shelf, which strands the number the fitter
    was still holding; a version four ahead of the store is refused just as firmly; and
    after re-reading and reserving a second time the fitter's own success invalidates
    that number too. Two of five attempts land.

    PRD: "Reserving par stock for an encounter requires the request to carry
    `expected_par_level_version`, holding the `version` of the targeted
    `ClinicParLevel` as the fitter last observed it."

    PRD: "If that value does not equal the par level's current stored `version`, the
    reservation is rejected with `ERR_STALE_PAR_LEVEL_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_par_level_version_on_reservation_rejected
    """
    practice = build_practice(api, with_shelf=False)
    opened = validate_success(
        api.create_par_level(
            f.par_level_payload(practice.clinic_id, practice.product_id, par_min_qty=1, par_max_qty=20),
            inventory_manager_headers(),
        ),
        201,
    )
    assert opened["version"] == 1
    stocked = validate_success(
        api.receive_stock(opened["id"], f.stock_receipt_payload(3), inventory_manager_headers()), 201
    )
    assert stocked["version"] == 2
    assert_shelf(stocked, on_hand_qty=3, reserved_qty=0, available_qty=3, stock_posture=POSTURE_OK)
    practice.par_level_id = opened["id"]

    held_version = stocked["version"]
    encounter_a = practice.verified_encounter()
    encounter_b = practice.verified_encounter()
    encounter_c = practice.verified_encounter()

    reserved_a = validate_success(
        api.create_reservation(
            encounter_a, f.reservation_payload(held_version), practice.fitter_headers
        ),
        201,
    )
    assert_encounter_states(reserved_a, clinical_status=CLINICAL_RESERVED)

    after_a = read_shelf(api, opened["id"])
    assert_shelf(
        after_a, on_hand_qty=3, reserved_qty=1, available_qty=2, stock_posture=POSTURE_OK, version=3
    )

    # The number that worked one call earlier is now stale, even though two units
    # are demonstrably free.
    assert_error(
        api.create_reservation(
            encounter_b, f.reservation_payload(held_version), practice.fitter_headers
        ),
        ApiErrors.STALE_PAR_LEVEL_VERSION,
        412,
    )
    # Equality, not "at least": a version ahead of the store is equally invalid.
    assert_error(
        api.create_reservation(
            encounter_b, f.reservation_payload(after_a["version"] + 4), practice.fitter_headers
        ),
        ApiErrors.STALE_PAR_LEVEL_VERSION,
        412,
    )
    after_refusals = read_shelf(api, opened["id"])
    assert_shelf(
        after_refusals,
        on_hand_qty=3,
        reserved_qty=1,
        available_qty=2,
        stock_posture=POSTURE_OK,
        version=3,
    )

    reserved_b = validate_success(
        api.create_reservation(
            encounter_b,
            f.reservation_payload(after_refusals["version"]),
            practice.fitter_headers,
        ),
        201,
    )
    assert_encounter_states(reserved_b, clinical_status=CLINICAL_RESERVED)

    # The fitter's own success invalidated the number they were still holding.
    assert_error(
        api.create_reservation(
            encounter_c,
            f.reservation_payload(after_refusals["version"]),
            practice.fitter_headers,
        ),
        ApiErrors.STALE_PAR_LEVEL_VERSION,
        412,
    )
    assert_encounter_states(
        read_encounter(api, encounter_c), clinical_status=CLINICAL_DOCUMENTED
    )
    assert_shelf(
        read_shelf(api, opened["id"]),
        on_hand_qty=3,
        reserved_qty=2,
        available_qty=1,
        stock_posture=POSTURE_OK,
        version=4,
    )


def test_issuing_a_notice_quotes_the_encounter_version_a_third_party_can_move(api):
    """The bump that strands the coordinator comes from an unrelated actor: a second
    physician's supervision attestation touches nothing financial yet advances the
    guarded version. The stale number and an older one are both refused without
    creating a notice, the re-read number succeeds, and because the successful issue
    advances the version again the identical replay — which would have voided the notice
    just written — is refused.

    PRD: "Issuing an advance beneficiary notice requires the request to carry
    `expected_encounter_version`, holding the `version` of the target
    `DispenseEncounter` as the coordinator last observed it."

    PRD: "If that value does not equal the encounter's current stored `version`, the
    issuance is rejected with `ERR_STALE_ENCOUNTER_VERSION` and HTTP 412."

    PRD: "Issuance legitimately supersedes every earlier outstanding notice on the
    encounter, so without this guard the operation would succeed against a stale view
    and silently void a notice the coordinator never saw"

    Design: Corner/cross_cutting_complexity_layers/corner_stale_encounter_version_on_abn_issue_rejected
    """
    clinic = create_clinic(api, dispensing_specialties=["SPINE"])
    physician_a = create_physician(api, clinic["id"], full_name="Ora Vance", specialty="SPINE")
    physician_b = create_physician(api, clinic["id"], full_name="Dov Reyes", specialty="SPINE")
    patient = create_patient(api, clinic["id"])
    supplier = create_supplier(api)
    product = validate_success(
        api.create_product(f.product_payload(supplier["id"]), inventory_manager_headers()), 201
    )
    assert_money(product, "cash_price_cents", 11765)

    encounter = validate_success(
        api.create_encounter(
            f.encounter_payload(clinic["id"], patient["id"], product["id"], physician_a["id"]),
            practice_admin_headers(),
        ),
        201,
    )
    assert encounter["version"] == 1
    noted = validate_success(
        api.sign_medical_necessity_note(
            encounter["id"],
            f.medical_necessity_note_payload(),
            make_ortho_physician_headers(physician_a["id"]),
        ),
        201,
    )
    assert noted["version"] == 2
    validate_success(
        api.create_coverage_verification(
            encounter["id"],
            f.coverage_verification_payload(covered=False),
            insurance_coordinator_headers(),
        ),
        201,
    )
    read_version = read_encounter(api, encounter["id"])
    assert read_version["version"] == 3
    assert_encounter_states(read_version, financial_status=FINANCIAL_NON_COVERED)
    held_version = read_version["version"]

    # A third party moves the guarded version without touching anything financial.
    attested = validate_success(
        api.attest_ioas(
            encounter["id"],
            f.ioas_attestation_payload(SUPERVISION_DIRECT),
            make_ortho_physician_headers(physician_b["id"]),
        ),
        201,
    )
    assert attested["version"] == 4
    assert_encounter_states(attested, financial_status=FINANCIAL_NON_COVERED)

    assert_error(
        api.create_abn_notice(
            encounter["id"],
            f.abn_notice_payload(held_version),
            insurance_coordinator_headers(),
        ),
        ApiErrors.STALE_ENCOUNTER_VERSION,
        412,
    )
    assert_error(
        api.create_abn_notice(
            encounter["id"],
            f.abn_notice_payload(held_version - 1),
            insurance_coordinator_headers(),
        ),
        ApiErrors.STALE_ENCOUNTER_VERSION,
        412,
    )
    refreshed = read_encounter(api, encounter["id"])
    assert refreshed["version"] == 4
    assert_encounter_states(refreshed, financial_status=FINANCIAL_NON_COVERED)
    assert_list_meta(
        api.list_abn_notices(encounter["id"], insurance_coordinator_headers()), expected_total=0
    )

    notice = validate_success(
        api.create_abn_notice(
            encounter["id"],
            f.abn_notice_payload(refreshed["version"]),
            insurance_coordinator_headers(),
        ),
        201,
    )
    assert notice["notice_seq"] == 1
    assert notice["status"] == ABN_ISSUED
    assert_money(notice, "estimated_subtotal_cents", 11765)
    assert_money(notice, "dispensing_fee_cents", 2500)
    assert_money(notice, "estimated_cost_cents", 14265)

    # The successful issue advanced the version, so the identical replay is stale.
    assert_error(
        api.create_abn_notice(
            encounter["id"],
            f.abn_notice_payload(refreshed["version"]),
            insurance_coordinator_headers(),
        ),
        ApiErrors.STALE_ENCOUNTER_VERSION,
        412,
    )
    final = read_encounter(api, encounter["id"])
    assert final["version"] == 5
    assert_encounter_states(final, financial_status=FINANCIAL_ABN_ISSUED)
    assert_list_meta(
        api.list_abn_notices(encounter["id"], insurance_coordinator_headers()), expected_total=1
    )
