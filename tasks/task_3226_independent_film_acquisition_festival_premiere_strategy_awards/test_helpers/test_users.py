"""Pre-built role headers for every role in the PRD.

Every role's X-User-ID is an opaque operator identifier (PRD §2.1) — never
compared to any entity id. Segregation-of-duties checks compare X-User-ID
strings between the creator and the acceptor/submitter, so we provide at
least two distinct identities for AcquisitionExec and AwardsStrategist.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "acq_exec_headers": build_user_headers("acq-exec-1", "AcquisitionExec"),
    "acq_exec_2_headers": build_user_headers("acq-exec-2", "AcquisitionExec"),
    "festival_prog_headers": build_user_headers("fest-prog-1", "FestivalProgrammer"),
    "dist_exec_headers": build_user_headers("dist-exec-1", "DistributionExec"),
    "awards_strat_headers": build_user_headers("awards-strat-1", "AwardsStrategist"),
    "awards_strat_2_headers": build_user_headers("awards-strat-2", "AwardsStrategist"),
    "talent_coord_headers": build_user_headers("talent-coord-1", "TalentCoordinator"),
    "part_acct_headers": build_user_headers("part-acct-1", "ParticipationAccountant"),
}


def make_acq_exec_headers(user_id: str) -> dict:
    """AcquisitionExec headers with an explicit operator id."""
    return build_user_headers(user_id, "AcquisitionExec")


def make_awards_strategist_headers(user_id: str) -> dict:
    """AwardsStrategist headers with an explicit operator id."""
    return build_user_headers(user_id, "AwardsStrategist")
