"""Subcomando `omc addons`: operaciones de addons sobre un proyecto.

Uso:
  omc addons sync [--proyecto P] [--bundle F] [--odoo 18] [--yes] [--skip-install] [--no-deploy]
  omc addons add --repo server-tools [--org oca] [--odoo 18] mod1 mod2 [...]
  omc addons quitar [--proyecto P] mod1 [...]
  omc addons bundle [--proyecto P] [--archivo F] [--odoo 18]
  omc addons export-bundle [--proyecto P] [--salida F] [--force]
  omc addons pull [--proyecto P] [repo]
  omc addons status [--proyecto P]
  omc addons fix-paths [--proyecto P]
  omc addons instalar [--proyecto P] [--odoo 18]
  omc addons check-deps [--proyecto P]
  omc addons deps [--proyecto P] [--fix]
  omc addons list-catalog [--org oca]
  omc addons list-modules [--org oca] [--repo server-tools] [--odoo 18]
  omc addons catalog-add --org miorg --repo mirepo --url URL [--desc TXT]
"""
import sys
from types import SimpleNamespace

_SUBS = (
    "sync", "add", "quitar", "bundle", "export-bundle", "pull", "status",
    "fix-paths", "instalar", "check-deps", "deps",
    "list-catalog", "list-modules", "catalog-add",
)

_FLAGS_VALOR = {
    "--proyecto", "-p", "--odoo", "--branch", "--org", "--repo", "--url",
    "--bundle", "--archivo", "--salida", "--desc", "--rclone-remote",
}
_FLAGS_BOOL = {"--yes", "--skip-install", "--no-deploy", "--force", "--fix"}


def _parse(argv):
    """Mini-parser: subcomando + posicionales + --flags. Devuelve (sub, ns)."""
    argv = list(argv or [])
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in _SUBS:
        print(__doc__)
        return None, None, []
    sub = argv[0]
    resto = argv[1:]
    vals = {}
    pos = []
    i = 0
    while i < len(resto):
        t = resto[i]
        if t in _FLAGS_BOOL:
            vals[t[2:].replace("-", "_")] = True
        elif t in _FLAGS_VALOR and i + 1 < len(resto):
            vals[t.lstrip("-").replace("-", "_")] = resto[i + 1]
            i += 1
        elif t.startswith("-"):
            print(f"Flag desconocido: {t}")
            sys.exit(2)
        else:
            pos.append(t)
        i += 1
    ns = SimpleNamespace(
        proyecto=vals.get("proyecto") or vals.get("p"),
        odoo=vals.get("odoo"),
        branch=vals.get("branch"),
        org=vals.get("org"),
        repo=vals.get("repo"),
        url=vals.get("url") or "",
        bundle=vals.get("bundle", ""),
        archivo=vals.get("archivo"),
        salida=vals.get("salida"),
        desc=vals.get("desc", ""),
        modulos=[],
        yes=bool(vals.get("yes")),
        skip_install=bool(vals.get("skip_install")),
        no_deploy=bool(vals.get("no_deploy")),
        force=bool(vals.get("force")),
        fix=bool(vals.get("fix")),
    )
    return sub, ns, pos


def main(argv=None) -> int:
    from . import flows as _f

    argv = list(argv or [])
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    sub, ns, pos = _parse(argv)
    if sub is None:
        print(__doc__)
        return 2
    if sub == "add":
        # add REPO mod... | add ORG/REPO mod... | add --repo R [--org O] mod...
        if not ns.repo and pos:
            primero = pos.pop(0)
            if "/" in primero:
                ns.org, ns.repo = primero.split("/", 1)
            else:
                ns.repo = primero
        ns.modulos = pos
        if not ns.repo:
            print("Falta el repo: add --repo R [--org O] mod...")
            return 2
        _f.run_add(ns)
    elif sub == "quitar":
        ns.modulos = pos
        _f.run_quitar(ns)
    elif sub == "sync":
        _f.run_sync(ns)
    elif sub == "bundle":
        ns.archivo = ns.archivo or (pos[0] if pos else "addons-bundle.json")
        _f.run_bundle(ns)
    elif sub == "export-bundle":
        ns.salida = ns.salida or (pos[0] if pos else "addons-bundle.json")
        _f.run_export_bundle(ns)
    elif sub == "pull":
        ns.repo = ns.repo or (pos[0] if pos else None)
        _f.run_pull(ns)
    elif sub == "status":
        _f.run_status(ns)
    elif sub == "fix-paths":
        _f.run_fix_paths(ns)
    elif sub == "instalar":
        _f.solo_install(_f.find_proyecto(ns.proyecto), ver=ns.odoo)
    elif sub == "check-deps":
        _f.run_check_deps(ns)
    elif sub == "deps":
        _f.run_deps(ns)
    elif sub == "list-catalog":
        ns.org = ns.org or "all"
        _f.run_list_catalog(ns)
    elif sub == "list-modules":
        if not ns.repo and pos:
            primero = pos[0]
            if "/" in primero:
                ns.org, ns.repo = primero.split("/", 1)
            else:
                ns.repo = primero
        _f.run_list_modules(ns)
    elif sub == "catalog-add":
        if not ns.org or not ns.repo:
            print("Falta --org y --repo (y --url si el org es desconocido).")
            return 2
        _f.run_catalog_add(ns)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
