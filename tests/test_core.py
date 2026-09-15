import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.core import parse_seleccion, parse_addon_spec, reparto_vps, render, sin_renderizar
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
    assert r["ODOO_WORKERS"] == "9"
    assert float(r["ODOO_CPUS"]) > 1.5
    assert r["PG_SHARED_BUFFERS"] == "1352MB"  # 20% de 8GB topado al 60% del db
    assert r["PG_EFFECTIVE_CACHE"] == "4GB"    # 50% de 8GB
    r2 = reparto_vps(2, 4, con_nginx=False)
    assert r2["ODOO_WORKERS"] == "5"
    r3 = reparto_vps(2, 2, con_nginx=True)     # VPS chico: manda el tope db
    assert r3["PG_SHARED_BUFFERS"] == "307MB"


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


def test_es_url():
    assert es_url("https://github.com/x/y")
    assert es_url("git@github.com:x/y.git")
    assert not es_url("oca/server-tools")


def test_templates_render_sin_residuos():
    from omc.compose import generar_compose
    mapping_dev = {
        "PROYECTO": "test", "ODOO_VERSION": "18", "ODOO_IMAGE": "odoo:18",
        "POSTGRES_IMAGE": "postgres:16", "ODOO_PORT": "8069", "ODOO_GEVENT_PORT": "8072",
        "ADDONS_PATH": "/mnt/extra-addons", "PG_SHARED_BUFFERS": "128MB",
        "PG_EFFECTIVE_CACHE": "512MB", "PG_WORK_MEM": "8MB", "PG_MAINT_MEM": "64MB",
        "PG_MAX_CONN": "50", "DB_DEPLOY": "", "ODOO_DEPLOY": "", "ODOO_BUILD_OR_IMAGE": "image: odoo:18",
        "ODOO_PORTS": "", "NGINX_SERVICES": "", "RCLONE_SERVICE": "",
    }
    dev = generar_compose("desarrollo", mapping_dev)
    assert "{{" not in dev
    prod = generar_compose("produccion", {**mapping_dev, "ODOO_PORTS": '    expose:\n      - "8069"\n', "NGINX_SERVICES": ""})
    assert "{{" not in prod


def test_reparto_limites_memoria():
    r = reparto_vps(4, 8, con_nginx=True)
    # odoo 4.5GB / 9 workers -> soft 512MB, hard 1.5x
    assert r["ODOO_LIMIT_SOFT"] == str(512 * 1024**2)
    assert r["ODOO_LIMIT_HARD"] == str(int(512 * 1024**2 * 1.5))
    r2 = reparto_vps(2, 2, con_nginx=True)
    assert int(r2["ODOO_LIMIT_SOFT"]) >= 256 * 1024**2  # piso VPS chicos
    assert int(r2["ODOO_LIMIT_HARD"]) == int(int(r2["ODOO_LIMIT_SOFT"]) * 1.5)
