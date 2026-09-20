import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omc.addonsops import add_modules


def _repo_local(tmp_path, nombre="mirepo", modulo="mimod"):
    """Repo git local con un módulo (origen file://, sin red). Devuelve (url, sha)."""
    import subprocess as _sp
    org = tmp_path / "origin"
    (org / modulo).mkdir(parents=True)
    (org / modulo / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf-8")
    _sp.run(["git", "init", "-q", "-b", "main"], cwd=str(org), check=True)
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            cwd=str(org), check=True)
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
             "uno"], cwd=str(org), check=True)
    sha = _sp.run(["git", "rev-parse", "HEAD"], cwd=str(org), capture_output=True,
                  text=True, check=True).stdout.strip()
    return f"file://{org}", sha


def test_git_sha_repo_local(tmp_path):
    from omc.gitutils import git_sha, remote_head
    from omc.gitutils import _REMOTE_HEAD_CACHE
    url, sha = _repo_local(tmp_path)
    assert git_sha(tmp_path / "origin") == sha
    assert git_sha(tmp_path / "no-existe") is None
    assert remote_head(url, "main") == sha  # file:// sin red
    _REMOTE_HEAD_CACHE.clear()


def test_add_modules_guarda_sha(tmp_path):
    from omc.manifest import load_repos
    url, sha = _repo_local(tmp_path)
    p = tmp_path / "proj"
    ok, fail = add_modules(p, "otro", "mirepo", url, "main", ["mimod"])
    assert ok == ["mimod"] and fail == []
    repos = load_repos(p)
    assert len(repos) == 1 and repos[0]["sha"] == sha


def test_pull_actualiza_sha(tmp_path):
    import subprocess as _sp
    from omc.flows import run_pull
    from omc.manifest import load_repos
    url, _sha1 = _repo_local(tmp_path)
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    from omc.addonsops import add_modules as _add
    _add(p, "otro", "mirepo", url, "main", ["mimod"])
    assert load_repos(p)[0]["sha"] == _sha1
    (tmp_path / "origin" / "mimod2").mkdir()
    (tmp_path / "origin" / "mimod2" / "__manifest__.py").write_text(
        "{'name': 'y'}", encoding="utf-8")
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            cwd=str(tmp_path / "origin"), check=True)
    _sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
             "dos"], cwd=str(tmp_path / "origin"), check=True)
    sha2 = _sp.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_path / "origin"),
                   capture_output=True, text=True, check=True).stdout.strip()
    assert sha2 != _sha1
    run_pull(SimpleNamespace(proyecto=str(p), repo=None))
    assert load_repos(p)[0]["sha"] == sha2


def test_bundle_export_incluye_sha(tmp_path):
    import json as _json
    from omc.addonsops import bundle_desde_estado
    url, sha = _repo_local(tmp_path)
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / ".env").write_text("ODOO_VERSION=18\n", encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps([
        {"org": "oca", "repo": "server-tools", "url": url, "branch": "18.0",
         "path": "addons/oca/server-tools", "modules": ["auditlog"],
         "sha": sha},
    ]), encoding="utf-8")
    data = bundle_desde_estado(p)
    assert data["modulos"][0]["sha"] == sha


def test_add_modules_sin_url_ni_catalogo_no_clona(tmp_path):
    # URL vacía + repo fuera del catálogo: no debe intentar clonar (antes:
    # `fatal: repositorio '' no existe`), devuelve todo como inválido.
    ok, fail = add_modules(tmp_path, "oca", "repo-que-no-existe-xyz", "", "17.0",
                           ["algun_modulo"])
    assert ok == []
    assert fail == ["algun_modulo"]
    assert not (tmp_path / "addons" / "oca" / "repo-que-no-existe-xyz").exists()


def _proj_repos(tmp_path, repos):
    import json as _json
    p = tmp_path / "proj"
    (p / "addons").mkdir(parents=True)
    (p / ".env").write_text("ODOO_VERSION=17\n", encoding="utf-8")
    (p / "addons" / "repos.json").write_text(_json.dumps(repos), encoding="utf-8")
    return p


def test_actualizar_crea_con_rama_pr(tmp_path):
    import json as _json
    from omc.addonsops import actualizar_bundle_desde_estado
    p = _proj_repos(tmp_path, [{"org": "custom", "repo": "web",
                      "url": "https://github.com/lubusax/web.git",
                      "branch": "17.0-mig-web_dark_theme",
                      "path": "addons/custom/web",
                      "modules": ["web_dark_mode"]}])
    assert actualizar_bundle_desde_estado(p) is True
    data = _json.loads((p / "addons-bundle.json").read_text(encoding="utf-8"))
    assert data["modulos"] == [{"org": "lubusax", "repo": "web",
                                "modules": ["web_dark_mode"],
                                "branch": "17.0-mig-web_dark_theme",
                                "url": "https://github.com/lubusax/web.git"}]
    # y el repos.json también quedó normalizado
    repos = _json.loads((p / "addons" / "repos.json").read_text(encoding="utf-8"))
    assert repos[0]["org"] == "lubusax"


def test_actualizar_fusiona_sin_borrar_manual(tmp_path):
    import json as _json
    from omc.addonsops import actualizar_bundle_desde_estado
    p = _proj_repos(tmp_path, [{"org": "oca", "repo": "server-tools",
                      "url": "https://github.com/OCA/server-tools",
                      "branch": "17.0", "path": "addons/oca/server-tools",
                      "modules": ["auditlog", "sentry"]}])
    (p / "addons-bundle.json").write_text(_json.dumps({
        "_comentario": "mío",
        "modulos": [{"org": "oca", "repo": "server-tools", "modules": ["auditlog"]}],
    }), encoding="utf-8")
    assert actualizar_bundle_desde_estado(p) is True
    data = _json.loads((p / "addons-bundle.json").read_text(encoding="utf-8"))
    assert data["_comentario"] == "mío"  # no pisa lo manual
    assert data["modulos"][0]["modules"] == ["auditlog", "sentry"]  # suma lo nuevo
    assert "branch" not in data["modulos"][0]  # rama default no se guarda
    # segunda corrida sin cambios -> False y no reescribe
    assert actualizar_bundle_desde_estado(p) is False


def test_actualizar_json_invalido_no_rompe(tmp_path):
    from omc.addonsops import actualizar_bundle_desde_estado
    p = _proj_repos(tmp_path, [])
    (p / "addons-bundle.json").write_text("{invalido", encoding="utf-8")
    assert actualizar_bundle_desde_estado(p) is False


def test_add_modules_actualiza_bundle(tmp_path):
    """add_modules deja el bundle al día (cualquier vía de descarga)."""
    import json as _json
    import subprocess as _sp
    import os as _os
    from omc.addonsops import add_modules
    rem = tmp_path / "remoto" / "r"
    mod = rem / "mi_mod"
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf-8")
    e = dict(_os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    _sp.run(["git", "init", "-qb", "17.0"], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "add", "."], cwd=str(rem), env=e, check=True)
    _sp.run(["git", "commit", "-qm", "ini"], cwd=str(rem), env=e, check=True)
    proj = tmp_path / "proj"
    (proj / "addons").mkdir(parents=True)
    (proj / ".env").write_text("ODOO_VERSION=17\n", encoding="utf-8")
    ok, fail = add_modules(proj, "custom", "r", str(rem), "17.0", ["mi_mod"])
    assert ok == ["mi_mod"] and fail == []
    data = _json.loads((proj / "addons-bundle.json").read_text(encoding="utf-8"))
    assert len(data["modulos"]) == 1
    assert data["modulos"][0]["sha"] and len(data["modulos"][0].pop("sha")) == 40
    assert data["modulos"] == [{"org": "custom", "repo": "r",
                                "modules": ["mi_mod"], "url": str(rem)}]


def test_actualizar_migra_custom_viejo_sin_duplicar(tmp_path):
    """Bundle con entrada vieja org custom + estado con dueño: migra sin duplicar."""
    import json as _json
    from omc.addonsops import actualizar_bundle_desde_estado
    p = _proj_repos(tmp_path, [{"org": "custom", "repo": "odoo-paintstore",
                      "url": "https://github.com/berisoft-arg/odoo-paintstore.git",
                      "branch": "17.0", "path": "addons/berisoft-arg/odoo-paintstore",
                      "modules": ["account_credit_card"]}])
    (p / "addons-bundle.json").write_text(_json.dumps({
        "modulos": [{"org": "custom", "repo": "odoo-paintstore",
                     "modules": ["account_credit_card"],
                     "url": "https://github.com/berisoft-arg/odoo-paintstore.git"}],
    }), encoding="utf-8")
    assert actualizar_bundle_desde_estado(p) is True
    data = _json.loads((p / "addons-bundle.json").read_text(encoding="utf-8"))
    assert len(data["modulos"]) == 1
    assert data["modulos"][0]["org"] == "berisoft-arg"
    assert data["modulos"][0]["modules"] == ["account_credit_card"]
