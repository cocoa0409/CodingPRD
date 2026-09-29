"""State-machine probes: the two parallel initial states, refused transitions,
precondition enforcement, terminal lockdown, the clock-driven expiry and one
closure cascade.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_PROCESS_TRANSITION,
    ERR_INVALID_QUALITY_TRANSITION,
    ERR_ORDER_INVALID_STATE,
    ERR_OUTSIDE_APPLICATION_WINDOW,
    ERR_SITE_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_cost_breakdown,
    assert_dry_tons,
    assert_facility_storage,
    assert_instant_equals,
    assert_percent,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    CERTIFYING_OFFICER_ID,
    OFFICER_HEADERS,
    make_officer_headers,
    make_operator_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestBatchInitialState:
    def test_new_batch_sits_at_both_declared_initial_states(self, api, build, facility):
        """PRD §3.2: "A batch is created with `process_status` `THICKENED`, `quality_status` `UNTESTED`, `disposition` `HELD` and `version` 1; `dry_tons_produced`, `unallocated_dry_tons`, `vsr_pct_van_kleeck` and `vsr_pct_mass_balance` all stay at 0.000 until the batch is dewatered."

        A batch runs two independent state dimensions, so a freshly created one sits at
        both initial states at once - THICKENED on the process side and UNTESTED on the
        quality side - with nothing yet reserved, no reduction figures computed and no
        vector demonstration recorded, while its wet tons are already on the pad.

        Design: Corner/state_machines/sm_batch_created_starts_thickened_and_untested_and_held
        """
        batch = validate_success(
            api.create_batch(
                F.batch_payload(facility["id"]), make_operator_headers(facility["id"])
            ),
            201,
        )

        assert batch["process_status"] == C.PROCESS_THICKENED
        assert batch["quality_status"] == C.QUALITY_UNTESTED
        assert batch["disposition"] == C.DISPOSITION_HELD
        assert_percent(batch["vsr_pct_van_kleeck"], 0.00)
        assert_percent(batch["vsr_pct_mass_balance"], 0.00)
        assert batch["vector_demonstrated_at_batch"] is False
        assert_dry_tons(batch["dry_tons_produced"], 0.000)
        assert_dry_tons(batch["unallocated_dry_tons"], 0.000)
        assert batch["retest_round"] == 0
        assert batch["version"] == 1

        assert_facility_storage(build.read_facility(facility["id"]), 800.00, 16.00)


class TestCertifyFromUntested:
    def test_certifying_an_untested_batch_is_refused_by_the_state_check(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.4: "Its preconditions, checked in the ladder order of §2.7, are that `process_status` is `DEWATERED`, `quality_status` is `PENDING_RESULTS` (any other quality state is `ERR_INVALID_QUALITY_TRANSITION`), the facility posture is not `FROZEN`, the derived `pathogen_class` is `CLASS_B` or `CLASS_A`, the plant-side vector evidence for the chosen option passes, every analyte that has an `ACTIVE` limit row at this moment has a result in the current round, no current-round result has `exceeds_ceiling` true, and no current-round result has `exceeds_monthly_avg` true."

        Certification is reachable only from PENDING_RESULTS, so a batch still UNTESTED
        is refused by the priority-20 dimension check before any pathogen, vector or
        panel evidence can be consulted, and the row is left untouched at version 1.
        A batch that is UNTESTED is necessarily still THICKENED, because the DEWATERED
        advance itself moves UNTESTED to PENDING_RESULTS, so both the process and the
        quality precondition are violated by the same request. Priority 20 covers both
        dimensions at one level and names both identifiers without stating which
        dimension is inspected first, so either is a faithful answer.

        Design: Corner/state_machines/sm_certify_from_untested_quality_dimension_is_rejected
        """
        batch = build.batch(facility["id"])

        response = api.certify_batch(
            batch["id"], make_officer_headers(CERTIFYING_OFFICER_ID)
        )
        validate_error_is_one_of(
            response,
            [ERR_INVALID_QUALITY_TRANSITION, ERR_INVALID_PROCESS_TRANSITION],
        )

        current = build.read_batch(batch["id"])
        assert current["quality_status"] == C.QUALITY_UNTESTED
        assert current["certified_at"] is None
        assert current["certified_by_user_id"] is None
        assert current["version"] == 1


class TestStartOutsideTheWindow:
    def test_start_before_the_window_opens_is_refused(self, api, base_world):
        """PRD §2.7: "**Priority 41 — inside the window.** The logical clock lies inside the half-open window from `window_start` inclusive to `window_end` exclusive, otherwise `ERR_OUTSIDE_APPLICATION_WINDOW` (409)."

        Every other start precondition holds - the site is PERMITTED with clear
        weather, the agreement is ACTIVE and the batch is QUALIFIED - and only the clock is
        wrong, still reading the seed instant while the window opens on 20 August. The
        window precondition alone refuses the transition and the reservation stands.

        Design: Corner/state_machines/sm_start_outside_the_application_window_is_rejected
        """
        event = base_world.build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            acres_treated=100.0,
            planned_dry_tons=80.000,
        )

        response = api.start_event(event["id"], make_operator_headers())
        validate_error(response, ERR_OUTSIDE_APPLICATION_WINDOW)

        current = base_world.build.read_event(event["id"])
        assert current["status"] == C.EVENT_SCHEDULED
        assert_dry_tons(current["reserved_dry_tons"], 80.000)
        assert base_world.build.read_site(base_world.site_id)["weather_clearance_ok"] is True


class TestSubmitPermitIsNotIdempotent:
    def test_second_submit_on_an_under_review_site_is_refused(self, api, build, draft_site):
        """PRD §3.5: "**Submitting for permit review** moves `DRAFT` to `UNDER_REVIEW` and is performed by the `Agronomist`."

        Submitting for permit review is not idempotent: the first call moves the site to
        UNDER_REVIEW at version 2 and the identical second call is refused by the site
        state machine, queueing no second review and leaving the version alone.

        Design: Corner/state_machines/sm_second_submit_permit_on_under_review_site_is_rejected
        """
        build.submit_permit(draft_site["id"])

        response = api.submit_permit(draft_site["id"], AGRONOMIST_HEADERS)
        validate_error(response, ERR_SITE_INVALID_STATE)

        current = build.read_site(draft_site["id"])
        assert current["status"] == C.SITE_UNDER_REVIEW
        assert current["version"] == 2


class TestSettledOrderIsTerminal:
    def test_second_settle_is_refused_and_storage_is_debited_once(self, api, build):
        """PRD §3.10: "**Settling** moves `COMMITTED` to `SETTLED` and may be done by a `FacilityOperator` or a `ComplianceOfficer`."

        SETTLED is terminal for a diversion order, so a repeated settlement is refused
        and the pad is debited exactly once: 200.00 wet tons leave storage, not 400.00.
        The costed breakdown and the outlet's annual acceptance are unchanged by the
        refused call.

        Design: Corner/state_machines/sm_settled_diversion_order_refuses_a_second_settle
        """
        facility = build.facility()
        build.limit()
        batch = build.dewatered_batch(facility["id"])
        outlet = build.outlet()
        order = build.order(batch["id"], outlet["id"], batch["version"])
        build.commit_order(order["id"])
        build.settle_order(order["id"])

        response = api.settle_order(order["id"], make_operator_headers())
        validate_error(response, ERR_ORDER_INVALID_STATE)

        current_order = build.read_order(order["id"])
        assert current_order["status"] == C.ORDER_SETTLED
        assert_cost_breakdown(
            current_order,
            processing=9000.00,
            hauling=725.76,
            subtotal=9725.76,
            surcharge_pct=0.03,
            surcharge=291.77,
            total=10017.53,
            per_dry_ton=250.44,
        )

        assert_facility_storage(build.read_facility(facility["id"]), 600.00, 12.00)
        assert_dry_tons(build.read_batch(batch["id"])["unallocated_dry_tons"], 120.000)
        assert build.read_outlet(outlet["id"])["ytd_accepted_wet_tons"] == 200.00


class TestClockDrivenExpiry:
    def test_moving_the_clock_past_the_term_expires_the_agreement(self, api, base_world):
        """PRD §3.13: "It returns `now` as accepted together with `expired_agreement_count`, the number of `ACTIVE` agreements moved to `EXPIRED` by the sweep described in §3.6."

        Expiry is the only clock-driven transition, and it fires on the clock write
        itself: setting the clock past the term end reports one agreement expired in the
        same response, moves the agreement to EXPIRED at version 5, and leaves the site
        PERMITTED because expiry cascades nothing.

        Design: Corner/state_machines/sm_clock_move_past_term_end_expires_the_active_agreement
        """
        clock = validate_success(
            api.set_clock(F.clock_payload("2027-01-01T00:00:00Z"), OFFICER_HEADERS)
        )

        assert clock["expired_agreement_count"] == 1
        assert_instant_equals(clock["now"], "2027-01-01T00:00:00Z")

        agreement = base_world.build.read_agreement(base_world.agreement_id)
        assert agreement["status"] == C.AGREEMENT_EXPIRED
        assert agreement["version"] == 5
        assert base_world.build.read_site(base_world.site_id)["status"] == C.SITE_PERMITTED


class TestSiteClosureCascade:
    def test_closing_the_site_withdraws_the_agreement_under_negotiation(self, api, build):
        """PRD §3.5: "Success sets `status` `CLOSED`, increments the site's `version` by 1, and cascades every farmer agreement on the site whose `status` is `DRAFT`, `PROPOSED` or `COUNTERED` to `WITHDRAWN`, incrementing each agreement's `version` by 1."

        Closing a field withdraws exactly the agreement still under negotiation: the
        COUNTERED agreement moves to WITHDRAWN with its round index frozen at 1 and the
        countered rate retained, and never gains a termination stamp, because withdrawal
        is not termination. The site itself lands at version 5.

        Design: Corner/state_machines/sm_site_close_cascades_countered_agreement_to_withdrawn
        """
        facility = build.facility()
        site = build.permitted_site(facility["id"])
        agreement = build.agreement(site["id"], site["version"])
        build.propose(agreement["id"])
        build.counter(agreement["id"], max_dry_tons_per_acre=18.0)

        closed = validate_success(api.close_site(site["id"], AGRONOMIST_HEADERS))
        assert closed["status"] == C.SITE_CLOSED
        assert closed["version"] == 5

        current = build.read_agreement(agreement["id"])
        assert current["status"] == C.AGREEMENT_WITHDRAWN
        assert current["round_index"] == 1
        assert current["max_dry_tons_per_acre"] == 18.0
        assert current["version"] == 4
        assert current["terminated_at"] is None
