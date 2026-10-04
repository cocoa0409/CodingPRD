"""Cyclic state machines: goodwill negotiation rounds and training remediation."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data, api_client,
    setup_retiring_advisor_with_transfer, create_advisor,
    make_advisor_headers, post_production,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_counter_offer_cycle_increments_round_and_version():
    """PRD §3.7: "A counter-offer — allowed while the transfer is `OFFERED` or
    `NEGOTIATING`, moving it into (or keeping it in) `NEGOTIATING` — must come
    from either the retiring or the successor advisor, must propose a positive
    `offer_price_cents`, and must carry the OCC guard
    `expected_transfer_version` described in §2.4."
    PRD §3.7: "Each accepted counter-offer increments `negotiation_round` by
    one and bumps the transfer's `version`."

    Design: Difficulty/non_linear_state_machine/goodwill_negotiation_cycle_with_alternation
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()
    assert transfer["status"] == "OFFERED"
    assert transfer["negotiation_round"] == 0

    first = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": transfer["version"], "offer_price_cents": 1700000},
        make_advisor_headers(successor["id"]),
    ))
    assert first["status"] == "NEGOTIATING"
    assert first["negotiation_round"] == 1
    assert first["version"] == transfer["version"] + 1

    second = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": first["version"], "offer_price_cents": 1750000},
        make_advisor_headers(retiring["id"]),
    ))
    assert second["status"] == "NEGOTIATING"
    assert second["negotiation_round"] == 2
    assert second["offer_price_cents"] == 1750000
    assert second["version"] == transfer["version"] + 2


def test_negotiation_cycle_stays_in_negotiating_until_decision():
    """PRD §3.7: "A counter-offer — allowed while the transfer is `OFFERED` or
    `NEGOTIATING`, moving it into (or keeping it in) `NEGOTIATING` — must come
    from either the retiring or the successor advisor, must propose a positive
    `offer_price_cents`, and must carry the OCC guard
    `expected_transfer_version` described in §2.4."
    PRD §3.7: "Each accepted counter-offer increments `negotiation_round` by
    one and bumps the transfer's `version`."

    Design: Difficulty/non_linear_state_machine/goodwill_negotiation_cycle_with_alternation
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()

    parties = [successor["id"], retiring["id"], successor["id"]]
    current = transfer
    for round_no, party_id in enumerate(parties, start=1):
        current = validate_success(api_client.counter_offer(
            transfer["id"],
            {
                "expected_transfer_version": current["version"],
                "offer_price_cents": 1800000 - round_no * 10000,
            },
            make_advisor_headers(party_id),
        ))
        assert current["status"] == "NEGOTIATING"
        assert current["negotiation_round"] == round_no

    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["status"] == "NEGOTIATING"
    assert fresh["negotiation_round"] == 3
    assert fresh["version"] == transfer["version"] + 3


def test_remediation_loop_then_pass_validates_advisor():
    """PRD §3.1: "A failing evaluation drops the program into `REMEDIATION`
    while the advisor remains a `TRAINEE`, and the remediation loop permits
    the advisor to submit again from `REMEDIATION` back to
    `MILESTONE_PENDING`."
    PRD §3.1: "A passing evaluation completes the program
    (`MILESTONE_PENDING → COMPLETED`) and validates the advisor
    (`TRAINEE → VALIDATED`); the advisor's `cumulative_commissions_cents` is
    not recomputed by the transition."

    Design: Difficulty/non_linear_state_machine/training_remediation_loop_then_pass
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 10000, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)

    post_production(advisor["id"], 5000, "2026-02-01T00:00:00Z")
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    first_eval = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-03-01T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    assert first_eval["outcome"] == "FAIL"
    program_now = get_success_data(api_client.get_training_program(program["id"], ADMIN))
    assert program_now["status"] == "REMEDIATION"
    advisor_now = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert advisor_now["status"] == "TRAINEE"

    # Remediation loop: submit again, add production, evaluate a second time.
    post_production(advisor["id"], 6000, "2026-03-15T00:00:00Z")
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    second_eval = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-04-01T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    # Production counts cumulatively from the program start_date.
    assert second_eval["production_cents"] == 11000
    assert second_eval["outcome"] == "PASS"

    program_final = get_success_data(api_client.get_training_program(program["id"], ADMIN))
    assert program_final["status"] == "COMPLETED"
    advisor_final = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert advisor_final["status"] == "VALIDATED"


def test_remediation_cycle_keeps_advisor_trainee():
    """PRD §3.1: "A failing evaluation drops the program into `REMEDIATION`
    while the advisor remains a `TRAINEE`, and the remediation loop permits
    the advisor to submit again from `REMEDIATION` back to
    `MILESTONE_PENDING`."
    PRD §3.1: "A passing evaluation completes the program
    (`MILESTONE_PENDING → COMPLETED`) and validates the advisor
    (`TRAINEE → VALIDATED`); the advisor's `cumulative_commissions_cents` is
    not recomputed by the transition."

    Design: Difficulty/non_linear_state_machine/training_remediation_loop_then_pass
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 10000, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    post_production(advisor["id"], 5000, "2026-02-01T00:00:00Z")

    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-03-01T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    assert get_success_data(
        api_client.get_training_program(program["id"], ADMIN)
    )["status"] == "REMEDIATION"
    assert get_success_data(
        api_client.get_advisor(advisor["id"], ADMIN)
    )["status"] == "TRAINEE"

    # The loop allows a second submission from REMEDIATION.
    submitted = get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    assert submitted["status"] == "MILESTONE_PENDING"
