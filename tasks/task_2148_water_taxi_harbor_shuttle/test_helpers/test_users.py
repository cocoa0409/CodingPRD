"""Pre-built role headers for every role in the PRD.

`VesselMaster` is the one role whose `X-User-ID` is a real entity id — it is
the acting `CrewMember`'s `id`. Any ownership-gated movement call must use
`make_vessel_master_headers(crew["id"])`; the shared constant below is a
fallback only for calls that never reach an ownership check.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque identifiers used consistently across the suite.
ADMIN_USER_ID = "admin-1"
DISPATCHER_USER_ID = "disp-1"
INSPECTOR_USER_ID = "insp-1"
RIDER_ANN_USER_ID = "rider-ann"
RIDER_BOB_USER_ID = "rider-bob"
RIDER_CID_USER_ID = "rider-cid"
AUDITOR_USER_ID = "aud-1"
AUDITOR_ALT_USER_ID = "aud-2"

TEST_USERS = {
    "harbor_admin_headers": build_user_headers(ADMIN_USER_ID, "HarborAdmin"),
    "dispatcher_headers": build_user_headers(DISPATCHER_USER_ID, "Dispatcher"),
    "marine_inspector_headers": build_user_headers(INSPECTOR_USER_ID, "MarineInspector"),
    "rider_headers": build_user_headers(RIDER_ANN_USER_ID, "Rider"),
    "rider_bob_headers": build_user_headers(RIDER_BOB_USER_ID, "Rider"),
    "rider_cid_headers": build_user_headers(RIDER_CID_USER_ID, "Rider"),
    "fare_auditor_headers": build_user_headers(AUDITOR_USER_ID, "FareAuditor"),
    "fare_auditor_alt_headers": build_user_headers(AUDITOR_ALT_USER_ID, "FareAuditor"),
    # Fallback only: never valid for an ownership-gated movement call.
    "vessel_master_headers": build_user_headers("unassigned-master", "VesselMaster"),
}


def make_vessel_master_headers(crew_member_id: str) -> dict:
    """For VesselMaster. Pass the acting CrewMember's id as X-User-ID whenever the
    call is ownership-gated against the trip's master_crew_id."""
    return build_user_headers(crew_member_id, "VesselMaster")


def make_rider_headers(rider_user_id: str) -> dict:
    """For Rider. X-User-ID is the opaque customer identifier stored on the
    booking's or pass's rider_user_id."""
    return build_user_headers(rider_user_id, "Rider")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_fare_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FareAuditor")


def make_harbor_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HarborAdmin")


def make_marine_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarineInspector")
