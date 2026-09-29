"""
Single requests that violate two enforcement rungs at once. Only the higher rung may
answer, and because the request never runs, nothing it would have written exists.
"""

from test_helpers import (
    HTTP_CONFLICT,
    HTTP_UNPROCESSABLE,
    ObservationApiClient,
    instant,
    validate_error,
)
from test_helpers.assertions import assert_fields, assert_row_count
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COST_POSTED,
    DECISION_APPROVE,
    ENTRY_KIND_PROVISIONAL,
    ERR_DEESCALATION_CERT_EXPIRED,
    ERR_INVALID_ORDER_STATE,
    MODALITY_ONE_TO_ONE_SITTER,
    ORDER_DISCONTINUED,
    POOL_INTERNAL_FLOAT,
    RECOMMENDATION_DISCONTINUE,
    RISK_FALL,
    STAFF_AVAILABLE,
    UNIT_OPEN,
)
from test_helpers.factories import (
    assignment_payload,
    discontinuation_decision_payload,
    discontinuation_review_payload,
)
from test_helpers.fixtures import (
    make_assignment,
    make_order,
    make_patient,
    make_reassessment,
    make_staff,
    make_unit,
    order_assignments,
    read_order,
    read_staff,
    read_unit,
    unit_cost_entries,
    unit_head,
)
from test_helpers.test_users import COORDINATOR, PROVIDER_1, PROVIDER_2


def _unit_i_tiny_budget_and_a_dead_order(api: ObservationApiClient) -> dict:
    """
    UNIT-I: a 10000-cent budget already 9600 spent, plus a second order that has been
    walked all the way to DISCONTINUED by a second provider.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-I",
        name="Observation Unit I",
        budget_cents=10000,
        video_monitoring_enabled=False,
    )
    patient_a = make_patient(api, unit["id"], mrn="MRN-9001", full_name="Pat Ten", age_years=60)
    patient_b = make_patient(api, unit["id"], mrn="MRN-9002", full_name="Pat Eleven", age_years=60)
    cheap_sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Eye One",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=1200,
        competency_level=COMPETENCY_ADVANCED,
    )
    dear_sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Eye Two",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2400,
        competency_level=COMPETENCY_ADVANCED,
    )
    live_order = make_order(
        api,
        patient_a["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Fall precautions, patient A",
    )
    live_watch = make_assignment(
        api,
        live_order["id"],
        cheap_sitter["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=live_order["version"],
    )
    dead_order = make_order(
        api,
        patient_b["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Fall precautions, patient B",
    )
    make_reassessment(api, dead_order["id"], [RISK_FALL])
    api.open_discontinuation_review(
        dead_order["id"],
        discontinuation_review_payload(RECOMMENDATION_DISCONTINUE),
        PROVIDER_1,
    )
    api.decide_discontinuation(
        dead_order["id"],
        discontinuation_decision_payload(
            DECISION_APPROVE, "Delirium resolved, no risk behaviours for a full shift"
        ),
        PROVIDER_2,
    )
    fresh = read_order(api, dead_order["id"])
    return {
        "unit": unit,
        "dear_sitter": dear_sitter,
        "live_watch": live_watch,
        "dead_order": fresh,
    }


class TestTerminalOrderStateBeatsTheUnitBudget:
    """Rung 8 answers a request that also breaks rung 28."""

    def test_scheduling_onto_a_discontinued_order_is_refused_as_a_state_failure(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.6: "And because the fiscal rules sit last, at rungs 28 and 29, a request
        that would both breach the budget and name an untrained observer reports the
        competency failure, not the budget failure."

        The provisional 19200 would drive the head from 9600 to 28800 against a
        10000-cent budget, so rung 28 is violated too; because the enforcement order
        is "first failure wins", the answer must be the 409 state code and not the
        402 fiscal code.

        Design: Difficulty/priority_pair_validation_conflict/discontinued_order_state_beats_unit_budget_exceeded
        """
        world = _unit_i_tiny_budget_and_a_dead_order(api)
        assert world["dead_order"]["status"] == ORDER_DISCONTINUED

        response = api.create_assignment(
            assignment_payload(
                world["dead_order"]["id"],
                world["dear_sitter"]["id"],
                instant(CLOCK_START, hours=8),
                instant(CLOCK_START, hours=16),
                world["dead_order"]["version"],
            ),
            COORDINATOR,
        )
        validate_error(response, ERR_INVALID_ORDER_STATE, HTTP_CONFLICT)

        after = read_order(api, world["dead_order"]["id"])
        assert_fields(
            after,
            label="order after the refusal",
            status=ORDER_DISCONTINUED,
            version=world["dead_order"]["version"],
        )
        assert_row_count(
            order_assignments(api, world["dead_order"]["id"]),
            0,
            "assignments on the discontinued order",
        )

    def test_the_refused_schedule_posts_no_provisional_entry(self, api: ObservationApiClient):
        """
        PRD 2.8: "If `expected_order_version` does not equal the order's current
        `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412,
        and no assignment row, no cost row and no unit mutation results."

        The same inertness is what makes the priority assertion legible here: the
        ledger still holds exactly the one provisional row belonging to the live
        watch, and the unit is still OPEN on a head of 9600.

        Design: Difficulty/priority_pair_validation_conflict/discontinued_order_state_beats_unit_budget_exceeded
        """
        world = _unit_i_tiny_budget_and_a_dead_order(api)
        api.create_assignment(
            assignment_payload(
                world["dead_order"]["id"],
                world["dear_sitter"]["id"],
                instant(CLOCK_START, hours=8),
                instant(CLOCK_START, hours=16),
                world["dead_order"]["version"],
            ),
            COORDINATOR,
        )

        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit after the refusal",
            observed_cost_to_date_cents=9600,
            status=UNIT_OPEN,
        )
        rows = unit_cost_entries(api, world["unit"]["id"])
        assert_row_count(rows, 1, "ledger rows on the unit")
        assert_fields(
            rows[0],
            label="surviving ledger row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            status=COST_POSTED,
            amount_cents=9600,
            assignment_id=world["live_watch"]["id"],
        )


def _unit_j_and_k_lapsed_floater(api: ObservationApiClient) -> dict:
    """
    The candidate sitter is homed on UNIT-K, the patient lives on UNIT-J, and the
    sitter's de-escalation certification lapsed before the logical clock started.
    """
    patient_unit = make_unit(
        api,
        unit_code="UNIT-J",
        name="Geriatric Unit J",
        budget_cents=500000,
        video_monitoring_enabled=False,
    )
    home_unit = make_unit(
        api,
        unit_code="UNIT-K",
        name="Float Pool Unit K",
        budget_cents=500000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(
        api, patient_unit["id"], mrn="MRN-9101", full_name="Pat Twelve", age_years=60
    )
    floater = make_staff(
        api,
        home_unit["id"],
        full_name="Lapsed Floater",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
        deescalation_cert_expires_on="2026-07-15T00:00:00Z",
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Repeated unassisted transfer attempts",
    )
    return {
        "patient_unit": patient_unit,
        "home_unit": home_unit,
        "floater": floater,
        "order": order,
    }


def _schedule_the_lapsed_floater(api: ObservationApiClient, world: dict):
    """The one request that breaks the certification gate and the float gate at once."""
    return api.create_assignment(
        assignment_payload(
            world["order"]["id"],
            world["floater"]["id"],
            instant(CLOCK_START, hours=8),
            instant(CLOCK_START, hours=16),
            world["order"]["version"],
        ),
        COORDINATOR,
    )


class TestExpiredCertificationBeatsMissingFloatAuthorization:
    """Rung 10 answers a request that also breaks rung 26, and both are 422."""

    def test_the_certification_gate_names_itself_and_not_the_float_gate(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.6: "Validations are not independent. They form a single ordered ladder,
        and the server evaluates them in ascending order and returns the **first**
        failure it reaches, so a request that violates several rules always surfaces the
        earliest one."

        The same request also omits the `float_authorization_code` that rung 26
        demands of a cross-unit sitter, and both rungs answer with HTTP 422, so only
        the error identifier settles which rung fired.

        Design: Difficulty/priority_pair_validation_conflict/expired_deescalation_cert_beats_missing_float_authorization
        """
        world = _unit_j_and_k_lapsed_floater(api)
        assert world["floater"]["home_unit_id"] == world["home_unit"]["id"]

        validate_error(
            _schedule_the_lapsed_floater(api, world),
            ERR_DEESCALATION_CERT_EXPIRED,
            HTTP_UNPROCESSABLE,
        )

    def test_the_refused_schedule_bumps_no_version_and_spends_nothing(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.4: "The nominated observer's `deescalation_cert_expires_on` must be
        strictly later than the current logical clock, or the request fails with
        `ERR_DEESCALATION_CERT_EXPIRED`."

        A create rejected at that rung writes nothing at all: no assignment row on
        the order, no version bump on the order or the observer, and no ledger
        movement on either the patient's unit or the observer's home unit.

        Design: Difficulty/priority_pair_validation_conflict/expired_deescalation_cert_beats_missing_float_authorization
        """
        world = _unit_j_and_k_lapsed_floater(api)
        _schedule_the_lapsed_floater(api, world)

        assert_row_count(
            order_assignments(api, world["order"]["id"]), 0, "assignments on the order"
        )
        assert read_order(api, world["order"]["id"])["version"] == world["order"]["version"]
        assert unit_head(api, world["patient_unit"]["id"]) == 0
        assert unit_head(api, world["home_unit"]["id"]) == 0
        assert_fields(
            read_staff(api, world["floater"]["id"]),
            label="the refused observer",
            status=STAFF_AVAILABLE,
            version=world["floater"]["version"],
        )
