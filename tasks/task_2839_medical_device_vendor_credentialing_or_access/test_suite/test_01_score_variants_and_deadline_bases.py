"""Two stored variants of one derivation reading differently from identical data."""

from __future__ import annotations

from test_helpers import (
    COMPLEXITY_COMPLEX,
    FEE_STATUS_REVERSED,
    INCIDENT_STATUS_REPORTED,
    INCIDENT_STATUS_SUBSTANTIATED,
    INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
    INCIDENT_TYPE_UNBADGED_ACCESS,
    LOANER_STATUS_DELIVERED_LATE,
    LOANER_STATUS_DELIVERED_ON_TIME,
    OUTCOME_SUBSTANTIATED,
    ACCESS_STATUS_PENDING,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    adjudicate_incident,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    read_case,
    read_incident,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    report_incident,
    reschedule_payload,
    OR_COORDINATOR,
    COMPLIANCE_ADMIN,
    validate_success,
)


class TestVendorScoreVariantsDiverge:
    """One reported and one substantiated incident pull the two scores apart."""

    @staticmethod
    def _setup(api):
        facility = create_facility(
            api, "MW-01", name="Mercy West Surgical Pavilion",
            spd_turnaround_hours=8, spd_bay_count=2,
        )
        vendor = create_vendor(api, "ORTHO", legal_name="Ortholine Devices Inc")
        rep = create_vendor_rep(api, vendor["id"], "Dana Reyes")
        case = create_case(
            api,
            facility["id"],
            "CASE-9001",
            "2026-09-05T08:00:00Z",
            "2026-09-05T10:00:00Z",
            procedure_name="Total Knee Arthroplasty",
        )
        minor = report_incident(
            api,
            case["id"],
            rep["id"],
            INCIDENT_TYPE_UNBADGED_ACCESS,
            SEVERITY_MINOR,
            headers=OR_COORDINATOR,
            narrative="Rep badge lent to a colleague at the kiosk.",
        )
        major = report_incident(
            api,
            case["id"],
            rep["id"],
            INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
            SEVERITY_MAJOR,
            headers=OR_COORDINATOR,
            narrative="Non-catalogued trial spacer opened in the field.",
        )
        return vendor, rep, minor, major

    def test_provisional_counts_the_open_incident_while_adjudicated_ignores_it(self, api):
        """Substantiating the MAJOR report leaves the two score variants three points apart.

        "The incident penalty is the sum, over the counted incidents, of three
        points for each `MINOR`, eight for each `MAJOR` and twenty for each
        `CRITICAL`." The provisional variant counts both incidents while the
        adjudicated variant counts only the substantiated one, so the gap is
        exactly the minor weight.

        Design: Difficulty/dual_variant_calc/vendor_provisional_vs_adjudicated_score_diverge_on_open_incident
        """
        vendor, _rep, _minor, major = self._setup(api)

        adjudicate_incident(api, major["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)

        stored = read_vendor(api, vendor["id"])
        assert_integer_field(stored, "provisional_compliance_score", 89)
        assert_integer_field(stored, "adjudicated_compliance_score", 92)
        assert (
            stored["adjudicated_compliance_score"]
            - stored["provisional_compliance_score"]
            == 3
        ), "the gap should be exactly the minor weight of the still-reported incident"

    def test_major_substantiation_moves_neither_the_open_incident_nor_the_rep(self, api):
        """The substantiated MAJOR incident does not touch its sibling or suspend the rep.

        "Only a `CRITICAL` incident of type `UNAPPROVED_PRODUCT_USE` suspends the
        representative", so a MAJOR substantiation of the same type leaves the
        representative exactly where it was.

        Design: Difficulty/dual_variant_calc/vendor_provisional_vs_adjudicated_score_diverge_on_open_incident
        """
        _vendor, rep, minor, major = self._setup(api)

        adjudicate_incident(api, major["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)

        adjudicated = read_incident(api, major["id"])
        assert adjudicated["status"] == INCIDENT_STATUS_SUBSTANTIATED
        assert adjudicated["adjudicated_outcome"] == OUTCOME_SUBSTANTIATED

        untouched = read_incident(api, minor["id"])
        assert untouched["status"] == INCIDENT_STATUS_REPORTED

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_PENDING


class TestLoanerDeadlineBasesDiverge:
    """A reschedule moves the current-basis deadline while the pinned basis stands."""

    @staticmethod
    def _setup(api):
        facility = create_facility(
            api, "ME-02", name="Mercy East Surgical Center",
            spd_turnaround_hours=8, spd_bay_count=2,
        )
        vendor = create_vendor(api, "SPNX", legal_name="Spinaxis Implants LLC")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "PS-X2-770",
            450000,
            is_implant=True,
            product_name="Pedicle Screw System X2",
            manufacturer="Spinaxis",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-9101",
            "2026-09-10T14:00:00Z",
            "2026-09-10T18:00:00Z",
            procedure_name="Lumbar Fusion L4-L5",
            implant_required=True,
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 9, COMPLEXITY_COMPLEX
        )
        received = receive_loaner_set(api, loaner["id"], "2026-09-09T14:37:00Z")
        assert received["status"] == LOANER_STATUS_DELIVERED_LATE
        return vendor, case, loaner

    def test_reschedule_splits_the_pinned_basis_from_the_current_basis(self, api):
        """One unchanged delivery instant reads 37 late minutes pinned and zero current.

        "`late_minutes_pinned_basis` is retained unchanged" while the
        current-basis figure is re-derived against the moved case, and
        "`original_scheduled_start_utc` ... never changes".

        Design: Difficulty/dual_variant_calc/loaner_pinned_versus_current_deadline_basis_after_reschedule
        """
        _vendor, case, loaner = self._setup(api)

        validate_success(
            api.reschedule_surgical_case(
                case["id"],
                reschedule_payload("2026-09-10T18:00:00Z", "2026-09-10T22:00:00Z"),
                OR_COORDINATOR,
            ),
            200,
        )

        moved = read_case(api, case["id"])
        assert_instant_equals(
            moved["original_scheduled_start_utc"],
            "2026-09-10T14:00:00Z",
            "original_scheduled_start_utc",
        )
        assert_instant_equals(
            moved["scheduled_start_utc"], "2026-09-10T18:00:00Z", "scheduled_start_utc"
        )

        stored = read_loaner_set(api, loaner["id"])
        assert_instant_equals(
            stored["pinned_deadline_utc"], "2026-09-09T14:00:00Z", "pinned_deadline_utc"
        )
        assert_instant_equals(
            stored["required_delivery_deadline_utc"],
            "2026-09-09T18:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_integer_field(stored, "late_minutes_pinned_basis", 37)
        assert_integer_field(stored, "late_minutes_current_basis", 0)
        assert stored["status"] == LOANER_STATUS_DELIVERED_ON_TIME

    def test_reversed_fee_retains_the_assessed_amount_and_clears_the_ledger(self, api):
        """The reversal debits the vendor while the historical assessment is kept.

        "if `fee_status` was `ASSESSED` it becomes `REVERSED` and the vendor's
        `late_fee_balance_cents` is debited by that set's
        `assessed_late_fee_cents` — the amount itself being retained as the
        historical assessment".

        Design: Difficulty/dual_variant_calc/loaner_pinned_versus_current_deadline_basis_after_reschedule
        """
        vendor, case, loaner = self._setup(api)

        validate_success(
            api.reschedule_surgical_case(
                case["id"],
                reschedule_payload("2026-09-10T18:00:00Z", "2026-09-10T22:00:00Z"),
                OR_COORDINATOR,
            ),
            200,
        )

        stored = read_loaner_set(api, loaner["id"])
        assert stored["fee_status"] == FEE_STATUS_REVERSED
        assert_money_cents(stored, "assessed_late_fee_cents", 1125)

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 0)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)
