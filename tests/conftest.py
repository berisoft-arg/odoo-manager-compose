"""Aislamiento global: HOME fakeado por test (nunca tocar el HOME real).

Los tests que necesiten otro HOME lo pisan con su propio monkeypatch.
"""
import pytest


@pytest.fixture(autouse=True)
def _home_aislado(monkeypatch, tmp_path):
    # Sin pre-crear: algunos tests crean tmp_path/"home" ellos mismos.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for v in ("OMC_HOME", "ODOO_CREATOR_HOME", "OMC_PROJECTS"):
        monkeypatch.delenv(v, raising=False)
