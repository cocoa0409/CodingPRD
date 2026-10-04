"""Site qualification workflow and the automotive production gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_site_qualification_payload,
    get_pool,
    make_capacity_pool,
    make_part,
    qualify_site,
    validate_error,
    validate_success,
    get_part,
)

PLANNER = TEST_USERS["supply_planner_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]


class TestSiteQualification:
    def test_qualification_skip_in_review_rejected(self, api):
        """PRD §3.5: "From `REQUESTED` the engineer moves it to `IN_REVIEW`; from
        `IN_REVIEW` either to `QUALIFIED` or to the terminal `REJECTED`; from
        `QUALIFIED` to `SUSPENDED`; and from `SUSPENDED` back to `QUALIFIED`."
        PRD §3.5: "The transition request names a `to_state`, and any transition
        outside this graph is `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/qualification_skip_in_review_rejected
        """
        qual = validate_success(
            api.create_site_qualification(
                create_site_qualification_payload(site_name="KFAB", segment="INDUSTRIAL"),
                QUALITY,
            ),
            201,
        )
        assert qual["status"] == "REQUESTED"

        res = api.transition_site_qualification(qual["id"], {"to_state": "QUALIFIED"}, QUALITY)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        legal = validate_success(
            api.transition_site_qualification(qual["id"], {"to_state": "IN_REVIEW"}, QUALITY),
            200,
        )
        assert legal["status"] == "IN_REVIEW"

    def test_qualification_suspend_requalify_cycle(self, api):
        """PRD §3.5: "The automotive cascade ties qualification to capacity: when a
        qualification with `segment` `AUTOMOTIVE` becomes `QUALIFIED`, every capacity
        pool with the matching `site_name` recomputes `qualified_for_automotive` to
        true; when such a qualification is suspended, those same pools recompute
        `qualified_for_automotive` back to false."
        PRD §3.5: "from `QUALIFIED` to `SUSPENDED`; and from `SUSPENDED` back to
        `QUALIFIED`."

        Design: Corner/state_machines/qualification_suspend_requalify_cycle
        """
        pool = make_capacity_pool(
            site_name="ATX-ASSEMBLY", process_technology="ANALOG_BIPOLAR",
            total_units=500,
        )
        assert pool["qualified_for_automotive"] is False
        qual = qualify_site("ATX-ASSEMBLY", segment="AUTOMOTIVE")
        assert qual["status"] == "QUALIFIED"
        assert get_pool(pool["id"])["qualified_for_automotive"] is True

        suspended = validate_success(
            api.transition_site_qualification(qual["id"], {"to_state": "SUSPENDED"}, QUALITY),
            200,
        )
        assert suspended["status"] == "SUSPENDED"
        assert get_pool(pool["id"])["qualified_for_automotive"] is False

        requalified = validate_success(
            api.transition_site_qualification(qual["id"], {"to_state": "QUALIFIED"}, QUALITY),
            200,
        )
        assert requalified["status"] == "QUALIFIED"
        assert get_pool(pool["id"])["qualified_for_automotive"] is True

    def test_second_qualified_qualification_overlap_rejected(self, api):
        """PRD §3.5: "Entering `QUALIFIED` — whether from `IN_REVIEW` or from
        `SUSPENDED` — is permitted only when no other site qualification with the
        same `site_name` and `segment` is currently `QUALIFIED` or `SUSPENDED`; a
        conflict is `ERR_QUALIFICATION_OVERLAP` (HTTP 409)."

        Design: Corner/validations/second_qualified_qualification_overlap_rejected
        """
        qual_a = qualify_site("ATX-ASSEMBLY", segment="AUTOMOTIVE")
        assert qual_a["status"] == "QUALIFIED"

        qual_b = validate_success(
            api.create_site_qualification(
                create_site_qualification_payload(site_name="ATX-ASSEMBLY", segment="AUTOMOTIVE"),
                QUALITY,
            ),
            201,
        )
        validate_success(
            api.transition_site_qualification(qual_b["id"], {"to_state": "IN_REVIEW"}, QUALITY),
            200,
        )
        res = api.transition_site_qualification(qual_b["id"], {"to_state": "QUALIFIED"}, QUALITY)
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_OVERLAP)

    def test_automotive_receipt_blocked_when_site_qualification_suspended(self, api):
        """PRD §3.5: "And when the part being received has `automotive_grade` true,
        the pool's `qualified_for_automotive` must be true, meaning the site holds a
        currently `QUALIFIED` automotive qualification — otherwise
        `ERR_SITE_NOT_QUALIFIED` (HTTP 422)."
        PRD §3.5: "when such a qualification is suspended, those same pools recompute
        `qualified_for_automotive` back to false."

        Design: Difficulty/cross_entity_state_dependency/automotive_receipt_blocked_when_site_qualification_suspended
        """
        part = make_part(
            part_number="LM2904QDRQ1", package_family="SOIC", automotive_grade=True
        )
        pool = make_capacity_pool(
            site_name="ATX-ASSEMBLY", process_technology="ANALOG_BIPOLAR",
            total_units=500,
        )
        qual = qualify_site("ATX-ASSEMBLY", segment="AUTOMOTIVE")

        first = validate_success(
            api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 10}, PLANNER),
            201,
        )
        assert first["on_hand_units"] == 10

        validate_success(
            api.transition_site_qualification(qual["id"], {"to_state": "SUSPENDED"}, QUALITY),
            200,
        )
        assert get_pool(pool["id"])["qualified_for_automotive"] is False

        res = api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 5}, PLANNER)
        validate_error(res, ApiErrorId.ERR_SITE_NOT_QUALIFIED)

        assert get_part(part["id"])["on_hand_units"] == 10
        final_pool = get_pool(pool["id"])
        assert final_pool["allocated_units"] == 10
        assert final_pool["qualified_for_automotive"] is False

    def test_non_automotive_receipt_unaffected_by_suspension(self, api):
        """PRD §3.5: "And when the part being received has `automotive_grade` true,
        the pool's `qualified_for_automotive` must be true, meaning the site holds a
        currently `QUALIFIED` automotive qualification — otherwise
        `ERR_SITE_NOT_QUALIFIED` (HTTP 422)."
        PRD §3.1: "`automotive_grade`, a boolean marking the part as qualified for
        automotive applications, defaults to false".

        Design: Difficulty/cross_entity_state_dependency/automotive_receipt_blocked_when_site_qualification_suspended
        """
        part = make_part(part_number="LM2904DR", package_family="SOIC")
        pool = make_capacity_pool(
            site_name="ATX-ASSEMBLY", process_technology="ANALOG_BIPOLAR",
            total_units=500,
        )
        qual = qualify_site("ATX-ASSEMBLY", segment="AUTOMOTIVE")
        validate_success(
            api.transition_site_qualification(qual["id"], {"to_state": "SUSPENDED"}, QUALITY),
            200,
        )
        assert get_pool(pool["id"])["qualified_for_automotive"] is False

        res = validate_success(
            api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 25}, PLANNER),
            201,
        )
        assert res["on_hand_units"] == 25
        assert get_pool(pool["id"])["allocated_units"] == 25
