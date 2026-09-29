"""The appeal cycle and the final-denial cascade.

Sources: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rules `non_linear_state_machine`
and `transitive_cascade`.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals, assert_money_ledger
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.factories import adalimumab_payload
from test_helpers.fixtures import (
    ADMIN,
    COORDINATOR,
    REVIEWER,
    active_enrollment,
    deny_authorization,
    open_authorization,
    planned_episode,
    set_clock,
    submit_authorization,
)


def _appealable_practice():
    """Adalimumab — a `TNFI` product, so the plan's own `TNFI` step requirement is
    removed as self-referential — on Meridian PPO, which allows two appeal rounds;
    a screened patient with one `PLANNED` episode and one `DRAFT` authorization
    for six units."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = planned_episode(drug_payload=adalimumab_payload())
    open_authorization(scenario, requested_units=6)
    return scenario


def _submit(scenario):
    return api_client.submit_authorization(scenario.authorization_id, COORDINATOR)


# ---------------------------------------------------------------------------
# non_linear_state_machine /
# authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
# ---------------------------------------------------------------------------
def test_a_non_final_denial_leaves_the_episode_pending_auth():
    """While the appeal allowance is unspent the denial changes nothing else.

    PRD §3.5: "When `appeal_round` is still strictly less than the plan's
    `appeal_rounds_allowed`, the denial is not final: the episode's
    `funding_state` stays at `PENDING_AUTH`, nothing else is touched, and the
    coordinator may appeal."

    Design: Difficulty/non_linear_state_machine/authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
    """
    scenario = _appealable_practice()

    submitted = submit_authorization(scenario)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["appeal_round"] == 0

    denied = deny_authorization(scenario)
    assert denied["status"] == "DENIED"
    assert denied["appeal_round"] == 0
    assert scenario.refresh_episode()["funding_state"] == "PENDING_AUTH"


def test_each_resubmission_out_of_denied_increments_the_appeal_round():
    """`SUBMITTED → DENIED → SUBMITTED` may run as often as the plan permits.

    PRD §3.5: "When the prior status was `DENIED`, it also increments
    `appeal_round` by one and clears `decision_reason`, so an authorization may
    traverse `SUBMITTED → DENIED → SUBMITTED` as many times as the plan's appeal
    allowance permits."

    Design: Difficulty/non_linear_state_machine/authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
    """
    scenario = _appealable_practice()

    submit_authorization(scenario)
    deny_authorization(scenario)

    first_appeal = submit_authorization(scenario)
    assert first_appeal["status"] == "SUBMITTED"
    assert first_appeal["appeal_round"] == 1
    assert first_appeal["decision_reason"] is None

    denied_again = deny_authorization(scenario)
    assert denied_again["status"] == "DENIED"
    assert denied_again["appeal_round"] == 1
    assert scenario.refresh_episode()["funding_state"] == "PENDING_AUTH"

    second_appeal = submit_authorization(scenario)
    assert second_appeal["status"] == "SUBMITTED"
    assert second_appeal["appeal_round"] == 2


def test_the_denial_at_the_last_permitted_round_unfunds_the_episode():
    """The denial becomes final once `appeal_round` reaches the allowance.

    PRD §3.5: "When `appeal_round` has reached `appeal_rounds_allowed`, the denial
    is final and a three-level cascade runs: the episode's `funding_state` moves
    `PENDING_AUTH → UNFUNDED` and its `version` increments by one, and every
    assistance enrollment of that episode whose `status` is not already
    `TERMINATED` is terminated with `termination_reason` `FUNDING_DENIED`, which
    releases each enrollment's `benefit_reserved_cents` back into its
    `benefit_remaining_cents` and increments that enrollment's `version` by one."

    Design: Difficulty/non_linear_state_machine/authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
    """
    scenario = _appealable_practice()

    submit_authorization(scenario)
    deny_authorization(scenario)
    submit_authorization(scenario)
    deny_authorization(scenario)
    submit_authorization(scenario)

    final = deny_authorization(scenario)

    assert final["status"] == "DENIED"
    assert final["appeal_round"] == 2
    assert scenario.refresh_episode()["funding_state"] == "UNFUNDED"


def test_a_further_submission_once_the_rounds_are_spent_is_refused():
    """A denied authorization at the allowance cannot be appealed again.

    PRD §3.5: "For a re-submission out of `DENIED`, the authorization's
    `appeal_round` must be strictly less than the plan's `appeal_rounds_allowed`,
    else `ERR_APPEAL_ROUNDS_EXHAUSTED` (HTTP 409) — a plan allowing zero rounds
    therefore permits no appeal whatsoever."

    Design: Difficulty/non_linear_state_machine/authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
    """
    scenario = _appealable_practice()

    for _round in range(3):
        submit_authorization(scenario)
        deny_authorization(scenario)

    response = _submit(scenario)

    validate_error(response, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED.value, 409)
    assert scenario.refresh_authorization()["status"] == "DENIED"
    assert scenario.refresh_authorization()["appeal_round"] == 2


def test_a_determination_against_a_denied_authorization_is_refused():
    """Determination is reachable only from `SUBMITTED`.

    PRD §3.5: "Only a `PayerReviewer` renders a determination, and only against an
    authorization in `SUBMITTED`; anything else is refused with
    `ERR_AUTHORIZATION_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/authorization_denied_resubmit_appeal_cycle_until_rounds_exhausted
    """
    scenario = _appealable_practice()

    for _round in range(3):
        submit_authorization(scenario)
        deny_authorization(scenario)

    response = api_client.determine_authorization(
        scenario.authorization_id,
        {"decision": "APPROVED", "approved_units": 6},
        REVIEWER,
    )

    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_STATE_INVALID.value, 409)
    assert scenario.refresh_authorization()["status"] == "DENIED"
    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "UNFUNDED"
    assert episode["therapy_state"] == "PLANNED"


# ---------------------------------------------------------------------------
# transitive_cascade /
# final_denial_cascade_unfunds_episode_and_terminates_enrollment
# ---------------------------------------------------------------------------
def _final_appeal_practice():
    """The same Adalimumab world with one `ACTIVE` enrollment of 500000 cents and
    an authorization already `SUBMITTED` at `appeal_round` 2 — its last permitted
    round."""
    scenario = _appealable_practice()
    active_enrollment(scenario)
    submit_authorization(scenario)
    deny_authorization(scenario)
    submit_authorization(scenario)
    deny_authorization(scenario)
    submit_authorization(scenario)
    return scenario


def test_the_final_denial_records_its_reason_and_determination_instant():
    """Every denial records `decision_reason` and `determination_at`.

    PRD §3.5: "A denial advances `SUBMITTED → DENIED` and always records
    `decision_reason` and `determination_at` and increments the authorization's
    `version` by one."

    Design: Difficulty/transitive_cascade/final_denial_cascade_unfunds_episode_and_terminates_enrollment
    """
    scenario = _final_appeal_practice()
    assert scenario.refresh_authorization()["status"] == "SUBMITTED"
    assert scenario.refresh_authorization()["appeal_round"] == 2

    denied = deny_authorization(
        scenario, decision_reason="MEDICAL_NECESSITY_NOT_ESTABLISHED"
    )

    assert denied["status"] == "DENIED"
    assert denied["appeal_round"] == 2
    assert denied["decision_reason"] == "MEDICAL_NECESSITY_NOT_ESTABLISHED"
    assert_instant_equals(
        denied["determination_at"], instant(2026, 8, 1, 0, 0, 0), "determination_at"
    )


def test_the_final_denial_unfunds_the_episode_and_leaves_it_planned():
    """The funding axis moves while the clinical axis stays where it was.

    PRD §2.9: "Neither axis constrains the other's representation: an episode may
    legitimately be `ACTIVE` while its funding is `LAPSED`, and it may be `HELD`
    while its funding is `AUTHORIZED`."

    Design: Difficulty/transitive_cascade/final_denial_cascade_unfunds_episode_and_terminates_enrollment
    """
    scenario = _final_appeal_practice()

    deny_authorization(scenario)

    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "UNFUNDED"
    assert episode["therapy_state"] == "PLANNED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_the_final_denial_terminates_the_episodes_enrollment_for_funding_denied():
    """Termination is a consequence of the episode losing its funding.

    PRD §3.8: "`termination_reason` records why: `FUNDING_DENIED` when a final
    authorization denial unfunds the episode, and `EPISODE_DISCONTINUED` when the
    episode itself is stopped."

    Design: Difficulty/transitive_cascade/final_denial_cascade_unfunds_episode_and_terminates_enrollment
    """
    scenario = _final_appeal_practice()
    before = scenario.refresh_enrollment()
    assert before["status"] == "ACTIVE"
    assert_money_ledger(before, used=0, reserved=0, remaining=500_000)

    deny_authorization(scenario)

    after = scenario.refresh_enrollment()
    assert after["status"] == "TERMINATED"
    assert after["termination_reason"] == "FUNDING_DENIED"
    assert_money_ledger(after, used=0, reserved=0, remaining=500_000)
