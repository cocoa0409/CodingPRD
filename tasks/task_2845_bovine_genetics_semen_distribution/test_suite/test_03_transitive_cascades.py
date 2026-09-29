"""Cascades that run three and four hops from a single call."""

import pytest

from test_helpers import (
    VET_ALT_USER_ID,
    assert_buckets,
    assert_instant_equals,
    fixtures as fx,
)

REG_A_PROOF = {
    "milk_kg": 900,
    "fat_kg": 40,
    "protein_kg": 30,
    "somatic_cell_score": 2.85,
    "fertility_pct": 1.5,
    "longevity_months": 2.0,
    "reliability_pct": 75,
    "progeny_daughter_count": 120,
    "effective_at": "2026-07-01T00:00:00Z",
}

CHILD_PROOF = {
    "milk_kg": 1100,
    "fat_kg": 45,
    "protein_kg": 36,
    "somatic_cell_score": 2.90,
    "fertility_pct": 2.0,
    "longevity_months": 3.0,
    "reliability_pct": 68,
    "progeny_daughter_count": 50,
    "effective_at": "2026-08-15T00:00:00Z",
}


class TestClockAdvanceExpirySuspensionVoidChain:
    """One clock move expires a test, suspends the bull and voids his booking."""

    @staticmethod
    def _bull_with_a_lapsing_assay(api):
        context = fx.eligible_sire(
            api,
            facility_overrides={
                "code": "F-IA-06",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            per_type_validity_days={"BLUETONGUE": 40},
        )
        context["booking"] = fx.book_collection(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            start_at="2026-09-20T08:00:00Z",
            end_at="2026-09-20T10:00:00Z",
        )
        return context

    def test_the_sweep_reports_every_id_it_touched(self, api):
        """The response body reports what the sweep touched, as `current_utc`
        alongside four id arrays — `expired_health_test_ids`,
        `suspended_sire_ids`, `voided_booking_ids` — plus `service_due_tank_ids`
        and `out_of_service_tank_ids` naming the tanks that landed in each of
        those two postures.

        Design: Difficulty/transitive_cascade/clock_advance_expiry_suspension_void_chain_depth_three
        """
        context = self._bull_with_a_lapsing_assay(api)
        lapsing = context["health_tests"]["BLUETONGUE"]
        assert_instant_equals(lapsing["valid_until"], "2026-09-10T00:00:00.000Z")

        sweep = fx.advance_clock(api, "2026-09-10T00:00:00Z")
        assert lapsing["id"] in sweep["expired_health_test_ids"]
        assert context["health_tests"]["IBR"]["id"] not in sweep["expired_health_test_ids"]
        assert context["sire"]["id"] in sweep["suspended_sire_ids"]
        assert context["booking"]["id"] in sweep["voided_booking_ids"]
        assert_instant_equals(sweep["current_utc"], "2026-09-10T00:00:00.000Z")

    def test_the_lapse_suspends_the_bull_and_voids_only_his_future_booking(self, api):
        """Second, every sire that thereby loses coverage of at least one of the
        four base required assays, and whose `collection_status` is `ELIGIBLE`,
        moves to `SUSPENDED` with `suspension_reason` set to
        `REQUIRED_TEST_EXPIRED`.

        Design: Difficulty/transitive_cascade/clock_advance_expiry_suspension_void_chain_depth_three
        """
        context = self._bull_with_a_lapsing_assay(api)
        fx.advance_clock(api, "2026-09-10T00:00:00Z")

        lapsed = fx.read_health_test(api, context["health_tests"]["BLUETONGUE"]["id"])
        assert lapsed["result"] == "EXPIRED"
        for test_type in ("IBR", "BVD", "TRICHOMONIASIS"):
            still_good = fx.read_health_test(
                api, context["health_tests"][test_type]["id"]
            )
            assert still_good["result"] == "NEGATIVE"

        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["collection_status"] == "SUSPENDED"
        assert sire["suspension_reason"] == "REQUIRED_TEST_EXPIRED"
        assert sire["acquisition_status"] == "RESIDENT"

        booking = fx.read_booking(api, context["booking"]["id"])
        assert booking["status"] == "VOIDED"


def _received_consignment_under_a_published_parent(api):
    """A RECEIVED 150-dose consignment against REG-C's RELEASED 200-straw lot."""
    parent = fx.register_sire(
        api,
        registration_code="REG-A",
        birth_date="2020-03-01",
        acquisition_cost_cents=0,
    )
    fx.published_proof(api, parent["id"], **REG_A_PROOF)
    return fx.received_consignment(
        api,
        doses=150,
        unit_price_cents=4000,
        distributor_overrides={"name": "D-US", "country_code": "US"},
        tank_overrides={"serial": "TK-7", "capacity_straws": 500},
        facility_overrides={
            "code": "F-IA-07",
            "housing_capacity": 4,
            "bench_capacity": 1,
            "approved_export_countries": ["CA"],
        },
        registration_code="REG-C",
        sire_overrides={
            "sire_id": parent["id"],
            "birth_date": "2023-05-01",
            "acquisition_cost_cents": 1500000,
        },
        product_line="CONVENTIONAL",
        straw_count=200,
        processing_cost_cents=250000,
    )


class TestProofPublicationRevaluationChain:
    """Publication walks four hops from the bull to the distributor's exposure."""

    def test_publication_walks_the_bull_lot_transfer_and_distributor_hops(self, api):
        """**Hop 3**, caused by hop 2, re-derives `carried_value_cents` on every
        consignment against a revalued lot, as that transfer's `doses_on_hand`
        multiplied by the lot's new `unit_book_value_cents`.

        Design: Difficulty/transitive_cascade/proof_publication_revaluation_chain_depth_four
        """
        context = _received_consignment_under_a_published_parent(api)
        before_transfer = fx.read_transfer(api, context["transfer"]["id"])
        assert before_transfer["carried_value_cents"] == 187500
        before_distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert before_distributor["consignment_value_cents"] == 187500

        draft = fx.file_evaluation(api, context["sire"]["id"], **CHILD_PROOF)
        published = fx.publish_evaluation(api, draft["id"])

        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["published_composite_index"] == pytest.approx(49.95, abs=0.01)
        assert_instant_equals(
            sire["published_evaluation_effective_at"], "2026-08-15T00:00:00.000Z"
        )

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 2248
        assert lot["valuation_basis"] == "MARKET_REVALUED"
        assert lot["pre_revaluation_unit_value_cents"] == 1250

        transfer = fx.read_transfer(api, context["transfer"]["id"])
        assert transfer["carried_value_cents"] == 337200

        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["consignment_value_cents"] == 337200

        assert published["revaluation_delta_cents"] == 199600

    def test_the_four_hop_cascade_moves_money_only(self, api):
        """**Ledger movements** are always transfers between buckets on one lot,
        never creations or destructions.

        Design: Difficulty/transitive_cascade/proof_publication_revaluation_chain_depth_four
        """
        context = _received_consignment_under_a_published_parent(api)
        draft = fx.file_evaluation(api, context["sire"]["id"], **CHILD_PROOF)
        fx.publish_evaluation(api, draft["id"])

        lot = fx.read_lot(api, context["lot"]["id"])
        assert_buckets(lot, 50, 0, 150, 0, 0)
        assert lot["distribution_status"] == "RELEASED"


class TestFacilitySuspensionCertificateChain:
    """A facility suspension reaches the bull and then his signed paperwork."""

    @staticmethod
    def _issued_certificate_at_an_approved_site(api):
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["BLUETONGUE", "IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
            sexed_semen_allowed=True,
            embryo_allowed=False,
        )
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-IA-08",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
        )
        context["certificate"] = fx.issued_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )
        return context

    def test_suspending_the_site_suspends_the_bull_it_houses(self, api):
        """The `APPROVED -> SUSPENDED` move stores that reason and then runs a
        two-hop cascade: every bull whose `housing_facility_id` is this facility
        and whose `collection_status` is `ELIGIBLE` becomes `SUSPENDED` with
        `suspension_reason` `FACILITY_SUSPENDED`.

        Design: Difficulty/transitive_cascade/facility_suspension_sire_certificate_chain_depth_three
        """
        context = self._issued_certificate_at_an_approved_site(api)
        certificate = context["certificate"]
        assert certificate["status"] == "ISSUED"
        assert certificate["issued_by_user_id"] == VET_ALT_USER_ID
        assert_instant_equals(certificate["expires_at"], "2027-08-01T00:00:00.000Z")

        suspended = fx.suspend_facility(
            api, context["facility"]["id"], suspension_reason="REGULATOR_AUDIT_FINDING"
        )
        assert suspended["approval_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "REGULATOR_AUDIT_FINDING"

        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["collection_status"] == "SUSPENDED"
        assert sire["suspension_reason"] == "FACILITY_SUSPENDED"
        assert sire["acquisition_status"] == "RESIDENT"

    def test_the_bull_suspension_revokes_his_issued_certificate(self, api):
        """A bull's suspension, from any of its four causes, voids his future
        `SCHEDULED` bookings and revokes his `ISSUED` export certificates.

        Design: Difficulty/transitive_cascade/facility_suspension_sire_certificate_chain_depth_three
        """
        context = self._issued_certificate_at_an_approved_site(api)
        fx.suspend_facility(
            api, context["facility"]["id"], suspension_reason="REGULATOR_AUDIT_FINDING"
        )

        certificate = fx.read_certificate(api, context["certificate"]["id"])
        assert certificate["status"] == "REVOKED"
        assert certificate["revocation_reason"] == "SIRE_SUSPENDED"

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["distribution_status"] == "RELEASED"
