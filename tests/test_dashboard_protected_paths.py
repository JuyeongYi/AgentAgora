"""Single-source regression for the dashboard protected-paths list.

The list was previously copy-pasted in __main__ + two test modules and could
drift. It now lives once in dashboard_routes; this pins its canonical contents
and the query-param subset.
"""
from agent_agora.dashboard import (
    DASHBOARD_PROTECTED_PATHS,
    DASHBOARD_QUERY_PARAM_PATHS,
)


def test_protected_paths_canonical_contents():
    assert DASHBOARD_PROTECTED_PATHS == [
        "/dashboard/data",
        "/dashboard/dispatch",
        "/dashboard/broadcast",
        "/dashboard/operator",
        "/dashboard/conversation",
        "/dashboard/instance",
        "/dashboard/schemas",
        "/dashboard/coverage",
        "/dashboard/stream",
    ]


def test_stream_is_query_param_path_and_subset():
    assert DASHBOARD_QUERY_PARAM_PATHS == ["/dashboard/stream"]
    # query-param paths must be a subset of protected paths
    assert set(DASHBOARD_QUERY_PARAM_PATHS) <= set(DASHBOARD_PROTECTED_PATHS)
