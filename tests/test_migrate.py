import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc import migrate
from omc.migrate import (
    _pasos_intermedios,
    asegurar_paquete_oca,
    check_module_migrated,
    generar_compose_migracion,
    generar_script_migracion_bd,
    listar_modulos_instalados,
    migrar_codigo_modulos,
    setup_openupgradelib,
    verificar_migrabilidad,
)


def test_menu_principal_existe():
    from omc.flows import menu_principal
    assert callable(menu_principal)


def test_elegir_proyecto_existe():
    from omc.flows import elegir_proyecto
    assert callable(elegir_proyecto)


def test_pasos_intermedios():
    assert _pasos_intermedios("17", "19") == ["18", "19"]
    assert _pasos_intermedios("18", "19") == ["19"]
    assert _pasos_intermedios("18", "18") == []
    assert _pasos_intermedios("19", "18") == []


def test_check_custom_sin_red():
    r = check_module_migrated("mi_mod", "custom", "mi_mod", "17", "19")
    assert r["migrated"] is False
    assert r["branch"] == "19.0"


def _proyecto_fake(tmp_path: Path) -> Path:
    (tmp_path / "addons" / "oca" / "server-tools").mkdir(parents=True)
    (tmp_path / "addons" / "custom" / "mi_mod").mkdir(parents=True)
    (tmp_path / "addons" / "custom" / "mi_mod" / "__manifest__.py").write_text(
        "{'name': 'Mi Mod', 'version': '17.0.1.0'}", encoding="utf-8")
    (tmp_path / ".env").write_text("ODOO_VERSION=17\n", encoding="utf-8")
    (tmp_path / "addons" / "repos.json").write_text(json.dumps([
        {"org": "oca", "repo": "server-tools",
         "url": "https://github.com/OCA/server-tools",
         "branch": "17.0", "path": "addons/oca/server-tools",
         "modules": ["auditlog"]},
    ]), encoding="utf-8")
    return tmp_path


def test_listar_modulos_instalados(tmp_path):
    proj = _proyecto_fake(tmp_path)
    mods = listar_modulos_instalados(proj)
    names = {m["name"] for m in mods}
    assert names == {"auditlog", "mi_mod"}
    by_name = {m["name"]: m for m in mods}
    assert by_name["auditlog"]["org"] == "oca"
    assert by_name["mi_mod"]["org"] == "custom"


def test_verificar_migrabilidad_mock(monkeypatch, tmp_path):
    proj = _proyecto_fake(tmp_path)
    migrate._RAMAS_CACHE.clear()
    monkeypatch.setattr(migrate, "ramas_version",
                        lambda url: ["17.0", "18.0", "19.0"])
    rep = verificar_migrabilidad(proj, "17", "19")
    assert rep["total"] == 2
    assert [m["name"] for m in rep["migrados"]] == ["auditlog"]
    assert [m["name"] for m in rep["custom"]] == ["mi_mod"]
    assert rep["sin_migrar"] == []


def test_verificar_sin_rama_destino(monkeypatch, tmp_path):
    proj = _proyecto_fake(tmp_path)
    migrate._RAMAS_CACHE.clear()
    monkeypatch.setattr(migrate, "ramas_version", lambda url: ["17.0"])
    rep = verificar_migrabilidad(proj, "17", "19")
    assert [m["name"] for m in rep["sin_migrar"]] == ["auditlog"]


def test_generar_script_bd(tmp_path):
    p = generar_script_migracion_bd(tmp_path, "mi_bd", "19")
    assert p.exists()
    import os
    assert os.access(p, os.X_OK)
    txt = p.read_text(encoding="utf-8")
    assert "--update all --stop-after-init" in txt
    assert "--load=base,web,openupgrade_framework" in txt
    assert "backup.sh" in txt
    assert "-f docker-compose.yml -f docker-compose.migrate.yml" in txt


def test_generar_compose_migracion(tmp_path):
    from omc.core import sin_renderizar
    p = generar_compose_migracion(tmp_path, "19")
    assert p.name == "docker-compose.migrate.yml"
    txt = p.read_text(encoding="utf-8")
    assert sin_renderizar(txt) == []
    assert "odoo:19" in txt
    assert "services:" in txt and "odoo:" in txt


def test_migrar_codigo_sin_binario(monkeypatch, tmp_path):
    proj = _proyecto_fake(tmp_path)
    monkeypatch.setattr(migrate.shutil, "which", lambda *a, **k: None)
    r = migrar_codigo_modulos(proj, [{"name": "mi_mod",
                                      "path": str(proj / "addons" / "custom" / "mi_mod")}],
                              "17", "19")
    assert r["fallidos"] == ["mi_mod"]
    assert "no instalado" in r["motivo"]


def test_run_deps_simple_existe_y_corre(tmp_path, capsys):
    from omc.flows import run_deps_simple
    proj = _proyecto_fake(tmp_path)
    run_deps_simple(proj, enfocar=["auditlog", "mi_mod"])
    out = capsys.readouterr().out
    assert "Dependencias entre módulos" in out


def test_ensure_dockerfile_sync_genera(tmp_path):
    from omc.core import sin_renderizar
    from omc.flows import ensure_dockerfile_sync
    proj = _proyecto_fake(tmp_path)
    (proj / "requirements-odoo.txt").write_text("pyafipws\n", encoding="utf-8")
    (proj / "docker-compose.yml").write_text(
        "services:\n  odoo:\n    image: odoo:17\n", encoding="utf-8")
    assert ensure_dockerfile_sync(proj) is True
    txt = (proj / "Dockerfile").read_text(encoding="utf-8")
    assert sin_renderizar(txt) == []
    assert "build: ." in (proj / "docker-compose.yml").read_text(encoding="utf-8")


def test_ensure_dockerfile_sync_sin_requirements(tmp_path):
    from omc.flows import ensure_dockerfile_sync
    proj = _proyecto_fake(tmp_path)
    assert ensure_dockerfile_sync(proj) is False
    assert not (proj / "Dockerfile").exists()


def _herramienta_fake():
    return {"binario": "fake-tool", "paquete": "fake-pkg", "para": "tests"}


def test_asegurar_presente_no_instala(monkeypatch):
    monkeypatch.setattr(migrate.shutil, "which", lambda *a, **k: "/usr/bin/fake-tool")
    def _boom(*a, **k):
        raise AssertionError("pip no debe correrse si ya está presente")
    monkeypatch.setattr(migrate.subprocess, "run", _boom)
    assert asegurar_paquete_oca(_herramienta_fake()) is True


def test_asegurar_falta_sin_tty_sin_yes_no_instala(monkeypatch):
    monkeypatch.setattr(migrate.shutil, "which", lambda *a, **k: None)
    def _boom(*a, **k):
        raise AssertionError("pip no debe correrse sin --yes ni tty")
    monkeypatch.setattr(migrate.subprocess, "run", _boom)
    assert asegurar_paquete_oca(_herramienta_fake()) is False


def test_asegurar_falta_con_yes_instala(monkeypatch):
    from argparse import Namespace
    llamadas = []
    estado = {"which": None}
    monkeypatch.setattr(migrate.shutil, "which", lambda *a, **k: estado["which"])
    class _R:
        returncode = 0
        stderr = ""
    def _fake_run(*a, **k):
        llamadas.append(a)
        estado["which"] = "/usr/bin/fake-tool"  # aparece tras instalar
        return _R()
    monkeypatch.setattr(migrate.subprocess, "run", _fake_run)
    assert asegurar_paquete_oca(_herramienta_fake(), Namespace(yes=True)) is True
    assert len(llamadas) == 1
    assert "fake-pkg" in llamadas[0][0]


def test_setup_openupgradelib_ya_presente_no_reinstala(monkeypatch):
    monkeypatch.setattr(migrate, "_hay_modulo", lambda *a, **k: True)
    def _boom(*a, **k):
        raise AssertionError("pip no debe correrse si ya está importable")
    monkeypatch.setattr(migrate.subprocess, "run", _boom)
    assert setup_openupgradelib() is True


def test_setup_openupgradelib_pip_falla(monkeypatch):
    monkeypatch.setattr(migrate, "_hay_modulo", lambda *a, **k: False)
    class _R:
        returncode = 1
        stderr = "ERROR: no existe"
    monkeypatch.setattr(migrate.subprocess, "run", lambda *a, **k: _R())
    assert setup_openupgradelib() is False
