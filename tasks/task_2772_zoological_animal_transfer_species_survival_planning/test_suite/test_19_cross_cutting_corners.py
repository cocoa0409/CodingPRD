"""Both concurrency tokens, the demotion threshold, and immediate derived reads."""

from __future__ import annotations

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_STALE_AGREEMENT_VERSION,
                                     ERR_STALE_ANIMAL_VERSION)
from test_helpers.assertions import (assert_date_equals, assert_money,
                                     assert_slot_counts)
from test_helpers.test_users import make_registrar_headers


class TestStaleSubjectAnimalVersion:
    """The animal token captured before an intervening write no longer holds."""

    def test_a_version_invalidated_by_a_crate_session_is_refused(self, api):
        """One logged session moves the animal on, and the old token is stale.

        PRD: "a `POST /population-recommendations` request must carry
        `expected_subject_animal_version`, a non-optional integer holding the
        client's last observed `version` of the subject `Animal`. If that value
        does not equal the subject animal's current `version`, the create is
        rejected with `ERR_STALE_ANIMAL_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/stale_expected_subject_animal_version_is_rejected_412
        """
        world = fx.base_pair(api)
        captured_version = world.m1_version
        assert captured_version == 1

        fx.crate_train(world, session_dates=["2026-07-28"])
        assert world.read_animal(world.m1_id)["version"] == 2

        response = api.create_recommendation(
            f.recommendation_payload(world.program_id, world.m1_id,
                                     captured_version,
                                     recommendation_type="HOLD",
                                     paired_animal_id=None),
            world.coordinator,
        )
        validate_error(response, ERR_STALE_ANIMAL_VERSION)

        _, meta = validate_paginated(api.list_recommendations(world.coordinator))
        assert meta["total_count"] == 0
        assert world.read_animal(world.m1_id)["pending_recommendation_id"] is None

    def test_the_retry_with_the_re_read_version_is_accepted(self, api):
        """Re-reading the animal yields the token the create then accepts.

        PRD: "the writer must re-read the animal — whose
        `pending_recommendation_id` now names the standing recommendation —
        before retrying."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_subject_animal_version_is_rejected_412
        """
        world = fx.base_pair(api)
        fx.crate_train(world, session_dates=["2026-07-28"])
        current_version = world.read_animal(world.m1_id)["version"]
        assert current_version == 2

        data = validate_success(
            api.create_recommendation(
                f.recommendation_payload(world.program_id, world.m1_id,
                                         current_version,
                                         recommendation_type="HOLD",
                                         paired_animal_id=None),
                world.coordinator,
            ),
            expected_status=201,
        )
        assert data["status"] == "PROPOSED"

        animal = world.read_animal(world.m1_id)
        assert animal["pending_recommendation_id"] == data["id"]
        assert animal["version"] == 3


class TestStaleTransferAgreementVersion:
    """Execution rewrites the agreement, so the acceptance token goes stale."""

    def test_the_version_observed_at_acceptance_is_refused_after_execution(
            self, api):
        """Booking on the pre-execution token is rejected on the token itself.

        PRD: "a `POST /shipment-bookings` request must carry
        `expected_transfer_agreement_version`, a non-optional integer holding
        the client's last observed `version` of the parent `TransferAgreement`.
        If that value does not equal the agreement's current `version`, the
        create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_transfer_agreement_version_is_rejected_412
        """
        world = fx.world_with_accepted_agreement(api)
        version_at_acceptance = world.ta_version
        fx.executed_agreement(world)
        version_after_execution = world.ta_version
        assert version_after_execution > version_at_acceptance

        response = api.create_booking(
            f.booking_payload(world.ta_id, version_at_acceptance),
            world.sender,
        )
        validate_error(response, ERR_STALE_AGREEMENT_VERSION)

        _, meta = validate_paginated(
            api.list_bookings(world.sender,
                              {"transfer_agreement_id": world.ta_id})
        )
        assert meta["total_count"] == 0

    def test_the_retry_on_the_post_execution_version_reserves_carriage(self, api):
        """The token read back after execution is the one the booking accepts.

        PRD: "A new booking opens with `status` at `RESERVED`,
        `temperature_samples` null because no journey has happened yet,
        `thermal_excursion_minutes` at 0, and `departed_at` and `delivered_at`
        null."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_transfer_agreement_version_is_rejected_412
        """
        world = fx.world_with_executed_agreement(api)
        current_version = world.read_agreement()["version"]

        data = validate_success(
            api.create_booking(
                f.booking_payload(world.ta_id, current_version),
                world.sender,
            ),
            expected_status=201,
        )
        assert data["status"] == "RESERVED"
        assert data["carrier_code"] == "AVI-CARGO-7"
        assert data["temperature_samples"] is None
        assert data["thermal_excursion_minutes"] == 0
        assert data["departed_at"] is None
        assert data["delivered_at"] is None


class TestComplianceThresholdDemotion:
    """A single late filing carries enough points to cost an accreditation."""

    def test_filing_computes_the_four_figures_and_posts_nothing(self, api):
        """Thirty-one days late earns 15.50, 0.40, 6.20 and 21.70, unposted.

        PRD: "`base_points` is `days_late` multiplied by half a point per day,
        rounded half up to two decimal places, and then **capped at 20
        points**; the cap is applied before anything else happens, not after."

        Design: Corner/cross_cutting_complexity_layers/compliance_points_threshold_demotes_an_accredited_institution
        """
        world = fx.base_world(api)
        data = fx.file_studbook_submission(world, submission_type="ACQUISITION",
                                           reporting_period_end="2026-06-01")
        assert_date_equals(data["submitted_on"], "2026-08-01", "submitted_on")
        assert data["days_late"] == 31
        assert_money(data["base_points"], 15.50, "base_points")
        assert_money(data["surcharge_multiplier"], 0.40, "surcharge_multiplier")
        assert_money(data["surcharge_points"], 6.20, "surcharge_points")
        assert_money(data["total_compliance_points"], 21.70,
                     "total_compliance_points")
        assert data["status"] == "SUBMITTED"

        institution = world.read_institution(world.sender_id)
        assert_money(institution["compliance_points_balance"], 0.00,
                     "compliance_points_balance")
        assert institution["accreditation_status"] == "ACCREDITED"

    def test_review_posts_the_points_and_demotes_the_institution(self, api):
        """21.70 has reached the exact 21.00 boundary, so accreditation falls.

        PRD: "If the posting leaves an institution that is currently
        `ACCREDITED` with a `compliance_points_balance` that has reached 21.00
        points or more, its `accreditation_status` is demoted to `PROVISIONAL`
        automatically; the boundary is exact, so a balance of 21.00 demotes and
        a balance of 20.99 does not."

        Design: Corner/cross_cutting_complexity_layers/compliance_points_threshold_demotes_an_accredited_institution
        """
        world = fx.base_world(api)
        filed = fx.file_studbook_submission(world, submission_type="ACQUISITION",
                                            reporting_period_end="2026-06-01")
        assert_money(filed["total_compliance_points"], 21.70,
                     "total_compliance_points")

        reviewed = fx.review_studbook_submission(
            world, filed["id"], outcome="ACCEPT", review_note="late but complete"
        )
        assert reviewed["status"] == "ACCEPTED"
        assert reviewed["review_note"] == "late but complete"
        assert reviewed["version"] == filed["version"] + 1

        institution = world.read_institution(world.sender_id)
        assert_money(institution["compliance_points_balance"], 21.70,
                     "compliance_points_balance")
        assert institution["accreditation_status"] == "PROVISIONAL"


class TestDerivedReadsAreImmediatelyVisible:
    """Every recomputed counter is readable on the very next request."""

    def test_the_accession_response_and_the_next_read_already_agree(self, api):
        """The 201 body carries the opening values and the holder already counts one.

        PRD: "A newly accessioned animal opens with `location_status` at `HELD`,
        `genetic_designation` at `UNEVALUATED`, `pending_recommendation_id`
        null, `crate_training_sessions_count` at 0 and `last_crate_session_on`
        null. The accession recomputes the programme's
        `current_population_count` and the holder's `occupied_slots`."

        Design: Corner/consistency_model/denormalised_counters_are_visible_in_the_same_request
        """
        world = fx.base_world(api)
        assert_slot_counts(world.read_institution(world.sender_id), 0, 0)

        created = validate_success(
            api.create_animal(
                f.animal_payload(world.program_id, world.sender_id),
                make_registrar_headers(world.sender_id),
            ),
            expected_status=201,
        )
        assert created["location_status"] == "HELD"
        assert created["crate_training_sessions_count"] == 0
        assert created["last_crate_session_on"] is None

        assert_slot_counts(world.read_institution(world.sender_id), 1, 0)
        assert world.read_program()["current_population_count"] == 1

    def test_a_logged_session_is_reflected_on_the_first_read_after_it(self, api):
        """The recomputed count and recency marker need no retry to appear.

        PRD: "An institution's `occupied_slots` and `reserved_slots`, a
        programme's `current_population_count` and `open_recommendation_count`,
        and an animal's `crate_training_sessions_count` are all recomputed from
        scratch on every write that could change them"

        Design: Corner/consistency_model/denormalised_counters_are_visible_in_the_same_request
        """
        world = fx.base_pair(api)
        validate_success(
            api.create_crate_training_session(
                world.m1_id,
                f.crate_training_session_payload(session_date="2026-07-28"),
                make_registrar_headers(world.sender_id),
            ),
            expected_status=201,
        )

        first_read = world.read_animal(world.m1_id)
        assert first_read["crate_training_sessions_count"] == 1
        assert_date_equals(first_read["last_crate_session_on"], "2026-07-28",
                           "last_crate_session_on")

        second_read = world.read_animal(world.m1_id)
        assert second_read == first_read
