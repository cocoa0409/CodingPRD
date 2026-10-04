"""Role headers for every role the API recognizes (PRD §2.1).

`WorldHeadquarters` is opaque: its X-User-ID is an operator identifier that is
never compared to any entity id, so one shared constant serves every test.

`ClubOfficer`, `Member` and `DistrictDirector` are entity-backed, so the shared
constants below are only safe for calls that are not ownership-gated. Any call
whose success depends on the caller owning the subject resource MUST use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identity — never compared to a persisted entity id.
    "world_headquarters_headers": build_user_headers("test-world-headquarters-1", "WorldHeadquarters"),
    # entity_backed:Membership — fallback for calls with no ownership clause.
    "club_officer_headers": build_user_headers("test-club-officer-1", "ClubOfficer"),
    # entity_backed:Member — fallback for calls with no ownership clause.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:Member — fallback for calls with no ownership clause.
    "district_director_headers": build_user_headers("test-district-director-1", "DistrictDirector"),
}


def make_club_officer_headers(membership_id: str) -> dict:
    """ClubOfficer acting through a real Membership of the target club.

    Pass the acting Membership's id; the ownership clause compares that
    membership's club_id against the club the operation targets.
    """
    return build_user_headers(membership_id, "ClubOfficer")


def make_member_headers(member_id: str) -> dict:
    """Member acting as themselves. Pass the real Member.id."""
    return build_user_headers(member_id, "Member")


def make_district_director_headers(member_id: str) -> dict:
    """DistrictDirector acting as a real Member. Pass the real Member.id."""
    return build_user_headers(member_id, "DistrictDirector")
