"""Caller identities and pre-built role headers.

PRD section 2.1 splits identity in two.  For ``SupplyChainDirector``,
``CommissaryPlanner``, ``QualityAuditor``, ``RealEstatePlanner``, and
``HRDirector`` the ``X-User-ID`` is an opaque operator identifier that the
server records (for example as ``posted_by_id`` on a manager posting) but
never compares against an entity ``id`` — those headers are constants below.
For ``StoreManager`` and ``Associate`` the ``X-User-ID`` IS the ``id`` of the
acting Associate, so their headers can only be built once the associate row
exists; use :func:`make_associate_headers` / :func:`make_store_manager_headers`
with the real associate id, never the opaque constants, on ownership-gated
calls.

Segregation of duties (PRD section 3.7) needs at least two distinct HRDirector
ids — the poster of a manager posting may not close it — hence
``HR_POSTER_USER_ID`` and ``HR_CLOSER_USER_ID``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSOCIATE,
    ROLE_COMMISSARY_PLANNER,
    ROLE_HR_DIRECTOR,
    ROLE_QUALITY_AUDITOR,
    ROLE_REAL_ESTATE_PLANNER,
    ROLE_STORE_MANAGER,
    ROLE_SUPPLY_CHAIN_DIRECTOR,
)

# ─── Opaque operator identifiers (PRD section 2.1) ─────────────────────────

SCD_USER_ID = "scd-1"
PLANNER_USER_ID = "planner-1"
AUDITOR_USER_ID = "auditor-1"
PLANNER_RE_USER_ID = "re-planner-1"
HR_POSTER_USER_ID = "hr-poster-1"
HR_CLOSER_USER_ID = "hr-closer-1"


def scd_headers():
    """SupplyChainDirector (opaque identity)."""
    return build_user_headers(SCD_USER_ID, ROLE_SUPPLY_CHAIN_DIRECTOR)


def planner_headers():
    """CommissaryPlanner (opaque identity)."""
    return build_user_headers(PLANNER_USER_ID, ROLE_COMMISSARY_PLANNER)


def auditor_headers():
    """QualityAuditor (opaque identity)."""
    return build_user_headers(AUDITOR_USER_ID, ROLE_QUALITY_AUDITOR)


def real_estate_headers():
    """RealEstatePlanner (opaque identity)."""
    return build_user_headers(PLANNER_RE_USER_ID, ROLE_REAL_ESTATE_PLANNER)


def hr_poster_headers():
    """HRDirector identity used to POST a manager posting (the poster)."""
    return build_user_headers(HR_POSTER_USER_ID, ROLE_HR_DIRECTOR)


def hr_closer_headers():
    """HRDirector identity used to CLOSE a manager posting (must differ from
    the poster per the segregation-of-duties rule in PRD section 3.7)."""
    return build_user_headers(HR_CLOSER_USER_ID, ROLE_HR_DIRECTOR)


def make_associate_headers(associate_id: str):
    """Associate headers whose X-User-ID is the real Associate.id — mandatory
    for ownership-gated calls (placing/serving/cancelling orders, applying to
    and withdrawing from postings)."""
    return build_user_headers(associate_id, ROLE_ASSOCIATE)


def make_store_manager_headers(associate_id: str):
    """StoreManager headers whose X-User-ID is the real Associate.id of the
    store's manager — mandatory for begin/end opening surge and shift
    management, where the server compares the store's manager reference
    against X-User-ID (PRD section 2.1)."""
    return build_user_headers(associate_id, ROLE_STORE_MANAGER)
