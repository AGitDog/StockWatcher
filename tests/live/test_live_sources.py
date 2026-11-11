"""Every live probe of the Sunday check as a pytest case, for a quick look on the own machine:

    python -m pytest tests/live --live -q

The Sunday workflow runs the same probes through ``python system_check.py`` (report and issue).
"""
import pytest

import system_check

ALL = system_check.LIVE_PROBES + system_check.OFFLINE_CHECKS


@pytest.mark.live
@pytest.mark.parametrize("area, name, probe, hard", ALL, ids=[f"{area}: {name}" for area, name, _, _ in ALL])
def test_probe(area, name, probe, hard):
    check = system_check.run_probe(area, name, probe, hard, retries=0)
    if not check.ok and not hard:
        pytest.skip(f"Warnung: {check.detail}")
    assert check.ok, check.detail
