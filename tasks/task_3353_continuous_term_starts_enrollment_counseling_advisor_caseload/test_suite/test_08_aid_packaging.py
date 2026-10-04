"""Award packaging variants, Pell/COA tier interaction, package uniqueness."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, setup_registered_enrollment,
    setup_open_term_scenario, create_advisor, create_counselor,
    create_applicant, create_submitted_application, admit_application,
    create_completed_tce, create_enrollment, create_aid_package,
    certify_aid_package, assert_aid_package,
)

REGISTRAR = TEST_USERS["registrar_headers"]
FAO1 = TEST_USERS["fao1_headers"]
FAO2 = TEST_USERS["fao2_headers"]


class TestAwardPackagingEstimatedVsCertifiedIntensity:
    def test_estimated_award_assumes_full_time(self):
        """PRD §3.8: "The estimate always assumes full-time attendance
        regardless of the enrollment's actual `enrollment_intensity`: the
        cost of attendance for `FULL_TIME` is 800,000 cents ($8,000), and the
        award is the smaller of the federal Pell maximum of 739,500 cents
        ($7,395) and the amount by which that cost of attendance exceeds
        `efc_cents` — never below zero."
        PRD §3.8: "The package's `certified_award_cents` is 0 until
        certification, and `disbursed_cents`, `returned_cents`,
        `retained_cents`, and `cancelled_cents` all start at 0."

        Design: Difficulty/dual_variant_calc/award_packaging_estimated_vs_certified_intensity
        """
        ctx = setup_registered_enrollment(intensity="HALF_TIME")
        resp = api_client.create_aid_package(
            ctx["enrollment"]["id"], 100000, FAO1)
        data = validate_success(resp, expected_status=201)
        assert_aid_package(data)
        # min(739500, 800000 - 100000) = 700000 despite HALF_TIME intensity.
        assert data["estimated_award_cents"] == 700000, (
            f"ESTIMATED variant must price HALF_TIME at full-time COA; got "
            f"{data['estimated_award_cents']}")
        assert data["certified_award_cents"] == 0
        assert data["status"] == "PACKAGED"

    def test_certified_award_uses_actual_intensity(self):
        """PRD §3.8: "Certification computes `certified_award_cents` using
        the same award formula as the estimate but keyed to the enrollment's
        actual `enrollment_intensity` — a `HALF_TIME` enrollment is priced
        against a 500,000-cent ($5,000) cost of attendance and a
        `LESS_THAN_HALF_TIME` enrollment against 200,000 cents ($2,000) — so
        identical inputs produce a different number whenever the intensity is
        not `FULL_TIME`."

        Design: Difficulty/dual_variant_calc/award_packaging_estimated_vs_certified_intensity
        """
        ctx = setup_registered_enrollment(intensity="HALF_TIME")
        package = create_aid_package(ctx["enrollment"]["id"], 100000, FAO1)
        resp = api_client.certify_aid_package(
            package["id"], ctx["enrollment"]["version"], FAO2)
        data = validate_success(resp, expected_status=200)
        assert_aid_package(data)
        # min(739500, 500000 - 100000) = 400000 under the CERTIFIED variant.
        assert data["certified_award_cents"] == 400000, (
            f"CERTIFIED variant must use HALF_TIME COA; got "
            f"{data['certified_award_cents']}")
        assert data["estimated_award_cents"] == 700000
        assert data["estimated_award_cents"] != data["certified_award_cents"], (
            "identical inputs must diverge across variants when intensity "
            "is not FULL_TIME")


class TestAwardPackagingTieredCapInteraction:
    def _enroll_with_package(self, ctx, intensity, tuition, efc):
        applicant = create_applicant()
        application = create_submitted_application(
            applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
        application = admit_application(application["id"])
        create_completed_tce(application["id"])
        enrollment = create_enrollment(application, ctx["advisor"]["id"],
                                       intensity=intensity,
                                       tuition_cents=tuition)
        package = create_aid_package(enrollment["id"], efc, FAO1)
        return enrollment, package

    def _setup(self):
        ctx = setup_open_term_scenario()
        ctx["advisor"] = create_advisor(cap=5)
        create_counselor(cap=10)
        return ctx

    def test_full_time_zero_efc_certifies_at_pell_ceiling(self):
        """PRD §3.8: "the award is the smaller of the federal Pell maximum of
        739,500 cents ($7,395) and the amount by which that cost of
        attendance exceeds `efc_cents` — never below zero."
        PRD §3.8: "Entry one releases on the term's `census_date` for half of
        `certified_award_cents` rounded down to a whole cent; entry two
        releases at the midpoint for the remainder — `certified_award_cents`
        minus entry one's amount — so an odd cent always lands on the second
        entry."

        Design: Difficulty/combinatorial_formula/award_packaging_tiered_cap_interaction
        """
        ctx = self._setup()
        enrollment, package = self._enroll_with_package(
            ctx, "FULL_TIME", 500000, 0)
        data = certify_aid_package(package["id"], enrollment["version"], FAO2)
        # min(739500, 800000 - 0): the Pell ceiling binds, not the COA term.
        assert data["certified_award_cents"] == 739500, (
            f"FULL_TIME efc 0 must certify at the Pell ceiling 739500; got "
            f"{data['certified_award_cents']}")
        schedule = data["disbursement_schedule"]
        assert len(schedule) == 2
        first, second = schedule
        assert first["sequence"] == 1
        assert str(first["release_date"]).startswith("2026-10-19"), (
            f"entry 1 releases on census_date 2026-10-19; got "
            f"{first['release_date']}")
        assert first["amount_cents"] == 369750
        assert second["sequence"] == 2
        assert str(second["release_date"]).startswith("2026-11-09"), (
            f"entry 2 releases at the midpoint (start + floor(70/2) days = "
            f"2026-11-09); got {second['release_date']}")
        assert second["amount_cents"] == 369750
        assert first["amount_cents"] + second["amount_cents"] == 739500

    def test_less_than_half_time_zero_efc_certifies_at_coa(self):
        """PRD §3.8: "Certification computes `certified_award_cents` using
        the same award formula as the estimate but keyed to the enrollment's
        actual `enrollment_intensity` — a `HALF_TIME` enrollment is priced
        against a 500,000-cent ($5,000) cost of attendance and a
        `LESS_THAN_HALF_TIME` enrollment against 200,000 cents ($2,000) — so
        identical inputs produce a different number whenever the intensity is
        not `FULL_TIME`."

        Design: Difficulty/combinatorial_formula/award_packaging_tiered_cap_interaction
        """
        ctx = self._setup()
        enrollment, package = self._enroll_with_package(
            ctx, "LESS_THAN_HALF_TIME", 100000, 0)
        data = certify_aid_package(package["id"], enrollment["version"], FAO2)
        # min(739500, 200000 - 0): the COA term binds; Pell is irrelevant.
        assert data["certified_award_cents"] == 200000, (
            f"LESS_THAN_HALF_TIME efc 0 must certify at its COA 200000; got "
            f"{data['certified_award_cents']}")


def test_package_already_exists_conflict():
    """PRD §3.8: "An enrollment may carry only one active package: if a
    package already exists in `PACKAGED`, `CERTIFIED`, or `DISBURSING`, the
    create is rejected with `ERR_PACKAGE_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/validations/package_already_exists_conflict
    """
    ctx = setup_registered_enrollment()
    create_aid_package(ctx["enrollment"]["id"], 0, FAO1)
    resp = api_client.create_aid_package(ctx["enrollment"]["id"], 5000, FAO2)
    validate_error(resp, ApiErrorId.ERR_PACKAGE_ALREADY_EXISTS)
