"""Peer segregation of duties: no role outranks another.

Each denial below is a request that is correct in every respect except the
acting role, so the only possible answer is the authorization refusal. The
shared grants are then shown to be symmetric between their declared holders and
enumerated per endpoint rather than inherited, and the one rule that compares
the acting identity against a stored field is exercised in both directions.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    CLINICAL_DOCUMENTED,
    CLINICAL_DRAFT,
    FINANCIAL_UNVERIFIED,
    POSTURE_STOCKOUT,
    SUPERVISION_DIRECT,
    SUPERVISION_GENERAL,
    assert_encounter_states,
    assert_error,
    assert_instant_equals,
    assert_list_meta,
    assert_shelf,
    build_practice,
    compliance_officer_headers,
    create_clinic,
    create_fitter,
    create_patient,
    create_physician,
    create_supplier,
    error_id_of,
    insurance_coordinator_headers,
    inventory_manager_headers,
    make_dme_fitter_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
    read_encounter,
    read_shelf,
)
from test_helpers import factories as f

NO_SUCH_RETURN = "99999999-9999-4999-8999-999999999979"


def test_each_exclusive_operation_refuses_every_role_but_its_own(api):
    """Seven otherwise-valid requests are each sent by a peer role that does not hold
    the endpoint, and all seven answer with the same authorization refusal — including
    one whose target identifier is also unresolvable, which proves the role check runs
    before existence is even consulted.

    PRD: "The `Authorized Role(s)` column is exhaustive: any other role receives
    `ERR_UNAUTHORIZED`, and role checking precedes every other check on the request."

    PRD: "If the role is recognised but is not among the roles authorised for the
    endpoint being called (see the table in §4), the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/corner_exclusive_operations_denied_to_every_other_role_rejected
    """
    practice = build_practice(api, received_qty=4)
    encounter_id = practice.documented_encounter()
    shelf_before = read_shelf(api, practice.par_level_id)

    # Master data belongs to the administrator; standards attestation does not.
    assert_error(
        api.create_clinic(f.clinic_payload(name="Shadow Ortho"), inventory_manager_headers()),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.standards_attestation(
            practice.supplier_id,
            f.standards_attestation_payload(dmepos_standards_attested=False, quality_hold=True),
            practice_admin_headers(),
        ),
        ApiErrors.UNAUTHORIZED,
        403,
    )

    # Stock custody is refused in both directions.
    assert_error(
        api.create_par_level(
            f.par_level_payload(practice.clinic_id, practice.product_id, par_min_qty=1, par_max_qty=5),
            practice_admin_headers(),
        ),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.receive_stock(practice.par_level_id, f.stock_receipt_payload(2), practice.fitter_headers),
        ApiErrors.UNAUTHORIZED,
        403,
    )

    # The financial and clinical steps are each held by exactly one peer.
    assert_error(
        api.create_coverage_verification(
            encounter_id,
            f.coverage_verification_payload(coinsurance_pct=0.5),
            practice_admin_headers(),
        ),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.sign_medical_necessity_note(
            encounter_id,
            f.medical_necessity_note_payload(mn_functional_deficit="second opinion"),
            compliance_officer_headers(),
        ),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_reservation(
            encounter_id,
            f.reservation_payload(shelf_before["version"]),
            inventory_manager_headers(),
        ),
        ApiErrors.UNAUTHORIZED,
        403,
    )

    # The role check precedes existence, so an unknown return id is still a 403.
    inspection = api.inspect_return(
        NO_SUCH_RETURN, f.inspection_payload(), practice.fitter_headers
    )
    assert_error(inspection, ApiErrors.UNAUTHORIZED, 403)
    assert error_id_of(inspection) != ApiErrors.RETURN_NOT_FOUND

    # No denial mutated anything.
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=4,
        reserved_qty=0,
        available_qty=4,
        version=shelf_before["version"],
    )
    assert_list_meta(
        api.list_par_levels(inventory_manager_headers(), {"clinic_id": practice.clinic_id}),
        expected_total=1,
    )
    assert_encounter_states(
        read_encounter(api, encounter_id),
        clinical_status=CLINICAL_DOCUMENTED,
        financial_status=FINANCIAL_UNVERIFIED,
    )


def test_the_three_shared_writes_treat_both_of_their_holders_identically(api):
    """Patient registration, catalog entry and encounter creation each have two
    declared holders, and the second holder gets the same 201 and the same body as
    the first. The shelf read is granted to three roles and returns one body, while
    the patient roster and the dispensing summary each refuse a role that holds
    neighbouring reads — so a grant is enumerated per endpoint, not by rank.

    PRD: "The `Authorized Role(s)` column is exhaustive: any other role receives
    `ERR_UNAUTHORIZED`, and role checking precedes every other check on the request."

    PRD: "Opens a dispensing encounter in the draft and unverified postures;
    `service_date` defaults to the logical clock date."

    Design: Corner/rbac/corner_shared_operations_accepted_from_every_declared_holder
    """
    clinic = create_clinic(api)
    physician = create_physician(api, clinic["id"], full_name="Ora Vance", specialty="SPINE")
    fitter = create_fitter(api, clinic["id"])
    supplier = create_supplier(api)

    # Patient registration: the administrator and the coordinator, symmetrically.
    patient_1 = validate_success(
        api.create_patient(
            clinic["id"],
            f.patient_payload(full_name="Pat Oro", dob="1965-01-01", payer_type="COMMERCIAL"),
            practice_admin_headers(),
        ),
        201,
    )
    patient_2 = validate_success(
        api.create_patient(
            clinic["id"],
            f.patient_payload(
                full_name="Sam Iles",
                dob="1948-04-04",
                payer_type="MEDICARE",
                medicare_beneficiary=True,
            ),
            insurance_coordinator_headers(),
        ),
        201,
    )
    assert patient_1["clinic_id"] == patient_2["clinic_id"] == clinic["id"]
    assert patient_2["payer_type"] == "MEDICARE"
    assert patient_2["medicare_beneficiary"] is True

    # Catalog entry: the administrator and the inventory manager.
    product_1 = validate_success(
        api.create_product(
            f.product_payload(supplier["id"], description="LSO brace admin-entered"),
            practice_admin_headers(),
        ),
        201,
    )
    product_2 = validate_success(
        api.create_product(
            f.product_payload(
                supplier["id"],
                hcpcs_code="L0631",
                description="LSO brace inventory-entered",
                same_or_similar_group="LSO_BRACE_ALT",
                allowed_amount_cents=18000,
                cash_price_cents=9900,
                unit_cost_cents=5200,
            ),
            inventory_manager_headers(),
        ),
        201,
    )
    assert product_2["supplier_id"] == supplier["id"]

    # Encounter creation: the administrator and the ordering physician.
    encounter_1 = validate_success(
        api.create_encounter(
            f.encounter_payload(clinic["id"], patient_1["id"], product_1["id"], physician["id"]),
            practice_admin_headers(),
        ),
        201,
    )
    encounter_2 = validate_success(
        api.create_encounter(
            f.encounter_payload(clinic["id"], patient_2["id"], product_2["id"], physician["id"]),
            make_ortho_physician_headers(physician["id"]),
        ),
        201,
    )
    for encounter in (encounter_1, encounter_2):
        assert_encounter_states(
            encounter, clinical_status=CLINICAL_DRAFT, financial_status=FINANCIAL_UNVERIFIED
        )
    assert encounter_2["ordering_physician_id"] == physician["id"]
    assert encounter_2["patient_id"] == patient_2["id"]
    assert encounter_2["product_id"] == product_2["id"]

    # One shared read, three holders, one body.
    shelf = validate_success(
        api.create_par_level(
            f.par_level_payload(clinic["id"], product_1["id"], par_min_qty=2, par_max_qty=20),
            inventory_manager_headers(),
        ),
        201,
    )
    postures = [
        validate_success(api.get_par_level(shelf["id"], headers), 200)["stock_posture"]
        for headers in (
            inventory_manager_headers(),
            make_dme_fitter_headers(fitter["id"]),
            practice_admin_headers(),
        )
    ]
    assert postures == [POSTURE_STOCKOUT, POSTURE_STOCKOUT, POSTURE_STOCKOUT]

    # Reads are not inherited: the fitter holds the fitter roster but not the
    # patient roster, and the coordinator is not a holder of the summary.
    assert_error(
        api.list_patients(clinic["id"], make_dme_fitter_headers(fitter["id"])),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.get_dispensing_summary(clinic["id"], insurance_coordinator_headers()),
        ApiErrors.UNAUTHORIZED,
        403,
    )
    assert_list_meta(
        api.list_patients(clinic["id"], insurance_coordinator_headers()), expected_total=2
    )


def test_the_ordering_physician_is_never_the_attester_of_their_own_supervision(api):
    """The same body, the same role and the same clinic are refused for the ordering
    physician and accepted for a second group physician added afterwards. The refusal
    writes nothing and does not bump the version, the second physician may attest
    again to correct the observed level, and the rule is re-evaluated on every request
    rather than being satisfied by the earlier valid attestation.

    PRD: "The physician who attests in-office ancillary-services supervision must not
    be the encounter's ordering physician — supervision of a self-referral is attested
    by a *second* group physician — and an attempt by the ordering physician to attest
    their own encounter is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 409."

    PRD: "The attestation stamps `ioas_attesting_physician_id` with the acting
    physician's identity, `ioas_attested_at` with the logical clock instant, and the
    observed level from the body, and it advances the encounter's `version` by 1 — but
    it moves **neither** state dimension"

    PRD: "Because the attestation may be replayed, a physician who recorded the wrong
    level can simply attest again and overwrite the observed level and instant."

    Design: Corner/rbac/corner_ordering_physician_cannot_attest_own_supervision_rejected
    """
    clinic = create_clinic(api, dispensing_specialties=["SPINE"], ioas_supervision_level=SUPERVISION_DIRECT)
    physician_a = create_physician(api, clinic["id"], full_name="Ora Vance", specialty="SPINE")
    patient = create_patient(api, clinic["id"])
    supplier = create_supplier(api)
    product = validate_success(
        api.create_product(f.product_payload(supplier["id"]), inventory_manager_headers()), 201
    )
    encounter = validate_success(
        api.create_encounter(
            f.encounter_payload(clinic["id"], patient["id"], product["id"], physician_a["id"]),
            practice_admin_headers(),
        ),
        201,
    )
    documented = validate_success(
        api.sign_medical_necessity_note(
            encounter["id"],
            f.medical_necessity_note_payload(),
            make_ortho_physician_headers(physician_a["id"]),
        ),
        201,
    )
    assert_encounter_states(documented, clinical_status=CLINICAL_DOCUMENTED)
    assert documented["version"] == 2

    assert_error(
        api.attest_ioas(
            encounter["id"],
            f.ioas_attestation_payload(SUPERVISION_DIRECT),
            make_ortho_physician_headers(physician_a["id"]),
        ),
        ApiErrors.SEGREGATION_OF_DUTIES,
        409,
    )

    after_denial = validate_success(
        api.get_encounter(encounter["id"], compliance_officer_headers()), 200
    )
    assert after_denial["ioas_attested_at"] is None
    assert after_denial["ioas_attesting_physician_id"] is None
    assert after_denial["version"] == 2

    physician_b = create_physician(api, clinic["id"], full_name="Vito Ames", specialty="SPINE")
    attested = validate_success(
        api.attest_ioas(
            encounter["id"],
            f.ioas_attestation_payload(SUPERVISION_GENERAL),
            make_ortho_physician_headers(physician_b["id"]),
        ),
        201,
    )
    assert attested["ioas_attesting_physician_id"] == physician_b["id"]
    assert attested["ioas_supervision_level_observed"] == SUPERVISION_GENERAL
    assert_instant_equals(attested["ioas_attested_at"], "2026-08-01T00:00:00Z", "ioas_attested_at")
    assert attested["version"] == 3

    corrected = validate_success(
        api.attest_ioas(
            encounter["id"],
            f.ioas_attestation_payload(SUPERVISION_DIRECT),
            make_ortho_physician_headers(physician_b["id"]),
        ),
        201,
    )
    assert corrected["ioas_attesting_physician_id"] == physician_b["id"]
    assert corrected["ioas_supervision_level_observed"] == SUPERVISION_DIRECT
    assert corrected["version"] == 4

    assert_error(
        api.attest_ioas(
            encounter["id"],
            f.ioas_attestation_payload(SUPERVISION_DIRECT),
            make_ortho_physician_headers(physician_a["id"]),
        ),
        ApiErrors.SEGREGATION_OF_DUTIES,
        409,
    )

    final = read_encounter(api, encounter["id"])
    assert_encounter_states(
        final, clinical_status=CLINICAL_DOCUMENTED, financial_status=FINANCIAL_UNVERIFIED
    )
    assert final["version"] == 4
