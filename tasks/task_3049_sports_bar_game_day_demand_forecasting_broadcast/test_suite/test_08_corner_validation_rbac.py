"""Corner coverage of authentication, authorization, existence, cross-entity
referential rules, and role isolation."""

from test_helpers import (
    ApiErrorId,
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    NON_EXISTENT_UUID,
    create_event,
    create_guest,
    create_venue,
    event_payload,
    headers_without_role,
    validate_error,
    venue_payload,
)


class TestMissingAuthHeaderReturnsUnauthenticated:
    def test_request_without_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Listing events with no `X-User-Role` header fails authentication
        before anything else is evaluated.

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_events(headers_without_role("someone"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestWrongRoleReturnsForbidden:
    def test_host_cannot_create_a_venue(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Venue creation is a PlatformAdmin operation, so a Host attempting it
        is forbidden.

        Design: Corner/validations/wrong_role_returns_forbidden
        """
        resp = api.create_venue(venue_payload(), HOST_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestNotFoundReturns404:
    def test_getting_a_missing_venue_is_not_found(self, api):
        """PRD §2.6: "The API enforces strict, hierarchical, left-to-right validation of path identifiers. When an endpoint path nests a child under a parent, the existence of each identifier is validated in path order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist."

        A venue lookup against a UUID that was never created is a 404.

        Design: Corner/validations/not_found_returns_404
        """
        resp = api.get_venue(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPpvCheckRequiresPpvEvent:
    def test_ppv_check_referencing_a_base_event_is_rejected(self, api):
        """PRD §3.5: "The `kind` is `REGULAR` by default; a `PPV` check additionally requires an `event_id` referencing an event whose kind is `PPV`, and a PPV check without such a reference is rejected with `ERR_PPV_REQUIRES_EVENT`."

        The referenced event is kind BASE, so the PPV check cannot be opened.

        Design: Corner/validations/ppv_check_requires_ppv_event
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        event = create_event(kind="BASE", league="FF_NFL", title="Game")

        resp = api.create_check(
            {
                "venue_id": venue["id"],
                "guest_id": guest["id"],
                "party_size": 2,
                "kind": "PPV",
                "event_id": event["id"],
            },
            SERVER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PPV_REQUIRES_EVENT)


class TestSchedulerCannotManageVenue:
    def test_scheduler_creating_a_venue_is_forbidden(self, api):
        """PRD §4: the `POST /api/venues` row authorizes only PlatformAdmin.
        PRD §2.1: "A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        The Scheduler role operates the event feed only; venue management is
        out of scope.

        Design: Corner/roles/scheduler_cannot_manage_venue
        """
        resp = api.create_venue(venue_payload(), SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestServerCannotManageStaffing:
    def test_server_creating_a_staffing_plan_is_forbidden(self, api):
        """PRD §4: the `POST /api/venues/{venue_id}/staffing-plans` row authorizes only VenueManager.
        PRD §2.1: "A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        The Server role runs table service; staffing planning is out of
        scope.

        Design: Corner/roles/server_cannot_manage_staffing
        """
        venue = create_venue()

        resp = api.create_staffing_plan(venue["id"], {"name": "Plan"}, SERVER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
