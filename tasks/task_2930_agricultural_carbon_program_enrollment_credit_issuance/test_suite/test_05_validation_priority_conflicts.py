"""Requests that violate two rungs of the validation ladder at once.

The ladder of §2.10 is evaluated in ascending order and the first violated rung
decides the answer, so a request that is both unauthorized and aimed at a missing
resource must report the authorization failure, and an approval that is both
mis-stated and duty-conflicted must report the state failure.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_GROWER_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    BASELINE_APPROVED,
    BASELINE_MODELED,
    BASELINE_PROPOSED,
    BASELINE_SUPERSEDED,
    ENROLLMENT_ACCEPTED,
    ENROLLMENT_ACTIVE,
    FIELD_ENROLLED,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import suspend_grower_payload
from test_helpers.test_users import (
    ADMIN_BASELINE_HEADERS,
    ADMIN_BASELINE_ID,
    ADMIN_HEADERS,
    ADMIN_SCREENER_HEADERS,
    grower_headers,
)

MISSING_GROWER = UNKNOWN_UUIDS["grower"]


def test_unauthorized_role_answers_before_the_path_is_resolved(scenario):
    """A grower principal aiming the suspension endpoint at a grower id that does not exist
    is told it may not call the endpoint, and the missing row is never mentioned.

    PRD §2.10: "**Authorization.** The acting role appears in the called endpoint's
    authorized-role list → otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_path_existence_returns_403
    """
    scenario.set_clock()

    response = scenario.api.suspend_grower(
        MISSING_GROWER,
        suspend_grower_payload(suspension_reason="attempted by a grower principal"),
        grower_headers(MISSING_GROWER),
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert ERR_GROWER_NOT_FOUND not in response.text


def test_path_existence_answers_once_the_role_is_authorized(scenario):
    """The identical request from a programme administrator reaches the next rung down and
    reports the missing grower, so the earlier answer was the ladder and not a blanket 403.

    PRD §2.10: "**Path existence.** Every path-parameter resource resolves, strictly left
    to right → otherwise the corresponding not-found code (404). Applies to every endpoint
    carrying path parameters."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_path_existence_returns_403
    """
    scenario.set_clock()

    response = scenario.api.suspend_grower(
        MISSING_GROWER,
        suspend_grower_payload(suspension_reason="attempted by an admin"),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_GROWER_NOT_FOUND, 404)


def test_state_rung_answers_before_the_duties_rung_on_a_superseded_baseline(scenario):
    """Approving a superseded baseline reports the state failure even though the acting
    administrator is also the one who screened the enrollment.

    PRD §2.10: "**State.** The addressed resource is in a state from which the requested
    transition is declared, and the transition's preconditions on *other* entities also
    hold — quantification requires the enrollment to be `ACTIVE`, issuance requires a
    `POSITIVE` verification opinion, registry listing requires `issuance_status` of
    `ISSUED` → otherwise `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action
    endpoint."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_of_duties_on_superseded_baseline
    """
    scenario.accepted_enrollment()
    first = scenario.propose_baseline()
    second = scenario.propose_baseline(BASELINE_MODELED)
    assert get_success_data(scenario.api.get_baseline(first["id"], ADMIN_HEADERS))[
        "status"] == BASELINE_SUPERSEDED

    response = scenario.api.approve_baseline(first["id"], None, ADMIN_SCREENER_HEADERS)

    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
    assert ERR_SEGREGATION_OF_DUTIES not in response.text
    assert get_success_data(scenario.api.get_baseline(first["id"], ADMIN_HEADERS))[
        "status"] == BASELINE_SUPERSEDED
    assert get_success_data(scenario.api.get_baseline(second["id"], ADMIN_HEADERS))[
        "status"] == BASELINE_PROPOSED
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_ACCEPTED


def test_duties_rung_answers_once_the_state_rung_is_satisfied(scenario):
    """The proposed baseline is refused to the screening administrator and granted to a
    second one, and only the granted call moves the enrollment.

    PRD §2.10: "**Segregation of duties** → `ERR_SEGREGATION_OF_DUTIES` (409), on baseline
    approval and reversal assessment, as described in §2.9."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_of_duties_on_superseded_baseline
    """
    scenario.accepted_enrollment()
    scenario.propose_baseline()
    second = scenario.propose_baseline(BASELINE_MODELED)
    version_before = scenario.enrollment_version

    refused = scenario.api.approve_baseline(second["id"], None, ADMIN_SCREENER_HEADERS)

    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 409)
    assert get_success_data(scenario.api.get_baseline(second["id"], ADMIN_HEADERS))[
        "status"] == BASELINE_PROPOSED
    assert scenario.enrollment_version == version_before

    approved = get_success_data(
        scenario.api.approve_baseline(second["id"], None, ADMIN_BASELINE_HEADERS)
    )

    assert approved["status"] == BASELINE_APPROVED
    enrollment = scenario.reload_enrollment()
    assert enrollment["status"] == ENROLLMENT_ACTIVE
    assert enrollment["baseline_approval_admin_id"] == ADMIN_BASELINE_ID
    assert enrollment["version"] == version_before + 1
    assert scenario.reload_field()["status"] == FIELD_ENROLLED
