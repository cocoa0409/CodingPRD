"""Entity field contracts: seeded defaults, derived fields, listing metadata and
the shape and existence gates that guard a creation body."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def test_patient_registration_returns_every_seeded_and_derived_field(api):
    """PRD 3.1: "On creation the chart is seeded with `sensitized_antigen_count` 0,
    `dermatographism` false, `immunotherapy_escalation_step` 1,
    `immunotherapy_status` `NONE`, `last_dose_administered_at` null,
    `risk_score_variant` `PROVISIONAL`, and a `risk_score` and `supervision_tier`
    computed immediately."

    Design: Corner/entities/patient_creation_returns_all_declared_fields
    """
    # A plan is registered so the new chart has a plan to name.
    policy = SETUP.create_policy(api, plan_code="ENTA-2999", payer_name="Corner Mutual")

    # One adult chart is registered with every optional intake fact supplied.
    response = api.create_patient(
        F.patient_payload(
            policy["id"],
            mrn=C.mrn(10191),
            full_name="Dana Reyes",
            date_of_birth="1990-05-20",
            epinephrine_on_file=True,
            prior_systemic_reaction_count=0,
        ),
        USERS.ADMIN_1,
    )
    patient = validate_success(response, 201)

    # The creation response already carries the whole chart, seeds and all.
    check.assert_patient(
        patient,
        payer_policy_id=policy["id"],
        mrn=C.mrn(10191),
        full_name="Dana Reyes",
        date_of_birth="1990-05-20",
        age_months=434,
        antihistamine_last_dose_at=None,
        epinephrine_on_file=True,
        dermatographism=False,
        prior_systemic_reaction_count=0,
        sensitized_antigen_count=0,
        risk_score=5,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
        immunotherapy_escalation_step=1,
        immunotherapy_status=C.IMMUNO_STATUS_NONE,
        last_dose_administered_at=None,
    )
    check.assert_mutable_resource(patient, expected_version=1)
    check.assert_request_meta(response)


def test_stored_plan_terms_read_back_unchanged_with_version_one(api):
    """PRD 2.4: "Twelve of the thirteen resource kinds additionally carry
    `updated_at`, of identical format, refreshed to the current logical-clock
    instant on every mutation of that row, and `version`, an integer that begins at
    1 when the row is created and increments by exactly 1 on every mutation of that
    row."

    Design: Corner/entities/payer_policy_retrieval_returns_stored_configuration
    """
    # Every configuration term is registered away from its default.
    policy = SETUP.create_policy(
        api,
        plan_code="ENTB-2999",
        payer_name="Retrieval Health",
        requires_prior_auth=False,
        min_medical_management_days=14,
        requires_ct_within_months=6,
        min_documented_criteria=2,
        max_balloon_devices=4,
        covered_pct_bps=5000,
        allergy_serum_covered=False,
        observation_floor_minutes=45,
        device_trial_days=60,
        restock_fee_bps=2000,
        restock_fee_floor_cents=20000,
        auth_validity_days=30,
        appliance_covered=False,
    )

    # The payer liaison reads the plan back; a read is not a mutation.
    stored = check.validate_unpaginated(
        api.get_payer_policy(policy["id"], USERS.LIAISON_1)
    )

    check.assert_payer_policy(
        stored,
        payer_name="Retrieval Health",
        plan_code="ENTB-2999",
        requires_prior_auth=False,
        min_medical_management_days=14,
        requires_ct_within_months=6,
        min_documented_criteria=2,
        max_balloon_devices=4,
        covered_pct_bps=5000,
        allergy_serum_covered=False,
        observation_floor_minutes=45,
        device_trial_days=60,
        restock_fee_bps=2000,
        restock_fee_floor_cents=20000,
        auth_validity_days=30,
        appliance_covered=False,
    )
    check.assert_mutable_resource(stored, expected_version=1)
    assert stored["id"] == policy["id"]


def test_allergy_order_pages_report_the_filtered_total(api):
    """PRD 2.3: "For list responses, the `meta` object carries four pagination
    fields in addition to the request identifier and timestamp: `limit` (the
    effective page size actually applied), `offset` (the effective offset actually
    applied), `total_count` (the number of rows matching the filters, before the
    page window is applied), and `has_more` (true when the sum of `offset` and the
    number of rows returned in this page is strictly less than `total_count`,
    otherwise false)."

    Design: Corner/entities/allergy_test_order_listing_paginates
    """
    policy = SETUP.create_policy(api, plan_code="ENTC-2999", payer_name="List Mutual")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10192),
        full_name="Lee Ortiz",
        date_of_birth="1988-03-04",
        epinephrine_on_file=True,
    )

    # Three panels are opened for the one chart.
    first = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )
    second = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_VENOM_5, method=C.METHOD_SKIN_PRICK
    )
    third = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_FOOD_24, method=C.METHOD_SERUM_IGE
    )

    # The first page of two carries two rows and reports the unwindowed total.
    head, head_meta = validate_paginated(
        api.list_allergy_test_orders(
            USERS.ADMIN_1,
            params={"patient_id": patient["id"], "limit": 2, "offset": 0},
        )
    )
    check.assert_pagination_meta(
        head_meta, limit=2, offset=0, total_count=3, has_more=True
    )
    assert len(head) == 2
    check.assert_ascending_created_at(head)

    # The second page carries the remainder and closes the window.
    tail, tail_meta = validate_paginated(
        api.list_allergy_test_orders(
            USERS.ADMIN_1,
            params={"patient_id": patient["id"], "limit": 2, "offset": 2},
        )
    )
    check.assert_pagination_meta(
        tail_meta, limit=2, offset=2, total_count=3, has_more=False
    )
    assert len(tail) == 1

    # Across the two pages every order appears exactly once.
    seen = check.ids_in_order(head) + check.ids_in_order(tail)
    assert len(set(seen)) == 3
    assert sorted(seen) == sorted([first["id"], second["id"], third["id"]])


def test_allergy_order_method_filter_narrows_the_total_count(api):
    """PRD 2.3: "Filter parameters on list endpoints are combined conjunctively: a
    request that supplies both a `patient_id` filter and a `status` filter returns
    only rows matching both."

    Design: Corner/entities/allergy_test_order_listing_paginates
    """
    policy = SETUP.create_policy(api, plan_code="ENTC-2999", payer_name="List Mutual")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10192),
        full_name="Lee Ortiz",
        date_of_birth="1988-03-04",
        epinephrine_on_file=True,
    )
    SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )
    SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_VENOM_5, method=C.METHOD_SKIN_PRICK
    )
    serum = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_FOOD_24, method=C.METHOD_SERUM_IGE
    )

    # Chart and method together select the single serum panel.
    rows, meta = validate_paginated(
        api.list_allergy_test_orders(
            USERS.ADMIN_1,
            params={"patient_id": patient["id"], "method": C.METHOD_SERUM_IGE},
        )
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    assert check.ids_in_order(rows) == [serum["id"]]
    check.assert_allergy_test_order(
        rows[0],
        patient_id=patient["id"],
        panel_code=C.PANEL_FOOD_24,
        method=C.METHOD_SERUM_IGE,
    )


def test_unknown_patient_id_in_the_path_is_not_found(api):
    """PRD 2.8: "Every identifier in the path resolves to a stored row, resolved
    left to right."

    Design: Corner/entities/patient_not_found_on_unknown_id
    """
    # A plan exists, but no chart has ever been registered under it.
    SETUP.create_policy(api, plan_code="ENTD-2999", payer_name="Absent Mutual")

    validate_error(
        api.get_patient(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.PATIENT_NOT_FOUND.value,
    )


def test_unknown_patient_id_in_the_body_is_not_found_and_persists_nothing(api):
    """PRD 2.8: "Every identifier supplied inside the request body resolves to a
    stored row, resolved in the order the endpoint's input list declares them."

    Design: Corner/entities/patient_not_found_on_unknown_id
    """
    SETUP.create_policy(api, plan_code="ENTD-2999", payer_name="Absent Mutual")

    # The panel names a chart that does not exist.
    validate_error(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                NON_EXISTENT_UUID,
                panel_code=C.PANEL_MOLD_12,
                method=C.METHOD_SKIN_PRICK,
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.PATIENT_NOT_FOUND.value,
    )

    # The refused creation left no order behind.
    rows, meta = validate_paginated(api.list_allergy_test_orders(USERS.ADMIN_1))
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )
    assert rows == []


def test_creations_missing_a_required_input_are_refused_and_persist_nothing(api):
    """PRD 2.8: "The body and query conform to the endpoint's declared input: every
    required field is present; no unknown field is present; every value has the
    declared type; every enum-typed value is a declared member; every integer lies
    inside its declared range; every ISO-8601 instant is well formed and expressed
    in UTC; every calendar date is well formed; every regex-constrained string
    matches its pattern (`mrn` matches an `MRN-` prefix followed by exactly five
    digits; `plan_code` is three to twenty characters drawn only from uppercase
    letters, digits and hyphens; `serial_number` matches an `SC-` prefix followed by
    exactly four digits; `lot_number` matches a `LOT-` prefix followed by exactly
    four digits; `device_serial` is exactly two uppercase letters followed by
    exactly six digits); array fields declared non-empty are non-empty; a documented
    therapy item never has a `start_date` later than its `end_date`; a reaction event
    carries exactly one of `allergy_test_order_id` and `immunotherapy_dose_id`, so
    supplying both or neither fails here; a study-results payload carries exactly the
    metric set its `study_type` demands; `limit` lies between 1 and 100 inclusive and
    `offset` is not negative."

    Design: Corner/entities/allergy_test_order_missing_panel_code_is_invalid_request
    """
    # A plan and one adult chart exist, so only the omission can be at fault.
    policy = SETUP.create_policy(api, plan_code="ENTE-2999", payer_name="Shape Mutual")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10193),
        full_name="Ada Nunez",
        date_of_birth="1979-11-02",
        epinephrine_on_file=True,
    )

    # A panel without its panel code.
    order_body = F.allergy_test_order_payload(
        patient["id"], method=C.METHOD_SKIN_PRICK
    )
    del order_body["panel_code"]
    validate_error(
        api.create_allergy_test_order(order_body, USERS.NURSE_1),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # A chart without a date of birth.
    patient_body = F.patient_payload(
        policy["id"], mrn=C.mrn(10194), full_name="No Birthday"
    )
    del patient_body["date_of_birth"]
    validate_error(
        api.create_patient(patient_body, USERS.ADMIN_1),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # A lot without an expiry instant.
    lot_body = F.supply_lot_payload(
        SETUP.LOT_EXPIRY_DEFAULT,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_number=C.lot_number(1010),
        quantity_received=4,
    )
    del lot_body["expires_at"]
    validate_error(
        api.create_supply_lot(lot_body, USERS.ADMIN_1),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # None of the three refusals wrote a row.
    _, order_meta = validate_paginated(
        api.list_allergy_test_orders(
            USERS.ADMIN_1, params={"patient_id": patient["id"]}
        )
    )
    assert order_meta["total_count"] == 0

    patient_rows, patient_meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    assert patient_meta["total_count"] == 1
    assert check.ids_in_order(patient_rows) == [patient["id"]]

    _, lot_meta = validate_paginated(api.list_supply_lots(USERS.ADMIN_1))
    assert lot_meta["total_count"] == 0


def test_plan_registration_applies_every_omitted_default(api):
    """PRD 3.1: "Thirteen further terms may be supplied, and each has a default that
    applies when the field is omitted: `requires_prior_auth` defaults to true;
    `min_medical_management_days` defaults to 28 and must lie between 0 and 180
    inclusive; `requires_ct_within_months` defaults to 12 and must lie between 1 and
    60 inclusive; `min_documented_criteria` defaults to 3 and must lie between 1 and
    6 inclusive; `max_balloon_devices` defaults to 2 and must lie between 1 and 6
    inclusive; `covered_pct_bps` defaults to 8000 — that is, the plan pays eight
    tenths of each billed allergy unit — and must lie between 0 and 10000 inclusive;
    `allergy_serum_covered` defaults to true; `observation_floor_minutes` defaults to
    20 and must lie between 0 and 120 inclusive; `device_trial_days` defaults to 30
    and must lie between 1 and 120 inclusive; `restock_fee_bps` defaults to 1500 —
    fifteen hundredths of the device price — and must lie between 0 and 10000
    inclusive; `restock_fee_floor_cents` defaults to 12500, that is one hundred and
    twenty-five dollars, and must lie between 0 and 500000 inclusive;
    `auth_validity_days` defaults to 90 and must lie between 1 and 365 inclusive; and
    `appliance_covered` defaults to true."

    Design: Corner/entities/payer_policy_defaults_applied_when_omitted
    """
    # Only the two mandatory terms are supplied.
    response = api.create_payer_policy(
        F.payer_policy_payload(payer_name="Default Mutual", plan_code="ENTF-2999"),
        USERS.ADMIN_1,
    )
    policy = validate_success(response, 201)

    check.assert_payer_policy(
        policy,
        payer_name="Default Mutual",
        plan_code="ENTF-2999",
        requires_prior_auth=True,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        min_documented_criteria=3,
        max_balloon_devices=2,
        covered_pct_bps=8000,
        allergy_serum_covered=True,
        observation_floor_minutes=20,
        device_trial_days=30,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
        auth_validity_days=90,
        appliance_covered=True,
    )
    check.assert_mutable_resource(policy, expected_version=1)


def test_supplied_age_months_is_refused_as_an_unknown_field(api):
    """PRD 2.11: "Fields whose `source` is computed or system are never accepted from
    a request body."

    Design: Corner/entities/patient_age_months_is_computed_and_input_is_invalid_request
    """
    policy = SETUP.create_policy(
        api, plan_code="ENTG-2999", payer_name="Computed Mutual"
    )

    # The registration tries to dictate the derived age.
    validate_error(
        api.create_patient(
            F.patient_payload(
                policy["id"],
                mrn=C.mrn(10195),
                full_name="Toddler One",
                date_of_birth="2024-06-01",
                age_months=60,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # No chart was registered under the plan.
    _, meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    assert meta["total_count"] == 0


def test_age_in_months_is_derived_from_the_birth_date_against_the_clock(api):
    """PRD 3.1: "Take the difference in years between the clock's year and the birth
    year and multiply by twelve; add the difference between the clock's month number
    and the birth month number; then, if the clock's day of month is strictly less
    than the birth day of month, subtract one."

    Design: Corner/entities/patient_age_months_is_computed_and_input_is_invalid_request
    """
    policy = SETUP.create_policy(
        api, plan_code="ENTG-2999", payer_name="Computed Mutual"
    )

    # The same registration without the derived field is accepted.
    response = api.create_patient(
        F.patient_payload(
            policy["id"],
            mrn=C.mrn(10195),
            full_name="Toddler One",
            date_of_birth="2024-06-01",
        ),
        USERS.ADMIN_1,
    )
    patient = validate_success(response, 201)

    check.assert_patient(
        patient,
        date_of_birth="2024-06-01",
        age_months=26,
        risk_score=23,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
        epinephrine_on_file=False,
        prior_systemic_reaction_count=0,
        sensitized_antigen_count=0,
    )

    # The chart is the only one on the plan.
    rows, meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1
    assert check.find_by_id(rows, patient["id"])["age_months"] == 26


def test_supplied_lot_status_is_refused_as_an_unknown_field(api):
    """PRD 2.11: "Fields whose `source` is computed or system are never accepted from
    a request body."

    Design: Corner/entities/supply_lot_system_fields_are_server_generated_and_input_is_invalid_request
    """
    # The receiving clerk tries to book the lot straight into quarantine.
    validate_error(
        api.create_supply_lot(
            F.supply_lot_payload(
                "2027-06-30T00:00:00Z",
                item_type=C.ITEM_TYPE_BALLOON_DEVICE,
                lot_number=C.lot_number(1011),
                quantity_received=6,
                status=C.LOT_QUARANTINED,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # Nothing was booked in.
    _, meta = validate_paginated(api.list_supply_lots(USERS.ADMIN_1))
    assert meta["total_count"] == 0


def test_received_lot_opens_with_server_stamped_quantity_buckets(api):
    """PRD 3.8: "The lot is created with `quantity_on_hand` equal to
    `quantity_received`, `quantity_reserved` 0, `quantity_consumed` 0,
    `quantity_wasted` 0 and status `ACTIVE`."

    Design: Corner/entities/supply_lot_system_fields_are_server_generated_and_input_is_invalid_request
    """
    # The same lot, with no bucket and no status supplied.
    response = api.create_supply_lot(
        F.supply_lot_payload(
            "2027-06-30T00:00:00Z",
            item_type=C.ITEM_TYPE_BALLOON_DEVICE,
            lot_number=C.lot_number(1011),
            quantity_received=6,
        ),
        USERS.ADMIN_1,
    )
    lot = validate_success(response, 201)

    check.assert_supply_lot(
        lot,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_number=C.lot_number(1011),
        quantity_received=6,
        quantity_on_hand=6,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=6,
        status=C.LOT_ACTIVE,
    )
    check.assert_mutable_resource(lot, expected_version=1)
    check.assert_plain_uuid(lot["id"])
    check.assert_instant_equals(lot["expires_at"], "2027-06-30T00:00:00Z")


def test_reaction_event_carries_no_updated_at_and_no_version(api):
    """PRD 2.4: "A reaction event therefore carries only `id` and `created_at` — it
    has **no** `updated_at` field and **no** `version` field at all, and neither
    appears in its representation."

    Design: Corner/entities/reaction_event_is_immutable_and_has_no_version
    """
    policy = SETUP.create_policy(
        api, plan_code="ENTH-2999", payer_name="Immutable Mutual"
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10196),
        full_name="Ken Vasquez",
        date_of_birth="1982-02-09",
        epinephrine_on_file=True,
    )
    order = SETUP.administered_order(
        api,
        patient["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    # A mild systemic reaction is recorded against the administered panel.
    response = api.create_reaction_event(
        F.reaction_event_payload(
            1,
            10,
            allergy_test_order_id=order["id"],
            local_wheal_mm=12.0,
            epinephrine_given=False,
        ),
        USERS.NURSE_1,
    )
    event = validate_success(response, 201)

    check.assert_reaction_event(
        event,
        allergy_test_order_id=order["id"],
        immunotherapy_dose_id=None,
        systemic_grade=1,
        onset_minutes=10,
        epinephrine_given=False,
        recorded_by_user_id=C.USER_NURSE_1,
    )
    check.assert_instant_equals(event["occurred_at"], C.CLOCK_DEFAULT)
    check.assert_immutable_resource(event)
    check.assert_absent(event, ("updated_at", "version"))

    # The stored representation is the same shape when read back.
    stored = check.validate_unpaginated(
        api.get_reaction_event(event["id"], USERS.ENT_1)
    )
    assert stored["id"] == event["id"]
    check.assert_immutable_resource(stored)
    check.assert_absent(stored, ("updated_at", "version"))


def test_grade_one_reaction_leaves_the_panel_administered_and_the_score_unmoved(api):
    """PRD 3.4: "Grades 0 and 1 stop there — they are documented, they raise the
    roll-up, and under the `PROVISIONAL` variant they contribute nothing to the risk
    score."

    Design: Corner/entities/reaction_event_is_immutable_and_has_no_version
    """
    policy = SETUP.create_policy(
        api, plan_code="ENTH-2999", payer_name="Immutable Mutual"
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10196),
        full_name="Ken Vasquez",
        date_of_birth="1982-02-09",
        epinephrine_on_file=True,
    )
    order = SETUP.administered_order(
        api,
        patient["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
        headers=USERS.NURSE_1,
    )

    SETUP.record_reaction(
        api,
        1,
        10,
        order_id=order["id"],
        headers=USERS.NURSE_1,
        local_wheal_mm=12.0,
        epinephrine_given=False,
    )

    # The panel is untouched apart from its roll-up.
    stored_order = SETUP.read_order(api, order["id"])
    check.assert_allergy_test_order(
        stored_order,
        status=C.ORDER_ADMINISTERED,
        worst_systemic_grade=1,
        abort_reason=None,
        positive_antigen_count=0,
    )

    # The provisional score is unmoved by a grade-1 event.
    stored_patient = SETUP.read_patient(api, patient["id"])
    check.assert_patient(
        stored_patient,
        risk_score=5,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )


def test_patient_under_an_unknown_plan_is_not_found(api):
    """PRD 2.8: "Every identifier supplied inside the request body resolves to a
    stored row, resolved in the order the endpoint's input list declares them."

    Design: Corner/entities/patient_requires_existing_payer_policy_fk
    """
    # One plan is stored; the probed identifier belongs to no row.
    SETUP.create_policy(api, plan_code="ENTI-2999", payer_name="Fk Mutual")

    validate_error(
        api.create_patient(
            F.patient_payload(
                NON_EXISTENT_UUID,
                mrn=C.mrn(10197),
                full_name="Orphan Row",
                date_of_birth="1975-07-07",
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.PAYER_POLICY_NOT_FOUND.value,
    )

    _, meta = validate_paginated(api.list_patients(USERS.ADMIN_1))
    assert meta["total_count"] == 0


def test_patient_is_reverse_reachable_from_its_stored_plan(api):
    """PRD 3.1: "Patients can be listed and filtered by `payer_policy_id`, by
    `immunotherapy_status` and by `supervision_tier`."

    Design: Corner/entities/patient_requires_existing_payer_policy_fk
    """
    policy = SETUP.create_policy(api, plan_code="ENTI-2999", payer_name="Fk Mutual")

    # The identical body naming the stored plan is accepted.
    response = api.create_patient(
        F.patient_payload(
            policy["id"],
            mrn=C.mrn(10197),
            full_name="Orphan Row",
            date_of_birth="1975-07-07",
        ),
        USERS.ADMIN_1,
    )
    patient = validate_success(response, 201)
    assert patient["payer_policy_id"] == policy["id"]

    # The plan reaches its chart back through the filter.
    rows, meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    assert check.ids_in_order(rows) == [patient["id"]]


def test_undeclared_panel_code_and_undeclared_method_are_refused(api):
    """PRD 2.8: "The body and query conform to the endpoint's declared input: every
    required field is present; no unknown field is present; every value has the
    declared type; every enum-typed value is a declared member; every integer lies
    inside its declared range; every ISO-8601 instant is well formed and expressed
    in UTC; every calendar date is well formed; every regex-constrained string
    matches its pattern (`mrn` matches an `MRN-` prefix followed by exactly five
    digits; `plan_code` is three to twenty characters drawn only from uppercase
    letters, digits and hyphens; `serial_number` matches an `SC-` prefix followed by
    exactly four digits; `lot_number` matches a `LOT-` prefix followed by exactly
    four digits; `device_serial` is exactly two uppercase letters followed by
    exactly six digits); array fields declared non-empty are non-empty; a documented
    therapy item never has a `start_date` later than its `end_date`; a reaction event
    carries exactly one of `allergy_test_order_id` and `immunotherapy_dose_id`, so
    supplying both or neither fails here; a study-results payload carries exactly the
    metric set its `study_type` demands; `limit` lies between 1 and 100 inclusive and
    `offset` is not negative."

    Design: Corner/entities/allergy_test_order_rejects_undeclared_panel_code
    """
    policy = SETUP.create_policy(api, plan_code="ENTJ-2999", payer_name="Type Mutual")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10198),
        full_name="Range Probe",
        date_of_birth="1991-01-19",
        epinephrine_on_file=True,
    )
    SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )

    # A panel code that names no declared panel.
    validate_error(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                patient["id"], panel_code="ENV_12", method=C.METHOD_SKIN_PRICK
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # A method that names no declared technique.
    validate_error(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                patient["id"], panel_code=C.PANEL_ENV_36, method="PATCH_TEST"
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # Only the one well-formed panel exists.
    _, meta = validate_paginated(
        api.list_allergy_test_orders(
            USERS.ADMIN_1, params={"patient_id": patient["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_reading_above_the_antigen_count_is_refused_before_the_state_check(api):
    """PRD 3.3: "`positive_antigen_count` may never exceed the order's
    `antigen_count`; a larger figure fails the shape gate."

    Design: Corner/entities/allergy_test_order_rejects_undeclared_panel_code
    """
    policy = SETUP.create_policy(api, plan_code="ENTJ-2999", payer_name="Type Mutual")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10198),
        full_name="Range Probe",
        date_of_birth="1991-01-19",
        epinephrine_on_file=True,
    )
    order = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )

    # Thirteen positives on a twelve-antigen panel, while the panel is unadministered.
    validate_error(
        api.record_allergy_test_reading(
            order["id"], F.allergy_reading_payload(13), USERS.NURSE_1
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # The shape gate answered first, so the panel never moved.
    stored_order = SETUP.read_order(api, order["id"])
    check.assert_allergy_test_order(
        stored_order,
        status=C.ORDER_ORDERED,
        antigen_count=12,
        positive_antigen_count=0,
        administered_at=None,
    )
    check.assert_mutable_resource(stored_order, expected_version=1)


def test_plan_terms_outside_their_declared_range_or_pattern_are_refused(api):
    """PRD 2.8: "The body and query conform to the endpoint's declared input: every
    required field is present; no unknown field is present; every value has the
    declared type; every enum-typed value is a declared member; every integer lies
    inside its declared range; every ISO-8601 instant is well formed and expressed
    in UTC; every calendar date is well formed; every regex-constrained string
    matches its pattern (`mrn` matches an `MRN-` prefix followed by exactly five
    digits; `plan_code` is three to twenty characters drawn only from uppercase
    letters, digits and hyphens; `serial_number` matches an `SC-` prefix followed by
    exactly four digits; `lot_number` matches a `LOT-` prefix followed by exactly
    four digits; `device_serial` is exactly two uppercase letters followed by
    exactly six digits); array fields declared non-empty are non-empty; a documented
    therapy item never has a `start_date` later than its `end_date`; a reaction event
    carries exactly one of `allergy_test_order_id` and `immunotherapy_dose_id`, so
    supplying both or neither fails here; a study-results payload carries exactly the
    metric set its `study_type` demands; `limit` lies between 1 and 100 inclusive and
    `offset` is not negative."

    Design: Corner/entities/allergy_test_order_rejects_undeclared_panel_code
    """
    policy = SETUP.create_policy(api, plan_code="ENTJ-2999", payer_name="Type Mutual")

    # A coverage share above ten thousand basis points.
    validate_error(
        api.create_payer_policy(
            F.payer_policy_payload(
                payer_name="Out Of Range",
                plan_code="ENTK-2999",
                covered_pct_bps=20000,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # A plan code carrying a space and lowercase letters.
    validate_error(
        api.create_payer_policy(
            F.payer_policy_payload(payer_name="Bad Code", plan_code="bad code"),
            USERS.ADMIN_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # The stored plan is untouched by either refusal.
    stored = SETUP.read_policy(api, policy["id"])
    check.assert_payer_policy(stored, plan_code="ENTJ-2999", payer_name="Type Mutual")
    check.assert_mutable_resource(stored, expected_version=1)
