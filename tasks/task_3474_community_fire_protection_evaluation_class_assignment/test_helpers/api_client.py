"""API client: one method per endpoint the PRD declares.

``ApiClient`` composes the three endpoint mixins over the framework's
``GenericApiClient`` (which supplies ``_request`` and reads ``API_BASE_URL``).
A module-level singleton is provided for tests that do not need a custom
base URL. Note the logical-clock endpoint lives outside the ``/ppc`` mount;
``set_clock`` deliberately calls the unprefixed path.
"""
from prd_bench_local_runner.testing import GenericApiClient

from .api_client_evaluation import EvaluationEndpoints
from .api_client_field import FieldDataEndpoints
from .api_client_insurance import InsuranceEndpoints


class ApiClient(EvaluationEndpoints, FieldDataEndpoints, InsuranceEndpoints, GenericApiClient):
    """Endpoint methods for every route the contract declares."""


api_client = ApiClient()
