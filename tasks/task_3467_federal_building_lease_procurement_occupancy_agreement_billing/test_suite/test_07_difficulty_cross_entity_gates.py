"""Cross-entity state dependencies: a transition gated on another entity's
state (PRD §2.10 rule 7)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, activate_oa, commence_lease, create_agency,
    create_leased_oa, create_owned_building, create_owned_oa,
    make_agency_manager_headers, set_clock, setup_awarded_lease,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]


def test_oa_activation_gated_on_lease_commencement(api):
    """PRD §3.5: "A leased agreement may activate only while its lease is
    `COMMENCED` or `EXPIRING` (`ERR_LEASE_NOT_COMMENCED`); an owned agreement
    has no lease gate."
    PRD §3.4: "Commencement pins the lease's `end_date`: the date
    `term_months` months after the commencement date, minus one day, using
    month arithmetic with the day preserved and clamped to the target month's
    end."

    While the lease is merely AWARDED the activate is rejected; after
    commencement the identical call succeeds.

    Design: Difficulty/cross_entity_state_dependency/oa_activation_gated_on_lease_commencement
    """
    bundle = setup_awarded_lease()
    agency, lease = bundle["agency"], bundle["lease"]
    agency_h = make_agency_manager_headers(agency["id"])
    oa = create_leased_oa(lease, agency)

    resp = api.activate_oa(oa["id"], agency_h)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_COMMENCED)
    oa_mid = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_mid["status"] == "DRAFT", "the rejected activation left DRAFT intact"

    commenced = commence_lease(lease)
    assert commenced["status"] == "COMMENCED"
    assert commenced["end_date"] == "2036-12-31"

    activated = validate_success(api.activate_oa(oa["id"], agency_h), 200)
    assert activated["status"] == "ACTIVE"


def test_alteration_lifecycle_gated_on_oa_active(api):
    """PRD §3.6: "Mid-term space alterations begin with the tenant: an
    `AgencyManager` of the agreement's agency requests one against an `ACTIVE`
    agreement (`ERR_OA_NOT_ACTIVE`), supplying a `title`, a scope
    `description`, and the `scope_sf` affected (greater than zero). The request
    starts in `REQUESTED`."

    No alteration can even be created while the OA is DRAFT; the identical
    create succeeds once the OA is ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/alteration_lifecycle_gated_on_oa_active
    """
    agency = create_agency(name="Park Service")
    building = create_owned_building()
    set_clock("2026-10-01T00:00:00Z")
    oa = create_owned_oa(building, agency)
    agency_h = make_agency_manager_headers(agency["id"])

    payload = {"title": "Kitchenette", "description": "Break room upgrade",
               "scope_sf": 400}
    resp = api.create_alteration(oa["id"], payload, agency_h)
    validate_error(resp, ApiErrorId.ERR_OA_NOT_ACTIVE)

    activate_oa(oa, agency)

    created = validate_success(api.create_alteration(oa["id"], payload, agency_h), 201)
    assert created["status"] == "REQUESTED"
    assert created["oa_id"] == oa["id"]
