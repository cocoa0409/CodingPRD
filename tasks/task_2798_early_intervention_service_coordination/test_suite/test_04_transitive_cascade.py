"""
Cascades that run several hops from the row the request names: a provider
suspension that raises a service gap on a family's case, and a plan supersession
that hands unspent units back to a conserved pool.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MAKEUP_AT_RISK_THRESHOLD_UNITS,
    add_service_line,
    assert_authorization_units,
    assert_case_weight,
    assert_unit_pool,
    author_ifsp,
    build_active_services,
    create_authorization,
    create_provider,
    document_visit,
    factories,
    read_authorization,
    read_coordinator,
    read_ifsp,
    read_provider,
    read_referral,
    read_service_line,
    read_visit,
    record_consent,
    schedule_visit,
    set_clock,
    validate_success,
)

SUSPENSION_CLOCK = "2026-04-06T12:00:00Z"
SUSPENSION_EFFECTIVE_DATE = "2026-04-06"


def _build_case_with_two_scheduled_sessions(api):
    """A case whose authorized line carries two 45-minute sessions, three units
    apiece, both still scheduled inside the authorization window."""
    case = build_active_services(api)
    case.provider_id = create_provider(api)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(api, case.line_id, case.provider_id)
    case.authorization_ids.append(case.authorization_id)
    for start, end in (
        ("2026-04-08T09:00:00Z", "2026-04-08T09:45:00Z"),
        ("2026-04-08T10:00:00Z", "2026-04-08T10:45:00Z"),
    ):
        case.visit_ids.append(schedule_visit(api, case.authorization_id, start, end))
    set_clock(api, SUSPENSION_CLOCK)
    case.clock = SUSPENSION_CLOCK
    return case


def _suspend(api, provider_id):
    response = api.suspend_provider(
        provider_id,
        factories.suspend_provider_payload(
            suspension_reason_code="QUALITY_CONCERN",
            effective_date=SUSPENSION_EFFECTIVE_DATE,
        ),
        ADMIN_HEADERS,
    )
    return validate_success(response, 200)


class TestProviderSuspensionReachesTheFamilyCase:
    """Provider, authorization, sessions, line, then the case's gap flag."""

    def test_suspension_cancels_sessions_and_flags_the_service_gap(self, api):
        """
        Suspending the agency cancels its scheduled sessions, loads the missed
        units onto the line as a makeup obligation, and raises the gap flag on
        a case the request never named.

        PRD 3.6: "Each affected service line has its `makeup_owed_units`
        increased by the `scheduled_units` of the sessions just cancelled, and
        where the resulting owed total strictly exceeds 4 units — one full hour
        of missed service — the line transitions to `AT_RISK`. And finally each
        affected case has `service_gap_flag` set to true, which is the signal a
        program manager watches for."

        Design: Difficulty/transitive_cascade/provider_suspension_cascade_to_service_at_risk
        """
        case = _build_case_with_two_scheduled_sessions(api)

        provider = _suspend(api, case.provider_id)
        assert provider["status"] == "SUSPENDED"
        assert provider["suspension_reason_code"] == "QUALITY_CONCERN"
        assert provider["suspended_date"] == SUSPENSION_EFFECTIVE_DATE
        assert read_provider(api, case.provider_id)["active_authorization_count"] == 0

        assert read_authorization(api, case.authorization_id)["status"] == "SUSPENDED"

        for visit_id in case.visit_ids:
            visit = read_visit(api, visit_id)
            assert visit["visit_status"] == "CANCELLED_PROVIDER"
            assert visit["billing_status"] == "CANCELLED_NO_CHARGE"
            assert visit["actual_units"] == 0
            assert visit["scheduled_units"] == 3

        line = read_service_line(api, case.line_id)
        assert line["makeup_owed_units"] == 6
        assert line["makeup_owed_units"] > MAKEUP_AT_RISK_THRESHOLD_UNITS
        assert line["status"] == "AT_RISK"

        assert read_referral(api, case.referral_id)["service_gap_flag"] is True

    def test_suspension_holds_the_units_it_does_not_release_them(self, api):
        """
        The suspended authorization keeps its whole allocation committed, so the
        line's pool is exactly where it was before the cascade ran.

        PRD 3.6: "On the suspension branch, every authorization for that
        provider whose `status` is `ACTIVE` transitions to `SUSPENDED` and keeps
        its units committed, because the program expects the provider back."

        Design: Difficulty/transitive_cascade/provider_suspension_cascade_to_service_at_risk
        """
        case = _build_case_with_two_scheduled_sessions(api)

        _suspend(api, case.provider_id)

        authorization = read_authorization(api, case.authorization_id)
        assert_authorization_units(
            authorization, units_consumed=0, units_released=0, units_remaining=24
        )

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )
        assert line["units_delivered"] == 0

        referral = read_referral(api, case.referral_id)
        assert_case_weight(referral["case_weight_points"], 1.00)
        assert_case_weight(
            read_coordinator(api, case.coordinator_id)["weighted_caseload_points"], 1.00
        )


SUPERSEDE_CLOCK = "2026-03-24T12:00:00Z"
SUPERSEDE_CONSENT_DATE = "2026-03-24"


def _build_successor_plan_case(api):
    """
    A case whose live plan has delivered 2 of its 24 authorized units and whose
    annual successor plan is authored and awaiting consent.
    """
    case = build_active_services(api)
    first_plan_id = case.ifsp_id
    first_line_id = case.line_id
    case.provider_id = create_provider(api)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(api, first_line_id, case.provider_id)
    case.authorization_ids.append(case.authorization_id)
    delivered_visit_id = schedule_visit(
        api,
        case.authorization_id,
        "2026-03-23T09:00:00Z",
        "2026-03-23T09:30:00Z",
    )
    scheduled_visit_id = schedule_visit(
        api,
        case.authorization_id,
        "2026-04-15T09:00:00Z",
        "2026-04-15T09:30:00Z",
    )
    case.visit_ids.extend([delivered_visit_id, scheduled_visit_id])
    set_clock(api, SUPERSEDE_CLOCK)
    case.clock = SUPERSEDE_CLOCK
    document_visit(
        api,
        delivered_visit_id,
        case.provider_id,
        visit_status="DELIVERED",
        actual_units=2,
    )
    successor_plan_id = author_ifsp(
        api,
        case.referral_id,
        case.coordinator_id,
        ifsp_type="ANNUAL",
        meeting_date=SUPERSEDE_CONSENT_DATE,
        supersedes_ifsp_id=first_plan_id,
    )
    successor_line_id = add_service_line(api, successor_plan_id)
    case.line_ids.append(successor_line_id)
    return case, first_plan_id, first_line_id, successor_plan_id, successor_line_id


def _consent_to_successor(api, case, successor_plan_id):
    return record_consent(
        api,
        successor_plan_id,
        case.child_id,
        consent_signed_date=SUPERSEDE_CONSENT_DATE,
    )


class TestPlanSupersessionCascade:
    """Consent to the successor retires the plan it replaces, hop by hop."""

    def test_supersession_revokes_authorizations_and_cancels_sessions(self, api):
        """
        Activating the annual plan supersedes the prior one, discontinues its
        line, revokes the line's authorization for the stated reason, and
        cancels the session still on the books.

        PRD 3.5: "Every provider authorization on those lines whose `status` is
        `ACTIVE`, `EXHAUSTED` or `SUSPENDED` transitions to `REVOKED`, with
        `units_released` set to that authorization's `units_remaining` and
        `revocation_reason_code` recorded as `PLAN_SUPERSEDED`."

        Design: Difficulty/transitive_cascade/ifsp_supersede_cascade_releases_units_to_pool
        """
        (
            case,
            first_plan_id,
            first_line_id,
            successor_plan_id,
            successor_line_id,
        ) = _build_successor_plan_case(api)

        successor = _consent_to_successor(api, case, successor_plan_id)
        assert successor["status"] == "ACTIVE"
        assert successor["activated_date"] == SUPERSEDE_CONSENT_DATE

        superseded = read_ifsp(api, first_plan_id)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["service_line_count"] == 0

        assert read_service_line(api, first_line_id)["status"] == "DISCONTINUED"

        authorization = read_authorization(api, case.authorization_id)
        assert authorization["status"] == "REVOKED"
        assert authorization["revocation_reason_code"] == "PLAN_SUPERSEDED"
        assert authorization["revoked_date"] == SUPERSEDE_CONSENT_DATE

        cancelled = read_visit(api, case.visit_ids[1])
        assert cancelled["visit_status"] == "CANCELLED_PROGRAM"
        assert cancelled["billing_status"] == "CANCELLED_NO_CHARGE"

        delivered = read_visit(api, case.visit_ids[0])
        assert delivered["visit_status"] == "DELIVERED"
        assert delivered["billing_status"] == "EXEMPT"

        assert read_referral(api, case.referral_id)["status"] == "ACTIVE_SERVICES"

    def test_supersession_releases_only_the_unconsumed_remainder(self, api):
        """
        Exactly the 22 units never delivered flow back, so the retired line's
        committed total falls to the 2 units it actually spent and the pool
        identity still sums to the planned total.

        PRD 3.6: "A line's `units_committed` is the sum of `authorized_units`
        over its authorizations in `ACTIVE`, `EXHAUSTED` or `SUSPENDED`, plus,
        for each authorization in `REVOKED`, that authorization's
        `authorized_units` minus its `units_released`, plus the same quantity
        for each authorization in `EXPIRED`."

        Design: Difficulty/transitive_cascade/ifsp_supersede_cascade_releases_units_to_pool
        """
        (
            case,
            first_plan_id,
            first_line_id,
            successor_plan_id,
            successor_line_id,
        ) = _build_successor_plan_case(api)

        _consent_to_successor(api, case, successor_plan_id)

        authorization = read_authorization(api, case.authorization_id)
        assert_authorization_units(
            authorization, units_consumed=2, units_released=22, units_remaining=0
        )

        retired_line = read_service_line(api, first_line_id)
        assert_unit_pool(
            retired_line,
            units_committed=2,
            units_pool_remaining=94,
            planned_units_total=96,
        )
        assert retired_line["units_delivered"] == 2

        successor_line = read_service_line(api, successor_line_id)
        assert successor_line["status"] == "PLANNED"
        assert_unit_pool(
            successor_line,
            units_committed=0,
            units_pool_remaining=96,
            planned_units_total=96,
        )

        assert_case_weight(
            read_referral(api, case.referral_id)["case_weight_points"], 1.00
        )
