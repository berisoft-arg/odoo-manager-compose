"""Operaciones sobre repos de addons: paths, clones, bundle, export."""
import json
import shutil
import subprocess
from pathlib import Path

from .core import load_catalog, leer_env
from .github import git_auth_args, org_desde_url, org_subdir, resolve_repo
from .gitutils import git_clone, run
from .manifest import (
    indice_modulos_disco, iterar_modulos, leer_manifest,
    load_repos, save_repos, base_total,
)


def addons_path_desde_repos(proyecto: Path) -> str:
    """Construye addons_path (/mnt/...) desde repos.json. Sin symlinks."""
    paths = ["/mnt/extra-addons/custom", "/mnt/extra-addons/extras", "/mnt/extra-addons"]
    for r in sorted(load_repos(proyecto), key=lambda x: x.get("path", "")):
        p = r.get("path", "")
        if p.startswith("addons/") and not r.get("single"):
            paths.append("/mnt/extra-addons/" + p[len("addons/"):])
    vistos, out = set(), []
    for p in paths:
        if p not in vistos:
            vistos.add(p)
            out.append(p)
    return ",".join(out)


def actualizar_addons_path(proyecto: Path):
    """Reescribe la línea addons_path de config/odoo.conf según repos.json."""
    import re
    conf = Path(proyecto) / "config" / "odoo.conf"
    if not conf.exists():
        print("  ⚠ No existe config/odoo.conf, no se actualizó addons_path.")
        return
    txt = conf.read_text(encoding="utf-8")
    nuevo = "addons_path = " + addons_path_desde_repos(proyecto)
    if re.search(r"^addons_path\s*=.*$", txt, re.M):
        txt = re.sub(r"^addons_path\s*=.*$", nuevo, txt, count=1, flags=re.M)
    else:
        txt = txt.replace("[options]", "[options]\n" + nuevo, 1)
    conf.write_text(txt, encoding="utf-8")
    print(f"  ✓ odoo.conf: {nuevo}")


def limpiar_symlinks(proyecto: Path) -> int:
    """Borra symlinks legacy de addons/ que apuntan a repos (oca/adhoc/cybrosys/mates/codize/custom)."""
    addons = Path(proyecto) / "addons"
    n = 0
    if not addons.is_dir():
        return 0
    for p in addons.iterdir():
        if p.is_symlink():
            try:
                tgt = str(p.resolve().relative_to(addons.resolve()))
            except ValueError:
                continue
            if tgt.split("/")[0] in ("oca", "adhoc", "cybrosys", "mates", "codize", "custom"):
                p.unlink()
                n += 1
    return n


def avisar_depends_nuevos(proyecto: Path, nuevos: list, dest: Path):
    """Al descargar: avisa en el acto si un módulo pide otro que no está.

    (El chequeo profundo con --fix vive en `deps`; acá es alerta temprana.)
    """
    if not nuevos:
        return
    proyecto = Path(proyecto)
    idx = indice_modulos_disco(proyecto)
    core, _core_ok = base_total(proyecto)
    try:
        r = subprocess.run(["git", "-C", str(dest), "ls-tree", "-d", "--name-only", "HEAD"],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
        top = set((r.stdout or "").splitlines()
                  ) if r.returncode == 0 else set()
    except Exception:  # noqa: BLE001
        top = set()
    for m in nuevos:
        man = leer_manifest(dest / m if (dest / m).is_dir() else proyecto / "addons" / "custom" / m)
        if not man:
            continue
        for dep in man.get("depends", []) or []:
            if dep in idx or dep in core:
                continue
            mismo = dep if dep in top else None
            if mismo:
                print(f"  ⚠ {m} necesita {dep} (está en el mismo repo sin descargar). Corre: deps --fix")
            elif not core:
                print(f"  ⚠ {m} necesita {dep} (no está en disco; si es base Odoo ignóralo, si no descárgalo).")
            else:
                print(f"  ⚠ {m} necesita {dep} (no está ni en disco ni en base: descárgalo).")


def add_modules(proyecto: Path, org: str, repo: str, url: str, branch: str, modulos: list):
    """Núcleo: sparse clone + addons_path en odoo.conf (sin symlinks). Devuelve (validos, invalidos)."""
    proyecto = Path(proyecto)
    if not (url or "").strip():
        # Algún llamador no pasó URL (ej instalar_addon sin url): resolver solo por
        # catálogo exacto. Nunca adivinar: un guess erróneo clonaría el repo equivocado.
        cat = load_catalog()
        hit = next((e.get("url", "") for e in cat.get(org, [])
                    if isinstance(e, dict) and e.get("repo") == repo), "")
        if not (hit or "").strip():
            print(f"  ⚠ Sin URL para {org}/{repo} (no está en el catálogo): no se puede clonar.")
            return [], list(modulos)
        url = hit
        print(f"  URL resuelta por catálogo: {url}")
    subdir = org_subdir(org, url)
    dest = proyecto / "addons" / subdir / repo
    dest.parent.mkdir(parents=True, exist_ok=True)

    repos = load_repos(proyecto)
    entry = next((r for r in repos if r.get("path") == f"addons/{subdir}/{repo}"), None)
    if entry is None:
        entry = {"org": org, "repo": repo, "url": url, "branch": branch,
                 "path": f"addons/{subdir}/{repo}", "modules": []}
        repos.append(entry)
    if entry["branch"] != branch:
        print(f"Aviso: el repo ya estaba en rama {entry['branch']}, se mantiene. Usa --branch igual para cambiar.")
        branch = entry["branch"]

    nuevos = [m for m in modulos if m not in entry["modules"]]
    todo_repo = modulos == ["*"] or "*" in modulos
    if not dest.is_dir():
        print(f"Clonando sparse {url}@{branch} -> {dest} ...")
        try:
            git_clone(url, branch, str(dest))
        except SystemExit:
            from .gitutils import avisar_ramas
            avisar_ramas(url, branch)
            raise
    elif nuevos or todo_repo:
        # El clon puede estar viejo (el listado siempre es fresco): si el remoto
        # avanzó, el checkout viejo no materializa módulos nuevos aunque listen bien.
        pf = subprocess.run(["git"] + git_auth_args(url) + ["pull", "--ff-only"],
                            cwd=str(dest), text=True, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, timeout=180)
        if pf.returncode != 0:
            ultima = (pf.stderr or "").strip().splitlines()
            motivo = ultima[-1][:120] if ultima else "sin detalle"
            print(f"  Aviso: no pude actualizar el clon ({motivo}). Sigo con lo que hay en disco.")
    # Repo de UN SOLO módulo (manifest en raíz, ej onlyone-odoo/dolares_arg):
    # va entero en custom/ ANTES de validar nombres (sus subdirs no son módulos).
    if (dest / "__manifest__.py").exists() or (dest / "__openerp__.py").exists():
        if entry.get("single") and entry.get("path") == f"addons/custom/{repo}" and \
           (proyecto / "addons" / "custom" / repo / "__manifest__.py").exists():
            print("Nada nuevo, ya estaba el módulo único.")
            return [repo], []
        print(f"  Repo de un solo módulo: clona entero en addons/custom/{repo}.")
        mono = proyecto / "addons" / "custom" / repo
        if dest.resolve() != mono.resolve() if dest.exists() else True:
            shutil.rmtree(dest, ignore_errors=True)
        if mono.exists():
            shutil.rmtree(mono, ignore_errors=True)
        run(["git"] + git_auth_args(url) + ["clone", "--depth", "1",
             "-b", branch, url, str(mono)])
        repos[:] = [r for r in repos if r.get("path") != f"addons/{subdir}/{repo}"
                    and r.get("path") != f"addons/custom/{repo}"]
        repos.append({"org": "custom", "repo": repo, "url": url, "branch": branch,
                      "path": f"addons/custom/{repo}", "modules": [repo],
                      "single": True})
        save_repos(proyecto, repos)
        actualizar_addons_path(proyecto)
        print(f"  ✓ {repo} en custom/{repo} (visible vía addons_path)")
        return [repo], []
    if todo_repo:
        # Repo entero: checkout completo y se registran todos sus módulos
        print(f"  Repo entero: checkout completo de {org}/{repo}.")
        run(["git", "sparse-checkout", "disable"], cwd=str(dest))
        todos = sorted(m for m, _p in iterar_modulos(dest))
        nuevos_todos = [m for m in todos if m not in entry["modules"]]
        entry["modules"] = sorted(set(entry["modules"]) | set(todos))
        save_repos(proyecto, repos)
        actualizar_addons_path(proyecto)
        for m in todos:
            print(f"  ✓ {m} en {subdir}/{repo} (visible vía addons_path)")
        avisar_depends_nuevos(proyecto, nuevos_todos, dest)
        return todos, []
    if not nuevos and dest.is_dir():
        print("Nada nuevo, ya estaban todos.")
    else:
        # agregar módulos al sparse-checkout (add = no borra los anteriores)
        print(f"Agregando módulos: {' '.join(nuevos) if nuevos else '(ya estaban)'}")
        if nuevos:
            # con auth: add/reapply bajan blobs del promisor (privados fallan sin header)
            run(["git"] + git_auth_args(url) + ["sparse-checkout", "add"] + nuevos,
                cwd=str(dest))
            # reapply: asegura que el árbol se materialice (a veces add solo registra el patrón)
            run(["git"] + git_auth_args(url) + ["sparse-checkout", "reapply"],
                cwd=str(dest))
        # Validar cuáles existen realmente en esta rama (maneja módulo inexistente)
        validos = [m for m in modulos if (dest / m).is_dir()]
        invalidos = [m for m in modulos if not (dest / m).is_dir()]
        for m in invalidos:
            print(f"  ⚠ {m}: NO existe en {org}/{repo}@{branch}, omitido (no se guarda en repos.json).")
        entry["modules"] = sorted(set(entry["modules"]) | set(validos))
        save_repos(proyecto, repos)

    actualizar_addons_path(proyecto)
    validos = [m for m in modulos if (dest / m).is_dir()]
    for m in validos:
        print(f"  ✓ {m} en {subdir}/{repo} (visible vía addons_path)")
    avisar_depends_nuevos(proyecto, validos, dest)
    if validos:
        # El bundle siempre refleja lo descargado, venga de add/sync/bundle/localizar/PR
        actualizar_bundle_desde_estado(proyecto)
    return validos, [m for m in modulos if m not in validos]


def bundle_install(proyecto: Path, data: dict, default_branch: str, catalog: dict):
    """Instala todas las entradas de un bundle. Devuelve (ok, omitidos)."""
    proyecto = Path(proyecto)
    entradas = data.get("modulos", data if isinstance(data, list) else [])
    if isinstance(entradas, dict):
        entradas = [{"org": k, **v} for k, v in entradas.items()]
    total_ok, total_fail = [], []
    for e in entradas:
        if not isinstance(e, dict) or e.get("repo", "").startswith("_"):
            continue
        if not e.get("repo") or not e.get("modules"):
            continue
        branch = e.get("branch") or default_branch
        if not branch:
            raise ValueError("El bundle no trae branch y no hay --odoo/--branch ni ODOO_VERSION en .env")
        org, repo, url = resolve_repo(e.get("org", "oca"), e["repo"], e.get("url", ""), catalog)
        print(f"\n== {org}/{repo}@{branch}: {', '.join(e['modules'])} ==")
        ok, fail = add_modules(proyecto, org, repo, url, branch, e["modules"])
        total_ok += [f"{repo}/{m}" for m in ok]
        total_fail += [f"{repo}/{m}" for m in fail]
    print(f"\nBundle listo: {len(total_ok)} ok, {len(total_fail)} omitidos.")
    if total_fail:
        print(f"  Omitidos: {' '.join(total_fail)}")
    return total_ok, total_fail


def bundle_desde_estado(proyecto: Path) -> dict:
    """Genera dict bundle a partir de addons/repos.json (para clonar la instancia)."""
    proyecto = Path(proyecto)
    env = leer_env(proyecto)
    from .core import odoo_to_branch
    default_branch = odoo_to_branch(env["ODOO_VERSION"]) if env.get("ODOO_VERSION") else ""
    modulos = []
    for r in sorted(load_repos(proyecto), key=lambda x: (x.get("org", ""), x.get("repo", ""))):
        if not r.get("repo") or not r.get("modules"):
            continue
        e = {"org": r.get("org", "oca"), "repo": r["repo"], "modules": sorted(r["modules"])}
        if r.get("branch") and r["branch"] != default_branch:
            e["branch"] = r["branch"]
        if e["org"].lower() not in ("oca", "adhoc", "cybrosys", "mates", "codize") and r.get("url"):
            e["url"] = r["url"]
        modulos.append(e)
    return {
        "_comentario": f"Generado por export-bundle desde {proyecto.name} "
                       f"(Odoo {env.get('ODOO_VERSION', '?')}). Úsalo con: "
                       "omc addons bundle <este-archivo> --odoo <ver>",
        "modulos": modulos,
    }


def actualizar_bundle_desde_estado(proyecto: Path) -> bool:
    """Fusiona el estado actual (repos.json) en addons-bundle.json (lo crea si falta).

    Suma repos/módulos nuevos (con su branch/url, ej ramas de PR) sin borrar
    entradas manuales. Normaliza org "custom" al dueño real cuando la URL lo
    permite (entradas viejas de Otro). Devuelve True si algo cambió.
    """
    proyecto = Path(proyecto)
    repos = load_repos(proyecto)
    if any(r.get("org") == "custom" and org_desde_url(r.get("url", "")) not in ("", "custom")
           for r in repos):
        for r in repos:
            if r.get("org") == "custom":
                o = org_desde_url(r.get("url", ""))
                if o not in ("", "custom"):
                    r["org"] = o
        save_repos(proyecto, repos)
    dest = proyecto / "addons-bundle.json"
    estado = bundle_desde_estado(proyecto)["modulos"]
    if dest.exists():
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError:
            return False
        if isinstance(data, dict):
            actual = data.get("modulos", [])
            base = {k: v for k, v in data.items() if k != "modulos"}
            forma = "dict"
        elif isinstance(data, list):
            actual, base, forma = list(data), {}, "list"
        else:
            return False
    else:
        actual, base, forma = [], {}, "dict"
    if not estado and not actual:
        return False
    idx = {(e.get("org", ""), e.get("repo", "")): e for e in actual
           if isinstance(e, dict)}
    idx_url = {(e.get("repo", ""), e.get("url", "")): e for e in actual
               if isinstance(e, dict) and e.get("repo") and e.get("url")}
    cambio = False

    def _fundir(cur, e):
        """Une módulos/branch/url de e en cur. Devuelve True si cambió."""
        nonlocal cambio
        nuevos = sorted(set(cur.get("modules", [])) | set(e["modules"]))
        if nuevos != cur.get("modules", []):
            cur["modules"] = nuevos
            cambio = True
        for campo in ("branch", "url"):
            if e.get(campo) and cur.get(campo) != e[campo]:
                cur[campo] = e[campo]
                cambio = True
        if cur.get("org") == "custom" and e.get("org") not in ("", "custom"):
            cur["org"] = e["org"]
            cambio = True

    for e in estado:
        cur = idx.get((e["org"], e["repo"]))
        if cur is None and e.get("url"):
            # migrar entrada vieja (ej org custom) que coincide por repo+url
            cur = idx_url.get((e["repo"], e["url"]))
        if cur is None:
            actual.append(dict(e))
            cambio = True
            continue
        _fundir(cur, e)
    # dedup: mismo (repo, url) -> una sola entrada
    seen, final = {}, []
    for e in actual:
        if not isinstance(e, dict) or not e.get("repo") or not e.get("url"):
            final.append(e)
            continue
        k = (e["repo"], e["url"])
        if k in seen:
            _fundir(seen[k], e)
        else:
            seen[k] = e
            final.append(e)
    actual = final
    if not cambio:
        return False
    if forma == "dict":
        base["modulos"] = actual
        out = base
    else:
        out = actual
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return True
