"""The two claims the error catalogue makes that no other section makes.

One envelope serves every status family, and its `data` leaks nothing about the
resource it refused; and the HTTP status is a property of the `error_id` rather
than of the endpoint, the field, or the resource involved.
"""

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.factories import (
    conservation_bank_payload,
    field_survey_payload,
    mitigation_commitment_payload,
    project_action_payload,
)
from test_helpers.fixtures import (
    AUDITOR,
    REGISTRAR,
    build_scenario,
    establish_conservation_bank,
    read_action,
    setup_second_action,
)
from test_helpers.test_users import anonymous_headers, headers_without_role


class TestErrorBodyShape:
    """Six status families, one body shape, and nothing of the refused row in it."""

    def test_every_failure_carries_exactly_an_error_id_and_a_message(self, api):
        """401, 403, 404, 400, 409 and 400 all answer with the same two keys.

        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        PRD: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        PRD: "The `message` provides a human-readable explanation of what went wrong."

        PRD: "This operation takes **no body fields at all** - every input it needs is
        already persisted - and it is available only while the action's `status` is
        `SCREENING`, so a second determination on the same action is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        None of the six bodies carries a version, a state, or the id of the resource
        it refused, and the 409 on the repeated effect determination leaves the action
        in `FORMAL_CONSULTATION` with the same `active_consultation_id`.

        Design: Corner/errors/every_error_body_carries_only_an_error_id_and_a_message
        """
        scenario = build_scenario("effect_determination")
        action_id = scenario["action"]["id"]
        headers = scenario["proponent_headers"]

        assert scenario["action"]["status"] == "FORMAL_CONSULTATION"

        unauthenticated = assert_error_envelope(
            api_client.get_project_action(action_id, headers_without_role()),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        forbidden = assert_error_envelope(
            api_client.get_project_action(action_id, anonymous_headers()),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        missing = assert_error_envelope(
            api_client.get_project_action(NON_EXISTENT_ID, AUDITOR),
            ApiErrorId.ERR_PROJECT_ACTION_NOT_FOUND,
            404,
        )
        malformed = assert_error_envelope(
            api_client.create_project_action(
                project_action_payload(
                    scenario["proponent"]["id"],
                    action_name="Bad Body",
                    footprint_acres=200.005,
                ),
                headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )
        state_conflict = assert_error_envelope(
            api_client.run_effect_determination(action_id, headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        negative_credits = assert_error_envelope(
            api_client.create_conservation_bank(
                conservation_bank_payload(
                    scenario["species"]["id"],
                    bank_name="Unlisted Bank",
                    credits_total_minted=-1.00,
                ),
                REGISTRAR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        bodies = (
            unauthenticated,
            forbidden,
            missing,
            malformed,
            state_conflict,
            negative_credits,
        )
        for body in bodies:
            assert set(body.keys()) == {"error_id", "message"}
            assert body["message"].strip()
            assert body["message"] != body["error_id"]
            assert action_id not in body["message"]

        assert len({body["error_id"] for body in bodies}) == 5

        untouched = read_action(action_id)

        assert untouched["status"] == "FORMAL_CONSULTATION"
        assert untouched["active_consultation_id"] == scenario["consultation"]["id"]
        assert untouched["version"] == scenario["action"]["version"]


class TestErrorIdStatusPinning:
    """The same endpoint and the same field set split across two statuses."""

    def test_the_status_follows_the_error_id_and_not_the_endpoint(self, api):
        """Two commitment refusals split 409/422 and two window refusals split 422/409.

        PRD: "Every error response uses the envelope of §2.2, with the identifier below
        in `error_id`."

        PRD: "Eligibility is checked before availability, so a commitment that is both
        out of service area and over budget reports the eligibility failure."

        PRD: "Two field-survey windows citing the **same** critical habitat unit
        conflict when they come within a three-day buffer of one another, and the
        comparison deliberately reaches across **all** project actions - the buffer
        protects the habitat, not the project."

        PRD: "A conflict is `ERR_SURVEY_WINDOW_CONFLICT` (HTTP 409)."

        The over-budget commitment is 409 while the ineligible-species commitment is
        422 on the same endpoint with the same field set; the missing window is 422
        while a window two days clear of the existing one is 409 on the same endpoint
        with the same field set, in the opposite direction.

        Design: Corner/errors/each_error_id_is_pinned_to_exactly_one_http_status
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]
        version = scenario["plan"]["version"]
        threatened_bank = establish_conservation_bank(
            scenario["threatened_species"]["id"],
            bank_name="Vireo Riparian Bank",
            credits_total_minted=100.00,
        )
        second_action = setup_second_action(scenario)

        assert scenario["bank"]["credits_available"] == 500.00
        assert scenario["field_determination"]["survey_window_start"] == "2026-05-04"
        assert scenario["field_determination"]["survey_window_end"] == "2026-05-08"
        assert second_action["status"] == "SCREENING"

        assert_error_envelope(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    version, units=500.01, conservation_bank_id=scenario["bank"]["id"]
                ),
                headers,
            ),
            ApiErrorId.ERR_INSUFFICIENT_BANK_CREDITS,
            409,
        )
        assert_error_envelope(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    version, units=10.00, conservation_bank_id=threatened_bank["id"]
                ),
                headers,
            ),
            ApiErrorId.ERR_BANK_NOT_ELIGIBLE,
            422,
        )

        windowless = field_survey_payload(
            scenario["species"]["id"],
            habitat_overlap_acres=4.00,
            critical_habitat_unit_id=scenario["unit"]["id"],
        )
        del windowless["survey_window_start"]
        del windowless["survey_window_end"]
        assert_error_envelope(
            api_client.create_presence_determination(
                second_action["id"], windowless, headers
            ),
            ApiErrorId.ERR_SURVEY_WINDOW_INVALID,
            422,
        )
        assert_error_envelope(
            api_client.create_presence_determination(
                second_action["id"],
                field_survey_payload(
                    scenario["species"]["id"],
                    habitat_overlap_acres=4.00,
                    critical_habitat_unit_id=scenario["unit"]["id"],
                    survey_window_start="2026-05-10",
                    survey_window_end="2026-05-12",
                ),
                headers,
            ),
            ApiErrorId.ERR_SURVEY_WINDOW_CONFLICT,
            409,
        )
