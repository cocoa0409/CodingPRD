"""Massive transfusion protocol: pack constitution, wind-down gates."""
from test_helpers import (
    ApiErrorId,
    dispatch_mtp_pack,
    get_issue,
    get_mtp,
    get_success_data,
    get_unit,
    make_mtp,
    make_patient,
    make_stock,
    receive_unit_descriptor,
    validate_error,
    validate_paginated,
    validate_success,
    DOC_1,
    TECH_A,
    api_client,
)

MTP_REASON = "trauma bay hemorrhage protocol"


def _setup_mtp_stock(api):
    """Untyped MTP patient; stock: 2 RBC O NEG, 2 FFP AB NEG, one O NEG and one
    (earlier-expiring) A NEG apheresis platelet."""
    stock = make_stock([
        receive_unit_descriptor("U-R1", donor_id="D-620", lot_number="LOT-3"),
        receive_unit_descriptor("U-R2", donor_id="D-621", lot_number="LOT-3"),
        receive_unit_descriptor("U-F1", product_type="FFP", abo_type="AB",
                                volume_ml=250, donor_id="D-622", lot_number="LOT-3"),
        receive_unit_descriptor("U-F2", product_type="FFP", abo_type="AB",
                                volume_ml=250, donor_id="D-623", lot_number="LOT-3"),
        receive_unit_descriptor("U-P-O", product_type="PLT_APHERESIS",
                                volume_ml=200, collected_at="2026-08-06T00:00:00Z",
                                donor_id="D-624", lot_number="LOT-3"),
        receive_unit_descriptor("U-P-A", product_type="PLT_APHERESIS",
                                abo_type="A", volume_ml=200,
                                collected_at="2026-08-05T20:00:00Z",
                                donor_id="D-625", lot_number="LOT-3"),
    ])
    patient = make_patient(mrn="M-9002", full_name="Pat Two",
                           date_of_birth="1985-11-02")
    mtp = make_mtp(patient["id"], MTP_REASON)
    return stock, patient, mtp


class TestPackConstitution:
    def test_mtp_pack_composition_and_preference_over_fefo(self, api):
        """PRD §3.6: "The pack has a fixed constitution, filled in a pinned order
        so that later components observe earlier decrements: four `RBC` units
        first, then two `FFP`, then one `PLT_APHERESIS`."
        PRD §3.6: "For the apheresis platelet the preference runs the patient's own
        group — or O when untyped — with Rh-negative, then A-negative, B-negative,
        AB-negative, and O-negative, de-duplicated so each bucket appears only at
        its first occurrence."
        PRD §3.6: "When every bucket is exhausted with a component still short, the
        dispatch records a shortfall naming the `product_type` and `missing_qty`
        and continues — dispatch never fails on short stock."

        Design: Difficulty/combinatorial_formula/mtp_pack_constitution_evaluation_order
        """
        stock, _patient, mtp = _setup_mtp_stock(api)
        pack = validate_success(api.dispatch_pack(
            mtp["id"], {"verified_by_user_id": "tech-b"}, TECH_A))
        assert pack["pack_number"] == 1
        # The PRD admits two faithful readings of how the platelet preference
        # walk interacts with the untyped-patient plasma-class compatibility
        # short-circuit (§3.4 step 2 vs §3.6 "or O when untyped"), so no exact
        # issue count or platelet outcome is asserted here — only what both
        # readings agree on.
        assert get_unit(stock["units"]["U-R1"]["id"])["status"] == "ISSUED"
        assert get_unit(stock["units"]["U-R2"]["id"])["status"] == "ISSUED", (
            "an untyped patient accepts only (O,NEG) red cells and just 2 exist"
        )
        assert get_unit(stock["units"]["U-F1"]["id"])["status"] == "ISSUED"
        assert get_unit(stock["units"]["U-F2"]["id"])["status"] == "ISSUED", (
            "the untyped FFP preference is AB-negative alone and both exist"
        )
        assert {"product_type": "RBC", "missing_qty": 2} in pack["shortfalls"], (
            "the red-cell component shortfalls by the two units not in stock"
        )
        assert get_unit(stock["units"]["U-P-A"]["id"])["status"] == "AVAILABLE", (
            "the (A,NEG) platelet is not selected: under every faithful reading "
            "the (O,NEG) bucket is walked first for an untyped patient"
        )

    def test_mtp_pack_issues_emergency_semantics(self, api):
        """PRD §3.6: "Each selected unit becomes an issue record created under
        emergency semantics: `is_emergency_release` true, `mtp_activation_id` set
        to the activation, `emergency_justification` copied from the activation's
        `activation_reason`, and the caller-supplied `verified_by_user_id`
        recorded."
        PRD §3.6: "the activation's `packs_dispatched` increments by one and
        `units_issued_total` tracks every issue record created under it."

        Design: Difficulty/combinatorial_formula/mtp_pack_constitution_evaluation_order
        """
        _stock, _patient, mtp = _setup_mtp_stock(api)
        pack = validate_success(api.dispatch_pack(
            mtp["id"], {"verified_by_user_id": "tech-b"}, TECH_A))
        for issue_id in pack["issue_record_ids"]:
            issue = get_issue(issue_id)
            assert issue["is_emergency_release"] is True
            assert issue["mtp_activation_id"] == mtp["id"]
            assert issue["emergency_justification"] == MTP_REASON
            assert issue["verified_by_user_id"] == "tech-b"
        mtp = get_mtp(mtp["id"])
        assert mtp["packs_dispatched"] == 1
        # PRD §3.6: "units_issued_total tracks every issue record created under
        # it" — the concrete fill count depends on the platelet-preference /
        # compatibility interaction the PRD leaves ambiguous, so the pinned
        # tracking invariant is asserted instead of a hard-coded count.
        assert mtp["units_issued_total"] == len(pack["issue_record_ids"])


class TestMtpWindDown:
    def test_mtp_deactivate_with_outstanding_units_rejected(self, api):
        """PRD §3.6: "Deactivation requires `STANDING_DOWN`
        (`ERR_MTP_NOT_STANDING_DOWN`) and is blocked while any issue record created
        under the activation still stands in `ISSUED` or `TRANSFUSION_STARTED`
        (`ERR_MTP_UNITS_OUTSTANDING`, HTTP 409) — outstanding units must be
        returned, completed, or stopped first."

        Design: Corner/state_machines/mtp_deactivate_with_outstanding_units_rejected
        """
        make_stock([receive_unit_descriptor("U-100")])
        patient = make_patient(mrn="M-2006", full_name="Jon Doe",
                               date_of_birth="1993-04-04")
        mtp = make_mtp(patient["id"], "trauma hemorrhage")
        pack = dispatch_mtp_pack(mtp["id"])
        assert len(pack["issue_record_ids"]) == 1, "one O NEG RBC unit available"
        get_success_data(api.stand_down_mtp(mtp["id"], DOC_1))

        resp = api.deactivate_mtp(mtp["id"], DOC_1)
        validate_error(resp, ApiErrorId.ERR_MTP_UNITS_OUTSTANDING)
        assert get_mtp(mtp["id"])["status"] == "STANDING_DOWN"

    def test_error_mtp_already_active(self, api):
        """PRD §3.6: "A patient may host at most one `ACTIVATED` protocol at a time
        — a second attempt meets `ERR_MTP_ALREADY_ACTIVE` (HTTP 409)."

        Design: Corner/errors/error_mtp_already_active
        """
        patient = make_patient(mrn="M-4007", full_name="Ted Doe",
                               date_of_birth="1969-06-06")
        make_mtp(patient["id"], "trauma protocol alpha")
        resp = api.create_mtp_activation(
            {"patient_id": patient["id"],
             "activation_reason": "second activation attempt"}, DOC_1)
        validate_error(resp, ApiErrorId.ERR_MTP_ALREADY_ACTIVE)
        _data, meta = validate_paginated(api.list_mtp_activations(
            TECH_A, params={"patient_id": patient["id"]}))
        assert meta["total_count"] == 1
