import json
import sys
from pathlib import Path

# para imports editable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.core import render, template_text, sin_renderizar, merge_json
from omc import flows as _flows


def test_vscode_templates_sin_residuos():
    for tpl in ["vscode-settings.json.tpl", "vscode-extensions.json.tpl",
                "vscode-launch.json.tpl", "vscode-tasks.json.tpl", "opencode.json.tpl"]:
        txt = template_text(tpl)
        out = render(txt, {"PROYECTO": "demo", "ODOO_VERSION": "18"})
        assert sin_renderizar(out) == [], f"{tpl} quedó con placeholders: {sin_renderizar(out)}"
        # debe ser jsonc parseable (quitamos //)
        lines = [l for l in out.splitlines() if not l.strip().startswith("//")]
        clean = "\n".join(lines)
        import re
        clean = re.sub(r",\s*([}\]])", r"\1", clean)
        data = json.loads(clean)
        assert isinstance(data, dict)
        if tpl == "vscode-extensions.json.tpl":
            assert "anomalyco.opencode" in clean


def test_merge_json():
    base = {"a": 1, "lst": [1, 2], "d": {"x": 1}}
    nuevo = {"a": 2, "lst": [2, 3], "d": {"y": 2}, "b": 1}
    out = merge_json(base, nuevo)
    assert out["a"] == 2
    assert out["lst"] == [1, 2, 3]
    assert out["d"] == {"x": 1, "y": 2}
    assert out["b"] == 1


def test_generar_vscode(tmp_path, monkeypatch):
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / ".env").write_text("ODOO_VERSION=18\nENTORNO=desarrollo\n", encoding="utf-8")
    mapping = {"PROYECTO": "demo", "ODOO_VERSION": "18", "ENTORNO": "desarrollo"}
    creados = _flows.generar_vscode(proj, mapping, ide="auto", instalar=False)
    assert (proj / ".vscode" / "settings.json").exists()
    assert (proj / ".vscode" / "extensions.json").exists()
    assert (proj / ".vscode" / "launch.json").exists()
    assert (proj / ".vscode" / "tasks.json").exists()
    assert (proj / "opencode.json").exists()
    assert any(".vscode/settings.json" in c for c in creados)
    # segundo llamado no pisa, hace merge
    (proj / ".vscode" / "settings.json").write_text('{"custom": 1}', encoding="utf-8")
    _flows.generar_vscode(proj, mapping, ide="auto", instalar=False)
    txt = (proj / ".vscode" / "settings.json").read_text(encoding="utf-8")
    assert '"custom": 1' in txt or '"custom":1' in txt
    # debe contener merge de odoo.version
    assert "odoo.version" in txt


def test_generar_vscode_prod_solo_con_force(tmp_path, monkeypatch):
    proj = tmp_path / "prod"
    proj.mkdir()
    (proj / ".env").write_text("ODOO_VERSION=18\nENTORNO=produccion\n", encoding="utf-8")
    mapping = {"PROYECTO": "prod", "ODOO_VERSION": "18", "ENTORNO": "produccion"}
    creados = _flows.generar_vscode(proj, mapping, ide="auto", instalar=False)
    assert creados == []
    assert not (proj / ".vscode").exists() or not any((proj / ".vscode").iterdir())
    assert not (proj / "opencode.json").exists()
    # con --force solo opencode.json en modo terminal
    creados2 = _flows.generar_vscode(proj, mapping, ide="auto", instalar=False, force=True)
    assert any("opencode.json" in c for c in creados2)
    assert (proj / "opencode.json").exists()
    assert not (proj / ".vscode" / "settings.json").exists()


def test_detectar_ide_bin(monkeypatch):
    monkeypatch.setattr("omc.flows.shutil.which", lambda x: "/usr/bin/codium" if x == "codium" else None)
    assert _flows._detectar_ide_bin("auto") == "codium"
    monkeypatch.setattr("omc.flows.shutil.which", lambda x: "/usr/bin/code" if x == "code" else None)
    assert _flows._detectar_ide_bin("auto") == "code"
    monkeypatch.setattr("omc.flows.shutil.which", lambda x: None)
    assert _flows._detectar_ide_bin("auto") is None


def test_cli_dev_parser():
    from omc.cli import build_parser
    p = build_parser()
    args = p.parse_args(["dev", "--proyecto", "/tmp/x", "--ide", "codium"])
    assert args.cmd == "dev"
    assert args.ide == "codium"
    args2 = p.parse_args(["ide", "--proyecto", "/tmp/x"])
    assert args2.cmd == "ide"
    args3 = p.parse_args(["crear", "--ide", "vscode"])
    assert args3.ide == "vscode"
    args4 = p.parse_args(["crear", "--ide", "codium", "--force"])
    assert args4.force is True
    args5 = p.parse_args(["dev", "--proyecto", "/tmp/x", "--force"])
    assert args5.force is True


def test_menu_13_es_dev(monkeypatch):
    # forzar fallback numérico: que elegir_interactivo falle
    import omc.tui as _tui
    monkeypatch.setattr(_tui, "elegir_interactivo", lambda *a, **k: (_ for _ in ()).throw(Exception("no tty")))
    monkeypatch.setattr("omc.flows.es_interactivo", lambda: False)
    monkeypatch.setattr(_flows, "ask_texto", lambda prompt, default: "13")
    assert _flows.menu_principal() == "dev"
    monkeypatch.setattr(_flows, "ask_texto", lambda prompt, default: "0")
    assert _flows.menu_principal() == "salir"


def test_agents_dev_render():
    txt = template_text("agents-proyecto.md.tpl")
    out = render(txt, {"PROYECTO": "demo", "ODOO_VERSION": "18", "MAILPIT_PORT": "8025"})
    assert sin_renderizar(out) == []
    assert "VSCodium" in out or "VS Code" in out
    assert "My Odoo Webkit" in out
    assert "my-odoo-webkit" in out
