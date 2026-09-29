"""The error catalog: authentication, authorisation, resolution and uniqueness.

Each family of identifiers is proved to be distinct from its neighbours - a
blank header is not a forbidden role, a 404 names the family that failed to
resolve, and a scoped uniqueness clash is not a singleton clash.
"""

from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_APPURTENANCE_NOT_FOUND,
    ERR_COATING_APPLICATION_NOT_FOUND,
    ERR_COMMISSIONING_PACKAGE_NOT_FOUND,
    ERR_COURSE_STATE_INVALID,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_FORBIDDEN_ROLE,
    ERR_FOUNDATION_NOT_ACCEPTED,
    ERR_FOUNDATION_PACKAGE_NOT_FOUND,
    ERR_FOUNDATION_STATE_INVALID,
    ERR_HYDROTEST_PLAN_NOT_FOUND,
    ERR_NDE_REPORT_NOT_FOUND,
    ERR_PLATE_LOT_NOT_FOUND,
    ERR_PLATE_LOT_STATE_INVALID,
    ERR_SEAM_NOT_WELDABLE,
    ERR_SETTLEMENT_SURVEY_NOT_FOUND,
    ERR_SHELL_COURSE_NOT_FOUND,
    ERR_SINGLETON_EXISTS,
    ERR_TANK_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_WATER_SOURCE_NOT_FOUND,
    ERR_WATER_WITHDRAWAL_NOT_FOUND,
    ERR_WELD_SEAM_NOT_FOUND,
    ERR_WELDER_NOT_FOUND,
    ERR_WITHDRAWAL_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_error_envelope_meta,
    assert_instant,
    assert_list_total,
    assert_money,
    assert_object_envelope,
    assert_source_ledger,
    assert_weight,
)
from test_helpers.constants import (
    CLOCK_BASE,
    COURSE_FITTED,
    COURSE_SPECIFIED,
    DECISION_ACCEPT,
    GHOST_UUID,
    LOT_ORDERED,
    LOT_RECEIVED,
    LOT_ROLLED,
    LOT_SHIPPED,
    PHASE_FOUNDATION_ACCEPTED,
    PKG_ACCEPTED,
    PKG_BASELINE_SET,
    PKG_PLANNED,
    PROCESS_FCAW,
    SEAM_FIT_READY,
    SEAM_HORIZONTAL,
    SOURCE_MUNICIPAL,
    WITHDRAWAL_CANCELLED,
)
from test_helpers.factories import (
    appurtenance_payload,
    commissioning_package_payload,
    foundation_acceptance_payload,
    foundation_package_payload,
    lot_status_payload,
    shell_course_payload,
    tank_payload,
    water_source_payload,
    weld_log_payload,
    weld_seam_payload,
    welder_payload,
    withdrawal_cancellation_payload,
    withdrawal_payload,
)
from test_helpers.test_users import (
    AI1,
    BLANK_USER_ID,
    BLANK_USER_ROLE,
    CC1,
    ES1,
    PE1,
    PE1_ID,
    QC1,
    headers_for_role,
    welder_headers,
)


class TestAuthenticationAndAuthorisation:
    def test_blank_identity_is_a_401_while_a_wrong_role_is_a_403(self, api):
        """Blank means the literal empty string, and an unknown role is not a 400.

        PRD: "If either header is absent, or is present but holds an empty string, the request
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD: "If `X-User-Role` holds a string that is not one of those six spellings, or holds a
        valid role that is not authorised for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD: "Authentication and authorisation come first, in three steps: header presence
        (`ERR_UNAUTHENTICATED`), then role validity and endpoint authorisation
        (`ERR_FORBIDDEN_ROLE`), then — on a weld log only — the welder-identity match
        (`ERR_WELDER_IDENTITY_MISMATCH`)."

        Design: Corner/errors/blank_headers_and_wrong_roles_are_rejected
        """
        validate_error(api.list_tanks(BLANK_USER_ID), ERR_UNAUTHENTICATED, 401)
        validate_error(api.list_tanks(BLANK_USER_ROLE), ERR_UNAUTHENTICATED, 401)

        validate_error(
            api.list_tanks(headers_for_role(PE1_ID, "Foreman")), ERR_FORBIDDEN_ROLE, 403
        )
        validate_error(api.create_tank(tank_payload(), CC1), ERR_FORBIDDEN_ROLE, 403)
        validate_error(api.create_welder(welder_payload(), QC1), ERR_FORBIDDEN_ROLE, 403)

        assert_list_total(api.list_tanks(PE1), 0)
        assert_list_total(api.list_welders(PE1), 0)


class TestIdentifierResolution:
    def test_each_route_family_answers_with_its_own_not_found_identifier(self, api):
        """One syntactically valid UUID, fourteen different error identifiers.

        PRD: "A tank identifier that does not resolve yields `ERR_TANK_NOT_FOUND`; a foundation
        package identifier yields `ERR_FOUNDATION_PACKAGE_NOT_FOUND`; a settlement survey
        identifier yields `ERR_SETTLEMENT_SURVEY_NOT_FOUND`; a plate lot identifier yields
        `ERR_PLATE_LOT_NOT_FOUND`; a shell course identifier yields
        `ERR_SHELL_COURSE_NOT_FOUND`; a welder identifier yields `ERR_WELDER_NOT_FOUND`; a
        weld seam identifier yields `ERR_WELD_SEAM_NOT_FOUND`; an examination report
        identifier yields `ERR_NDE_REPORT_NOT_FOUND`; a water source identifier yields
        `ERR_WATER_SOURCE_NOT_FOUND`; a hydrostatic test plan identifier yields
        `ERR_HYDROTEST_PLAN_NOT_FOUND`; a withdrawal identifier yields
        `ERR_WATER_WITHDRAWAL_NOT_FOUND`; a coating application identifier yields
        `ERR_COATING_APPLICATION_NOT_FOUND`; an appurtenance identifier yields
        `ERR_APPURTENANCE_NOT_FOUND`; and a commissioning package identifier yields
        `ERR_COMMISSIONING_PACKAGE_NOT_FOUND`. All fourteen carry HTTP 404."

        PRD: "Exactly the same mapping governs foreign keys arriving in a request **body**,
        which are resolved in the order the endpoint declares its input fields; a
        body-borne `tank_id` that does not resolve therefore also yields
        `ERR_TANK_NOT_FOUND`, a `host_shell_course_id` that does not resolve yields
        `ERR_SHELL_COURSE_NOT_FOUND`, and a `predecessor_seam_id` that does not resolve
        yields `ERR_WELD_SEAM_NOT_FOUND`."

        Design: Corner/errors/every_path_parameter_returns_its_own_not_found
        """
        probes = [
            (api.get_tank, ERR_TANK_NOT_FOUND),
            (api.get_foundation_package, ERR_FOUNDATION_PACKAGE_NOT_FOUND),
            (api.get_settlement_survey, ERR_SETTLEMENT_SURVEY_NOT_FOUND),
            (api.get_plate_lot, ERR_PLATE_LOT_NOT_FOUND),
            (api.get_shell_course, ERR_SHELL_COURSE_NOT_FOUND),
            (api.get_welder, ERR_WELDER_NOT_FOUND),
            (api.get_weld_seam, ERR_WELD_SEAM_NOT_FOUND),
            (api.get_nde_report, ERR_NDE_REPORT_NOT_FOUND),
            (api.get_water_source, ERR_WATER_SOURCE_NOT_FOUND),
            (api.get_hydrotest_plan, ERR_HYDROTEST_PLAN_NOT_FOUND),
            (api.get_water_withdrawal, ERR_WATER_WITHDRAWAL_NOT_FOUND),
            (api.get_coating_application, ERR_COATING_APPLICATION_NOT_FOUND),
            (api.get_appurtenance, ERR_APPURTENANCE_NOT_FOUND),
            (api.get_commissioning_package, ERR_COMMISSIONING_PACKAGE_NOT_FOUND),
        ]
        assert len(probes) == 14

        for getter, error_id in probes:
            response = getter(GHOST_UUID, AI1)
            validate_error(response, error_id, 404)
            body = response.json()
            assert body["response_type"] == "error", error_id
            assert body["data"]["message"], f"{error_id} carries no message"
            assert_error_envelope_meta(response)

        source = X.create_water_source(api)
        validate_error(
            api.create_water_withdrawal(
                withdrawal_payload(
                    GHOST_UUID,
                    source["id"],
                    "2026-08-10T01:00:00Z",
                    "2026-08-10T20:00:00Z",
                    400.0,
                    400000.0,
                    source["version"],
                ),
                ES1,
            ),
            ERR_HYDROTEST_PLAN_NOT_FOUND,
            404,
        )
        assert_list_total(api.list_water_withdrawals(ES1), 0)
        assert_source_ledger(X.read_water_source(api, source["id"]), 0.00, 0.00, 2000000.00)


class TestUniquenessScopesAndSingletons:
    def test_each_identifier_collides_only_inside_its_own_scope(self, api):
        """A label that clashes on one course is accepted on a course of another tank.

        PRD: "The payload names the owner's identifier for the tank in `tank_tag`, a string of 1
        to 32 characters that must be unique across every tank in the system — a repeat is
        rejected with `ERR_DUPLICATE_IDENTIFIER`."

        PRD: "Both `seam_label` and `sequence_index` must be unique within the host course, and
        a collision on either is rejected with `ERR_DUPLICATE_IDENTIFIER`."

        PRD: "The pair of `appurtenance_type` and `azimuth_deg` must be unique within the host
        shell course, a repeat being rejected with `ERR_DUPLICATE_IDENTIFIER`; two
        different types may share an azimuth, and the same type may recur at a different
        azimuth."

        PRD: "A `ProjectEngineer` opens exactly one package per `tank_id`; a second attempt is
        rejected with `ERR_SINGLETON_EXISTS`."

        Design: Corner/errors/duplicate_identifiers_and_second_singletons_are_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        first = X.create_tank(api)
        second = X.create_tank(
            api,
            tank_tag="TK-201",
            diameter_ft=60.0,
            shell_height_ft=32.0,
            design_liquid_level_ft=32.0,
            product_specific_gravity=1.00,
            joint_efficiency=0.85,
        )
        course_one = X.create_course(api, first["id"], 1)
        course_two = X.create_course(api, second["id"], 1, plate_thickness_in=0.3750)
        X.create_seam(api, course_one["id"], "V1", 1)
        X.create_welder(api)
        X.create_water_source(api)
        X.create_appurtenance(api, first["id"], course_one["id"])
        X.create_foundation_package(api, first["id"])
        X.create_commissioning_package(api, first["id"])

        validate_error(
            api.create_tank(tank_payload(diameter_ft=80.0), PE1), ERR_DUPLICATE_IDENTIFIER, 409
        )
        validate_error(
            api.create_welder(
                welder_payload("W-07", full_name="S. Bell", process=PROCESS_FCAW), AI1
            ),
            ERR_DUPLICATE_IDENTIFIER,
            409,
        )
        validate_error(
            api.create_water_source(
                water_source_payload(
                    "Riverside Intake",
                    source_type=SOURCE_MUNICIPAL,
                    permitted_volume_gal=500000.0,
                    max_concurrent_rate_gpm=250.0,
                ),
                PE1,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            409,
        )
        validate_error(
            api.create_shell_course(
                shell_course_payload(first["id"], 1, plate_thickness_in=0.5000), PE1
            ),
            ERR_DUPLICATE_IDENTIFIER,
            409,
        )
        validate_error(
            api.create_weld_seam(
                weld_seam_payload(
                    course_one["id"], "V1", 2, seam_type=SEAM_HORIZONTAL, length_in=314.0
                ),
                ES1,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            409,
        )

        twin = assert_object_envelope(
            api.create_weld_seam(weld_seam_payload(course_two["id"], "V1", 1), ES1), 201
        )
        assert twin["seam_label"] == "V1"
        assert twin["shell_course_id"] == course_two["id"]

        validate_error(
            api.create_appurtenance(
                appurtenance_payload(
                    first["id"], course_one["id"], nominal_size_in=12.0, elevation_ft=6.0
                ),
                PE1,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            409,
        )

        validate_error(
            api.create_foundation_package(
                foundation_package_payload(
                    first["id"], monitoring_point_count=12, permitted_uniform_settlement_in=4.0
                ),
                CC1,
            ),
            ERR_SINGLETON_EXISTS,
            409,
        )
        validate_error(
            api.create_commissioning_package(commissioning_package_payload(first["id"]), PE1),
            ERR_SINGLETON_EXISTS,
            409,
        )

        assert_list_total(api.list_tanks(PE1), 2)
        assert_list_total(api.list_welders(PE1), 1)
        assert_list_total(api.list_water_sources(PE1), 1)
        assert_list_total(api.list_shell_courses(PE1, {"tank_id": first["id"]}), 1)
        assert_list_total(api.list_foundation_packages(CC1, {"tank_id": first["id"]}), 1)
        assert_list_total(api.list_weld_seams(ES1, {"shell_course_id": course_one["id"]}), 1)


class TestFoundationAcceptancePrecondition:
    def test_acceptance_needs_the_zero_fill_survey_that_moves_the_package(self, api):
        """The identical decision is refused before the baseline and accepted after it.

        PRD: "The package must be in `BASELINE_SET` and a baseline survey must exist; a decision
        recorded on a package in any other status, or a monitoring survey submitted before
        a baseline exists, is rejected with `ERR_FOUNDATION_STATE_INVALID`."

        PRD: "On `ACCEPT`, the package moves `BASELINE_SET → ACCEPTED` (a terminal status),
        `decided_by_user_id` and `decided_at_utc` are stamped from the acting operator and
        the logical clock, `decision_remarks` is stored, and the tank advances
        `DESIGN_REGISTERED → FOUNDATION_ACCEPTED` with its `version` incremented and
        `updated_at` refreshed."

        Design: Corner/errors/foundation_acceptance_before_a_baseline_is_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        package = X.create_foundation_package(api, tank["id"])

        validate_error(
            api.foundation_acceptance(
                package["id"], foundation_acceptance_payload(DECISION_ACCEPT), PE1
            ),
            ERR_FOUNDATION_STATE_INVALID,
            409,
        )
        package = X.read_foundation_package(api, package["id"])
        assert package["status"] == PKG_PLANNED
        assert package["baseline_survey_id"] is None
        assert package["decided_at_utc"] is None
        assert package["decided_by_user_id"] is None

        survey = X.create_survey(api, package["id"], [100.0] * 8, 0.0)
        package = X.read_foundation_package(api, package["id"])
        assert package["status"] == PKG_BASELINE_SET
        assert package["baseline_survey_id"] == survey["id"]

        accepted = assert_object_envelope(
            api.foundation_acceptance(
                package["id"], foundation_acceptance_payload(DECISION_ACCEPT), PE1
            ),
            200,
        )
        assert accepted["status"] == PKG_ACCEPTED
        assert accepted["decided_by_user_id"] == PE1_ID
        assert_instant(accepted["decided_at_utc"], CLOCK_BASE, "decision stamp")
        assert X.read_tank(api, tank["id"])["construction_phase"] == PHASE_FOUNDATION_ACCEPTED


class TestPlateLotTransitionGuards:
    def test_a_skipped_step_and_a_missing_report_number_share_one_identifier(self, api):
        """Two failure modes of the same endpoint, and the ledger moves only on receipt.

        PRD: "From `ORDERED` the lot may go to `ROLLED`; from `ROLLED` to `SHIPPED`; from
        `SHIPPED` to `RECEIVED`; from `RECEIVED` to either `QUARANTINED` or `RELEASED`;
        and from `QUARANTINED` to `RELEASED`."

        PRD: "A `target_status` that is not reachable from the lot's current status is rejected
        with `ERR_PLATE_LOT_STATE_INVALID`, and so is a move to `RECEIVED` or `RELEASED`
        that does not carry the required material test report number."

        PRD: "On reaching `RECEIVED`, the lot's `received_weight_lb` is set once and for all to
        `plate_count` multiplied by `plate_weight_lb`, and its `remaining_weight_lb` is
        set to the same figure because nothing has yet been allocated."

        Design: Corner/errors/plate_lot_status_skips_and_missing_mtr_are_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        lot = X.create_plate_lot(api, tank["id"])
        assert lot["status"] == LOT_ORDERED

        validate_error(
            api.plate_lot_status_transition(
                lot["id"], lot_status_payload(LOT_RECEIVED, mtr_number="MTR-4471-A"), ES1
            ),
            ERR_PLATE_LOT_STATE_INVALID,
            409,
        )
        assert_weight(X.read_tank(api, tank["id"])["steel_received_lb"], 0.00, "steel received")

        assert X.lot_transition(api, lot["id"], LOT_ROLLED)["status"] == LOT_ROLLED
        assert X.lot_transition(api, lot["id"], LOT_SHIPPED)["status"] == LOT_SHIPPED
        assert_weight(X.read_tank(api, tank["id"])["steel_received_lb"], 0.00, "steel received")

        validate_error(
            api.plate_lot_status_transition(lot["id"], lot_status_payload(LOT_RECEIVED), ES1),
            ERR_PLATE_LOT_STATE_INVALID,
            409,
        )
        assert X.read_plate_lot(api, lot["id"])["status"] == LOT_SHIPPED

        received = assert_object_envelope(
            api.plate_lot_status_transition(
                lot["id"], lot_status_payload(LOT_RECEIVED, mtr_number="MTR-4471-A"), ES1
            ),
            200,
        )
        assert received["status"] == LOT_RECEIVED
        assert received["mtr_number"] == "MTR-4471-A"
        assert_weight(received["received_weight_lb"], 12505.00, "received weight")
        assert_weight(received["remaining_weight_lb"], 12505.00, "remaining weight")
        assert_weight(
            X.read_tank(api, tank["id"])["steel_received_lb"], 12505.00, "steel received"
        )


class TestFitupFoundationGate:
    def test_erection_waits_for_the_accepted_package_and_the_weld_waits_for_the_course(self, api):
        """Two adjacent gates, and the higher-priority seam gate masks the foundation one.

        PRD: "It requires the tank's foundation package to have reached `ACCEPTED`, or the
        request is rejected with `ERR_FOUNDATION_NOT_ACCEPTED`."

        PRD: "The seam must be `FIT_READY` or `REPAIR_IN_PROGRESS` and its host course must be
        `FITTED` or `WELDED`, or the attempt is rejected with `ERR_SEAM_NOT_WELDABLE`."

        PRD: "Next come the referential checks: same-tank agreement between every entity
        referenced in one request (`ERR_CROSS_TANK_REFERENCE`), then the
        accepted-foundation precondition for fit-up and weld logging
        (`ERR_FOUNDATION_NOT_ACCEPTED`), then the host-course acceptance precondition for
        appurtenance installation (`ERR_HOST_COURSE_NOT_ACCEPTED`), then the
        all-appurtenances-installed precondition for commissioning submission
        (`ERR_APPURTENANCES_NOT_INSTALLED`)."

        Design: Corner/errors/fitup_without_an_accepted_foundation_is_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        ctx = X.tank_with_baseline(api)
        course = X.create_course(api, ctx.tank_id, 1)
        welder = X.create_welder(api)
        seam = X.create_seam(api, course["id"], "V1", 1)
        assert X.read_foundation_package(api, ctx.package_id)["status"] == PKG_BASELINE_SET

        # PRD gives the fit-up phase requirement — "It requires the tank's
        # `construction_phase` to be either `FOUNDATION_ACCEPTED` or
        # `ERECTION_IN_PROGRESS`" — no error identifier of its own. An
        # unaccepted package always leaves the tank at `DESIGN_REGISTERED`, so
        # both that unnamed phase requirement (reasonably folded into the
        # fit-up state gate `ERR_COURSE_STATE_INVALID`, priority 13) and
        # `ERR_FOUNDATION_NOT_ACCEPTED` (a later referential check) are tripped
        # by the same call, and PRD does not say which one answers.
        refused = api.fitup(course["id"], ES1)
        assert refused.status_code == 409
        validate_error_is_one_of(
            refused, [ERR_FOUNDATION_NOT_ACCEPTED, ERR_COURSE_STATE_INVALID]
        )
        assert X.read_course(api, course["id"])["status"] == COURSE_SPECIFIED

        validate_error(
            api.weld_log(
                seam["id"], weld_log_payload(welder["id"]), welder_headers(welder["id"])
            ),
            ERR_SEAM_NOT_WELDABLE,
            409,
        )

        X.accept_foundation(api, ctx.package_id)

        fitted = assert_object_envelope(api.fitup(course["id"], ES1), 200)
        assert fitted["status"] == COURSE_FITTED

        seam = X.read_seam(api, seam["id"])
        assert seam["status"] == SEAM_FIT_READY
        assert seam["welded_at_utc"] is None
        assert seam["welder_id"] is None


class TestSeamPredecessorResolution:
    def test_a_three_deep_chain_is_accepted_and_a_dangling_link_is_a_404(self, api):
        """The walk terminates at a root, and an unresolvable predecessor never lands.

        PRD: "The predecessor must belong to the same tank, or the request is rejected with
        `ERR_CROSS_TANK_REFERENCE`, and following the chain of predecessors must terminate
        at a seam with no predecessor — a chain that would close on itself is rejected
        with `ERR_SEAM_SEQUENCE_CYCLE`."

        PRD: "Exactly the same mapping governs foreign keys arriving in a request **body**,
        which are resolved in the order the endpoint declares its input fields; a
        body-borne `tank_id` that does not resolve therefore also yields
        `ERR_TANK_NOT_FOUND`, a `host_shell_course_id` that does not resolve yields
        `ERR_SHELL_COURSE_NOT_FOUND`, and a `predecessor_seam_id` that does not resolve
        yields `ERR_WELD_SEAM_NOT_FOUND`."

        Design: Corner/errors/seam_predecessor_chains_are_walked_to_a_root
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        course = X.create_course(api, tank["id"], 1)

        head = assert_object_envelope(
            api.create_weld_seam(weld_seam_payload(course["id"], "A", 1), ES1), 201
        )
        middle = assert_object_envelope(
            api.create_weld_seam(
                weld_seam_payload(course["id"], "B", 2, predecessor_seam_id=head["id"]), ES1
            ),
            201,
        )
        tail = assert_object_envelope(
            api.create_weld_seam(
                weld_seam_payload(course["id"], "C", 3, predecessor_seam_id=middle["id"]), ES1
            ),
            201,
        )

        assert head["predecessor_seam_id"] is None
        assert middle["predecessor_seam_id"] == head["id"]
        assert tail["predecessor_seam_id"] == middle["id"]

        validate_error(
            api.create_weld_seam(
                weld_seam_payload(course["id"], "D", 4, predecessor_seam_id=GHOST_UUID), ES1
            ),
            ERR_WELD_SEAM_NOT_FOUND,
            404,
        )

        rows, _ = assert_list_total(
            api.list_weld_seams(ES1, {"shell_course_id": course["id"]}), 3
        )
        assert sorted(row["seam_label"] for row in rows) == ["A", "B", "C"]


class TestWithdrawalCancellationIsNotIdempotent:
    def test_the_second_cancellation_is_refused_and_credits_nothing(self, api):
        """A tolerated repeat would hand the permit its volume back twice.

        PRD: "The withdrawal must be `RESERVED`, or the request is rejected with
        `ERR_WITHDRAWAL_STATE_INVALID`."

        PRD: "On success it moves `RESERVED → CANCELLED`, the reason is stored, the source's
        `reserved_volume_gal` falls and its `available_volume_gal` rises by the released
        `reserved_volume_gal`, the cancelled window stops participating in both the
        rate-overlap check and the permitted-volume check, and the owning plan's cost
        fields are recomputed with the withdrawal excluded."

        Design: Corner/errors/cancelling_an_already_cancelled_withdrawal_is_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        plan = X.create_plan(api, tank["id"], source["id"])
        withdrawal = X.reserve_withdrawal(
            api,
            plan["id"],
            source["id"],
            "2026-08-11T00:00:00Z",
            "2026-08-11T20:00:00Z",
            400.0,
            400000.0,
        )

        cancelled = assert_object_envelope(
            api.withdrawal_cancellation(
                withdrawal["id"],
                withdrawal_cancellation_payload("intake permit re-negotiated"),
                ES1,
            ),
            200,
        )
        assert cancelled["status"] == WITHDRAWAL_CANCELLED
        assert cancelled["cancellation_reason"] == "intake permit re-negotiated"

        assert_source_ledger(
            X.read_water_source(api, source["id"]), 0.00, 0.00, 2000000.00
        )
        assert_money(X.read_plan(api, plan["id"])["total_cost_usd"], 0.00, "plan total cost")

        validate_error(
            api.withdrawal_cancellation(
                withdrawal["id"],
                withdrawal_cancellation_payload("duplicate submission by the field crew"),
                ES1,
            ),
            ERR_WITHDRAWAL_STATE_INVALID,
            409,
        )

        assert_source_ledger(
            X.read_water_source(api, source["id"]), 0.00, 0.00, 2000000.00
        )
        held = X.read_withdrawal(api, withdrawal["id"])
        assert held["status"] == WITHDRAWAL_CANCELLED
        assert held["cancellation_reason"] == "intake permit re-negotiated"
