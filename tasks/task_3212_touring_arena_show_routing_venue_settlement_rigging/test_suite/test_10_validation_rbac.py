"""Validation and RBAC coverage: required fields, role exclusivity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_engagement_payload,
    create_venue_payload,
    setup_held_engagement,
    setup_tour_and_venue,
    create_date_avail,
    validate_error,
)

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
LS = TEST_USERS["labor_steward_headers"]


class TestRequiredFields:
    def test_engagement_create_missing_agreed_rent_returns_invalid_request(self):
        """PRD §3.3: "`deal_type` is either `FLAT_RENT` or `PERCENTAGE`, and
        `agreed_rent_cents` is the contracted rent — the entire venue take under
        `FLAT_RENT`, or the floor beneath the percentage computation under
        `PERCENTAGE`."
        PRD §2.9: "required-field presence and basic shape of every input field,
        reported as `ERR_INVALID_REQUEST` (HTTP 400) when nothing earlier has
        fired."

        Design: Corner/validations/engagement_create_missing_agreed_rent_returns_invalid_request
        """
        tour, venue = setup_tour_and_venue()
        avail = create_date_avail(venue["id"])
        payload = create_engagement_payload(
            venue["id"], avail["id"], avail["version"],
        )
        payload.pop("agreed_rent_cents")
        resp = api_client.create_engagement(tour["id"], payload, TM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRoleExclusivity:
    def test_venue_booker_cannot_confirm_engagement_returns_unauthorized(self):
        """PRD §2.1: "`TourManager` — owns tour creation and lifecycle (opening
        routing, closing), engagement creation, confirmation and cancellation,
        and settlement reconciliation, payment, and dispute resolution."
        PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/venue_booker_cannot_confirm_engagement_returns_unauthorized
        """
        ctx = setup_held_engagement()
        resp = api_client.confirm_engagement(
            ctx["tour"]["id"], ctx["engagement"]["id"], VB
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        eng = api_client.get_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
        assert eng.json()["data"]["status"] == "HOLD"

    def test_labor_steward_cannot_create_venue_returns_unauthorized(self):
        """PRD §2.1: "`VenueBooker` — owns venue registration, rigging-point
        declaration, date-avail declaration and release, and the opening of
        settlement disputes on behalf of the venue."
        PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/labor_steward_cannot_create_venue_returns_unauthorized
        """
        resp = api_client.create_venue(create_venue_payload(), LS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
