import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.core import parse_seleccion, parse_addon_spec, reparto_vps, render, sin_renderizar
from omc.core import projects_home, data_home, default_salida, asegurar_escribible
from omc.github import resolve_repo, es_url
from omc.manifest import normalizar_req


def test_parse_seleccion_numeros():
    assert parse_seleccion("1,3", ["a", "b", "c"]) == (["a", "c"], [])
    assert parse_seleccion("todo", ["a", "b"]) == (["a", "b"], [])
    assert parse_seleccion("TODO", ["a"]) == (["a"], [])
    assert parse_seleccion("1, x", ["a", "b"]) == (["a"], ["x"])


def test_parse_addon_spec():
    assert parse_addon_spec("oca/server-tools:auditlog,auto_backup") == ("oca", "server-tools", ["auditlog", "auto_backup"])
    assert parse_addon_spec("server-tools:auditlog") == ("oca", "server-tools", ["auditlog"])
    assert parse_addon_spec("adhoc/odoo-argentina:l10n_ar") == ("adhoc", "odoo-argentina", ["l10n_ar"])


def test_reparto_vps():
    r = reparto_vps(4, 8, con_nginx=True)
    assert "GB" in r["ODOO_MEM"]
    assert r["ODOO_WORKERS"] == "4"  # min(2CPU+1, tope RAM 1GB/worker)
    assert float(r["ODOO_CPUS"]) > 1.5
    assert r["PG_SHARED_BUFFERS"] == "1352MB"  # 20% de 8GB topado al 60% del db
    assert r["PG_EFFECTIVE_CACHE"] == "4GB"    # 50% de 8GB
    r2 = reparto_vps(2, 4, con_nginx=False)
    assert r2["ODOO_WORKERS"] == "2"
    r3 = reparto_vps(2, 2, con_nginx=True)     # VPS chico: manda el tope db
    assert r3["PG_SHARED_BUFFERS"] == "307MB"
    assert r3["ODOO_WORKERS"] == "1"  # 0.8GB -> un solo slot de 1GB


def test_render_sin_residuos():
    assert render("hola {{NOMBRE}}", {"NOMBRE": "chango"}) == "hola chango"
    assert sin_renderizar("a {{X}} b {{Y}}") == ["X", "Y"]
    assert sin_renderizar("sin placeholders") == []


def test_resolve_repo_url_directa():
    # URL pegada debe inferir org
    org, repo, url = resolve_repo("oca", "https://github.com/ingadhoc/account-financial-tools", "", {"oca": []})
    assert org == "adhoc"
    assert repo == "account-financial-tools"


def test_normalizar_req():
    assert normalizar_req("OpenSSL") == "pyOpenSSL"
    assert normalizar_req("OpenSSL>=1.0") == "pyOpenSSL>=1.0"
    assert normalizar_req("git+https://x") == "git+https://x"
    assert normalizar_req("Pillow>=2.0") == "Pillow>=2.0"


def test_detectar_conflictos():
    from omc.manifest import detectar_conflictos
    assert detectar_conflictos(["httplib2>=0.7", "click>=8.0"]) == []
    assert detectar_conflictos(["a==1.0"]) == []
    assert detectar_conflictos(["git+https://x/y", "-r other.txt", ""]) == []
    assert detectar_conflictos(["pysimplesoap==1.8.14", "pysimplesoap==1.8.22"]) != []
    assert detectar_conflictos(["x==1.0", "x!=1.0"]) != []
    assert detectar_conflictos(["x==1.0", "x>=2.0"]) != []
    assert detectar_conflictos(["x==2.0", "x<2.0"]) != []
    assert detectar_conflictos(["x==1.5", "x~=1.4.2"]) != []
    assert detectar_conflictos(["x==1.4.9", "x~=1.4.2"]) == []
    assert detectar_conflictos(["x==1.0", "x>=1.0", "x"]) == []
    msg = detectar_conflictos(["a==1.0", "a==2.0"])[0]
    assert "a:" in msg and "1.0" in msg and "2.0" in msg


def test_es_url():
    assert es_url("https://github.com/x/y")
    assert es_url("git@github.com:x/y.git")
    assert not es_url("oca/server-tools")


def test_templates_render_sin_residuos():
    from omc.compose import generar_compose
    mapping_dev = {
        "PROYECTO": "test", "ODOO_VERSION": "18", "ODOO_IMAGE": "odoo:18",
        "POSTGRES_IMAGE": "postgres:16",         "ODOO_PORT": "8069", "ODOO_GEVENT_PORT": "8072", "MAILPIT_PORT": "8025",
        "ADDONS_PATH": "/mnt/extra-addons", "PG_SHARED_BUFFERS": "128MB",
        "PG_EFFECTIVE_CACHE": "512MB", "PG_WORK_MEM": "8MB", "PG_MAINT_MEM": "64MB",
        "PG_MAX_CONN": "50", "DB_DEPLOY": "", "ODOO_DEPLOY": "", "ODOO_BUILD_OR_IMAGE": "image: odoo:18",
        "ODOO_PORTS": "", "NGINX_SERVICES": "", "RCLONE_SERVICE": "",
    }
    dev = generar_compose("desarrollo", mapping_dev)
    assert "{{" not in dev
    assert "mailpit:" in dev and '"8025:8025"' in dev  # buzón solo en dev
    prod = generar_compose("produccion", {**mapping_dev, "ODOO_PORTS": '    expose:\n      - "8069"\n', "NGINX_SERVICES": ""})
    assert "{{" not in prod
    assert "mailpit" not in prod


def test_reparto_limites_memoria():
    r = reparto_vps(4, 8, con_nginx=True)
    # odoo 4.5GB / (4 workers + cron + longpolling) -> soft 768MB, hard 960MB
    assert r["ODOO_LIMIT_SOFT"] == "805306368"
    assert r["ODOO_LIMIT_HARD"] == "1006632960"
    r2 = reparto_vps(2, 2, con_nginx=True)
    assert r2["ODOO_LIMIT_SOFT"] == "286331153"  # 0.8GB/3, arriba del piso
    assert r2["ODOO_LIMIT_HARD"] == str(768 * 1024**2)  # piso hard p/requests pesados


def _limpiar_env(monkeypatch, home):
    for v in ("OMC_PROJECTS", "OMC_HOME", "ODOO_CREATOR_HOME"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HOME", str(home))


def test_projects_home_orden(monkeypatch, tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    _limpiar_env(monkeypatch, h)
    assert projects_home() == Path("/opt")  # instalación nueva
    (h / "odoo-manager-compose").mkdir()
    assert projects_home() == h / "odoo-manager-compose"  # migración legada
    monkeypatch.setenv("OMC_HOME", str(tmp_path / "data"))
    assert projects_home() == tmp_path / "data"  # compat: OMC_HOME valía proyectos
    monkeypatch.setenv("OMC_PROJECTS", "/opt")
    assert projects_home() == Path("/opt")  # OMC_PROJECTS manda


def test_data_home_orden(monkeypatch, tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    _limpiar_env(monkeypatch, h)
    assert data_home() == Path("/opt/omc")  # instalación nueva
    (h / "odoo-manager-compose").mkdir()
    assert data_home() == h / "odoo-manager-compose"  # migración legada
    monkeypatch.setenv("OMC_HOME", str(tmp_path / "data"))
    assert data_home() == tmp_path / "data"


def test_default_salida(monkeypatch, tmp_path):
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    assert default_salida("mi-odoo") == (tmp_path / "mi-odoo").resolve()
    assert default_salida("mi-odoo", "rel") == (Path.cwd() / "rel").resolve()
    assert default_salida("mi-odoo", "/abs/x") == Path("/abs/x")


def test_asegurar_escribible_ok_y_falla(monkeypatch, tmp_path):
    asegurar_escribible(tmp_path / "nuevo" / "proj", "proyectos")  # crea padres, no falla
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        import pytest
        with pytest.raises(SystemExit) as e:
            asegurar_escribible(ro / "x", "proyectos")
        assert "sudo" in str(e.value.code)
    finally:
        ro.chmod(0o755)


def test_gitignore_cubre_secretos(tmp_path):
    from omc.core import template_text, sin_renderizar
    out = template_text("gitignore.tpl")
    assert sin_renderizar(out) == []
    lineas = [l.strip() for l in out.splitlines() if l.strip()]
    for req in (".env", "backups/", "letsencrypt/", "certbot-www/",
                "scripts/rclone.conf", "rclone.conf.bak"):
        assert req in lineas  # nada con tokens commiteado por default


def test_run_list_ve_proyectos_en_root(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace
    from omc.flows import run_list
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    p = tmp_path / "smoke"
    p.mkdir()
    (p / "docker-compose.yml").write_text("x", encoding="utf-8")
    (p / ".env").write_text("ENTORNO=produccion\nODOO_VERSION=18\nODOO_PORT=8070\n", encoding="utf-8")
    run_list(SimpleNamespace())
    out = capsys.readouterr().out
    assert "smoke" in out and "8070" in out


def test_color_solo_con_tty(monkeypatch):
    from omc import tui
    # sin tty: texto pelado siempre
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert tui.usa_color() is False
    assert tui.c("hola", "1") == "hola"
    assert tui.titulo("T") == "T" and tui.ok("x") == "x"
    # con tty: pinta
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert tui.usa_color() is True
    assert tui.c("hola", "1") == "\033[1mhola\033[0m"
    # NO_COLOR o dumb: pelado aunque haya tty
    monkeypatch.setenv("NO_COLOR", "1")
    assert tui.usa_color() is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert tui.usa_color() is False


def test_menu_sin_color_fuera_de_tty(monkeypatch, capsys, tmp_path):
    # menú en no-tty: byte-idéntico al histórico (sin ANSI)
    import sys as _sys
    from omc.flows import menu_principal
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert menu_principal() == "crear"  # sin tty: default sin leer input
    out = capsys.readouterr().out
    assert "\033[" not in out
    assert "=== Odoo Manager Compose" in out and " 11)" in out


def test_banner_marco_seccion_planos_sin_tty(monkeypatch):
    from omc import tui
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert tui.banner_omc("9.9.9") == "\n=== Odoo Manager Compose 9.9.9 ==="
    assert tui.marco("T", ["a", "b"], pie="P") == "T\na\nb\nP"
    assert tui.marco("T", ["a"]) == "T\na"
    assert tui.separador() == "=" * 60
    assert tui.seccion("== X ==") == "=" * 60 + "\n== X =="


def test_marco_dibuja_caja_con_tty(monkeypatch):
    from omc import tui
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    out = tui.marco("Título", ["  1) Uno"], pie="pie")
    assert "┌" in out and "┐" in out and "└" in out and "┘" in out
    assert "│" in out and "  1)" in out and "Título" in out and "pie" in out
    b = tui.banner_omc("1.0.0")
    assert "=== Odoo Manager Compose 1.0.0 ===" in b
    assert b.count("\n") >= 6  # arte + título


def test_checklist_paginacion_no_desborda(monkeypatch):
    from omc import tui
    import shutil as _shutil
    import sys as _sys
    # Simular terminal chica (10 filas) y muchos items → página limitada
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(_sys.stdin, "fileno", lambda: 0)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(_shutil, "get_terminal_size", lambda fallback=None: __import__("os").terminal_size((80, 10)))
    # Mock termios/tty para no tocar terminal real
    monkeypatch.setattr("termios.tcgetattr", lambda fd: [0] * 7)
    monkeypatch.setattr("termios.tcsetattr", lambda *a, **k: None)
    monkeypatch.setattr("tty.setcbreak", lambda fd: None)
    monkeypatch.setattr("select.select", lambda r, w, e, t=None: ([_sys.stdin], [], []))
    # Primer Enter confirma vacío
    monkeypatch.setattr("os.read", lambda fd, n: b"\r")
    captured = []
    monkeypatch.setattr(_sys.stdout, "write", lambda s: captured.append(s) or len(s))
    res = tui.checklist("Elige", [f"mod{i}" for i in range(50)])
    assert res == []
    # La caja renderizada no debe tener n+overhead líneas, sino page_size+overhead (≤7-8 en terminal 10)
    out = "".join(captured)
    # Con 10 filas, overhead ~6, page_size = max(5, 10-8)=5 → altura 5+4=9 líneas aprox, nunca 50
    assert out.count("mod0") <= 1  # solo una página visible, no todos
    assert "Pág" in out or "página" in out.lower() or "↑/↓" in out


def test_checklist_flecha_abajo_scrollea(monkeypatch):
    from omc import tui
    import shutil as _shutil
    import sys as _sys
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(_sys.stdin, "fileno", lambda: 0)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(_shutil, "get_terminal_size", lambda fallback=None: __import__("os").terminal_size((80, 10)))
    monkeypatch.setattr("termios.tcgetattr", lambda fd: [0] * 7)
    monkeypatch.setattr("termios.tcsetattr", lambda *a, **k: None)
    monkeypatch.setattr("tty.setcbreak", lambda fd: None)
    # Simular 25 ↓ y luego Enter
    seq = [b"\x1b[B"] * 25 + [b"\r"]
    it = iter(seq)
    monkeypatch.setattr("os.read", lambda fd, n: next(it, b"\r"))
    monkeypatch.setattr("select.select", lambda r, w, e, t=None: ([_sys.stdin], [], []))
    captured = []
    monkeypatch.setattr(_sys.stdout, "write", lambda s: captured.append(s) or len(s))
    res = tui.checklist("Elige", [f"mod{i}" for i in range(30)])
    # Flecha abajo 25 veces con wrap y scroll no debe colgar y debe retornar lista (vacía si no se marcó)
    assert isinstance(res, list)
