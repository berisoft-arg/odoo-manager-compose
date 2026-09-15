import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.flows import (
    _activar_https,
    _certonly_cmd,
    aplicar_localizacion,
    bloques_localizacion,
    ensure_dockerfile_sync,
    es_prod,
    exigir_prod,
    run_backup,
    run_deps,
    run_restore,
    run_web,
    run_rclone,
    _monitor_cmd,
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


def test_run_web_y_rclone_dev_no_ejecutan(capsys, tmp_path):
    dev = str(_proj_dev(tmp_path))
    run_web(SimpleNamespace(proyecto=dev))
    run_rclone(SimpleNamespace(proyecto=dev))
    out = capsys.readouterr().out
    assert out.count("solo de producción") == 2


def test_monitor_cmd_devuelve_lista():
    cmd = _monitor_cmd()
    assert isinstance(cmd, list) and cmd


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


def test_aplicar_guarda_repo_requirements(monkeypatch, tmp_path):
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
                 {"PROYECTO": "demo", "DOMINIO": "tienda.com"})
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


def test_restore_tpl_cubre_fuente_externa():
    from omc.core import render, template_text, sin_renderizar
    out = render(template_text("restore.sh.tpl"), {"PROYECTO": "demo"})
    assert sin_renderizar(out) == []
    assert "docker compose up -d db" in out and "pg_isready" in out
    assert "--clean --if-exists" in out
    assert 'filestore*.tar.gz' in out  # backups ajenos usan .tar.gz, no .tgz


def test_generar_odoo_conf_usa_limites_del_reparto():
    from omc.compose import generar_odoo_conf
    conf = generar_odoo_conf("produccion", {"ODOO_LIMIT_SOFT": "111",
                                            "ODOO_LIMIT_HARD": "222"})
    assert "limit_memory_soft = 111" in conf
    assert "limit_memory_hard = 222" in conf
    conf_dflt = generar_odoo_conf("produccion", {})
    assert "limit_memory_soft = 2147483648" in conf_dflt  # fallback defaults Odoo
    conf_dev = generar_odoo_conf("desarrollo", {})
    assert "limit_memory" not in conf_dev and "workers = 0" in conf_dev



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
