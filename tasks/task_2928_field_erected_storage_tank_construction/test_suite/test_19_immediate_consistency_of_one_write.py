"""Immediate consistency: the write's own body, the next item read and the list read.

There is no queue and no worker anywhere in this API, so a cascade that crosses
an aggregate boundary has to be complete by the time the response is written and
has to be visible to the very next read, item and collection alike.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_object_envelope,
    assert_settlement,
    assert_spacing,
    assert_thickness,
)
from test_helpers.constants import (
    ALLOWABLE_DIFFERENTIAL_IN_RATIO_0_005,
    CLOCK_BASE,
    DECISION_ACCEPT,
    PHASE_DESIGN_REGISTERED,
    PHASE_FOUNDATION_ACCEPTED,
    PKG_ACCEPTED,
    PKG_BASELINE_SET,
    PKG_PLANNED,
    POINT_SPACING_IN_8_POINTS_100FT,
    POSTURE_OPEN,
    SURVEY_ROLE_BASELINE,
    VERDICT_BASELINE,
)
from test_helpers.factories import (
    foundation_acceptance_payload,
    settlement_survey_payload,
)
from test_helpers.test_users import CC1, ES1, PE1, PE1_ID


class TestOneWriteIsCompleteWhenItAnswers:
    def test_the_acceptance_body_the_tank_read_and_both_list_reads_all_agree_at_once(
        self, api
    ):
        """No settling time, no re-read loop: the cascade is in the next read.

        PRD: "Unless otherwise noted, operations that create or modify a resource will return
        the created or updated resource object in the data field."

        PRD: "Creating the package freezes a tolerance envelope from that configuration and the
        parent tank's geometry. The arc distance between adjacent monitoring points,
        stored as `point_spacing_in`, is the tank circumference in inches divided by the
        number of monitoring points: take the mathematical constant pi
        (3.141592653589793), multiply by `diameter_ft`, multiply by the 12 inches in a
        foot, and divide by `monitoring_point_count`; the result is rounded half up to 4
        decimal places. The allowable differential settlement, stored as
        `allowable_differential_in`, is `permitted_differential_ratio` multiplied by that
        spacing, rounded half up to 3 decimal places. The package is created with `status`
        at `PLANNED`, `baseline_survey_id` null, and `decided_by_user_id`,
        `decided_at_utc` and `decision_remarks` all null."

        PRD: "The first survey recorded against a package — the one taken while the package
        still has no `baseline_survey_id` — becomes the datum. Its `survey_role` is set to
        `BASELINE`, its `verdict` is set to `BASELINE`, its `uniform_settlement_in` is
        0.000 by definition, the package's `baseline_survey_id` is pointed at the new
        survey, and the package moves `PLANNED → BASELINE_SET`."

        PRD: "On `ACCEPT`, the package moves `BASELINE_SET → ACCEPTED` (a terminal status),
        `decided_by_user_id` and `decided_at_utc` are stamped from the acting operator and
        the logical clock, `decision_remarks` is stored, and the tank advances
        `DESIGN_REGISTERED → FOUNDATION_ACCEPTED` with its `version` incremented and
        `updated_at` refreshed."

        Design: Corner/consistency_model/cascaded_and_derived_fields_are_correct_in_the_same_response
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        version_at_creation = tank["version"]
        assert tank["construction_phase"] == PHASE_DESIGN_REGISTERED

        # The create response already carries the frozen tolerance envelope.
        package = X.create_foundation_package(api, tank["id"])
        assert package["status"] == PKG_PLANNED
        assert package["baseline_survey_id"] is None
        assert_spacing(package["point_spacing_in"], POINT_SPACING_IN_8_POINTS_100FT)
        assert_thickness(
            package["allowable_differential_in"],
            ALLOWABLE_DIFFERENTIAL_IN_RATIO_0_005,
            "allowable differential",
        )

        # The datum's own create response already carries its classification.
        baseline = assert_object_envelope(
            api.create_settlement_survey(
                settlement_survey_payload(package["id"], X.UNIFORM_BASELINE, 0.0), CC1
            ),
            201,
        )
        assert baseline["survey_role"] == SURVEY_ROLE_BASELINE
        assert baseline["verdict"] == VERDICT_BASELINE
        assert_settlement(baseline["uniform_settlement_in"], 0.000, "baseline uniform settlement")
        assert X.read_foundation_package(api, package["id"])["status"] == PKG_BASELINE_SET

        accepted = assert_object_envelope(
            api.foundation_acceptance(
                package["id"], foundation_acceptance_payload(DECISION_ACCEPT), PE1
            ),
            200,
        )
        assert accepted["status"] == PKG_ACCEPTED
        assert accepted["baseline_survey_id"] == baseline["id"]
        assert accepted["decided_by_user_id"] == PE1_ID
        assert_instant(accepted["decided_at_utc"], CLOCK_BASE, "decision stamp")

        # The cross-aggregate effect is already visible on the very next read.
        cascaded = X.read_tank(api, tank["id"])
        assert cascaded["construction_phase"] == PHASE_FOUNDATION_ACCEPTED
        assert cascaded["quality_posture"] == POSTURE_OPEN
        assert cascaded["version"] > version_at_creation

        rows, _ = assert_list_total(
            api.list_foundation_packages(
                ES1, {"tank_id": tank["id"], "status": PKG_ACCEPTED}
            ),
            1,
        )
        assert rows[0]["id"] == package["id"]
        assert rows[0]["status"] == PKG_ACCEPTED
        assert rows[0]["baseline_survey_id"] == baseline["id"]

        surveys, _ = assert_list_total(
            api.list_settlement_surveys(
                CC1,
                {"foundation_package_id": package["id"], "survey_role": SURVEY_ROLE_BASELINE},
            ),
            1,
        )
        assert surveys[0]["id"] == baseline["id"]
        assert surveys[0]["verdict"] == VERDICT_BASELINE
