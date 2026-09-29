"""Rejections that the contract pins to a named error and an exact status.

Each test drives one family of guards from a fixture that satisfies everything
else, so the identifier the server answers with is the only thing under test,
and each also shows that the refused request left the entities it touched
exactly as they were.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    ApiErrors,
    CATEGORY_CUSTOM_FABRICATED,
    CLINICAL_DELIVERED,
    CLINICAL_DOCUMENTED,
    CLINICAL_DRAFT,
    CLINICAL_FITTED,
    CLINICAL_RESERVED,
    DISPENSING_RESTRICTED,
    DISPENSING_SUSPENDED,
    FINANCIAL_ABN_ISSUED,
    FINANCIAL_AUTH_APPROVED,
    FINANCIAL_BILLED,
    FINANCIAL_UNVERIFIED,
    FINANCIAL_VERIFIED,
    HOLD_CLINIC_SUSPENDED,
    PA_PENDED,
    PA_SUBMITTED,
    POSTURE_OK,
    POSTURE_STOCKOUT,
    RETURN_DESTROYED,
    RETURN_REFIT_ISSUED,
    RETURN_REQUESTED,
    RETURN_RESTOCKED,
    SCOPE_OFF_SHELF_ONLY,
    SUPERVISION_DIRECT,
    SUPERVISION_GENERAL,
    add_fitter,
    add_patient,
    add_physician,
    add_product,
    add_shelf,
    assert_clinic_posture,
    assert_compliance_hold,
    assert_encounter_states,
    assert_error,
    assert_instant_equals,
    assert_list_meta,
    assert_money,
    assert_responsibility,
    assert_shelf,
    build_practice,
    create_clinic,
    create_physician,
    insurance_coordinator_headers,
    inventory_manager_headers,
    make_dme_fitter_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
    read_clinic,
    read_encounter,
    read_shelf,
    set_clock,
    shelf_version,
)
from test_helpers import factories as f


def test_shelf_creation_and_receipt_guards_each_reject_on_their_own(api):
    """Four shelf guards fire from one stocked shelf: the clinic-and-product
    uniqueness rule, the minimum-above-maximum rule, the refusal to stock a
    fabricated-to-order device, and a receipt whose overshoot is only visible
    once the units already on the shelf are added in.

    PRD: "At most one par level may exist per clinic-and-product pair, and a
    second attempt at the same pair is refused with `ERR_DUPLICATE_PAR_LEVEL`
    and HTTP 409." ... "A receipt may not push `on_hand_qty` above
    `par_max_qty`; one that would is refused with `ERR_PAR_MAX_EXCEEDED`."

    Design: Corner/validations/corner_par_level_creation_and_receipt_constraints_rejected
    """
    practice = build_practice(api, received_qty=6)
    spare = add_product(practice, f.cervical_collar_product_payload(practice.supplier_id))
    fabricated = add_product(
        practice,
        f.product_payload(
            practice.supplier_id,
            hcpcs_code="L1940",
            description="Ankle foot orthosis, custom fabricated",
            category=CATEGORY_CUSTOM_FABRICATED,
            same_or_similar_group="AFO_CUSTOM",
            allowed_amount_cents=42000,
            cash_price_cents=49999,
            unit_cost_cents=20000,
        ),
    )
    before = read_shelf(api, practice.par_level_id)
    assert_shelf(before, on_hand_qty=6, stock_posture=POSTURE_OK)

    assert_error(
        api.create_par_level(
            f.par_level_payload(
                practice.clinic_id, practice.product_id, par_min_qty=2, par_max_qty=30
            ),
            inventory_manager_headers(),
        ),
        ApiErrors.DUPLICATE_PAR_LEVEL,
        409,
    )
    assert_error(
        api.create_par_level(
            f.par_level_payload(practice.clinic_id, spare["id"], par_min_qty=25, par_max_qty=20),
            inventory_manager_headers(),
        ),
        ApiErrors.PAR_MAX_EXCEEDED,
        422,
    )
    assert_error(
        api.create_par_level(
            f.par_level_payload(
                practice.clinic_id, fabricated["id"], par_min_qty=1, par_max_qty=5
            ),
            inventory_manager_headers(),
        ),
        ApiErrors.PRODUCT_CATEGORY_MISMATCH,
        422,
    )
    assert_error(
        api.receive_stock(
            practice.par_level_id, f.stock_receipt_payload(21), inventory_manager_headers()
        ),
        ApiErrors.PAR_MAX_EXCEEDED,
        422,
    )

    after = read_shelf(api, practice.par_level_id)
    assert_shelf(after, on_hand_qty=6, version=before["version"])


def test_a_receipt_that_lands_exactly_on_par_max_is_accepted(api):
    """The stocking ceiling is inclusive, so a receipt that brings a brand-new
    shelf to precisely its maximum is accepted and fixes every derived quantity
    in the same response.

    PRD: "A receipt may not push `on_hand_qty` above `par_max_qty`; one that
    would is refused with `ERR_PAR_MAX_EXCEEDED`." ... "A receipt adds that
    quantity to both `on_hand_qty` and `lifetime_received_qty` and advances the
    shelf's `version` by 1."

    Design: Corner/validations/corner_stock_receipt_to_exactly_par_max_succeeds
    """
    practice = build_practice(api, with_shelf=False)
    opened = validate_success(
        api.create_par_level(
            f.par_level_payload(practice.clinic_id, practice.product_id),
            inventory_manager_headers(),
        ),
        201,
    )
    assert_shelf(opened, on_hand_qty=0, stock_posture=POSTURE_STOCKOUT, version=1)

    received = validate_success(
        api.receive_stock(opened["id"], f.stock_receipt_payload(20), inventory_manager_headers()),
        201,
    )

    assert_shelf(
        received,
        on_hand_qty=20,
        reserved_qty=0,
        available_qty=20,
        lifetime_received_qty=20,
        stock_posture=POSTURE_OK,
        version=2,
    )


def test_an_npi_already_used_anywhere_in_the_practice_is_refused(api):
    """The same identifier is refused both at the clinic that already holds it
    and at a second clinic, while a different identifier is accepted for the
    very same name at the first clinic.

    PRD: "The identifier is unique practice-wide: creating a physician whose
    `npi` already exists anywhere in the practice is refused with
    `ERR_DUPLICATE_NPI` and HTTP 409."

    Design: Corner/validations/corner_duplicate_npi_across_the_whole_practice_rejected
    """
    clinic_a = create_clinic(api, name="North Ortho")
    clinic_b = create_clinic(api, name="South Ortho")
    create_physician(api, clinic_a["id"], full_name="Ora Vance", npi="1700000301")

    assert_error(
        api.create_physician(
            clinic_a["id"],
            f.physician_payload(full_name="Ora Vance II", npi="1700000301"),
            practice_admin_headers(),
        ),
        ApiErrors.DUPLICATE_NPI,
        409,
    )
    assert_error(
        api.create_physician(
            clinic_b["id"],
            f.physician_payload(full_name="Ora Vance", npi="1700000301"),
            practice_admin_headers(),
        ),
        ApiErrors.DUPLICATE_NPI,
        409,
    )

    accepted = validate_success(
        api.create_physician(
            clinic_a["id"],
            f.physician_payload(full_name="Ora Vance", npi="1700000302"),
            practice_admin_headers(),
        ),
        201,
    )
    assert accepted["npi"] == "1700000302"
    assert_list_meta(api.list_physicians(clinic_a["id"], practice_admin_headers()), expected_total=2)
    assert_list_meta(api.list_physicians(clinic_b["id"], practice_admin_headers()), expected_total=0)


def test_each_fulfilment_route_refuses_the_other_routes_product(api):
    """A shelf reservation, a reservation of a fabricated-to-order device and a
    fabrication order placed with a supplier that does not fabricate are refused
    with three different identifiers, and none of them touches the shelf.

    PRD: "Taking the wrong route — reserving a `CUSTOM_FABRICATED` item, or
    ordering fabrication for a prefabricated one — is refused with
    `ERR_PRODUCT_CATEGORY_MISMATCH` and HTTP 422." ... "The named supplier must
    have `custom_fab_capable` true, or the request is refused with
    `ERR_CUSTOM_FAB_NOT_SUPPORTED` and HTTP 422."

    Design: Corner/validations/corner_reservation_and_fabrication_route_gates_rejected
    """
    practice = build_practice(
        api,
        supplier={"custom_fab_capable": False},
        par_level={"par_min_qty": 1},
        received_qty=1,
    )
    fabricated = add_product(
        practice,
        f.product_payload(
            practice.supplier_id,
            hcpcs_code="L1940",
            description="Ankle foot orthosis, custom fabricated",
            category=CATEGORY_CUSTOM_FABRICATED,
            same_or_similar_group="AFO_CUSTOM",
            allowed_amount_cents=42000,
            cash_price_cents=49999,
            unit_cost_cents=20000,
        ),
    )
    before = read_shelf(api, practice.par_level_id)
    assert_shelf(before, on_hand_qty=1, available_qty=1)
    shelf_encounter_id = practice.documented_encounter(quantity=2)
    fabricated_encounter_id = practice.documented_encounter(product_id=fabricated["id"])

    assert_error(
        api.create_reservation(
            shelf_encounter_id,
            f.reservation_payload(before["version"]),
            practice.fitter_headers,
        ),
        ApiErrors.INSUFFICIENT_PAR_STOCK,
        422,
    )
    assert_error(
        api.create_reservation(
            fabricated_encounter_id,
            f.reservation_payload(before["version"]),
            practice.fitter_headers,
        ),
        ApiErrors.PRODUCT_CATEGORY_MISMATCH,
        422,
    )
    assert_error(
        api.create_custom_fab_order(
            fabricated_encounter_id,
            f.custom_fab_order_payload(practice.supplier_id),
            practice.fitter_headers,
        ),
        ApiErrors.CUSTOM_FAB_NOT_SUPPORTED,
        422,
    )

    assert_shelf(read_shelf(api, practice.par_level_id), reserved_qty=0, version=before["version"])
    assert_encounter_states(
        read_encounter(api, shelf_encounter_id), clinical_status=CLINICAL_DOCUMENTED
    )
    assert_encounter_states(
        read_encounter(api, fabricated_encounter_id), clinical_status=CLINICAL_DOCUMENTED
    )


def test_the_self_referral_and_delivery_paperwork_gates_are_three_distinct_rules(api):
    """A note signed for a physician with no disclosure on file, a delivery with
    no supervision attestation, a delivery whose attestation observed too little
    supervision, and a delivery the patient refused to sign each answer with
    their own identifier, and none of them advances the encounter.

    PRD: "A dispense attempted with no attestation at all, or with insufficient
    supervision for a `DIRECT` item, is refused with
    `ERR_IOAS_SUPERVISION_MISSING` and HTTP 422." ... "A `REFUSED` signature
    cannot complete a delivery, and neither can a missing one; either is refused
    with `ERR_DELIVERY_SIGNATURE_MISSING` and HTTP 422."

    Design: Corner/validations/corner_self_referral_and_delivery_documentation_gates_rejected
    """
    practice = build_practice(
        api,
        product_factory=lambda supplier_id: f.product_payload(
            supplier_id, ioas_supervision_required=SUPERVISION_DIRECT
        ),
        received_qty=6,
    )
    undisclosed = add_physician(practice, full_name="Cyd Ames", stark_disclosure_on_file=False)

    encounter_id = practice.open_encounter()["id"]
    practice.sign_note(encounter_id)
    practice.verify_coverage(encounter_id)
    practice.reserve(encounter_id)
    practice.fit(encounter_id)
    undisclosed_encounter = validate_success(
        api.create_encounter(
            f.encounter_payload(
                practice.clinic_id, practice.patient_id, practice.product_id, undisclosed["id"]
            ),
            practice_admin_headers(),
        ),
        201,
    )

    assert_error(
        api.sign_medical_necessity_note(
            undisclosed_encounter["id"],
            f.medical_necessity_note_payload(),
            make_ortho_physician_headers(undisclosed["id"]),
        ),
        ApiErrors.STARK_DISCLOSURE_MISSING,
        422,
    )
    assert_error(
        api.dispense(encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers),
        ApiErrors.IOAS_SUPERVISION_MISSING,
        422,
    )

    general = practice.attest(encounter_id, SUPERVISION_GENERAL)
    assert general["ioas_supervision_level_observed"] == SUPERVISION_GENERAL

    assert_error(
        api.dispense(encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers),
        ApiErrors.IOAS_SUPERVISION_MISSING,
        422,
    )

    direct = practice.attest(encounter_id, SUPERVISION_DIRECT)
    assert direct["ioas_supervision_level_observed"] == SUPERVISION_DIRECT

    assert_error(
        api.dispense(encounter_id, f.dispense_payload("REFUSED"), practice.fitter_headers),
        ApiErrors.DELIVERY_SIGNATURE_MISSING,
        422,
    )

    stalled = read_encounter(api, encounter_id)
    assert_encounter_states(
        stalled, clinical_status=CLINICAL_FITTED, financial_status=FINANCIAL_VERIFIED
    )
    assert stalled["delivered_at"] is None
    unsigned = read_encounter(api, undisclosed_encounter["id"])
    assert_encounter_states(unsigned, clinical_status=CLINICAL_DRAFT)
    assert unsigned["mn_signed_at"] is None


def test_a_fitting_session_is_refused_for_a_bad_interval_or_a_narrow_privilege(api):
    """A zero-length interval and an interval dated after the logical clock are
    both bad intervals, a narrowly privileged fitter may not fit a custom-fitted
    device at all, and an interval later in the clock's own day is accepted.

    PRD: "`fitting_end_at` must be strictly after `fitting_start_at`, and
    neither instant may fall on a calendar date strictly later than the logical
    clock date — a same-day instant later than the current clock time is
    accepted, so a session booked for later this afternoon is fine while one
    booked for tomorrow is not." ... "an `OFF_SHELF_ONLY` fitter may fit only
    `OFF_SHELF_PREFAB` devices and is otherwise refused with
    `ERR_FITTER_PRIVILEGE_SCOPE` and HTTP 403."

    Design: Corner/validations/corner_fitting_interval_and_privilege_scope_rejected
    """
    practice = build_practice(api, received_qty=6)
    narrow_fitter = add_fitter(
        practice, full_name="Rae Ellis", privilege_scope=SCOPE_OFF_SHELF_ONLY
    )
    custom_fitted = add_product(practice, f.custom_fitted_product_payload(practice.supplier_id))
    custom_shelf = add_shelf(practice, custom_fitted["id"], received_qty=6)
    off_shelf_encounter_id = practice.reserved_encounter()
    custom_encounter_id = practice.reserved_encounter(
        product_id=custom_fitted["id"], par_level_id=custom_shelf["id"]
    )

    assert_error(
        api.create_fitting_record(
            off_shelf_encounter_id,
            f.fitting_record_payload("2026-08-01T09:00:00Z", "2026-08-01T09:00:00Z"),
            practice.fitter_headers,
        ),
        ApiErrors.INVALID_INTERVAL,
        422,
    )
    assert_error(
        api.create_fitting_record(
            off_shelf_encounter_id,
            f.fitting_record_payload("2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"),
            practice.fitter_headers,
        ),
        ApiErrors.INVALID_INTERVAL,
        422,
    )
    assert_error(
        api.create_fitting_record(
            custom_encounter_id,
            f.fitting_record_payload("2026-08-01T13:00:00Z", "2026-08-01T13:45:00Z"),
            make_dme_fitter_headers(narrow_fitter["id"]),
        ),
        ApiErrors.FITTER_PRIVILEGE_SCOPE,
        403,
    )

    accepted = validate_success(
        api.create_fitting_record(
            off_shelf_encounter_id,
            f.fitting_record_payload("2026-08-01T18:00:00Z", "2026-08-01T18:45:00Z"),
            practice.fitter_headers,
        ),
        201,
    )

    assert accepted["fitting_minutes"] == 45
    assert accepted["fitter_id"] == practice.fitter_id
    assert_encounter_states(
        read_encounter(api, custom_encounter_id), clinical_status=CLINICAL_RESERVED
    )


def test_the_authorization_book_keeps_three_separate_constraints(api):
    """An approval for more units than were requested, a request for a product
    that needs no authorization at all, and a third appeal on a request whose
    two rounds are spent are three different refusals, and none of them writes
    anything.

    PRD: "The approved figure must be at least 1 and at most `requested_units`,
    and a violation is refused with `ERR_APPROVED_UNITS_EXCEED_REQUEST` and HTTP
    422." ... "At most one authorization request may exist per encounter: a
    second submission, or a submission for a product that does not in fact
    require authorization, is refused with `ERR_PRIOR_AUTH_ALREADY_EXISTS` and
    HTTP 409."

    Design: Corner/validations/corner_prior_auth_lifecycle_constraints_rejected
    """
    practice = build_practice(
        api,
        product_factory=lambda supplier_id: f.product_payload(
            supplier_id, requires_prior_auth=True
        ),
        with_shelf=False,
    )
    unrestricted = add_product(practice, f.cervical_collar_product_payload(practice.supplier_id))

    exhausted_encounter_id = practice.verified_encounter(quantity=2)
    exhausted = practice.request_prior_auth(exhausted_encounter_id, requested_units=2)
    pended = f.prior_auth_decision_payload(
        decision=PA_PENDED, approved_units=None, auth_number=None, valid_for_days=None
    )
    practice.decide_prior_auth(exhausted["id"], **pended)
    first_appeal = practice.appeal_prior_auth(exhausted["id"])
    assert first_appeal["appeal_round"] == 1
    practice.decide_prior_auth(exhausted["id"], **pended)
    second_appeal = practice.appeal_prior_auth(exhausted["id"])
    assert second_appeal["appeal_round"] == 2
    still_open = practice.decide_prior_auth(exhausted["id"], **pended)
    assert still_open["status"] == PA_PENDED

    unrestricted_encounter_id = practice.verified_encounter(product_id=unrestricted["id"])
    fresh_encounter_id = practice.verified_encounter(quantity=1)
    fresh = practice.request_prior_auth(fresh_encounter_id, requested_units=1)
    assert fresh["requested_units"] == 1

    assert_error(
        api.decide_prior_auth(
            fresh["id"],
            f.prior_auth_decision_payload(
                decision="APPROVED", approved_units=3, auth_number="AUTH-3", valid_for_days=60
            ),
            insurance_coordinator_headers(),
        ),
        ApiErrors.APPROVED_UNITS_EXCEED_REQUEST,
        422,
    )
    fresh_rows, _meta = assert_list_meta(
        api.list_prior_auth_requests(fresh_encounter_id, insurance_coordinator_headers()),
        expected_total=1,
    )
    assert fresh_rows[0]["status"] == PA_SUBMITTED
    assert fresh_rows[0]["approved_units"] is None

    assert_error(
        api.create_prior_auth_request(
            unrestricted_encounter_id,
            f.prior_auth_request_payload(1),
            insurance_coordinator_headers(),
        ),
        ApiErrors.PRIOR_AUTH_ALREADY_EXISTS,
        409,
    )
    assert_encounter_states(
        read_encounter(api, unrestricted_encounter_id), financial_status=FINANCIAL_VERIFIED
    )

    assert_error(
        api.appeal_prior_auth(
            exhausted["id"],
            f.prior_auth_appeal_payload("third level review requested"),
            insurance_coordinator_headers(),
        ),
        ApiErrors.APPEAL_LIMIT_REACHED,
        422,
    )
    exhausted_rows, _exhausted_meta = assert_list_meta(
        api.list_prior_auth_requests(exhausted_encounter_id, insurance_coordinator_headers()),
        expected_total=1,
    )
    assert exhausted_rows[0]["appeal_round"] == 2
    assert exhausted_rows[0]["status"] == PA_PENDED


def test_the_dispense_freshness_gates_answer_in_their_pinned_priority_order(api):
    """One encounter is blocked by a missing authorization with the clock
    untouched, another by a lapsed coverage quote ten days on, and the same
    encounter ninety-two days on reports the stale note rather than the lapsed
    quote even though both are true.

    PRD: "A note signed more than 90 whole days before delivery is stale and the
    physician must re-document before the device may be handed over; either
    failure is refused with `ERR_MEDICAL_NECESSITY_MISSING` and HTTP 422." ...
    "the effective verification's `expires_at` must be on or after the logical
    clock instant, or `ERR_COVERAGE_VERIFICATION_EXPIRED`; and when the
    product's `requires_prior_auth` is true, the encounter's authorization must
    be `APPROVED` with an `expires_at` on or after the logical clock instant, or
    `ERR_PRIOR_AUTH_REQUIRED`."

    Design: Corner/validations/corner_dispense_freshness_gates_and_their_priority_order_rejected
    """
    practice = build_practice(api, received_qty=6)
    authorized_product = add_product(
        practice, f.cervical_collar_product_payload(practice.supplier_id, requires_prior_auth=True)
    )
    authorized_shelf = add_shelf(practice, authorized_product["id"], received_qty=6)

    short_quote_encounter_id = practice.fitted_encounter(coverage={"valid_for_days": 5})
    unauthorized_encounter_id = practice.fitted_encounter(
        product_id=authorized_product["id"],
        par_level_id=authorized_shelf["id"],
        start_at="2026-08-01T10:00:00Z",
        end_at="2026-08-01T10:30:00Z",
    )
    assert_instant_equals(
        read_encounter(api, short_quote_encounter_id)["mn_signed_at"], "2026-08-01T00:00:00Z"
    )
    quotes, _quote_meta = assert_list_meta(
        api.list_coverage_verifications(
            short_quote_encounter_id, insurance_coordinator_headers()
        ),
        expected_total=1,
    )
    assert_instant_equals(quotes[0]["expires_at"], "2026-08-06T00:00:00Z")
    assert_encounter_states(
        read_encounter(api, unauthorized_encounter_id), financial_status=FINANCIAL_VERIFIED
    )

    assert_error(
        api.dispense(
            unauthorized_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers
        ),
        ApiErrors.PRIOR_AUTH_REQUIRED,
        422,
    )

    day_ten = set_clock(api, "2026-08-11T00:00:00Z")
    assert_instant_equals(day_ten["current_utc"], "2026-08-11T00:00:00Z")
    assert_error(
        api.dispense(
            short_quote_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers
        ),
        ApiErrors.COVERAGE_VERIFICATION_EXPIRED,
        422,
    )

    day_ninety_two = set_clock(api, "2026-11-01T00:00:00Z")
    assert_instant_equals(day_ninety_two["current_utc"], "2026-11-01T00:00:00Z")
    assert_error(
        api.dispense(
            short_quote_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers
        ),
        ApiErrors.MEDICAL_NECESSITY_MISSING,
        422,
    )

    assert_encounter_states(
        read_encounter(api, short_quote_encounter_id),
        clinical_status=CLINICAL_FITTED,
        financial_status=FINANCIAL_VERIFIED,
    )


def test_the_two_beneficiary_notice_gates_are_reached_from_two_financial_states(api):
    """An authorization that covers fewer units than were ordered demands a
    signed notice for the excess, an outstanding notice blocks delivery, a
    notice the patient declined to sign does not clear that block, and only a
    corrected notice signed under option one lets the device go out at the cash
    price.

    PRD: "Finally, whenever the encounter's `quantity` exceeds the number of
    units the payer will cover, a notice with `status` `SIGNED`, the greatest
    `notice_seq` for the encounter, and an `option_selected` of `OPTION_1` or
    `OPTION_2` must exist, or the dispense is refused with
    `ERR_ABN_REQUIRED_FOR_EXCESS_UNITS` and HTTP 422." ... "an encounter sitting
    at `ABN_ISSUED` — a notice was issued but the patient has not yet responded,
    or responded with a declined signature — is refused with
    `ERR_ABN_NOT_SIGNED` and HTTP 422."

    Design: Corner/validations/corner_abn_excess_units_and_unsigned_notice_gates_rejected
    """
    practice = build_practice(
        api,
        product_factory=lambda supplier_id: f.cervical_collar_product_payload(
            supplier_id, allowed_amount_cents=31000, requires_prior_auth=True
        ),
        received_qty=6,
    )
    cash_product = add_product(practice, f.product_payload(practice.supplier_id))
    cash_shelf = add_shelf(practice, cash_product["id"], received_qty=6)
    second_patient = add_patient(practice, full_name="Joel Pike", dob="1958-09-19")

    excess_encounter_id = practice.attested_encounter(quantity=2)
    practice.verify_coverage(excess_encounter_id)
    request = practice.request_prior_auth(excess_encounter_id, requested_units=2)
    decision = practice.decide_prior_auth(
        request["id"], decision="APPROVED", approved_units=1, auth_number="AUTH-77002"
    )
    assert decision["approved_units"] == 1
    assert decision["status"] == "APPROVED"
    practice.reserve(excess_encounter_id)
    practice.fit(excess_encounter_id)

    cash_encounter_id = practice.verified_encounter(
        product_id=cash_product["id"],
        patient_id=second_patient["id"],
        coverage={"covered": False},
    )
    first_notice = practice.issue_abn(cash_encounter_id)
    assert first_notice["notice_seq"] == 1
    practice.reserve(cash_encounter_id, cash_shelf["id"])
    practice.fit(cash_encounter_id, "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z")

    assert_error(
        api.dispense(
            excess_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers
        ),
        ApiErrors.ABN_REQUIRED_FOR_EXCESS_UNITS,
        422,
    )
    assert_error(
        api.dispense(cash_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers),
        ApiErrors.ABN_NOT_SIGNED,
        422,
    )

    declined = get_success_data(
        api.sign_abn_notice(
            first_notice["id"], f.abn_decline_payload(), insurance_coordinator_headers()
        )
    )
    assert declined["status"] == "DECLINED"
    assert_encounter_states(
        read_encounter(api, cash_encounter_id), financial_status=FINANCIAL_ABN_ISSUED
    )

    assert_error(
        api.dispense(cash_encounter_id, f.dispense_payload("PATIENT"), practice.fitter_headers),
        ApiErrors.ABN_NOT_SIGNED,
        422,
    )

    second_notice = practice.issue_abn(cash_encounter_id)
    assert second_notice["notice_seq"] == 2
    assert_money(second_notice, "dispensing_fee_cents", 2500)
    assert_money(second_notice, "estimated_cost_cents", 14265)
    signed = practice.sign_abn(second_notice["id"], option="OPTION_1")
    assert signed["status"] == "SIGNED"

    delivered = practice.dispense(cash_encounter_id)

    assert_encounter_states(
        delivered, clinical_status=CLINICAL_DELIVERED, financial_status=FINANCIAL_BILLED
    )
    assert_responsibility(
        delivered,
        patient_responsibility_cents=14265,
        billable_amount_cents=0,
        responsibility_variant="ABN_CASH_SELFPAY",
    )
    assert_encounter_states(
        read_encounter(api, excess_encounter_id),
        clinical_status=CLINICAL_FITTED,
        financial_status=FINANCIAL_AUTH_APPROVED,
    )


def test_the_return_window_is_per_reason_and_a_refit_has_two_separate_gates(api):
    """Thirty-one days after delivery the same clinic refuses a poor-fit return
    and accepts a defect return on an identical device, the defect return is too
    late to go back on the shelf even though it came back sellable, and a refit
    is refused first for its reason and then for its actor before a second
    fitter succeeds.

    PRD: "A return opened past its window is refused with
    `ERR_RETURN_WINDOW_EXPIRED` and HTTP 422, and an encounter that already has
    a return is refused with `ERR_RETURN_ALREADY_EXISTS` and HTTP 409." ... "And
    the acting fitter's identity must differ from the returned encounter's
    `fitter_id`, so that the fitter whose work is being redone cannot certify the
    redo; a self-refit is refused with `ERR_REFIT_SAME_FITTER` and HTTP 409."

    Design: Corner/validations/corner_return_window_and_refit_eligibility_rejected
    """
    practice = build_practice(api, received_qty=10)
    second_fitter = add_fitter(practice, full_name="Rae Ellis")
    second_patient = add_patient(practice, full_name="Joel Pike", dob="1958-09-19")
    third_patient = add_patient(practice, full_name="Mira Kell", dob="1972-11-02")
    half_coinsurance = {
        "covered": True,
        "deductible_remaining_cents": 0,
        "coinsurance_pct": 0.5,
    }

    late_encounter_id = practice.delivered_encounter(coverage=half_coinsurance)
    defect_encounter_id = practice.delivered_encounter(
        coverage=half_coinsurance,
        patient_id=second_patient["id"],
        start_at="2026-08-01T10:00:00Z",
        end_at="2026-08-01T10:30:00Z",
    )
    refit_encounter_id = practice.delivered_encounter(
        coverage=half_coinsurance,
        patient_id=third_patient["id"],
        start_at="2026-08-01T11:00:00Z",
        end_at="2026-08-01T11:30:00Z",
    )
    assert_money(read_encounter(api, late_encounter_id), "patient_responsibility_cents", 10300)

    restocked = practice.inspect_return(
        practice.open_return(refit_encounter_id, reason="POOR_FIT")["id"], condition="SELLABLE"
    )
    assert restocked["status"] == RETURN_RESTOCKED
    assert_money(restocked, "refund_cents", 9348)
    assert_money(restocked, "restock_fee_cents", 952)

    day_thirty_one = set_clock(api, "2026-09-01T00:00:00Z")
    assert_instant_equals(day_thirty_one["current_utc"], "2026-09-01T00:00:00Z")

    assert_error(
        api.create_return(
            late_encounter_id,
            f.return_payload("POOR_FIT", "reported late"),
            practice.fitter_headers,
        ),
        ApiErrors.RETURN_WINDOW_EXPIRED,
        422,
    )

    defect = practice.open_return(
        defect_encounter_id, reason="DEFECT", return_note="panel delamination"
    )
    assert defect["days_since_delivery"] == 31
    assert defect["status"] == RETURN_REQUESTED

    inspected = practice.inspect_return(defect["id"], condition="SELLABLE")
    assert inspected["status"] == RETURN_DESTROYED
    assert inspected["restock_eligible"] is False
    assert_money(inspected, "refund_cents", 10300)
    assert_money(inspected, "restock_fee_cents", 0)

    assert_error(
        api.issue_refit(defect["id"], {}, make_dme_fitter_headers(second_fitter["id"])),
        ApiErrors.REFIT_REASON_NOT_ELIGIBLE,
        422,
    )
    assert_error(
        api.issue_refit(restocked["id"], {}, practice.fitter_headers),
        ApiErrors.REFIT_SAME_FITTER,
        409,
    )

    refit = validate_success(
        api.issue_refit(restocked["id"], {}, make_dme_fitter_headers(second_fitter["id"])), 201
    )

    assert refit["refit_of_encounter_id"] == refit_encounter_id
    assert refit["mn_diagnosis_code"] == "M54.50"
    assert_encounter_states(
        refit, clinical_status=CLINICAL_DOCUMENTED, financial_status=FINANCIAL_UNVERIFIED
    )
    closed_rows, _closed_meta = assert_list_meta(
        api.list_returns(refit_encounter_id, inventory_manager_headers()), expected_total=1
    )
    assert closed_rows[0]["status"] == RETURN_REFIT_ISSUED
    assert closed_rows[0]["refit_encounter_id"] == refit["id"]


def test_a_suspended_clinic_blocks_a_fitting_and_a_reservation_for_two_reasons(api):
    """Two shelves emptying suspend the clinic, which stamps a hold on an
    in-flight reservation and independently refuses a brand-new reservation on a
    perfectly healthy third shelf; restoring one shelf clears both without any
    explicit unblocking call.

    PRD: "While a hold is active, two operations are refused with
    `ERR_COMPLIANCE_HOLD_ACTIVE` and HTTP 409: recording a fitting session, and
    dispensing." ... "Independently of the holds, the clinic's posture gates
    three encounter operations — reserving par stock, placing a
    custom-fabrication order, and dispensing — with
    `ERR_CLINIC_DISPENSING_SUSPENDED` and HTTP 409."

    Design: Corner/validations/corner_clinic_suspension_gates_fitting_and_reservation_rejected
    """
    practice = build_practice(
        api, par_level={"par_min_qty": 1, "par_max_qty": 20}, received_qty=1
    )
    second_product = add_product(practice, f.cervical_collar_product_payload(practice.supplier_id))
    third_product = add_product(
        practice,
        f.product_payload(
            practice.supplier_id,
            hcpcs_code="L0631",
            description="LSO brace, sagittal control, prefabricated",
            same_or_similar_group="LSO_SAGITTAL",
        ),
    )
    second_shelf = add_shelf(
        practice, second_product["id"], received_qty=1, par_min_qty=1, par_max_qty=20
    )
    third_shelf = add_shelf(
        practice, third_product["id"], received_qty=2, par_min_qty=1, par_max_qty=20
    )

    first_encounter_id = practice.fitted_encounter()
    second_encounter_id = practice.fitted_encounter(
        product_id=second_product["id"],
        par_level_id=second_shelf["id"],
        start_at="2026-08-01T10:00:00Z",
        end_at="2026-08-01T10:30:00Z",
    )
    reserved_encounter_id = practice.reserved_encounter(
        product_id=third_product["id"], par_level_id=third_shelf["id"]
    )
    waiting_encounter_id = practice.documented_encounter(product_id=third_product["id"])

    practice.dispense(first_encounter_id)
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status=DISPENSING_RESTRICTED,
        stockout_par_level_count=1,
    )
    practice.dispense(second_encounter_id)
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status=DISPENSING_SUSPENDED,
        stockout_par_level_count=2,
    )
    assert_shelf(read_shelf(api, third_shelf["id"]), stock_posture=POSTURE_OK)

    blocked_session = f.fitting_record_payload(
        "2026-08-01T13:00:00Z", "2026-08-01T13:30:00Z", measurement_set={"waist_cm": 88}
    )
    assert_error(
        api.create_fitting_record(
            reserved_encounter_id, blocked_session, practice.fitter_headers
        ),
        ApiErrors.COMPLIANCE_HOLD_ACTIVE,
        409,
    )
    assert_error(
        api.create_reservation(
            waiting_encounter_id,
            f.reservation_payload(shelf_version(api, third_shelf["id"])),
            practice.fitter_headers,
        ),
        ApiErrors.CLINIC_DISPENSING_SUSPENDED,
        409,
    )

    held = read_encounter(api, reserved_encounter_id)
    assert_compliance_hold(held, True, HOLD_CLINIC_SUSPENDED)
    assert_encounter_states(held, clinical_status=CLINICAL_RESERVED)

    restored = validate_success(
        api.receive_stock(
            second_shelf["id"], f.stock_receipt_payload(3), inventory_manager_headers()
        ),
        201,
    )
    assert_shelf(restored, on_hand_qty=3, stock_posture=POSTURE_OK)
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status=DISPENSING_RESTRICTED,
        stockout_par_level_count=1,
    )
    assert_compliance_hold(read_encounter(api, reserved_encounter_id), False, None)

    session = validate_success(
        api.create_fitting_record(
            reserved_encounter_id, blocked_session, practice.fitter_headers
        ),
        201,
    )
    assert session["fitting_minutes"] == 30
    assert_encounter_states(
        read_encounter(api, reserved_encounter_id), clinical_status=CLINICAL_FITTED
    )
