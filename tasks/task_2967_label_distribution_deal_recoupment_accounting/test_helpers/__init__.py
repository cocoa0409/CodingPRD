"""
Test infrastructure for the Label Distribution Recoupment API.

Import anything from the package root::

    from test_helpers import (
        ApiClient, LABEL_ADMIN, ERR_INVALID_DEAL_STATE,
        given_executed_deal, assert_fields_money,
    )
    from test_helpers import factories as f

The submodules stay importable under their own names as well, which is how the
payload builders are normally reached (``f.deal_payload(...)``) since their names
would otherwise crowd the root namespace.

Layout:

  ``constants``   - roles, enum members, ranges, quanta and derived-status tuples.
  ``api_errors``  - the 45 error ids of PRD Section 5 plus their HTTP status map,
                    which is registered with the runner on import.
  ``types``       - TypedDicts for the eleven record types.
  ``api_client``  - one method per PRD Section 4 endpoint row; serialises
                    percentages with their exact written decimal places.
  ``test_users``  - ready-made and constructible auth headers per role.
  ``assertions``  - domain assertions (money, percentages, instants, envelopes,
                    listings, conserved quantities).
  ``factories``   - request-payload builders.
  ``fixtures``    - ``mk_*`` / ``do_*`` / ``read_*`` primitives and ``given_*``
                    composites that build preconditions from an empty database.

The re-exports below are deliberately star imports: several modules legitimately
share a name (``LABEL_ADMIN`` is the same object in ``test_users`` and
``fixtures``, ``TIER_PREMIUM`` the same string in three places), so a flat
namespace is unambiguous, and listing ~350 names by hand would only rot.
"""

from . import api_client, api_errors, assertions, constants, factories
from . import fixtures, test_users, types

from .api_client import *  # noqa: F401,F403
from .api_errors import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
