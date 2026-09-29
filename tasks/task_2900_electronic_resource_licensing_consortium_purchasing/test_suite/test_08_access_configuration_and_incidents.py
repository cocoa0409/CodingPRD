"""Federation bindings, incident lifecycles and the access health decay."""

from test_helpers import (
    assert_access_health_score,
    assert_access_incident,
    assert_auth_config,
    assert_renewal_decision,
    assert_subscription,
    auth_config_payload,
    cast_vote,
    configure_auth,
    decide,
    diagnose,
    diagnose_and_resolve,
    file_usage_months,
    open_renewal_decision,
    open_vote,
    probe_auth,
    probe_payload,
    read_incident,
    read_subscription,
    reopen,
    report_incident,
    report_off_campus_incidents,
    resolve,
    resolve_payload,
    set_clock,
    setup_active_subscription,
    setup_configured_access,
    setup_realm_bindings,
    validate_error,
    validate_paginated,
    validate_success,
)


def _only_auth_config(api, headers, subscription_id):
    """The single binding of a subscription, read back through its listing."""
    rows, meta = validate_paginated(api.list_auth_configs(subscription_id, headers))
    assert meta["total_count"] == 1
    return rows[0]


def test_resolving_an_undiagnosed_incident_is_rejected(api, engineer):
    """The only edge into RESOLVED starts at DIAGNOSED, never at OPEN.

    PRD: "Resolution advances `DIAGNOSED → RESOLVED` and writes `remedy_code` —
    one of `IP_RANGE_UPDATED`, `PROXY_FIXED`, `VENDOR_TICKET_CLOSED` or
    `ENTITLEMENT_LOADED`."

    PRD: "The incident opens in `OPEN` with `root_cause_code` and `remedy_code`
    null and `reopen_count` of 0."

    Design: Corner/errors/resolving_an_undiagnosed_incident_is_rejected
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    incident = report_incident(subscription_id, scenario["member"]["id"],
                               "OFF_CAMPUS_DENIED", True)
    assert incident["status"] == "OPEN"
    assert read_subscription(subscription_id)["access_health_score"] == 92

    response = api.resolve_incident(incident["id"], resolve_payload("PROXY_FIXED"),
                                    engineer)
    validate_error(response, "ERR_INCIDENT_INVALID_STATE", 409)

    stored = read_incident(incident["id"])
    assert_access_incident(stored)
    assert stored["status"] == "OPEN", "the refused resolution moved nothing"
    assert stored["root_cause_code"] is None
    assert stored["remedy_code"] is None, "no remedy was recorded"
    assert stored["reopen_count"] == 0

    subscription = read_subscription(subscription_id)
    assert subscription["access_health_score"] == 92, (
        "one off-campus incident costs eight points and the refusal changed nothing"
    )
    assert subscription["access_status"] == "CONFIGURED"


def test_verifying_auth_while_the_contract_is_not_active_is_rejected(api, engineer, admin):
    """The probe reads the subscription's contract axis, not just its own state.

    PRD: "The probe is admissible while the binding's `verification_status` is
    `PENDING` or `FAILED`, and requires the subscription's `contract_status` to be
    `ACTIVE`; a binding that is already `VERIFIED` cannot be re-probed and yields
    `ERR_AUTH_CONFIG_INVALID_STATE` (409)."

    PRD: "The code names the entity whose state was wrong:
    `ERR_TRIAL_INVALID_STATE`, `ERR_NEGOTIATION_INVALID_STATE`,
    `ERR_COMMITMENT_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE`,
    `ERR_RENEWAL_INVALID_STATE`, `ERR_ARCHIVAL_CHECK_INVALID_STATE`,
    `ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE`,
    `ERR_SUBSCRIPTION_ACCESS_INVALID_STATE` or `ERR_AUTH_CONFIG_INVALID_STATE` —
    all HTTP 409."

    Design: Corner/errors/verifying_auth_before_activation_returns_subscription_contract_invalid_state
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]
    binding = configure_auth(subscription_id)
    assert binding["verification_status"] == "PENDING"

    decision = open_renewal_decision(subscription_id, "CANCEL", 0.00)
    decision = open_vote(decision["id"])
    cast_vote(decision["id"], member_id, "YES")
    decide(decision["id"], "CANCEL")
    assert read_subscription(subscription_id)["contract_status"] == "NOTICE_GIVEN"

    response = api.verify_auth_config(binding["id"], probe_payload("PASS"), engineer)
    validate_error(response, "ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE", 409)

    stored = _only_auth_config(api, admin, subscription_id)
    assert_auth_config(stored)
    assert stored["verification_status"] == "PENDING", "the probe never landed"
    assert stored["last_probe_result"] is None

    subscription = read_subscription(subscription_id)
    assert subscription["contract_status"] == "NOTICE_GIVEN", (
        "the blocking row is the subscription, not the binding"
    )
    assert subscription["access_status"] == "UNCONFIGURED"
    assert subscription["access_health_score"] == 100


def test_verifying_an_already_verified_auth_config_is_rejected(api, engineer, admin):
    """VERIFIED has no outgoing edge, so the score reset cannot be re-run.

    PRD: "The probe is admissible while the binding's `verification_status` is
    `PENDING` or `FAILED`, and requires the subscription's `contract_status` to be
    `ACTIVE`; a binding that is already `VERIFIED` cannot be re-probed and yields
    `ERR_AUTH_CONFIG_INVALID_STATE` (409)."

    PRD: "It also reaches into the subscription: `access_status` advances to
    `CONFIGURED`, and `access_health_score` is reset to 100."

    Design: Corner/errors/verifying_an_already_verified_auth_config_is_rejected
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["auth_config"]["verification_status"] == "VERIFIED"
    report_off_campus_incidents(subscription_id, scenario["member"]["id"], 3)
    assert read_subscription(subscription_id)["access_health_score"] == 76

    response = api.verify_auth_config(scenario["auth_config"]["id"],
                                      probe_payload("PASS"), engineer)
    validate_error(response, "ERR_AUTH_CONFIG_INVALID_STATE", 409)

    stored = _only_auth_config(api, admin, subscription_id)
    assert stored["verification_status"] == "VERIFIED"
    assert stored["last_probe_result"] == "PASS", "the first probe's outcome stands"

    subscription = read_subscription(subscription_id)
    assert subscription["access_health_score"] == 76, (
        "the refused probe did not launder away three off-campus penalties"
    )
    assert subscription["access_status"] == "CONFIGURED"


def _score_walked_down_to_fifty_five():
    """Two reopened off-campus incidents and one untouched on-campus incident.

    The walk is 100 → 80 on the three filings, → 85 and → 65 as I1 is resolved
    and reopened, → 70 and → 50 as I2 is resolved and reopened (which degrades
    the axis once), and → 55 as I1 is resolved a second time.  I2 is then
    diagnosed, leaving its resolution as the only step that can reach 60.
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]

    first = report_incident(subscription_id, member_id, "OFF_CAMPUS_DENIED", True)
    second = report_incident(subscription_id, member_id, "PROXY_LOOP", True)
    third = report_incident(subscription_id, member_id, "WALK_IN_BLOCKED", False)

    diagnose_and_resolve(first["id"])
    reopen(first["id"], member_id)
    diagnose_and_resolve(second["id"])
    reopen(second["id"], member_id)
    diagnose_and_resolve(first["id"])
    diagnose(second["id"])

    scenario["incidents"] = [first, second, third]
    scenario["member_id"] = member_id
    return scenario


def test_a_resolution_landing_exactly_on_the_threshold_restores_configured(api, engineer):
    """A recomputed score of exactly 60 is enough to leave DEGRADED.

    PRD: "When a recomputation triggered by a resolution leaves the score
    **greater than or equal to** 60 while the axis is `DEGRADED`, it advances
    `DEGRADED → CONFIGURED`; a recomputed score of exactly 60 restores
    `CONFIGURED`."

    PRD: "Each incident whose `status` is exactly `RESOLVED` gives back 5 points
    of recovery."

    PRD: "Each entry into `DEGRADED` adds to `sla_credit_cents` an amount equal to
    two percent of the subscription's current `negotiated_price_cents`, rounded
    half up to whole cents — but only while the newly incremented `degrade_count`
    is less than or equal to 3 events."

    Design: Difficulty/boundary_precision_check/access_health_score_exactly_at_degrade_threshold_restores_configured
    """
    scenario = _score_walked_down_to_fifty_five()
    subscription_id = scenario["subscription"]["id"]
    first, second, third = scenario["incidents"]

    response = api.resolve_incident(second["id"], resolve_payload("PROXY_FIXED"),
                                    engineer)
    data = validate_success(response)

    assert_access_incident(data)
    assert data["status"] == "RESOLVED"
    assert data["reopen_count"] == 1, "the reopen penalty survives the resolution"
    assert data["remedy_code"] == "PROXY_FIXED"

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["access_health_score"] == 60, (
        "8 + 15 - 5 twice over plus 4 for the on-campus incident is a penalty of 40"
    )
    assert subscription["access_status"] == "CONFIGURED", (
        "the recovery comparison is inclusive, so exactly 60 restores the axis"
    )
    assert subscription["degrade_count"] == 1, "restoring is not a second degradation"
    assert subscription["sla_credit_cents"] == 180000, "two percent of 9,000,000, once"

    assert read_incident(first["id"])["status"] == "RESOLVED"
    assert read_incident(third["id"])["status"] == "OPEN", (
        "the on-campus incident was never worked"
    )
    assert_access_health_score(
        [read_incident(row["id"]) for row in (first, second, third)], 60)


def test_a_resolution_five_points_short_of_the_threshold_stays_degraded(api, engineer):
    """The same endpoint at 55 leaves the axis where it is, so 60 is the boundary.

    PRD: "The **access health score** is a decay function recomputed from scratch
    over *every* incident row on the subscription, regardless of status, whenever
    an incident is created, reopened or resolved."

    PRD: "When a recomputation triggered by an incident report or a reopen leaves
    the score **strictly below** 60 while the subscription's `access_status` is
    `CONFIGURED`, the axis advances `CONFIGURED → DEGRADED`."

    PRD: "Each incident additionally contributes 15 points for every reopen it has
    suffered — that is, 15 multiplied by its `reopen_count`."

    Design: Difficulty/boundary_precision_check/access_health_score_exactly_at_degrade_threshold_restores_configured
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]

    first = report_incident(subscription_id, member_id, "OFF_CAMPUS_DENIED", True)
    second = report_incident(subscription_id, member_id, "PROXY_LOOP", True)
    report_incident(subscription_id, member_id, "WALK_IN_BLOCKED", False)
    after_filings = read_subscription(subscription_id)
    assert after_filings["access_health_score"] == 80, "8 + 8 + 4 of base penalty"
    assert after_filings["access_status"] == "CONFIGURED"

    diagnose_and_resolve(first["id"])
    reopen(first["id"], member_id)
    after_first_reopen = read_subscription(subscription_id)
    assert after_first_reopen["access_health_score"] == 65
    assert after_first_reopen["access_status"] == "CONFIGURED", "65 is not below 60"
    assert after_first_reopen["degrade_count"] == 0
    assert after_first_reopen["sla_credit_cents"] == 0

    diagnose_and_resolve(second["id"])
    assert read_subscription(subscription_id)["access_health_score"] == 70
    reopen(second["id"], member_id)
    after_second_reopen = read_subscription(subscription_id)
    assert after_second_reopen["access_health_score"] == 50
    assert after_second_reopen["access_status"] == "DEGRADED", "50 is strictly below 60"
    assert after_second_reopen["degrade_count"] == 1
    assert after_second_reopen["sla_credit_cents"] == 180000

    diagnose(first["id"])
    resolved_again = resolve(first["id"])
    assert resolved_again["status"] == "RESOLVED"
    short_of_the_threshold = read_subscription(subscription_id)
    assert short_of_the_threshold["access_health_score"] == 55, (
        "the second resolution gives back only its own 5 points"
    )
    assert short_of_the_threshold["access_status"] == "DEGRADED", (
        "55 does not reach the inclusive restore threshold"
    )
    assert short_of_the_threshold["degrade_count"] == 1, "no second degradation happened"
    assert short_of_the_threshold["sla_credit_cents"] == 180000, "and no second credit"


def test_a_fourth_overlapping_binding_on_one_realm_is_refused(api, engineer, admin):
    """Three legal bindings on one realm make the fourth illegal by aggregate.

    PRD: "Before a new binding is admitted, the system counts the existing
    authentication bindings that share the same `auth_realm_code`, whose
    `verification_status` is either `PENDING` or `VERIFIED`, and whose
    subscription's window overlaps the new subscription's window."

    PRD: "A subscription's window for this purpose runs from its
    `activation_start_date` to its `term_end` and is closed at both ends, so
    windows that merely touch at a single day do count as overlapping."

    PRD: "If that count is already 3 or more, the request is refused with
    `ERR_REALM_CAPACITY_EXCEEDED` (409); it is admitted only while the count is
    strictly below 3 overlapping bindings."

    Design: Difficulty/resource_temporal_overlap/fourth_overlapping_binding_on_one_realm_exceeds_realm_capacity
    """
    scenario = setup_realm_bindings()
    subscriptions = scenario["subscriptions"]
    for subscription in subscriptions:
        assert subscription["activation_start_date"] == "2027-01-01"
        assert subscription["term_end"] == "2027-12-31", "all four windows coincide"

    response = api.create_auth_config(
        subscriptions[3]["id"],
        auth_config_payload(auth_method="SHIBBOLETH", auth_realm_code="SHIB-EDU-1"),
        engineer,
    )
    validate_error(response, "ERR_REALM_CAPACITY_EXCEEDED", 409)

    for index in range(3):
        binding = _only_auth_config(api, admin, subscriptions[index]["id"])
        assert binding["verification_status"] == "PENDING", (
            "a binding awaiting its probe still occupies the realm"
        )
        assert binding["auth_realm_code"] == "SHIB-EDU-1"

    rows, meta = validate_paginated(
        api.list_auth_configs(subscriptions[3]["id"], admin))
    assert meta["total_count"] == 0, "the refused binding stored no row"
    assert rows == []
    assert read_subscription(subscriptions[3]["id"])["access_status"] == "UNCONFIGURED"


def test_a_failed_binding_frees_the_realm_for_the_same_request(api, engineer, admin):
    """The capacity counts PENDING and VERIFIED bindings only, so a FAILED one releases a slot.

    PRD: "Bindings whose `verification_status` is `FAILED` are not counted at all."

    PRD: "A `FAIL_OFF_CAMPUS` or `FAIL_ON_CAMPUS` sets `verification_status` to
    `FAILED` and `last_probe_result` to the reported outcome."

    PRD: "The binding records the `subscription_id` it configures and is created
    with `verification_status` of `PENDING` and `last_probe_result` of null."

    Design: Difficulty/resource_temporal_overlap/fourth_overlapping_binding_on_one_realm_exceeds_realm_capacity
    """
    scenario = setup_realm_bindings()
    subscriptions = scenario["subscriptions"]
    payload = auth_config_payload(auth_method="SHIBBOLETH",
                                  auth_realm_code="SHIB-EDU-1")

    validate_error(
        api.create_auth_config(subscriptions[3]["id"], payload, engineer),
        "ERR_REALM_CAPACITY_EXCEEDED", 409)

    failed = probe_auth(scenario["auth_configs"][0]["id"], "FAIL_OFF_CAMPUS")
    assert failed["verification_status"] == "FAILED"
    assert failed["last_probe_result"] == "FAIL_OFF_CAMPUS"
    assert read_subscription(subscriptions[0]["id"])["access_status"] == "UNCONFIGURED", (
        "a failing probe touches nothing on its subscription"
    )

    data = validate_success(
        api.create_auth_config(subscriptions[3]["id"], payload, engineer),
        expected_status=201)

    assert_auth_config(data)
    assert data["subscription_id"] == subscriptions[3]["id"]
    assert data["auth_realm_code"] == "SHIB-EDU-1"
    assert data["verification_status"] == "PENDING", (
        "two counted bindings is strictly below the capacity of three"
    )
    assert data["last_probe_result"] is None
    assert read_subscription(subscriptions[3]["id"])["access_status"] == "UNCONFIGURED"


def _read_decision(api, headers, subscription_id, decision_id):
    """One renewal decision of a subscription, read back through its listing."""
    rows, _ = validate_paginated(
        api.list_renewal_decisions(subscription_id, headers))
    matching = [row for row in rows if row["id"] == decision_id]
    assert len(matching) == 1, "the decision under test is on the subscription"
    return matching[0]


def _voting_decision_over_a_recoverable_incident():
    """A VOTING renewal offer sitting on a subscription one reopen away from DEGRADED.

    Two months of usage pool to 6,200 full-text requests over the window
    [2027-01, 2027-03], so the offer's band is `GOOD`.  Five off-campus incidents
    then park the score on exactly 60 and resolving the first lifts it to 65,
    leaving the reopen of that incident as the step that crosses the threshold.
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]

    file_usage_months(subscription_id, scenario["vendor"]["id"], member_id,
                      [("2027-01", 3100), ("2027-02", 3100)])
    set_clock("2027-03-01T00:00:00Z")

    decision = open_renewal_decision(subscription_id, "RENEW", 12.00)
    scenario["decision"] = open_vote(decision["id"])

    incidents = report_off_campus_incidents(subscription_id, member_id, 5)
    diagnose_and_resolve(incidents[0]["id"])

    scenario["incidents"] = incidents
    scenario["member_id"] = member_id
    return scenario


def test_the_reopen_cascade_degrades_the_axis_and_accrues_the_sla_credit(api):
    """One reopen drives three hops: the incident, the axis, and the money.

    PRD: "A reopen's **first hop** increments the incident's `reopen_count` by 1,
    sets its `status` to `REOPENED` and clears `remedy_code` back to null."

    PRD: "The **second hop** is caused by that mutation: the subscription's
    `access_health_score` is recomputed, and if the recomputed score is below 60
    while the axis is `CONFIGURED`, the axis moves to `DEGRADED` and the
    subscription's `degrade_count` is incremented by 1."

    PRD: "The **third hop** is caused by that degradation: an SLA credit accrues."

    Design: Difficulty/transitive_cascade/incident_reopen_cascade_accrues_sla_credit_and_refreshes_the_voting_offer
    """
    scenario = _voting_decision_over_a_recoverable_incident()
    subscription_id = scenario["subscription"]["id"]
    before = read_subscription(subscription_id)
    assert before["access_health_score"] == 65
    assert before["access_status"] == "CONFIGURED"
    assert before["sla_credit_cents"] == 0

    reopened = reopen(scenario["incidents"][0]["id"], scenario["member_id"])

    assert_access_incident(reopened)
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["remedy_code"] is None, "the remedy that did not hold is cleared"

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["access_health_score"] == 45, (
        "the reopen adds 15 and forfeits the 5 points of recovery"
    )
    assert subscription["access_status"] == "DEGRADED"
    assert subscription["degrade_count"] == 1
    assert subscription["sla_credit_cents"] == 180000, "two percent of 9,000,000"
    assert subscription["contract_status"] == "ACTIVE", "the contract axis is unmoved"
    assert subscription["negotiated_price_cents"] == 9000000


def test_the_accrued_credit_refreshes_the_offer_members_are_voting_on(api, admin):
    """The fourth hop follows the credit, not the reopen call, and only for VOTING.

    PRD: "The **fourth hop** is caused by the credit movement: every renewal
    decision on this subscription whose `status` is `VOTING` has its offer
    recomputed, refreshing `sla_credit_applied_cents` and `offer_price_cents` so
    that members voting right now see the credit they have actually earned."

    PRD: "Take the SLA credit: `sla_credit_applied_cents` is a straight snapshot of
    the subscription's current `sla_credit_cents`."

    PRD: "Set `offer_price_cents` to the larger of that floor and the escalated
    amount less the loyalty credit less the applied SLA credit."

    Design: Difficulty/transitive_cascade/incident_reopen_cascade_accrues_sla_credit_and_refreshes_the_voting_offer
    """
    scenario = _voting_decision_over_a_recoverable_incident()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]

    preliminary = scenario["decision"]
    assert_renewal_decision(preliminary)
    assert preliminary["status"] == "VOTING"
    assert float(preliminary["capped_increase_pct"]) == 5.00, "12.00 asked, 5.00 capped"
    assert preliminary["cost_per_use_cents"] == 1452, "9,000,000 over 6,200 requests"
    assert preliminary["cost_per_use_band"] == "GOOD"
    assert preliminary["loyalty_credit_cents"] == 180000, "two percent for a GOOD band"
    assert preliminary["sla_credit_applied_cents"] == 0
    assert preliminary["offer_price_cents"] == 9270000, (
        "9,450,000 escalated less the 180,000 loyalty credit"
    )

    reopen(scenario["incidents"][0]["id"], scenario["member_id"])

    refreshed = _read_decision(api, admin, subscription_id, decision_id)
    assert_renewal_decision(refreshed)
    assert refreshed["status"] == "VOTING", "the vote is still open"
    assert refreshed["sla_credit_applied_cents"] == 180000, (
        "the snapshot follows the subscription's freshly accrued credit"
    )
    assert refreshed["offer_price_cents"] == 9090000, (
        "9,450,000 less 180,000 of loyalty less 180,000 of SLA credit"
    )
    assert float(refreshed["capped_increase_pct"]) == 5.00, "the cap is unchanged"
    assert refreshed["cost_per_use_cents"] == 1452, (
        "the band stays keyed on the prior term's price"
    )
    assert refreshed["cost_per_use_band"] == "GOOD"
    assert refreshed["loyalty_credit_cents"] == 180000
    assert read_subscription(subscription_id)["negotiated_price_cents"] == 9000000, (
        "recomputing an offer never touches the running term's price"
    )
