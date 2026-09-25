import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.flows import (
    _activar_https,
    _certonly_cmd,
    _elegir_modo_web,
    aplicar_localizacion,
    bloques_localizacion,
    ensure_dockerfile_sync,
    es_prod,
    exigir_prod,
    modo_configurar_web,
    run_backup,
    run_deps,
    run_restore,
    run_sync,
    run_web,
    run_rclone,
    run_monitor,
    menu_principal,
    _monitor_cmd,
    _monitor_service_info,
    _resolver_proyecto,
)
from omc.addons_cli import _parse


def _proj_dev(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / ".env").write_text("ENTORNO=desarrollo\nODOO_VERSION=18\n", encoding="utf-8")
    return p


def test_es_prod_y_exigir(tmp_path):
    dev = _proj_dev(tmp_path)
    assert not es_prod(dev)
    assert exigir_prod(dev, "Backup") is False
    (dev / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    assert es_prod(dev)
    assert exigir_prod(dev, "Backup") is True


def test_run_backup_dev_no_ejecuta(capsys, tmp_path):
    run_backup(SimpleNamespace(proyecto=str(_proj_dev(tmp_path))))
    assert "solo de producción" in capsys.readouterr().out


def test_run_restore_sin_script_avisa(capsys, tmp_path):
    proj = _proj_dev(tmp_path)
    (proj / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    run_restore(SimpleNamespace(proyecto=str(proj)))
    assert "no existe" in capsys.readouterr().out


def test_run_sync_resumen_faltantes(monkeypatch, tmp_path, capsys):
    import json as _json
    import subprocess as _sp
    import omc.flows as F
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps([
        {"org": "oca", "repo": "server-tools", "url": "https://x/y",
         "branch": "18.0", "path": "addons/oca/server-tools",
         "modules": ["auditlog", "desaparecido"]},
        {"org": "oca", "repo": "vacío", "url": "https://x/z",
         "branch": "18.0", "path": "addons/oca/vacio", "modules": []},
    ]), encoding="utf-8")
    (p / "addons" / "oca" / "server-tools" / "auditlog").mkdir(parents=True)
    monkeypatch.setattr(F, "run_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "run_check_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "actualizar_bundle_desde_estado", lambda *a, **k: False)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    run_sync(SimpleNamespace(proyecto=str(p), bundle="", odoo="", branch="",
                             yes=True, skip_install=True, no_deploy=False))
    out = capsys.readouterr().out
    assert "server-tools/desaparecido" in out
    assert "no descargados" in out


def test_run_sync_avisa_drift(monkeypatch, tmp_path, capsys):
    import json as _json
    import subprocess as _sp
    import omc.flows as F
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps([
        {"org": "oca", "repo": "server-tools", "url": "https://x/y",
         "branch": "18.0", "path": "addons/oca/server-tools",
         "modules": ["auditlog"], "sha": "a" * 40},
    ]), encoding="utf-8")
    (p / "addons" / "oca" / "server-tools" / "auditlog").mkdir(parents=True)
    monkeypatch.setattr(F, "run_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "run_check_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "actualizar_bundle_desde_estado", lambda *a, **k: False)
    monkeypatch.setattr(F, "remote_head", lambda *a, **k: "b" * 40)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    run_sync(SimpleNamespace(proyecto=str(p), bundle="", odoo="", branch="",
                             yes=True, skip_install=True, no_deploy=False))
    out = capsys.readouterr().out
    assert "cambios upstream" in out
    assert "omc addons pull" in out


def test_run_sync_no_descargar_no_muestra_deps(monkeypatch, tmp_path, capsys):
    import subprocess as _sp
    import omc.flows as F
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(F, "ask_si_no", lambda *a, **k: False)
    monkeypatch.setattr(F, "solo_install", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamarse")))
    run_sync(SimpleNamespace(proyecto=str(p), bundle="", odoo="", branch="", yes=False, skip_install=False, no_deploy=False))
    out = capsys.readouterr().out
    assert "== Dependencias ==" not in out
    assert "Aplicar" not in out


def test_run_sync_nada_no_muestra_deps(monkeypatch, tmp_path, capsys):
    import json as _json
    import subprocess as _sp
    import omc.flows as F
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    # ask_si_no "¿Descargar...?" -> True, pero solo_install devuelve False (Nada)
    calls = []
    def _ask(prompt, **k):
        calls.append(prompt)
        if "Descargar" in prompt:
            return True
        return False
    def _fake_solo(*a, **k):
        print("\nSin cambios, no hay nada que aplicar.")
        return False
    monkeypatch.setattr(F, "ask_si_no", _ask)
    monkeypatch.setattr(F, "solo_install", _fake_solo)
    monkeypatch.setattr(F, "actualizar_bundle_desde_estado", lambda *a, **k: False)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    run_sync(SimpleNamespace(proyecto=str(p), bundle="", odoo="", branch="", yes=False, skip_install=False, no_deploy=False))
    out = capsys.readouterr().out
    assert "Sin cambios" in out
    assert "== Dependencias ==" not in out
    assert "Aplicar cambios" not in out


def test_run_sync_con_novedad_una_sola_pregunta(monkeypatch, tmp_path, capsys):
    import json as _json
    import subprocess as _sp
    import omc.flows as F
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
    # Simular que solo_install cambió algo y nuevo repo aparece
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    def _solo(*a, **k):
        (p / "addons" / "repos.json").write_text(_json.dumps([{"path": "addons/oca/a", "modules": ["m1"]}] ), encoding="utf-8")
        (p / "addons" / "oca" / "a" / "m1").mkdir(parents=True, exist_ok=True)
        return True
    monkeypatch.setattr(F, "solo_install", _solo)
    preguntas = []
    orig_ask = F.ask_si_no
    def _ask2(prompt, **k):
        preguntas.append(prompt)
        if "Descargar" in prompt:
            return True
        if "Aplicar cambios" in prompt:
            return True
        return orig_ask(prompt, **k)
    monkeypatch.setattr(F, "ask_si_no", _ask2)
    monkeypatch.setattr(F, "run_check_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "run_deps_simple", lambda *a, **k: None)
    monkeypatch.setattr(F, "run_deps", lambda *a, **k: None)
    monkeypatch.setattr(F, "actualizar_bundle_desde_estado", lambda *a, **k: False)
    monkeypatch.setattr(F, "asegurar_queue_job_conf", lambda *a, **k: None)
    monkeypatch.setattr(F, "ensure_dockerfile_sync", lambda *a: False)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    run_sync(SimpleNamespace(proyecto=str(p), bundle="", odoo="", branch="", yes=False, skip_install=False, no_deploy=False))
    # Solo una pregunta de aplicar, no dos
    aplicar = [q for q in preguntas if "Aplicar" in q]
    assert len(aplicar) == 1
    assert "cambios" in aplicar[0].lower()


def _proj_json(tmp_path, nombre="tienda", env_extra=""):
    base = tmp_path / "projs"
    base.mkdir(exist_ok=True)
    p = base / nombre
    p.mkdir(exist_ok=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / ".env").write_text(
        "ENTORNO=produccion\nODOO_VERSION=18\nODOO_IMAGE=odoo:18\n"
        "POSTGRES_IMAGE=postgres:16\nODOO_PORT=8070\n" + env_extra,
        encoding="utf-8")
    (p / "config").mkdir(exist_ok=True)
    (p / "config" / "odoo.conf").write_text("[options]\n", encoding="utf-8")
    (p / "addons").mkdir(exist_ok=True)
    (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
    return base, p


def test_menu_12_es_migrar_vps(monkeypatch, capsys):
    from omc.flows import menu_principal
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "12")
    assert menu_principal() == "migrar_vps"
    out = capsys.readouterr().out
    assert "12 -" in out and "Migrar instancia a otro VPS" in out


def test_cli_migrar_vps_flags():
    from omc.cli import build_parser
    assert build_parser().parse_args(["migrar-vps"]).todo is False
    assert build_parser().parse_args(["migrar-vps", "--todo"]).todo is True
    assert build_parser().parse_args(["migrar-vps", "--consistente"]).consistente is True


def test_migrar_vps_paquete(monkeypatch, tmp_path, capsys):
    import tarfile
    from omc.flows import run_migrar_vps
    base = tmp_path / "projs"
    base.mkdir()
    for name in ("a", "b"):
        p = base / name
        p.mkdir()
        (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        (p / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
        (p / "scripts").mkdir()
        (p / "scripts" / "backup.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (p / "backups").mkdir()
        (p / "backups" / "full_backup_midb_day1.tar.gz").write_text("x", encoding="utf-8")
        (p / "addons-bundle.json").write_text("{}", encoding="utf-8")
        (p / "addons").mkdir()
        (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
        (p / "config").mkdir()
        (p / "config" / "odoo.conf").write_text("[x]\n", encoding="utf-8")
    # proxy no debe entrar
    (base / "proxy").mkdir()
    (base / "proxy" / "docker-compose.yml").write_text("x", encoding="utf-8")
    monkeypatch.setenv("OMC_PROJECTS", str(base))
    monkeypatch.delenv("OMC_HOME", raising=False)
    # stub subprocess: psql lista una BD, backup ok, stop/start ok
    import subprocess as _sp
    def _fake(cmd, **k):
        if "psql" in cmd:
            return SimpleNamespace(returncode=0, stdout="midb\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(_sp, "run", _fake)
    # para todo: debe generar paquete con a y b
    run_migrar_vps(SimpleNamespace(proyecto=None, todo=True, consistente=False))
    outs = list(base.glob("migrar_*.tar.gz"))
    assert len(outs) == 1
    with tarfile.open(outs[0]) as tf:
        names = tf.getnames()
        assert any("a/full_backup" in n for n in names)
        assert any("b/full_backup" in n for n in names)
        assert not any("proxy" in n for n in names)
        assert "MANIFEST.json" in names
    capsys.readouterr()


def test_list_json_valido(monkeypatch, tmp_path, capsys):
    import json as _json
    from omc.flows import run_list
    base, _p = _proj_json(tmp_path)
    monkeypatch.setenv("OMC_PROJECTS", str(base))
    monkeypatch.delenv("OMC_HOME", raising=False)
    run_list(SimpleNamespace(json=True))
    data = _json.loads(capsys.readouterr().out)
    assert data == [{"nombre": "tienda", "odoo": "18", "puerto": "8070",
                     "entorno": "produccion", "dominio": ""}]


def test_doctor_json_y_exit_code(monkeypatch, tmp_path, capsys):
    import json as _json
    import pytest
    from omc.flows import run_doctor
    base, p = _proj_json(tmp_path)
    monkeypatch.setenv("OMC_PROJECTS", str(base))
    monkeypatch.delenv("OMC_HOME", raising=False)
    monkeypatch.setattr("omc.flows.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    run_doctor(SimpleNamespace(proyecto=str(p), fix=False, json=True))
    data = _json.loads(capsys.readouterr().out)
    assert data == [{"proyecto": "tienda", "ok": True, "errores": []}]
    (p / "config" / "odoo.conf").unlink()  # romper
    with pytest.raises(SystemExit) as e:
        run_doctor(SimpleNamespace(proyecto=str(p), fix=False, json=True))
    assert e.value.code == 2
    data = _json.loads(capsys.readouterr().out)
    assert data[0]["ok"] is False and data[0]["errores"] != []
    # modo texto también sale 2 (agentes sin --json)
    with pytest.raises(SystemExit) as e2:
        run_doctor(SimpleNamespace(proyecto=str(p), fix=False, json=False))
    assert e2.value.code == 2
    assert "hay errores" in capsys.readouterr().out


def test_cli_list_doctor_json_flags():
    from omc.cli import build_parser
    assert build_parser().parse_args(["list", "--json"]).json is True
    assert build_parser().parse_args(["list"]).json is False
    assert build_parser().parse_args(["doctor", "--json"]).json is True


def test_run_web_y_rclone_dev_no_ejecutan(capsys, tmp_path):
    dev = str(_proj_dev(tmp_path))
    run_web(SimpleNamespace(proyecto=dev))
    run_rclone(SimpleNamespace(proyecto=dev))
    out = capsys.readouterr().out
    assert out.count("solo de producción") == 2


def test_monitor_cmd_devuelve_lista():
    cmd = _monitor_cmd()
    assert isinstance(cmd, list) and cmd


def _unit_monitor(home, token="TOK-SERVICIO-123", port=8765, host="127.0.0.1"):
    d = home / ".config" / "systemd" / "user"
    d.mkdir(parents=True)
    (d / "omc-monitor.service").write_text(
        "[Service]\nEnvironment=OMC_HOME=/opt/omc\n"
        f"Environment=ODOO_WEB_TOKEN={token}\n"
        f"ExecStart=/root/.venv/omc/bin/omc-monitor --host {host} --port {port}\n",
        encoding="utf-8")


def test_monitor_service_info_lee_unit(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _monitor_service_info() is None  # sin unit
    _unit_monitor(tmp_path, port=9999)
    monkeypatch.setattr("omc.flows.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    info = _monitor_service_info()
    assert info["token"] == "TOK-SERVICIO-123" and info["port"] == 9999
    assert info["host"] == "127.0.0.1" and info["activo"] is True


def test_run_monitor_muestra_servicio_y_vuelve(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    _unit_monitor(tmp_path)
    monkeypatch.setattr("omc.flows.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "5")  # Volver
    run_monitor(SimpleNamespace())
    out = capsys.readouterr().out
    assert "TOK-SERVICIO-123" in out and "8765" in out


def test_menu_principal_muestra_tip_monitor(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    assert menu_principal() == "salir"
    out = capsys.readouterr().out
    # Tip removido por diseño
    assert "Tip:" not in out
    assert "opción 6" not in out
    assert "11 -" in out


def test_menu_opcion_11_es_proxy(monkeypatch, capsys):
    from omc.flows import menu_principal
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "11")
    assert menu_principal() == "proxy"
    out = capsys.readouterr().out
    assert "11 -" in out and "Proxy multinstancia" in out


def test_run_proxy_init_crea_proyecto(monkeypatch, tmp_path, capsys):
    from omc.core import sin_renderizar
    from omc.flows import run_proxy_init
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    class _R:
        def __init__(self, rc=0):
            self.returncode = rc
    llamadas = []
    def _fake(cmd, **k):
        llamadas.append(cmd)
        if cmd[:3] == ["docker", "network", "inspect"]:
            return _R(1)  # red no existe -> crear
        return _R(0)
    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    root = run_proxy_init()
    assert root == (tmp_path / "proxy").resolve()
    comp = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"80:80"' in comp and '"443:443"' in comp
    assert "omc-proxy:\n    external: true" in comp
    assert "./conf.d:/etc/nginx/conf.d/:ro" in comp
    assert sin_renderizar(comp) == []
    env = (root / ".env").read_text(encoding="utf-8")
    assert "PROYECTO=proxy" in env and "ENTORNO=infraestructura" in env
    assert (root / "conf.d").is_dir() and (root / "letsencrypt").is_dir()
    assert (root / "certbot-www").is_dir()
    assert (root / "conf.d" / "gzip.conf").exists()
    assert "letsencrypt/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert any(c[:3] == ["docker", "network", "create"] for c in llamadas)
    assert ["docker", "compose", "up", "-d"] in llamadas
    out = capsys.readouterr().out
    assert "Proxy central en:" in out


def test_run_proxy_init_idempotente(monkeypatch, tmp_path, capsys):
    from omc.flows import run_proxy_init
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    class _R:
        def __init__(self, rc=0):
            self.returncode = rc
    llamadas = []
    def _fake(cmd, **k):
        llamadas.append(cmd)
        if cmd[:3] == ["docker", "network", "inspect"]:
            return _R(0)  # red ya existe -> no crear
        return _R(0)
    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    run_proxy_init()
    run_proxy_init()  # segunda corrida no falla ni duplica
    assert not any(c[:3] == ["docker", "network", "create"] for c in llamadas)
    assert llamadas.count(["docker", "compose", "up", "-d"]) == 2
    capsys.readouterr()


def test_run_proxy_delega_init(monkeypatch, tmp_path):
    import omc.flows as F
    from omc.flows import run_proxy
    vistos = []
    monkeypatch.setattr(F, "run_proxy_init", lambda salida=None: vistos.append(salida))
    run_proxy()
    run_proxy(SimpleNamespace(salida="/x/proxy"))
    assert vistos == [None, "/x/proxy"]


def test_dispatch_proxy_no_pide_proyecto(monkeypatch, capsys, tmp_path):
    from omc.cli import _ejecutar_accion_menu
    import omc.flows as F
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)

    def _boom(*a, **k):
        raise AssertionError("no debe pedir input")

    monkeypatch.setattr("builtins.input", _boom)
    monkeypatch.setattr(F, "run_proxy_init", lambda salida=None: print("init-ok"))
    _ejecutar_accion_menu("proxy")  # sin elegir proyecto, sin colgarse
    assert "init-ok" in capsys.readouterr().out


def test_cli_proxy_init_parser():
    from omc.cli import build_parser
    args = build_parser().parse_args(["proxy"])
    assert args.cmd == "proxy" and args.accion == "init" and args.salida is None
    args = build_parser().parse_args(["proxy", "init", "--salida", "/x"])
    assert args.accion == "init" and args.salida == "/x"


def test_cli_web_proxy_flags():
    import pytest
    from omc.cli import build_parser
    args = build_parser().parse_args(["web", "--proxy", "--proyecto", "X"])
    assert args.proxy is True and args.standalone is False
    args = build_parser().parse_args(["web", "--standalone"])
    assert args.standalone is True and args.proxy is False
    args = build_parser().parse_args(["web"])
    assert args.proxy is False and args.standalone is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["web", "--proxy", "--standalone"])


def _proj_web_prod(tmp_path):
    p = tmp_path / "tienda"
    p.mkdir()
    (p / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    image: postgres:16\n"
        "  odoo:\n"
        "    image: odoo:18\n"
        "    restart: always\n"
        '    ports:\n      - "8070:8069"\n'
        "    environment:\n"
        "      - HOST=db\n"
        "volumes:\n"
        "  odoo-db-data:\n",
        encoding="utf-8")
    (p / ".env").write_text(
        "ENTORNO=produccion\nODOO_VERSION=18\nODOO_IMAGE=odoo:18\nODOO_PORT=8070\n",
        encoding="utf-8")
    (p / "config").mkdir()
    (p / "config" / "odoo.conf").write_text("[options]\n", encoding="utf-8")
    return p


def _proxy_vacio(tmp_path):
    from pathlib import Path as _P
    root = _P(tmp_path) / "proxy"
    (root / "conf.d").mkdir(parents=True)
    (root / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    return root


class _RC:
    def __init__(self, rc=0):
        self.returncode = rc


def _ns_web(proyecto, **kw):
    base = dict(proyecto=str(proyecto), dominio="tienda.com", email="yo@x.com",
                staging=False, proxy=False, standalone=False, no_input=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_elegir_modo_web_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    ns = SimpleNamespace(proxy=False, standalone=False, no_input=True)
    assert _elegir_modo_web(ns, tmp_path) is False  # sin proxy: clásico
    _proxy_vacio(tmp_path)
    assert _elegir_modo_web(ns, tmp_path) is True  # con proxy: central
    assert _elegir_modo_web(SimpleNamespace(proxy=True, standalone=False,
                                            no_input=True), tmp_path) is True
    assert _elegir_modo_web(SimpleNamespace(proxy=False, standalone=True,
                                            no_input=True), tmp_path) is False


def test_elegir_modo_web_pregunta(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    _proxy_vacio(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")  # default
    ns = SimpleNamespace(proxy=False, standalone=False, no_input=False)
    assert _elegir_modo_web(ns, tmp_path) is True  # default = proxy (hay proxy)
    capsys.readouterr()
    (tmp_path / "proxy" / "docker-compose.yml").unlink()
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    assert _elegir_modo_web(ns, tmp_path) is False  # default = standalone
    capsys.readouterr()


def test_web_proxy_completo(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    proxy = _proxy_vacio(tmp_path)
    llamadas = []

    def _fake(cmd, **k):
        llamadas.append((list(cmd), k.get("cwd", "")))
        return _RC(0)

    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    modo_configurar_web(_ns_web(p, proxy=True))
    out = capsys.readouterr().out
    # site en el proxy con resolver (sin upstream estático)
    sitio = proxy / "conf.d" / "tienda.com.conf"
    txt = sitio.read_text(encoding="utf-8")
    assert "server_name tienda.com www.tienda.com;" in txt
    assert "proxy_pass http://$up;" in txt
    assert "set $up tienda-odoo:8069;" in txt
    assert "upstream {" not in txt
    assert "{{" not in txt
    # compose del sitio parcheado
    comp = (p / "docker-compose.yml").read_text(encoding="utf-8")
    assert "container_name: tienda-odoo" in comp
    assert "omc-proxy:\n    external: true" in comp
    assert '"8070:8069"' not in comp
    assert "proxy_mode = True" in (p / "config" / "odoo.conf").read_text(
        encoding="utf-8")
    # .env persistido
    env = (p / ".env").read_text(encoding="utf-8")
    assert "DOMINIO=tienda.com" in env and "CERTBOT_EMAIL=yo@x.com" in env
    # certonly central: comando exacto con cwd=proxy
    certs = [c for c, _ in llamadas if "certbot" in c]
    assert len(certs) == 1
    assert certs[0][:9] == ["docker", "compose", "run", "--rm", "certbot",
                            "certonly", "--webroot", "-w", "/var/www/certbot"]
    assert "-d" in certs[0] and "tienda.com" in certs[0] and "www.tienda.com" in certs[0]
    assert "--staging" not in certs[0]
    assert [cwd for c, cwd in llamadas if "certbot" in c] == [str(proxy)]
    # nginx -t antes del reload
    idx_t = next(i for i, (c, _) in enumerate(llamadas) if c[-2:] == ["nginx", "-t"])
    idx_r = next(i for i, (c, _) in enumerate(llamadas)
                 if c[-3:] == ["nginx", "-s", "reload"])
    assert idx_t < idx_r
    assert "cron semanal en host" in out and "https://tienda.com" in out


def test_web_proxy_sin_init_falla_limpio(monkeypatch, tmp_path, capsys):
    import pytest
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    antes = (p / "docker-compose.yml").read_text(encoding="utf-8")

    def _boom(*a, **k):
        raise AssertionError("sin proxy no debe llamar a docker")

    monkeypatch.setattr("omc.flows.subprocess.run", _boom)
    with pytest.raises(SystemExit) as e:
        modo_configurar_web(_ns_web(p, proxy=True))
    assert "omc proxy init" in str(e.value.code)
    assert (p / "docker-compose.yml").read_text(encoding="utf-8") == antes
    assert not (tmp_path / "proxy").exists()
    capsys.readouterr()


def test_web_proxy_rechaza_nginx_local(monkeypatch, tmp_path, capsys):
    import pytest
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    with open(p / "docker-compose.yml", "a", encoding="utf-8") as f:
        f.write("\n  nginx:\n    image: nginx:alpine\n")
    antes = (p / "docker-compose.yml").read_text(encoding="utf-8")
    _proxy_vacio(tmp_path)
    llamadas = []

    def _fake(cmd, **k):
        llamadas.append(list(cmd))
        return _RC(0)

    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    with pytest.raises(SystemExit) as e:
        modo_configurar_web(_ns_web(p, proxy=True))
    assert "80/443" in str(e.value.code)
    assert (p / "docker-compose.yml").read_text(encoding="utf-8") == antes
    assert not any("certbot" in c for c in llamadas)
    capsys.readouterr()


def test_web_proxy_puertos_ocupados(monkeypatch, tmp_path, capsys):
    import pytest
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    antes = (p / "docker-compose.yml").read_text(encoding="utf-8")
    _proxy_vacio(tmp_path)
    llamadas = []

    def _fake(cmd, **k):
        llamadas.append(list(cmd))
        if cmd == ["docker", "compose", "up", "-d"] and k.get("cwd", "").endswith("proxy"):
            return _RC(1)  # 80/443 ocupados por otro
        return _RC(0)

    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    with pytest.raises(SystemExit) as e:
        modo_configurar_web(_ns_web(p, proxy=True))
    assert "traefik" in str(e.value.code)
    assert (p / "docker-compose.yml").read_text(encoding="utf-8") == antes
    assert not any("certbot" in c for c in llamadas)
    capsys.readouterr()


def test_web_proxy_cert_falla_conserva_dia1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    proxy = _proxy_vacio(tmp_path)

    def _fake(cmd, **k):
        if "certbot" in cmd:
            return _RC(1)
        return _RC(0)

    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    modo_configurar_web(_ns_web(p, proxy=True))
    out = capsys.readouterr().out
    sitio = proxy / "conf.d" / "tienda.com.conf"
    assert "listen 443 ssl" not in sitio.read_text(encoding="utf-8")
    assert "https://tienda.com" not in out
    assert "cron semanal en host" not in out


def test_web_proxy_reusa_cert_existente(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    proxy = _proxy_vacio(tmp_path)
    live = proxy / "letsencrypt" / "live" / "tienda.com"
    live.mkdir(parents=True)
    (live / "fullchain.pem").write_text("x", encoding="utf-8")
    llamadas = []

    def _fake(cmd, **k):
        llamadas.append(list(cmd))
        return _RC(0)

    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    modo_configurar_web(_ns_web(p, proxy=True, staging=False))
    out = capsys.readouterr().out
    assert not any("certbot" in c for c in llamadas)  # no re-emite
    assert "se conserva" in out
    sitio = proxy / "conf.d" / "tienda.com.conf"
    assert "listen 443 ssl" in sitio.read_text(encoding="utf-8")
    assert "https://tienda.com" in out


def test_web_standalone_intacto(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)

    def _boom(*a, **k):
        raise AssertionError("standalone con no_input no llama a docker")

    monkeypatch.setattr("omc.flows.subprocess.run", _boom)
    modo_configurar_web(_ns_web(p))
    comp = (p / "docker-compose.yml").read_text(encoding="utf-8")
    assert "  nginx:" in comp and "expose:" in comp  # bloque local, como siempre
    assert (p / "nginx" / "nginx.conf").exists()  # día 1 en el proyecto
    assert "DOMINIO=tienda.com" in (p / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "proxy").exists()
    capsys.readouterr()


def test_run_web_pasa_flags(monkeypatch, tmp_path):
    import omc.flows as F
    p = _proj_web_prod(tmp_path)
    vistos = []
    monkeypatch.setattr(F, "modo_configurar_web", lambda ns: vistos.append(ns))
    from omc.flows import run_web
    run_web(SimpleNamespace(proyecto=str(p), dominio="t.com", email="a@b.c",
                            staging=True, proxy=True, standalone=False,
                            no_input=True))
    assert len(vistos) == 1
    assert vistos[0].proxy is True and vistos[0].standalone is False
    assert vistos[0].staging is True and vistos[0].no_input is True
    assert vistos[0].dominio == "t.com"


def test_resolver_proyecto_rechaza_sin_compose(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        _resolver_proyecto(SimpleNamespace(proyecto=str(tmp_path)))


def test_addons_cli_parse():
    sub, ns, pos = _parse(["add", "--repo", "server-tools", "--org", "oca",
                           "--odoo", "18", "auditlog", "sentry"])
    assert sub == "add"
    assert ns.repo == "server-tools" and ns.org == "oca" and ns.odoo == "18"
    assert pos == ["auditlog", "sentry"]
    sub, ns, pos = _parse(["sync", "--proyecto", "X", "--yes"])
    assert sub == "sync" and ns.proyecto == "X" and ns.yes is True
    assert _parse([])[0] is None
    assert _parse(["status"])[0] == "status"


def _args_deps(proj, fix):
    return SimpleNamespace(proyecto=str(proj), branch="17.0", odoo="",
                           fix=fix, porcelain=False, enfocar="")


def _mock_sin_salida(monkeypatch):
    """analizar devuelve un faltante inexistente; catálogo vacío; path no-op."""
    import omc.flows as F
    monkeypatch.setattr(F, "analizar_depends",
                        lambda p: ({"mod_a": [("dep_x", "falta")]}, {}, {"dep_x"}))
    monkeypatch.setattr(F, "buscar_modulo_en_catalogo", lambda *a, **k: [])
    monkeypatch.setattr(F, "actualizar_addons_path", lambda *a, **k: None)


def test_run_deps_fix_sin_avance_no_repite(monkeypatch, tmp_path, capsys):
    """--fix sin tty ante faltante fuera de catálogo: informa una vez y sale."""
    _mock_sin_salida(monkeypatch)
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    run_deps(_args_deps(proj, fix=True))
    out = capsys.readouterr().out
    assert out.count("no está en el catálogo") == 1
    assert "Cadena muy larga" not in out
    assert "Sin avances" in out


def test_run_deps_fix_pregunta_y_omite(monkeypatch, tmp_path, capsys):
    """--fix con tty: pregunta cómo resolverlo; Omitir corta el loop."""
    _mock_sin_salida(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "3")  # Omitir
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    run_deps(_args_deps(proj, fix=True))
    out = capsys.readouterr().out
    assert "¿Cómo lo resolvemos?" in out
    assert out.count("no está en el catálogo") == 1
    assert "Cadena muy larga" not in out


def _proj_sync(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "docker-compose.yml").write_text(
        "services:\n  odoo:\n    image: odoo:17\n", encoding="utf-8")
    (p / ".env").write_text("ENTORNO=produccion\nODOO_VERSION=17\n", encoding="utf-8")
    (p / "addons").mkdir(exist_ok=True)
    return p


def _loc_adhoc(p):
    (p / "addons" / "localizacion.json").write_text(
        '{"perfil": "argentina-adhoc", "pip_extra": ["cryptography"],'
        ' "pip_exclude": ["M2Crypto"], "apt": ["python3-m2crypto"],'
        ' "seclevel": true, "pyafipws_cache": true}', encoding="utf-8")


def test_bloques_localizacion_sin_json(tmp_path):
    p = _proj_dev(tmp_path)
    assert bloques_localizacion(p) == {"APT_PKGS": "", "SECPY_BLOCK": ""}


def test_bloques_localizacion_adhoc(tmp_path):
    p = _proj_dev(tmp_path)
    (p / "addons").mkdir(exist_ok=True)
    (p / "requirements-odoo.txt").write_text("M2Crypto\npyafipws\n", encoding="utf-8")
    _loc_adhoc(p)
    b = bloques_localizacion(p)
    assert "python3-m2crypto" in b["APT_PKGS"]
    assert "SECLEVEL=2" in b["SECPY_BLOCK"] and "cache" in b["SECPY_BLOCK"]
    req = (p / "requirements-odoo.txt").read_text(encoding="utf-8")
    assert "cryptography" in req and "M2Crypto" not in req


def test_ensure_dockerfile_sync_con_localizacion(tmp_path):
    p = _proj_sync(tmp_path)
    _loc_adhoc(p)
    assert ensure_dockerfile_sync(p) is True
    dock = (p / "Dockerfile").read_text(encoding="utf-8")
    assert "python3-m2crypto" in dock and "SECLEVEL" in dock
    assert "build: ." in (p / "docker-compose.yml").read_text(encoding="utf-8")


def test_ensure_dockerfile_sync_sin_nada(tmp_path):
    p = _proj_sync(tmp_path)
    assert ensure_dockerfile_sync(p) is False
    assert not (p / "Dockerfile").exists()


def test_quitar_m2crypto():
    from omc.manifest import quitar_m2crypto
    kept, out = quitar_m2crypto(["pyOpenSSL", "M2Crypto", "httplib2>=0.7",
                                 "git+https://github.com/reingart/pyafipws"])
    assert out == ["M2Crypto"]
    assert "M2Crypto" not in kept and len(kept) == 3


def test_escanear_saca_m2crypto(tmp_path, capsys):
    from omc.flows import escanear_externas
    p = tmp_path / "proj"
    (p / "addons" / "custom" / "mod_ar").mkdir(parents=True)
    (p / "addons" / "custom" / "mod_ar" / "__manifest__.py").write_text(
        "{'name': 'mod_ar'}", encoding="utf-8")
    (p / "addons" / "custom" / "mod_ar" / "requirements.txt").write_text(
        "M2Crypto\nhttplib2>=0.7\n", encoding="utf-8")
    escanear_externas(p)
    out = capsys.readouterr().out
    assert "M2Crypto fuera del pip" in out
    req = (p / "requirements-odoo.txt").read_text(encoding="utf-8")
    assert "M2Crypto" not in req and "httplib2" in req


REQS_AR_17 = ["pyOpenSSL", "M2Crypto", "httplib2>=0.7", "pysimplesoap~=1.8.22",
             "git+https://github.com/reingart/pyafipws"]


def _proj_loc(tmp_path):
    import json as _json
    p = tmp_path / "proj"
    (p / "addons" / "adhoc" / "odoo-argentina-ce").mkdir(parents=True)
    (p / "addons" / "adhoc" / "odoo-argentina-ce" / "requirements.txt").write_text(
        "\n".join(REQS_AR_17) + "\n", encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps([
        {"org": "adhoc", "repo": "odoo-argentina-ce",
         "url": "https://github.com/ingadhoc/odoo-argentina-ce",
         "branch": "17.0", "path": "addons/adhoc/odoo-argentina-ce",
         "modules": ["l10n_ar_afipws", "l10n_ar_afipws_fe"]},
    ]), encoding="utf-8")
    return p


def test_aplicar_guarda_repo_requirements(monkeypatch, tmp_path, capsys):
    import json as _json
    import omc.flows as F
    monkeypatch.setattr(F, "instalar_addon", lambda *a, **k: True)
    p = _proj_loc(tmp_path)
    assert aplicar_localizacion(p, "17", "argentina-adhoc",
                                ofrecer_aplicar=False) == "argentina-adhoc"
    loc = _json.loads((p / "addons" / "localizacion.json").read_text(encoding="utf-8"))
    assert loc["repo_requirements"] == REQS_AR_17
    sc = p / "scripts" / "parametros_ar.sh"
    assert sc.exists() and "report.url" in sc.read_text(encoding="utf-8")
    assert "homologación" in capsys.readouterr().out  # recuerda pasar a producción


def test_bloques_fusiona_repo_requirements(tmp_path):
    import json as _json
    p = _proj_dev(tmp_path)
    (p / "addons").mkdir(exist_ok=True)
    (p / "addons" / "localizacion.json").write_text(_json.dumps({
        "perfil": "argentina-adhoc", "pip_extra": ["cryptography"],
        "pip_exclude": ["M2Crypto"], "repo_requirements": REQS_AR_17,
        "apt": ["python3-m2crypto"], "seclevel": True, "pyafipws_cache": True,
    }), encoding="utf-8")
    b = bloques_localizacion(p)
    assert "python3-m2crypto" in b["APT_PKGS"]
    req = (p / "requirements-odoo.txt").read_text(encoding="utf-8")
    assert "M2Crypto" not in req
    for esperado in ("httplib2>=0.7", "pysimplesoap~=1.8.22",
                     "git+https://github.com/reingart/pyafipws", "cryptography"):
        assert esperado in req, esperado


def test_parametros_ar_script(tmp_path):
    from omc.flows import _escribir_parametros_ar
    p = _proj_dev(tmp_path)
    sc = _escribir_parametros_ar(p)
    txt = sc.read_text(encoding="utf-8")
    assert "ir_config_parameter" in txt
    assert "report.url" in txt and "http://localhost:8069" in txt
    assert "WHERE NOT EXISTS" in txt
    import os as _os
    assert _os.access(sc, _os.X_OK)


def test_nginx_https_estructura():
    from omc.core import render, template_text
    out = render(template_text("nginx-https.conf.tpl"),
                 {"PROYECTO": "demo", "DOMINIO": "tienda.com", "ODOO_HOST": "odoo"})
    assert out.count("server {") == 3
    assert "server_name tienda.com www.tienda.com" in out
    assert "return 301 https://tienda.com$request_uri;" in out
    assert "server_name www.tienda.com;" in out
    assert "location /web/database/manager" in out and "return 404;" in out
    assert "location /websocket" in out and "proxy_pass http://odoo:8072;" in out
    assert "proxy_pass http://odoo:8069/;" in out
    for directiva in ('proxy_set_header Connection "upgrade";',
                      "proxy_cache_bypass $http_upgrade;",
                      "proxy_set_header X-NginX-Proxy true;",
                      "proxy_read_timeout 36000s;",
                      "client_max_body_size 10240m;",
                      "Strict-Transport-Security",
                      "/etc/letsencrypt/live/tienda.com/fullchain.pem",
                      "ssl_protocols TLSv1.2 TLSv1.3;"):
        assert directiva in out, directiva
    assert "include /etc/letsencrypt/options-ssl-nginx.conf" not in out  # certonly webroot no lo crea
    assert "{{" not in out


def test_nginx_https_modo_proxy():
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("nginx-https.conf.tpl"),
                 {"PROYECTO": "demo", "DOMINIO": "tienda.com",
                  "ODOO_HOST": "demo-odoo"})
    assert sin_renderizar(out) == []
    assert "proxy_pass http://demo-odoo:8072;" in out
    assert "proxy_pass http://demo-odoo:8069/;" in out
    assert "http://odoo:" not in out and "server odoo:" not in out


def test_proxy_site_templates_con_resolver():
    from omc.core import render, template_text, sin_renderizar
    m = {"PROYECTO": "demo", "DOMINIO": "tienda.com", "ODOO_HOST": "demo-odoo"}
    dia1 = render(template_text("proxy-site.conf.tpl"), m)
    https = render(template_text("proxy-site-https.conf.tpl"), m)
    for out in (dia1, https):
        assert sin_renderizar(out) == []
        assert "resolver 127.0.0.11 valid=10s;" in out
        assert "upstream {" not in out  # nada estático: un caído no voltea al resto
        assert "server_name tienda.com www.tienda.com;" in out
    assert "set $up demo-odoo:8069;" in dia1
    assert "proxy_pass http://$up;" in dia1
    assert "set $up demo-odoo:8069;" in https
    assert "set $up_ws demo-odoo:8072;" in https
    assert "proxy_pass http://$up_ws;" in https
    assert https.count("listen 443 ssl;") == 2
    assert "return 404;" in https  # manager bloqueado también en proxy


def test_nginx_dia1_modos():
    from omc.core import render, template_text, sin_renderizar
    clasico = render(template_text("nginx.conf.tpl"),
                     {"PROYECTO": "demo", "DOMINIO": "t.com", "ODOO_HOST": "odoo"})
    assert sin_renderizar(clasico) == []
    assert "upstream odoo {" in clasico and "proxy_pass http://odoo;" in clasico
    proxy = render(template_text("nginx.conf.tpl"),
                   {"PROYECTO": "demo", "DOMINIO": "t.com", "ODOO_HOST": "demo-odoo"})
    assert sin_renderizar(proxy) == []
    assert "upstream demo-odoo {" in proxy
    assert "server demo-odoo:8069;" in proxy
    assert "proxy_pass http://demo-odoo;" in proxy
    # un solo upstream por archivo: dos sites no chocan en el proxy central
    assert proxy.count("upstream ") == 1


def test_proxy_compose_estructura():
    from omc.compose import PROXY_NETWORK, generar_proxy_compose
    from omc.core import sin_renderizar
    out = generar_proxy_compose()
    assert sin_renderizar(out) == []
    assert out.count('"80:80"') == 1 and out.count('"443:443"') == 1  # único publicador
    assert "./conf.d:/etc/nginx/conf.d/:ro" in out
    assert "./letsencrypt:/etc/letsencrypt:ro" in out
    assert "networks:\n  omc-proxy:\n    external: true" in out
    assert PROXY_NETWORK == "omc-proxy"


def _proj_proxy_site(tmp_path, env_extra=""):
    p = tmp_path / "tienda"
    p.mkdir()
    (p / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    image: postgres:16\n"
        "  odoo:\n"
        "    image: odoo:18\n"
        "    restart: always\n"
        '    ports:\n      - "8070:8069"\n'
        "    environment:\n"
        "      - HOST=db\n"
        "volumes:\n"
        "  odoo-db-data:\n",
        encoding="utf-8")
    (p / ".env").write_text("ODOO_PORT=8070\n", encoding="utf-8")
    (p / "config").mkdir()
    (p / "config" / "odoo.conf").write_text("[options]\n", encoding="utf-8")
    return p


def test_parchear_compose_a_proxy(monkeypatch, tmp_path):
    from omc.compose import parchear_compose_a_proxy
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_proxy_site(tmp_path)
    res = parchear_compose_a_proxy(p, "tienda")
    assert set(res["cambios"]) == {"container_name", "networks odoo", "expose",
                                   "networks externa"}
    txt = (p / "docker-compose.yml").read_text(encoding="utf-8")
    assert "container_name: tienda-odoo" in txt
    assert '"8070:8069"' not in txt and '"8069"' in txt and '"8072"' in txt
    assert "networks:\n  omc-proxy:\n    external: true" in txt
    assert (p / "config" / "odoo.conf").read_text(encoding="utf-8").count(
        "proxy_mode = True") == 0  # el helper no toca odoo.conf
    # idempotente: segunda corrida no cambia nada
    res2 = parchear_compose_a_proxy(p, "tienda")
    assert res2 == {"cambios": []}
    assert (p / "docker-compose.yml").read_text(encoding="utf-8") == txt


def test_parchear_compose_a_proxy_rechaza_nginx_local(tmp_path):
    import pytest
    from omc.compose import parchear_compose_a_proxy
    p = _proj_proxy_site(tmp_path)
    with open(p / "docker-compose.yml", "a", encoding="utf-8") as f:
        f.write("\n  nginx:\n    image: nginx:alpine\n")
    with pytest.raises(SystemExit) as e:
        parchear_compose_a_proxy(p, "tienda")
    assert "80/443" in str(e.value.code)


def test_asegurar_proxy_mode(tmp_path):
    from omc.compose import asegurar_proxy_mode
    p = tmp_path / "proj"
    assert asegurar_proxy_mode(p) is False  # sin odoo.conf
    (p / "config").mkdir(parents=True)
    (p / "config" / "odoo.conf").write_text("[options]\nworkers = 4\n",
                                            encoding="utf-8")
    assert asegurar_proxy_mode(p) is True
    txt = (p / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "workers = 4" in txt and txt.count("proxy_mode = True") == 1
    assert asegurar_proxy_mode(p) is False  # ya estaba


def test_certonly_cmd_lleva_www():
    cmd = _certonly_cmd("yo@x.com", "tienda.com", False)
    assert "-d" in cmd and "tienda.com" in cmd and "www.tienda.com" in cmd
    assert "--staging" not in cmd
    assert "--staging" in _certonly_cmd("yo@x.com", "tienda.com", True)


def _proj_web(tmp_path):
    p = tmp_path / "proj"
    (p / "nginx").mkdir(parents=True)
    (p / "nginx" / "nginx.conf").write_text("# dia 1 HTTP", encoding="utf-8")
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    return p


def test_activar_https_ok_escribe_conf(monkeypatch, tmp_path):
    p = _proj_web(tmp_path)
    class _R:
        returncode = 0
    monkeypatch.setattr("omc.flows.subprocess.run", lambda *a, **k: _R())
    assert _activar_https(p, "tienda.com", "yo@x.com", False) is True
    txt = (p / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "listen 443 ssl" in txt and "tienda.com" in txt


def test_activar_https_cert_falla_conserva_dia1(monkeypatch, tmp_path):
    p = _proj_web(tmp_path)
    class _R:
        def __init__(self, rc):
            self.returncode = rc
    llamadas = []
    def _fake(cmd, **k):
        llamadas.append(cmd)
        return _R(0 if "up" in cmd else 1)  # up ok, certonly falla
    monkeypatch.setattr("omc.flows.subprocess.run", _fake)
    assert _activar_https(p, "tienda.com", "yo@x.com", False) is False
    assert (p / "nginx" / "nginx.conf").read_text(encoding="utf-8") == "# dia 1 HTTP"


def test_nginx_gzip_conf():
    from omc.core import render, template_text
    out = render(template_text("nginx-gzip.conf.tpl"), {"PROYECTO": "demo"})
    for directiva in ("gzip on;", 'gzip_disable "msie6";', "gzip_vary on;",
                      "gzip_proxied any;", "gzip_comp_level 6;",
                      "gzip_buffers 16 8k;", "gzip_http_version 1.1;",
                      "gzip_types text/plain text/css application/json"):
        assert directiva in out, directiva
    assert "{{" not in out


def test_compose_nginx_block_monta_gzip_y_sitio():
    from omc.core import render, template_text
    out = render(template_text("compose-nginx-block.yml.tpl"),
                 {"PROYECTO": "demo", "DOMINIO": "t.com",
                  "CERTBOT_EMAIL": "a@b.c", "CERTBOT_STAGING": ""})
    assert "./nginx/nginx.conf:/etc/nginx/conf.d/odoo.conf:ro" in out
    assert "./nginx/gzip.conf:/etc/nginx/conf.d/gzip.conf:ro" in out
    assert "default.conf" not in out


def test_backup_tpl_retencion_semanal():
    import subprocess as _sp
    from omc.core import template_text, sin_renderizar
    out = template_text("backup.sh.tpl").replace("{{PROYECTO}}", "demo")
    assert sin_renderizar(out) == []
    assert "week$((10#$(date +%V) % 4))" in out  # 4 domingos rotando
    assert "Subida dominical OK." in out
    r = _sp.run(["bash", "-n", "/dev/stdin"], input=out, text=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
    assert r.returncode == 0


def test_restore_tpl_cubre_fuente_externa():
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    assert sin_renderizar(out) == []
    assert "docker compose up -d db" in out and "pg_isready" in out
    assert "--clean --if-exists" in out
    assert 'filestore*.tar.gz' in out  # backups ajenos usan .tar.gz, no .tgz


def test_restore_tpl_neutralizar_opt_in():
    import subprocess as _sp
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    assert sin_renderizar(out) == []
    assert "odoo neutralize -d" in out
    assert "--neutralizar" in out and "--sin-neutralizar" in out
    assert "JAMÁS en producción" in out  # nunca por default
    r = _sp.run(["bash", "-n", "/dev/stdin"], input=out, text=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
    assert r.returncode == 0


def test_run_restore_pasa_flags_neutralizar(monkeypatch, tmp_path, capsys):
    import subprocess as _sp
    proj = _proj_dev(tmp_path)
    (proj / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "restore.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(_sp, "run", lambda *a, **k: vistos.append(a[0]))
    run_restore(SimpleNamespace(proyecto=str(proj), neutralizar=True,
                                sin_neutralizar=False))
    run_restore(SimpleNamespace(proyecto=str(proj), neutralizar=False,
                                sin_neutralizar=True))
    run_restore(SimpleNamespace(proyecto=str(proj)))
    assert vistos[0] == ["./scripts/restore.sh", "--neutralizar"]
    assert vistos[1] == ["./scripts/restore.sh", "--sin-neutralizar"]
    assert vistos[2] == ["./scripts/restore.sh"]
    capsys.readouterr()


def test_cli_restore_flags():
    from omc.cli import build_parser
    args = build_parser().parse_args(["restore"])
    assert args.neutralizar is False and args.sin_neutralizar is False
    args = build_parser().parse_args(["restore", "--neutralizar"])
    assert args.neutralizar is True
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args(["restore", "--neutralizar", "--sin-neutralizar"])


def _proj_short(tmp_path):
    p = tmp_path / "proj"
    p.mkdir(exist_ok=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    return p


def test_cli_logs_update_test():
    from omc.cli import build_parser
    a = build_parser().parse_args(["logs"])
    assert (a.servicio, a.tail) == ("odoo", 200)
    a = build_parser().parse_args(["logs", "--servicio", "db", "--tail", "50"])
    assert (a.servicio, a.tail) == ("db", 50)
    a = build_parser().parse_args(["update", "sale", "--db", "midb"])
    assert (a.modulo, a.db) == ("sale", "midb")
    a = build_parser().parse_args(["test"])
    assert a.modulo is None and a.db is None


def test_run_logs(monkeypatch, tmp_path, capsys):
    import subprocess as _sp
    from omc.flows import run_logs
    p = _proj_short(tmp_path)
    vistos = []
    monkeypatch.setattr(_sp, "run", lambda *a, **k: vistos.append((a[0], k.get("cwd"))))
    run_logs(SimpleNamespace(proyecto=str(p)))
    run_logs(SimpleNamespace(proyecto=str(p), servicio="db", tail=50))
    assert vistos[0] == (["docker", "compose", "logs", "-f", "--tail=200", "odoo"],
                         str(p))
    assert vistos[1][0][-2:] == ["--tail=50", "db"]
    assert "Ctrl+C" in capsys.readouterr().out


def test_run_update_y_test(monkeypatch, tmp_path, capsys):
    import subprocess as _sp
    from omc.flows import run_update, run_test
    p = _proj_short(tmp_path)
    vistos = []

    def _ok(*a, **k):
        vistos.append(a[0])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(_sp, "run", _ok)
    run_update(SimpleNamespace(proyecto=str(p), modulo="sale", db="midb"))
    run_test(SimpleNamespace(proyecto=str(p), modulo="sale", db="midb"))
    assert vistos[0] == ["docker", "compose", "run", "--rm", "odoo",
                         "odoo", "-d", "midb", "-u", "sale", "--stop-after-init"]
    assert vistos[1] == ["docker", "compose", "run", "--rm", "odoo",
                         "odoo", "-d", "midb", "-u", "sale",
                         "--test-enable", "--stop-after-init"]
    assert "Reiniciá: docker compose restart odoo" in capsys.readouterr().out
    import pytest
    with pytest.raises(SystemExit):
        run_update(SimpleNamespace(proyecto=str(p), modulo=None, db="midb"))
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(SystemExit):
        run_test(SimpleNamespace(proyecto=str(p), modulo="sale", db="midb"))


def test_elegir_bd(monkeypatch, tmp_path, capsys):
    import subprocess as _sp
    from omc.flows import _elegir_bd
    p = _proj_short(tmp_path)
    assert _elegir_bd(p, "midb", "x") == "midb"  # flag manda
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=1,
                                                                   stdout=""))
    import pytest
    with pytest.raises(SystemExit) as e:
        _elegir_bd(p, None, "x")
    assert "--db" in str(e.value.code)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=0,
                                                                   stdout="midb\n"))
    assert _elegir_bd(p, None, "x") == "midb"  # única: auto
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="a\nb\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        _elegir_bd(p, None, "x")  # varias + no tty: exige --db
    capsys.readouterr()


def test_agents_proyecto_render_sin_residuos():
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("agents-proyecto.md.tpl"),
                 {"PROYECTO": "demo", "ODOO_VERSION": "18", "MAILPIT_PORT": "8025"})
    assert sin_renderizar(out) == []
    assert "docker compose logs -f odoo" in out
    assert "omc test <modulo>" in out and "--test-enable" in out
    assert "--neutralizar" in out
    assert "demo" in out


def test_generar_odoo_conf_usa_limites_del_reparto():
    from omc.compose import generar_odoo_conf
    conf = generar_odoo_conf("produccion", {"ODOO_LIMIT_SOFT": "111",
                                            "ODOO_LIMIT_HARD": "222"})
    assert "limit_memory_soft = 111" in conf
    assert "limit_memory_hard = 222" in conf
    conf_dflt = generar_odoo_conf("produccion", {})
    assert "limit_memory_soft = 2147483648" in conf_dflt  # fallback defaults Odoo
    assert "list_db = True" in conf_dflt  # manager por IP:puerto en prod (https bloqueado por nginx)
    conf_dev = generar_odoo_conf("desarrollo", {})
    assert "limit_memory" not in conf_dev and "workers = 0" in conf_dev
    assert "list_db = True" in conf_dev  # también en dev
    assert "smtp_server = mailpit" in conf_dev and "smtp_port = 1025" in conf_dev


def test_env_ejemplo_sin_residuos_ni_secretos():
    from omc.core import render, template_text, sin_renderizar
    mapping = {"PROYECTO": "demo", "ENTORNO": "desarrollo", "ODOO_VERSION": "18",
               "ODOO_IMAGE": "odoo:18", "POSTGRES_IMAGE": "postgres:16",
               "POSTGRES_PASSWORD": "cambiar-esta-clave",
               "ODOO_PORT": "8069", "ODOO_GEVENT_PORT": "8072",
               "PG_SHARED_BUFFERS": "128MB", "PG_EFFECTIVE_CACHE": "512MB",
               "PG_WORK_MEM": "8MB", "PG_MAINT_MEM": "64MB", "PG_MAX_CONN": "50",
               "ODOO_CPUS": "1.0", "ODOO_MEM": "2G", "DB_CPUS": "0.5", "DB_MEM": "1G"}
    out = render(template_text("env.ejemplo.tpl"), mapping)
    assert sin_renderizar(out) == []
    assert "POSTGRES_PASSWORD=cambiar-esta-clave" in out
    assert "ghp_" not in out and "token" not in out.lower()



def test_instalar_addon_respeta_rama_pr(monkeypatch, tmp_path):
    import omc.flows as F
    visto = {}
    monkeypatch.setattr(F, "add_modules",
                        lambda p, o, r, u, b, m: visto.setdefault("branch", b))
    F.instalar_addon(tmp_path, "adhoc", "web", ["web_dark_mode"], "17",
                     "https://github.com/lubusax/web.git",
                     branch="17.0-mig-web_dark_theme")
    assert visto["branch"] == "17.0-mig-web_dark_theme"
    visto.clear()
    F.instalar_addon(tmp_path, "adhoc", "web", ["m"], "17", "https://x/y")
    assert visto["branch"] == "17.0"


def test_otro_pr_guarda_rama_en_repos_json(tmp_path):
    """Otro + rama de PR: el .json (repos.json) queda con la rama del PR."""
    import json as _json
    import subprocess as _sp
    import os as _os
    import omc.flows as F
    # remoto local con rama de migración
    rem = tmp_path / "remoto" / "web"
    mod = rem / "web_dark_mode"
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf-8")
    e = dict(_os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
             GIT_INIT_DEFAULT_BRANCH="17.0-mig-web_dark_theme")
    _sp.run(["git", "init", "-q"], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "add", "."], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "commit", "-qm", "ini"], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "branch", "-M", "17.0-mig-web_dark_theme"], cwd=str(rem), env=e,
            check=True)
    proj = tmp_path / "proj"
    (proj / "addons").mkdir(parents=True)
    F.instalar_addon_url(proj, "custom", "web", str(rem), ["web_dark_mode"], "17",
                         branch="17.0-mig-web_dark_theme")
    repos = _json.loads((proj / "addons" / "repos.json").read_text(encoding="utf-8"))
    assert len(repos) == 1
    assert repos[0]["branch"] == "17.0-mig-web_dark_theme"
    assert repos[0]["modules"] == ["web_dark_mode"]
    assert (proj / "addons" / "custom" / "web" / "web_dark_mode").is_dir()


def _proj_qj(tmp_path, conf_txt):
    import json as _json
    p = tmp_path / "proj"
    (p / "config").mkdir(parents=True)
    (p / "addons").mkdir(exist_ok=True)
    (p / "config" / "odoo.conf").write_text(conf_txt, encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps([
        {"org": "oca", "repo": "queue", "url": "https://github.com/OCA/queue",
         "branch": "17.0", "path": "addons/oca/queue", "modules": ["queue_job"]},
    ]), encoding="utf-8")
    return p


_CONF_BASE = "[options]\naddons_path = /x\nworkers = 4\n"


def test_queue_job_agrega_conf(tmp_path, capsys):
    from omc.flows import asegurar_queue_job_conf
    from types import SimpleNamespace
    p = _proj_qj(tmp_path, _CONF_BASE)
    assert asegurar_queue_job_conf(p, SimpleNamespace(yes=True)) is True
    txt = (p / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "server_wide_modules = web,queue_job" in txt
    assert "[queue_job]" in txt and "channels = root:2" in txt
    # idempotente: segunda vez no cambia
    assert asegurar_queue_job_conf(p, SimpleNamespace(yes=True)) is False


def test_queue_job_respeta_valores(tmp_path):
    from omc.flows import asegurar_queue_job_conf
    from types import SimpleNamespace
    p = _proj_qj(tmp_path, _CONF_BASE + "server_wide_modules = web,mi_mod\n"
                 "[queue_job]\nchannels = root:8\n")
    assert asegurar_queue_job_conf(p, SimpleNamespace(yes=True)) is True
    txt = (p / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "server_wide_modules = web,mi_mod,queue_job" in txt  # fusiona sw
    assert "channels = root:8" in txt  # respeta channels del usuario
    assert asegurar_queue_job_conf(p, SimpleNamespace(yes=True)) is False  # ya está
    p2 = _proj_qj(tmp_path / "p2", _CONF_BASE + "server_wide_modules = web,mi_mod\n")
    assert asegurar_queue_job_conf(p2, SimpleNamespace(yes=True)) is True
    txt2 = (p2 / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "server_wide_modules = web,mi_mod,queue_job" in txt2  # fusiona
    assert "channels = root:8" not in txt2 and "channels = root:2" in txt2


def test_queue_job_sin_modulo_no_toca(tmp_path):
    import json as _json
    from omc.flows import asegurar_queue_job_conf
    from types import SimpleNamespace
    p = _proj_qj(tmp_path, _CONF_BASE)
    (p / "addons" / "repos.json").write_text(_json.dumps([]), encoding="utf-8")
    assert asegurar_queue_job_conf(p, SimpleNamespace(yes=True)) is False
    assert (p / "config" / "odoo.conf").read_text(encoding="utf-8") == _CONF_BASE


def test_queue_job_avisa_sin_workers(tmp_path, capsys):
    from omc.flows import asegurar_queue_job_conf
    from types import SimpleNamespace
    p = _proj_qj(tmp_path, "[options]\nworkers = 0\n")
    asegurar_queue_job_conf(p, SimpleNamespace(yes=True))
    assert "workers > 0" in capsys.readouterr().out


def _remoto_qj(tmp_path):
    import subprocess as _sp
    import os as _os
    rem = tmp_path / "remoto" / "queue"
    mod = rem / "queue_job"
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf-8")
    e = dict(_os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    _sp.run(["git", "init", "-qb", "17.0"], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "add", "."], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "commit", "-qm", "ini"], cwd=str(rem), env=e, check=True)
    return rem


def _proj_qj_add(tmp_path, rem):
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "config").mkdir(parents=True)
    (p / ".env").write_text("ODOO_VERSION=17\n", encoding="utf-8")
    (p / "config" / "odoo.conf").write_text("[options]\nworkers = 2\n", encoding="utf-8")
    return p


def test_run_add_configura_queue_job(tmp_path):
    from types import SimpleNamespace
    import omc.flows as F
    rem = _remoto_qj(tmp_path)
    proj = _proj_qj_add(tmp_path, rem)
    F.run_add(SimpleNamespace(proyecto=str(proj), branch="17.0", odoo="", org="oca",
                              repo="queue", url=str(rem), modulos=["queue_job"]))
    txt = (proj / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "server_wide_modules = web,queue_job" in txt
    assert "[queue_job]" in txt


def test_run_bundle_configura_queue_job(tmp_path):
    import json as _json
    from types import SimpleNamespace
    import omc.flows as F
    rem = _remoto_qj(tmp_path)
    proj = _proj_qj_add(tmp_path, rem)
    (proj / "b.json").write_text(_json.dumps({
        "modulos": [{"org": "oca", "repo": "queue", "url": str(rem),
                     "modules": ["queue_job"]}]}), encoding="utf-8")
    F.run_bundle(SimpleNamespace(proyecto=str(proj), archivo="b.json", branch="17.0",
                                 odoo="", yes=True))
    txt = (proj / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "server_wide_modules = web,queue_job" in txt


def test_github_autocompleta_org_con_login(monkeypatch, tmp_path, capsys):
    import omc.flows as F
    monkeypatch.setattr(F, "gh_config_leer", lambda: {})
    guardado = {}
    monkeypatch.setattr(F, "gh_config_guardar", lambda c: guardado.update(c) or tmp_path / "c.json")
    monkeypatch.setattr(F, "gh_token", lambda: "")
    monkeypatch.setattr(F, "gh_org", lambda: "")
    respuestas = iter(["ghp_faketoken123", ""])
    monkeypatch.setattr(F, "ask_texto", lambda *a, **k: next(respuestas))
    monkeypatch.setattr(F, "gh_validar_token", lambda t: "miusuario")
    assert F.configurar_github_interactivo() is True
    assert guardado["github_org"] == "miusuario"
    assert "miusuario/<repo>" in capsys.readouterr().out


def test_git_env_no_pide_password():
    import omc.gitutils as G
    assert G.git_env().get("GIT_TERMINAL_PROMPT") == "0"


def test_run_pasa_env_sin_prompt(monkeypatch):
    import subprocess as _sp
    import omc.gitutils as G
    visto = {}
    class _R:
        returncode = 0
        stdout = ""
        stderr = ""
    def _fake(cmd, **k):
        visto.update(k)
        return _R()
    monkeypatch.setattr(_sp, "run", _fake)
    G.run(["true"])
    assert visto.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


def test_list_topdirs_auth_falla_con_mensaje(monkeypatch, capsys):
    import omc.gitutils as G
    class _R:
        returncode = 128
        stdout = ""
        stderr = "remote: Invalid username or password.\nfatal: Authentication failed"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
    assert G.list_remote_topdirs("https://github.com/x/y", "17.0") == (None, False, None)
    out = capsys.readouterr().out
    assert "autenticación" in out and "menú 7" in out


def test_list_topdirs_error_generico_sugiere_ramas(monkeypatch):
    import omc.gitutils as G
    class _R:
        returncode = 128
        stdout = ""
        stderr = "Repository not found."
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
    monkeypatch.setattr(G, "avisar_ramas", lambda *a, **k: None)
    monkeypatch.setattr(G, "ramas_version", lambda *a, **k: ["17.0"])
    assert G.list_remote_topdirs("https://github.com/x/y", "17.0") == (None, False, ["17.0"])


def test_git_red_con_token_y_sin_token(monkeypatch, tmp_path):
    import subprocess as _sp
    import os as _os
    import omc.gitutils as G
    d = tmp_path / "r"
    d.mkdir()
    _sp.run(["git", "init", "-q"], cwd=str(d), check=True)
    _sp.run(["git", "remote", "add", "origin", "https://github.com/x/y"], cwd=str(d),
            check=True)
    monkeypatch.setattr("omc.github.gh_token", lambda: "")
    assert G.git_red(str(d)) == ["git"]
    monkeypatch.setattr("omc.github.gh_token", lambda: "TOKEN123")
    pref = G.git_red(str(d))
    assert pref[0] == "git" and pref[1] == "-c" and "basic" in pref[2]
    _os.environ.pop("GIT_TERMINAL_PROMPT", None)  # no tocar entorno real


def test_org_desde_url_dueno_real():
    from omc.github import org_desde_url
    assert org_desde_url("https://github.com/berisoft-arg/odoo-paintstore.git") == "berisoft-arg"
    assert org_desde_url("https://github.com/OCA/server-tools") == "oca"
    assert org_desde_url("git@github.com:ingadhoc/odoo-argentina.git") == "adhoc"
    assert org_desde_url("basura") == "custom"
    assert org_desde_url("") == "custom"


def test_add_modules_actualiza_clon_viejo(tmp_path):
    """Clon viejo + módulo nuevo en remoto: hace pull e instala (no 'omitido')."""
    import subprocess as _sp
    import os as _os
    from omc.addonsops import add_modules
    rem = tmp_path / "remoto" / "r"
    (rem / "mod_a").mkdir(parents=True)
    (rem / "mod_a" / "__manifest__.py").write_text("{'name': 'a'}", encoding="utf-8")
    e = dict(_os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    _sp.run(["git", "init", "-qb", "17.0"], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "add", "."], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "commit", "-qm", "v1"], cwd=str(rem), env=e, check=True)
    proj = tmp_path / "proj"
    (proj / "addons").mkdir(parents=True)
    (proj / ".env").write_text("ODOO_VERSION=17\n", encoding="utf-8")
    ok, _ = add_modules(proj, "custom", "r", str(rem), "17.0", ["mod_a"])
    assert ok == ["mod_a"]
    (rem / "mod_b").mkdir()
    (rem / "mod_b" / "__manifest__.py").write_text("{'name': 'b'}", encoding="utf-8")
    _sp.run(["git", "add", "."], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "commit", "-qm", "v2"], cwd=str(rem), env=e, check=True)
    ok2, fail2 = add_modules(proj, "custom", "r", str(rem), "17.0", ["mod_b"])
    assert ok2 == ["mod_b"] and fail2 == [], "el clon viejo debe actualizarse vía pull"


def test_menu_agrupado_muestra_fases_y_flujo(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    assert menu_principal() == "salir"
    out = capsys.readouterr().out
    assert "— Crear —" in out
    assert "— Publicar [prod] —" in out
    assert "— Operar —" in out
    assert "Habitual: 1 crear" in out
    # numeración intacta en dos dígitos sin paréntesis (sin renumerar)
    assert "11 -" in out and "Proxy multinstancia" in out
    assert "12 -" in out and "Migrar instancia a otro VPS" in out
    assert "00 - Salir" in out


def test_web_proxy_sin_init_ofrece_init(monkeypatch, tmp_path, capsys):
    import omc.flows as _fl
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = _proj_web_prod(tmp_path)
    assert not (tmp_path / "proxy").exists()
    monkeypatch.setattr(_fl, "es_interactivo", lambda: True)
    monkeypatch.setattr(_fl, "ask_si_no", lambda *a, **k: True)

    def _fake_init(salida=None):
        _proxy_vacio(tmp_path)
        return tmp_path / "proxy"

    monkeypatch.setattr(_fl, "run_proxy_init", _fake_init)
    monkeypatch.setattr(_fl.subprocess, "run", lambda *a, **k: _RC(0))
    modo_configurar_web(_ns_web(p, proxy=True, no_input=False))
    out = capsys.readouterr().out
    sitio = tmp_path / "proxy" / "conf.d" / "tienda.com.conf"
    assert sitio.exists()
    assert "listen 443 ssl" in sitio.read_text(encoding="utf-8")
    assert "https://tienda.com" in out


def test_menu_loop_pausa_tras_exit(monkeypatch, capsys):
    import omc.cli as _cli
    seq = iter(["web", "salir"])

    def _fake_menu():
        return next(seq)

    def _boom(accion):
        raise SystemExit("No hay proxy central en /opt/proxy (corre `omc proxy init` primero).")

    prompts = []
    monkeypatch.setattr("omc.flows.menu_principal", _fake_menu)
    monkeypatch.setattr(_cli, "_ejecutar_accion_menu", _boom)
    monkeypatch.setattr(_cli, "es_interactivo", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: prompts.append(a) or "")
    _cli._menu_loop()
    out = capsys.readouterr().out
    assert "omc proxy init" in out
    assert any("volver al men" in str(a[0]).lower() for a in prompts)


def test_run_deps_checklist_filtra_sugeridos(monkeypatch, tmp_path, capsys):
    """Con tty + --fix, el checklist filtra qué sugeridos traer (subset)."""
    import omc.flows as F
    monkeypatch.setattr(F, "analizar_depends",
                        lambda p: ({"mod_a": [("dep_x", "falta"), ("dep_y", "falta")]},
                                   {}, {"dep_x", "dep_y"}))
    monkeypatch.setattr(F, "buscar_modulo_en_catalogo",
                        lambda dep, *a, **k: [("oca", "server-tools", "https://x/r")])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("omc.tui.checklist",
                        lambda titulo, items, marcados=None, pie=None: ["dep_x → oca/server-tools"])
    traidos = []
    monkeypatch.setattr(F, "add_modules",
                        lambda proyecto, org, repo, url, br, mods: traidos.append((org, repo, mods)))
    monkeypatch.setattr(F, "actualizar_addons_path", lambda *a, **k: None)
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    F.run_deps(_args_deps(proj, fix=True))
    assert traidos and all(t == ("oca", "server-tools", ["dep_x"]) for t in traidos)
    capsys.readouterr()


def test_run_deps_checklist_vacio_no_trae(monkeypatch, tmp_path, capsys):
    """Checklist vacío (deseleccionar todo + Enter) no trae nada."""
    import omc.flows as F
    monkeypatch.setattr(F, "analizar_depends",
                        lambda p: ({"mod_a": [("dep_x", "falta")]}, {}, {"dep_x"}))
    monkeypatch.setattr(F, "buscar_modulo_en_catalogo",
                        lambda dep, *a, **k: [("oca", "server-tools", "https://x/r")])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("omc.tui.checklist", lambda *a, **k: [])
    traidos = []
    monkeypatch.setattr(F, "add_modules",
                        lambda proyecto, org, repo, url, br, mods: traidos.append(mods))
    monkeypatch.setattr(F, "actualizar_addons_path", lambda *a, **k: None)
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    F.run_deps(_args_deps(proj, fix=True))
    assert traidos == []
    assert "Sin avances" in capsys.readouterr().out


def test_run_deps_checklist_mismo_repo_subset(monkeypatch, tmp_path, capsys):
    """Checklist filtra mismo-repo: solo el módulo elegido va a sparse-checkout."""
    import omc.flows as F
    monkeypatch.setattr(F, "analizar_depends",
                        lambda p: ({}, {"addons/oca/server-tools": ["mod_a", "mod_b"]}, set()))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("omc.tui.checklist",
                        lambda *a, **k: ["mod_a  [addons/oca/server-tools]"])
    agregados = []
    monkeypatch.setattr(F, "git_red", lambda s: [s])
    monkeypatch.setattr(F, "run",
                        lambda cmd, **k: agregados.append(cmd) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(F, "load_repos", lambda p: [])
    monkeypatch.setattr(F, "save_repos", lambda p, r: None)
    monkeypatch.setattr(F, "actualizar_addons_path", lambda *a, **k: None)
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    F.run_deps(_args_deps(proj, fix=True))
    adds = [c for c in agregados if "sparse-checkout" in c and "add" in c]
    assert adds and all("mod_a" in c and "mod_b" not in c for c in adds)
    capsys.readouterr()


def test_elegir_repo_guiado_checklist(monkeypatch, tmp_path, capsys):
    """Guiado usa checklist paginado para repo y módulos (con fallback intacto)."""
    import omc.flows as F
    from omc.flows import elegir_repo_guiado
    proj = _proj_dev(tmp_path)
    (proj / "addons").mkdir(exist_ok=True)
    cat = {"oca": [{"repo": "server-tools", "url": "https://x/server-tools"}]}
    monkeypatch.setattr("omc.flows.ask_opcion", lambda *a, **k: "OCA")
    llamadas = {"n": 0}

    def _fake_cl(titulo, items, marcados=None, pie=None):
        llamadas["n"] += 1
        if "repo" in titulo.lower():
            assert items == ["server-tools"]
            return ["server-tools"]
        assert "auditlog" in items and "sentry" in items
        return ["auditlog"]

    monkeypatch.setattr("omc.tui.checklist", _fake_cl)
    monkeypatch.setattr(F, "list_remote_topdirs",
                        lambda url, br: (["auditlog", "sentry"], False, []))
    traidos = []
    monkeypatch.setattr(F, "add_modules",
                        lambda proyecto, org, repo, url, br, mods: traidos.append((org, repo, mods)) or True)
    assert elegir_repo_guiado(proj, "auditlog", "17.0", cat) is True
    assert traidos == [("oca", "server-tools", ["auditlog"])]
    capsys.readouterr()


def test_marco_titulo_plano_sin_fondo(monkeypatch):
    """resaltar_titulo=False deja el título plano; True mantiene fondo azul."""
    import omc.tui as T
    monkeypatch.setattr(T.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(T.os, "environ", {})
    con = T.marco("¿Qué quiere hacer?", ["  1) Crear"], pie=None, resaltar_titulo=True)
    assert "\x1b[1;37;44m ¿Qué quiere hacer? \x1b[0m" in con
    sin = T.marco("¿Qué quiere hacer?", ["  1) Crear"], pie=None, resaltar_titulo=False)
    assert "\x1b[1;37;44m ¿Qué quiere hacer? \x1b[0m" not in sin
    assert "¿Qué quiere hacer?" in sin


def test_esperar_esc_volver_sin_tty_no_bloquea(monkeypatch):
    """Sin tty retorna True sin leer nada (CI, --no-input, pytest)."""
    import omc.tui as T
    monkeypatch.setattr(T.sys.stdin, "isatty", lambda: False)
    assert T.esperar_esc_volver() is True


def test_esperar_esc_volver_solo_esc(monkeypatch, capsys):
    """Enter/otras se ignoran; solo ESC (o q) vuelve."""
    import sys as _sys
    import omc.tui as T
    monkeypatch.setattr(T.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(T.sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(T.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    lecturas = iter([b"\r", b"x", b"\x1b"])

    class _FakeTermios:
        TCSADRAIN = 1

        @staticmethod
        def tcgetattr(fd):
            return "old"

        @staticmethod
        def tcsetattr(fd, when, old):
            return None

    class _FakeTty:
        @staticmethod
        def setcbreak(fd):
            return None

    class _FakeSelect:
        @staticmethod
        def select(r, w, x, *a):
            return (r, [], [])

    monkeypatch.setitem(_sys.modules, "termios", _FakeTermios)
    monkeypatch.setitem(_sys.modules, "tty", _FakeTty)
    monkeypatch.setitem(_sys.modules, "select", _FakeSelect)
    monkeypatch.setattr(T.os, "read", lambda fd, n: next(lecturas))
    assert T.esperar_esc_volver() is True
    assert capsys.readouterr().out.count("Pulsa ESC") == 3


def test_paso_despliegue_exito_espera_esc(monkeypatch, tmp_path, capsys):
    """Tras up -d ok muestra ps + espera ESC (no vuelve solo)."""
    import omc.flows as F
    from omc.flows import paso_despliegue
    p = tmp_path / "demo"
    p.mkdir()

    def _fake_run(cmd, **k):
        if cmd[-1] == "ps":
            return SimpleNamespace(returncode=0, stdout="NAME   STATUS\ndemo   Up\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(F.subprocess, "run", _fake_run)
    monkeypatch.setattr(F, "es_interactivo", lambda: True)
    monkeypatch.setattr(F, "preguntar", lambda *a, **k: "si")
    esperas = []
    monkeypatch.setattr(F, "esperar_esc_volver", lambda *a, **k: esperas.append(1) or True)
    paso_despliegue(p, 8069)
    out = capsys.readouterr().out
    assert "✓ Desplegado" in out and "Up" in out
    assert esperas == [1]


def test_paso_despliegue_fallo_espera_esc_con_hint(monkeypatch, tmp_path, capsys):
    """Tras up -d fallido muestra hints (429, puertos) y espera ESC."""
    import omc.flows as F
    from omc.flows import paso_despliegue
    p = tmp_path / "demo"
    p.mkdir()
    monkeypatch.setattr(F.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr(F, "es_interactivo", lambda: True)
    monkeypatch.setattr(F, "preguntar", lambda *a, **k: "si")
    esperas = []
    monkeypatch.setattr(F, "esperar_esc_volver", lambda *a, **k: esperas.append(1) or True)
    paso_despliegue(p, 8069)
    out = capsys.readouterr().out
    assert "⚠ Falló el despliegue" in out and "429" in out
    assert esperas == [1]


def test_paso_despliegue_sin_tty_no_espera(monkeypatch, tmp_path, capsys):
    """Sin tty (auto) no bloquea esperando tecla."""
    import omc.flows as F
    from omc.flows import paso_despliegue
    p = tmp_path / "demo"
    p.mkdir()
    monkeypatch.setattr(F.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="Up\n", stderr=""))
    monkeypatch.setattr(F, "es_interactivo", lambda: False)

    def _boom(*a, **k):
        raise AssertionError("sin tty no debe esperar tecla")

    monkeypatch.setattr(F, "esperar_esc_volver", _boom)
    paso_despliegue(p, 8069, auto=True)
    assert "✓ Desplegado" in capsys.readouterr().out


def test_elegir_proyecto_excluye_infra(monkeypatch, tmp_path, capsys):
    """El prompt solo lista entornos (prod + legado sin .env), nunca proxy."""
    from omc.flows import elegir_proyecto
    (tmp_path / "odoo").mkdir()
    (tmp_path / "odoo" / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "odoo" / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (tmp_path / "legado").mkdir()
    (tmp_path / "legado" / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "proxy").mkdir()
    (tmp_path / "proxy" / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "proxy" / ".env").write_text("ENTORNO=infraestructura\n", encoding="utf-8")
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd neutro (sin compose): solo lista
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "1")
    elegido = elegir_proyecto()
    out = capsys.readouterr().out
    assert "infraestructura" not in out and "proxy" not in out
    assert "[produccion]" in out
    assert elegido == (tmp_path / "legado").resolve()


def test_resolver_proyecto_rechaza_infra(tmp_path):
    """--proyecto /opt/proxy explícito se rechaza con mensaje claro."""
    import pytest
    from omc.flows import _resolver_proyecto
    p = tmp_path / "proxy"
    p.mkdir()
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (p / ".env").write_text("ENTORNO=infraestructura\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        _resolver_proyecto(SimpleNamespace(proyecto=str(p)))
    assert "infraestructura" in str(e.value.code)


def test_migrar_vps_todo_excluye_infra_renombrada(monkeypatch, tmp_path, capsys):
    """--todo excluye infra por ENTORNO aunque no se llame proxy."""
    import tarfile
    from omc.flows import run_migrar_vps
    base = tmp_path
    for name, entorno in (("a", "produccion"), ("gateway", "infraestructura")):
        p = base / name
        p.mkdir()
        (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        (p / ".env").write_text(f"ENTORNO={entorno}\n", encoding="utf-8")
        (p / "scripts").mkdir()
        (p / "scripts" / "backup.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (p / "backups").mkdir()
        (p / "backups" / "full_backup_midb_day1.tar.gz").write_text("x", encoding="utf-8")
        (p / "addons-bundle.json").write_text("{}", encoding="utf-8")
        (p / "addons").mkdir()
        (p / "addons" / "repos.json").write_text("[]", encoding="utf-8")
        (p / "config").mkdir()
        (p / "config" / "odoo.conf").write_text("[x]\n", encoding="utf-8")
    monkeypatch.setenv("OMC_PROJECTS", str(base))
    monkeypatch.delenv("OMC_HOME", raising=False)
    import subprocess as _sp

    def _fake(cmd, **k):
        if "psql" in cmd:
            return SimpleNamespace(returncode=0, stdout="midb\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_sp, "run", _fake)
    run_migrar_vps(SimpleNamespace(proyecto=None, todo=True, consistente=False))
    outs = list(base.glob("migrar_*.tar.gz"))
    assert len(outs) == 1
    with tarfile.open(outs[0]) as tf:
        names = tf.getnames()
        assert any("a/full_backup" in n for n in names)
        assert not any("gateway" in n for n in names)
    capsys.readouterr()


def test_checklist_titulo_plano(monkeypatch, capsys):
    """Checklist: título plano sin fondo; solo el foco se resalta."""
    import sys as _sys
    import omc.tui as T
    monkeypatch.setattr(T.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(T.sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(T.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    import os as _os
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "get_terminal_size",
                        lambda: _os.terminal_size((80, 24)))

    class _FakeTermios:
        TCSADRAIN = 1

        @staticmethod
        def tcgetattr(fd):
            return "old"

        @staticmethod
        def tcsetattr(fd, when, old):
            return None

    class _FakeTty:
        @staticmethod
        def setcbreak(fd):
            return None

    class _FakeSelect:
        @staticmethod
        def select(r, w, x, *a):
            return (r, [], [])

    monkeypatch.setitem(_sys.modules, "termios", _FakeTermios)
    monkeypatch.setitem(_sys.modules, "tty", _FakeTty)
    monkeypatch.setitem(_sys.modules, "select", _FakeSelect)
    monkeypatch.setattr(T.os, "read", lambda fd, n: b"\r")
    assert T.checklist("Elige módulos", ["m1", "m2"], marcados=["m1"]) == ["m1"]
    out = capsys.readouterr().out
    assert "\x1b[1;37;44m Elige módulos" not in out
    assert "Elige módulos" in out


def test_run_monitor_espera_esc_para_copiar(monkeypatch, tmp_path, capsys):
    """Vista del servicio: muestra token y espera ESC antes del submenú."""
    import omc.flows as F
    monkeypatch.setenv("HOME", str(tmp_path))
    _unit_monitor(tmp_path)
    monkeypatch.setattr("omc.flows.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "5")  # Volver
    esperas = []
    monkeypatch.setattr(F, "esperar_esc_volver",
                        lambda *a, **k: esperas.append(1) or True)
    run_monitor(SimpleNamespace())
    out = capsys.readouterr().out
    assert "TOK-SERVICIO-123" in out
    assert esperas == [1]


def test_run_monitor_sin_tty_no_espera(monkeypatch, tmp_path, capsys):
    """Sin tty no bloquea esperando tecla (CI, --no-input)."""
    import omc.flows as F
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("omc.flows.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(F, "es_interactivo", lambda: False)

    def _boom(*a, **k):
        raise AssertionError("sin tty no debe esperar tecla")

    monkeypatch.setattr(F, "esperar_esc_volver", _boom)
    run_monitor(SimpleNamespace())
    out = capsys.readouterr().out
    assert "token:" in out


def test_menu_dos_digitos_sin_negrita(monkeypatch, capsys):
    """Formato 01 - 11 sin paréntesis ni negrita; 00 sale."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "00")
    assert menu_principal() == "salir"
    out = capsys.readouterr().out
    assert "01 -" in out and "09 -" in out and "11 -" in out
    assert "00 - Salir" in out
    assert "\x1b[1;34m" not in out and "\x1b[1;37m" not in out


def test_menu_numero_sin_negrita_con_tty(monkeypatch):
    """Con tty: números en azul sin negrita."""
    from omc import tui
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert tui.numero("01 -") == "\033[34m01 -\033[0m"
    assert tui.texto_menu("Crear") == "\033[37mCrear\033[0m"


def test_restore_tpl_acepta_sueltos_render(monkeypatch, tmp_path):
    """restore.sh lista full_backup + *.dump + carpetas, y desempaqueta sueltos."""
    import subprocess as _sp
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    assert sin_renderizar(out) == []
    assert "backups/*.dump" in out
    assert 'db.dump' in out
    assert '[[ "$SRC" == *.dump ]]' in out
    assert "--drive" in out and "--local" in out
    r = _sp.run(["bash", "-n", "/dev/stdin"], input=out, text=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
    assert r.returncode == 0


def _restore_harness(tmp_path):
    """Proyecto fake con restore.sh renderizado + backups sueltos."""
    import subprocess as _sp
    from omc.core import render, template_text
    p = tmp_path / "proj"
    (p / "backups" / "carpeta").mkdir(parents=True)
    (p / "backups" / "carpeta" / "db.dump").write_text("DUMP", encoding="utf-8")
    (p / "backups" / "b.dump").write_text("DUMP", encoding="utf-8")
    (p / "backups" / "full_backup_a_day1.tar.gz").write_text("TGZ", encoding="utf-8")
    import subprocess as _touch
    _touch.run(["touch", "-d", "2026-01-01 00:00:01", str(p / "backups" / "carpeta" / "db.dump")])
    _touch.run(["touch", "-d", "2026-01-02 00:00:01", str(p / "backups" / "b.dump")])
    _touch.run(["touch", "-d", "2026-01-03 00:00:01",
                str(p / "backups" / "full_backup_a_day1.tar.gz")])
    (p / "scripts").mkdir(exist_ok=True)
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    (p / "scripts" / "restore.sh").write_text(out, encoding="utf-8")
    # extraer solo la función elegir_archivo del script real
    fn = _sp.run(["awk", "/^elegir_archivo\\(\\) \\{/,/^\\}$/",
                  str(p / "scripts" / "restore.sh")],
                 text=True, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                 timeout=15).stdout
    assert "CANDS" in fn
    harness = ("export REMOTE=gdrive\n" + fn
               + '\nelegir_archivo\necho "SRC=$SRC DRIVE=$DRIVE"\n')
    return p, harness


def test_restore_menu_lista_sueltos_y_carpeta(tmp_path):
    """El menú 9 ve tgz + dump suelto + carpeta (antes: ninguno local)."""
    import subprocess as _sp
    p, harness = _restore_harness(tmp_path)
    r = _sp.run(["bash", "-c", harness], input="2\n", text=True,
                stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=15, cwd=str(p))
    assert r.returncode == 0
    assert "ninguno local" not in r.stdout
    assert "SRC=backups/b.dump" in r.stdout


def test_restore_menu_carpeta_y_drive(tmp_path):
    """Carpeta elegible por número; 0 va a Drive."""
    import subprocess as _sp
    p, harness = _restore_harness(tmp_path)
    r = _sp.run(["bash", "-c", harness], input="3\n", text=True,
                stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=15, cwd=str(p))
    assert "SRC=backups/carpeta" in r.stdout
    r = _sp.run(["bash", "-c", harness], input="0\n", text=True,
                stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=15, cwd=str(p))
    assert "DRIVE=1" in r.stdout


def test_restore_menu_sin_nada_local(tmp_path):
    """Sin backups muestra (ninguno local) y 0 sigue yendo a Drive."""
    import subprocess as _sp
    from omc.core import render, template_text
    p = tmp_path / "vacio"
    (p / "backups").mkdir(parents=True)
    (p / "scripts").mkdir(exist_ok=True)
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    (p / "scripts" / "restore.sh").write_text(out, encoding="utf-8")
    fn = _sp.run(["awk", "/^elegir_archivo\\(\\) \\{/,/^\\}$/",
                  str(p / "scripts" / "restore.sh")],
                 text=True, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                 timeout=15).stdout
    harness = ("export REMOTE=gdrive\n" + fn
               + '\nelegir_archivo\necho "SRC=$SRC DRIVE=$DRIVE"\n')
    r = _sp.run(["bash", "-c", harness], input="0\n", text=True,
                stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=15, cwd=str(p))
    assert "(ninguno local)" in r.stdout
    assert "DRIVE=1" in r.stdout


def test_run_restore_pasa_db_archivo_drive(monkeypatch, tmp_path, capsys):
    """run_restore pasa --db/--archivo/--drive/--local al script."""
    import subprocess as _sp
    proj = _proj_dev(tmp_path)
    (proj / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "restore.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(_sp, "run", lambda *a, **k: vistos.append(a[0]))
    run_restore(SimpleNamespace(proyecto=str(proj), db="paintershop",
                                archivo="backups/manual", drive=False, local=False,
                                neutralizar=False, sin_neutralizar=True))
    run_restore(SimpleNamespace(proyecto=str(proj), db=None, archivo=None,
                                drive=True, local=False,
                                neutralizar=False, sin_neutralizar=False))
    assert vistos[0] == ["./scripts/restore.sh", "paintershop", "backups/manual",
                         "--sin-neutralizar"]
    assert vistos[1] == ["./scripts/restore.sh", "--drive"]
    capsys.readouterr()


def test_cli_restore_drive_local_db_archivo():
    from omc.cli import build_parser
    args = build_parser().parse_args(["restore", "--drive"])
    assert args.drive is True and args.local is False
    args = build_parser().parse_args(
        ["restore", "--db", "paintershop", "--archivo", "backups/manual", "--local"])
    assert args.db == "paintershop" and args.archivo == "backups/manual"
    assert args.local is True
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args(["restore", "--drive", "--local"])


def _validar_harness(tmp_path):
    """Extrae validar_filestore() del restore.sh real + fixtures tgz."""
    import subprocess as _sp
    from omc.core import render, template_text
    p = tmp_path / "vfs"
    (p / "src").mkdir(parents=True, exist_ok=True)
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    (p / "restore.sh").write_text(out, encoding="utf-8")
    fn = _sp.run(["awk", "/^validar_filestore\\(\\) \\{/,/^\\}$/",
                  str(p / "restore.sh")],
                 text=True, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                 timeout=15).stdout
    assert "FS_MODO" in fn
    # bueno: con prefijo filestore/<bd>/... ; anidado: <bd>/... pelado
    (p / "src" / "filestore" / "bd").mkdir(parents=True, exist_ok=True)
    (p / "src" / "filestore" / "bd" / "a.bin").write_text("A", encoding="utf-8")
    _sp.run(["tar", "czf", str(p / "bueno.tgz"), "-C", str(p / "src"),
             "filestore/bd"], check=True, timeout=15)
    (p / "src2" / "bd").mkdir(parents=True, exist_ok=True)
    (p / "src2" / "bd" / "a.bin").write_text("A", encoding="utf-8")
    _sp.run(["tar", "czf", str(p / "anidado.tgz"), "-C", str(p / "src2"),
             "bd"], check=True, timeout=15)
    _sp.run(["tar", "czf", str(p / "vacio.tgz"), "--files-from", "/dev/null"],
            check=True, timeout=15)
    (p / "corrupto.tgz").write_text("no es un tar", encoding="utf-8")
    return p, fn


def _corre_validar(tmp_path, tgz, bd="bd"):
    import subprocess as _sp
    p, fn = _validar_harness(tmp_path)
    harness = (fn + f'\nFS="{tgz}"\nBD="{bd}"\n'
               + 'if validar_filestore; then echo "RC=0 MODO=$FS_MODO"; '
               + 'else echo "RC=1"; fi\n')
    return _sp.run(["bash", "-c", harness], text=True, stdout=_sp.PIPE,
                   stderr=_sp.DEVNULL, timeout=15, cwd=str(p))


def test_validar_filestore_directo(tmp_path):
    r = _corre_validar(tmp_path, "bueno.tgz")
    assert r.returncode == 0
    assert "RC=0 MODO=directo" in r.stdout
    assert "prefijo filestore/ OK" in r.stdout


def test_validar_filestore_anidado_autoajuste(tmp_path):
    r = _corre_validar(tmp_path, "anidado.tgz")
    assert r.returncode == 0
    assert "RC=0 MODO=anidado" in r.stdout
    assert "sin prefijo" in r.stdout


def test_validar_filestore_vacio_y_corrupto_abortan(tmp_path):
    r = _corre_validar(tmp_path, "vacio.tgz")
    assert "RC=1" in r.stdout and "vacío" in r.stdout
    r = _corre_validar(tmp_path, "corrupto.tgz")
    assert "RC=1" in r.stdout and "ilegible" in r.stdout
    r = _corre_validar(tmp_path, "noexiste.tgz")
    assert "RC=1" in r.stdout and "no encontrado" in r.stdout


def _backup_harness(tmp_path):
    """Proyecto fake con backup.sh renderizado + docker stub (dump ok, rclone falla)."""
    import os as _os
    import stat as _stat
    import subprocess as _sp
    from omc.core import render, template_text
    p = tmp_path / "bproj"
    (p / "backups").mkdir(parents=True)
    (p / "scripts").mkdir(exist_ok=True)
    out = render(template_text("backup.sh.tpl"), {"PROYECTO": "demo"})
    (p / "scripts" / "backup.sh").write_text(out, encoding="utf-8")
    (p / ".env").write_text("POSTGRES_PASSWORD=odoo\n", encoding="utf-8")
    bindir = p / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "docker").write_text(
        "#!/bin/bash\n"
        # el script usa "docker compose ..." y "docker run ..." pelado
        '[ "${1:-}" = "compose" ] && shift\n'
        'case "${1:-}" in\n'
        "  exec)\n"
        '    for a in "$@"; do [ "$a" = "pg_dump" ] && { echo "DUMP-FAKE"; exit 0; }; done\n'
        "    exit 0 ;;\n"
        "  run)\n"
        '    for a in "$@"; do [ "$a" = "rclone" ] && exit 1; done\n'
        "    exit 1 ;;\n"  # alpine test -d -> sin filestore
        "  --profile)\n"
        "    exit 1 ;;\n"  # rclone copy -> falla
        "esac\n"
        "exit 0\n", encoding="utf-8")
    _os.chmod(bindir / "docker", 0o755
              | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)
    assert "sin-rclone" in out and "Backup local en" in out
    r = _sp.run(["bash", "-n", "/dev/stdin"], input=out, text=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
    assert r.returncode == 0
    return p, bindir


def test_backup_rclone_falla_local_ok_con_resumen(tmp_path):
    """Sin rclone válido: rc 1 pero resumen local visible (opción B)."""
    import os as _os
    import subprocess as _sp
    p, bindir = _backup_harness(tmp_path)
    env = dict(_os.environ, PATH=str(bindir) + _os.pathsep + _os.environ["PATH"])
    r = _sp.run(["bash", "scripts/backup.sh", "midb"], text=True,
                stdout=_sp.PIPE, stderr=_sp.STDOUT, timeout=60,
                cwd=str(p), env=env)
    assert r.returncode == 1
    assert "✓ Backup local en" in r.stdout
    assert "falló la subida" in r.stdout
    assert list((p / "backups").glob("full_backup_midb_day*.tar.gz"))


def test_backup_sin_rclone_solo_local(tmp_path):
    """--sin-rclone: rc 0 sin intentar subida."""
    import os as _os
    import subprocess as _sp
    p, bindir = _backup_harness(tmp_path)
    env = dict(_os.environ, PATH=str(bindir) + _os.pathsep + _os.environ["PATH"])
    r = _sp.run(["bash", "scripts/backup.sh", "midb", "--sin-rclone"], text=True,
                stdout=_sp.PIPE, stderr=_sp.STDOUT, timeout=60,
                cwd=str(p), env=env)
    assert r.returncode == 0
    assert "solo local" in r.stdout
    assert "Subiendo a Drive" not in r.stdout


def test_run_backup_pasa_flags_y_espera_esc(monkeypatch, tmp_path, capsys):
    """run_backup pasa --db/--sin-rclone, informa rc y espera ESC."""
    import subprocess as _sp
    proj = _proj_dev(tmp_path)
    (proj / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "backup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(_sp, "run",
                        lambda *a, **k: vistos.append(a[0]) or SimpleNamespace(returncode=1))
    import omc.flows as F
    monkeypatch.setattr(F, "es_interactivo", lambda: True)
    esperas = []
    monkeypatch.setattr(F, "esperar_esc_volver",
                        lambda *a, **k: esperas.append(1) or True)
    run_backup(SimpleNamespace(proyecto=str(proj), db="midb", sin_rclone=True,
                               local=False))
    assert vistos[0] == ["./scripts/backup.sh", "midb", "--sin-rclone"]
    out = capsys.readouterr().out
    assert "terminó con errores" in out
    assert esperas == [1]


def test_run_backup_sin_tty_no_espera(monkeypatch, tmp_path, capsys):
    """Sin tty no bloquea esperando tecla."""
    import subprocess as _sp
    import omc.flows as F
    proj = _proj_dev(tmp_path)
    (proj / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "backup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(_sp, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(F, "es_interactivo", lambda: False)

    def _boom(*a, **k):
        raise AssertionError("sin tty no debe esperar tecla")

    monkeypatch.setattr(F, "esperar_esc_volver", _boom)
    run_backup(SimpleNamespace(proyecto=str(proj)))
    assert "✓ Backup terminado" in capsys.readouterr().out


def test_cli_backup_flags():
    from omc.cli import build_parser
    args = build_parser().parse_args(["backup"])
    assert args.db is None
    args = build_parser().parse_args(["backup", "--db", "midb", "--sin-rclone"])
    assert args.db == "midb" and args.sin_rclone is True
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args(["backup", "--sin-rclone", "--local"])


def test_crear_prod_publica_gevent_remapeado(tmp_path, monkeypatch):
    """Prod standalone publica PUERTO:8069 + GEVENT:8072 (remapeo con efecto)."""
    from types import SimpleNamespace
    from omc.core import sin_renderizar
    from omc.flows import crear_proyecto
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    args = SimpleNamespace(
        entorno="produccion", version="18", nombre="tienda",
        puerto=18069, gevent_port=18073, salida=str(tmp_path / "tienda"),
        password="pgpass", admin_password="admin", no_input=True,
        addon=[], sin_addons=True, bundle=None, localizacion=None,
        deploy=False, sin_deploy=True, dominio=None, email=None,
        sin_nginx=True, staging=False, odoo_cpus=None, odoo_mem=None,
        db_cpus=None, db_mem=None, rclone_remote=None, vcpus=None,
        ram_gb=None, ide="none", proyecto=None,
    )
    crear_proyecto(args)
    comp = (tmp_path / "tienda" / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"18069:8069"' in comp and '"18073:8072"' in comp
    assert sin_renderizar(comp) == []
    env = (tmp_path / "tienda" / ".env").read_text(encoding="utf-8")
    assert "ODOO_GEVENT_PORT=18073" in env


def test_parchear_proxy_doble_ports(tmp_path):
    """El parche a proxy convierte bloque ports doble en expose."""
    from omc.compose import parchear_compose_a_proxy
    p = tmp_path / "tienda"
    p.mkdir()
    (p / "docker-compose.yml").write_text(
        "services:\n  odoo:\n    image: odoo:18\n"
        '    ports:\n      - "8070:8069"\n      - "8073:8072"\n'
        "volumes:\n  odoo-db-data:\n", encoding="utf-8")
    (p / ".env").write_text("ENTORNO=produccion\nODOO_PORT=8070\n",
                            encoding="utf-8")
    (p / "config").mkdir()
    (p / "config" / "odoo.conf").write_text("[options]\n", encoding="utf-8")
    cambios = parchear_compose_a_proxy(p, "tienda")["cambios"]
    txt = (p / "docker-compose.yml").read_text(encoding="utf-8")
    assert "expose" in txt and '"8072"' in txt
    assert "8070:8069" not in txt and "8073:8072" not in txt
    assert "container_name: tienda-odoo" in txt
    assert "expose" in cambios


def test_run_monitor_instala_servicio_persistente(monkeypatch, tmp_path, capsys):
    """Opción servicio: genera unit 0600, enable --now y conserva el token."""
    import omc.flows as F
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path / "projs"))
    monkeypatch.setenv("OMC_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("USER", "tester")
    cmds = []

    def _fake_run(cmd, **k):
        cmds.append(list(cmd))
        if cmd[:3] == ["loginctl", "show-user", "tester"]:
            return SimpleNamespace(returncode=0, stdout="Linger=yes\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("omc.flows.subprocess.run", _fake_run)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    respuestas = iter(["3", "", "", "", ""])  # persistente, puerto/host/token default
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(respuestas))
    monkeypatch.setattr(F, "puerto_en_uso", lambda p: False)
    esperas = []
    monkeypatch.setattr(F, "esperar_esc_volver",
                        lambda *a, **k: esperas.append(1) or True)
    monkeypatch.setattr(F, "ask_si_no", lambda *a, **k: False)
    run_monitor(SimpleNamespace())
    out = capsys.readouterr().out
    unit = (tmp_path / ".config" / "systemd" / "user" / "omc-monitor.service")
    assert unit.exists()
    txt = unit.read_text(encoding="utf-8")
    assert "Environment=ODOO_WEB_TOKEN=" in txt
    assert "--host 127.0.0.1 --port 8765" in txt
    assert "sobrevive reboot" in out
    assert any(c[:3] == ["systemctl", "--user", "daemon-reload"] for c in cmds)
    assert any(c[:4] == ["systemctl", "--user", "enable", "--now"] for c in cmds)
    import os as _os
    assert oct(_os.stat(unit).st_mode & 0o777) == "0o600"


def test_run_monitor_servicio_pide_linger(monkeypatch, tmp_path, capsys):
    """Sin linger lo indica y lo ejecuta con sudo si se acepta."""
    import omc.flows as F
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path / "projs"))
    monkeypatch.setenv("OMC_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("USER", "tester")
    cmds = []

    def _fake_run(cmd, **k):
        cmds.append(list(cmd))
        if cmd[:2] == ["loginctl", "show-user"]:
            return SimpleNamespace(returncode=0, stdout="Linger=no\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("omc.flows.subprocess.run", _fake_run)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    respuestas = iter(["3", "", "", "", ""])  # persistente, puerto/host/token default
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(respuestas))
    monkeypatch.setattr(F, "puerto_en_uso", lambda p: False)
    monkeypatch.setattr(F, "esperar_esc_volver", lambda *a, **k: True)
    monkeypatch.setattr(F, "ask_si_no", lambda *a, **k: True)
    run_monitor(SimpleNamespace())
    out = capsys.readouterr().out
    assert "enable-linger" in out
    assert ["sudo", "loginctl", "enable-linger", "tester"] in cmds


def test_certbot_solo_a_demanda_sin_sleep():
    """certbot no queda corriendo con up -d (profiles) ni rompe el entrypoint."""
    from omc.core import render, template_text, sin_renderizar
    for tpl, mapping in (
        ("compose-nginx-block.yml.tpl",
         {"PROYECTO": "demo", "DOMINIO": "t.com",
          "CERTBOT_EMAIL": "a@b.c", "CERTBOT_STAGING": ""}),
        ("proxy-compose.yml.tpl", {"PROYECTO": "proxy"}),
    ):
        out = render(template_text(tpl), mapping)
        assert sin_renderizar(out) == []
        assert "sleep infinity" not in out
        assert 'profiles: ["certbot"]' in out
        assert "image: certbot/certbot" in out
