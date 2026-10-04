"""Sites and the funding ledger: creation defaults, posture bands, posture
recomputation on member activation, and the close precondition."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
)


class TestSiteCreationDefaults:
    def test_site_create_defaults_and_tight_posture(self, api):
        """PRD §3.1: "A new site begins in `SETUP` status with all of its
        received-funding counters at zero."
        PRD §3.1: "A freshly created site has zero receipts, zero outlay, and
        zero obligations, so its headroom is 0 and its posture reads `TIGHT`."

        Design: Corner/entities/site_create_defaults_and_tight_posture
        """
        fixtures.set_clock(api)
        resp = api.create_site(factories.site_payload(), SITE_DIRECTOR_HEADERS)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["response_type"] == "object"
        site = validate_success(resp, 201)

        assert site["status"] == "SETUP"
        assert site["version"] == 1
        assert site["funding_posture"] == "TIGHT"
        assert site["funding_headroom_cents"] == 0
        assert site["cost_share_installment_1_cents"] == 0
        assert site["district_committed_cents"] == 0
        assert site["philanthropy_committed_cents"] == 0
        assert site["federal_committed_cents"] == 0
        assert site["district_received_cents"] == 0
        assert site["philanthropy_received_cents"] == 0
        assert site["federal_received_cents"] == 0
        assert site["total_received_cents"] == 0
        assert site["stipend_outlay_cents"] == 0
        assert site["id"] and site["created_at"] and site["updated_at"]


class TestFundingPosture:
    def test_funding_posture_threshold_walk(self, api):
        """PRD §3.1: "Subtracting outlay and projected obligations from total
        receipts yields `funding_headroom_cents`, and the headroom drives
        `funding_posture`: `DEFICIT` when headroom is negative, `TIGHT` when
        headroom is zero or positive but below 500000 cents (a $5,000 buffer),
        and `FUNDED` otherwise."

        Design: Corner/calculations/funding_posture_threshold_walk"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])

        pre = fixtures.get_site(api, site["id"])
        assert pre["funding_posture"] == "DEFICIT"
        # 0 received - 0 outlay - 1300000 projected obligations.
        assert pre["funding_headroom_cents"] == -1_300_000

        mid = validate_success(
            api.receive_funding(
                site["id"],
                {"funding_type": "DISTRICT", "amount_cents": 1_300_000},
                SITE_DIRECTOR_HEADERS,
            )
        )
        # 0 is inside the TIGHT band (lower boundary inclusive).
        assert mid["funding_posture"] == "TIGHT"
        assert mid["funding_headroom_cents"] == 0

        post = validate_success(
            api.receive_funding(
                site["id"],
                {"funding_type": "FEDERAL", "amount_cents": 500_000},
                SITE_DIRECTOR_HEADERS,
            )
        )
        # 500000 is not below 500000: the upper boundary lands in FUNDED.
        assert post["funding_posture"] == "FUNDED"
        assert post["funding_headroom_cents"] == 500_000

    def test_posture_reconciles_on_member_activation(self, api):
        """PRD §3.7: "Activation — `ENROLLED` to `ACTIVE` — requires the site
        to be `ACTIVE` (else `ERR_INVALID_STATE`) and cascades inside the
        member record: `stipend_status` moves from `NOT_STARTED` to `ACTIVE`,
        and the site's `projected_obligations_cents` and `funding_posture` are
        recomputed."

        Design: Corner/cross_cutting_layers/posture_reconciles_on_member_activation
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.enroll_member(api, site["id"])

        pre = fixtures.get_site(api, site["id"])
        assert pre["funding_posture"] == "TIGHT"
        assert pre["funding_headroom_cents"] == 0

        fixtures.activate_member_service(api, member["id"])
        mid = fixtures.get_site(api, site["id"])
        assert mid["funding_posture"] == "DEFICIT"
        assert mid["funding_headroom_cents"] == -1_300_000
        assert mid["projected_obligations_cents"] == 1_300_000

        fixtures.suspend_member_service(api, member["id"])
        post = fixtures.get_site(api, site["id"])
        # Service suspension cascaded stipend to SUSPENDED, so obligations
        # return to zero and posture to TIGHT.
        assert post["funding_posture"] == "TIGHT"
        assert post["funding_headroom_cents"] == 0


class TestSiteClose:
    def test_site_close_blocked_with_live_members(self, api):
        """PRD §3.1: "no corps member of the site may have `service_status` of
        `ENROLLED`, `ACTIVE`, or `SUSPENDED`, and no team at any of the site's
        schools may be `FORMING`, `DEPLOYED`, or `UNDERSTAFFED`. Either
        violation is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/site_close_blocked_with_live_members
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])

        blocked = api.transition_site(site["id"], {"to_status": "CLOSED"}, SITE_DIRECTOR_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        exited = fixtures.exit_member(api, member["id"], "FOR_CAUSE")
        assert exited["service_status"] == "EXITED_EARLY"

        closed = api.transition_site(site["id"], {"to_status": "CLOSED"}, SITE_DIRECTOR_HEADERS)
        data = validate_success(closed)
        assert data["status"] == "CLOSED"
